"""Long-video voices: every line of the screenplay spoken by its character's own voice: an Edge neural voice (free), or
a premium voice from Gemini, ElevenLabs or MiniMax (job["engine"], through genmedia.py), one voice per character type.

    python lf_voice.py job.json      # runs in .venv-audio, like narrate.py
job = {"lines": [{"id", "voice_type", "text"}], "out_dir", "ffmpeg", "rate", "engine"?, "style"?, "parallel"?}; writes
out_dir/<id>.wav (48 kHz mono) and out_dir/lines.json:
[{"id", "dur", "mouth": [[t, "A".."H" | "X"]], "accents": [t], "sentences": [{"text", "start", "end"}]}].
The mouth track is lip sync: every word's mouth shapes (from its spelling) laid over the word's time in the audio (Edge
and ElevenLabs report word times; for other voices they are estimated from the voiced frames), closed wherever the voice
is quiet. Films voiced before this have [[t, 0-3]] loudness states, which the animation kit still plays.
The top of the file is stdlib only: the main engine imports VOICE_MAP from it."""

import asyncio
import json
import re
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
# The same cast in the premium engines: type -> (voice, speed offset). Gemini voices are told who they are in words.
PREMIUM_MAP = {
    "gemini": {"narrator-deep": ("Charon", -0.03), "narrator-warm": ("Sulafat", -0.02), "male-deep": ("Algenib", 0.0),
               "male-warm": ("Orus", 0.0), "male-young": ("Puck", 0.04), "female-warm": ("Aoede", 0.0),
               "female-bright": ("Leda", 0.03), "child": ("Zephyr", 0.05), "elder-male": ("Gacrux", -0.06),
               "elder-female": ("Vindemiatrix", -0.05)},
    "elevenlabs": {"narrator-deep": ("George", -0.03), "narrator-warm": ("Brian", -0.02), "male-deep": ("Daniel", 0.0),
                   "male-warm": ("Adam", 0.0), "male-young": ("Liam", 0.04), "female-warm": ("Rachel", 0.0),
                   "female-bright": ("Matilda", 0.03), "child": ("Bella", 0.05), "elder-male": ("George", -0.06),
                   "elder-female": ("Matilda", -0.05)},
    "minimax": {"narrator-deep": ("English_Deep-VoicedGentleman", -0.03), "narrator-warm": ("English_expressive_narrator", -0.02),
                "male-deep": ("English_magnetic_voiced_man", 0.0), "male-warm": ("English_Trustworthy_Man", 0.0),
                "male-young": ("English_Persuasive_Man", 0.04), "female-warm": ("English_CalmWoman", 0.0),
                "female-bright": ("English_Graceful_Lady", 0.03), "child": ("English_Graceful_Lady", 0.05),
                "elder-male": ("English_Deep-VoicedGentleman", -0.06), "elder-female": ("English_Wiselady", -0.05)},
}
CHARACTER_STYLE = {"male-deep": "a deep-voiced, grounded man", "male-warm": "a warm, friendly man", "male-young": "an energetic young man",
                   "female-warm": "a warm, kind woman", "female-bright": "a bright, lively young woman", "child": "a curious, excited child",
                   "elder-male": "a slow, kindly old man", "elder-female": "a gentle, wise old woman"}
HOP = 1 / 30


