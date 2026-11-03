"""Self-tests for the long-film modules, run by `daily_shorts.py --self-test`. Pure logic only: no LLM, no network, no render."""

import json
import re

import lf_audio
import lf_build
import lf_finish
import lf_plan
import lf_screenplay as sc
import lf_voice


def outline():
    cast = [{"id": i, "name": i.title(), "role": "r", "voice": v, "look": {}} for i, v in
            (("you", "male-warm"), ("mia", "male-warm"), ("kid", "child"), ("gran", "bogus"))]
    scenes = [{"id": "x", "title": f"Scene {n}", "chapter": n in (3,), "room": r, "tone": "dusk", "cast": ["you", "mia", "nobody"],
               "pos": {"you": "center", "mia": "center"}, "start": {"you": "lie"}, "words": 40, "purpose": "p"}
              for n, r in enumerate(("hospital", "hospital", "street", "moon"), 1)]
    return {"title": "T", "logline": "L", "cast": cast, "scenes": scenes}


def reply_for(ids):
    beats = [{"who": "narrator", "text": "You wake up. It is nineteen ninety-nine.", "cam": "mid", "act": "nope", "emo": "surprised"},
             {"who": "ghost", "text": "Who said that?", "act": "walk:left"},
             {"who": "mia", "text": "Look at this chart!", "cue": {"kind": "chart", "values": [1, 2, 5]}}, {"who": "you", "text": "   "}]
    return "Sure!\n```json\n" + json.dumps({"scenes": [{"id": i, "beats": beats} for i in ids]}) + "\n```"


def timings(sp):
    return {b["line"]: {"id": b["line"], "dur": 2.0, "mouth": [[0, 0], [0.2, 2], [0.8, 1]],
                        "sentences": [{"text": b["text"], "start": 0.0, "end": 1.8}]} for s in sp["scenes"] for b in s["beats"]}


