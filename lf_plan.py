"""Screenplay + voice timings -> scene descriptions for lf_build (who stands where, what happens when, which shot, which
card, which caption). Pure functions: no files, no LLM, no rendering, so the whole plan can be tested with fake timings.

The voice is the clock: every beat starts when the previous one's audio ends plus a small gap, and everything that
happens on screen (mouths, gestures, cards, captions, camera) hangs off the beat's start."""

import re

import lf_screenplay as sc

LEAD, TAIL, GAP, CHAPTER_LEAD, MIN_SHOT = 0.45, 0.6, 0.28, 2.7, 4.5
COLORS = ["#ffd166", "#7fd1ff", "#ff8fa3", "#9be79b", "#c4a6ff", "#ffa66b"]
FLOOR_Y = 944
ACTORS = {"hop", "nod", "no", "shake", "sit", "stand"}
APART, EDGE, WALK_SPEED = 260, 250, 420      # px between two characters' centres; nearest a centre comes to the frame edge; px a second
# The beds the vector rooms draw (rooms.js): where someone sits up in bed (x of their back, at the pillow end), the height
# their hips sink to on the mattress, which way they face (toward the foot end) and the room's blanket colour.
BEDS = {"hospital": {"x": 1540, "hips": 652, "face": -1, "color": "#8fc1e3"},
        "bedroom": {"x": 1245, "hips": 662, "face": 1, "color": "#e07a5f"}}
# Where the cast may stand: (slot x, lowest x, highest x, px apart). A film uses the whole room. A vertical Short's camera
# sees about 530 px of it (stage.js), so its cast stands close together around the middle, nobody in bed (a bed is off frame).
WIDE = (sc.SLOTS, EDGE, 1920 - EDGE, APART)
TALL = ({"far-left": 790, "left": 820, "center": 960, "right": 1100, "far-right": 1130}, 780, 1140, 175)
SHORT_FRAME = [1080, 1920]
TALL_LEAD, TALL_GAP, TALL_MIN_SHOT, TALL_CAPTION_WORDS = 0.12, 0.15, 2.2, 6     # the hook is heard at once; quick cuts; short captions


STYLES = ("cartoon", "stick")


def apply_style(sp, style):
    """A copy of the screenplay with every character drawn in `style`: "cartoon" people or "stick" figures (an unknown name
    means cartoon). The saved screenplay is untouched, so the same script can be filmed in either look."""
    style = style if style in STYLES else "cartoon"
    return {**sp, "cast": [{**c, "look": {**c["look"], "style": style}} for c in sp["cast"]]}


def lines_of(sp):
    """Every beat as a voice line [{id, voice_type, text, scene, emo?}]; also stamps beat['line']. A character's line
    carries its emotion so the voice can colour it; the narrator stays even."""
    voice = {c["id"]: c["voice"] for c in sp["cast"]}
    out, n = [], 0
    for s in sp["scenes"]:
        for b in s["beats"]:
            n += 1
            b["line"] = f"L{n:04d}"
            vt = "narrator-" + sp["narrator"]["voice"] if b["who"] == "narrator" else voice[b["who"]]
            emo = {"emo": b["emo"]} if b.get("emo") and b["who"] != "narrator" else {}
            out.append({"id": b["line"], "voice_type": vt, "text": b["text"], "scene": s["id"], **emo})
    return out


def free_spot(want, others, floor=WIDE):
    """The x nearest `want` that keeps the floor's distance from every x in `others` and stays inside its range; on a
    floor that crowded, the x furthest from everyone. Two characters never share a spot (one would hide behind the other)."""
    _, lo, hi, apart = floor
    xs = range(lo, hi + 1, 10)
    clear = [x for x in xs if all(abs(x - o) >= apart for o in others)]
    if clear:
        return min(clear, key=lambda x: (abs(x - want), x))
    return max(xs, key=lambda x: (min(abs(x - o) for o in others), -abs(x - want)))


def spread(s, fixed=None, floor=WIDE):
    """x per character: their chosen slot, or the free spot nearest it. fixed: {id: x} placed already (in bed)."""
    xs = dict(fixed or {})
    for cid in s["cast"]:
        if cid not in xs:
            xs[cid] = free_spot(floor[0][s["pos"][cid]], list(xs.values()), floor)
    return xs


