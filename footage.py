"""Footage: find candidate clips in several free sources, let Claude LOOK at them, and
place the best ones exactly under the sentence they illustrate.

Why it is more accurate than MoneyPrinterTurbo's own clip picking:
  * Clips are matched per sentence group ("beat"), using the real voiceover timing.
  * Landscape clips are accepted and center-cropped to vertical (4K sources stay sharp),
    so far more candidates exist than with a vertical-only search.
  * Claude sees each candidate as it will actually appear (cropped 9:16) and picks the
    best one for the words being spoken; no clip is used twice in a video.
  * Each cut is trimmed to the beat's exact length, taken from the calm middle of the clip.

Sources: Pixabay (API key), Coverr (official API, optional key) and your own clip
library in clips/ (hand-downloaded Mixkit, Vidsplay, ...). Mixkit forbids bots, so it
is never fetched automatically.
"""

import hashlib
import json
import math
import re
import shutil
import subprocess
import time
from pathlib import Path

W, H, FPS = 1080, 1920, 30
CUT_MAX = 4.2          # a beat longer than this is split into several quick cuts
BEAT_TARGET = 3.4      # aim for about this many seconds of voiceover per beat
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm"}
MAX_DOWNLOAD = 300e6   # never fetch a single clip bigger than this (bytes)
# Sources that require a visible credit in the description (Vidsplay's terms; Coverr asks API users)
CREDIT_RULES = {"vidsplay": "Footage: Vidsplay.com", "coverr": "Footage: Coverr (coverr.co)"}


# ---- Timing (pure) -----------------------------------------------------------------

def _secs(stamp):
    h, m, rest = stamp.strip().split(":")
    s, _, ms = rest.replace(".", ",").partition(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int((ms + "000")[:3]) / 1000


def parse_srt(text):
    """[(start, end, text)] from SRT text."""
    out = []
    for block in re.split(r"\n\s*\n", text.strip().replace("\r\n", "\n")):
        lines = [l for l in block.split("\n") if l.strip()]
        for i, line in enumerate(lines):
            if "-->" in line:
                a, _, b = line.partition("-->")
                out.append((_secs(a), _secs(b), " ".join(lines[i + 1:]).strip()))
                break
    return [s for s in out if s[2]]


def make_beats(segments, total, target=BEAT_TARGET, lo=1.8):
    """Group subtitle lines into beats of about `target` seconds that tile 0..total.
    A beat starts exactly when its first line is spoken, so the picture changes with the words.
    Returns [(start, end, text)]."""
    groups, cur = [], None
    for s, e, txt in segments:
        if cur is None:
            cur = [s, e, txt]
        else:
            cur[1], cur[2] = e, f"{cur[2]} {txt}"
        if cur[1] - cur[0] >= target:
            groups.append(cur)
            cur = None
    if cur:
        if groups and cur[1] - cur[0] < lo:
            groups[-1][1], groups[-1][2] = cur[1], f"{groups[-1][2]} {cur[2]}"
        else:
            groups.append(cur)
    if not groups:
        return [(0.0, total, "")]
    starts = [0.0] + [g[0] for g in groups[1:]]
    ends = starts[1:] + [total]
    return [(round(a, 3), round(b, 3), g[2]) for a, b, g in zip(starts, ends, groups)]


def cut_lengths(beat_len, cut_max=CUT_MAX):
    """Split a beat into equal cuts no longer than cut_max (quick cuts keep Shorts lively)."""
    n = max(1, math.ceil(beat_len / cut_max - 1e-9))
    return [beat_len / n] * n


def window(clip_len, need):
    """Where to cut inside a clip: returns (start, source_seconds_to_read, speed) or None.
    Skips the first/last frames (fades, camera shake) and takes the part just before the
    middle, where stock footage is usually at its best. If the clip is a bit short it is
    slowed down (min 0.7x); if shorter than that it can't be used."""
    margin = min(0.3, clip_len * 0.05)
    usable = clip_len - 2 * margin
    if usable >= need:
        return round(margin + (usable - need) * 0.35, 3), need, 1.0
    speed = clip_len / need
    if speed < 0.7:
        return None
    return 0.0, clip_len, round(speed, 3)


def credits_for(sources):
    """Credit lines to add to the video description for the sources actually used."""
    text = " ".join(str(s).lower() for s in sources)
    return sorted({line for key, line in CREDIT_RULES.items() if key in text})


# ---- ffmpeg helpers ------------------------------------------------------------------

def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg") or "ffmpeg"


def run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8",
                          errors="replace", stdin=subprocess.DEVNULL)


