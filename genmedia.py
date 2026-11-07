"""Generative media behind one small API: still images for the picture track, short image-to-video clips, premium
voices, with a cost ledger and a per-video budget. Standard library only (urllib), so narrate.py and lf_voice.py
(which run in .venv-audio) can import it as well as the main engine.

Providers and where their keys come from (environment first, then MoneyPrinterTurbo's config.toml [app] table):
    muapi        MUAPI_API_KEY        / muapi_api_key          images (z-image-turbo, nano-banana-2-lite, ...),
                                                               image-to-video (seedance-lite-i2v, ...), pay per call
    gemini       GEMINI_API_KEY       / gemini_api_key         Gemini TTS voices (works on the free tier) and
                                                               Gemini image models (need billing enabled on the key)
    pollinations POLLINATIONS_API_KEY (optional)               free images, one every 45 s without a key
    elevenlabs   ELEVENLABS_API_KEY   / elevenlabs_api_key     voices with word timing
    minimax      MINIMAX_API_KEY      / minimax_api_key        voices (speech-02-hd)

Every paid call is appended to logs/genmedia.jsonl with its estimated cost, so the Review page and the budget cap can
see what a video cost. Nothing here retries a submission that may already have been billed (MuAPI jobs)."""

import base64
import hashlib
import json
import os
import re
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEDGER = HERE / "logs" / "genmedia.jsonl"
UA = "shorts-autopilot/1.0 (+https://github.com)"

MUAPI_BASE = "https://api.muapi.ai/api/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
ELEVEN_BASE = "https://api.elevenlabs.io/v1"
MINIMAX_BASE = "https://api.minimax.io/v1"
POLLINATIONS = "https://image.pollinations.ai/prompt/"

# Defaults chosen for a faceless explainer channel: cheap, fast, photoreal. Any MuAPI text-to-image endpoint works.
MUAPI_IMAGE = "z-image-turbo"
MUAPI_I2V = "seedance-lite-i2v"
GEMINI_IMAGE = "gemini-2.5-flash-image"
GEMINI_TTS = "gemini-2.5-flash-preview-tts"        # takes a spoken-style instruction; the 3.x TTS models read it aloud
ELEVEN_MODEL = "eleven_multilingual_v2"
MINIMAX_MODEL = "speech-02-hd"

# Estimated USD per call (the ledger records the provider's own figure when it returns one)
EST = {("muapi", "z-image-turbo"): 0.007, ("muapi", "nano-banana-2-lite"): 0.03, ("muapi", "flux-2-pro"): 0.032,
       ("muapi", "seedream-5.0"): 0.0325, ("muapi", "google-imagen4-fast"): 0.02, ("muapi", "nano-banana-2"): 0.06,
       ("muapi", "seedance-lite-i2v"): 0.18, ("muapi", "ltx-2.3-image-to-video"): 0.104,
       ("gemini", "gemini-2.5-flash-image"): 0.039, ("gemini", "gemini-3.1-flash-image"): 0.067,
       ("gemini", "gemini-3-pro-image"): 0.134, ("gemini", GEMINI_TTS): 0.004, ("elevenlabs", ELEVEN_MODEL): 0.02,
       ("minimax", MINIMAX_MODEL): 0.01, ("pollinations", "flux"): 0.0}
# Fields the MuAPI endpoints take (from GET /models); anything else is looked up live and cached for a day
MUAPI_FIELDS = {"z-image-turbo": ["prompt", "width", "height"], "flux-schnell-image": ["prompt", "width", "height"],
                "nano-banana-2-lite": ["prompt", "aspect_ratio"], "nano-banana": ["prompt", "aspect_ratio"],
                "flux-2-pro": ["prompt", "aspect_ratio", "resolution"], "seedream-5.0": ["prompt", "aspect_ratio", "quality"],
                "google-imagen4-fast": ["prompt", "aspect_ratio"], "flux-kontext-pro-t2i": ["prompt", "aspect_ratio"],
                "seedance-lite-i2v": ["prompt", "image_url", "resolution", "duration", "camera_fixed"],
                "ltx-2.3-image-to-video": ["prompt", "image_url", "duration", "resolution"]}

