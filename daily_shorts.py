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

DEFAULTS = {
    "niche": "money psychology and surprising personal finance facts",
    "language": "en-US",
    "voice": "en-US-ChristopherNeural-Male",
    "script_rules": (
        "Write 120-140 words (about 50 seconds spoken). "
        "First sentence is a hook that creates a curiosity gap, no greetings. "
        "Short punchy sentences. End with a question that invites comments."
    ),
    "monthly_uploads": 10,              # Upload-Post free plan; raise if you upgrade
    "run_times": ["09:00", "19:00"],    # Task Scheduler times; upload spacing uses them
    "buffer": 3,                        # videos to keep waiting for review/upload
    "music_volume": 0.12,               # quiet bed under the voice
    "clean_after_days": 14,             # delete MPT render caches older than this (0 = never)
}

PATCH_MARKERS = ('"video_type": "film"', '"tags": str(v.get("tags")')
AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
HERE = Path(__file__).resolve().parent


def set_base(base):
    """Point every data path at `base` (the project folder; tests use a temp dir)."""
    global BASE, SETTINGS, HISTORY, LOG_DIR, RUNS, LOCK, LEDGER, SAFE_MUSIC, MUSIC_SOURCES
    global REVIEW, APPROVED, POSTED, CHECK, THUMBS
    BASE = Path(base)
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


def reject(stem):
    for f in (*pair(REVIEW, stem), THUMBS / f"{stem}.png"):
        f.unlink(missing_ok=True)


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
        for e in ledger:
            if e.get("file") == file:
                e["status"] = "posted"
    else:
        move_pair(stem, CHECK, APPROVED)
        ledger = [e for e in ledger if e.get("file") != file]
    save_ledger(ledger)


# ---- Music -----------------------------------------------------------------------

def approved_tracks(sources_text, files_present):
    """Tracks that are both in the folder AND listed with a source. Unlisted = never used."""
    present = {f.lower(): f for f in files_present}
    ok = []
    for line in sources_text.splitlines():
        name, sep, source = (p.strip() for p in line.partition("|"))
        if line.strip().startswith("#") or not sep or not source:
            continue
        if Path(name).suffix.lower() in AUDIO_EXT and name.lower() in present:
            ok.append(present[name.lower()])
    return ok


def music_entries():
    """[(filename, source, file_present)] for every track listed in SOURCES.txt."""
    if not MUSIC_SOURCES.exists():
        return []
    out = []
    for line in MUSIC_SOURCES.read_text(encoding="utf-8").splitlines():
        name, sep, source = (p.strip() for p in line.partition("|"))
        if line.strip().startswith("#") or not sep:
            continue
        out.append((name, source, (SAFE_MUSIC / name).is_file()))
    return out


def add_track(src_file, source):
    if not source.strip():
        raise ValueError("a source/license note is required")
    src = Path(src_file)
    if src.suffix.lower() not in AUDIO_EXT:
        raise ValueError(f"not an audio file: {src.name}")
    if "|" in src.name:
        raise ValueError("file names can't contain '|'")
    SAFE_MUSIC.mkdir(exist_ok=True)
    shutil.copyfile(src, SAFE_MUSIC / src.name)
    with MUSIC_SOURCES.open("a", encoding="utf-8") as f:
        f.write(f"\n{src.name} | {source.strip()}")


def remove_track(name):
    lines = MUSIC_SOURCES.read_text(encoding="utf-8").splitlines() if MUSIC_SOURCES.exists() else []
    keep = [l for l in lines if l.partition("|")[0].strip().lower() != name.lower() or l.strip().startswith("#")]
    MUSIC_SOURCES.write_text("\n".join(keep) + "\n", encoding="utf-8")
    (SAFE_MUSIC / name).unlink(missing_ok=True)


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


def patch_applied(mpt_dir):
    material = Path(mpt_dir) / "app" / "services" / "material.py"
    if not material.exists():
        return False
    text = material.read_text(encoding="utf-8")
    return all(m in text for m in PATCH_MARKERS)


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


def parse_ids(text):
    match = re.search(r"\[.*?\]", text, re.S)
    return {str(i) for i in json.loads(match.group(0))} if match else set()


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50]


# ---- Rendering (needs MoneyPrinterTurbo) ---------------------------------------------

def ask(llm, prompt):
    reply = llm._generate_response(prompt)  # MPT returns "Error: ..." instead of raising
    if reply.startswith("Error:"):
        raise RuntimeError(reply)
    return reply


