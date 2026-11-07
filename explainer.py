"""Narrated explainer videos: one calm narrator over flat vector illustrations that Claude draws scene by scene and the
HyperFrames kit brings to life (parts bob, swim, sway; things appear as the narration names them; the camera pushes in).
No characters, no paid video or picture service. A "master prompt" suggests niches and topics first.

    run_daily.bat --explainer-niches [hint]       -> work/explainer_niches.json, read by the Explainer page
    run_daily.bat --explainer job.json            job = {"topic", "niche", "format": "short" | "long", "seconds", "gates"}
A Short (vertical, 30-58 s) lands in Review like every Short; a long video (16:9, 1-10 min) is a film on the Long video
page, approved and uploaded from there. Either way nothing is posted until you approve it.

The stages are the long-film ones (longform.py): the write stage makes the script AND the drawings (art/<scene>.svg, kept
as they arrive so a stopped run resumes), so every later stage can be redone without the LLM."""

import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import lf_finish
import lf_plan
import lf_screenplay as sc
import longform as lf

WORLD = {"long": (1920, 1080), "short": (1080, 1920)}       # the drawing's canvas: the frame itself, so nothing is cropped
LENGTHS = {"short": (30, 58), "long": (60, 600)}             # seconds the app accepts
WORDS_PER_SECOND = {"short": 2.4, "long": 2.5}               # Edge, pauses included (story Shorts and films measured)
ART_BATCH, ART_MAX = 3, 24000                                # scenes drawn per call; characters a cleaned drawing may have
MOVES = ("bob", "drift", "swim", "sway", "spin", "pulse", "blink")
# Dropped from a drawing: anything that runs code, loads something, carries text, or animates on its own clock (the render
# seeks a paused timeline, so only the kit's tweens are frame-exact).
STRIP = re.compile(r"<!--.*?-->|<(script|style|foreignObject|text|animate\w*|set|image|title|desc|metadata)\b[^>]*?(?:/>|>.*?</\1\s*>)", re.S | re.I)
NO_ATTR = (re.compile(r"""\s+on\w+\s*=\s*("[^"]*"|'[^']*')""", re.I),                         # event handlers
           re.compile(r"""\s+(?:xlink:)?href\s*=\s*("(?!#)[^"]*"|'(?!#)[^']*')""", re.I),       # links out of the drawing
           re.compile(r"""\s+[\w:-]+\s*=\s*"[^"]*(?:url\(\s*['"]?(?!#)|animation|transition|@import|javascript:)[^"]*\"""", re.I))


def niches_file():
    import daily_shorts as e
    return e.WORK / "explainer_niches.json"


# ---- Prompts ----------------------------------------------------------------------------------------

def niches_prompt(n=6, used=(), hint=""):
    """The "master prompt": niches and sub-niches that suit a faceless animated explainer channel, each with topics."""
    return f"""You are a YouTube strategist who builds faceless animated explainer channels: flat 2D vector animation, one calm narrator, simple fact cards, 30-second Shorts and 3-10 minute videos.
{('The channel owner is interested in: ' + hint) if hint else 'Range widely: animals, prehistoric life, the ocean, space, the human body, history, survival, psychology, how things work.'}
Suggest {n} niches that suit this format and can grow a channel:
- each a broad niche with one specific sub-niche (e.g. 'Animals' -> 'Prehistoric sea monsters');
- "why": who watches, why they watch to the end, whether it is evergreen, how crowded it is (one or two sentences);
- 5 specific video topics in it, each a curiosity title under 10 words built on well-documented facts (e.g. 'The armored fish that didn't need teeth'), safe for all ages, easy to show with simple drawings (animals, places, objects, diagrams; no real people's faces);
- none of these topics, already made: {list(used)[-40:]}.
JSON rules: valid JSON only, no line breaks inside strings.
Reply with ONLY this JSON: [{{"niche":"...","sub_niche":"...","why":"...","topics":["..."]}}]"""


def topics_prompt(niche, used=()):
    return (f"Give 8 topics for faceless animated explainer videos (flat vector drawings, a narrator) in this niche: {niche or 'surprising animals, history and science'}. "
            "Each a curiosity title under 10 words built on well-documented facts, safe for all ages, easy to show with simple drawings, "
            f"not these: {list(used)[-40:]}. Reply with only a JSON array of strings.")


