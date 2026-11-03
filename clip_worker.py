"""Transcription worker for the clipper: a video's speech with a time for every word.

    python clip_worker.py job.json      # runs in .venv-audio, like narrate.py
job = {"audio": 16 kHz mono wav, "out": result path, "models_dir", "model": "small.en"}; writes
{"duration", "segments": [{"text", "start", "end", "words": [{"text", "start", "end"}]}]}.
Whisper runs on this PC (int8, CPU): nothing is uploaded."""

import json
import sys
from pathlib import Path


def transcribe(job):
    from faster_whisper import WhisperModel
    root = Path(job["models_dir"]) / "hf"
    model = WhisperModel(job.get("model", "small.en"), device="cpu", compute_type="int8", cpu_threads=8,
                         download_root=str(root), local_files_only=root.exists())
    segments, info = model.transcribe(job["audio"], language="en", word_timestamps=True, vad_filter=True, beam_size=2,
                                      condition_on_previous_text=False, temperature=0.0)
    out = []
    for seg in segments:
        words = [{"text": w.word.strip(), "start": round(float(w.start), 3), "end": round(float(w.end), 3)}
                 for w in (seg.words or []) if w.word.strip()]
        if words:
            out.append({"text": seg.text.strip(), "start": round(float(seg.start), 3), "end": round(float(seg.end), 3), "words": words})
    Path(job["out"]).write_text(json.dumps({"duration": round(info.duration, 2), "segments": out}), encoding="utf-8")
    return {"segments": len(out), "seconds": round(info.duration)}


if __name__ == "__main__":
    print(json.dumps(transcribe(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))))