def pick_topic(llm, s):
    used = HISTORY.read_text(encoding="utf-8").splitlines() if HISTORY.exists() else []
    reply = ask(llm, (
        f"Give 6 YouTube Shorts video topics for the niche: {s['niche']}. "
        "Each topic is one specific, curiosity-driven idea in under 12 words. "
        f"Do not repeat or closely resemble these past topics: {used[-100:]}. "
        "Reply with only a JSON array of strings."))
    topics = parse_topics(reply, used, 1)
    if not topics:
        raise RuntimeError("LLM returned no new topic")
    return topics[0]


def pick_terms(llm, script):
    """Short concrete search words, in script order. MPT's own terms are abstract
    3-word phrases that mostly return 0 stock clips."""
    reply = ask(llm, (
        "For this voiceover, list 18 stock-video search terms in the same order as the script. "
        "Each term is 1-2 concrete, filmable English words (e.g. 'wallet', 'cash counting', "
        "'stock chart', 'worried woman'). No abstract ideas, no brand names.\n\n"
        f"Script: {script}\n\nReply with only a JSON array of strings."))
    return parse_topics(reply, [], 20)


def add_tag_filter(material, original, llm, topic):
    """Wrap MPT's Pixabay search: the LLM drops clips whose tags don't fit the term.
    Needs the MPT patch that keeps Pixabay's `tags` (patches/mpt-material.patch)."""
    def filtered(search_term, *args, **kwargs):
        items = original(search_term, *args, **kwargs)
        tagged = [i for i in items if (i.source_info or {}).get("tags")]
        if not tagged:
            return items
        listing = "\n".join(f'{i.source_info["asset_id"]}: {i.source_info["tags"]}' for i in tagged)
        reply = llm._generate_response(
            f"A Shorts video about '{topic}' needs a stock clip for: '{search_term}'.\n"
            "Each line is a clip id and its tags. Keep only clips that clearly show this. "
            f"Reply with only a JSON array of kept ids.\n\n{listing}")
        if reply.startswith("Error:"):
            return items  # ponytail: filter failure keeps all clips rather than failing the video
        keep = parse_ids(reply)
        kept = [i for i in tagged if i.source_info["asset_id"] in keep]
        print(f"Tag filter '{search_term}': kept {len(kept)}/{len(tagged)}")
        return kept

    material.search_videos_pixabay = filtered


def pick_music(bgm_dir, s):
    """Never let MPT choose music: its bundled 'random' songs triggered a Content ID block.
    Use an approved track (copied into MPT's allowed bgm folder) or no music at all."""
    SAFE_MUSIC.mkdir(exist_ok=True)
    text = MUSIC_SOURCES.read_text(encoding="utf-8") if MUSIC_SOURCES.exists() else ""
    tracks = approved_tracks(text, [p.name for p in SAFE_MUSIC.iterdir() if p.is_file()])
    if not tracks:
        print("Music: none (no approved tracks in safe_music/SOURCES.txt) - voice only")
        return {"bgm_type": "none", "bgm_file": ""}, None
    name = random.choice(tracks)
    dest = Path(bgm_dir) / f"safe-{name}"
    shutil.copyfile(SAFE_MUSIC / name, dest)
    print(f"Music: {name} (approved)")
    return {"bgm_type": "custom", "bgm_file": str(dest), "bgm_volume": float(s["music_volume"])}, name