def scene_count(seconds, fmt):
    return max(3, round(seconds / 10)) if fmt == "short" else max(4, round(seconds / 14))


def word_range(seconds, fmt):
    want = seconds * WORDS_PER_SECOND[fmt]
    lo, hi = int(want * 0.75), int(want * 1.25)
    return (max(50, lo), min(150, hi)) if fmt == "short" else (lo, hi)


def script_prompt(topic, seconds, fmt, lessons=""):
    lo, hi = word_range(seconds, fmt)
    cues = sc.SHORT_CUES if fmt == "short" else sc.CUES
    kind = (f"This one is a vertical YouTube Short of about {seconds} seconds." if fmt == "short"
            else f"This one is a 16:9 YouTube video of about {round(seconds / 60, 1)} minutes.")
    ending = "and makes them want to watch it again" if fmt == "short" else "then one closing line that invites a comment"
    extra = (', {"kind":"compare","left":{"title":"Myth","items":["..."]},"right":{"title":"Reality","items":["..."]}}, '
             '{"kind":"chart","title":"...","values":[3,5,9],"labels":["a","b","c"]}') if fmt == "long" else ""
    return f"""You write faceless animated explainer videos for YouTube: one calm, curious narrator over flat 2D vector illustrations that move gently, with a fact card now and then. {kind} Original writing only.
Topic: {topic}
{lessons}
Rules:
- About {int(seconds * WORDS_PER_SECOND[fmt])} spoken words in total (never under {lo} or over {hi}), in about {scene_count(seconds, fmt)} scenes. A scene is one illustration held for 2 to 4 beats; a beat is one or two spoken sentences, under 30 words.
- Shape: the first beat is the hook (under 12 words, the most surprising true thing); then explain step by step, one idea per scene, with concrete numbers, sizes and comparisons people can picture ('as heavy as a great white shark'); one twist ('here is the strange part'); an ending that pays off the hook {ending}.
- Facts: only what you are confident is true; where experts disagree, say so ('scientists think', 'about'). List every real-world claim the script makes in "claims" and set "check": true on any you are not certain of, so a person verifies it before upload.
- The text is read aloud: spell numbers the way they are spoken ('three hundred sixty million years'), no emoji, no stage directions, no abbreviations.
- "art": what the scene's illustration shows, for the illustrator: the main subject, the setting, what moves (one or two sentences). Never text, logos or real people's faces. Keep subjects and setting consistent from scene to scene.
- "style": ONE drawing style and palette for every illustration (e.g. 'flat vector, deep teal ocean palette with warm orange accents, soft gradients, rounded shapes').
- "cam" per beat: "wide" (the whole picture), "mid" or "close" (in on the main subject). Change it every 2 or 3 beats; close for the most surprising fact.
- "cue" puts a fact card on screen while the beat plays, at most one per 20 seconds, kinds {list(cues)}: {{"kind":"stat","value":"3.5 m","label":"short label"}}, {{"kind":"list","title":"...","items":["...","..."]}}, {{"kind":"year","text":"360M years ago"}}, {{"kind":"stamp","text":"NO TEETH"}}, {{"kind":"quote","text":"...","who":"..."}}{extra}. Card text is shown, so digits are fine there.
- Narrator voice "deep" or "warm".
JSON rules: valid JSON only; inside strings use single quotes for quoted phrases (never unescaped double quotes) and no line breaks.
Reply with ONLY this JSON:
{{"title":"accurate title under 70 characters, no exaggeration","description":"YouTube description, 1-2 sentences","tags":["..."],"style":"...","narrator":{{"voice":"warm"}},
 "claims":[{{"claim":"a real-world claim the script makes","check":false}}],
 "scenes":[{{"title":"...","art":"...","beats":[{{"text":"...","cam":"wide","cue":{{...}}}}]}}]}}"""