def probe(path):
    """(duration_s, width, height) of a video, read from ffmpeg's banner."""
    err = run([ffmpeg_exe(), "-hide_banner", "-i", str(path)], timeout=60).stderr
    d = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", err)
    v = re.search(r"Video:.*?(\d{3,5})x(\d{3,5})", err)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    return dur, int(v.group(1)) if v else 0, int(v.group(2)) if v else 0


def fit_audio(src, seconds, dest):
    """Trim (or loop, if too short) an audio file to exactly `seconds`. MoneyPrinterTurbo does not do
    this for a music file handed to it, so without this a long track would stretch the video."""
    r = run([ffmpeg_exe(), "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src), "-t", f"{seconds:.2f}",
             "-c:a", "libmp3lame", "-q:a", "3", str(dest)])
    if r.returncode or not Path(dest).exists():
        raise RuntimeError(f"couldn't fit the music: {r.stderr[-200:]}")
    return dest


def cut_filter(speed):
    f = f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},setsar=1,fps={FPS}"
    return f + (f",setpts=PTS/{speed}" if speed != 1.0 else "")


def render_cut(src, dest, start, read_len, speed):
    """One vertical, silent, exactly-timed piece of a clip."""
    out_len = read_len / speed
    r = run([ffmpeg_exe(), "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{read_len:.3f}", "-i", str(src),
             "-vf", cut_filter(speed), "-t", f"{out_len:.3f}", "-an", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "19", "-pix_fmt", "yuv420p", str(dest)])
    if r.returncode or not Path(dest).exists():
        raise RuntimeError(f"ffmpeg cut failed: {r.stderr[-300:]}")


def concat(pieces, out):
    listing = Path(out).with_suffix(".txt")
    listing.write_text("".join(f"file '{Path(p).as_posix()}'\n" for p in pieces), encoding="utf-8")
    r = run([ffmpeg_exe(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
             "-c", "copy", str(out)])
    if r.returncode or not Path(out).exists():
        raise RuntimeError(f"ffmpeg concat failed: {r.stderr[-300:]}")
    listing.unlink(missing_ok=True)


# ---- Candidate sources -----------------------------------------------------------------
# A candidate is a dict: id, source, url (download) or path (local), thumb (url or path),
# dur, w, h, tags, page.

def _get(url, headers=None, **kw):
    import requests
    return requests.get(url, timeout=(20, 60), headers={"User-Agent": "shorts-autopilot", **(headers or {})}, **kw)


def pick_rendition(renditions):
    """Best Pixabay file for a 1080x1920 center crop: the smallest one that is at least 1920 px
    tall (so the crop is never upscaled), else the tallest available. None if there is no file."""
    usable = [(name, r) for name, r in (renditions or {}).items()
              if isinstance(r, dict) and r.get("url") and int(r.get("height") or 0) > 0
              and 0 < float(r.get("size") or 1) < MAX_DOWNLOAD]
    big = sorted((x for x in usable if int(x[1]["height"]) >= H), key=lambda x: int(x[1]["height"]))
    if big:
        return big[0]
    return max(usable, key=lambda x: int(x[1]["height"]), default=None)


def search_pixabay(term, key, min_dur):
    r = _get("https://pixabay.com/api/videos/", params={"key": key, "q": term, "video_type": "film",
                                                         "per_page": 24, "safesearch": "true"})
    out = []
    for h in r.json().get("hits", []):
        dur = h.get("duration") or 0
        picked = pick_rendition(h.get("videos"))
        if not picked or dur < min_dur:
            continue
        name, f = picked
        out.append({"id": f"pixabay:{h['id']}", "source": "pixabay", "url": f["url"], "thumb": f.get("thumbnail"),
                    "dur": float(dur), "w": int(f["width"]), "h": int(f["height"]),
                    "tags": h.get("tags", ""), "page": h.get("pageURL", ""), "ext": ".mp4"})
    return out


def search_coverr(term, key, min_dur):
    r = _get("https://api.coverr.co/videos", params={"query": term, "page_size": 20, "urls": "true", "sort": "popular"},
             headers={"Authorization": f"Bearer {key}"})
    out = []
    for v in r.json().get("hits", []):
        urls = v.get("urls") or {}
        dl = urls.get("mp4_download") or urls.get("mp4")
        try:
            dur = float(v.get("duration") or 0)
        except (TypeError, ValueError):
            continue
        if not dl or dur < min_dur or int(v.get("max_height") or 0) < 1080:
            continue
        out.append({"id": f"coverr:{v['id']}", "source": "coverr", "url": dl,
                    "thumb": v.get("poster") or v.get("thumbnail"), "dur": dur,
                    "w": int(v.get("max_width") or 0), "h": int(v.get("max_height") or 0),
                    "tags": " ".join(v.get("tags") or []) if isinstance(v.get("tags"), list) else str(v.get("tags") or ""),
                    "page": v.get("canonical_url") or "", "ext": ".mp4"})
    return out


def load_library(folder):
    """Clips you downloaded by hand into clips/. Lines of clips/SOURCES.txt:
    filename | source (Mixkit, Vidsplay, Coverr, ...) | tags"""
    folder = Path(folder)
    sources = folder / "SOURCES.txt"
    if not sources.exists():
        return []
    lib = []
    for line in sources.read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split("|")]
        if line.strip().startswith("#") or len(parts) < 2 or not parts[1]:
            continue
        path = folder / parts[0]
        if path.suffix.lower() in VIDEO_EXT and path.is_file():
            lib.append({"id": f"library:{parts[0]}", "source": parts[1], "path": str(path),
                        "tags": parts[2] if len(parts) > 2 else "", "page": ""})
    return lib


