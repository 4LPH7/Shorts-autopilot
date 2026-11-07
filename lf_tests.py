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
    assert man["voices"]["Narrator"] == "en-US-ChristopherNeural" and man["music"][0]["source"] == "Mixkit free" and "generated_clips" not in man
    assert json.loads(json.dumps(man))["claims"][0]["check"] is True
    stick = lf_plan.apply_style(sp, "stick")                                # the look is a per-film choice, never written into the script
    assert all(c["look"]["style"] == "stick" for c in stick["cast"]) and all("style" not in c["look"] for c in sp["cast"])
    assert all(c["look"]["style"] == "cartoon" for c in lf_plan.apply_style(sp, "bogus")["cast"]) and stick["scenes"] is sp["scenes"]
    assert lf_plan.plan(stick, tm)[0]["cast"][0]["look"]["style"] == "stick"
    placement_test()
    short_test()
    lipsync_test()
    backgrounds_test()
    gates_test()
    print("long-film self-test passed")


def backgrounds_test():
    """Generated rooms come only from a paid picture service: the free one ignores the style and stamps a logo, so the
    film keeps its drawn rooms. A picture is cached under the service that made it; an older untagged one is ignored."""
    import tempfile
    from pathlib import Path

    import daily_shorts
    import genmedia
    import longform
    saved, calls = (daily_shorts.load_settings, genmedia.image_providers, genmedia.image), []

    def fake_image(prompt, dest, providers, *rest):
        calls.append(list(providers))
        Path(dest).write_bytes(b"picture")
        return Path(dest), providers[0], "m"
    with tempfile.TemporaryDirectory() as tmp:
        film = longform.Film.__new__(longform.Film)
        film.dir, film.meta = Path(tmp), {}
        (film.dir / "bg").mkdir()
        (film.dir / "bg" / "street-day-painted.png").write_bytes(b"old free picture with a logo")
        sp = {"scenes": [{"id": "s01", "room": "street", "tone": "day", "start": {}}]}
        try:
            daily_shorts.load_settings = lambda: {**daily_shorts.DEFAULTS, "lf_backgrounds": "painted", "image_provider": "auto"}
            genmedia.image = fake_image
            genmedia.image_providers = lambda preferred="auto": ["pollinations"]
            assert longform.room_backgrounds(film, sp, film.dir / "project") == {} and not calls and "drawn rooms" in film.meta["message"]
            genmedia.image_providers = lambda preferred="auto": ["muapi", "pollinations"]
            got = longform.room_backgrounds(film, sp, film.dir / "project")
            assert calls == [["muapi"]] and got == {"s01": "assets/bg/street-day-painted-muapi.png"}
            assert longform.room_backgrounds(film, sp, film.dir / "project") == got and len(calls) == 1      # cached
        finally:
            daily_shorts.load_settings, genmedia.image_providers, genmedia.image = saved


def short_reply(n_words=80, hook="A man sold the Eiffel Tower. Twice."):
    filler = " ".join(["then"] * max(1, n_words - sc.words(hook) - 6))
    beats = [{"who": "narrator", "text": hook, "cam": "wide", "cue": {"kind": "year", "text": "1925"}},
             {"who": "lustig", "text": "Top secret, gentlemen.", "act": "point", "cam": "close", "cue": {"kind": "compare", "left": {}, "right": {}}},
             {"who": "narrator", "text": filler + ".", "cam": "mid", "act": "walk:right", "cue": {"kind": "chart", "values": [1, 2]}}]
    return {"title": "T", "description": "D", "tags": ["a"], "narrator": {"voice": "deep"},
            "cast": [{"id": "lustig", "name": "Victor", "role": "con man", "voice": "male-warm", "look": {}}],
            "claims": [{"claim": "He sold it in 1925", "check": False}, {"claim": "He sold it twice", "check": True}],
            "scenes": [{"id": "x", "title": "Paris", "room": "office", "tone": "day", "cast": ["lustig"], "pos": {"lustig": "far-right"},
                        "start": {"lustig": "lie"}, "beats": beats}]}


