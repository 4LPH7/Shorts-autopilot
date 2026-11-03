"""Everything you hear in a long film, assembled once the plan has fixed when each line starts: the voice track (every
line placed on one timeline and mastered), synthesised sound effects, one or two safe-music tracks crossfaded, and the mix
with the music ducked under the voice. Main-engine Python (numpy + ffmpeg), like sound.py."""

import random
import wave
from pathlib import Path

import numpy as np

import footage
import sound

SR = sound.SR
CALM = ("calm", "ambient", "cinematic", "documentary", "atmospheric", "soft", "inspiring", "emotional", "piano", "chill")


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        if w.getframerate() != SR or w.getnchannels() != 1:
            raise RuntimeError(f"{path} isn't 48 kHz mono")
        return np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").astype(np.float32) / 32768


def voice_track(voice_dir, starts, total, dest):
    """starts: [(line id, seconds)]. Every line's wav placed on one mono timeline `total` seconds long."""
    track = np.zeros(int(total * SR) + SR, np.float32)
    for lid, t in starts:
        x = read_wav(Path(voice_dir) / f"{lid}.wav")
        a = int(t * SR)
        b = min(len(track), a + len(x))
        if b > a:
            track[a:b] += x[: b - a]
    return sound.write_wav(track[: int(total * SR)], dest)


def sfx_plan(scenes):
    """(cut times, big-moment times) on the film's clock: scene changes that are not plain cuts, and number/stamp cards."""
    cuts, hits, t0 = [], [], 0.0
    for s in scenes:
        if s.get("cover_in") in ("wipe", "fade") and t0 > 0:
            cuts.append(round(t0 + 0.2, 3))
        for e in s["events"]:
            if e["do"] == "card" and e.get("kind") in ("stat", "stamp"):
                hits.append((round(t0 + e["t"], 3), "", ""))
        t0 += s["dur"]
    return cuts, hits


def pick_music(entries, n=2, seed=0):
    """Up to n distinct tracks, calm ones first. entries: [(file, source, tags)]."""
    rng = random.Random(seed)
    calm = [e for e in entries if any(w in (e[2] or "").lower() or w in e[0].lower() for w in CALM)]
    rest = [e for e in entries if e not in calm]
    rng.shuffle(calm)
    rng.shuffle(rest)
    return [e[0] for e in (calm + rest)[:n]]


def music_track(files, total, dest, work):
    """One music bed exactly `total` seconds long: the tracks looped as needed and crossfaded."""
    work = Path(work)
    if len(files) == 1:
        return footage.fit_audio(files[0], total, dest)
    fade = 4.0
    seg = total / len(files) + fade
    parts = [footage.fit_audio(f, seg, work / f"music_{i}.mp3") for i, f in enumerate(files)]
    ins = sum([["-i", str(p)] for p in parts], [])
    chain = "[0:a][1:a]acrossfade=d={0}:c1=tri:c2=tri[x1]".format(fade)
    for i in range(2, len(parts)):
        chain += f";[x{i - 1}][{i}:a]acrossfade=d={fade}:c1=tri:c2=tri[x{i}]"
    r = footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", *ins, "-filter_complex", chain, "-map", f"[x{len(parts) - 1}]",
                     "-t", f"{total:.2f}", "-ar", str(SR), str(dest)], timeout=600)
    if r.returncode:
        raise RuntimeError(f"couldn't join the music: {r.stderr[-300:]}")
    return dest


def mix(voice, sfx, music, dest, music_gain=0.2):
    """voice (+ effects) over music that dips whenever the voice speaks. Any of sfx/music may be None."""
    ins, graph = ["-i", str(voice)], ["[0:a]asplit=2[v1][v2]"]
    layers = ["[v2]"]
    n = 1
    if music:
        ins += ["-i", str(music)]
        graph += [f"[{n}:a]volume={music_gain}[m]", "[m][v1]sidechaincompress=threshold=0.03:ratio=12:attack=20:release=500[md]"]
        layers.append("[md]")
        n += 1
    else:
        graph.append("[v1]anullsink")
    if sfx:
        ins += ["-i", str(sfx)]
        layers.append(f"[{n}:a]")
    graph.append(f"{''.join(layers)}amix=inputs={len(layers)}:normalize=0:dropout_transition=0[out]")
    r = footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", *ins, "-filter_complex", ";".join(graph), "-map", "[out]",
                     "-ar", str(SR), "-ac", "1", str(dest)], timeout=900)
    if r.returncode:
        raise RuntimeError(f"couldn't mix the audio: {r.stderr[-400:]}")
    return dest


def mux(video, audio, dest):
    r = footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", "-i", str(video), "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0",
                     "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ac", "2", "-shortest", "-movflags", "+faststart", str(dest)], timeout=1800)
    if r.returncode:
        raise RuntimeError(f"couldn't join picture and sound: {r.stderr[-300:]}")
    return dest
