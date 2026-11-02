"""Automatic checks on a finished video, so a problem is caught before you spend time reviewing it.

Everything is measured with ffmpeg on the real file (format, length, loudness and peak, dead air, black or frozen
picture) plus what the pipeline already knows (how well the narration matched the script, the caption design rules).
The checks only flag: approving a video stays your decision."""

import os
import re

import footage

LIMITS = {"min_s": 45.0, "max_s": 80.0, "lufs": (-16.0, -12.5), "peak_db": -0.8, "dead_air_s": 1.4,
          "black_s": 0.3, "freeze_s": 1.8, "size_mb": 90.0, "narration": 0.8}


def parse_report(text):
    """The numbers in ffmpeg's output (a pure function of the text, so it can be tested with canned output)."""
    f = {"silences": [], "black": [], "freezes": []}
    m = re.search(r"Video: (\w+).*?, (\d{3,5})x(\d{3,5}).*?, ([\d.]+) fps", text)
    if m:
        f.update(codec=m.group(1), width=int(m.group(2)), height=int(m.group(3)), fps=float(m.group(4)))
    m = re.search(r"Audio: (\w+).*?, (\d+) Hz, (\w+)", text)
    if m:
        f.update(audio=m.group(1), hz=int(m.group(2)), layout=m.group(3))
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", text)
    if m:
        f["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    m = re.search(r"Integrated loudness:\s*I:\s*(-?[\d.]+) LUFS", text, re.S)
    if m:
        f["lufs"] = float(m.group(1))
    m = re.search(r"True peak:\s*Peak:\s*(-?[\d.]+|-inf) dBFS", text, re.S)
    if m and m.group(1) != "-inf":
        f["peak"] = float(m.group(1))
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", text)]
    f["silences"] = [(a, b) for a, b in zip(starts, ends)] + ([(starts[-1], None)] if len(starts) > len(ends) else [])
    f["black"] = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", text)]
    f["freezes"] = [float(x) for x in re.findall(r"freeze_duration: ([\d.]+)", text)]
    return f


def evaluate(facts, size_mb, narration=None, design=(), limits=LIMITS, weak=()):
    """[(name, ok, detail)] from the measured facts. `weak` lists the beats where no clip matched the words well."""
    L, out = limits, []
    dur = facts.get("duration", 0.0)
    ok = (facts.get("width"), facts.get("height")) == (1080, 1920) and abs(facts.get("fps", 0) - 30) < 0.5 \
        and facts.get("hz") == 48000 and facts.get("layout") == "stereo" and facts.get("codec") == "h264"
    out.append(("format", ok, f"{facts.get('width')}x{facts.get('height')} {facts.get('fps')} fps {facts.get('codec')}, "
                              f"{facts.get('hz')} Hz {facts.get('layout')}"))
    out.append(("length", L["min_s"] <= dur <= L["max_s"], f"{dur:.1f} s (wanted {L['min_s']:.0f}-{L['max_s']:.0f})"))
    lufs = facts.get("lufs")
    out.append(("loudness", lufs is not None and L["lufs"][0] <= lufs <= L["lufs"][1],
                f"{lufs} LUFS (target -14)" if lufs is not None else "not measured"))
    peak = facts.get("peak")
    out.append(("peak", peak is None or peak <= L["peak_db"], f"{peak} dBFS" if peak is not None else "not measured"))
    dead = [(a, b) for a, b in facts.get("silences", [])        # a pause inside the video, not the tail after the last word
            if a > 0.5 and b is not None and b - a >= L["dead_air_s"] and b < dur - 0.1]
    out.append(("dead air", not dead, "none" if not dead else "silence at " + ", ".join(f"{a:.1f}s" for a, _ in dead[:4])))
    black = [(a, b) for a, b in facts.get("black", []) if b - a >= L["black_s"]]
    out.append(("black frames", not black, "none" if not black else "black at " + ", ".join(f"{a:.1f}s" for a, _ in black[:4])))
    frozen = [d for d in facts.get("freezes", []) if d >= L["freeze_s"]]
    out.append(("frozen picture", not frozen, "none" if not frozen else f"{len(frozen)} still stretch(es), longest {max(frozen):.1f}s"))
    out.append(("file size", size_mb <= L["size_mb"], f"{size_mb:.0f} MB"))
    if narration:
        worst = narration.get("worst_match", narration.get("worst", 1.0))
        out.append(("narration", worst >= L["narration"], f"worst sentence heard {worst:.0%} like the script"))
    out.append(("captions", not design, "design rules hold" if not design else "; ".join(design[:2])))
    out.append(("footage match", not weak, "every beat has a clip that fits" if not weak
                else "no strong match for beat " + ", ".join(str(b) for b in weak[:6])))
    return out


def check_video(path, narration=None, design=(), limits=LIMITS, weak=()):
    """Run the checks on a video file. Returns {"passed", "checks": [{name, ok, detail}], "measured": {...}}."""
    r = footage.run([footage.ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(path),
                     "-vf", "blackdetect=d=0.2:pix_th=0.04,freezedetect=n=0.001:d=1.0",
                     "-af", "ebur128=peak=true:framelog=quiet,silencedetect=noise=-42dB:d=1.0", "-f", "null", "-"], timeout=600)
    facts = parse_report(r.stderr)
    size_mb = os.path.getsize(path) / 1e6
    rows = evaluate(facts, size_mb, narration, design, limits, weak)
    return {"passed": all(ok for _, ok, _ in rows),
            "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in rows],
            "measured": {k: facts[k] for k in ("duration", "lufs", "peak") if k in facts}}


def summary(report):
    """One line for logs and the Review page."""
    bad = [c["name"] for c in report["checks"] if not c["ok"]]
    return "all checks passed" if not bad else "to look at: " + ", ".join(bad)


def self_test():
    sample = """Duration: 00:00:58.34, start: 0.000000, bitrate: 4549 kb/s
  Stream #0:0: Video: h264 (High), yuv420p(tv, bt709), 1080x1920 [SAR 1:1 DAR 9:16], 4378 kb/s, 30 fps, 30 tbr
  Stream #0:1: Audio: aac (LC), 48000 Hz, stereo, fltp, 202 kb/s
[silencedetect @ 0x1] silence_start: 17.13
[silencedetect @ 0x1] silence_end: 17.96 | silence_duration: 0.83
[silencedetect @ 0x1] silence_start: 40.2
[silencedetect @ 0x1] silence_end: 42.1 | silence_duration: 1.9
[blackdetect @ 0x2] black_start:0 black_end:0.1 black_duration:0.1
[freezedetect @ 0x3] lavfi.freezedetect.freeze_duration: 2.4
  Integrated loudness:
    I:         -14.1 LUFS
    Threshold: -24.4 LUFS
  True peak:
    Peak:       -1.2 dBFS
"""
    f = parse_report(sample)
    assert (f["width"], f["height"], f["fps"], f["hz"], f["layout"], f["lufs"], f["peak"]) == (1080, 1920, 30.0, 48000, "stereo", -14.1, -1.2)
    assert f["silences"] == [(17.13, 17.96), (40.2, 42.1)] and f["black"] == [(0.0, 0.1)] and f["freezes"] == [2.4]
    rows = {n: ok for n, ok, _ in evaluate(f, 33.0, {"worst_match": 0.95}, ())}
    assert rows["format"] and rows["length"] and rows["loudness"] and rows["peak"] and rows["black frames"] and rows["narration"]
    assert not rows["dead air"] and not rows["frozen picture"], rows            # 1.9 s of silence and a 2.4 s still are flagged
    bad = {n: ok for n, ok, _ in evaluate({**f, "lufs": -20.0, "peak": -0.1, "duration": 120.0}, 120.0, {"worst_match": 0.5}, ["x"])}
    assert not (bad["loudness"] or bad["peak"] or bad["length"] or bad["file size"] or bad["narration"] or bad["captions"]), bad
    assert {n: ok for n, ok, _ in evaluate(f, 33.0, None, (), LIMITS, [3, 7])}["footage match"] is False
    assert summary({"checks": [{"name": "a", "ok": True}, {"name": "b", "ok": False}]}) == "to look at: b"