# Gemini's prebuilt voices, with Google's one-word character for each: pick by ear with --audition
GEMINI_VOICES = {"Charon": "informative, deep", "Algenib": "gravelly", "Orus": "firm", "Gacrux": "mature", "Enceladus": "breathy",
                 "Sulafat": "warm", "Iapetus": "clear", "Schedar": "even", "Sadaltager": "knowledgeable", "Rasalgethi": "informative",
                 "Kore": "firm", "Aoede": "breezy", "Leda": "youthful", "Zephyr": "bright", "Puck": "upbeat", "Fenrir": "excitable",
                 "Callirrhoe": "easy-going", "Autonoe": "bright", "Umbriel": "easy-going", "Algieba": "smooth", "Despina": "smooth",
                 "Erinome": "clear", "Laomedeia": "upbeat", "Achernar": "soft", "Alnilam": "firm", "Pulcherrima": "forward",
                 "Achird": "friendly", "Zubenelgenubi": "casual", "Vindemiatrix": "gentle", "Sadachbia": "lively"}
# ElevenLabs premade voices (name -> voice id) and MiniMax system voices, so a name can be typed in Settings
ELEVEN_VOICES = {"George": "JBFqnCBsd6RMkjVDRZzb", "Daniel": "onwK4e9ZLuTAKqWW03F9", "Brian": "nPczCjzI2devNBz1zQrb",
                 "Adam": "pNInz6obpnxaLZgGdU7j", "Liam": "TX3LPaxmHKxFdv7VOQHJ", "Charlie": "IKne3meq5aSn9XLyUdCD",
                 "Rachel": "21m00Tcm4TlvDq8ikWAM", "Bella": "EXAVITQu4vr4xnSDxMaL", "Sarah": "EXAVITQu4vr4xnSDxMaL",
                 "Matilda": "XrExE9yKIg1WjnnlVkGX"}
MINIMAX_VOICES = ["English_expressive_narrator", "English_Trustworthy_Man", "English_magnetic_voiced_man", "English_Graceful_Lady",
                  "English_CalmWoman", "English_Gentle-voiced_man", "English_Deep-VoicedGentleman", "English_Wiselady",
                  "English_CaptivatingStoryteller", "English_Persuasive_Man"]


class GenError(RuntimeError):
    """A provider said no (bad key, no credits, a hard quota): the caller should try the next provider, not again."""

    def __init__(self, message, code=0):
        super().__init__(message)
        self.code = code


class BudgetExceeded(GenError):
    pass


# ---- Keys and config --------------------------------------------------------------------------------

def mpt_dir():
    env = HERE / "env.bat"
    if env.exists():
        m = re.search(r'^\s*set\s+"?MPT_DIR\s*=\s*([^"\r\n]+)', env.read_text(encoding="utf-8", errors="replace"), re.M | re.I)
        if m and m.group(1).strip():
            return Path(m.group(1).strip())
    return Path(os.environ.get("MPT_DIR", r"D:\MPT"))


_CONFIG = {}


def mpt_app_config():
    """MoneyPrinterTurbo's [app] table (where the Setup tab saves keys), read once per process."""
    if "app" not in _CONFIG:
        app = {}
        try:
            import tomllib
            app = tomllib.loads((mpt_dir() / "config.toml").read_text(encoding="utf-8")).get("app", {})
        except Exception:
            pass
        _CONFIG["app"] = app
    return _CONFIG["app"]


KEY_SOURCES = {"gemini": (("GEMINI_API_KEY", "GOOGLE_API_KEY"), ("gemini_api_key",)),
               "muapi": (("MUAPI_API_KEY",), ("muapi_api_key",)),
               "elevenlabs": (("ELEVENLABS_API_KEY", "ELEVEN_API_KEY"), ("elevenlabs_api_key",)),
               "minimax": (("MINIMAX_API_KEY",), ("minimax_api_key",)),
               "pollinations": (("POLLINATIONS_API_KEY",), ("pollinations_api_key",))}


