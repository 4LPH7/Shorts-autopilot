"""The writing half of the long-video pipeline: ask the LLM for a concept, a cast of 4-5 characters and a scene outline,
then for the beats of each scene; check everything against the vocabulary the animation kit understands and repair it.

A beat is one spoken line plus its stage directions:
    {"who": "narrator" | <cast id>, "text": "...", "emo": "happy", "act": "point", "cam": "close",
     "cue": {"kind": "stat", "value": "$85", "label": "Google at its IPO"}}
Nothing here touches the disk except save()/load(); the LLM is passed in as a function (prompt -> reply)."""

import json
import re
from pathlib import Path

ROOMS = ("living", "bedroom", "hospital", "classroom", "street", "office", "kitchen", "park", "cafe", "stage", "void")
TONES = ("day", "evening", "night", "dawn")
EMOS = ("neutral", "happy", "sad", "angry", "surprised", "scared", "thinking")
POSES = ("open", "point", "shrug", "think", "wave", "up", "hold", "clap", "hug", "fist")
MOVES = ("hop", "nod", "no", "shake", "sit", "stand", "walk:left", "walk:center", "walk:right")
SHOTS = ("wide", "mid", "close", "two")
CUES = ("title", "stat", "list", "chart", "compare", "stamp", "year", "quote")
SHORT_CUES = ("stat", "list", "stamp", "year", "quote")      # the cards that fit a vertical Short's narrow frame
SHORT_WORDS = (60, 150)                                      # spoken words in a story Short (20-60 seconds)
STARTS = ("stand", "sit", "lie")
SLOTS = {"far-left": 330, "left": 600, "center": 960, "right": 1320, "far-right": 1590}
VOICE_TYPES = ("male-deep", "male-warm", "male-young", "female-warm", "female-bright", "child", "elder-male", "elder-female")
WORDS_PER_MINUTE = 150           # spoken words per finished minute (Edge speaks about 3 a second), pauses and card moments included

LOOK_HELP = ('look = {"skin":0-4, "hair":"short|spiky|long|bun|curly|cap|elder|none", "hair_color":"#hex", '
             '"top":"tee|suit|dress|hoodie|coat|apron|uniform", "color":"#hex outfit", "pants":"#hex", "acc":"glasses,beard,hat (comma list or empty)", '
             '"h":height 1.0 adult / 0.88 teen / 0.62 child, "hs":head size 1.0 adult / 1.3 child}')


def outline_prompt(topic, minutes, cast_size, lessons=""):
    return f"""You are the head writer of a hit YouTube channel of animated "What if..." story-explainers: a {minutes}-minute film told with 2D cartoon characters, a narrator and real dialogue, where every complication teaches something true.
Topic: {topic}
Runtime: {minutes} minutes, about {int(minutes * WORDS_PER_MINUTE)} spoken words in total.
{lessons}
Write the concept, the cast and the scene outline. Rules:
- A cast of exactly {cast_size} characters with different personalities and voices. One is the protagonist (id "you", the viewer's stand-in, addressed as "you" by the narrator and by name by the others). Each other character must matter to the story.
- Structure: a cold open that hooks in the first 20 seconds; setup; three escalating complications, each exploring ONE real mechanism (science, economics, psychology, history) with concrete numbers; a midpoint twist; an emotional turn; a resolution that calls back to the opening.
- Facts: only things you are confident are true. Anything illustrative is framed as "imagine" or "roughly".
- 14 to 18 scenes. Each has a room, a time of day, who is in it, where they stand and a one-line purpose. A scene is 20 to 45 seconds. Give each scene a "words" budget so the budgets add up to the total.
- Brief: the single question the film answers, an original angle, a one-sentence takeaway, three different accurate title options (no exaggerated claims) and the opening image. Per scene list the real-world claims it makes in "facts" (at most 4) and set "check": true on any you are not certain of, so a person verifies them before the film is approved.
- "chapter": true on at most 4 scenes (a title card opens them).
Allowed values: room {list(ROOMS)}; tone {list(TONES)}; start {list(STARTS)} ("lie" means sitting up in bed: only in a hospital or bedroom scene, one person); position {list(SLOTS)}; voice {list(VOICE_TYPES)} (every character a different voice); narrator voice "deep" or "warm".
{LOOK_HELP}
JSON rules: valid JSON only; inside strings use single quotes for quoted phrases (never unescaped double quotes) and no line breaks.
Reply with ONLY this JSON:
{{"title":"...", "logline":"...", "brief":{{"question":"the one question the film answers", "angle":"what makes this treatment original", "takeaway":"one sentence", "titles":["accurate option 1","option 2","option 3"], "first_frame":"the opening image"}},
 "description":"YouTube description, 3-4 sentences", "tags":["..."], "narrator":{{"voice":"deep"}},
 "cast":[{{"id":"you","name":"...","role":"...","personality":"...","voice":"male-warm","look":{{...}}}}],
 "scenes":[{{"id":"s01","title":"...","chapter":false,"room":"hospital","tone":"night","cast":["you"],"pos":{{"you":"center"}},"start":{{"you":"lie"}},"purpose":"...","words":80,"facts":[{{"claim":"a real-world claim this scene makes","check":false}}]}}]}}"""