def run():
    # parsing and checking
    assert sc.parse_json('words {"a": [1, 2]} more') == {"a": [1, 2]} and sc.parse_json("```json\n[1,2]\n```") == [1, 2]
    try:
        sc.parse_json("no json here")
        raise AssertionError("parse_json accepted nothing")
    except ValueError:
        pass
    sp = sc.check_outline(outline())
    assert len({c["voice"] for c in sp["cast"]}) == 4 and all(c["voice"] in sc.VOICE_TYPES for c in sp["cast"])      # duplicates and bad voices repaired
    assert [s["id"] for s in sp["scenes"]] == ["s01", "s02", "s03", "s04"] and sp["scenes"][3]["room"] == "living" and sp["scenes"][0]["tone"] == "day"
    assert sp["scenes"][0]["cast"] == ["you", "mia"] and set(sp["scenes"][0]["pos"].values()) <= set(sc.SLOTS)       # a stranger in the cast list is dropped
    sc.write_beats(sp, lambda prompt: reply_for(re.findall(r"s\d\d", prompt.split("Full outline")[0])[:4]), batch=2, progress=lambda m: None)
    b = sp["scenes"][0]["beats"]
    assert len(b) == 3 and b[1]["who"] == "narrator" and "act" not in b[0] and b[0]["cam"] == "mid" and b[2]["cue"]["kind"] == "chart"
    cue = sc.clean_beat({"who": "narrator", "text": "x", "cue": {"kind": "list", "title": "T" * 90, "items": ["a" * 99, "", "b", "c", "d", "e", "f"]}}, {"you"})["cue"]
    assert len(cue["items"]) == 5 and len(cue["items"][0]) == 40 and len(cue["title"]) == 36                # a card the layout can hold
    assert "cue" not in sc.clean_beat({"who": "narrator", "text": "x", "cue": {"kind": "chart", "values": ["a", 2]}}, set())
    assert sc.clean_beat({"who": "narrator", "text": "x", "cue": {"kind": "stat", "value": "$85", "label": "L"}}, set())["cue"] == {"kind": "stat", "value": "$85", "label": "L"}
    # the plan
    lf_plan.lines_of(sp)
    tm = timings(sp)
    scenes = lf_plan.plan(sp, tm)
    assert [s["cover_in"] for s in scenes][0] == "fade" and scenes[-1]["cover_out"] == "fade"
    assert scenes[1]["cover_out"] == "fade" and scenes[0]["cover_out"] == "cut"            # into the chapter: through black; same room: a cut
    for s in scenes:
        say = [e["t"] for e in s["events"] if e["do"] == "say"]
        assert say == sorted(say) and s["dur"] > max(say or [0]) and s["lines"][0]["t"] >= lf_plan.LEAD
        assert all(0 <= c["t"] <= s["dur"] for c in s["caps"]) and len(s["cast"]) == len(set(c["x"] for c in s["cast"]))
        shots = [e["t"] for e in s["events"] if e["do"] == "shot"]
        assert all(b2 - a >= lf_plan.MIN_SHOT - 1e-6 for a, b2 in zip(shots, shots[1:]))
    gap, secs = lf_plan.fit_gap(sp, tm)
    assert 0.12 <= gap <= 0.7 and secs > 0
    # the project files
    evil = {**scenes[0], "caps": scenes[0]["caps"] + [{"t": 0, "d": 1, "text": "</script><b>x", "who": "", "color": "#fff"}]}
    html = lf_build.scene_html(evil)
    assert 'id="s01-cam"' in html and 'data-composition-id="s01"' in html and html.count("</script>") == 1     # caption text can't close the script
    assert json.loads(re.search(r"const S = (\{.*\});", html).group(1).replace("<\\/", "</"))["id"] == "s01"
    idx = lf_build.index_html(scenes, lf_plan.total_seconds(scenes))
    assert idx.count("data-composition-src") == 4 and 'data-start="0.000"' in idx
    # the voice and the sound
    import numpy as np
    x = np.concatenate([np.zeros(24000), 0.4 * np.sin(np.linspace(0, 2000, 24000)), np.zeros(24000)]).astype("float32")
    runs = lf_voice.mouth_runs(x)
    assert runs[0] == [0.0, 0] and any(st == 2 for _, st in runs) and runs[-1][1] == 0 and all(0 <= st <= 2 for _, st in runs)
    entries = [("a.mp3", "s", "loud, EDM"), ("b.mp3", "s", "calm, piano"), ("c.mp3", "s", "")]
    assert lf_audio.pick_music(entries, 2)[0] == "b.mp3" and len(set(lf_audio.pick_music(entries, 5))) == 3
    cuts, hits = lf_audio.sfx_plan([{"dur": 5, "cover_in": "fade", "events": []}, {"dur": 6, "cover_in": "wipe", "events": [{"do": "card", "t": 1.0, "kind": "stat"}]}])
    assert cuts == [5.2] and hits == [(6.0, "", "")]
    # the upload text
    for i in (1, 2):
        sp["scenes"][i]["chapter"] = True
    pack = lf_finish.upload_pack(sp, [{"dur": 70}] * 4, "f.mp4", "nope.jpg")
    assert lf_finish.stamp(125) == "2:05" and "0:00 Intro" in pack["description"] and "1:10 Scene 2" in pack["description"] and pack["thumbnail"] == ""
    # the brief, the claims, the checks on the plan and the record of what went in
    raw = outline()
    raw["brief"] = {"question": "Q" * 300, "titles": ["a", "b", "c", "d", ""], "angle": None}
    raw["scenes"][0]["facts"] = [{"claim": "x" * 400, "check": 1}, {"claim": "  "}, "junk", {"claim": "ok", "check": False}] + [{"claim": "e"}] * 3
    sp2 = sc.check_outline(raw)
    assert len(sp2["brief"]["question"]) == 200 and sp2["brief"]["titles"] == ["a", "b", "c"] and sp2["brief"]["angle"] == ""
    facts = sp2["scenes"][0]["facts"]
    assert len(facts) == 4 and facts[0]["check"] is True and len(facts[0]["claim"]) == 160 and facts[1]["claim"] == "ok"
    assert sc.claims(sp2)[0][:2] == ("s01", "Scene 1") and sc.claims(sp2)[0][3] is True and len(sc.claims(sp2)) == 4
    plan_checks = {c["name"]: c for c in lf_finish.check_plan(lf_plan.plan(sp, tm), sp)["checks"]}
    assert not plan_checks["length"]["ok"] and plan_checks["captions fit"]["ok"] and plan_checks["claims"]["ok"]       # a toy film is far under 8 minutes
    assert not plan_checks["every character speaks"]["ok"] and "Kid" in plan_checks["every character speaks"]["detail"]
    sp["scenes"][0]["facts"] = [{"claim": "c", "check": True}]
    assert not {c["name"]: c for c in lf_finish.check_plan(lf_plan.plan(sp, tm), sp)["checks"]}["claims"]["ok"]
    man = lf_finish.manifest(sp, lf_plan.plan(sp, tm), [("a.mp3", "Mixkit free")], {"seconds": 12.0})
    assert man["voices"]["Narrator"] == "en-US-ChristopherNeural" and man["music"][0]["source"] == "Mixkit free" and man["generated_clips"] == []
    assert json.loads(json.dumps(man))["claims"][0]["check"] is True
    gates_test()
    print("long-film self-test passed")


def gates_test():
    """A film made with gates stops after the script and after the storyboard until a person approves; one without runs straight through."""
    import tempfile
    from pathlib import Path

    import longform
    names = ("write_screenplay", "voice_film", "build_film", "render_film", "finish_film")
    saved, old, calls = {n: getattr(longform, n) for n in names}, longform.FILMS, []

    def step(name, nxt):
        def fn(film, *args, **kwargs):
            calls.append(name)
            film.update(stage=nxt)
        return fn
    with tempfile.TemporaryDirectory() as tmp:
        longform.FILMS = Path(tmp)
        try:
            for n, (label, nxt) in zip(names, (("script", "screenplay"), ("voice", "voiced"), ("build", "built"), ("render", "rendered"), ("finish", "review"))):
                setattr(longform, n, step(label, nxt))
            film = longform.new_film("gated", 9, 5, gates=True)
            longform.run_all(film, {}, ask_llm=lambda prompt: "")
            assert calls == ["script"] and film.meta["stage"] == "screenplay" and "script ready" in film.meta["message"]
            longform.run_all(film, {}, ask_llm=None)
            assert calls == ["script"]                                              # nobody approved the script yet
            longform.approve_gate(film, "screenplay")
            longform.run_all(film, {}, ask_llm=None)
            assert calls == ["script", "voice", "build"] and film.meta["stage"] == "built"
            longform.approve_gate(film, "built")
            longform.run_all(film, {}, ask_llm=None)
            assert calls[-2:] == ["render", "finish"] and film.meta["stage"] == "review"
            calls.clear()
            longform.run_all(longform.new_film("free", 9, 5), {}, ask_llm=lambda prompt: "")
            assert calls == ["script", "voice", "build", "render", "finish"]
        finally:
            for n, fn in saved.items():
                setattr(longform, n, fn)
            longform.FILMS = old
