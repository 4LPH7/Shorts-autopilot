"""Narration worker: script -> clean narration with exact word timing and a check against the script.

    python narrate.py job.json      # writes voice.wav, words.json, sentences.json, qa.json into the job's out_dir

Runs in the isolated audio environment (.venv-audio): Edge neural voices (free) or Kokoro (local, offline) speak the
script sentence by sentence, so the pauses are chosen here and not by the voice, one bad sentence can be redone alone,
and every word gets a real start and end time (Edge reports them; Whisper measures them for Kokoro). Whisper also
listens to the result and compares it with the script, so a garbled sentence is caught.

The pure helpers at the top need only the standard library, so the main engine's self-test can import them."""

import asyncio
import json
import re
import subprocess
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

SR = 48000                                   # every sentence is brought to 48 kHz mono before it is joined
PAUSE = {".": 0.30, "!": 0.26, "?": 0.40, "…": 0.45, "p": 0.55}     # silence after a sentence, by its ending
HOOK_PAUSE = 0.42                            # the first sentence is the hook: give it room to land
NUMBER_WORDS = set("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
                   "sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred "
                   "thousand million billion percent dollar dollars cents point".split())


# ---- Text (pure) -----------------------------------------------------------------------

def clean_spoken(text):
    """What the voice should read: no emoji, markdown, stage directions or stray symbols."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", text)               # [scene notes] and (asides)
    text = text.replace("—", ", ").replace("–", ", ").replace(" - ", ", ")      # a dash is a short pause
    text = re.sub(r"[*_#`>~|]+", " ", text)
    text = re.sub(r"[^\w\s$€£%'’.,;:!?&+/…\"“”-]", " ", text)       # emoji and other symbols
    text = re.sub(r"[ \t]+", " ", text).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", text)


def split_sentences(text):
    """[(sentence, kind)] with kind one of . ! ? … p ('p' = ends a paragraph). Order and wording are kept."""
    out = []
    paragraphs = [p for p in re.split(r"\n\s*\n|\n", text) if p.strip()]
    for pi, para in enumerate(paragraphs):
        para = clean_spoken(para)
        parts = re.split(r"(?<=[.!?…])[\"”')\]]*\s+(?=[\"“'(\[]?[A-Z0-9$€£])", para)
        parts = [p.strip() for p in parts if re.search(r"\w", p)]
        for si, part in enumerate(parts):
            end = part.rstrip("\"”')]")[-1:]
            kind = end if end in ".!?…" else "."
            if si == len(parts) - 1 and pi < len(paragraphs) - 1:
                kind = "p"
            out.append((part, kind))
    return out


def pause_after(kind, index, last, scale=1.0):
    """Seconds of silence after a sentence: the hook gets extra room, the last sentence none."""
    if last:
        return 0.0
    return round((HOOK_PAUSE if index == 0 and kind in ".!?…" else PAUSE.get(kind, 0.3)) * scale, 3)


def norm_token(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


def script_tokens(sentence):
    """The words of a sentence as the captions will show them (punctuation stripped from the edges)."""
    edge = ".,;:!?\"“”()[]…"
    return [w.strip(edge) for w in sentence.split() if w.strip(edge)]


# ---- Timing (pure) ------------------------------------------------------------------------

def map_words(script_words, heard):
    """Give every script word a (start, end): `heard` is [(word, start, end)] from the voice or from Whisper.
    Words are matched by spelling; the rest are placed in proportion between their matched neighbours."""
    n = len(script_words)
    if n == 0:
        return []
    if not heard:
        return [None] * n
    a = [norm_token(w) for w in script_words]
    b = [norm_token(w) for w, _, _ in heard]
    times = [None] * n
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal" or (tag == "replace" and i2 - i1 == j2 - j1):
            for k in range(i2 - i1):
                times[i1 + k] = (heard[j1 + k][1], heard[j1 + k][2])
    start0, end0 = heard[0][1], heard[-1][2]
    i = 0
    while i < n:                                            # fill gaps between matched neighbours
        if times[i] is not None:
            i += 1
            continue
        j = i
        while j < n and times[j] is None:
            j += 1
        lo = times[i - 1][1] if i > 0 else start0
        hi = times[j][0] if j < n else end0
        hi = max(hi, lo)
        weights = [len(norm_token(script_words[k])) + 1 for k in range(i, j)]
        total, t = sum(weights), lo
        for k, wt in zip(range(i, j), weights):
            t1 = t + (hi - lo) * wt / total
            times[k] = (round(t, 3), round(t1, 3))
            t = t1
        i = j
    return times


def spoken_match(script, heard_text):
    """0..1: how much of the script sentence Whisper heard. Numbers may be heard as words, so number words and
    digits are ignored on both sides."""
    def toks(t):
        out = []
        for w in re.findall(r"[A-Za-z0-9']+", t.lower().replace("%", " percent ").replace("$", " dollars ")):
            if w not in NUMBER_WORDS and not any(c.isdigit() for c in w):
                out.append(w.replace("'", ""))
        return out
    a, b = toks(script), toks(heard_text)
    if not a:
        return 1.0
    return round(SequenceMatcher(None, a, b, autojunk=False).ratio(), 3)


# ---- Audio: synthesis, decoding, trimming (needs the audio environment) ------------------------

def to_pcm(src, ffmpeg, sr=SR):
    """A sound file as float32 mono samples at `sr` (ffmpeg does the decoding and resampling)."""
    import numpy as np
    r = subprocess.run([ffmpeg, "-v", "error", "-i", str(src), "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"],
                       capture_output=True, stdin=subprocess.DEVNULL)
    if r.returncode or not r.stdout:
        raise RuntimeError(f"couldn't decode {src}: {r.stderr[-200:].decode(errors='replace')}")
    return np.frombuffer(r.stdout, dtype=np.float32).copy()


def trim(x, sr=SR, floor_db=-48.0, lead=0.03, tail=0.08):
    """Cut the silence a voice leaves before and after a sentence. Returns (samples, seconds cut from the start)."""
    import numpy as np
    win = int(sr * 0.01)
    n = len(x) // win
    if n == 0:
        return x, 0.0
    rms = np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1) + 1e-12)
    live = np.where(20 * np.log10(rms) > floor_db)[0]
    if len(live) == 0:
        return x, 0.0
    a = max(0, int(live[0] * win - lead * sr))
    b = min(len(x), int((live[-1] + 1) * win + tail * sr))
    return x[a:b], a / sr


def level_match(x, target_db=-21.0, max_db=4.0):
    """Even out sentence loudness: bring the speech level (not the pauses) to about target_db, within +-max_db."""
    import numpy as np
    win = int(SR * 0.02)
    n = len(x) // win
    if n == 0:
        return x
    db = 20 * np.log10(np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1) + 1e-12))
    voiced = db[db > -45]
    if len(voiced) == 0:
        return x
    gain = float(np.clip(target_db - np.mean(voiced), -max_db, max_db))
    y = x * (10 ** (gain / 20))
    fade = int(SR * 0.008)                                  # tiny fades so joins never click
    y[:fade] *= np.linspace(0, 1, fade)
    y[-fade:] *= np.linspace(1, 0, fade)
    return y.astype("float32")


async def edge_sentence(text, voice, rate, retries=3):
    """One sentence from an Edge neural voice: (mp3 bytes, [(word, start, end)]) with real word timing."""
    import edge_tts
    pct = f"{round((rate - 1) * 100):+d}%"
    last = None
    for attempt in range(retries):
        audio, words = bytearray(), []
        try:
            async def pull():
                comm = edge_tts.Communicate(text, voice, rate=pct, boundary="WordBoundary")
                async for ch in comm.stream():
                    if ch["type"] == "audio":
                        audio.extend(ch["data"])
                    elif ch["type"] == "WordBoundary":
                        words.append((ch["text"], ch["offset"] / 1e7, (ch["offset"] + ch["duration"]) / 1e7))
            await asyncio.wait_for(pull(), 60)
            if audio:
                return bytes(audio), words
            last = RuntimeError("the voice returned no audio")
        except Exception as err:                            # network hiccup: wait and try again
            last = err
        await asyncio.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Edge voice {voice} failed after {retries} tries: {last}")


async def edge_all(sentences, voice, rate, parallel=4):
    gate = asyncio.Semaphore(parallel)

    async def one(text):
        async with gate:
            return await edge_sentence(text, voice, rate)
    return await asyncio.gather(*(one(t) for t, _ in sentences))


_MODELS = {}


def kokoro_sentence(text, voice, rate, models):
    """One sentence from Kokoro running on this PC: (float32 samples, sample rate). No network, no word timing."""
    if "kokoro" not in _MODELS:
        from kokoro_onnx import Kokoro
        d = Path(models) / "kokoro"
        _MODELS["kokoro"] = Kokoro(str(d / "kokoro-v1.0.onnx"), str(d / "voices-v1.0.bin"))
    lang = "en-gb" if voice[:1] == "b" else "en-us"
    samples, sr = _MODELS["kokoro"].create(text, voice=voice, speed=rate, lang=lang)
    return samples.astype("float32"), sr


def whisper_listen(pcm48, models, name="small.en"):
    """What Whisper hears: ([(word, start, end)], text). Word times are relative to the start of `pcm48`."""
    if name not in _MODELS:
        from faster_whisper import WhisperModel
        root = Path(models) / "hf"
        _MODELS[name] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=8,
                                     download_root=str(root), local_files_only=root.exists())
    n = len(pcm48) // 3 * 3
    pcm16 = pcm48[:n].reshape(-1, 3).mean(axis=1).astype("float32")         # 48 kHz -> 16 kHz for Whisper
    segments, _ = _MODELS[name].transcribe(pcm16, language="en", word_timestamps=True, beam_size=2,
                                           condition_on_previous_text=False, vad_filter=False, temperature=0.0)
    words, text = [], []
    for seg in segments:
        text.append(seg.text)
        words += [(w.word.strip(), float(w.start), float(w.end)) for w in (seg.words or []) if w.word.strip()]
    return words, " ".join(text).strip()


# ---- The job -------------------------------------------------------------------------------

def synth_sentence(i, text, job, tmp, raw=None):
    """Speak one sentence. Returns (samples, native_words or None): trimmed, level-matched, word times shifted to
    the trimmed start. `raw` is an already-fetched Edge result (the parallel first pass)."""
    import soundfile as sf
    ffmpeg, voice, rate = job["ffmpeg"], job["voice"], float(job.get("rate", 1.0))
    if job["engine"] == "edge":
        mp3, words = raw if raw is not None else asyncio.run(edge_sentence(text, voice, rate))
        src = Path(tmp) / f"s{i}.mp3"
        src.write_bytes(mp3)
        pcm, cut = trim(to_pcm(src, ffmpeg))
        native = [(w, max(0.0, s - cut), max(0.0, e - cut)) for w, s, e in words]
        return level_match(pcm), native
    if job["engine"] == "kokoro":
        samples, sr = kokoro_sentence(text, voice, rate, job["models_dir"])
        src = Path(tmp) / f"s{i}.wav"
        sf.write(str(src), samples, sr)
        pcm, _ = trim(to_pcm(src, ffmpeg))
        return level_match(pcm), None
    raise ValueError(f"unknown voice engine: {job['engine']}")


def narrate(job):
    """Speak job['script'] and write voice.wav, words.json, sentences.json and qa.json into job['out_dir']."""
    import numpy as np
    import soundfile as sf
    t0 = time.time()
    out = Path(job["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "parts"
    tmp.mkdir(exist_ok=True)
    sentences = split_sentences(job["script"])
    if not sentences:
        raise ValueError("the script has no sentences to speak")
    raw = None
    if job["engine"] == "edge":                              # Edge answers are slow and independent: ask in parallel
        raw = asyncio.run(edge_all(sentences, job["voice"], float(job.get("rate", 1.0))))
    check = bool(job.get("check", True))
    scale = float(job.get("pause_scale", 1.0))
    pieces, words_out, sents_out, retried, t = [], [], [], [], 0.0
    for i, (text, kind) in enumerate(sentences):
        best = None
        for attempt in range(2):                             # a garbled sentence is spoken once more, then the better one is kept
            pcm, native = synth_sentence(i, text, job, tmp, raw[i] if raw and attempt == 0 else None)
            heard, heard_text, match = native, "", 1.0
            if native is None or check:
                listened, heard_text = whisper_listen(pcm, job["models_dir"])
                match = spoken_match(text, heard_text)
                heard = listened if native is None else native
            if best is None or match > best[3]:
                best = (pcm, heard, heard_text, match)
            if match >= 0.8 or job["engine"] != "edge":
                break
            retried.append(i)
        pcm, heard, heard_text, match = best
        toks = script_tokens(text)
        for tok, span in zip(toks, map_words(toks, heard)):
            if span is not None:
                words_out.append({"text": tok, "start": round(t + span[0], 3), "end": round(t + span[1], 3), "sentence": i})
        dur = len(pcm) / SR
        sents_out.append({"text": text, "kind": kind, "start": round(t, 3), "end": round(t + dur, 3),
                          "match": match, "heard": heard_text})
        gap = pause_after(kind, i, i == len(sentences) - 1, scale)
        pieces += [pcm, np.zeros(int(gap * SR), dtype="float32")]
        t += dur + gap
    audio = np.concatenate(pieces)
    sf.write(str(out / "voice.wav"), audio, SR, subtype="PCM_16")
    (out / "words.json").write_text(json.dumps(words_out, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "sentences.json").write_text(json.dumps(sents_out, ensure_ascii=False, indent=1), encoding="utf-8")
    matches = [s["match"] for s in sents_out]
    qa = {"engine": job["engine"], "voice": job["voice"], "rate": job.get("rate", 1.0), "seconds": round(len(audio) / SR, 2),
          "sentences": len(sents_out), "words": len(words_out), "mean_match": round(sum(matches) / len(matches), 3),
          "worst_match": min(matches), "doubtful": [i for i, m in enumerate(matches) if m < 0.8], "retried": retried,
          "native_timing": job["engine"] == "edge", "work_seconds": round(time.time() - t0, 1)}
    (out / "qa.json").write_text(json.dumps(qa, indent=1), encoding="utf-8")
    return qa


if __name__ == "__main__":
    print(json.dumps(narrate(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))))