def words(text):
    return {w for w in re.findall(r"[a-z]{3,}", text.lower())}


def search_library(lib, terms, probe_cache, thumbs_dir, min_dur, limit=3):
    """Library clips whose tags or file name share a word with a search term."""
    want = set().union(*(words(t) for t in terms)) if terms else set()
    hits = []
    for c in lib:
        have = words(c["tags"] + " " + Path(c["path"]).stem)
        overlap = len(want & have)
        if not overlap:
            continue
        if c["path"] not in probe_cache:
            probe_cache[c["path"]] = probe(c["path"])
        dur, w, h = probe_cache[c["path"]]
        if dur < min_dur:
            continue
        hits.append((overlap, {**c, "dur": dur, "w": w, "h": h, "thumb": make_thumb(c["path"], thumbs_dir, dur)}))
    hits.sort(key=lambda x: -x[0])
    return [c for _, c in hits[:limit]]


def make_thumb(video, thumbs_dir, dur):
    """A frame from the middle of a local video (cached)."""
    thumbs_dir = Path(thumbs_dir)
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    out = thumbs_dir / (hashlib.md5(str(video).encode()).hexdigest()[:12] + ".jpg")
    if not out.exists():
        run([ffmpeg_exe(), "-y", "-v", "error", "-ss", f"{max(dur, 1) / 2:.2f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=640:-2", str(out)], timeout=60)
    return str(out) if out.exists() else None


def interleave(*lists, limit=8):
    """Round-robin so every source gets a place among the candidates."""
    out, seen = [], set()
    for i in range(max((len(l) for l in lists), default=0)):
        for l in lists:
            if i < len(l) and l[i]["id"] not in seen:
                seen.add(l[i]["id"])
                out.append(l[i])
    return out[:limit]


FALLBACK_QUERIES = ["city lights", "abstract background"]


def gather(beats, queries, searchers, log=print, pause=0.25):
    """Candidate clips for every beat: [[cand, ...]], up to 8 each, sources interleaved.
    `searchers` is [(name, fn(term, min_dur) -> [cand])]; one source failing never stops the others.
    A beat with no results gets generic fallback footage so the video can always be finished."""
    cache, out = {}, []
    for i, ((start, end, _), qs) in enumerate(zip(beats, queries)):
        min_dur = max(cut_lengths(end - start)) * 0.75        # shorter clips would need slowing below 0.7x
        lists = []
        for q in list(qs or []) + (FALLBACK_QUERIES if not qs else []):
            for name, fn in searchers:
                key = (name, q, round(min_dur, 1))
                if key not in cache:
                    try:
                        cache[key] = fn(q, min_dur)
                    except Exception as e:
                        log(f"{name} search '{q}' failed: {type(e).__name__}: {str(e)[:80]}")
                        cache[key] = []
                    time.sleep(pause)                          # be gentle with the APIs
                lists.append(cache[key])
        found = interleave(*lists)
        if not found:
            for q in FALLBACK_QUERIES:
                for name, fn in searchers:
                    key = (name, q, round(min_dur, 1))
                    if key not in cache:
                        try:
                            cache[key] = fn(q, min_dur)
                        except Exception:
                            cache[key] = []
                    lists.append(cache[key])
            found = interleave(*lists)
        out.append(found)
        log(f"Beat {i + 1}: {len(found)} candidates for {list(qs or [])}")
    if not any(out):
        raise RuntimeError("no footage found for any beat")
    return out