def key_for(provider):
    """The API key for a provider, or '' (pollinations needs none)."""
    envs, keys = KEY_SOURCES[provider]
    for name in envs:
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    app = mpt_app_config()
    for k in keys:
        v = app.get(k)
        if isinstance(v, list):
            v = v[0] if v else ""
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def has(provider):
    return provider == "pollinations" or bool(key_for(provider))


# ---- HTTP -------------------------------------------------------------------------------------------

def http(method, url, headers=None, data=None, timeout=120, retries=3, retry_on=(429, 500, 502, 503, 504)):
    """(status, body bytes, headers). Retries transient failures with backoff; raises GenError on a final 4xx/5xx."""
    last = None
    tries = max(retries, 6) if 429 in retry_on else retries         # a rate limit is worth waiting out a few times
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method=method, headers={"User-Agent": UA, **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as err:
            body = err.read()
            text = body[:1200].decode("utf-8", "replace")
            if err.code == 429 and ("limit: 0" in text or "INSUFFICIENT" in text.upper() or "PerDay" in text or "per day" in text):
                raise GenError(f"HTTP 429: {text[:200]}", 429)      # a hard quota: waiting changes nothing
            can_retry = err.code in retry_on and attempt < (tries if err.code == 429 else retries) - 1
            if can_retry:
                wait = _retry_after(text, err.headers) or (6.0 * (attempt + 1) if err.code == 429 else 2.0 * (attempt + 1))
                time.sleep(min(wait, 75))
                last = GenError(f"HTTP {err.code}: {text[:200]}", err.code)
                continue
            raise GenError(f"HTTP {err.code}: {text[:300]}", err.code)
        except (urllib.error.URLError, TimeoutError, OSError) as err:
            last = GenError(f"{type(err).__name__}: {err}")
            if attempt < retries - 1:
                time.sleep(2.0 * (attempt + 1))
    raise last or GenError("request failed")


def _retry_after(text, headers):
    """Seconds a service asked us to wait: Pollinations' 'Retry after Ns', Gemini's retryDelay / 'retry in N.Ns'."""
    m = re.search(r"[Rr]etry after (\d+)s|retryDelay\"?\s*:\s*\"?(\d+)|retry in (\d+(?:\.\d+)?)s", text)
    if m:
        return float(next(g for g in m.groups() if g)) + 1
    try:
        return float(headers.get("Retry-After", "")) if headers else None
    except (TypeError, ValueError):
        return None


def post_json(url, body, headers=None, timeout=120, retries=3):
    status, data, _ = http("POST", url, {"Content-Type": "application/json", **(headers or {})},
                           json.dumps(body).encode("utf-8"), timeout, retries)
    return json.loads(data.decode("utf-8"))


def get_json(url, headers=None, timeout=60, retries=3):
    status, data, _ = http("GET", url, headers, None, timeout, retries)
    return json.loads(data.decode("utf-8"))


def download(url, dest, timeout=300):
    _, data, _ = http("GET", url, None, None, timeout, 2)
    Path(dest).write_bytes(data)
    return Path(dest)


# ---- Ledger and budget -------------------------------------------------------------------------------

def record(kind, provider, model, usd, video="", note=""):
    LEDGER.parent.mkdir(exist_ok=True)
    row = {"t": datetime.now().isoformat(timespec="seconds"), "video": video, "kind": kind, "provider": provider,
           "model": model, "usd": round(float(usd or 0), 4), "note": note[:120]}
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def spent(video=None, since=None):
    """USD recorded for one video (or for everything since an ISO date / all time)."""
    if not LEDGER.exists():
        return 0.0
    total = 0.0
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if video is not None and row.get("video") != video:
            continue
        if since and row.get("t", "") < since:
            continue
        total += float(row.get("usd") or 0)
    return round(total, 4)


class Budget:
    """A per-video cap on generated media. check() before a paid call, add() after it."""

    def __init__(self, cap_usd, video=""):
        self.cap, self.video, self.used = float(cap_usd), video, 0.0

    def check(self, est):
        if self.cap >= 0 and self.used + est > self.cap + 1e-9:
            raise BudgetExceeded(f"generated media budget reached (${self.used:.2f} + ${est:.3f} > ${self.cap:.2f} a video)")

    def add(self, kind, provider, model, usd, note=""):
        self.used += float(usd or 0)
        record(kind, provider, model, usd, self.video, note)


def estimate(provider, model):
    return EST.get((provider, model), 0.03 if provider != "pollinations" else 0.0)


# ---- MuAPI (submit, poll, download) ----------------------------------------------------------------

def muapi_headers():
    key = key_for("muapi")
    if not key:
        raise GenError("no MuAPI key (Setup tab, or MUAPI_API_KEY)")
    return {"x-api-key": key}


def muapi_fields(endpoint):
    """Input fields of a MuAPI endpoint: the built-in table, else the live catalog (cached a day in logs/)."""
    if endpoint in MUAPI_FIELDS:
        return MUAPI_FIELDS[endpoint]
    cache = HERE / "logs" / "muapi_models.json"
    models = None
    if cache.exists() and time.time() - cache.stat().st_mtime < 86400:
        try:
            models = json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            models = None
    if models is None:
        models = get_json(f"{MUAPI_BASE}/models", muapi_headers()).get("models", [])
        cache.parent.mkdir(exist_ok=True)
        cache.write_text(json.dumps(models), encoding="utf-8")
    for m in models:
        if m.get("endpoint_url") == endpoint:
            if m.get("cost") is not None:
                EST[("muapi", endpoint)] = float(m["cost"])
            return list(m.get("input_fields") or ["prompt"])
    raise GenError(f"MuAPI has no endpoint called {endpoint}")


def muapi_run(endpoint, payload, timeout=900, poll=4.0):
    """Submit one job and wait for it. Returns (outputs: [url], usd charged). A submission is never retried once
    it may have been accepted (it is billable)."""
    headers = muapi_headers()
    sub = post_json(f"{MUAPI_BASE}/{endpoint}", payload, headers, timeout=90, retries=1)
    rid = str(sub.get("request_id") or sub.get("id") or "").strip()
    if not rid:
        raise GenError(f"MuAPI accepted nothing: {str(sub)[:200]}")
    usd = float((sub.get("cost") or {}).get("amount_usd") or 0) or estimate("muapi", endpoint)
    deadline = time.time() + timeout
    while True:
        time.sleep(poll)
        res = get_json(f"{MUAPI_BASE}/predictions/{rid}/result", headers, timeout=60, retries=5)
        status = str(res.get("status", "")).lower()
        if status == "completed":
            outs = res.get("outputs") or res.get("output") or []
            outs = [outs] if isinstance(outs, str) else [o for o in outs if isinstance(o, str)]
            if not outs:
                raise GenError(f"MuAPI job {rid} completed without a file")
            return outs, float((res.get("cost") or {}).get("amount_usd") or usd)
        if status in ("failed", "cancelled", "canceled", "expired", "error"):
            raise GenError(f"MuAPI job {rid} {status}: {str(res.get('error') or res.get('detail') or '')[:200]}")
        if time.time() > deadline:
            raise GenError(f"MuAPI job {rid} still running after {timeout}s")


def muapi_image(prompt, dest, endpoint=MUAPI_IMAGE, aspect="9:16", budget=None, note=""):
    fields = muapi_fields(endpoint)
    # width/height endpoints cap each side at 1536; the frame is upscaled with lanczos when it is filmed
    w, h = {"9:16": (864, 1536), "16:9": (1536, 864), "1:1": (1024, 1024)}.get(aspect, (864, 1536))
    payload = {"prompt": prompt}
    if "aspect_ratio" in fields:
        payload["aspect_ratio"] = aspect
    elif "width" in fields:
        payload.update(width=w, height=h)
    if "num_images" in fields:
        payload["num_images"] = 1
    est = estimate("muapi", endpoint)
    if budget:
        budget.check(est)
    outs, usd = muapi_run(endpoint, payload, timeout=600)
    download(outs[0], dest)
    if budget:
        budget.add("image", "muapi", endpoint, usd, note)
    else:
        record("image", "muapi", endpoint, usd, note=note)
    return Path(dest)


def muapi_upload(path):
    """A public URL for a local file (image-to-video needs one). Tries MuAPI's upload routes, then a data URL."""
    data = Path(path).read_bytes()
    mime = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
    boundary = "----sa" + hashlib.md5(data[:64]).hexdigest()
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{Path(path).name}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    for route in ("files/upload", "upload"):
        try:
            _, raw, _ = http("POST", f"{MUAPI_BASE}/{route}", {**muapi_headers(), "Content-Type": f"multipart/form-data; boundary={boundary}"},
                             body, timeout=120, retries=1)
            res = json.loads(raw.decode("utf-8"))
            url = res.get("url") or res.get("file_url") or (res.get("data") or {}).get("url")
            if url:
                return url
        except (GenError, ValueError):
            continue
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def muapi_i2v(image, prompt, dest, endpoint=MUAPI_I2V, seconds=5, resolution="720p", budget=None, note=""):
    """Animate a still into a short clip (experimental: not run on this account yet). Returns the mp4 path."""
    fields = muapi_fields(endpoint)
    payload = {"prompt": prompt, "image_url": muapi_upload(image)}
    if "duration" in fields:
        payload["duration"] = int(seconds)
    if "resolution" in fields:
        payload["resolution"] = resolution
    if "camera_fixed" in fields:
        payload["camera_fixed"] = False
    est = estimate("muapi", endpoint)
    if budget:
        budget.check(est)
    outs, usd = muapi_run(endpoint, payload, timeout=1200, poll=6.0)
    download(outs[0], dest)
    if budget:
        budget.add("video", "muapi", endpoint, usd, note)
    return Path(dest)


# ---- Gemini (images and voices) ---------------------------------------------------------------------

def gemini_headers():
    key = key_for("gemini")
    if not key:
        raise GenError("no Gemini key (GEMINI_API_KEY, or the Setup tab)")
    return {"x-goog-api-key": key}


def gemini_generate(model, body, timeout=180):
    return post_json(f"{GEMINI_BASE}/models/{model}:generateContent", body, gemini_headers(), timeout=timeout, retries=2)


def _inline_part(reply, prefix):
    for cand in reply.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            data = part.get("inlineData")
            if data and str(data.get("mimeType", "")).startswith(prefix):
                return base64.b64decode(data["data"]), data["mimeType"]
    reason = (reply.get("candidates") or [{}])[0].get("finishReason") or reply.get("promptFeedback", {}).get("blockReason")
    raise GenError(f"Gemini returned no {prefix} ({reason or 'empty reply'})")


def gemini_image(prompt, dest, model=GEMINI_IMAGE, aspect="9:16", budget=None, note=""):
    est = estimate("gemini", model)
    if budget:
        budget.check(est)
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": aspect}}}
    data, _ = _inline_part(gemini_generate(model, body), "image/")
    Path(dest).write_bytes(data)
    if budget:
        budget.add("image", "gemini", model, est, note)
    else:
        record("image", "gemini", model, est, note=note)
    return Path(dest)


def wav_bytes(pcm, rate=24000, channels=1, width=2):
    """A WAV file around raw 16-bit PCM."""
    n = len(pcm)
    header = b"RIFF" + struct.pack("<I", 36 + n) + b"WAVE" + b"fmt " + struct.pack("<IHHIIHH", 16, 1, channels, rate,
                                                                                    rate * channels * width, channels * width, 8 * width)
    return header + b"data" + struct.pack("<I", n) + pcm


def gemini_tts(text, dest, voice="Charon", style="", model=GEMINI_TTS):
    """One passage in a Gemini voice -> a WAV file (24 kHz mono). `style` is a plain-language delivery note; the 2.5
    TTS models follow it, the 3.x TTS models would read it aloud, so it is only sent to models that take it."""
    takes_style = model.startswith("gemini-2.5")
    prompt = f"{style.strip()}\n\n{text}" if style and takes_style else text
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    data, mime = _inline_part(gemini_generate(model, body, timeout=120), "audio/")
    if data[:4] != b"RIFF":
        rate = int((re.search(r"rate=(\d+)", mime) or [None, 24000])[1])
        data = wav_bytes(data, rate)
    Path(dest).write_bytes(data)
    return Path(dest)


# ---- ElevenLabs and MiniMax voices -------------------------------------------------------------------

def elevenlabs_tts(text, dest, voice="George", model=ELEVEN_MODEL, rate=1.0, style=0.3, stability=0.5):
    """One passage -> mp3 plus [(word, start, end)] from the character alignment (None if the API gave none)."""
    key = key_for("elevenlabs")
    if not key:
        raise GenError("no ElevenLabs key (ELEVENLABS_API_KEY, or the Setup tab)")
    voice_id = ELEVEN_VOICES.get(voice, voice)
    body = {"text": text, "model_id": model,
            "voice_settings": {"stability": stability, "similarity_boost": 0.8, "style": style, "use_speaker_boost": True,
                               "speed": max(0.7, min(1.2, float(rate)))}}
    headers = {"xi-api-key": key}
    try:
        res = post_json(f"{ELEVEN_BASE}/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128", body, headers, 180, 2)
        audio, align = base64.b64decode(res["audio_base64"]), res.get("alignment") or {}
        words = _words_from_chars(align.get("characters") or [], align.get("character_start_times_seconds") or [],
                                  align.get("character_end_times_seconds") or [])
    except (GenError, KeyError):
        _, audio, _ = http("POST", f"{ELEVEN_BASE}/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                           {"Content-Type": "application/json", **headers}, json.dumps(body).encode(), 180, 2)
        words = None
    Path(dest).write_bytes(audio)
    return Path(dest), words


def _words_from_chars(chars, starts, ends):
    words, cur, s0, e0 = [], "", None, None
    for ch, a, b in zip(chars, starts, ends):
        if ch.isspace():
            if cur:
                words.append((cur, s0, e0))
            cur, s0 = "", None
            continue
        cur += ch
        s0 = a if s0 is None else s0
        e0 = b
    if cur:
        words.append((cur, s0, e0))
    return words or None


def minimax_tts(text, dest, voice="English_expressive_narrator", model=MINIMAX_MODEL, rate=1.0, emotion=""):
    """One passage -> mp3 from MiniMax's speech model (not run on this account yet)."""
    key = key_for("minimax")
    if not key:
        raise GenError("no MiniMax key (MINIMAX_API_KEY, or the Setup tab)")
    group = os.environ.get("MINIMAX_GROUP_ID") or str(mpt_app_config().get("minimax_group_id") or "")
    url = f"{MINIMAX_BASE}/t2a_v2" + (f"?GroupId={group}" if group else "")
    voice_setting = {"voice_id": voice, "speed": max(0.5, min(2.0, float(rate))), "vol": 1.0, "pitch": 0}
    if emotion:
        voice_setting["emotion"] = emotion
    body = {"model": model, "text": text, "stream": False, "voice_setting": voice_setting,
            "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1}}
    res = post_json(url, body, {"Authorization": f"Bearer {key}"}, 180, 2)
    status = (res.get("base_resp") or {}).get("status_code", 0)
    if status:
        raise GenError(f"MiniMax: {(res.get('base_resp') or {}).get('status_msg', status)}")
    hexed = (res.get("data") or {}).get("audio") or ""
    if not hexed:
        raise GenError("MiniMax returned no audio")
    Path(dest).write_bytes(bytes.fromhex(hexed))
    return Path(dest)


# ---- Pollinations (free, slow) ------------------------------------------------------------------------

_POLL_LOCK = threading.Lock()
_POLL_LAST = [0.0]
POLL_GAP = 46.0                      # seconds between free (keyless) requests: the service allows one per 45 s per address


def pollinations_image(prompt, dest, width=1080, height=2048, model="flux", seed=None, tries=4):
    """A free image. Without a key the service allows one image every 45 s per address and stamps a small logo in the
    bottom-right corner; the caller crops that off (hence the extra height). Keyless calls are serialised and spaced
    across threads, so parallel keyframe workers never trip the limit; a limit hit anyway is waited out."""
    if not key_for("pollinations"):
        with _POLL_LOCK:
            wait = POLL_GAP - (time.time() - _POLL_LAST[0])
            if wait > 0:
                time.sleep(wait)
            try:
                return _pollinations_once(prompt, dest, width, height, model, seed, tries)
            finally:
                _POLL_LAST[0] = time.time()
    return _pollinations_once(prompt, dest, width, height, model, seed, tries)


def _pollinations_once(prompt, dest, width, height, model, seed, tries):
    q = urllib.parse.quote(prompt[:1400])
    params = {"width": width, "height": height, "model": model, "nologo": "true", "private": "true", "enhance": "false",
              "seed": seed if seed is not None else int(hashlib.md5(prompt.encode()).hexdigest()[:6], 16)}
    key = key_for("pollinations")
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    url = POLLINATIONS + q + "?" + urllib.parse.urlencode(params)
    last = None
    for attempt in range(tries):
        try:
            _, data, _ = http("GET", url, headers, None, timeout=240, retries=1)
            if data[:4] in (b"\x89PNG", b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1") or data[:3] == b"\xff\xd8\xff":
                Path(dest).write_bytes(data)
                record("image", "pollinations", model, 0.0, note=prompt[:60])
                return Path(dest)
            last = GenError("pollinations returned something that isn't an image")
        except GenError as err:
            last = err
            wait = _retry_after(str(err), None)
            if err.code in (402, 429) and wait:
                time.sleep(min(wait, 75))
                continue
            if err.code and 400 <= err.code < 500 and err.code not in (402, 429):
                raise
        time.sleep(8 * (attempt + 1))
    raise last or GenError("pollinations failed")


# ---- One door for images -------------------------------------------------------------------------------

IMAGE_PROVIDERS = ("muapi", "gemini", "pollinations")


def image_providers(preferred="auto"):
    """The image providers to try, in order: the one chosen in Settings, else every one with a key, free last."""
    if preferred in IMAGE_PROVIDERS:
        return [preferred] + [p for p in IMAGE_PROVIDERS if p != preferred and has(p)]
    return [p for p in IMAGE_PROVIDERS if has(p)]


def image(prompt, dest, providers=None, model="", aspect="9:16", budget=None, note="", log=print, skip=None):
    """One image via the first provider that delivers. Returns (path, provider, model). `skip` is a set the caller
    keeps across calls: a provider that said no (no credits, no billing) is not asked again for the next frame."""
    skip = skip if skip is not None else set()
    errors = []
    for p in providers or image_providers():
        if p in skip:
            continue
        try:
            if p == "muapi":
                m = model or MUAPI_IMAGE
                muapi_image(prompt, dest, m, aspect, budget, note)
            elif p == "gemini":
                m = model if model.startswith("gemini") else GEMINI_IMAGE
                gemini_image(prompt, dest, m, aspect, budget, note)
            else:
                m = "flux"
                w, h = (1080, 2048) if aspect == "9:16" else (2048, 1152) if aspect == "16:9" else (1024, 1024)
                pollinations_image(prompt, dest, w, h, m)
            return Path(dest), p, m
        except BudgetExceeded:
            raise
        except GenError as err:
            errors.append(f"{p}: {err}")
            rate_limited = "FREE_LIMIT" in str(err) or "Retry after" in str(err)        # Pollinations' 402 is a speed limit
            if not rate_limited and (err.code in (401, 402, 403, 422) or err.code == 429 and ("limit: 0" in str(err) or "INSUFFICIENT" in str(err).upper())):
                skip.add(p)                      # a hard no: don't ask this provider for every frame
                log(f"Images: {p} is off for this video ({str(err)[:120]})")
        except Exception as err:                 # noqa: BLE001  (a provider's odd failure must not stop the chain)
            errors.append(f"{p}: {type(err).__name__}: {str(err)[:120]}")
    raise GenError("no image provider delivered: " + "; ".join(errors)[:400])


def status():
    """What is set up, for the Setup page and --doctor: {provider: 'ready' | 'no key' | 'free (slow)'}."""
    out = {}
    for p in ("muapi", "gemini", "elevenlabs", "minimax"):
        out[p] = "key set" if has(p) else "no key"
    out["pollinations"] = "key set" if key_for("pollinations") else "ready (free, one image every 45 s)"
    return out
