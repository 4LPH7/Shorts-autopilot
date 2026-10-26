"""Shorts Autopilot engine: render YouTube Shorts with MoneyPrinterTurbo for your
review, then upload the ones you approve, spread evenly over the monthly
Upload-Post quota.

Every scheduled run (default 09:00 and 19:00):
  1. Upload: if an upload slot is due this month, post the oldest video in approved/.
  2. Render: if fewer than `buffer` videos wait in review/ + approved/, render one into review/.
  3. Clean: delete MoneyPrinterTurbo cache files older than `clean_after_days`.

Run with MPT's own Python from inside the MPT folder (run_daily.bat does this):
    python daily_shorts.py             # normal scheduled run
    python daily_shorts.py --dry-run   # show what would happen, change nothing
    python daily_shorts.py --render    # render one video now (never uploads)
    python daily_shorts.py --doctor    # JSON health report (LLM, footage, Upload-Post, ...)
    python daily_shorts.py --self-test # check the pure logic, no MPT needed

The GUI (autopilot_gui.pyw) imports this module for everything except the MPT calls,
so all rules live here once.
"""

import json
import random
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import footage  # noqa: E402  (sits next to this file)

DEFAULTS = {
    "niche": "money psychology and surprising personal finance facts",
    "language": "en-US",
    "voice": "en-US-GuyNeural-Male",    # lively and expressive; any voice from the Settings list works
                                        # (the "Multilingual" voices stall on the free Edge TTS service)
    "voice_rate": 1.12,                 # 1.0 = normal; 1.12 is a bit fast and punchy
    "script_rules": (
        "Write 130-150 words (about 50 seconds when spoken fast). "
        "Fun, energetic and conversational, like an excited friend sharing a surprising fact. "
        "First sentence is a hook that creates a curiosity gap, no greetings. "
        "Very short punchy sentences, contractions, a little humor. End with a question that invites comments."
    ),
    "monthly_uploads": 10,              # Upload-Post free plan; raise if you upgrade
    "run_times": ["09:00", "19:00"],    # Task Scheduler times; upload spacing uses them
    "buffer": 3,                        # videos to keep waiting for review/upload
    "music_mode": "auto",               # auto = AI picks the best-fitting approved track; fixed; none
    "music_track": "",                  # the track used when music_mode is "fixed"
    "music_volume": 0.2,                # a clearly audible bed, about 5 dB under the voice
    "clean_after_days": 14,             # delete MPT render caches older than this (0 = never)
}
MUSIC_MODES = ("auto", "fixed", "none")

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
HERE = Path(__file__).resolve().parent


def set_base(base):
    """Point every data path at `base` (the project folder; tests use a temp dir)."""
    global BASE, SETTINGS, HISTORY, LOG_DIR, RUNS, LOCK, LEDGER, SAFE_MUSIC, MUSIC_SOURCES
    global REVIEW, APPROVED, POSTED, CHECK, THUMBS, FEEDBACK, LESSONS, WORK, CLIPS, CLIPS_SOURCES
    BASE = Path(base)
    WORK = BASE / "work"                      # per-video leftovers that allow swapping the music later
    CLIPS = BASE / "clips"                    # your hand-downloaded clips (Mixkit, Vidsplay, ...)
    CLIPS_SOURCES = CLIPS / "SOURCES.txt"
    FEEDBACK = BASE / "feedback.jsonl"        # one line per rejected video: why you rejected it
    LESSONS = BASE / "lessons.json"           # rules distilled from the feedback (fed to the prompts)
    SETTINGS = BASE / "settings.json"
    HISTORY = BASE / "topics_used.txt"
    LOG_DIR = BASE / "logs"
    RUNS = LOG_DIR / "runs.jsonl"
    LOCK = LOG_DIR / "run.lock"
    LEDGER = BASE / "uploads.json"            # every upload that counts against the quota
    SAFE_MUSIC = BASE / "safe_music"          # only cleared tracks go here (see SAFETY.md)
    MUSIC_SOURCES = SAFE_MUSIC / "SOURCES.txt"
    REVIEW, APPROVED, POSTED, CHECK = (BASE / d for d in ("review", "approved", "posted", "check"))
    THUMBS = BASE / ".thumbs"


set_base(HERE)


# ---- Settings ----------------------------------------------------------------

def parse_times(values):
    """["09:00", "19:00"] -> [(9, 0), (19, 0)]; raises ValueError on bad input."""
    out = set()
    for v in values:
        h, _, m = str(v).strip().partition(":")
        h, m = int(h), int(m or 0)
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"bad time: {v}")
        out.add((h, m))
    if not out:
        raise ValueError("at least one run time is needed")
    return sorted(out)


def load_settings():
    s = dict(DEFAULTS)
    if SETTINGS.exists():
        saved = json.loads(SETTINGS.read_text(encoding="utf-8"))
        s.update({k: v for k, v in saved.items() if k in DEFAULTS})
    return s


def save_settings(s):
    clean = {k: s.get(k, DEFAULTS[k]) for k in DEFAULTS}
    parse_times(clean["run_times"])  # validate before writing
    for k in ("monthly_uploads", "buffer", "clean_after_days"):
        clean[k] = int(clean[k])
        if clean[k] < 0:
            raise ValueError(f"{k} can't be negative")
    clean["music_volume"] = float(clean["music_volume"])
    clean["voice_rate"] = float(clean["voice_rate"])
    if not 0.7 <= clean["voice_rate"] <= 1.5:
        raise ValueError("voice speed must be between 0.7 and 1.5")
    if not 0 <= clean["music_volume"] <= 1:
        raise ValueError("music volume must be between 0 and 1")
    if clean["music_mode"] not in MUSIC_MODES:
        raise ValueError(f"music mode must be one of {MUSIC_MODES}")
    SETTINGS.write_text(json.dumps(clean, indent=2, ensure_ascii=False), encoding="utf-8")
    return clean


# ---- Upload schedule -----------------------------------------------------------

def slots(after, until, times):
    """Scheduled run times t with after < t <= until."""
    out, day = [], after.date()
    while day <= until.date():
        for h, m in times:
            t = datetime(day.year, day.month, day.day, h, m)
            if after < t <= until:
                out.append(t)
        day += timedelta(days=1)
    return out


def month_bounds(now):
    start = datetime(now.year, now.month, 1)
    end = (start + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)
    return start, end


def used_this_month(ledger, now):
    start, _ = month_bounds(now)
    return sum(datetime.fromisoformat(e["time"]) >= start for e in ledger)


def upload_due(now, ledger, limit, times):
    """Spread the remaining monthly uploads evenly over the remaining run slots.
    Returns (due, reason)."""
    _, month_end = month_bounds(now)
    used = used_this_month(ledger, now)
    remaining = limit - used
    if remaining <= 0:
        return False, f"monthly quota used ({used}/{limit})"
    # The run happening now counts as the latest slot at or before now (+15 min slack).
    current = max(slots(now - timedelta(days=1), now + timedelta(minutes=15), times))
    left = len(slots(current - timedelta(seconds=1), month_end, times))
    stamps = sorted(datetime.fromisoformat(e["time"]) for e in ledger)
    if not stamps:
        return True, f"first upload ({remaining} left, {left} slots)"
    since = len(slots(stamps[-1], current, times))
    gap = left / remaining
    due = remaining >= left or since >= gap
    return due, f"{used}/{limit} used, {left} slots left, {since} since last, gap {gap:.2f}"