def premium_fetch(plan, job):
    """Every sentence of every line from the premium engine in job['engine']:
    {(line, sentence): (sound file, tempo, [(word, start, end)] or None)}. A character's emotion goes along in words
    (Gemini) or as the engine's emotion setting (MiniMax); ElevenLabs reports word times."""
    from concurrent.futures import ThreadPoolExecutor
    import genmedia
    engine, base = job["engine"], float(job.get("rate", 1.0))
    parts = Path(job["out_dir"]) / "parts"
    voices = PREMIUM_MAP[engine]

    def one(item):
        li, si, text, _ = item
        line = job["lines"][li]
        vtype, emo = line["voice_type"], line.get("emo", "")
        voice, off = voices.get(vtype, voices["narrator-warm"])
        rate = base * (1 + off)
        dest = parts / f"{li}-{si}"
        if engine == "gemini":
            feel = f", {EMO_WORDS[emo]}" if emo in EMO_WORDS else ""
            style = job.get("style", "") if vtype.startswith("narrator") else f"Speak in character as {CHARACTER_STYLE.get(vtype, 'a person')}{feel}, naturally, like dialogue in a film."
            return (li, si), genmedia.gemini_tts(text, dest.with_suffix(".wav"), voice, style, job.get("model") or genmedia.GEMINI_TTS), rate, None
        if engine == "elevenlabs":
            src, words = genmedia.elevenlabs_tts(text, dest.with_suffix(".mp3"), voice, job.get("model") or genmedia.ELEVEN_MODEL, rate)
            return (li, si), src, 1.0, words
        return (li, si), genmedia.minimax_tts(text, dest.with_suffix(".mp3"), voice, job.get("model") or genmedia.MINIMAX_MODEL, rate,
                                              EMO_MINIMAX.get(emo, "")), 1.0, None
    try:
        with ThreadPoolExecutor(max_workers=max(1, int(job.get("parallel", 1)))) as pool:
            return {key: (src, tempo, words) for key, src, tempo, words in pool.map(one, plan)}
    except genmedia.GenError as err:
        if err.code == 429 and engine == "gemini":
            raise RuntimeError("Gemini's free tier allows 10 voice requests a day per model and a film needs one per sentence: "
                               "enable billing on the key, or choose another voice engine for films") from err
        raise


# A character's emotion colours their voice a little (the narrator stays even): Edge (speed factor, pitch shift in Hz),
# Gemini (how to say it, in words) and MiniMax (its emotion setting).
EMO_PROSODY = {"happy": (1.04, 3), "surprised": (1.05, 4), "scared": (1.06, 4), "angry": (1.03, 1), "sad": (0.93, -3),
               "thinking": (0.95, -1)}
EMO_WORDS = {"happy": "cheerfully", "surprised": "with real surprise", "scared": "nervously, a little scared",
             "angry": "with frustration", "sad": "quietly and sadly", "thinking": "thoughtfully, working it out"}
EMO_MINIMAX = {"happy": "happy", "surprised": "surprised", "scared": "fearful", "angry": "angry", "sad": "sad"}


def edge_voice(line, base):
    """(Edge voice, rate, pitch) for one line: the character's voice, coloured by the line's emotion."""
    voice, off, pitch = VOICE_MAP[line["voice_type"]]
    k, shift = EMO_PROSODY.get(line.get("emo"), (1.0, 0))
    return voice, base * (1 + off) * k, f"{int(pitch[:-2]) + shift:+d}Hz"


# ---- Lip sync ------------------------------------------------------------------------------------------------
# Mouth shapes as Rhubarb Lip Sync and the Preston Blair chart name them: A lips closed (M B P), B teeth just apart
# (most consonants, EE), C open (EH, AE), D wide open (AA), E rounded (O, ER), F puckered (OO, W), G lower lip under the
# teeth (F V), H tongue up (L, TH), X rest (the face's own closed mouth for its mood). Spelling rules, not a phoneme
# dictionary: a cartoon mouth needs the right shape family at the right moment, not a linguist.
SPELLING = [("tch", "B"), ("th", "H"), ("ph", "G"), ("wh", "F"), ("qu", "BF"), ("oo", "F"), ("ou", "E"), ("ow", "EF"),
            ("oy", "EB"), ("oi", "EB"), ("aw", "E"), ("au", "E"), ("ee", "B"), ("ea", "B"), ("ie", "B"), ("ey", "B"),
            ("ar", "D"), ("er", "E"), ("ir", "E"), ("ur", "E"), ("or", "E"), ("ew", "F"), ("ue", "F"), ("ch", "B"),
            ("sh", "B"), ("ng", "B"), ("ck", "B")]
