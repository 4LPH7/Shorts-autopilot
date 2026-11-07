"""Everything you hear except the music: voice mastering and sound effects.

The effects are synthesised here from noise and sine waves. Nothing is downloaded or sampled, so no third party can
hold rights to them: a Content ID claim on a stock track already cost a video once, and stock effects libraries
(Pixabay's included) are one of the places such claims come from.

Pure numpy and ffmpeg: it runs in MoneyPrinterTurbo's Python, no extra install."""

import random
import wave

import numpy as np

import footage

SR = 48000
LEVELS = {"off": 0.0, "subtle": 1.0, "full": 1.0}      # how many effects: see plan_sfx


def db(x):
    return 10 ** (x / 20)


# ---- Voice mastering ---------------------------------------------------------------------------

# Warmth, presence and a gentle compressor make a bare synthetic voice sound like it was recorded and mixed.
# Edge voices are a little hard around 5-7 kHz, Kokoro a little dull, so each gets its own touch.
VOICE_CHAIN = {
    "edge": ("highpass=f=75,equalizer=f=140:t=q:w=1.0:g=1.5,equalizer=f=2800:t=q:w=1.2:g=2.0,"
             "equalizer=f=6200:t=q:w=1.5:g=-2.5,"
             "acompressor=threshold=0.09:ratio=3:attack=6:release=110:makeup=2.5,alimiter=limit=0.93"),
    "kokoro": ("highpass=f=75,equalizer=f=160:t=q:w=1.0:g=1.2,equalizer=f=3000:t=q:w=1.2:g=1.5,"
               "equalizer=f=9000:t=h:w=1:g=2.0,"
               "acompressor=threshold=0.09:ratio=3:attack=6:release=110:makeup=2.5,alimiter=limit=0.93"),
    # Gemini's voices come at 24 kHz: a touch of body and air, and the same gentle compressor
    "gemini": ("highpass=f=70,equalizer=f=130:t=q:w=1.0:g=1.3,equalizer=f=2600:t=q:w=1.3:g=1.2,"
               "equalizer=f=9500:t=h:w=1:g=1.5,"
               "acompressor=threshold=0.09:ratio=2.6:attack=6:release=120:makeup=2.0,alimiter=limit=0.93"),
    # Studio-grade voices need almost nothing: a high-pass, a hint of presence, the compressor for consistency
    "elevenlabs": ("highpass=f=70,equalizer=f=3000:t=q:w=1.4:g=0.8,"
                   "acompressor=threshold=0.1:ratio=2.4:attack=6:release=120:makeup=1.8,alimiter=limit=0.93"),
    "minimax": ("highpass=f=70,equalizer=f=3000:t=q:w=1.4:g=0.8,"
                "acompressor=threshold=0.1:ratio=2.4:attack=6:release=120:makeup=1.8,alimiter=limit=0.93"),
}


def master_voice(src, dest, engine="edge", tail=0.0):
    """Mastered copy of a narration file (48 kHz mono wav). The mix later matches loudness; this shapes tone.
    engine picks the chain ("none" leaves the tone alone); tail adds that many seconds of silence at the end."""
    chain = "" if engine == "none" else VOICE_CHAIN.get(engine, VOICE_CHAIN["edge"])
    if tail:
        chain = (chain + "," if chain else "") + f"apad=pad_dur={tail}"
    cmd = [footage.ffmpeg_exe(), "-y", "-v", "error", "-i", str(src)] + (["-af", chain] if chain else [])
    r = footage.run(cmd + ["-ar", str(SR), "-ac", "1", str(dest)])
    if r.returncode:
        raise RuntimeError(f"voice mastering failed: {r.stderr[-300:]}")
    return dest


# ---- Synthesis -----------------------------------------------------------------------------------

def sweep_noise(dur, f0, f1, width=1.4, seed=1):
    """Noise shaped by a band-pass whose centre glides from f0 to f1 Hz (a log sweep): the body of a whoosh."""
    n = int(dur * SR)
    noise = np.random.default_rng(seed).standard_normal(n + 4096).astype(np.float32)
    block, hop = 2048, 512
    win = np.hanning(block).astype(np.float32)
    freqs = np.fft.rfftfreq(block, 1 / SR) + 1e-3
    out = np.zeros(n + 2 * block, np.float32)
    for start in range(0, n, hop):
        fc = f0 * (f1 / f0) ** (start / max(n, 1))
        mask = np.exp(-0.5 * (np.log2(freqs / fc) / (width / 2)) ** 2)
        out[start:start + block] += np.fft.irfft(np.fft.rfft(noise[start:start + block] * win) * mask).astype(np.float32)
    return out[:n] / 2.0                                        # Hann at 75% overlap sums to 2


