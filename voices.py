"""The narration step: runs narrate.py in the isolated audio environment, masters the voice, and turns its timing into
the files the rest of the pipeline reads (per-sentence and per-word subtitle files, a mastered audio.wav).

Engines: "edge" (Microsoft neural voices, free, online), "kokoro" (runs on this PC, offline) and "mpt"
(MoneyPrinterTurbo's own voiceover: the old path, and the fallback when the audio environment is missing)."""

import json
import os
import re
import subprocess
from pathlib import Path

import footage
import sound

ENGINES = ("edge", "kokoro", "mpt")
HERE = Path(__file__).resolve().parent
AUDIO_PY = HERE / ".venv-audio" / "Scripts" / "python.exe"
MODELS = HERE / "models"
TAIL = 0.7                       # seconds of room after the last word: the last caption lingers, the music lands
AUDITION_TEXT = ("Your phone battery isn't dying because you're unlucky. It's dying because of math! "
                 "After about 500 cycles, it keeps roughly 80% of its original capacity, and heat makes it worse. "
                 "So which of these habits will you fix first?")
# (engine, voice, label): a spread of the best free voices for the listener to choose from
CANDIDATES = [("edge", "en-US-AndrewMultilingualNeural", "Andrew (warm, conversational)"),
              ("edge", "en-US-BrianMultilingualNeural", "Brian (clear, confident)"),
              ("edge", "en-US-AvaMultilingualNeural", "Ava (bright, lively)"),
              ("edge", "en-US-EmmaMultilingualNeural", "Emma (friendly)"),
              ("edge", "en-US-GuyNeural", "Guy (the previous default)"),
              ("kokoro", "af_heart", "Heart (Kokoro, on this PC)"),
              ("kokoro", "af_bella", "Bella (Kokoro)"),
              ("kokoro", "am_michael", "Michael (Kokoro)"),
              ("kokoro", "am_fenrir", "Fenrir (Kokoro)"),
              ("kokoro", "am_puck", "Puck (Kokoro, playful)")]


def edge_name(voice):
    """MoneyPrinterTurbo writes 'en-US-GuyNeural-Male'; Edge itself wants 'en-US-GuyNeural'."""
    return re.sub(r"-(Male|Female)$", "", voice)


def available(engine):
    """(ok, why not): are the audio environment and the models this engine needs in place?"""
    if engine == "mpt":
        return True, ""
    if not AUDIO_PY.exists():
        return False, "the audio environment isn't installed (run install.bat)"
    if engine == "kokoro" and not (MODELS / "kokoro" / "kokoro-v1.0.onnx").exists():
        return False, "the Kokoro voice model isn't downloaded (run install.bat)"
    if not (MODELS / "hf").exists():
        return False, "the Whisper model isn't downloaded (run install.bat)"
    return True, ""


def srt_time(t):
    ms = int(round(max(0.0, t) * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def to_srt(rows):
    """SRT text from [(start, end, text)]."""
    return "".join(f"{i}\n{srt_time(a)} --> {srt_time(b)}\n{text}\n\n" for i, (a, b, text) in enumerate(rows, 1))


def run_worker(job, timeout=1500):
    """Run narrate.py with `job`; returns its quality report. Raises RuntimeError with the reason on failure."""
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    job_file = out / "job.json"
    job_file.write_text(json.dumps(job, indent=1), encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "HF_HUB_DISABLE_TELEMETRY": "1"}
    r = subprocess.run([str(AUDIO_PY), str(HERE / "narrate.py"), str(job_file)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=env, stdin=subprocess.DEVNULL)
    if r.returncode:
        raise RuntimeError(f"narration failed: {(r.stderr or r.stdout)[-500:].strip()}")
    return json.loads((out / "qa.json").read_text(encoding="utf-8"))


def job_for(s, script, out_dir, check=True):
    voice = s["voice"] if s["voice_engine"] == "kokoro" else edge_name(s["voice"])
    return {"script": script, "engine": s["voice_engine"], "voice": voice, "rate": float(s["voice_rate"]),
            "out_dir": str(out_dir), "models_dir": str(MODELS), "ffmpeg": footage.ffmpeg_exe(), "check": check}


def make_voiceover(s, script, work):
    """Narration for one video. Writes work/audio.wav (mastered), work/subtitle.srt (per sentence) and
    work/words.srt (per word). Returns (sentence srt text, word srt text, audio path, quality report)."""
    engine = s["voice_engine"]
    ok, why = available(engine)
    if not ok:
        raise RuntimeError(why)
    if engine == "kokoro" and not re.match(r"^[abefhijpz][fm]_", s["voice"]):
        raise RuntimeError(f"'{s['voice']}' isn't a Kokoro voice (pick one like af_heart in Settings)")
    work = Path(work)
    qa = run_worker(job_for(s, script, work / "voice"))
    raw = work / "voice" / "voice.wav"
    audio = work / "audio.wav"
    if s["voice_master"]:
        sound.master_voice(raw, audio, engine, tail=TAIL)
    else:
        sound.master_voice(raw, audio, "none", tail=TAIL)
    sentences = json.loads((work / "voice" / "sentences.json").read_text(encoding="utf-8"))
    words = json.loads((work / "voice" / "words.json").read_text(encoding="utf-8"))
    sentence_srt = to_srt([(x["start"], x["end"], x["text"]) for x in sentences])
    word_srt = to_srt([(x["start"], x["end"], x["text"]) for x in words])
    (work / "subtitle.srt").write_text(sentence_srt, encoding="utf-8")
    (work / "words.srt").write_text(word_srt, encoding="utf-8")
    return sentence_srt, word_srt, audio, qa


def audition(out_dir, candidates=None, rate=1.05):
    """One mastered sample per candidate voice, all reading the same lines: [(label, path)]. For choosing a voice by ear."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for n, (engine, voice, label) in enumerate(candidates or CANDIDATES, 1):
        ok, why = available(engine)
        if not ok:
            print(f"skipping {label}: {why}")
            continue
        try:
            tmp = out_dir / f"_{n:02d}"
            job = {"script": AUDITION_TEXT, "engine": engine, "voice": voice, "rate": rate, "out_dir": str(tmp),
                   "models_dir": str(MODELS), "ffmpeg": footage.ffmpeg_exe(), "check": False}
            run_worker(job)
            wav = sound.master_voice(tmp / "voice.wav", tmp / "master.wav", engine, tail=0.3)
            dest = out_dir / f"{n:02d}-{engine}-{voice}.mp3"
            r = footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-q:a", "2", str(dest)])
            if r.returncode:
                raise RuntimeError(r.stderr[-200:])
            made.append((label, dest))
        except Exception as err:
            print(f"skipping {label}: {err}")
    return made