def art_prompt(sp, scenes, world):
    w, h = world
    shape = ("a vertical canvas: stack the picture top to bottom, the main subject in the middle third, nothing important in "
             "the bottom quarter (captions go there)" if h > w else "a wide canvas: the main subject large, a little off centre")
    rows = "\n".join(f'{s["id"]} "{s["title"]}": {s["art"]}\n   narration: ' + " | ".join(f"{i}) {b['text']}" for i, b in enumerate(s["beats"], 1))
                     for s in scenes)
    return f"""You are the illustrator of an animated explainer film, "{sp['title']}". Draw one illustration per scene as an inline SVG, all in this one style: {sp['style']}.
Canvas: viewBox "0 0 {w} {h}", {shape}.
Rules:
- Flat 2D vector art like a modern animated documentary: bold simple shapes, soft gradients (in <defs>), a full-bleed background covering the whole canvas, the main subject large and recognisable, two to four supporting elements. Animals and objects anatomically right, friendly, not childish.
- No text, letters, numbers, logos or real people's faces. Do not use <text>, <image>, <script>, <style>, <foreignObject> or SMIL animation (<animate>, <set>). Colours as attributes (fill, stroke, opacity).
- Motion comes from classes on <g> groups: bob (floats up and down), drift (slides side to side), swim (glides and tilts), sway (rocks from its base: plants, tails), spin (turns slowly), pulse (breathes), blink (eyes). Give each scene 2 to 5 moving groups; the background stays still. Put a moving group's own transform on an inner group, not on the group with the class.
- data-beat="N" on a group makes it appear when the scene's beat N is spoken (N starts at 1): use it for what the narration introduces later.
- The root is <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" data-focus="x,y">, where x,y is the centre of the main subject (the camera pushes in there).
- Each SVG under 9000 characters.
Scenes:
{rows}
Reply with only the drawings, each one as a line '=== <scene id> ===' followed by its <svg>...</svg>."""


# ---- Checking what the LLM wrote ------------------------------------------------------------------------

def check_niches(raw, n=8):
    if not isinstance(raw, list):
        raise ValueError("the reply is not a JSON list")
    out = []
    for x in raw:
        if not isinstance(x, dict):
            continue
        topics = [sc.clip(t, 90) for t in (x.get("topics") or []) if isinstance(t, str) and t.strip()][:6]
        if sc.clip(x.get("niche"), 60) and topics:
            out.append({"niche": sc.clip(x.get("niche"), 60), "sub_niche": sc.clip(x.get("sub_niche"), 80), "why": sc.clip(x.get("why"), 300), "topics": topics})
    if not out:
        raise ValueError("no niche with topics in the reply")
    return out[:n]


def check_script(raw, seconds, fmt):
    """The script as the LLM wrote it -> a screenplay the long-film stages take (narrator only, no cast; claims as the first
    scene's facts). Raises ValueError with what to fix: the next try's prompt says it."""
    if not isinstance(raw, dict) or not isinstance(raw.get("scenes"), list) or not raw["scenes"]:
        raise ValueError("the reply needs a list of scenes")
    title, style = sc.clip(raw.get("title"), 100), sc.clip(raw.get("style"), 300)
    if not title or not style:
        raise ValueError('"title" and "style" must both be filled in')
    kinds = sc.SHORT_CUES if fmt == "short" else sc.CUES
    scenes = []
    for i, s in enumerate((s for s in raw["scenes"] if isinstance(s, dict)), 1):
        beats = []
        for b in (b for b in (s.get("beats") or []) if isinstance(b, dict)):
            beat = sc.clean_beat({**b, "who": "narrator"}, set())
            if not beat:
                continue
            beat.pop("emo", None), beat.pop("act", None)                    # nobody on screen to act it out
            if beat.get("cam") == "two":
                beat["cam"] = "mid"
            if beat.get("cue", {}).get("kind") not in kinds:
                beat.pop("cue", None)
            beats.append(beat)
        art = sc.clip(s.get("art"), 400)
        if beats and not art:
            raise ValueError(f"scene {i} has no 'art' description for the illustrator")
        if beats:
            scenes.append({"id": f"s{len(scenes) + 1:02d}", "title": sc.clip(s.get("title"), 60) or f"Scene {len(scenes) + 1}", "art": art,
                           "chapter": False, "room": "void", "tone": "day", "cast": [], "pos": {}, "start": {}, "beats": beats})
    if not scenes:
        raise ValueError("no scene has any beats")
    want = scene_count(seconds, fmt)
    if not want * 0.5 <= len(scenes) <= want * 1.6 + 1:
        raise ValueError(f"the script has {len(scenes)} scenes; it should have about {want}")
    voice = (raw.get("narrator") or {}).get("voice")
    sp = {"title": title, "description": sc.clip(raw.get("description"), 1000), "style": style, "cast": [],
          "tags": [sc.clip(t, 40) for t in (raw.get("tags") or []) if isinstance(t, str) and t.strip()][:15],
          "narrator": {"voice": voice if voice in ("deep", "warm") else "warm"}, "scenes": scenes}
    lo, hi = word_range(seconds, fmt)
    n = sc.spoken_words(sp)
    if not lo <= n <= hi:
        raise ValueError(f"the script has {n} spoken words; it must have {lo} to {hi}")
    if fmt == "short" and sc.words(scenes[0]["beats"][0]["text"]) > 14:
        raise ValueError("the hook (the first beat) must be under 12 words so it lands in 2 seconds")
    scenes[0]["facts"] = [{"claim": sc.clip(c.get("claim"), 160), "check": bool(c.get("check"))} for c in (raw.get("claims") or [])
                          if isinstance(c, dict) and str(c.get("claim", "")).strip()][:10]
    return sp