def plan_uploads(now, ledger, limit, times, until):
    """Future slots (after `now`, up to `until`) that will post, assuming videos are approved."""
    led, out = list(ledger), []
    for t in slots(now, until, times):
        if upload_due(t, led, limit, times)[0]:
            led.append({"time": t.isoformat()})
            out.append(t)
    return out


# ---- Review queue (the GUI calls these) ----------------------------------------

def stems(folder):
    """Video names (without extension) in a queue folder, oldest first."""
    return [p.stem for p in sorted(Path(folder).glob("*.mp4"))]


def pair(folder, stem):
    return Path(folder) / f"{stem}.mp4", Path(folder) / f"{stem}.json"


def load_meta(folder, stem):
    meta_file = pair(folder, stem)[1]
    return json.loads(meta_file.read_text(encoding="utf-8")) if meta_file.exists() else {}


def save_meta(folder, stem, title, description, tags):
    meta = load_meta(folder, stem)
    meta.update(title=title.strip(), description=description.strip(),
                tags=[t.strip() for t in tags if t.strip()])
    pair(folder, stem)[1].write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def move_pair(stem, src, dst):
    Path(dst).mkdir(exist_ok=True)
    for f in pair(src, stem):
        if f.exists():
            shutil.move(str(f), str(Path(dst) / f.name))


def approve(stem):
    move_pair(stem, REVIEW, APPROVED)


def unapprove(stem):
    move_pair(stem, APPROVED, REVIEW)


REJECT_REASONS = {
    "footage": "Footage doesn't match what's being said",
    "hook": "Weak or boring opening / script",
    "topic": "Topic is dull, repetitive or off-niche",
    "facts": "Wrong, misleading or risky claim",
    "length": "Too long or too short",
    "audio": "Voice, captions or music problem",
    "other": "Something else (explain)",
}
# Which prompt a reason teaches. "audio" can't be learned from prompts: change Settings instead.
CATEGORY_AREA = {"footage": "footage", "hook": "script", "topic": "topic", "facts": "script",
                 "length": "script", "other": "script"}
LESSON_AREAS = ("topic", "script", "footage")


def reject(stem, category, note=""):
    """Record why a video was rejected (it teaches future videos), then delete it."""
    if category not in REJECT_REASONS:
        raise ValueError("pick a reason")
    note = note.strip()
    if category == "other" and not note:
        raise ValueError("please describe what was wrong")
    meta = load_meta(REVIEW, stem)
    record = {"time": datetime.now().isoformat(timespec="seconds"), "category": category, "note": note,
              "topic": meta.get("topic", ""), "title": meta.get("title", ""),
              "script": meta.get("script", "")[:700], "music": meta.get("music", "")}
    with FEEDBACK.open("a", encoding="utf-8") as fh:   # log first: never delete without recording why
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    for path in (*pair(REVIEW, stem), THUMBS / f"{stem}.png"):
        path.unlink(missing_ok=True)
    drop_work(stem)


def load_feedback():
    if not FEEDBACK.exists():
        return []
    rows = []
    for line in FEEDBACK.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def parse_lessons(text):
    """{area: [short rules]} from an LLM reply; unknown areas dropped, rules capped."""
    match = re.search(r"\{.*\}", text, re.S)
    data = json.loads(match.group(0)) if match else {}
    out = {}
    for area in LESSON_AREAS:
        rules = data.get(area, []) if isinstance(data, dict) else []
        rules = rules if isinstance(rules, list) else []
        out[area] = [str(r).strip()[:200] for r in rules if str(r).strip()][:8]
    return out


def fallback_lessons(feedback, per_area=5):
    """Rules straight from the newest rejection notes (used when the LLM can't distill)."""
    out = {a: [] for a in LESSON_AREAS}
    for row in reversed(feedback):
        area = CATEGORY_AREA.get(row.get("category"))
        text = (row.get("note") or REJECT_REASONS.get(row.get("category"), "")).strip()
        if area == "topic" and row.get("topic"):
            text += f' (rejected topic: "{row["topic"]}")'
        if area and text and text not in out[area] and len(out[area]) < per_area:
            out[area].append(text[:200])
    return out


def lessons_block(lessons, area):
    """Prompt text for one area, or "" when there's nothing to apply."""
    rules = (lessons or {}).get(area) or []
    if not rules:
        return ""
    return ("Lessons from videos the channel owner rejected. Follow them strictly:\n"
            + "\n".join(f"- {r}" for r in rules))