def captions(beat, tm, t, who_label, color, most=16):
    """One caption per sentence, timed from the voice; a sentence over `most` words is cut into even parts."""
    out = []
    for sent in tm["sentences"]:
        words = sent["text"].split()
        n = max(1, -(-len(words) // most))
        parts = [words[len(words) * k // n: len(words) * (k + 1) // n] for k in range(n)]
        a, b = t + sent["start"], t + sent["end"]
        for k, part in enumerate(parts):
            lo = a + (b - a) * (k / len(parts))
            out.append({"t": round(lo, 3), "d": round((b - a) / len(parts) + 0.2, 3), "text": " ".join(part), "who": who_label if k == 0 else "", "color": color})
    return out


def plan_scene(sp, s, timings, gap=GAP, bg=None, tall=False):
    """One scene. tall: a vertical Short (1080x1920): the cast close together, no bed, no chapter card, the first line at
    once, quicker shots, short captions, and only the cards that fit a narrow frame."""
    cast = {c["id"]: c for c in sp["cast"]}
    colors = {c["id"]: COLORS[i % len(COLORS)] for i, c in enumerate(sp["cast"])}
    hero = "you" if "you" in s["cast"] else s["cast"][0] if s["cast"] else None     # None: a narrated explainer, nobody on screen
    floor, min_shot, chapter = (TALL, TALL_MIN_SHOT, False) if tall else (WIDE, MIN_SHOT, s["chapter"])
    bed, starts, in_bed = None if tall else BEDS.get(s["room"]), dict(s["start"]), None
    for cid in s["cast"]:
        if starts.get(cid) == "lie":                       # lying = sitting up in the room's bed; one bed, nobody on the floor
            in_bed = cid if bed and in_bed is None else in_bed
            starts[cid] = "bed" if cid == in_bed else "sit"
    xs = spread(s, {in_bed: bed["x"]} if in_bed else None, floor)
    start_x = dict(xs)                                     # where each one stands when the scene opens (xs follows the walks)
    posture = {c: starts.get(c, "stand") for c in s["cast"]}
    ev, caps, lines, t = [], [], [], (CHAPTER_LEAD if chapter else TALL_LEAD if tall else LEAD)
    if chapter:
        ev.append({"do": "card", "t": 0.4, "d": CHAPTER_LEAD - 0.2, "kind": "title", "text": s["title"]})
    shot_t, focus, prev, card_end, shot_on = -99.0, None, None, 0.0, None
    for b in s["beats"]:
        tm = timings[b["line"]]
        d = tm["dur"]
        lines.append({"id": b["line"], "t": round(t, 3), "d": d})
        who = b["who"]
        actor = who if who != "narrator" else hero
        if who != "narrator":
            ev.append({"do": "say", "t": round(t, 3), "d": d, "who": who, "mouth": tm["mouth"], **({"emo": b["emo"]} if b.get("emo") else {}),
                       **({"accents": tm["accents"]} if tm.get("accents") else {})})
        elif b.get("emo"):
            ev.append({"do": "emo", "t": round(t, 3), "who": hero, "emo": b["emo"]})
        act = b.get("act")
        if act in sc.POSES:
            ev.append({"do": "pose", "t": round(t + 0.15, 3), "who": actor, "pose": act, "d": min(2.2, max(1.0, d - 0.3))})
        elif act in ACTORS or (act or "").startswith("walk:"):
            ev += moves(act, actor, round(t + 0.1, 3), xs, posture, bed, floor)
        mode = b.get("cam")
        hidden = tall and who != "narrator" and shot_on is not None and who not in shot_on     # a narrow frame shows whoever speaks
        if hidden:
            mode = mode if mode in ("close", "mid", "two") else "close"
        if mode and (t - shot_t >= min_shot or hidden) and mode != "wide" or (mode == "wide" and focus and t - shot_t >= min_shot):
            on = actor
            if mode == "two":
                others = [c for c in s["cast"] if c != actor]
                on = [actor, min(others, key=lambda c: abs(xs[c] - xs.get(actor, 960)))] if others else actor
            ev.append({"do": "shot", "t": round(t, 3), "mode": mode, "on": on})
            shot_t, focus = t, (xs.get(actor, 960) if mode != "wide" else None)
            shot_on = None if mode == "wide" else on if isinstance(on, list) else [on]
        cue = b.get("cue")
        kinds = sc.SHORT_CUES if tall else sc.CUES
        cue = {"kind": cue["kind"], **c} if cue and cue.get("kind") in kinds and (c := sc.clamp_cue(cue)) else None     # a hand edit can't break the layout
        if cue and t >= card_end - 0.3:
            side = "left" if (focus or 960) >= 960 and focus else "right"
            cd = max(2.6, min(9.0, d + 0.5))
            ev.append({"do": "card", "t": round(t + 0.1, 3), "d": round(cd, 3), "side": side, **cue})
            card_end = t + 0.1 + cd
        label = cast[who]["name"] if who != "narrator" else ""
        caps += captions(b, tm, t, label, colors.get(who, "#fff"), TALL_CAPTION_WORDS if tall else 16)
        t += d + gap + (0.2 if who != prev else 0)
        prev = who
    dur = max(3.0, t + TAIL - gap)
    return {"id": s["id"], "dur": round(dur, 3), "room": {"kind": s["room"], "tone": s["tone"]}, "events": ev, "caps": caps, "lines": lines,
            **({"bg": bg} if bg else {}), **({"frame": SHORT_FRAME} if tall else {}),
            "cast": [placed(c, cast[c]["look"], start_x[c], FLOOR_Y + (i % 3) * 8, starts.get(c, "stand"), bed) for i, c in enumerate(s["cast"])]}


def placed(cid, look, x, floor, start, bed):
    """A cast entry for the scene. In bed, the root goes where the hips meet the mattress (the legs are hidden under
    the blanket) and `floor` is where they stand once they get up."""
    out = {"id": cid, "look": look, "x": x, "y": floor, "start": start, "face": -1 if x > 960 else 1}
    if start == "bed":
        out.update(y=round(bed["hips"] + 130 * float(look.get("h") or 1)), face=bed["face"], bed=bed["color"], floor=floor)
    return out


def moves(act, who, t, xs, posture, bed, floor=WIDE):
    """The events for one movement direction, keeping where everyone is (xs) and how they are (posture) current. A walk
    ends at a free spot, facing the nearest person; whoever sits or is in bed gets up first; nobody hops in a chair."""
    out, others = [], [x for o, x in xs.items() if o != who]
    if posture[who] != "stand" and (act == "stand" or act.startswith("walk:")):
        out.append({"do": "stand", "t": t, "who": who, "d": 0.6})
        if posture[who] == "bed":
            out[-1]["to"] = xs[who] = free_spot(xs[who] + 300 * bed["face"], others, floor)
        posture[who], t = "stand", round(t + 0.7, 3)
    if act.startswith("walk:"):
        to = free_spot(floor[0][act[5:]], others, floor)
        if abs(to - xs[who]) >= 40:
            near = min(others, key=lambda x: abs(x - to), default=960)
            out.append({"do": "walk", "t": t, "who": who, "to": to, "face": 1 if near >= to else -1,
                        "d": round(min(2.6, max(0.8, abs(to - xs[who]) / WALK_SPEED)), 2)})
            xs[who] = to
    elif act == "sit" and posture[who] == "stand":
        out.append({"do": "sit", "t": t, "who": who, "d": 0.6})
        posture[who] = "sit"
    elif act in ("nod", "no", "shake") or (act == "hop" and posture[who] == "stand"):
        out.append({"do": act, "t": t, "who": who, "d": 0.6})
    return out


def plan(sp, timings, gap=GAP, bgs=None, tall=False):
    """All scenes, with the cuts between them: fade through black into a chapter (and at both ends of the film), a wipe
    when the location changes, a straight cut otherwise. bgs: {scene id: asset path} of generated backgrounds that replace the flat vector room. tall: a vertical Short, which
    opens on its first frame (no fade in: the hook has two seconds)."""
    scenes = [plan_scene(sp, s, timings, gap, (bgs or {}).get(s["id"]), tall) for s in sp["scenes"]]
    for i, sc_ in enumerate(scenes):
        sc_["cover_in"] = ("cut" if tall else "fade") if i == 0 else sc_.get("cover_in", "cut")
        sc_["cover_out"] = "fade" if i == len(scenes) - 1 else sc_.get("cover_out", "cut")
        if i + 1 < len(scenes):
            nxt = sp["scenes"][i + 1]
            link = "fade" if nxt["chapter"] else "wipe" if nxt["room"] != sp["scenes"][i]["room"] else "cut"
            sc_["cover_out"], scenes[i + 1]["cover_in"] = link, link
    return scenes


def total_seconds(scenes):
    return sum(s["dur"] for s in scenes)


def fit_gap(sp, timings, lo=495.0, hi=595.0, tall=False):
    """The gap between beats that lands the film inside [lo, hi] seconds when the voices alone do not: (gap, seconds).
    A Short starts from a tighter gap and is never stretched past a natural pause."""
    first = TALL_GAP if tall else GAP
    base = total_seconds(plan(sp, timings, first, tall=tall))
    beats = sum(len(s["beats"]) for s in sp["scenes"])
    want = min(max(base, lo), hi)
    gap = min(0.45 if tall else 0.7, max(0.08 if tall else 0.12, first + (want - base) / max(1, beats)))
    return gap, total_seconds(plan(sp, timings, gap, tall=tall))