def parse_art(reply):
    """{scene id: raw svg} from the '=== s01 ===' blocks of an art reply (SVG is full of quotes, so it never goes in JSON)."""
    return {m.group(1): m.group(2) for m in re.finditer(r"===\s*(s\d+)\s*===\s*(<svg\b.*?</svg>)", reply, re.S | re.I)}


def clean_svg(svg, sid, world):
    """A drawing the page can hold safely and render frame-exactly: no code, no outside links, no text, no self-running
    animation; every id prefixed with the scene id (the scenes share one page); sized to the canvas. Raises ValueError."""
    start, end = svg.find("<svg"), svg.rfind("</svg>")
    if start < 0 or end < start:
        raise ValueError("no <svg> element")
    svg = STRIP.sub("", svg[start:end + 6])
    svg = re.sub(r"</?a\b[^>]*>", "", svg)
    for rx in NO_ATTR:
        svg = rx.sub("", svg)
    svg = re.sub(r'(\sid\s*=\s*")([^"]+)"', lambda m: f'{m.group(1)}{sid}-{m.group(2)}"', svg)
    svg = re.sub(r"url\(\s*#([^)\s]+)\s*\)", lambda m: f"url(#{sid}-{m.group(1)})", svg)
    svg = re.sub(r'(href\s*=\s*")#([^"]+)"', lambda m: f'{m.group(1)}#{sid}-{m.group(2)}"', svg)
    root = re.match(r"<svg\b[^>]*>", svg).group(0)
    box = re.search(r'viewBox\s*=\s*"([-\d.\s,]+)"', root)
    focus = re.search(r'data-focus\s*=\s*"([^"]*)"', root)
    w, h = world
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="{box.group(1) if box else f"0 0 {w} {h}"}" '
           f'width="{w}" height="{h}" preserveAspectRatio="xMidYMid slice"' + (f' data-focus="{focus.group(1)}"' if focus else "") + ">" + svg[len(root):])
    if len(svg) > ART_MAX:
        raise ValueError(f"the drawing is {len(svg)} characters after cleaning; keep it under 9000")
    try:
        parsed = ET.fromstring(svg)
    except ET.ParseError as err:
        raise ValueError(f"the drawing is not valid SVG ({err})") from None
    if sum(1 for _ in parsed.iter()) < 4:
        raise ValueError("the drawing is nearly empty")
    return svg


def focus_of(svg, world):
    """(x, y) the camera pushes in on: the drawing's data-focus, kept inside the canvas; the middle when it has none."""
    w, h = world
    m = re.search(r'data-focus="\s*(-?[\d.]+)\s*[, ]\s*(-?[\d.]+)', svg)
    return [round(min(w * 0.85, max(w * 0.15, float(m.group(1))))), round(min(h * 0.85, max(h * 0.15, float(m.group(2)))))] if m else [w // 2, h // 2]


def plain_art(world):
    """What a scene shows when its drawing could not be made: a quiet gradient (the narration and cards carry it)."""
    w, h = world
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}"><defs><radialGradient id="plain-g" cx="50%" cy="45%" r="75%">'
            f'<stop offset="0" stop-color="#24406b"/><stop offset="1" stop-color="#0d1630"/></radialGradient></defs><rect width="{w}" height="{h}" fill="url(#plain-g)"/></svg>')