def load_lessons():
    if LESSONS.exists():
        try:
            return json.loads(LESSONS.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {}


def build_lessons(ask_llm):
    """Distill all rejection feedback into short rules and save them (cached until new
    feedback arrives). ask_llm(prompt) -> reply text. Falls back to the raw notes."""
    feedback = load_feedback()
    empty = {a: [] for a in LESSON_AREAS}
    if not feedback:
        return empty
    current = load_lessons()
    if current.get("based_on") == len(feedback):
        return {a: current.get(a, []) for a in LESSON_AREAS}
    entries = "\n".join(
        f'- [{REJECT_REASONS.get(r.get("category"), r.get("category"))}] {r.get("note") or "(no note)"} '
        f'| topic: {r.get("topic")} | title: {r.get("title")} | script start: {(r.get("script") or "")[:160]}'
        for r in feedback[-40:])
    prompt = (
        "The owner of a faceless YouTube Shorts channel rejected these generated videos and said why:\n"
        f"{entries}\n\n"
        "Turn this into rules that will make FUTURE videos better. Reply with only a JSON object with "
        'keys "topic" (choosing topics), "script" (writing the voiceover) and "footage" (picking stock '
        "video clips). Each key holds at most 8 short, specific, imperative rules (under 25 words each). "
        "Merge duplicates; when notes conflict, prefer the newest (listed last). Omit anything that "
        "isn't actionable for that key.")
    try:
        rules = parse_lessons(ask_llm(prompt))
    except Exception as e:   # includes bad JSON and LLM errors
        print(f"Lessons: couldn't distill ({type(e).__name__}); using raw notes")
        rules = empty
    if not any(rules.values()):
        rules = fallback_lessons(feedback)
    LESSONS.write_text(json.dumps({"based_on": len(feedback), "updated": datetime.now().isoformat(
        timespec="seconds"), **rules}, indent=2, ensure_ascii=False), encoding="utf-8")
    return rules


def lessons_summary():
    """Plain text for the GUI: what future videos are being taught."""
    feedback = load_feedback()
    if not feedback:
        return "No rejections yet. When you reject a video and say why, the reasons become rules here."
    lessons = load_lessons()
    pending = lessons.get("based_on") != len(feedback)
    rules = fallback_lessons(feedback) if not lessons else {a: lessons.get(a, []) for a in LESSON_AREAS}
    lines = [f"Based on {len(feedback)} rejection(s)."]
    if pending:
        lines.append("New feedback is waiting: the rules below are refreshed at the next render.")
    for area in LESSON_AREAS:
        lines.append(f"\n{area.upper()}")
        lines += [f"  - {r}" for r in rules[area]] or ["  (nothing learned yet)"]
    audio = sum(1 for r in feedback if r.get("category") == "audio")
    if audio:
        lines.append(f"\n{audio} voice/caption/music complaint(s) can't be learned automatically: "
                     "change the voice, music volume or tracks in Settings and Music.")
    return "\n".join(lines)


def load_ledger():
    return json.loads(LEDGER.read_text(encoding="utf-8")) if LEDGER.exists() else []


def save_ledger(ledger):
    LEDGER.write_text(json.dumps(ledger, indent=2, ensure_ascii=False), encoding="utf-8")


def resolve_check(stem, uploaded):
    """An 'unconfirmed' upload: you checked YouTube Studio.
    uploaded=True  -> it's live: move to posted/, mark it posted.
    uploaded=False -> it never arrived: back to approved/, and it stops counting."""
    ledger = load_ledger()
    file = f"{stem}.mp4"
    if uploaded:
        move_pair(stem, CHECK, POSTED)
        drop_work(stem)
        for e in ledger:
            if e.get("file") == file:
                e["status"] = "posted"
    else:
        move_pair(stem, CHECK, APPROVED)
        ledger = [e for e in ledger if e.get("file") != file]
    save_ledger(ledger)


# ---- Music -----------------------------------------------------------------------

def parse_music_sources(text):
    """[(filename, source, tags)] from SOURCES.txt lines `filename | source | tags` (tags optional)."""
    out = []
    for line in text.splitlines():
        if line.strip().startswith("#"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 2 and parts[0] and parts[1]:
            out.append((parts[0], parts[1], parts[2] if len(parts) > 2 else ""))
    return out


def approved_tracks(sources_text, files_present):
    """Tracks that are both in the folder AND listed with a source. Unlisted = never used."""
    present = {f.lower(): f for f in files_present}
    return [present[n.lower()] for n, _, _ in parse_music_sources(sources_text)
            if Path(n).suffix.lower() in AUDIO_EXT and n.lower() in present]


def music_entries():
    """[(filename, source, tags, file_present)] for every track listed in SOURCES.txt."""
    text = MUSIC_SOURCES.read_text(encoding="utf-8") if MUSIC_SOURCES.exists() else ""
    return [(n, src, tags, (SAFE_MUSIC / n).is_file()) for n, src, tags in parse_music_sources(text)]


def usable_tracks():
    """[(filename, source, tags)] approved AND present: the only tracks that may be used."""
    names = set(approved_tracks(MUSIC_SOURCES.read_text(encoding="utf-8") if MUSIC_SOURCES.exists() else "",
                                [p.name for p in SAFE_MUSIC.glob("*") if p.is_file()]))
    return [(n, s, t) for n, s, t, ok in music_entries() if ok and n in names]


def recent_tracks(n=2):
    """Tracks used by the latest videos, newest first (to avoid repeating one)."""
    rows = []
    for folder in (REVIEW, APPROVED, POSTED, CHECK):
        for stem in stems(folder):
            meta = load_meta(folder, stem)
            rows.append((meta.get("rendered", ""), meta.get("music", "")))
    return [m for _, m in sorted(rows, reverse=True)[:n] if m and m != "none"]


def choose_track(settings, entries, ask_llm=None, topic="", script="", recent=()):
    """The track to use, as a filename, or None for voice only.
    mode "none" -> None. "fixed" -> the chosen track. "auto" -> Claude picks the best fit for
    the script from the mood tags (never one of the `recent` tracks if there are enough others);
    if that fails, a random track."""
    names = [n for n, _, _ in entries]
    mode = settings.get("music_mode", "auto")
    if mode == "none" or not names:
        return None
    if mode == "fixed" and settings.get("music_track") in names:
        return settings["music_track"]
    pool = [e for e in entries if e[0] not in recent] if len(names) > len(set(recent)) + 1 else list(entries)
    if len(pool) == 1 or ask_llm is None:
        return random.choice(pool)[0]
    listing = "\n".join(f"- {n}: {tags or 'no tags'}" for n, _, tags in pool)
    try:
        reply = ask_llm(
            f"Pick the background music for a fun, energetic, fast-paced YouTube Short about: {topic}.\n"
            f"Voiceover (start): {script[:500]}\n\nTracks (file: mood tags):\n{listing}\n\n"
            "Choose the single track whose mood and energy best fit this video. "
            'Reply with only JSON like {"track": "<exact file name>"}.')
        pick = json.loads(re.search(r"\{.*\}", reply, re.S).group(0)).get("track")
    except Exception:
        pick = None
    return pick if pick in [n for n, _, _ in pool] else random.choice(pool)[0]


def add_track(src_file, source, tags=""):
    if not source.strip():
        raise ValueError("a source/license note is required")
    src = Path(src_file)
    if src.suffix.lower() not in AUDIO_EXT:
        raise ValueError(f"not an audio file: {src.name}")
    if "|" in src.name or "|" in source or "|" in tags:
        raise ValueError("the '|' character can't be used in names, sources or tags")
    SAFE_MUSIC.mkdir(exist_ok=True)
    if src.resolve() != (SAFE_MUSIC / src.name).resolve():
        shutil.copyfile(src, SAFE_MUSIC / src.name)
    with MUSIC_SOURCES.open("a", encoding="utf-8") as f:
        f.write(f"\n{src.name} | {source.strip()}" + (f" | {tags.strip()}" if tags.strip() else ""))


def remove_track(name):
    lines = MUSIC_SOURCES.read_text(encoding="utf-8").splitlines() if MUSIC_SOURCES.exists() else []
    keep = [l for l in lines if l.partition("|")[0].strip().lower() != name.lower() or l.strip().startswith("#")]
    MUSIC_SOURCES.write_text("\n".join(keep) + "\n", encoding="utf-8")
    (SAFE_MUSIC / name).unlink(missing_ok=True)


# ---- Your clip library (clips/) ------------------------------------------------------

def clip_entries():
    """[(filename, source, tags, file_present)] for every clip listed in clips/SOURCES.txt."""
    text = CLIPS_SOURCES.read_text(encoding="utf-8") if CLIPS_SOURCES.exists() else ""
    return [(n, s, t, (CLIPS / n).is_file()) for n, s, t in parse_music_sources(text)]


def add_clip(src_file, source, tags):
    """Copy a hand-downloaded clip into clips/ and list it. Tags are how the picker finds it."""
    src = Path(src_file)
    if src.suffix.lower() not in footage.VIDEO_EXT:
        raise ValueError(f"not a video file: {src.name}")
    if not source.strip() or not tags.strip():
        raise ValueError("a source (e.g. Mixkit, Vidsplay) and a few tags are required")
    if "|" in src.name or "|" in source or "|" in tags:
        raise ValueError("the '|' character can't be used in names, sources or tags")
    CLIPS.mkdir(exist_ok=True)
    if src.resolve() != (CLIPS / src.name).resolve():
        shutil.copyfile(src, CLIPS / src.name)
    with CLIPS_SOURCES.open("a", encoding="utf-8") as f:
        f.write(f"\n{src.name} | {source.strip()} | {tags.strip()}")


def remove_clip(name):
    lines = CLIPS_SOURCES.read_text(encoding="utf-8").splitlines() if CLIPS_SOURCES.exists() else []
    keep = [l for l in lines if l.partition("|")[0].strip().lower() != name.lower() or l.strip().startswith("#")]
    CLIPS_SOURCES.write_text("\n".join(keep) + "\n", encoding="utf-8")
    (CLIPS / name).unlink(missing_ok=True)


def drop_work(stem):
    """Delete the leftovers that allow swapping a video's music (once it's gone or posted)."""
    shutil.rmtree(WORK / stem, ignore_errors=True)


# ---- Run lock, history, cleanup -----------------------------------------------------

class AlreadyRunning(Exception):
    pass


class RunLock:
    """Exclusive OS file lock held for a whole run; released automatically if the
    process dies. Stops a manual run and a scheduled run from both uploading."""

    def __enter__(self):
        import msvcrt
        import os
        LOG_DIR.mkdir(exist_ok=True)
        self.fd = os.open(LOCK, os.O_RDWR | os.O_CREAT)
        try:
            msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(self.fd)
            raise AlreadyRunning("another run is in progress")
        return self

    def __exit__(self, *exc):
        import msvcrt
        import os
        os.lseek(self.fd, 0, 0)
        msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        os.close(self.fd)


def is_running():
    try:
        with RunLock():
            return False
    except AlreadyRunning:
        return True


def log_run(record):
    LOG_DIR.mkdir(exist_ok=True)
    with RUNS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def recent_runs(n=30):
    if not RUNS.exists():
        return []
    rows = []
    for line in RUNS.read_text(encoding="utf-8").splitlines()[-n:]:
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def folder_size(path):
    p = Path(path)
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def old_entries(folder, days, now):
    """Direct children of `folder` last modified more than `days` days before `now`."""
    folder = Path(folder)
    if days <= 0 or not folder.is_dir():
        return []
    cutoff = (now - timedelta(days=days)).timestamp()
    return [p for p in folder.iterdir() if p.stat().st_mtime < cutoff]


def clean_mpt_cache(mpt_dir, days, now=None):
    """Delete MPT render leftovers (task folders, downloaded clips) older than `days`.
    Returns bytes freed. Our own review/approved/posted videos are never touched."""
    now = now or datetime.now()
    freed = 0
    for sub in ("storage/tasks", "storage/cache_videos"):
        for p in old_entries(Path(mpt_dir) / sub, days, now):
            size = folder_size(p) if p.is_dir() else p.stat().st_size
            try:
                shutil.rmtree(p) if p.is_dir() else p.unlink()
                freed += size
            except OSError as e:
                print(f"Clean: skipped {p.name}: {e}")
    return freed


# ---- Pure helpers ------------------------------------------------------------------

def parse_topics(text, used, n):
    """Pull a JSON list of strings out of an LLM reply, drop repeats, return n."""
    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        raise ValueError(f"LLM reply has no JSON list: {text[:200]}")
    seen = {u.strip().lower() for u in used}
    picked = []
    for t in json.loads(match.group(0)):
        t = str(t).strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            picked.append(t)
    return picked[:n]


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50]


# ---- Rendering (needs MoneyPrinterTurbo) ---------------------------------------------

def ask(llm, prompt):
    reply = llm._generate_response(prompt)  # MPT returns "Error: ..." instead of raising
    if reply.startswith("Error:"):
        raise RuntimeError(reply)
    return reply


def pick_topic(llm, s, lessons=None):
    used = HISTORY.read_text(encoding="utf-8").splitlines() if HISTORY.exists() else []
    reply = ask(llm, (
        f"Give 6 YouTube Shorts video topics for the niche: {s['niche']}. "
        "Each topic is one specific, curiosity-driven idea in under 12 words. "
        f"Do not repeat or closely resemble these past topics: {used[-100:]}. "
        f"{lessons_block(lessons, 'topic')}\n"
        "Reply with only a JSON array of strings."))
    topics = parse_topics(reply, used, 1)
    if not topics:
        raise RuntimeError("LLM returned no new topic")
    return topics[0]


def ask_vision_factory(M):
    """A function that shows images to Claude (through the logged-in Claude CLI) and returns its reply.
    Only reads files in the folder it is given. Raises when the CLI isn't available."""
    import json as _json
    import subprocess
    cli = (M.config.app.get("claude_code_cli_path") or "").strip() or shutil.which("claude")

    def ask_vision(prompt, folder):
        if not cli:
            raise RuntimeError("the claude CLI isn't installed, so clips can't be checked visually")
        env, _ = M.llm.build_claude_code_env()
        r = subprocess.run([cli, "-p", "--output-format", "json", "--tools", "Read", "--safe-mode"],
                           input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           cwd=str(folder), env=env, timeout=300)
        payload = _json.loads((r.stdout or "").strip() or "{}")
        if payload.get("is_error") or not payload.get("result"):
            raise RuntimeError(str(payload.get("result") or r.stderr)[:200])
        return payload["result"]
    return ask_vision


def plan_queries(ask_llm, topic, beats, lessons_text=""):
    """Search words for every beat: a specific one and a broader fallback."""
    lines = "\n".join(f'{i + 1}. ({e - s:.1f}s) "{txt}"' for i, (s, e, txt) in enumerate(beats))
    reply = ask_llm(
        f"Plan the stock footage for a fast, fun vertical YouTube Short about: {topic}.\n"
        "Below are the voiceover beats in order. For EACH beat give two stock-video search queries: "
        "a specific one and a broader fallback. Queries are 1-3 concrete, filmable English words that show "
        "what the beat is about (e.g. 'cash counting', 'worried woman', 'shopping cart', 'stock chart'); no abstract "
        "ideas, no brand names. Vary the shots so consecutive beats don't look alike.\n"
        f"{lessons_text}\n\nBeats:\n{lines}\n\n"
        'Reply with only a JSON array like [{"i": 1, "queries": ["cash counting", "money"]}, ...].')
    qs = footage.parse_queries(reply, len(beats))
    for i, (s, e, txt) in enumerate(beats):          # never leave a beat without something to search
        if not qs[i]:
            top = sorted(footage.words(txt), key=len, reverse=True)[:2]
            qs[i] = [" ".join(top)] if top else ["city lights"]
    return qs


def build_searchers(M):
    """The footage sources that are set up: Pixabay, Coverr (if you have a key) and your clip library."""
    searchers = []
    pix = M.config.app.get("pixabay_api_keys") or []
    pix = pix if isinstance(pix, list) else [pix]
    if pix:
        searchers.append(("pixabay", lambda q, d: footage.search_pixabay(q, pix[0], d)))
    cov = M.config.app.get("coverr_api_keys") or []
    cov = cov if isinstance(cov, list) else [cov]
    if cov:
        searchers.append(("coverr", lambda q, d: footage.search_coverr(q, cov[0], d)))
    lib, probes = footage.load_library(CLIPS), {}
    if lib:
        searchers.append(("library", lambda q, d: footage.search_library(lib, [q], probes, BASE / ".thumbs" / "clips", d)))
    return searchers


def make_params(M, s, topic, script, with_music):
    return M.VideoParams(
        video_subject=topic, video_script=script, video_language=s["language"], voice_name=s["voice"],
        voice_rate=float(s["voice_rate"]), video_aspect="9:16",
        subtitle_position="center",          # bottom gets covered by the Shorts UI
        font_name="BeVietnamPro-Bold.ttf", font_size=90, stroke_width=5,
        bgm_type="custom" if with_music else "none", bgm_file="", bgm_volume=float(s["music_volume"]))


def mix_final(M, s, topic, script, combined, audio, srt, out, track):
    """Voiceover + captions + (optional approved) music on top of the picture track."""
    path = SAFE_MUSIC / track if track else None
    if path:   # the mixer keeps a music file's full length, so cut it to the video first
        path = footage.fit_audio(path, footage.probe(combined)[0] + 0.1, Path(out).with_name("music_fit.mp3"))
    ok = M.video.generate_video(
        video_path=str(combined), audio_path=str(audio), subtitle_path=str(srt), output_file=str(out),
        params=make_params(M, s, topic, script, bool(path)), bgm_file_override=str(path) if path else None)
    if not Path(out).exists():
        raise RuntimeError("final video was not created")
    if path and not ok:
        print("WARNING: the music could not be mixed in; the video is voice only")
    return bool(path) and ok


def render_one(M, s):
    ask_llm = lambda prompt: ask(M.llm, prompt)           # noqa: E731
    lessons = build_lessons(ask_llm)
    applied = sum(len(v) for v in lessons.values())
    if applied:
        print(f"Lessons applied from your rejections: {applied} rule(s)")
    topic = pick_topic(M.llm, s, lessons)
    # MPT caps the script prompt at 2000 characters
    script_prompt = f"{s['script_rules']}\n{lessons_block(lessons, 'script')}".strip()[:1900]
    script = M.llm.generate_script(video_subject=topic, language=s["language"], video_script_prompt=script_prompt)
    if not script or script.startswith("Error"):
        raise RuntimeError(f"script failed: {script}")
    print("Topic:", topic)

    stem = f"{datetime.now():%Y%m%d-%H%M}-{slugify(topic)}"
    work = WORK / stem
    work.mkdir(parents=True, exist_ok=True)
    try:
        # 1. Voiceover and its exact timing
        tid = str(uuid4())
        result = M.tm.start(tid, make_params(M, s, topic, script, False), stop_at="subtitle")
        srt = result.get("subtitle_path")
        audio = Path(M.utils.task_dir(tid)) / "audio.mp3"
        if not srt or not audio.exists():
            raise RuntimeError(f"voiceover failed: {result.get('error')}")
        total = footage.probe(audio)[0]
        beats = footage.make_beats(footage.parse_srt(Path(srt).read_text(encoding="utf-8")), total)
        print(f"Voiceover {total:.1f}s -> {len(beats)} beats")

        # 2. Find, look at and place the footage
        flessons = lessons_block(lessons, "footage")
        queries = plan_queries(ask_llm, topic, beats, flessons)
        searchers = build_searchers(M)
        if not searchers:
            raise RuntimeError("no footage source is set up (add a Pixabay key in Setup)")
        cands = footage.gather(beats, queries, searchers)
        ranked = footage.choose_with_vision(topic, beats, cands, ask_vision_factory(M), work, flessons)
        cache = Path(M.config.root_dir) / "storage" / "cache_videos"
        combined, used = footage.compose(beats, ranked, work, cache)

        # 3. Music: the best-fitting approved track (or the one you fixed, or none)
        track = choose_track(s, usable_tracks(), ask_llm, topic, script, recent_tracks())
        print("Music:", track or "none (voice only)")

        # 4. Final mix
        shutil.copyfile(audio, work / "audio.mp3")
        shutil.copyfile(srt, work / "subtitle.srt")
        final = work / "final.mp4"
        mix_final(M, s, topic, script, combined, work / "audio.mp3", work / "subtitle.srt", final, track)
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise

    social = M.llm.generate_social_metadata(video_subject=topic, video_script=script,
                                            language=s["language"], platform="youtube_shorts")
    REVIEW.mkdir(exist_ok=True)
    shutil.copyfile(final, REVIEW / f"{stem}.mp4")
    final.unlink(missing_ok=True)
    (REVIEW / f"{stem}.json").write_text(json.dumps({
        "topic": topic,
        "title": social.get("title") or topic,           # editable in the app before approving
        "description": social.get("caption", ""),
        "tags": social.get("hashtags", []),
        "music": track or "none",
        "credits": footage.credits_for([c["source"] for c in used]),
        "clips": [c["id"] for c in used],
        "lessons_applied": applied,
        "script": script,
        "rendered": datetime.now().isoformat(timespec="seconds"),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(topic + "\n")
    print(f"READY FOR REVIEW: {REVIEW / (stem + '.mp4')}")
    return REVIEW / f"{stem}.mp4"


def remix_music(M, stem, track):
    """Swap the music of a video that's waiting for review or approval, without redoing the
    footage: only the final mix is redone (about a minute). track=None means voice only."""
    folder = next((f for f in (REVIEW, APPROVED) if pair(f, stem)[0].exists()), None)
    work = WORK / stem
    if folder is None:
        raise RuntimeError("that video is not in review or approved any more")
    if not all((work / n).exists() for n in ("combined.mp4", "audio.mp3", "subtitle.srt")):
        raise RuntimeError("the working files for this video are gone (older videos can't change music)")
    if track and track not in [n for n, _, _ in usable_tracks()]:
        raise RuntimeError("that track isn't in the approved list")
    meta = load_meta(folder, stem)
    s = load_settings()
    out = work / "remix.mp4"
    mix_final(M, s, meta.get("topic", ""), meta.get("script", ""), work / "combined.mp4", work / "audio.mp3",
              work / "subtitle.srt", out, track)
    shutil.move(str(out), str(pair(folder, stem)[0]))
    meta["music"] = track or "none"
    pair(folder, stem)[1].write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (THUMBS / f"{stem}.png").unlink(missing_ok=True)
    print(f"REMIXED {stem} with {track or 'no music'}")


# ---- Uploading -------------------------------------------------------------------

def upload_next(upload_post, svc):
    """Upload the oldest approved video. Returns (status, title, error);
    status is "posted", "unconfirmed", "failed" or "none" (nothing approved)."""
    queue = stems(APPROVED)
    if not queue:
        print("UPLOAD DUE but nothing is approved. Approve a video in the Review tab to keep the schedule.")
        return "none", None, None
    stem = queue[0]
    video, meta_file = pair(APPROVED, stem)
    meta = load_meta(APPROVED, stem)
    title = meta.get("title") or stem
    # Footage sources that require a visible credit (Vidsplay, Coverr) are named in the description
    description = "\n\n".join(x for x in [meta.get("description", "").strip(), *meta.get("credits", [])] if x)
    result = upload_post.cross_post_video(
        video_path=str(video), title=description or title, platforms=["youtube"],
        youtube_extra={
            "youtube_title": title,
            "youtube_description": description,
            "tags": meta.get("tags", []),
            "privacyStatus": svc.youtube_privacy_status,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,      # AI-generated disclosure
        })
    ok = bool(result.get("success"))
    error = str(result.get("error") or "")
    unconfirmed = "unconfirmed" in error
    status = "posted" if ok else "unconfirmed" if unconfirmed else "failed"
    if ok or unconfirmed:
        # Both count against the quota. Unconfirmed is never retried: it may already be live.
        move_pair(stem, APPROVED, POSTED if ok else CHECK)
        if ok:
            drop_work(stem)
        ledger = load_ledger()
        ledger.append({"time": datetime.now().isoformat(timespec="seconds"), "title": title,
                       "file": video.name, "status": status,
                       "request_id": result.get("request_id")})
        save_ledger(ledger)
    print(f"UPLOAD {status.upper()}: {title} {error}")
    return status, title, error or None


# ---- Entry points ------------------------------------------------------------------

def load_mpt():
    """MoneyPrinterTurbo's parts we use: the LLM, the voiceover, the final mix and Upload-Post."""
    from types import SimpleNamespace
    from app.config import config
    from app.models.schema import VideoParams
    from app.services import llm, upload_post, video
    from app.services import task as tm
    from app.utils import utils
    # Approval gate: MPT must never upload straight after rendering.
    config.app["upload_post_auto_upload"] = False
    return SimpleNamespace(config=config, VideoParams=VideoParams, llm=llm, tm=tm, video=video,
                           utils=utils, upload_post=upload_post)


def run(mode):
    """mode: "run" (scheduled), "dry" or "render"."""
    s = load_settings()
    times = parse_times(s["run_times"])
    M = load_mpt()
    mpt_dir, upload_post = Path(M.config.root_dir), M.upload_post
    svc = upload_post.upload_post_service
    for d in (REVIEW, APPROVED, POSTED):
        d.mkdir(exist_ok=True)

    now = datetime.now()
    due, why = upload_due(now, load_ledger(), int(s["monthly_uploads"]), times)
    waiting = len(stems(REVIEW)) + len(stems(APPROVED))
    print(f"Upload due: {due} ({why}) | review: {len(stems(REVIEW))}, approved: {len(stems(APPROVED))}")
    if mode == "dry":
        print(f"Would render: {waiting < int(s['buffer'])}")
        return 0

    record = {"time": now.isoformat(timespec="seconds"), "mode": mode,
              "upload_due": due if mode == "run" else None, "reason": why,
              "upload": None, "title": None, "rendered": None, "errors": []}
    if mode == "run" and due:
        if not (svc.is_configured() and "youtube" in svc.platforms):
            record["errors"].append("upload due but Upload-Post is not enabled for YouTube")
            print("UPLOAD DUE but Upload-Post is not enabled for YouTube in MPT's config.")
        else:
            status, title, error = upload_next(upload_post, svc)
            record.update(upload=status, title=title)
            if status in ("failed", "unconfirmed"):
                record["errors"].append(f"upload {status}: {error}")

    if mode == "render" or waiting < int(s["buffer"]):
        try:
            record["rendered"] = render_one(M, s).name
        except Exception as e:
            record["errors"].append(f"render failed: {type(e).__name__}: {e}")
            print(f"RENDER FAILED: {type(e).__name__}: {e}")

    days = int(s["clean_after_days"])
    if days:
        freed = clean_mpt_cache(mpt_dir, days)
        if freed:
            print(f"Clean: freed {freed / 1e6:.0f} MB of MPT cache older than {days} days")

    record["exit"] = 1 if record["errors"] else 0
    log_run(record)
    return record["exit"]


def doctor():
    """Health report as one JSON line (prefixed so callers can find it among MPT's logs)."""
    report = {"time": datetime.now().isoformat(timespec="seconds")}

    def check(name, fn):
        try:
            report[name] = fn()
        except Exception as e:
            report[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}

    M = load_mpt()
    config, llm, upload_post = M.config, M.llm, M.upload_post
    report["mpt"] = {"ok": True, "version": getattr(config, "project_version", "?"), "dir": str(config.root_dir)}

    def llm_check():
        ok, msg, secs = llm.test_connection()
        return {"ok": bool(ok), "provider": config.app.get("llm_provider"),
                "message": str(msg)[:300], "seconds": round(secs, 1)}

    def footage_check():
        sources = {}
        for name, fn in build_searchers(M):
            sources[name] = len(fn("ocean", 3) if name != "library" else [])
        library = len(clip_entries())
        return {"ok": any(v > 0 for v in sources.values()), "sample_results": sources, "library_clips": library,
                "pixabay_key": bool(config.app.get("pixabay_api_keys")),
                "coverr_key": bool(config.app.get("coverr_api_keys"))}

    def upload_check():
        svc = upload_post.upload_post_service
        return {"ok": bool(svc.is_configured() and "youtube" in svc.platforms),
                "enabled": bool(svc.enabled), "has_key": bool(svc.api_key),
                "profile_set": bool(svc.username), "platforms": list(svc.platforms),
                "auto_upload_in_config": bool(config.app.get("upload_post_auto_upload")),
                "privacy": svc.youtube_privacy_status}

    def voices_check():
        from app.services import voice
        return {"ok": True, "en_US": voice.get_all_azure_voices(["en-US"])}

    check("llm", llm_check)
    check("footage", footage_check)
    check("upload_post", upload_check)
    check("voices", voices_check)
    report["claude_cli"] = shutil.which("claude")
    print("DOCTOR_JSON:" + json.dumps(report, ensure_ascii=False))
    return 0


def self_test():
    import tempfile

    reply = 'Sure!\n```json\n["Why rich people rent", "The latte myth", "why RICH people rent"]\n```'
    assert parse_topics(reply, [], 5) == ["Why rich people rent", "The latte myth"]
    assert parse_topics(reply, ["the latte myth"], 5) == ["Why rich people rent"]
    src = "# c\nCalm.mp3 | YouTube Audio Library | calm, soft\nloose.mp3\nnotes.txt | x\ngone.mp3 | YTAL"
    assert approved_tracks(src, ["calm.mp3", "loose.mp3", "notes.txt"]) == ["calm.mp3"]
    assert parse_music_sources(src)[0] == ("Calm.mp3", "YouTube Audio Library", "calm, soft")

    # music choice: modes, never an unlisted/absent track, avoids repeats, falls back when Claude fails
    tr = [("a.mp3", "s", "calm"), ("b.mp3", "s", "energetic, fast"), ("c.mp3", "s", "upbeat")]
    assert choose_track({"music_mode": "none"}, tr) is None and choose_track({"music_mode": "auto"}, []) is None
    assert choose_track({"music_mode": "fixed", "music_track": "c.mp3"}, tr) == "c.mp3"
    assert choose_track({"music_mode": "fixed", "music_track": "zzz.mp3"}, tr[:1]) == "a.mp3"   # missing -> auto
    asked = []
    pick_b = lambda p: (asked.append(p), '{"track": "b.mp3"}')[1]                              # noqa: E731
    assert choose_track({"music_mode": "auto"}, tr, pick_b, "T", "script") == "b.mp3" and "energetic, fast" in asked[0]
    assert choose_track({"music_mode": "auto"}, tr, pick_b, recent=("b.mp3",)) in ("a.mp3", "c.mp3")
    assert choose_track({"music_mode": "auto"}, tr, lambda p: '{"track": "evil.mp3"}') in ("a.mp3", "b.mp3", "c.mp3")
    assert choose_track({"music_mode": "auto"}, tr, lambda p: 1 / 0) in ("a.mp3", "b.mp3", "c.mp3")

    # footage logic (pure)
    srt = "1\n00:00:00,100 --> 00:00:02,000\nHello there,\n\n2\n00:00:02,000 --> 00:00:03,900\nfriend.\n\n" \
          "3\n00:00:03,900 --> 00:00:09,800\nA long second sentence follows here."
    segs = footage.parse_srt(srt)
    assert segs[0] == (0.1, 2.0, "Hello there,") and len(segs) == 3
    beats = footage.make_beats(segs, 10.0)
    assert beats[0][0] == 0.0 and beats[-1][1] == 10.0 and all(a[1] == b[0] for a, b in zip(beats, beats[1:]))
    assert beats[1][0] == 3.9                                   # the picture changes when the words do
    assert [round(x, 2) for x in footage.cut_lengths(1.0)] == [1.0] and len(footage.cut_lengths(6.0)) == 2
    assert footage.window(10, 3)[2] == 1.0 and footage.window(3.3, 4.2)[2] < 1.0 and footage.window(2, 4.2) is None
    assert footage.credits_for(["Vidsplay", "Mixkit", "pixabay"]) == ["Footage: Vidsplay.com"]
    assert footage.parse_queries('x [{"i": 2, "queries": ["Cash  Counting", "money"]}]', 2) == [[], ["cash counting", "money"]]
    assert footage.parse_picks('{"1": [2, 9, 2, 1], "7": [1]}', {1: 3}) == {1: [2, 1]}
    assert footage.pick_rendition({"large": {"url": "u", "height": 2160, "size": 5e6},
                                   "medium": {"url": "u", "height": 1080, "size": 1e6}})[0] == "large"
    fake = [("one", lambda q, d: [{"id": f"one:{q}", "dur": 9}]), ("bad", lambda q, d: 1 / 0)]
    got = footage.gather([(0, 3, "x"), (3, 6, "y")], [["cash"], []], fake, log=lambda m: None, pause=0)
    assert [c["id"] for c in got[0]] == ["one:cash"] and got[1]                  # failing source skipped, fallback used
    try:
        footage.gather([(0, 3, "x")], [["q"]], [("bad", lambda q, d: 1 / 0)], log=lambda m: None, pause=0)
        raise AssertionError("gather should fail when no footage exists")
    except RuntimeError:
        pass

    # real ffmpeg: cut two synthetic landscape clips to exact beat lengths, join, check size and time
    import tempfile as _tf
    with _tf.TemporaryDirectory() as t2:
        t2 = Path(t2)
        for name, src_ in (("a.mp4", "testsrc=size=1920x1080:rate=30"), ("b.mp4", "smptebars=size=1280x720:rate=30")):
            r = footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i", f"{src_}:duration=6",
                             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(t2 / name)])
            assert r.returncode == 0, r.stderr
        ranked = {0: [{"id": "t:a", "path": str(t2 / "a.mp4"), "source": "x"}],
                  1: [{"id": "t:b", "path": str(t2 / "b.mp4"), "source": "x"}]}
        out, used = footage.compose([(0.0, 3.0, "a"), (3.0, 8.5, "b")], ranked, t2 / "w", t2 / "cache", log=lambda m: None)
        dur, w, h = footage.probe(out)
        assert (w, h) == (1080, 1920) and abs(dur - 8.5) < 0.25 and len(used) == 2, (dur, w, h)
        # music is cut to the video's length (trimmed when long, looped when short)
        tone = t2 / "tone.mp3"
        r = footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                         str(tone)])
        assert r.returncode == 0, r.stderr
        for secs in (2.0, 5.0):
            fitted = footage.fit_audio(tone, secs, t2 / f"fit{secs}.mp3")
            assert abs(footage.probe(fitted)[0] - secs) < 0.15, (secs, footage.probe(fitted))
    assert slugify("Why $9.99 tricks you!") == "why-9-99-tricks-you"
    assert parse_times(["19:00", "9:30", "19:00"]) == [(9, 30), (19, 0)]
    for bad in (["25:00"], [], ["x"]):
        try:
            parse_times(bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass

    # Upload spacing: every free upload used, no long gaps.
    times = parse_times(DEFAULTS["run_times"])
    nov = plan_uploads(datetime(2026, 10, 31, 23), [], 10, times, datetime(2026, 11, 30, 23, 59))
    assert len(nov) == 10, len(nov)
    gaps = {(b - a).days for a, b in zip(nov, nov[1:])}
    assert gaps <= {2, 3, 4}, gaps
    octo = plan_uploads(datetime(2026, 10, 26, 12), [{"time": "2026-10-26T11:15:33"}], 10, times,
                        datetime(2026, 10, 31, 23, 59))
    assert len(octo) == 9, len(octo)

    with tempfile.TemporaryDirectory() as tmp:
        set_base(tmp)
        try:
            # settings round-trip, unknown keys dropped, validation
            assert load_settings() == DEFAULTS
            SETTINGS.write_text('{"buffer": 5, "junk": 1}', encoding="utf-8")
            assert load_settings()["buffer"] == 5 and "junk" not in load_settings()
            try:
                save_settings({**DEFAULTS, "run_times": ["99:00"]})
                raise AssertionError("bad time saved")
            except ValueError:
                pass

            # queue moves keep .mp4 + .json together
            REVIEW.mkdir()
            for name in ("20261101-0900-a", "20261102-0900-b"):
                (REVIEW / f"{name}.mp4").write_bytes(b"x")
                (REVIEW / f"{name}.json").write_text('{"title": "t"}', encoding="utf-8")
            approve("20261101-0900-a")
            assert stems(APPROVED) == ["20261101-0900-a"] and (APPROVED / "20261101-0900-a.json").exists()
            save_meta(APPROVED, "20261101-0900-a", " New ", "d", ["#a", " ", "#b"])
            assert load_meta(APPROVED, "20261101-0900-a")["tags"] == ["#a", "#b"]
            unapprove("20261101-0900-a")
            for bad in (("", ""), ("nonsense", ""), ("other", "  ")):   # a real reason is required
                try:
                    reject("20261102-0900-b", *bad)
                    raise AssertionError(f"rejected without a reason: {bad}")
                except ValueError:
                    pass
            assert stems(REVIEW) == ["20261101-0900-a", "20261102-0900-b"] and not FEEDBACK.exists()
            (REVIEW / "20261102-0900-b.json").write_text(
                '{"topic": "Why tax refunds feel free", "title": "T", "script": "s"}', encoding="utf-8")
            reject("20261102-0900-b", "topic", "too generic, I want specific numbers")
            assert stems(REVIEW) == ["20261101-0900-a"] and not stems(APPROVED)
            fb = load_feedback()
            assert len(fb) == 1 and fb[0]["category"] == "topic" and fb[0]["topic"] == "Why tax refunds feel free"

            # learning: bad/empty LLM output falls back to the raw notes; results are cached
            assert parse_lessons('x {"topic": ["a", " "], "script": "oops", "extra": ["z"]}') == \
                {"topic": ["a"], "script": [], "footage": []}
            assert parse_lessons("no json here") == {"topic": [], "script": [], "footage": []}
            calls = []

            def llm_ok(prompt):
                calls.append(prompt)
                return '{"topic": ["Use concrete numbers in the topic"], "script": [], "footage": []}'
            rules = build_lessons(llm_ok)
            assert rules["topic"] == ["Use concrete numbers in the topic"] and len(calls) == 1
            assert "too generic" in calls[0]
            assert build_lessons(llm_ok) == rules and len(calls) == 1          # cached: no 2nd LLM call
            (REVIEW / "20261101-0900-a.json").write_text('{"topic": "t2"}', encoding="utf-8")
            reject("20261101-0900-a", "footage", "clips of animals in a money video")
            assert fallback_lessons(load_feedback())["footage"] == ["clips of animals in a money video"]

            def llm_bad(prompt):
                raise RuntimeError("boom")
            rules = build_lessons(llm_bad)                                      # new feedback, LLM down
            assert rules["footage"] == ["clips of animals in a money video"]
            assert rules["topic"] and "Why tax refunds feel free" in rules["topic"][0]
            assert load_lessons()["based_on"] == 2
            assert "Follow them strictly" in lessons_block(rules, "topic") and lessons_block(rules, "script") == ""
            assert "FOOTAGE" in lessons_summary() and "2 rejection" in lessons_summary()

            # unconfirmed upload resolution
            CHECK.mkdir()
            (CHECK / "c.mp4").write_bytes(b"x")
            save_ledger([{"time": "2026-11-01T09:00:00", "file": "c.mp4", "status": "unconfirmed"}])
            resolve_check("c", uploaded=False)
            assert stems(APPROVED) == ["c"] and load_ledger() == []

            # music list add/remove
            track = Path(tmp) / "Calm.mp3"
            track.write_bytes(b"x")
            add_track(track, "YouTube Audio Library", "calm, soft")
            assert music_entries() == [("Calm.mp3", "YouTube Audio Library", "calm, soft", True)]
            assert usable_tracks() == [("Calm.mp3", "YouTube Audio Library", "calm, soft")]
            remove_track("Calm.mp3")
            assert music_entries() == [] and usable_tracks() == []

            # clip library: needs a source and tags; only listed + present clips count
            clip = Path(tmp) / "Money Walk.mp4"
            clip.write_bytes(b"x")
            for bad in (("", "tags"), ("Mixkit", "")):
                try:
                    add_clip(clip, *bad)
                    raise AssertionError("clip added without source/tags")
                except ValueError:
                    pass
            add_clip(clip, "Vidsplay", "money, walking")
            assert clip_entries() == [("Money Walk.mp4", "Vidsplay", "money, walking", True)]
            assert [c["source"] for c in footage.load_library(CLIPS)] == ["Vidsplay"]
            remove_clip("Money Walk.mp4")
            assert clip_entries() == [] and not (CLIPS / "Money Walk.mp4").exists()

            # work folders (kept so music can be swapped) are deleted with the video
            (WORK / "v1").mkdir(parents=True)
            (WORK / "v1" / "combined.mp4").write_bytes(b"x")
            drop_work("v1")
            assert not (WORK / "v1").exists()
            # recent tracks come from the saved videos' metadata, newest first
            (REVIEW / "r1.mp4").write_bytes(b"x")
            (REVIEW / "r1.json").write_text('{"music": "x.mp3", "rendered": "2026-10-01T10:00:00"}', encoding="utf-8")
            (REVIEW / "r2.mp4").write_bytes(b"x")
            (REVIEW / "r2.json").write_text('{"music": "y.mp3", "rendered": "2026-10-02T10:00:00"}', encoding="utf-8")
            assert recent_tracks(2) == ["y.mp3", "x.mp3"] and recent_tracks(1) == ["y.mp3"]

            # lock is exclusive while held, free afterwards
            with RunLock():
                assert is_running()
            assert not is_running()

            # cleanup only removes old entries
            cache = Path(tmp) / "storage" / "cache_videos"
            cache.mkdir(parents=True)
            (cache / "old.mp4").write_bytes(b"12345")
            assert clean_mpt_cache(tmp, 14, now=datetime.now() + timedelta(days=15)) == 5
            assert clean_mpt_cache(tmp, 0) == 0
        finally:
            set_base(HERE)
    print("self-test passed")


def main(args):
    if "--self-test" in args:
        self_test()
        return 0
    if "--doctor" in args:
        return doctor()
    if "--dry-run" in args:
        return run("dry")
    mode = "render" if "--render" in args else "run"
    try:
        with RunLock():
            if "--remix" in args:             # --remix <video name> <track file or "none">
                i = args.index("--remix")
                remix_music(load_mpt(), args[i + 1], None if args[i + 2] == "none" else args[i + 2])
                return 0
            return run(mode)
    except AlreadyRunning:
        print("Another run is in progress; skipping this one.")
        return 0


if __name__ == "__main__":
    import os
    args = sys.argv[1:]
    log = os.environ.get("AUTOPILOT_LOG")
    if log and "--doctor" not in args and "--self-test" not in args:
        # Python opens files with sharing allowed, so overlapping runs can all append;
        # a cmd ">>" redirect would lock the log against the second run.
        sys.stdout = sys.stderr = open(log, "a", encoding="utf-8", buffering=1)
        print(f"===== [{datetime.now():%Y-%m-%d %H:%M:%S}] start {' '.join(args)} =====")
    code = 1
    try:
        code = main(args)
    finally:
        if log and "--doctor" not in args and "--self-test" not in args:
            print(f"===== [{datetime.now():%Y-%m-%d %H:%M:%S}] exit code {code} =====")
    sys.exit(code)