def fetch(url, dest):
    """Download (once) to dest; returns dest."""
    dest = Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _get(url, stream=True) as r:
        r.raise_for_status()
        total = 0
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                total += len(chunk)
                if total > MAX_DOWNLOAD:
                    raise RuntimeError("clip too large")
                f.write(chunk)
    tmp.replace(dest)
    return dest


# ---- Looking at the candidates ---------------------------------------------------------

def parse_queries(text, n):
    """[[query, ...]] of length n from an LLM reply like [{"i":1,"queries":["a","b"]}, ...]."""
    match = re.search(r"\[.*\]", text, re.S)
    data = json.loads(match.group(0)) if match else []
    out = [[] for _ in range(n)]
    for k, item in enumerate(data):
        if isinstance(item, dict):
            idx = int(item.get("i", k + 1)) - 1
            qs = item.get("queries") or []
        else:
            idx, qs = k, item if isinstance(item, list) else [item]
        if 0 <= idx < n:
            out[idx] = [re.sub(r"\s+", " ", str(q)).strip().lower() for q in qs if str(q).strip()][:3]
    return out


def parse_picks(text, counts):
    """{beat_number: [candidate numbers, best first]} from a reply like {"3": [2, 5], "4": []}.
    `counts` maps beat number -> how many candidates that sheet had."""
    match = re.search(r"\{.*\}", text, re.S)
    data = json.loads(match.group(0)) if match else {}
    picks = {}
    for key, nums in data.items():
        try:
            beat = int(key)
        except ValueError:
            continue
        if beat in counts and isinstance(nums, list):
            good = []
            for x in nums:
                if isinstance(x, (int, float)) and 1 <= int(x) <= counts[beat] and int(x) not in good:
                    good.append(int(x))
            picks[beat] = good[:3]
    return picks


def crop_vertical(img):
    """Center 9:16 crop: what the viewer will actually see of a landscape clip."""
    w, h = img.size
    target = 9 / 16
    if w / h > target:
        nw = int(h * target)
        x = (w - nw) // 2
        return img.crop((x, 0, x + nw, h))
    nh = int(w / target)
    y = (h - nh) // 2
    return img.crop((0, y, w, y + nh))


def load_thumb(c, cache):
    t = c.get("thumb")
    if not t:
        return None
    if str(t).startswith("http"):
        dest = Path(cache) / (hashlib.md5(t.encode()).hexdigest()[:12] + ".jpg")
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            r = _get(t)
            r.raise_for_status()
            dest.write_bytes(r.content)
        return dest
    return Path(t)