def render_one(mpt, s):
    config, VideoParams, llm, tm, material, bgm = mpt
    topic = pick_topic(llm, s)
    script = llm.generate_script(video_subject=topic, language=s["language"],
                                 video_script_prompt=s["script_rules"])
    if not script or script.startswith("Error"):
        raise RuntimeError(f"script failed: {script}")
    terms = pick_terms(llm, script)
    music, track = pick_music(bgm.uploaded_bgm_dir(create=True), s)
    print("Topic:", topic, "| Search terms:", terms)

    original = material.search_videos_pixabay
    add_tag_filter(material, original, llm, topic)
    try:
        result = tm.start(str(uuid4()), VideoParams(
            video_subject=topic,
            video_script=script,
            video_terms=terms,
            video_language=s["language"],
            voice_name=s["voice"],
            video_aspect="9:16",
            video_source=config.app.get("video_source") or "pexels",
            video_clip_duration=3,           # fast cuts keep viewers from swiping
            match_materials_to_script=True,  # search clips per sentence
            subtitle_position="center",      # bottom gets covered by the Shorts UI
            font_name="BeVietnamPro-Bold.ttf",
            font_size=90,
            stroke_width=5,
            **music,                         # approved track or none, never MPT's bundled songs
        ))
    finally:
        material.search_videos_pixabay = original
    videos = result.get("videos")
    if not videos:
        raise RuntimeError(f"render failed: {result.get('error')}")

    meta = llm.generate_social_metadata(video_subject=topic, video_script=script,
                                        language=s["language"], platform="youtube_shorts")
    REVIEW.mkdir(exist_ok=True)
    base = REVIEW / f"{datetime.now():%Y%m%d-%H%M}-{slugify(topic)}"
    shutil.copyfile(videos[0], base.with_suffix(".mp4"))
    base.with_suffix(".json").write_text(json.dumps({
        "topic": topic,
        "title": meta.get("title") or topic,          # editable in the GUI before approving
        "description": meta.get("caption", ""),
        "tags": meta.get("hashtags", []),
        "music": track or "none",
        "script": script,
        "rendered": datetime.now().isoformat(timespec="seconds"),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    with HISTORY.open("a", encoding="utf-8") as f:
        f.write(topic + "\n")
    print(f"READY FOR REVIEW: {base.with_suffix('.mp4')}")
    return base.with_suffix(".mp4")


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
    result = upload_post.cross_post_video(
        video_path=str(video), title=meta.get("description") or title, platforms=["youtube"],
        youtube_extra={
            "youtube_title": title,
            "youtube_description": meta.get("description", ""),
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
        ledger = load_ledger()
        ledger.append({"time": datetime.now().isoformat(timespec="seconds"), "title": title,
                       "file": video.name, "status": status,
                       "request_id": result.get("request_id")})
        save_ledger(ledger)
    print(f"UPLOAD {status.upper()}: {title} {error}")
    return status, title, error or None


# ---- Entry points ------------------------------------------------------------------

def load_mpt():
    from app.config import config
    from app.models.schema import VideoParams
    from app.services import bgm, llm, material, upload_post
    from app.services import task as tm
    # Approval gate: MPT must never upload straight after rendering.
    config.app["upload_post_auto_upload"] = False
    return config, VideoParams, llm, tm, material, bgm, upload_post


def run(mode):
    """mode: "run" (scheduled), "dry" or "render"."""
    s = load_settings()
    times = parse_times(s["run_times"])
    config, VideoParams, llm, tm, material, bgm, upload_post = load_mpt()
    mpt_dir = Path(config.root_dir)
    svc = upload_post.upload_post_service
    for d in (REVIEW, APPROVED, POSTED):
        d.mkdir(exist_ok=True)
    if not patch_applied(mpt_dir):
        print("WARNING: MPT patch missing (apply it in the Setup tab). "
              "Footage may include animations and the tag filter is off.")

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
            record["rendered"] = render_one((config, VideoParams, llm, tm, material, bgm), s).name
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

    config, VideoParams, llm, tm, material, bgm, upload_post = load_mpt()
    report["mpt"] = {"ok": True, "version": getattr(config, "project_version", "?"),
                     "dir": str(config.root_dir), "patch": patch_applied(config.root_dir)}

    def llm_check():
        ok, msg, secs = llm.test_connection()
        return {"ok": bool(ok), "provider": config.app.get("llm_provider"),
                "message": str(msg)[:300], "seconds": round(secs, 1)}

    def footage_check():
        from app.models.schema import VideoAspect
        source = config.app.get("video_source")
        if source != "pixabay":
            return {"ok": True, "source": source, "note": "only Pixabay is checked"}
        # "ocean"/"people" reliably have vertical full-HD clips; this checks the key works.
        count = sum(len(material.search_videos_pixabay(t, 3, VideoAspect.portrait))
                    for t in ("ocean", "people"))
        return {"ok": count > 0, "source": source, "sample_results": count}

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
    assert parse_ids('Kept: ["12", 34]') == {"12", "34"}
    src = "# c\nCalm.mp3 | YouTube Audio Library\nloose.mp3\nnotes.txt | x\ngone.mp3 | YTAL"
    assert approved_tracks(src, ["calm.mp3", "loose.mp3", "notes.txt"]) == ["calm.mp3"]
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
            reject("20261102-0900-b")
            assert stems(REVIEW) == ["20261101-0900-a"] and not stems(APPROVED)

            # unconfirmed upload resolution
            CHECK.mkdir()
            (CHECK / "c.mp4").write_bytes(b"x")
            save_ledger([{"time": "2026-11-01T09:00:00", "file": "c.mp4", "status": "unconfirmed"}])
            resolve_check("c", uploaded=False)
            assert stems(APPROVED) == ["c"] and load_ledger() == []

            # music list add/remove
            track = Path(tmp) / "Calm.mp3"
            track.write_bytes(b"x")
            add_track(track, "YouTube Audio Library")
            assert music_entries() == [("Calm.mp3", "YouTube Audio Library", True)]
            remove_track("Calm.mp3")
            assert music_entries() == []

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