def short_test():
    """A story Short: one call writes it (1-3 characters, 60-150 words, a hook under 12 words, claims kept with their check
    flags), and the vertical plan keeps everyone inside the narrow frame, opens on the hook and uses only cards that fit."""
    sp = sc.check_short(short_reply())
    assert len(sp["cast"]) == 1 and sp["scenes"][0]["start"]["lustig"] == "sit" and not sp["scenes"][0]["chapter"]
    assert [c[3] for c in sc.claims(sp)] == [False, True] and sc.SHORT_WORDS[0] <= sc.spoken_words(sp) <= sc.SHORT_WORDS[1]
    for bad, why in ((short_reply(200), "spoken words"), (short_reply(40), "spoken words"),
                     (short_reply(80, "This is a very long opening line that takes far too many words to say out loud"), "hook")):
        try:
            sc.check_short(bad)
            raise AssertionError(f"accepted a Short with a bad {why}")
        except ValueError as err:
            assert why in str(err), str(err)
    replies = iter(["no json", json.dumps(short_reply())])
    asked = []
    got = sc.new_short(lambda p: (asked.append(p), next(replies))[1], "Lustig", 30, progress=lambda m: None)
    assert got["format"] == "short" and "could not be used" in asked[1] and "About 72 spoken words" in asked[0]
    # a "What if...?" Short: its own prompt, and it must end on the narrator's question to the viewer
    wi = short_reply(hook="What if you never slept again?")
    try:
        sc.check_short(wi, "whatif")
        raise AssertionError("accepted a What if Short that doesn't end on a question")
    except ValueError as err:
        assert "question" in str(err)
    wi["scenes"][0]["beats"][-1]["text"] = wi["scenes"][0]["beats"][-1]["text"][:-1] + " would you try it?"
    assert sc.check_short(wi, "whatif") and sc.check_short(short_reply()) is not None                          # a true story needn't ask
    p = sc.short_prompt("What if you never slept again?", 30, kind="whatif")
    assert "What if: What if you never" in p and "ending with '?'" in p and "id 'you'" in p and "Eiffel" not in p.split("Rules:")[0]
    assert "What if" in sc.story_ideas_prompt(5, kind="whatif") and "true, surprising" in sc.story_ideas_prompt(5)
    import story_short
    assert [story_short.story_kind(a, t, f) for a, t, f in ((None, "What if the Moon fell?", False), (None, "Lustig", False),
                                                           (None, "", True), ("true", "What if x", False), ("bogus", "x", False))] == \
        ["whatif", "true", "whatif", "true", "true"]
    # three characters on a vertical stage: all inside the camera's ~530 px, apart, the walk stays in there too
    three = sc.check_short({**short_reply(), "cast": [{"id": i, "name": i, "voice": v, "look": {}} for i, v in
                                                      (("lustig", "male-warm"), ("dealer", "male-deep"), ("wife", "female-warm"))]})
    three["scenes"][0].update(cast=["lustig", "dealer", "wife"], pos={"lustig": "far-left", "dealer": "center", "wife": "far-right"})
    three["scenes"][0]["beats"].insert(2, {"who": "dealer", "text": "Really?"})          # 2 s after a close on Lustig, no shot asked for
    lf_plan.lines_of(three)
    scenes = lf_plan.plan(three, timings(three), lf_plan.TALL_GAP, tall=True)
    s = scenes[0]
    said = next(e["t"] for e in s["events"] if e["do"] == "say" and e["who"] == "dealer")
    assert any(e["do"] == "shot" and e["on"] == "dealer" and e["t"] == said for e in s["events"])      # whoever speaks is in the frame
    lo, hi = lf_plan.TALL[1], lf_plan.TALL[2]
    xs = [c["x"] for c in s["cast"]] + [e["to"] for e in s["events"] if e["do"] == "walk"]
    assert all(lo <= x <= hi for x in xs) and max(xs) - min(xs) <= 400 and len({c["x"] for c in s["cast"]}) == 3
    assert s["frame"] == [1080, 1920] and scenes[0]["cover_in"] == "cut" and s["lines"][0]["t"] < 0.2      # the hook is heard at once
    assert all(len(c["text"].split()) <= lf_plan.TALL_CAPTION_WORDS for c in s["caps"])
    assert [e["kind"] for e in s["events"] if e["do"] == "card"] == ["year"]                               # compare and chart don't fit
    html, idx = lf_build.scene_html(s), lf_build.index_html(scenes, 30)
    assert "height: 1920px" in html and 'data-width="1080" data-height="1920"' in html and 'data-v="1"' in html
    assert 'data-resolution="portrait"' in idx and 'width=1080, height=1920' in idx
    lf_plan.lines_of(sp)
    film = lf_plan.plan(sp, timings(sp))                                                                     # films unchanged
    assert "frame" not in film[0] and 'data-resolution="landscape"' in lf_build.index_html(film, 30) and "1920px" not in lf_build.scene_html(film[0]).split("#root .cam")[0]
    assert "height: 1920px" not in lf_build.scene_html(film[0])
    limits = {"min": 20.0, "max": 58.0}
    assert {c["name"]: c for c in lf_finish.check_plan(scenes, three, limits)["checks"]}["length"]["detail"].endswith("(wanted 20-58 seconds)")
    import story_short
    text = story_short.script_text(sp)
    assert text.startswith("Narrator: A man sold") and "CHECK  He sold it twice" in text.split("Claims")[1].split("\n")[1]