def beats_prompt(sp, ids, done_tail):
    cast = "\n".join(f'- {c["id"]} ({c["name"]}): {c["role"]}; {c.get("personality", "")}' for c in sp["cast"])
    rows = "\n".join(f'{s["id"]} [{s["room"]}, {", ".join(s["cast"])}] ({s["words"]} words): {s["purpose"]}' for s in sp["scenes"])
    mine = ", ".join(ids)
    return f"""Write the script for scenes {mine} of the animated film "{sp['title']}" ({sp['logline']}).
Cast:
{cast}
Narrator: speaks to "you", explains, bridges. Full outline (the scenes you write are {mine}):
{rows}
{('The last beats already written: ' + done_tail) if done_tail else 'This is the start of the film: open with a hook in the first sentence.'}
Rules:
- Each beat is one spoken line. "who" is "narrator" or a cast id present in that scene. Characters speak short natural dialogue (under 22 words); the narrator carries the explanation. Hit each scene's word budget (+-15%).
- The text is read aloud by a voice: spell numbers the way they are spoken ("eighty-five dollars", "nineteen ninety-nine"), no emoji, no stage directions, no abbreviations.
- Stage directions in separate fields: "emo" {list(EMOS)}; "act" one of {list(POSES + MOVES)} (omit if nothing happens); "cam" one of {list(SHOTS)} (change the shot at most every 6-8 seconds, close for emotion).
- "cue" puts an explanation card on screen while the line plays, at most one per 25 seconds, only where it helps: {{"kind":"stat","value":"$85","label":"short label"}}, {{"kind":"list","title":"...","items":["...","..."]}}, {{"kind":"chart","title":"...","values":[3,5,9],"labels":["a","b","c"]}}, {{"kind":"compare","left":{{"title":"Myth","items":["..."]}},"right":{{"title":"Reality","items":["..."]}}}}, {{"kind":"stamp","text":"BUSTED"}}, {{"kind":"year","text":"1999"}}, {{"kind":"quote","text":"...","who":"..."}}, {{"kind":"title","text":"Chapter title","sub":"optional"}}. Card text is shown, so digits are fine there.
- Only facts you are confident are true. Every scene ends on a beat that pulls the viewer into the next.
- JSON rules: valid JSON only; inside strings use single quotes for quoted phrases (never unescaped double quotes) and no line breaks.
Reply with ONLY this JSON: {{"scenes":[{{"id":"{ids[0]}","beats":[{{"who":"narrator","text":"...","emo":"neutral","act":"point","cam":"wide","cue":{{...}}}}]}}]}}"""


def ideas_prompt(n, used=()):
    return (f'Give {n} ideas for animated "What if..." story-explainer films, each a single question that opens a rich chain of '
            'consequences (e.g. "What if you were reborn with all your memories?", "What if everyone could see each other\'s credit score?"). '
            f'Concrete, emotional, explainable with real science, economics or psychology. Not these: {list(used)[-30:]}. Reply with only a JSON array of strings.')