LETTER = {"a": "C", "e": "C", "i": "C", "o": "E", "u": "C", "y": "B", "b": "A", "m": "A", "p": "A", "f": "G", "v": "G",
          "l": "H", "w": "F"}                     # any other letter: B; h is breath and makes no shape of its own
VOWEL_SHAPES, FPS = set("CDEF"), 30
SMALL_WORDS = set("a an the and or but so of to in on at for with from into than then this that these those there "
                  "is are was were be been it its i you he she we they me him her us them my your our their".split())


def word_shapes(word):
    """The mouth shapes of one written word, in order, each with how long it holds relative to the others."""
    w = re.sub(r"[^a-z0-9]", "", word.lower())
    if any(ch.isdigit() for ch in w):
        return [("C", 1.6), ("B", 1.0)] * sum(ch.isdigit() for ch in w)        # a number is spoken as words
    if len(w) > 3 and w.endswith("e") and w[-2] not in "aeiouy":
        w = w[:-1]                                                               # a silent final e
    out, i = [], 0
    while i < len(w):
        for spelt, shapes in SPELLING:
            if w.startswith(spelt, i):
                i += len(spelt)
                break
        else:
            shapes, i = ("" if w[i] == "h" else LETTER.get(w[i], "B")), i + 1
        for s in shapes:
            if not out or out[-1][0] != s:                                       # a double letter is one shape
                out.append((s, 1.6 if s in VOWEL_SHAPES else 1.0))
    return out or [("C", 1.0)]