# ---- Calls ----------------------------------------------------------------------------------------

def retrying(ask_llm, prompt, check, what, progress=print, debug_dir=None):
    """check(parsed reply) up to 3 tries, each retry saying what was wrong (as story Shorts do)."""
    problem = ""
    for attempt in range(3):
        progress(f"writing the {what}" + (f", try {attempt + 1}" if attempt else ""))
        reply = ask_llm(prompt + (f"\n\nYour previous reply could not be used ({problem}). Reply again with ONLY the valid JSON." if problem else ""))
        try:
            return check(sc.parse_json(reply))
        except (ValueError, AttributeError, TypeError, KeyError) as err:
            problem = str(err)[:200]
            if debug_dir:
                (Path(debug_dir) / f"reply_{what.replace(' ', '_')}_try{attempt + 1}.txt").write_text(reply, encoding="utf-8")
    raise ValueError(f"the LLM's {what} was unusable after 3 tries: {problem}")


def find_niches(ask_llm, used=(), hint="", progress=print):
    return retrying(ask_llm, niches_prompt(6, used, hint), check_niches, "niche ideas", progress)


def pick_topic(ask_llm, niche, used=()):
    seen = {u.strip().lower() for u in used}
    ideas = sc.parse_json(ask_llm(topics_prompt(niche, used)))
    fresh = [str(i).strip() for i in (ideas if isinstance(ideas, list) else []) if str(i).strip() and str(i).strip().lower() not in seen]
    if not fresh:
        raise RuntimeError("the LLM suggested no new topic")
    return fresh[0]


def draw_art(sp, ask_llm, folder, world, progress=print):
    """Every scene's drawing into folder/<id>.svg, a few scenes per call; scenes already drawn are skipped (resume). A batch
    that fails twice leaves those scenes plain (never stops the film). Returns the ids left plain."""
    folder.mkdir(parents=True, exist_ok=True)
    todo = [s for s in sp["scenes"] if not (folder / f"{s['id']}.svg").exists()]
    plain = []
    for k in range(0, len(todo), ART_BATCH):
        batch, problem = todo[k:k + ART_BATCH], ""
        for attempt in range(2):
            progress(f"drawing scenes {batch[0]['id']}-{batch[-1]['id']} of {len(sp['scenes'])}" + (", again" if attempt else ""))
            got = parse_art(ask_llm(art_prompt(sp, batch, world) + (f"\n\nYour previous drawings could not be used: {problem}. Draw them again." if problem else "")))
            bad = []
            for s in batch:
                try:
                    (folder / f"{s['id']}.svg").write_text(clean_svg(got[s["id"]], s["id"], world), encoding="utf-8")
                except KeyError:
                    bad.append(f"{s['id']} is missing")
                except ValueError as err:
                    bad.append(f"{s['id']}: {err}")
            batch, problem = [s for s in batch if not (folder / f"{s['id']}.svg").exists()], "; ".join(bad)[:300]
            if not batch:
                break
        plain += [s["id"] for s in batch]
    return plain


# ---- The film ---------------------------------------------------------------------------------------

def limits(fmt, seconds):
    return {"min": 20.0, "max": 58.0} if fmt == "short" else {"min": round(seconds * 0.75), "max": round(seconds * 1.3)}


def new_film(topic, fmt="long", seconds=180, niche="", gates=False):
    """A film folder for one explainer: a long one under longform/films (the Long video page lists it), a Short under
    longform/shorts like the story Shorts."""
    import story_short
    fmt = fmt if fmt in WORLD else "long"
    lo, hi = LENGTHS[fmt]
    seconds = max(lo, min(hi, int(seconds)))
    folder = (lf.FILMS if fmt == "long" else story_short.SHORTS) / f"{datetime.now():%Y%m%d-%H%M%S}-{lf.slug(topic or niche or 'explainer')}"
    folder.mkdir(parents=True)
    film = lf.Film.__new__(lf.Film)
    film.dir, film.meta = folder, {}
    film.update(kind="explainer", format=fmt, topic=topic, niche=niche, target_seconds=seconds, minutes=round(seconds / 60, 1), cast_size=0,
                gates=bool(gates) and fmt == "long", approved=[], style="explainer", limits=limits(fmt, seconds), stage="new",
                title=topic or "explainer", message="", progress=0.0, error="", created=datetime.now().isoformat(timespec="seconds"))
    return film