STORY_KINDS = ("true", "whatif")                 # a true story told with a twist, or a "What if...?" chain of consequences
SHORT_RULES = {
    "true": ("animated true stories: a narrator tells ONE real, surprising story",
             "a hook the viewer hears in the first 2 seconds (the first beat: the narrator, under 12 words, the most surprising true fact, "
             "e.g. 'A man sold the Eiffel Tower. Twice.'); the setup in a few quick lines; ONE escalation; a twist; a last line that pays off "
             "the hook (a punchline or a callback, not a question to the viewer).",
             "Real people may appear as simple cartoon characters; nobody invented is presented as real.",
             "Where accounts disagree, say so in the script ('the story goes') or leave it out."),
    "whatif": ("animated 'What if...?' Shorts: a narrator walks the viewer through ONE imagined situation and what would really follow",
               "a hook the viewer hears in the first 2 seconds (the first beat: the narrator asks the what-if in under 12 words, e.g. 'What if you "
               "never needed to sleep again?'); short sentences, one idea each; quick consequences that build, each from a real mechanism "
               "(science, money, psychology); one twist nobody expects; the LAST beat is the narrator asking the viewer a question that invites "
               "a comment, ending with '?'.",
               "The protagonist is the viewer: a character with id 'you', addressed as 'you'.",
               "Everything imagined is said as imagined ('you would', 'imagine'); only the real facts it leans on are claims."),
}


def short_prompt(topic, seconds=30, lessons="", kind="true"):
    """One call for a whole story Short: the cast, 1-3 scenes and every beat (a Short is too small to outline first).
    kind: "true" (a real story, payoff ending) or "whatif" (an imagined situation, question ending)."""
    what, shape, people, unsure = SHORT_RULES[kind if kind in SHORT_RULES else "true"]
    words = int(seconds * 2.4)                       # Edge speaks about 2.4 words a second with the pauses (the first sample: 99 words, 41 s)
    return f"""You write vertical YouTube Shorts for a channel of {what} in about {seconds} seconds while 1 to 3 flat cartoon characters act it out. Original writing only: never copy another channel's script, characters or catchphrases.
{'Story' if kind != 'whatif' else 'What if'}: {topic}
{lessons}
Rules:
- About {words} spoken words in total, never under {SHORT_WORDS[0]} or over {SHORT_WORDS[1]}.
- The shape: {shape}
- The narrator carries the story. Characters say short lines (under 10 words) at the dramatic moments. {people}
- Facts: only what you are confident is true. List every real-world claim the script makes in "claims" (names, dates, numbers, what happened) and set "check": true on any you are not certain of, so a person verifies it before upload. {unsure}
- 1 to 3 scenes, each in one room, with 1 to 3 characters standing in it. Each scene has at least 2 beats.
- The text is read aloud: spell numbers the way they are spoken ('nineteen twenty-five'), no emoji, no stage directions, no abbreviations.
- Stage directions in separate fields: "emo" {list(EMOS)}; "act" one of {list(POSES + MOVES)}; "cam" one of {list(SHOTS)}: change the shot every 2 to 4 seconds, close for the twist.
- "cue" puts a card on screen while the line plays, at most 3 in the Short: {{"kind":"year","text":"1925"}}, {{"kind":"stat","value":"7,000 tons","label":"short label"}}, {{"kind":"stamp","text":"SOLD"}}, {{"kind":"quote","text":"...","who":"..."}}, {{"kind":"list","title":"...","items":["...","..."]}}. Card text is shown, so digits are fine there.
Allowed values: room {list(ROOMS)}; tone {list(TONES)}; start "stand" or "sit"; position {list(SLOTS)}; voice {list(VOICE_TYPES)} (every character a different voice); narrator voice "deep" or "warm".
{LOOK_HELP}
JSON rules: valid JSON only; inside strings use single quotes for quoted phrases (never unescaped double quotes) and no line breaks.
Reply with ONLY this JSON:
{{"title":"accurate title under 70 characters, no exaggeration", "description":"YouTube description, 1-2 sentences", "tags":["..."], "narrator":{{"voice":"deep"}},
 "cast":[{{"id":"lustig","name":"...","role":"...","personality":"...","voice":"male-warm","look":{{...}}}}],
 "claims":[{{"claim":"a real-world claim the script makes","check":false}}],
 "scenes":[{{"id":"s01","title":"...","room":"office","tone":"day","cast":["lustig"],"pos":{{"lustig":"center"}},"start":{{"lustig":"stand"}},
   "beats":[{{"who":"narrator","text":"...","emo":"surprised","act":"point","cam":"wide","cue":{{...}}}}]}}]}}"""