def frame_db(pcm, sr=narrate.SR):
    """Loudness in dB of every 1/30 s of `pcm`, and the level of its loud parts (the 90th percentile)."""
    import numpy as np
    hop = int(sr * HOP)
    n = len(pcm) // hop
    if n == 0:
        return np.zeros(0), 0.0
    db = 20 * np.log10(np.sqrt((pcm[: n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-9)
    return db, float(np.percentile(db, 90))


def visemes(words, pcm, sr=narrate.SR):
    """[[seconds, shape]] for one line: every word's shapes spread over its time; the mouth at rest wherever the voice
    is quiet for a tenth of a second; every shape held two frames or more (a brief M/B/P closure is kept); all of it one
    frame early, because the eye expects the lips to move just before the sound."""
    db, top = frame_db(pcm, sr)
    n = max(1, len(db))
    frame = ["X"] * n
    for w, a, b in words:
        shapes = word_shapes(w)
        total, t = sum(k for _, k in shapes), a
        for s, k in shapes:
            t2 = t + (b - a) * k / total
            for f in range(int(t * FPS), min(n, max(int(t * FPS) + 1, round(t2 * FPS)))):
                frame[f] = s
            t = t2
    quiet = [d < top - 30 for d in db]
    for f in range(len(quiet)):
        if quiet[f] and (sum(quiet[max(0, f - 2):f + 1]) == 3 or sum(quiet[f:f + 3]) == 3):
            frame[f] = "X"
    frame = frame[1:] + ["X"]
    runs = []                                                                    # [first frame, shape]
    for f, s in enumerate(frame):
        if runs and runs[-1][1] == s:
            continue
        if runs and f - runs[-1][0] < 2 and runs[-1][1] != "A":
            start = runs.pop()[0]                                                # a one-frame flicker gives way
            if runs and runs[-1][1] == s:
                continue
            runs.append([start, s])
            continue
        runs.append([f, s])
    return [[round(f / FPS, 3), s] for f, s in runs]


def estimate_words(text, pcm, sr=narrate.SR):
    """Word times for a voice that reports none: the words laid over the voiced frames of the sentence, each in
    proportion to its letters (Edge and ElevenLabs give real times; this is for Gemini, MiniMax and odd cases)."""
    words = re.findall(r"[A-Za-z0-9']+", text)
    db, top = frame_db(pcm, sr)
    voiced = [f for f, d in enumerate(db) if d > top - 30]
    if not words or not voiced:
        return []
    weights = [len(w) + 1 for w in words]
    total, acc, out = sum(weights), 0, []
    for w, k in zip(words, weights):
        i0 = min(len(voiced) - 1, int(acc / total * len(voiced)))
        acc += k
        i1 = min(len(voiced) - 1, max(i0, int(acc / total * len(voiced)) - 1))
        out.append((w, voiced[i0] * HOP, (voiced[i1] + 1) * HOP))
    return out


def accents(words):
    """When the speaker's head gives a small nod: the onsets of strong words, at most one every 0.7 s."""
    out = []
    for w, a, _ in words:
        bare = re.sub(r"[^a-z]", "", w.lower())
        if len(bare) >= 4 and bare not in SMALL_WORDS and (not out or a - out[-1] >= 0.7):
            out.append(round(a, 3))
    return out


def mouth_runs(pcm, sr=narrate.SR):
    """[[seconds, state]] with state 0 closed, 1 small, 2 wide, changing at most every other frame: the mouth read off
    loudness alone, for a line with no words to time."""
    import numpy as np
    db, top = frame_db(pcm, sr)
    if len(db) == 0:
        return [[0, 0]]
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
            voice, rate, pitch = edge_voice(job["lines"][li], base)
            async with gate:
                return await narrate.edge_sentence(text, voice, rate, pitch=pitch)
        return await asyncio.gather(*(one(li, text) for li, _, text, _ in plan))
    fetched = {}                                                 # (line, sentence) -> (sound file, tempo, words or None)
    if job.get("engine", "edge") in PREMIUM_MAP:
        fetched = premium_fetch(plan, job)
    else:
        for (li, si, _, _), (mp3, words) in zip(plan, asyncio.run(fetch())):
            src = parts / f"{li}-{si}.mp3"
            src.write_bytes(mp3)
            fetched[(li, si)] = (src, 1.0, words or None)        # a sentence Edge gave no word times for is estimated
    pcm_of = {}
    for li, si, text, kind in plan:
        src, tempo, words = fetched[(li, si)]
        pcm, cut = narrate.trim(narrate.to_pcm(src, job["ffmpeg"], tempo=tempo))
        if words:                                                # word times follow the trim and the tempo change
            words = [(w, max(0.0, s / tempo - cut), max(0.0, e / tempo - cut)) for w, s, e in words]
        pcm_of[(li, si)] = (narrate.level_match(pcm), text, kind, words or estimate_words(text, pcm))
    report = []
    for li, ln in enumerate(job["lines"]):
        sents = sorted(k for k in pcm_of if k[0] == li)
        pieces, spans, said, t = [], [], [], 0.0
        for n, key in enumerate(sents):
            pcm, text, kind, words = pcm_of[key]
            gap = narrate.pause_after(kind, n, n == len(sents) - 1, 0.8)
            spans.append({"text": text, "start": round(t, 3), "end": round(t + len(pcm) / narrate.SR, 3)})
            said += [(w, t + a, t + b) for w, a, b in words]
            pieces += [pcm, np.zeros(int(gap * narrate.SR), dtype="float32")]
            t += len(pcm) / narrate.SR + gap
        audio = np.concatenate(pieces) if pieces else np.zeros(int(0.2 * narrate.SR), dtype="float32")
        sf.write(str(out / f"{ln['id']}.wav"), audio, narrate.SR, subtype="PCM_16")
        report.append({"id": ln["id"], "dur": round(len(audio) / narrate.SR, 3), "mouth": visemes(said, audio) if said else mouth_runs(audio),
                       "accents": accents(said), "sentences": spans})
    (out / "lines.json").write_text(json.dumps(report), encoding="utf-8")
    return {"lines": len(report), "seconds": round(sum(r["dur"] for r in report), 1)}


if __name__ == "__main__":
    print(json.dumps(speak(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))))
