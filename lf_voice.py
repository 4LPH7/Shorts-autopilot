"""Long-video voices: every line of the screenplay spoken by its character's own Edge neural voice.

    python lf_voice.py job.json      # runs in .venv-audio, like narrate.py
job = {"lines": [{"id", "voice_type", "text"}], "out_dir", "ffmpeg", "rate"}; writes out_dir/<id>.wav (48 kHz mono) and
out_dir/lines.json: [{"id", "dur", "mouth": [[t, 0-3]], "sentences": [{"text", "start", "end"}]}].
The mouth track is read off the audio itself (loudness per 1/30 s), so the cartoon mouths open when the voice does.
The top of the file is stdlib only: the main engine imports VOICE_MAP from it."""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import narrate  # noqa: E402  (its pure helpers; heavy imports happen inside its functions)

# type -> (Edge voice, speed offset, pitch). Distinct enough that a listener always knows who is talking.
VOICE_MAP = {
    "narrator-deep": ("en-US-ChristopherNeural", -0.04, "+0Hz"), "narrator-warm": ("en-US-AndrewMultilingualNeural", -0.02, "+0Hz"),
    "male-deep": ("en-US-GuyNeural", 0.0, "-4Hz"), "male-warm": ("en-US-BrianMultilingualNeural", 0.0, "+0Hz"),
    "male-young": ("en-US-EricNeural", 0.04, "+6Hz"), "female-warm": ("en-US-JennyNeural", 0.0, "+0Hz"),
    "female-bright": ("en-US-AvaMultilingualNeural", 0.04, "+2Hz"), "child": ("en-US-AnaNeural", 0.06, "+0Hz"),
    "elder-male": ("en-US-RogerNeural", -0.08, "-6Hz"), "elder-female": ("en-GB-SoniaNeural", -0.08, "-2Hz"),
}
HOP = 1 / 30


async def edge_one(text, voice, rate, pitch, retries=3):
    import edge_tts
    last = None
    for attempt in range(retries):
        audio = bytearray()
        try:
            async def pull():
                async for ch in edge_tts.Communicate(text, voice, rate=f"{round((rate - 1) * 100):+d}%", pitch=pitch).stream():
                    if ch["type"] == "audio":
                        audio.extend(ch["data"])
            await asyncio.wait_for(pull(), 60)
            if audio:
                return bytes(audio)
            last = RuntimeError("the voice returned no audio")
        except Exception as err:
            last = err
        await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Edge voice {voice} failed after {retries} tries: {last}")


def mouth_runs(pcm, sr=narrate.SR):
    """[[seconds, state]] with state 0 closed, 1 small, 2 wide, changing at most every other frame."""
    import numpy as np
    hop = int(sr * HOP)
    n = len(pcm) // hop
    if n == 0:
        return [[0, 0]]
    db = 20 * np.log10(np.sqrt((pcm[: n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9)
    top = float(np.percentile(db, 90))
    state = np.where(db < top - 22, 0, np.where(db < top - 9, 1, 2))
    runs, last, hold = [], -1, 0
    for i, s in enumerate(state):
        if s != last and (hold >= 2 or last == -1):
            runs.append([round(i * HOP, 3), int(s)])
            last, hold = int(s), 0
        hold += 1
    return runs


def speak(job):
    import numpy as np
    import soundfile as sf
    out = Path(job["out_dir"])
    parts = out / "parts"
    parts.mkdir(parents=True, exist_ok=True)
    base = float(job.get("rate", 1.0))
    plan = []                                                    # (line index, sentence index, text, kind)
    for li, ln in enumerate(job["lines"]):
        for si, (text, kind) in enumerate(narrate.split_sentences(ln["text"])):
            plan.append((li, si, text, kind))

    async def fetch():
        gate = asyncio.Semaphore(6)

        async def one(li, text):
            voice, off, pitch = VOICE_MAP[job["lines"][li]["voice_type"]]
            async with gate:
                return await edge_one(text, voice, base * (1 + off), pitch)
        return await asyncio.gather(*(one(li, text) for li, _, text, _ in plan))
    mp3s = asyncio.run(fetch())
    pcm_of = {}
    for (li, si, text, kind), mp3 in zip(plan, mp3s):
        src = parts / f"{li}-{si}.mp3"
        src.write_bytes(mp3)
        pcm, _ = narrate.trim(narrate.to_pcm(src, job["ffmpeg"]))
        pcm_of[(li, si)] = (narrate.level_match(pcm), text, kind)
    report = []
    for li, ln in enumerate(job["lines"]):
        sents = sorted(k for k in pcm_of if k[0] == li)
        pieces, spans, t = [], [], 0.0
        for n, key in enumerate(sents):
            pcm, text, kind = pcm_of[key]
            gap = narrate.pause_after(kind, n, n == len(sents) - 1, 0.8)
            spans.append({"text": text, "start": round(t, 3), "end": round(t + len(pcm) / narrate.SR, 3)})
            pieces += [pcm, np.zeros(int(gap * narrate.SR), dtype="float32")]
            t += len(pcm) / narrate.SR + gap
        audio = np.concatenate(pieces) if pieces else np.zeros(int(0.2 * narrate.SR), dtype="float32")
        sf.write(str(out / f"{ln['id']}.wav"), audio, narrate.SR, subtype="PCM_16")
        report.append({"id": ln["id"], "dur": round(len(audio) / narrate.SR, 3), "mouth": mouth_runs(audio), "sentences": spans})
    (out / "lines.json").write_text(json.dumps(report), encoding="utf-8")
    return {"lines": len(report), "seconds": round(sum(r["dur"] for r in report), 1)}


if __name__ == "__main__":
    print(json.dumps(speak(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))))