def shape(x, peak_at=0.6, attack=1.6, decay=1.3):
    """Swell to a peak at `peak_at` (0..1 of the length) and fall away: the envelope of a pass-by."""
    p = np.linspace(0, 1, len(x), dtype=np.float32)
    env = np.where(p < peak_at, (p / peak_at) ** attack, ((1 - p) / (1 - peak_at)) ** decay)
    return x * env


def normalise(x, peak_db):
    return (x / (np.max(np.abs(x)) + 1e-9) * db(peak_db)).astype(np.float32)


def whoosh(dur=0.6, rising=True, seed=1, peak_db=-17):
    f0, f1 = (350, 5200) if rising else (5200, 350)
    return normalise(shape(sweep_noise(dur, f0, f1, 1.5, seed)), peak_db)


def impact(dur=1.3, seed=2, peak_db=-16):
    """A deep hit: a sine that falls from 110 to 40 Hz, a low noise thump and a short click, softly saturated."""
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    freq = 40 + 70 * np.exp(-t / 0.06)
    boom = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t / 0.30)
    thump = sweep_noise(dur, 160, 90, 1.2, seed) * np.exp(-t / 0.10)
    click = np.random.default_rng(seed).standard_normal(len(t)).astype(np.float32) * np.exp(-t / 0.004) * 0.35
    return normalise(np.tanh(1.6 * (boom + 0.35 * thump + click)), peak_db)


def riser(dur=1.5, seed=3, peak_db=-19):
    """Noise and a tone climbing together, loudest at the very end: place it so it ends on a hit or a reveal."""
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    tone = np.sin(2 * np.pi * np.cumsum(180 + 1400 * (t / dur) ** 2) / SR) * 0.25
    body = sweep_noise(dur, 300, 6500, 1.8, seed)
    env = (t / dur) ** 2.2
    return normalise((body / (np.max(np.abs(body)) + 1e-9) + tone) * env, peak_db)


def pop(dur=0.14, peak_db=-21):
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    return normalise(np.sin(2 * np.pi * np.cumsum(750 - 520 * np.minimum(t / 0.08, 1)) / SR) * np.exp(-t / 0.03), peak_db)


def ping(dur=0.9, hz=1318.5, peak_db=-23):
    """A soft bell: three inharmonic partials with their own decays."""
    t = np.arange(int(dur * SR), dtype=np.float32) / SR
    x = sum(a * np.sin(2 * np.pi * hz * m * t) * np.exp(-t / d) for m, a, d in ((1, 1.0, 0.35), (2.01, 0.35, 0.22), (3.5, 0.15, 0.10)))
    return normalise(x * np.minimum(t / 0.004, 1), peak_db)


SOUNDS = {"whoosh": whoosh, "whoosh_down": lambda: whoosh(0.5, False, 4), "impact": impact, "riser": riser,
          "pop": pop, "ping": ping}
# seconds from the start of each sound to its moment of impact: the plan places sounds so that moment lands on the beat
PEAK_AT = {"whoosh": 0.36, "whoosh_down": 0.18, "impact": 0.0, "riser": 1.5, "pop": 0.0, "ping": 0.0}


def make(name):
    return SOUNDS[name]()


# ---- The sound design plan ------------------------------------------------------------------------

GAP = 1.4            # seconds between effects: sound design is restraint
EDGE = 1.0           # nothing in the first or last second but the voice (and the optional intro whoosh)


def plan_sfx(total, cut_times, callouts, level="subtle", seed=0):
    """[(start_s, sound, gain_db)]: effects only where they mean something and never crowding the voice.

    subtle: a whoosh into about every other cut (its swell peaks on the cut) and a hit on every big number.
    full:   a whoosh into every cut, an intro whoosh, and a riser that builds into the first big number.
    A hit wins over a whoosh near it, and effects are at least GAP seconds apart."""
    if level not in ("subtle", "full") or total < 5:
        return []
    rng = random.Random(seed)
    events = [(s, "impact", 0.0, 2) for s, _, _ in callouts if EDGE <= s <= total - EDGE]
    if level == "full" and events:
        first = min(e[0] for e in events)
        if first >= 3.0:
            events.append((first - PEAK_AT["riser"], "riser", -2.0, 1))
    parity, flip = rng.randrange(2), rng.random() < 0.5
    for k, t in enumerate(cut_times):
        if not (EDGE <= t <= total - EDGE) or (level == "subtle" and k % 2 != parity):
            continue
        name = "whoosh" if (k % 2 == 0) != flip else "whoosh_down"
        events.append((t - PEAK_AT[name], name, -2.0, 0))
    if level == "full":
        events.append((0.05, "whoosh_down", -4.0, 0))
    events.sort(key=lambda e: (-e[3], e[0]))                  # strongest first
    kept = []
    for start, name, gain, prio in events:
        if not any(clash((start, name), (s, n)) for s, n, _ in kept):
            kept.append((start, name, gain))
    return sorted((round(max(0.0, s), 3), n, g) for s, n, g in kept)


