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
- "chapter": true on at most 4 scenes (a title card opens them). "vids": on at most 3 scenes, a one-sentence prompt for a cinematic 8-second live-action cutaway an AI video generator could make (no people's faces, no logos, no text); omit otherwise.
Allowed values: room {list(ROOMS)}; tone {list(TONES)}; start {list(STARTS)}; position {list(SLOTS)}; voice {list(VOICE_TYPES)} (every character a different voice); narrator voice "deep" or "warm".
{LOOK_HELP}
JSON rules: valid JSON only; inside strings use single quotes for quoted phrases (never unescaped double quotes) and no line breaks.
Reply with ONLY this JSON:
{{"title":"...", "logline":"...", "brief":{{"question":"the one question the film answers", "angle":"what makes this treatment original", "takeaway":"one sentence", "titles":["accurate option 1","option 2","option 3"], "first_frame":"the opening image"}},
 "description":"YouTube description, 3-4 sentences", "tags":["..."], "narrator":{{"voice":"deep"}},
 "cast":[{{"id":"you","name":"...","role":"...","personality":"...","voice":"male-warm","look":{{...}}}}],
 "scenes":[{{"id":"s01","title":"...","chapter":false,"room":"hospital","tone":"night","cast":["you"],"pos":{{"you":"center"}},"start":{{"you":"lie"}},"purpose":"...","words":80,"facts":[{{"claim":"a real-world claim this scene makes","check":false}}],"vids":"optional"}}]}}"""


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


def check_outline(sp):
    """Fix what can be fixed, raise ValueError for what cannot. Returns the same dict."""
    if not (3 <= len(sp.get("cast", [])) <= 6) or not sp.get("scenes"):
        raise ValueError("the outline needs a cast of 4-5 and a list of scenes")
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


def save(sp, path):
    Path(path).write_text(json.dumps(sp, ensure_ascii=False, indent=1), encoding="utf-8")


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))