def story_ideas_prompt(n, used=(), kind="true"):
    if kind == "whatif":
        return (f'Give {n} ideas for 30-second animated "What if...?" Shorts, each a single question about the viewer that opens a surprising '
                "chain of real consequences (e.g. 'What if you never needed to sleep again?', 'What if the Moon disappeared tonight?'). "
                f"Safe for all ages, explainable with real science, money or psychology, not these: {list(used)[-30:]}. "
                "Reply with only a JSON array of strings.")
    return (f"Give {n} ideas for 30-second animated Shorts that each tell ONE true, surprising, little-known story from history, science or "
            "business with a twist at the end (e.g. 'The man who sold the Eiffel Tower twice', 'The general who lost a battle to his own army'). "
            f"Well documented, safe for all ages, no living private people, not these: {list(used)[-30:]}. Reply with only a JSON array of strings.")


# ---- Parsing and checking ---------------------------------------------------------------------

def parse_json(reply):
    """The first JSON object or array in an LLM reply (it may be wrapped in prose or a code fence)."""
    text = re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.M)
    for opener, closer in (("{", "}"), ("[", "]")):
        a, b = text.find(opener), text.rfind(closer)
        if a != -1 and b > a:
            try:
                return json.loads(text[a:b + 1])
            except ValueError:
                continue
    raise ValueError("the reply holds no JSON")


def words(text):
    return len(re.findall(r"[\w'’$%-]+", text))


def clip(text, n):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def clamp_cue(cue):
    """An explanation card the layout can hold: short texts, few items, numbers only in a chart. None if unusable."""
    k = cue.get("kind")
    if k == "stat":
        out = {"value": clip(cue.get("value"), 12), "label": clip(cue.get("label"), 44)}
        return out if out["value"] else None
    if k == "list":
        items = [clip(i, 40) for i in (cue.get("items") or []) if str(i).strip()][:5]
        return {"title": clip(cue.get("title"), 36), "items": items} if items else None
    if k == "chart":
        vals = []
        for v in (cue.get("values") or [])[:10]:
            try:
                vals.append(float(v))
            except (TypeError, ValueError):
                return None
        if len(vals) < 2:
            return None
        return {"title": clip(cue.get("title"), 44), "values": vals, "labels": [clip(x, 8) for x in (cue.get("labels") or [])[: len(vals)]]}
    if k == "compare":
        side = lambda s: {"title": clip((s or {}).get("title"), 22), "items": [clip(i, 34) for i in ((s or {}).get("items") or [])[:3]]}   # noqa: E731
        left, right = side(cue.get("left")), side(cue.get("right"))
        return {"left": left, "right": right} if left["items"] and right["items"] else None
    if k in ("stamp", "year", "title", "quote"):
        limit = {"stamp": 16, "year": 10, "title": 40, "quote": 140}[k]
        out = {"text": clip(cue.get("text"), limit)}
        if k == "title" and cue.get("sub"):
            out["sub"] = clip(cue["sub"], 50)
        if k == "quote" and cue.get("who"):
            out["who"] = clip(cue["who"], 30)
        return out if out["text"] else None
    return None


def clean_beat(b, cast_ids):
    who = b.get("who") if b.get("who") in cast_ids or b.get("who") == "narrator" else "narrator"
    out = {"who": who, "text": re.sub(r"\s+", " ", str(b.get("text", ""))).strip()}
    if b.get("emo") in EMOS:
        out["emo"] = b["emo"]
    if b.get("act") in POSES + MOVES:
        out["act"] = b["act"]
    if b.get("cam") in SHOTS:
        out["cam"] = b["cam"]
    cue = b.get("cue")
    cue = clamp_cue(cue) if isinstance(cue, dict) and cue.get("kind") in CUES else None
    if cue:
        out["cue"] = {"kind": b["cue"]["kind"], **cue}
    return out if out["text"] else None


