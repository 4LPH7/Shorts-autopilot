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


STYLES = ("cartoon", "stick")


def apply_style(sp, style):
    """A copy of the screenplay with every character drawn in `style`: "cartoon" people or "stick" figures (an unknown name
    means cartoon). The saved screenplay is untouched, so the same script can be filmed in either look."""
    style = style if style in STYLES else "cartoon"
    return {**sp, "cast": [{**c, "look": {**c["look"], "style": style}} for c in sp["cast"]]}


def lines_of(sp):
    """Every beat as a voice line [{id, voice_type, text, scene}]; also stamps beat['line']."""
    voice = {c["id"]: c["voice"] for c in sp["cast"]}
    out, n = [], 0
    for s in sp["scenes"]:
        for b in s["beats"]:
            n += 1
            b["line"] = f"L{n:04d}"
            vt = "narrator-" + sp["narrator"]["voice"] if b["who"] == "narrator" else voice[b["who"]]
            out.append({"id": b["line"], "voice_type": vt, "text": b["text"], "scene": s["id"]})
    return out


def spread(s):
    """x per character: their chosen slot, pushed apart when two chose the same one."""
    xs, taken = {}, []
    for cid in s["cast"]:
        x = sc.SLOTS[s["pos"][cid]]
        while any(abs(x - o) < 250 for o in taken):
            x += 280 if x < 1500 else -280
        xs[cid] = max(240, min(1680, x))
        taken.append(xs[cid])
    return xs


def captions(beat, tm, t, who_label, color):
    """One caption per sentence, timed from the voice; a long sentence is cut in two at its midpoint."""
    out = []
    for sent in tm["sentences"]:
        words = sent["text"].split()
        parts = [words] if len(words) <= 16 else [words[: len(words) // 2], words[len(words) // 2:]]
        a, b = t + sent["start"], t + sent["end"]
        for k, part in enumerate(parts):
            lo = a + (b - a) * (k / len(parts))
            out.append({"t": round(lo, 3), "d": round((b - a) / len(parts) + 0.2, 3), "text": " ".join(part), "who": who_label if k == 0 else "", "color": color})
    return out


def plan_scene(sp, s, timings, gap=GAP, vids=None):
    cast = {c["id"]: c for c in sp["cast"]}
    colors = {c["id"]: COLORS[i % len(COLORS)] for i, c in enumerate(sp["cast"])}
    hero = "you" if "you" in s["cast"] else s["cast"][0]
    xs = spread(s)
    ev, caps, lines, t = [], [], [], (CHAPTER_LEAD if s["chapter"] else LEAD)
    if s["chapter"]:
        ev.append({"do": "card", "t": 0.4, "d": CHAPTER_LEAD - 0.2, "kind": "title", "text": s["title"]})
    shot_t, focus, prev, card_end, clip_t = -99.0, None, None, 0.0, None
    for b in s["beats"]:
        tm = timings[b["line"]]
        d = tm["dur"]
        lines.append({"id": b["line"], "t": round(t, 3), "d": d})
        who = b["who"]
        actor = who if who != "narrator" else hero
        if who != "narrator":
            ev.append({"do": "say", "t": round(t, 3), "d": d, "who": who, "mouth": tm["mouth"], **({"emo": b["emo"]} if b.get("emo") else {})})
        elif b.get("emo"):
            ev.append({"do": "emo", "t": round(t, 3), "who": hero, "emo": b["emo"]})
        act = b.get("act")
        if act in sc.POSES:
            ev.append({"do": "pose", "t": round(t + 0.15, 3), "who": actor, "pose": act, "d": min(2.2, max(1.0, d - 0.3))})
        elif act in ACTORS:
            ev.append({"do": act, "t": round(t + 0.1, 3), "who": actor, "d": 0.6})
        elif act and act.startswith("walk:"):
            to = sc.SLOTS[{"left": "left", "center": "center", "right": "right"}[act[5:]]]
            ev.append({"do": "walk", "t": round(t + 0.1, 3), "who": actor, "to": to, "d": 1.3})
            xs[actor] = to
        mode = b.get("cam")
        if mode and t - shot_t >= MIN_SHOT and mode != "wide" or (mode == "wide" and focus and t - shot_t >= MIN_SHOT):
            on = actor
            if mode == "two":
                others = [c for c in s["cast"] if c != actor]
                on = [actor, min(others, key=lambda c: abs(xs[c] - xs.get(actor, 960)))] if others else actor
            ev.append({"do": "shot", "t": round(t, 3), "mode": mode, "on": on})
            shot_t, focus = t, (xs.get(actor, 960) if mode != "wide" else None)
        cue = b.get("cue")
        cue = {"kind": cue["kind"], **c} if cue and cue.get("kind") in sc.CUES and (c := sc.clamp_cue(cue)) else None     # a hand edit can't break the layout
        if cue and t >= card_end - 0.3:
            side = "left" if (focus or 960) >= 960 and focus else "right"
            cd = max(2.6, min(9.0, d + 0.5))
            ev.append({"do": "card", "t": round(t + 0.1, 3), "d": round(cd, 3), "side": side, **cue})
            card_end = t + 0.1 + cd
        label = cast[who]["name"] if who != "narrator" else ""
        caps += captions(b, tm, t, label, colors.get(who, "#fff"))
        if clip_t is None:
            clip_t = t + d + 0.3
        t += d + gap + (0.2 if who != prev else 0)
        prev = who
    dur = max(3.0, t + TAIL - gap)
    clips = []
    if vids and clip_t is not None and dur - clip_t > 3.0:
        clips = [{"t": round(clip_t, 3), "d": round(min(8.0, dur - clip_t - 0.3), 3), "src": vids}]
    return {"id": s["id"], "dur": round(dur, 3), "room": {"kind": s["room"], "tone": s["tone"]}, "events": ev, "caps": caps, "clips": clips, "lines": lines,
            "cast": [{"id": c, "look": cast[c]["look"], "x": xs[c], "y": FLOOR_Y + (i % 3) * 8, "start": s["start"].get(c, "stand"),
                      "face": -1 if xs[c] > 960 else 1} for i, c in enumerate(s["cast"])]}


def plan(sp, timings, gap=GAP, vids=None):
    """All scenes, with the cuts between them: fade through black into a chapter (and at both ends of the film), a wipe
    when the location changes, a straight cut otherwise. vids: {scene id: asset path} of imported generated clips."""
    scenes = [plan_scene(sp, s, timings, gap, (vids or {}).get(s["id"])) for s in sp["scenes"]]
    for i, sc_ in enumerate(scenes):
        sc_["cover_in"] = "fade" if i == 0 else sc_.get("cover_in", "cut")
        sc_["cover_out"] = "fade" if i == len(scenes) - 1 else sc_.get("cover_out", "cut")
        if i + 1 < len(scenes):
            nxt = sp["scenes"][i + 1]
            link = "fade" if nxt["chapter"] else "wipe" if nxt["room"] != sp["scenes"][i]["room"] else "cut"
            sc_["cover_out"], scenes[i + 1]["cover_in"] = link, link
    return scenes


def total_seconds(scenes):
    return sum(s["dur"] for s in scenes)


def fit_gap(sp, timings, lo=495.0, hi=595.0):
    """The gap between beats that lands the film inside [lo, hi] seconds when the voices alone do not: (gap, seconds)."""
    base = total_seconds(plan(sp, timings))
    beats = sum(len(s["beats"]) for s in sp["scenes"])
    want = min(max(base, lo), hi)
    gap = min(0.7, max(0.12, GAP + (want - base) / max(1, beats)))
    return gap, total_seconds(plan(sp, timings, gap))