def make_sheet(cands, dest, cache):
    """One image with numbered 9:16 tiles, one per candidate."""
    from PIL import Image, ImageDraw, ImageFont
    cw, ch, cols, pad = 200, 356, 4, 8
    rows = math.ceil(len(cands) / cols)
    sheet = Image.new("RGB", (cols * (cw + pad) + pad, rows * (ch + pad) + pad), (28, 28, 28))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=30)
    for i, c in enumerate(cands):
        x, y = pad + (i % cols) * (cw + pad), pad + (i // cols) * (ch + pad)
        try:
            tile = crop_vertical(Image.open(load_thumb(c, cache)).convert("RGB")).resize((cw, ch))
            sheet.paste(tile, (x, y))
        except Exception:
            draw.rectangle((x, y, x + cw, y + ch), fill=(70, 70, 70))
            draw.text((x + 40, y + ch // 2), "no preview", fill=(200, 200, 200))
        draw.rectangle((x, y, x + 40, y + 40), fill=(0, 0, 0))
        draw.text((x + 8, y + 2), str(i + 1), fill=(255, 255, 0), font=font)
    sheet.save(dest)
    return dest


def vision_prompt(topic, items, lessons_text):
    lines = "\n".join(f'- Beat {b} (file {Path(f).name}, {n} candidates): "{txt}"' for b, txt, f, n in items)
    return (
        f"You are choosing stock-video clips for a vertical YouTube Short, a fast, fun explainer about: {topic}.\n"
        "Each image file below is a contact sheet for ONE beat of the voiceover. It shows numbered candidate clips "
        "exactly as they would look on a phone (9:16 center crop).\n"
        "For each beat, rank up to 3 candidates that best illustrate the words being spoken. Judge: does the picture "
        "fit or clearly support the meaning of the words (literally or as a clear visual metaphor)? Is the main subject "
        "fully inside the frame? Is it sharp, bright and attractive? Reject visible text, logos or watermarks, unrelated "
        "subjects (animals, nature scenery, children) unless the words are about them, dull or dark footage, and anything "
        "unsuitable for a general audience.\n"
        f"{lessons_text}\n"
        "Open every image file with the Read tool. Then reply with ONLY a JSON object keyed by beat number, "
        'for example {"3": [2, 5], "4": []}. Use an empty list when no candidate fits.\n\nBeats:\n' + lines)


def choose_with_vision(topic, beats, cands_per_beat, ask_vision, work, lessons_text="", chunk=5, log=print):
    """{beat_index: ranked candidate list}. Falls back to search order when vision isn't available."""
    sheets = Path(work) / "sheets"
    sheets.mkdir(parents=True, exist_ok=True)
    cache = Path(work) / "thumbs"
    ranked = {i: list(c) for i, c in enumerate(cands_per_beat)}
    todo = [i for i, c in enumerate(cands_per_beat) if len(c) > 1]
    for start in range(0, len(todo), chunk):
        group = todo[start:start + chunk]
        items, counts = [], {}
        for i in group:
            f = make_sheet(cands_per_beat[i], sheets / f"beat_{i + 1:02d}.png", cache)
            items.append((i + 1, beats[i][2], f, len(cands_per_beat[i])))
            counts[i + 1] = len(cands_per_beat[i])
        try:
            picks = parse_picks(ask_vision(vision_prompt(topic, items, lessons_text), sheets), counts)
        except Exception as e:
            log(f"Vision pick failed ({type(e).__name__}: {str(e)[:120]}); using search order for beats {[g + 1 for g in group]}")
            continue
        for i in group:
            chosen = [cands_per_beat[i][n - 1] for n in picks.get(i + 1, [])]
            if not chosen:
                log(f"Beat {i + 1}: nothing fits well, using the top search result")
            rest = [c for c in cands_per_beat[i] if c not in chosen]
            ranked[i] = chosen + rest
    return ranked


# ---- Building the picture track ---------------------------------------------------------

def compose(beats, ranked, work, cache_dir, log=print):
    """Cut one clip piece per beat slot, exactly as long as the voiceover needs, and join them.
    Returns (combined_path, [candidates used])."""
    work, cache_dir = Path(work), Path(cache_dir)
    pieces_dir = work / "pieces"
    pieces_dir.mkdir(parents=True, exist_ok=True)
    pieces, used, used_ids, cursor = [], [], set(), {}
    for i, (start, end, _) in enumerate(beats):
        for k, need in enumerate(cut_lengths(end - start)):
            options = [c for c in ranked.get(i, []) if c["id"] not in used_ids] or ranked.get(i, [])
            if not options:
                raise RuntimeError(f"no clip found for beat {i + 1}")
            for c in options:
                try:
                    name = f"sa-{hashlib.md5(c['id'].encode()).hexdigest()[:10]}{c.get('ext', '.mp4')}"
                    path = c.get("path") or fetch(c["url"], cache_dir / name)
                    dur = probe(path)[0] if c.get("path") else c["dur"]
                    win = window(dur, need)
                    if win is None:
                        continue
                    s, read_len, speed = win
                    if c["id"] in cursor and cursor[c["id"]] + read_len <= dur - 0.1:
                        s = cursor[c["id"]]               # reused clip: carry on, never replay the same moment
                    cursor[c["id"]] = s + read_len
                    dest = pieces_dir / f"{i + 1:02d}-{k + 1}.mp4"
                    render_cut(path, dest, s, read_len, speed)
                    pieces.append(dest)
                    if c not in used:
                        used.append(c)
                    used_ids.add(c["id"])
                    log(f"Beat {i + 1}.{k + 1} {need:.1f}s <- {c['id']} @ {s:.1f}s")
                    break
                except Exception as e:
                    log(f"Skipping {c['id']}: {type(e).__name__}: {str(e)[:100]}")
            else:
                raise RuntimeError(f"no usable clip for beat {i + 1}")
    combined = work / "combined.mp4"
    concat(pieces, combined)
    return combined, used