def write(film, ask_llm):
    """The write stage: the script (kept once made), then the drawings."""
    import daily_shorts as e
    m = film.meta
    if not film.screenplay.exists():
        topic = m.get("topic") or pick_topic(ask_llm, m.get("niche", ""), used_topics())
        film.update(topic=topic, title=topic)
        sp = retrying(ask_llm, script_prompt(topic, m["target_seconds"], m["format"], e.lessons_block(e.load_lessons(), "script")),
                      lambda raw: check_script(raw, m["target_seconds"], m["format"]), "script", film.say, film.dir)
        sp.update(topic=topic, minutes=m["minutes"], format=m["format"], kind="explainer")
        sc.save(sp, film.screenplay)
    sp = sc.load(film.screenplay)
    plain = draw_art(sp, ask_llm, film.dir / "art", WORLD[m["format"]], film.say)
    lf_plan.lines_of(sp)
    sc.save(sp, film.screenplay)
    film.update(stage="screenplay", title=sp["title"], words=sc.spoken_words(sp), progress=1.0, error="", art_plain=plain,
                message=f"script and drawings ready: {len(sp['scenes'])} scenes, {sc.spoken_words(sp)} words"
                        + (f" ({len(plain)} scene(s) without a drawing)" if plain else ""))


def attach_art(scenes, folder, world):
    """Each planned scene gets its drawing, where the camera pushes in, and the canvas size."""
    for S in scenes:
        path = Path(folder) / f"{S['id']}.svg"
        svg = path.read_text(encoding="utf-8") if path.exists() else plain_art(world)
        S.update(art=svg, focus=focus_of(svg, world), world=list(world))
    return scenes


def build(film):
    import lf_build
    m = film.meta
    tall, lim, want = m["format"] == "short", m["limits"], m["target_seconds"]
    sp = sc.load(film.screenplay)
    timings = {x["id"]: x for x in json.loads((film.dir / "voice" / "lines.json").read_text(encoding="utf-8"))}
    gap, _ = lf_plan.fit_gap(sp, timings, want * 0.9, min(lim["max"], want * 1.1), tall=tall)
    scenes = attach_art(lf_plan.plan(sp, timings, gap, tall=tall), film.dir / "art", WORLD[m["format"]])
    total = lf_build.write_project(film.dir / "project", scenes)
    if total > lim["max"]:
        raise RuntimeError(f"the voiced video runs {total:.0f} s, over the {lim['max']:.0f} s allowed: shorten the script")
    film.plan.write_text(json.dumps(scenes), encoding="utf-8")
    lf.lint_project(film)
    film.say("making the storyboard sheet", 0.6)
    sheet = lf.storyboard(film, scenes)
    film.update(stage="built", seconds=round(total, 1), gap=round(gap, 2), storyboard=bool(sheet), progress=1.0, error="",
                plan_checks=lf_finish.check_plan(scenes, sp, lim), message=f"project built: {len(scenes)} scenes, {int(total // 60)}:{int(total % 60):02d}")


def used_topics():
    import daily_shorts as e
    used = e.HISTORY.read_text(encoding="utf-8").splitlines() if e.HISTORY.exists() else []
    return used + [f.meta.get("topic", "") for f in lf.list_films()]


def run_short(film, settings, ask_llm, quality="looks"):
    """A vertical explainer from where it stopped, into Review (story_short.finish writes the Review pair)."""
    import story_short
    steps = {"new": lambda: write(film, ask_llm), "screenplay": lambda: lf.voice_film(film, float(settings.get("voice_rate", 1.05)), "edge"),
             "voiced": lambda: build(film), "built": lambda: lf.render_film(film, quality), "rendered": lambda: story_short.finish(film, settings)}
    try:
        while film.meta["stage"] in steps:
            steps[film.meta["stage"]]()
    except Exception as err:
        film.update(error=f"{type(err).__name__}: {err}", message="stopped: " + str(err)[:200])
        raise


def is_long(args):
    """True when the job is a long film: it takes the film lock (in run_all), not the Shorts run lock."""
    if "--resume" in args:
        return (lf.FILMS / args[args.index("--resume") + 1]).exists()
    return bool(args) and args[0].lower().endswith(".json") and json.loads(Path(args[0]).read_text(encoding="utf-8")).get("format") == "long"