def span(start, name):
    """The stretch of time an effect is 'about': just its peak, or for a riser the whole build-up."""
    peak = start + PEAK_AT[name]
    return (start, peak) if name == "riser" else (peak, peak)


def clash(a, b):
    """Do two (start, name) effects crowd each other? A riser may end on the hit it builds into."""
    if {a[1], b[1]} == {"riser", "impact"} and abs(sum(span(*a)) / 2 - sum(span(*b)) / 2) < 1.0:
        return False
    (a0, a1), (b0, b1) = span(*a), span(*b)
    return max(a0, b0) - min(a1, b1) < GAP


def build_track(events, total):
    """All effects placed on one mono track exactly `total` seconds long."""
    track = np.zeros(int(total * SR), np.float32)
    cache = {}
    for start, name, gain in events:
        x = cache.setdefault(name, make(name)) * db(gain)
        a = int(start * SR)
        b = min(len(track), a + len(x))
        if b > a:
            track[a:b] += x[: b - a]
    return track


def write_wav(x, path):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    return path


def sfx_track(path, total, cut_times, callouts, level="subtle", seed=0):
    """Write the sound-effects track for a video; returns (path, events) or (None, []) when there is nothing to add."""
    events = plan_sfx(total, cut_times, callouts, level, seed)
    if not events:
        return None, []
    return write_wav(build_track(events, total), path), events


def normalize_video_audio(src, dest):
    """A copy of a video whose audio is matched to YouTube's loudness (-14 LUFS, two passes). The picture is copied
    untouched, so this is fast and loses nothing. For videos made before the studio mix, which sit around -19 LUFS."""
    import json
    import re
    import motion
    ffmpeg = footage.ffmpeg_exe()
    cmd = [ffmpeg, "-hide_banner", "-nostats", "-i", str(src), "-map", "0:a:0", "-af",
           f"loudnorm={motion.LOUD}:print_format=json", "-f", "null", "-"]
    found = re.search(r'\{[^{}]*"input_i"[^{}]*\}', footage.run(cmd, timeout=600).stderr, re.S)
    if not found:
        raise RuntimeError("couldn't measure the loudness")
    m = json.loads(found.group(0))
    norm = (f"loudnorm={motion.LOUD}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:"
            f"measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true,aresample=48000")
    r = footage.run([ffmpeg, "-y", "-v", "error", "-i", str(src), "-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy",
                     "-af", norm, "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
                     str(dest)], timeout=900)
    if r.returncode:
        raise RuntimeError(f"couldn't fix the loudness: {r.stderr[-300:]}")
    return dest


def picture_hash(path):
    """MD5 of a video's picture stream as stored (nothing is decoded): equal hashes mean a bit-identical picture."""
    r = footage.run([footage.ffmpeg_exe(), "-v", "error", "-i", str(path), "-map", "0:v:0", "-c", "copy", "-f", "md5", "-"])
    if r.returncode or not r.stdout.startswith("MD5="):
        raise RuntimeError(f"couldn't read the picture of {path}: {r.stderr[-200:]}")
    return r.stdout.strip()


# ---- Self-test (called by daily_shorts --self-test) ---------------------------------------------------

def self_test():
    for name in SOUNDS:
        x = make(name)
        assert x.dtype == np.float32 and 0.04 * SR < len(x) < 2.5 * SR and 0.05 < np.max(np.abs(x)) <= 1.0, name
        assert np.isfinite(x).all() and abs(float(x[0])) < 0.2 and abs(float(x[-1])) < 0.05, name   # no clicks at the edges
    assert np.array_equal(make("whoosh"), make("whoosh"))                                      # deterministic
    cuts = [3.4 * k for k in range(1, 17)]
    plan = plan_sfx(58.0, cuts, [(12.0, 14.0, "80%"), (31.0, 33.0, "$800")], "subtle", seed=3)
    peaks = sorted(s + PEAK_AT[n] for s, n, _ in plan)
    assert all(b - a >= GAP - 1e-6 for a, b in zip(peaks, peaks[1:])), plan
    assert sum(n == "impact" for _, n, _ in plan) == 2 and all(EDGE - 0.4 <= p <= 58 - EDGE + 0.4 for p in peaks), plan
    assert 6 <= len(plan) <= 16, len(plan)
    full = plan_sfx(58.0, cuts, [(12.0, 14.0, "80%")], "full", seed=3)
    assert len(full) >= len(plan_sfx(58.0, cuts, [(12.0, 14.0, "80%")], "subtle", seed=3)) and any(n == "riser" for _, n, _ in full)
    assert plan_sfx(58.0, cuts, [], "off") == [] and plan_sfx(3.0, cuts, [], "subtle") == []
    track = build_track(plan, 58.0)
    assert len(track) == 58 * SR and np.max(np.abs(track)) <= 1.0 and np.count_nonzero(track) > SR
