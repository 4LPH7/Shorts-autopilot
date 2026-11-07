"""The narration step: runs narrate.py in the isolated audio environment, masters the voice, and turns its timing into
the files the rest of the pipeline reads (per-sentence and per-word subtitle files, a mastered audio.wav).

Engines: "edge" (Microsoft neural voices, free, online), "kokoro" (runs on this PC, offline), "gemini", "elevenlabs"
and "minimax" (premium voices through genmedia.py, keys from the environment or MPT's config) and "mpt"
(MoneyPrinterTurbo's own voiceover: the old path, and the fallback when the audio environment is missing)."""

import json
import os
import re
import subprocess
from pathlib import Path

import footage
import genmedia
import sound

API_ENGINES = ("gemini", "elevenlabs", "minimax")
ENGINES = ("edge", "kokoro", "mpt") + API_ENGINES
ENGINE_NAMES = {"gemini": "Gemini", "elevenlabs": "ElevenLabs", "minimax": "MiniMax"}
HERE = Path(__file__).resolve().parent
AUDIO_PY = HERE / ".venv-audio" / "Scripts" / "python.exe"
MODELS = HERE / "models"
TAIL = 0.7                       # seconds of room after the last word: the last caption lingers, the music lands
AUDITION_TEXT = ("Your phone battery isn't dying because you're unlucky. It's dying because of math! "
                 "After about 500 cycles, it keeps roughly 80% of its original capacity, and heat makes it worse. "
                 "So which of these habits will you fix first?")
# (engine, voice, label): a spread of the best voices for the listener to choose from (premium ones first, when a key is set)
CANDIDATES = [("gemini", "Charon", "Charon (Gemini: deep, informative)"),
              ("gemini", "Algenib", "Algenib (Gemini: gravelly)"),
              ("gemini", "Orus", "Orus (Gemini: firm)"),
              ("gemini", "Enceladus", "Enceladus (Gemini: breathy, intimate)"),
              ("gemini", "Sulafat", "Sulafat (Gemini: warm)"),
              ("elevenlabs", "George", "George (ElevenLabs: warm storyteller)"),
              ("minimax", "English_expressive_narrator", "Expressive narrator (MiniMax)"),
              ("edge", "en-US-AndrewMultilingualNeural", "Andrew (warm, conversational)"),
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
    if engine in API_ENGINES and not genmedia.has(engine):
        return False, f"no {ENGINE_NAMES[engine]} key (paste one in Setup, or set {genmedia.KEY_SOURCES[engine][0][0]})"
    return True, ""


def check_voice(engine, voice):
    """The voice name as the engine wants it; raises with a hint when it can't be one of this engine's voices."""
    voice = str(voice or "").strip()
    if engine == "kokoro":
        if not re.match(r"^[abefhijpz][fm]_", voice):
            raise RuntimeError(f"'{voice}' isn't a Kokoro voice (pick one like af_heart in Settings)")
        return voice
    if engine == "gemini":
        match = next((v for v in genmedia.GEMINI_VOICES if v.lower() == voice.lower()), None)
        if not match:
            raise RuntimeError(f"'{voice}' isn't a Gemini voice (pick one like Charon in Settings)")
        return match
    if engine in ("elevenlabs", "minimax"):
        if not voice:
            raise RuntimeError(f"choose a {ENGINE_NAMES[engine]} voice in Settings")
        return voice
    return edge_name(voice)


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
    engine = s["voice_engine"]
    return {"script": script, "engine": engine, "voice": check_voice(engine, s["voice"]), "rate": float(s["voice_rate"]),
            "style": s.get("voice_style", "") if engine in API_ENGINES else "", "model": s.get("voice_model", "") or "",
            "whole": True,                                       # premium voices: the whole script in one request
            "parallel": 1 if engine == "gemini" else 3,          # (Gemini's free tier: 10 requests a day per model)
            "out_dir": str(out_dir), "models_dir": str(MODELS), "ffmpeg": footage.ffmpeg_exe(), "check": check}


def make_voiceover(s, script, work):
    """Narration for one video. Writes work/audio.wav (mastered), work/subtitle.srt (per sentence) and
    work/words.srt (per word). Returns (sentence srt text, word srt text, audio path, quality report)."""
    engine = s["voice_engine"]
    ok, why = available(engine)
    if not ok:
        raise RuntimeError(why)
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


def audition(out_dir, candidates=None, rate=1.05, style=""):
    """One mastered sample per candidate voice, all reading the same lines: [(label, path)]. For choosing a voice by ear.
    Premium voices without a key are skipped with a note, so the list is never empty."""
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
                   "style": style if engine in API_ENGINES else "", "parallel": 1 if engine == "gemini" else 3, "whole": True,
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
