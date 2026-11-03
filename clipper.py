"""Shorts from a video you have the right to use: transcribe it, pick the best self-contained moments, reframe them to
9:16 and give them the same finish as every other Short (word-timed captions, a look, synthesised sound effects, music
that ducks under the speech, YouTube loudness). They land in Review; nothing is posted without your approval.

    run_daily.bat --clipper <job.json>
job = {"source": "C:/videos/talk.mp4", "n": 3, "frame": "fit" | "fill", "focus": 0.5, "confirmed": true,
       "rights": "my own recording", "credit": ""}

Rights: the app never downloads anything. It refuses a URL, and it refuses a file unless you said where the video comes
from and confirmed you may reuse it in monetized YouTube Shorts. Someone else's famous video is not yours to repost:
Content ID claims and strikes follow, and downloading from YouTube breaks its terms. See SAFETY.md."""

import json
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import footage
import lf_screenplay as sc
import voices

HERE = Path(__file__).resolve().parent
LO, HI = 22.0, 58.0                  # a Short's length window in seconds
MAX_SOURCE_MIN = 120
ZOOM = 1.12                          # how far the picture punches in on every other stretch


class JobError(Exception):
    pass


def check_job(job):
    """The rules, before anything is processed. Returns the source file's Path or raises JobError."""
    src = str(job.get("source", "")).strip()
    if re.match(r"^[a-z][a-z0-9+.-]*://", src, re.I) or src.lower().startswith("www."):
        raise JobError("the app doesn't download videos: give it a video file you have the right to use")
    path = Path(src)
    if not path.is_file() or path.suffix.lower() not in footage.VIDEO_EXT:
        raise JobError(f"not a video file: {src}")
    if not job.get("confirmed") or len(str(job.get("rights", "")).strip()) < 8:
        raise JobError("say where the video comes from and confirm you have the right to reuse it in monetized YouTube Shorts")
    if job.get("frame", "fit") not in ("fit", "fill"):
        raise JobError("frame must be fit or fill")
    return path


# ---- Transcript and the choice of moments -------------------------------------------------------