def main(args):
    """--explainer job.json [--draft] | --explainer --resume <folder> | --explainer --niches [hint words]"""
    import daily_shorts as e
    import story_short
    s, M = e.load_settings(), e.load_mpt()
    ask_llm = lambda prompt: e.ask(M.llm, prompt)                         # noqa: E731
    if args and args[0] == "--niches":
        try:
            found = find_niches(ask_llm, used_topics(), " ".join(args[1:]).strip()[:200])
        except Exception as err:
            print(f"NICHES FAILED: {type(err).__name__}: {err}")
            return 1
        niches_file().parent.mkdir(exist_ok=True)
        niches_file().write_text(json.dumps({"made": datetime.now().isoformat(timespec="seconds"), "niches": found}, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"NICHES READY: {len(found)} niches")
        return 0
    words = [a for a in args if a != "--draft"]
    if "--resume" in words:
        name = words[words.index("--resume") + 1]
        film = lf.Film(next(p for p in (lf.FILMS / name, story_short.SHORTS / name) if p.exists()))
    else:
        job = json.loads(Path(words[0]).read_text(encoding="utf-8")) if words and words[0].lower().endswith(".json") else {"topic": " ".join(words)}
        fmt = job.get("format") if job.get("format") in WORLD else "short"
        film = new_film(str(job.get("topic") or "").strip()[:200], fmt, int(job.get("seconds") or (45 if fmt == "short" else 180)),
                        str(job.get("niche") or "").strip()[:120], bool(job.get("gates")))
    print(f"Explainer ({film.meta['format']}): {film.meta['topic'] or film.meta['niche'] or 'a new topic'} ({film.dir.name})")
    quality = "draft" if "--draft" in args else "looks"
    try:
        if film.meta["format"] == "long":
            lf.run_all(film, s, ask_llm, quality)
        else:
            run_short(film, s, ask_llm, quality)
    except Exception as err:
        print(f"EXPLAINER FAILED: {type(err).__name__}: {err}")
        return 1
    print(f"EXPLAINER {film.meta['stage'].upper()}: {film.meta.get('title')} ({film.dir})")
    return 0


# ---- Self-test (no LLM, no files outside a temp folder) ------------------------------------------------------

def self_test():
    import tempfile
    beat = {"text": "This armored fish ruled the seas three hundred sixty million years ago.", "cam": "wide"}       # 12 words
    raw = {"title": "The fish with no teeth", "style": "flat vector, teal ocean", "narrator": {"voice": "deep"}, "tags": ["fish", 2],
           "claims": [{"claim": "Dunkleosteus lived about 360 million years ago", "check": True}, {"claim": ""}],
           "scenes": [{"title": f"S{i}", "art": "A huge armored fish gliding over a reef",
                       "beats": [dict(beat, act="point", emo="happy", cue={"kind": "stat", "value": "3.5 m", "label": "long"}), dict(beat, cam="two"),
                                 dict(beat, cue={"kind": "chart", "values": [1, 2]})]} for i in range(4)]}
    sp = check_script(json.loads(json.dumps(raw)), 55, "short")                                        # 144 words
    b0, b1, b2 = sp["scenes"][0]["beats"]
    assert sp["cast"] == [] and sp["narrator"]["voice"] == "deep" and sp["tags"] == ["fish"] and [s["id"] for s in sp["scenes"]] == ["s01", "s02", "s03", "s04"]
    assert b0["who"] == "narrator" and "act" not in b0 and "emo" not in b0 and b0["cue"]["kind"] == "stat" and b1["cam"] == "mid" and "cue" not in b2
    assert sp["scenes"][0]["facts"] == [{"claim": "Dunkleosteus lived about 360 million years ago", "check": True}] and sc.claims(sp)[0][3] is True
    long_beat = dict(beat, text="So here is the thing: " + beat["text"])                               # 17 words: too long for a hook
    for bad, why in ((dict(raw, scenes=raw["scenes"][:1]), "1 scenes"), (dict(raw, style=""), '"style"'), ({"scenes": []}, "list of scenes"),
                     (dict(raw, scenes=[dict(s, art="") for s in raw["scenes"]]), "'art'"),
                     (dict(raw, scenes=[dict(raw["scenes"][0], beats=[long_beat, beat, beat])] + raw["scenes"][1:]), "hook"),
                     (raw, "should have about 21")):                     # 4 scenes are far too few for 5 minutes
        try:
            check_script(json.loads(json.dumps(bad)), 300 if bad is raw else 55, "long" if bad is raw else "short")
            raise AssertionError(f"accepted a bad script ({why})")
        except ValueError as err:
            assert why in str(err), err
    # the drawings: blocks out of a reply, and everything unsafe or self-running taken out
    reply = ('Here:\n=== s01 ===\n<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1920" data-focus="540,900" onload="x()">'
             '<defs><linearGradient id="g1"><stop offset="0" stop-color="#123"/></linearGradient></defs><style>*{animation:spin 1s}</style>'
             '<script>alert(1)</script><rect width="1080" height="1920" fill="url(#g1)"/><g class="swim" data-beat="2"><ellipse cx="540" cy="900" rx="300" ry="120" fill="#e85"/>'
             '<use xlink:href="#g1"/><image href="http://x/y.png"/></g><animate attributeName="x"/><text>HI</text><a href="https://x">'
             '<circle cx="1" cy="1" r="1" fill="url(https://evil/x)"/></a></svg>\n=== s02 ===\n<svg viewBox="0 0 1080 1920"><rect/></svg>')
    got = parse_art(reply)
    assert sorted(got) == ["s01", "s02"]
    svg = clean_svg(got["s01"], "s01", WORLD["short"])
    for gone in ("onload", "<style", "<script", "<image", "<animate", "<text", "https://", "<a "):
        assert gone not in svg, gone
    assert 'id="s01-g1"' in svg and 'fill="url(#s01-g1)"' in svg and 'xlink:href="#s01-g1"' in svg and 'class="swim" data-beat="2"' in svg
    assert 'width="1080" height="1920"' in svg and focus_of(svg, WORLD["short"]) == [540, 900] and focus_of(plain_art((1920, 1080)), (1920, 1080)) == [960, 540]
    for bad, why in (("<svg><rect></svg>", "not valid SVG"), ("no drawing here", "no <svg>"), ("<svg viewBox='0 0 9 9'><rect/></svg>", "nearly empty")):
        try:
            clean_svg(bad, "s09", WORLD["long"])
            raise AssertionError(f"accepted a bad drawing ({why})")
        except ValueError as err:
            assert why in str(err), err
    with tempfile.TemporaryDirectory() as tmp:          # s02 comes back too small, its retry is good; s03 never comes and stays plain
        replies = iter([reply, "=== s02 ===\n" + got["s01"], "nothing", "nothing"])
        sp3 = {"title": "t", "style": "s", "scenes": [dict(sp["scenes"][i], id=f"s0{i + 1}") for i in range(3)]}
        assert draw_art(sp3, lambda p: next(replies), Path(tmp), WORLD["short"], lambda m: None) == ["s03"]
        assert 'id="s02-g1"' in (Path(tmp) / "s02.svg").read_text(encoding="utf-8")
    # an empty cast plans, wide and tall, with the drawing attached and the camera told where to push in
    lf_plan.lines_of(sp)
    tm = {b["line"]: {"dur": 3.0, "mouth": [], "sentences": [{"text": b["text"], "start": 0.0, "end": 2.8}]} for s in sp["scenes"] for b in s["beats"]}
    for fmt in ("short", "long"):
        scenes = attach_art(lf_plan.plan(sp, tm, tall=fmt == "short"), Path("no-such-folder"), WORLD[fmt])
        assert len(scenes) == 4 and all(S["art"].startswith("<svg") and S["world"] == list(WORLD[fmt]) and not S["cast"] for S in scenes)
        assert any(e["do"] == "shot" for S in scenes for e in S["events"]) and any(e["do"] == "card" for S in scenes for e in S["events"])
    assert check_niches([{"niche": "Animals", "sub_niche": "Prehistoric fish", "topics": ["The armored fish", 3]}, {"niche": "x"}]) == \
        [{"niche": "Animals", "sub_niche": "Prehistoric fish", "why": "", "topics": ["The armored fish"]}]
    assert limits("long", 180) == {"min": 135, "max": 234} and word_range(45, "short") == (81, 135)
    print("explainer self-test passed")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