def check_outline(sp, cast=(3, 6)):
    """Fix what can be fixed, raise ValueError for what cannot. Returns the same dict. cast: how many characters may be in it."""
    if not (cast[0] <= len(sp.get("cast", [])) <= cast[1]) or not sp.get("scenes"):
        raise ValueError(f"the outline needs a cast of {cast[0]}-{cast[1]} and a list of scenes")
    ids = [c["id"] for c in sp["cast"]]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate character ids")
    used = set()
    for c in sp["cast"]:
        v = c.get("voice")
        if v not in VOICE_TYPES or v in used:
            v = next((t for t in VOICE_TYPES if t not in used), VOICE_TYPES[0])
        c["voice"] = v
        used.add(v)
        c["look"] = {**{"skin": 1, "hair": "short", "top": "tee", "color": "#4a7bd6", "h": 1.0}, **(c.get("look") or {})}
        c.setdefault("personality", "")
        c.setdefault("role", "")
        c.setdefault("name", c["id"].title())
    for i, s in enumerate(sp["scenes"], 1):
        s["id"] = f"s{i:02d}"
        s["room"] = s.get("room") if s.get("room") in ROOMS else "living"
        s["tone"] = s.get("tone") if s.get("tone") in TONES else "day"
        s["cast"] = [c for c in s.get("cast", []) if c in ids] or ids[:1]
        s["pos"] = {c: (s.get("pos", {}).get(c) if s.get("pos", {}).get(c) in SLOTS else list(SLOTS)[1 + k * 2 % 4]) for k, c in enumerate(s["cast"])}
        s["start"] = {c: (s.get("start", {}).get(c) if s.get("start", {}).get(c) in STARTS else "stand") for c in s["cast"]}
        s["words"] = int(s.get("words") or 80)
        s["facts"] = [{"claim": clip(f.get("claim"), 160), "check": bool(f.get("check"))} for f in (s.get("facts") or [])
                      if isinstance(f, dict) and str(f.get("claim", "")).strip()][:4]
        s["chapter"] = bool(s.get("chapter"))
        s.setdefault("title", f"Scene {i}")
        s.setdefault("purpose", "")
    b = sp.get("brief") if isinstance(sp.get("brief"), dict) else {}
    sp["brief"] = {"question": clip(b.get("question"), 200), "angle": clip(b.get("angle"), 240), "takeaway": clip(b.get("takeaway"), 200),
                   "titles": [clip(t, 100) for t in (b.get("titles") or [])[:3] if str(t).strip()], "first_frame": clip(b.get("first_frame"), 200)}
    sp.setdefault("narrator", {"voice": "deep"})
    sp["narrator"]["voice"] = "warm" if sp["narrator"].get("voice") == "warm" else "deep"
    sp.setdefault("tags", [])
    sp.setdefault("description", sp.get("logline", ""))
    return sp


def write_beats(sp, ask_llm, batch=4, progress=print, save=None, debug_dir=None):
    """Fill sp['scenes'][i]['beats'] with the LLM, `batch` scenes per call, up to 3 tries per batch (each retry says what was
    wrong). Batches that already have beats are skipped, so a stopped run resumes; save(sp) is called after every batch and
    a failed reply is kept in debug_dir."""
    scenes = sp["scenes"]
    tail = ""
    for a in range(0, len(scenes), batch):
        chunk = scenes[a:a + batch]
        ids = [s["id"] for s in chunk]
        if all(s.get("beats") for s in chunk):
            tail = " | ".join(f'{b["who"]}: {b["text"]}' for b in chunk[-1]["beats"][-3:])
            continue
        got, problem, prompt = {}, "", beats_prompt(sp, ids, tail)
        for attempt in range(3):
            progress(f"writing scenes {ids[0]}-{ids[-1]} ({a + 1}-{a + len(chunk)} of {len(scenes)})" + (f", try {attempt + 1}" if attempt else ""))
            reply = ask_llm(prompt + (f"\n\nYour previous reply could not be used ({problem}). Reply again with ONLY the valid JSON." if problem else ""))
            try:
                data = parse_json(reply)
                got = {x.get("id"): x for x in (data.get("scenes") if isinstance(data, dict) else data) or []}
                if all(got.get(i) and got[i].get("beats") for i in ids):
                    break
                problem = "some scenes had no beats"
            except (ValueError, AttributeError) as err:
                problem = str(err)[:160]
            if debug_dir:
                (Path(debug_dir) / f"reply_{ids[0]}_try{attempt + 1}.txt").write_text(reply, encoding="utf-8")
        else:
            raise ValueError(f"the LLM's script for {ids[0]}-{ids[-1]} was unusable after 3 tries: {problem}")
        for s in chunk:
            beats = [clean_beat(b, set(s["cast"]) | {"narrator"}) for b in (got.get(s["id"], {}).get("beats") or [])]
            s["beats"] = [b for b in beats if b]
            if not s["beats"]:
                raise ValueError(f"the LLM wrote nothing for {s['id']}")
        tail = " | ".join(f'{b["who"]}: {b["text"]}' for b in chunk[-1]["beats"][-3:])
        if save:
            save(sp)
    return sp