def placement_test():
    """Nobody shares a spot (one hid behind the other: 'four hands'), nobody floats sideways, a walk starts where the
    character stands and ends beside the others, and whoever sits or is in bed gets up before walking."""
    crowd = {"cast": ["a", "b", "c", "d", "e"], "pos": {"a": "right", "b": "far-right", "c": "right", "d": "right", "e": "far-right"}}
    xs = lf_plan.spread(crowd)                                      # this used to loop for ever
    assert all(abs(xs[p] - xs[q]) >= lf_plan.APART for p in xs for q in xs if p < q) and all(250 <= x <= 1670 for x in xs.values())
    look = {"h": 1}
    cast = [{"id": i, "name": i, "voice": "male-warm", "look": look} for i in ("you", "walt", "mia")]

    def scene(room, start, beats):
        return {"id": "s01", "title": "T", "chapter": False, "room": room, "tone": "day", "cast": ["you", "walt", "mia"],
                "pos": {"you": "left", "walt": "center", "mia": "right"}, "start": start, "beats": beats}
    beats = [{"who": "walt", "text": "Hi.", "act": "walk:left", "line": "L1"}, {"who": "you", "text": "Up.", "act": "walk:center", "line": "L2"}]
    tm = {k: {"dur": 1.0, "mouth": [[0, "X"]], "sentences": [{"text": "x", "start": 0, "end": 0.9}]} for k in ("L1", "L2")}
    sp = {"cast": cast, "scenes": [scene("hospital", {"you": "lie", "mia": "lie"}, beats)]}
    s = lf_plan.plan_scene(sp, sp["scenes"][0], tm)
    by = {c["id"]: c for c in s["cast"]}
    assert by["you"]["start"] == "bed" and by["you"]["x"] == lf_plan.BEDS["hospital"]["x"] and by["you"]["bed"] and by["you"]["y"] < lf_plan.FLOOR_Y
    assert by["mia"]["start"] == "sit"                              # one bed: the second one sits
    assert by["walt"]["x"] == 960                                   # starts at his own spot, not where his walk ends
    ev = [e for e in s["events"] if e["do"] in ("walk", "stand")]
    w1 = ev[0]
    assert w1["do"] == "walk" and w1["who"] == "walt" and all(abs(w1["to"] - x) >= lf_plan.APART for x in (by["you"]["x"], by["mia"]["x"]))
    up, w2 = ev[1], ev[2]                                           # out of bed first, then the walk, never onto anyone
    assert up["do"] == "stand" and up["who"] == "you" and "to" in up and w2["do"] == "walk" and w2["t"] > up["t"]
    assert all(abs(w2["to"] - x) >= lf_plan.APART for x in (w1["to"], by["mia"]["x"]))
    street = lf_plan.plan_scene(sp, scene("street", {"you": "lie"}, []), tm)
    assert {c["id"]: c["start"] for c in street["cast"]}["you"] == "sit"      # no bed in the street: sit, don't float
    sp["narrator"] = {"voice": "deep"}
    sp["scenes"][0]["beats"] = [{"who": "walt", "text": "Ha!", "emo": "happy"}, {"who": "narrator", "text": "So.", "emo": "sad"}]
    assert [ln.get("emo") for ln in lf_plan.lines_of(sp)] == ["happy", None]  # the narrator's voice stays even


def lipsync_test():
    """Mouth shapes follow the words and close in the pauses; voices take a little colour from the line's emotion."""
    import numpy as np
    assert [s for s, _ in lf_voice.word_shapes("Bob")] == ["A", "E", "A"] and [s for s, _ in lf_voice.word_shapes("five")] == ["G", "C", "G"]
    assert [s for s, _ in lf_voice.word_shapes("food")] == ["G", "F", "B"] and lf_voice.word_shapes("1999")[0][0] == "C"
    sr = 48000
    rng = np.random.default_rng(1)
    pcm = np.zeros(sr, dtype="float32")
    pcm[int(0.2 * sr):int(0.8 * sr)] = 0.3 * rng.standard_normal(int(0.6 * sr)).astype("float32")
    runs = lf_voice.visemes([("map", 0.2, 0.5), ("food", 0.5, 0.8)], pcm, sr)
    times = [t for t, _ in runs]
    assert runs[0][1] == "X" and runs[-1][1] == "X" and times == sorted(times) and {s for _, s in runs} <= set("ABCDEFGHX")
    assert any(s == "A" and 0.15 <= t <= 0.22 for t, s in runs)                # the M of "map", a frame early
    assert all(b - a >= 2 / 30 - 0.002 or s == "A" for (a, s), (b, _) in zip(runs, runs[1:]))   # times are rounded to ms
    assert not any(s != "X" and t > 0.85 for t, s in runs)                     # quiet after the words: mouth at rest
    est = lf_voice.estimate_words("map food", pcm, sr)
    assert len(est) == 2 and 0.15 <= est[0][1] <= 0.25 and est[1][2] <= 0.85 and est[0][2] <= est[1][1] + 1e-6
    assert lf_voice.accents([("the", 0.0, 0.1), ("money", 0.1, 0.4), ("vanished", 0.5, 0.9), ("completely", 1.0, 1.5)]) == [0.1, 1.0]
    voice, rate, pitch = lf_voice.edge_voice({"voice_type": "male-young", "emo": "sad"}, 1.0)
    assert voice == "en-US-EricNeural" and rate < 1.04 and pitch == "+3Hz"
    assert lf_voice.edge_voice({"voice_type": "narrator-deep"}, 1.0)[1:] == (0.96, "+0Hz")


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