def transcribe(source, work):
    """{"duration", "segments": [{text, start, end, words}]} from Whisper on this PC."""
    ok, why = voices.available("edge")
    if not ok:
        raise RuntimeError(why)
    wav = work / "source16k.wav"
    r = footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", str(wav)], timeout=3600)
    if r.returncode or not wav.exists():
        raise RuntimeError(f"couldn't read the sound of that video: {r.stderr[-200:]}")
    job, out = work / "transcribe_job.json", work / "transcript.json"
    job.write_text(json.dumps({"audio": str(wav), "out": str(out), "models_dir": str(voices.MODELS)}), encoding="utf-8")
    p = subprocess.run([str(voices.AUDIO_PY), str(HERE / "clip_worker.py"), str(job)], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=7200, env={**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_TELEMETRY": "1"},
                       stdin=subprocess.DEVNULL)
    wav.unlink(missing_ok=True)
    if p.returncode:
        raise RuntimeError(f"transcription failed: {(p.stderr or p.stdout)[-400:].strip()}")
    return json.loads(out.read_text(encoding="utf-8"))


def moments_prompt(segs, n, lo=LO, hi=HI):
    lines = "\n".join(f"[{s['start']:.1f}-{s['end']:.1f}] {s['text'][:200]}" for s in segs)
    return (f"You are editing vertical YouTube Shorts out of one long video, from its transcript. Pick the {n} best self-contained moments.\n"
            f"Each is {lo:.0f}-{hi:.0f} seconds long, starts at the beginning of a segment that hooks the viewer (a question, a surprising claim, "
            "the start of a story) and ends where a thought is complete, never mid-sentence. Moments must not overlap and must make sense "
            "without the rest of the video. Use the exact segment times shown. Give each an accurate title under 60 characters (no exaggeration) "
            f"and one sentence on why it works.\n\nTranscript:\n{lines}\n\n"
            'Reply with only a JSON array like [{"start": 12.4, "end": 51.0, "title": "...", "why": "..."}].')


def snap(raw, segs, lo=LO, hi=HI, n=3):
    """The chosen moments made to start and end on segment boundaries, inside [lo, hi] seconds, without overlap."""
    out, last_end, valid = [], -1.0, []
    for m in raw:
        try:
            valid.append((float(m["start"]), float(m["end"]), m))
        except (KeyError, TypeError, ValueError):             # not a moment: the LLM's reply may hold anything
            continue
    for a, b, m in sorted(valid, key=lambda v: v[0]):
        i = min(range(len(segs)), key=lambda k: abs(segs[k]["start"] - a))
        j = min(range(i, len(segs)), key=lambda k: abs(segs[k]["end"] - b))
        while segs[j]["end"] - segs[i]["start"] > hi and j > i:
            j -= 1
        while segs[j]["end"] - segs[i]["start"] < lo and j + 1 < len(segs) and segs[j + 1]["end"] - segs[i]["start"] <= hi:
            j += 1
        if not lo <= segs[j]["end"] - segs[i]["start"] <= hi or segs[i]["start"] < last_end:
            continue
        out.append({"i": i, "j": j, "start": segs[i]["start"], "end": segs[j]["end"], "title": str(m.get("title") or "")[:80], "why": str(m.get("why") or "")})
        last_end = segs[j]["end"]
        if len(out) == n:
            break
    return out


def heuristic_moments(segs, n, lo=LO, hi=HI, taken=()):
    """Moments without the LLM: dense speech that opens with a hook (a question, a number, why/how/what). Avoids `taken` (i, j) spans."""
    found = []
    for i in range(len(segs)):
        j = i
        while j + 1 < len(segs) and segs[j]["end"] - segs[i]["start"] < lo:
            j += 1
        dur = segs[j]["end"] - segs[i]["start"]
        if not lo <= dur <= hi:
            continue
        first = segs[i]["text"]
        hook = ("?" in first) + bool(re.search(r"\d", first)) + bool(re.match(r"(?i)\W*(why|how|what|here|never|nobody|the secret)", first))
        found.append((sum(len(s["words"]) for s in segs[i:j + 1]) / dur + 0.4 * hook, i, j))
    spans, out = list(taken), []
    for _, i, j in sorted(found, reverse=True):
        if all(j < a or i > b for a, b in spans):
            spans.append((i, j))
            out.append({"i": i, "j": j, "start": segs[i]["start"], "end": segs[j]["end"], "title": "", "why": "fast, dense speech"})
        if len(out) == n:
            break
    return out


# ---- The picture ---------------------------------------------------------------------------------

def zoom_plan(sentence_starts, dur, gap=5.5):
    """(cut times, punched-in windows) in seconds into the clip: a cut at a sentence start at least `gap` apart and never
    in the first or last 3 seconds; every second stretch is punched in, like a talking-head editor's jump cuts."""
    cuts = []
    for t in sentence_starts:
        if 3.0 <= t <= dur - 3.0 and (not cuts or t - cuts[-1] >= gap):
            cuts.append(round(t, 2))
    edges = [0.0] + cuts + [dur]
    return cuts, [(edges[k], edges[k + 1]) for k in range(1, len(edges) - 1, 2)]


def picture_graph(frame, focus, windows, zoom=ZOOM):
    """ffmpeg filter_complex: the source reframed to 1080x1920, then the punch-ins. frame "fit" keeps the whole picture over
    a blurred copy of itself; "fill" crops to the screen, `focus` (0 left .. 1 right) choosing which part."""
    if frame == "fit":
        base = ("[0:v]split=2[a][b];[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=40:6[bg];"
                "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2")
    else:
        base = f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920:(iw-1080)*{focus:.3f}:(ih-1920)/2"
    if not windows:
        return base + "[v]"
    z = "+".join(f"between(t,{a:.2f},{b:.2f})" for a, b in windows)
    k = f"(1+{zoom - 1:.3f}*({z}))"
    return base + f"[v0];[v0]scale=w='trunc(1080*{k}/2)*2':h='trunc(1920*{k}/2)*2':eval=frame,crop=1080:1920[v]"


def build_clip(source, m, segs, work, frame, focus, source_seconds):
    """Everything the Shorts finish needs, in `work`: combined.mp4 (the picture), audio.wav (the speech), words.srt and
    subtitle.srt (timing relative to the clip), cuts.json (where the punch-ins are, for the effects). Returns the clip's seconds."""
    a = max(0.0, m["start"] - 0.15)
    dur = min(source_seconds, m["end"] + 0.3) - a
    pick = segs[m["i"]:m["j"] + 1]
    words = [(max(0.0, w["start"] - a), max(0.05, w["end"] - a), w["text"]) for s in pick for w in s["words"]]
    sents = [(max(0.0, s["start"] - a), s["end"] - a, s["text"]) for s in pick]
    work.mkdir(parents=True, exist_ok=True)
    (work / "words.srt").write_text(voices.to_srt(words), encoding="utf-8")
    (work / "subtitle.srt").write_text(voices.to_srt(sents), encoding="utf-8")
    cuts, windows = zoom_plan([x[0] for x in sents[1:]], dur)
    (work / "cuts.json").write_text(json.dumps(cuts), encoding="utf-8")
    ff = footage.ffmpeg_exe()
    r = footage.run([ff, "-y", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{dur:.3f}", "-i", str(source), "-vn", "-ac", "1", "-ar", "48000",
                     "-c:a", "pcm_s16le", str(work / "audio.wav")], timeout=600)
    if r.returncode:
        raise RuntimeError(f"couldn't cut the sound: {r.stderr[-200:]}")
    r = footage.run([ff, "-y", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{dur:.3f}", "-i", str(source), "-filter_complex",
                     picture_graph(frame, focus, windows), "-map", "[v]", "-an", "-r", "30", "-c:v", "libx264", "-preset", "fast",
                     "-crf", "17", "-pix_fmt", "yuv420p", str(work / "combined.mp4")], timeout=1800)
    if r.returncode or not (work / "combined.mp4").exists():
        raise RuntimeError(f"couldn't reframe the picture: {r.stderr[-300:]}")
    return dur


# ---- The run -------------------------------------------------------------------------------------

def run(job_file):
    import daily_shorts as e
    import qa
    job = json.loads(Path(job_file).read_text(encoding="utf-8"))
    try:
        source = check_job(job)
    except JobError as err:
        print(f"CLIPPER REFUSED: {err}")
        return 1
    seconds = footage.probe(source)[0]
    if not seconds or seconds > MAX_SOURCE_MIN * 60:
        print(f"CLIPPER REFUSED: the video must be between a few seconds and {MAX_SOURCE_MIN} minutes")
        return 1
    s, M, n = e.load_settings(), e.load_mpt(), max(1, min(6, int(job.get("n", 3))))
    ask_llm = lambda prompt: e.ask(M.llm, prompt)                                      # noqa: E731
    clock = e.Clock()
    base = e.WORK / f"clip-{datetime.now():%Y%m%d-%H%M}-{e.slugify(source.stem)[:30]}"
    base.mkdir(parents=True, exist_ok=True)
    print(f"Listening to {source.name} ({seconds / 60:.1f} min)")
    segs = transcribe(source, base)["segments"]
    clock.mark("transcript")
    if len(segs) < 3:
        print("CLIPPER STOPPED: not enough speech to cut Shorts from")
        return 1
    try:
        moments = snap(sc.parse_json(ask_llm(moments_prompt(segs, n))), segs, n=n)
    except Exception as err:
        print(f"Moment choice by the LLM failed ({type(err).__name__}: {str(err)[:120]}); using the speech density instead")
        moments = []
    if len(moments) < n:
        moments += heuristic_moments(segs, n - len(moments), taken=[(m["i"], m["j"]) for m in moments])
    clock.mark("moments")
    made = 0
    for k, m in enumerate(sorted(moments, key=lambda m: m["start"]), 1):
        title = m["title"] or re.sub(r"\s+", " ", segs[m["i"]]["text"])[:60]
        stem = f"{datetime.now():%Y%m%d-%H%M}-{e.slugify(title)[:36]}-{k}"
        work = e.WORK / stem
        try:
            script = " ".join(sg["text"] for sg in segs[m["i"]:m["j"] + 1])
            length = build_clip(source, m, segs, work, job.get("frame", "fit"), float(job.get("focus", 0.5)), seconds)
            track = e.choose_track(s, e.usable_tracks(), ask_llm, title, script, e.recent_tracks())
            final = work / "final.mp4"
            e.finish_video(M, s, title, script, work, final, track, fresh=True)
            design = json.loads((work / "motion.json").read_text(encoding="utf-8")).get("design", []) if (work / "motion.json").exists() else []
            report = qa.check_video(final, None, design, limits={**qa.LIMITS, "min_s": 15.0, "max_s": 60.0})
            try:
                social = M.llm.generate_social_metadata(video_subject=title, video_script=script, language=s["language"], platform="youtube_shorts")
            except Exception:
                social = {}
            credit = str(job.get("credit", "")).strip()
            description = (social.get("caption") or m["why"] or title) + (f"\n\nSource: {credit}" if credit else "")
            e.REVIEW.mkdir(exist_ok=True)
            shutil.copyfile(final, e.REVIEW / f"{stem}.mp4")
            final.unlink(missing_ok=True)
            (e.REVIEW / f"{stem}.json").write_text(json.dumps({
                "topic": title, "title": social.get("title") or title, "description": description, "tags": social.get("hashtags", []),
                "music": track or "none", "motion": s["motion_level"], "look": s["look"], "narration": {"engine": "original audio", "voice": "the video's own audio"}, "weak_beats": [],
                "qa": report, "timings": clock.rows, "credits": footage.credits_for([]), "clips": [], "script": script,
                "source": {"file": source.name, "from": round(m["start"], 1), "to": round(m["end"], 1), "rights": str(job["rights"]).strip(),
                          "credit": credit, "frame": job.get("frame", "fit")},
                "rendered": datetime.now().isoformat(timespec="seconds")}, indent=2, ensure_ascii=False), encoding="utf-8")
            made += 1
            print(f"READY FOR REVIEW: {e.REVIEW / (stem + '.mp4')} ({length:.0f} s, {qa.summary(report)})")
        except Exception as err:
            shutil.rmtree(work, ignore_errors=True)
            print(f"Short {k} failed: {type(err).__name__}: {str(err)[:300]}")
    shutil.rmtree(base, ignore_errors=True)
    print(f"CLIPPER DONE: {made} of {len(moments)} Short(s) are waiting in Review")
    return 0 if made else 1


# ---- Self-test (called by daily_shorts --self-test) ----------------------------------------------

def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        clip = Path(tmp) / "talk.mp4"
        clip.write_bytes(b"x")
        ok = {"source": str(clip), "confirmed": True, "rights": "my own recording"}
        assert check_job(ok) == clip
        for bad, why in (({**ok, "source": "https://www.youtube.com/watch?v=abc"}, "download"), ({**ok, "source": "www.example.com/a.mp4"}, "download"),
                         ({**ok, "confirmed": False}, "right"), ({**ok, "rights": "mine"}, "right"), ({**ok, "frame": "zoom"}, "frame"),
                         ({**ok, "source": str(Path(tmp) / "missing.mp4")}, "video file")):
            try:
                check_job(bad)
                raise AssertionError(f"accepted {bad}")
            except JobError as err:
                assert why in str(err), (why, str(err))
    segs = [{"text": f"Sentence {i} about money?" if i % 4 == 0 else f"Sentence {i} goes on.", "start": i * 10.0, "end": i * 10.0 + 9.0,
             "words": [{"text": "w", "start": i * 10.0, "end": i * 10.0 + 1}] * (12 + i % 3)} for i in range(12)]
    got = snap([{"start": 11.0, "end": 52.0, "title": "A"}, {"start": 30.0, "end": 60.0, "title": "overlaps"}, {"start": 70.0, "end": 100.0, "title": "B"},
                {"start": "x"}], segs, n=3)
    assert [(g["start"], g["end"]) for g in got] == [(10.0, 49.0), (70.0, 99.0)] and got[0]["title"] == "A"            # snapped, overlap dropped
    assert all(LO <= g["end"] - g["start"] <= HI for g in got)
    heur = heuristic_moments(segs, 2, taken=[(0, 2)])
    assert len(heur) == 2 and all(h["i"] > 2 for h in heur) and heur[0]["end"] - heur[0]["start"] >= LO
    cuts, windows = zoom_plan([0.0, 4.0, 6.0, 12.0, 18.0, 24.0, 43.0], 44.0)          # 0.0 and 43.0 are too close to the ends, 6.0 to 4.0
    assert cuts == [4.0, 12.0, 18.0, 24.0] and windows == [(4.0, 12.0), (18.0, 24.0)] and zoom_plan([], 30.0) == ([], [])
    g_fit, g_fill = picture_graph("fit", 0.5, windows), picture_graph("fill", 0.25, [])
    assert "boxblur" in g_fit and "between(t,4.00,12.00)+between(t,18.00,24.00)" in g_fit and g_fit.endswith("[v]") and "eval=frame" in g_fit
    assert "(iw-1080)*0.250" in g_fill and g_fill.endswith("[v]") and "eval=frame" not in g_fill
    prompt = moments_prompt(segs[:2], 3)
    assert "[0.0-9.0] Sentence 0 about money?" in prompt and "JSON array" in prompt
    print("clipper self-test passed")