def claims(sp):
    """[(scene id, scene title, claim, needs checking)]: every real-world claim the writer listed, for a person to verify."""
    return [(s["id"], s["title"], f["claim"], f["check"]) for s in sp["scenes"] for f in s.get("facts", [])]


def spoken_words(sp):
    return sum(words(b["text"]) for s in sp["scenes"] for b in s.get("beats", []))


def new_outline(ask_llm, topic, minutes=9, cast_size=5, lessons="", progress=print):
    progress("writing the concept, cast and outline")
    sp = check_outline(parse_json(ask_llm(outline_prompt(topic, minutes, cast_size, lessons))))
    sp["topic"], sp["minutes"] = topic, minutes
    return sp


def new_screenplay(ask_llm, topic, minutes=9, cast_size=5, lessons="", progress=print):
    return write_beats(new_outline(ask_llm, topic, minutes, cast_size, lessons, progress), ask_llm, progress=progress)


def check_short(raw, kind="true"):
    """A story Short as the LLM wrote it -> a screenplay the long-film stages take (scenes with beats, claims as the first
    scene's facts). Raises ValueError with what to fix: the next try's prompt says it. A "whatif" Short ends on a question."""
    if not isinstance(raw, dict):
        raise ValueError("the reply is not one JSON object")
    sp = check_outline(raw, cast=(1, 3))
    sp["scenes"][0]["facts"] = [{"claim": clip(f.get("claim"), 160), "check": bool(f.get("check"))} for f in (sp.get("claims") or [])
                                if isinstance(f, dict) and str(f.get("claim", "")).strip()][:8]           # all of them, for claims()
    for s in sp["scenes"]:
        s["chapter"] = False
        s["start"] = {c: ("sit" if v == "lie" else v) for c, v in s["start"].items()}
        beats = [clean_beat(b, set(s["cast"]) | {"narrator"}) for b in (s.get("beats") or []) if isinstance(b, dict)]
        s["beats"] = [b for b in beats if b]
    sp["scenes"] = [s for s in sp["scenes"] if s["beats"]]
    if not sp["scenes"]:
        raise ValueError("no scene has any beats")
    n, first = spoken_words(sp), sp["scenes"][0]["beats"][0]
    if not SHORT_WORDS[0] <= n <= SHORT_WORDS[1]:
        raise ValueError(f"the script has {n} spoken words; it must have {SHORT_WORDS[0]} to {SHORT_WORDS[1]}")
    if words(first["text"]) > 14:
        raise ValueError(f"the hook (the first beat) has {words(first['text'])} words; it must be under 12 so it lands in 2 seconds")
    if kind == "whatif" and not sp["scenes"][-1]["beats"][-1]["text"].rstrip().endswith("?"):
        raise ValueError("the last beat must be the narrator's question to the viewer, ending with '?'")
    return sp


def new_short(ask_llm, topic, seconds=30, lessons="", progress=print, debug_dir=None, kind="true"):
    """A story Short's whole screenplay in one call, up to 3 tries (each retry says what was wrong)."""
    prompt, problem = short_prompt(topic, seconds, lessons, kind), ""
    for attempt in range(3):
        progress("writing the story" + (f", try {attempt + 1}" if attempt else ""))
        reply = ask_llm(prompt + (f"\n\nYour previous reply could not be used ({problem}). Reply again with ONLY the valid JSON." if problem else ""))
        try:
            sp = check_short(parse_json(reply), kind)
            sp["topic"], sp["minutes"], sp["format"], sp["story"] = topic, round(seconds / 60, 2), "short", kind
            return sp
        except (ValueError, AttributeError, TypeError, KeyError) as err:
            problem = str(err)[:200]
            if debug_dir:
                (Path(debug_dir) / f"reply_short_try{attempt + 1}.txt").write_text(reply, encoding="utf-8")
    raise ValueError(f"the LLM's story was unusable after 3 tries: {problem}")


def save(sp, path):
    Path(path).write_text(json.dumps(sp, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
