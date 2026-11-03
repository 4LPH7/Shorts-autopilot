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
import os
import random
import re
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent))
import footage  # noqa: E402  (sits next to this file)

DEFAULTS = {
    "niche": (
        "Dark psychology of emotional persuasion and demographic manipulation — exposing how corporations, "
        "algorithms, luxury brands, and gurus exploit our deepest primal fears, secret desires, and raw vulnerabilities. "
        "The viral checklist of human emotional hooks:\n"
        "• Men: Primal lust, hunger for power, respect, and terror of insignificance.\n"
        "• Women: Unrealistic beauty standards, the dread of aging, craving emotional safety and adoration.\n"
        "• Parents: Crushing parental guilt, chronic exhaustion, desperate protective instincts, and buying peace of mind.\n"
        "• Kids: Pure wonder, boundless dreams, grand ambitions, and the intoxicating thrill of adventure.\n"
        "• The Rich: Obsessive paranoia of losing wealth, capital preservation, insomnia over collapse, and desperately buying back time.\n"
        "• The Poor / Broke: Suffocating financial anxiety, desperate hope, the seductive promise of get-rich-quick shortcuts, and reclaiming human dignity.\n"
        "• The Old: Heartbreaking nostalgia, grief over lost youth, fighting physical decline, and the yearning for vitality and dignity.\n"
        "• The Young: Burning status anxiety, FOMO, identity crises, rebellion against authority, and the terror of being ordinary.\n"
        "• The Lonely: The deafening ache of isolation, the desperate hunger for belonging, acceptance, intimacy, and a tribe.\n"
        "• The Sick: Agonizing vulnerability, fear of mortality, and grasping at miracles or relief at any financial cost.\n"
        "• The Healthy: Silent paranoia of invisible illness, hypochondria, mortality anxiety, and the obsessive quest to cheat death.\n"
        "• The Smart: Intellectual arrogance, impatience with the crowd, and an obsession with secret cheat codes, leverage, and unfair shortcuts.\n"
        "• The Dumb / Insecure: Painful feelings of inadequacy, desperate craving for applause, ego validation, and illusory moral superiority.\n"
        "• The Faithful: Cosmic dread of chaos, seeking refuge in absolute certainty, dogmatic belonging, and divine purpose.\n"
        "• The Faithless / Skeptics: Cynical rebellion, the adrenaline rush of exposing hypocrisy, and uncovering forbidden taboo truths.\n"
        "• Everyone: The brutal ticking clock of mortality — our desperate hunger to buy back stolen time, freedom, and autonomy.\n"
        "Each video exposes the shocking psychological manipulation, emotional traps, and hidden marketing tactics behind why we buy, believe, crave, and obey."
    ),
    "language": "en-US",
    "voice": "en-US-AndrewMultilingualNeural",   # warm and conversational; audition the others in Settings
    "voice_engine": "edge",             # edge (Microsoft neural voices), kokoro (runs on this PC) or mpt (the old way)
    "voice_master": True,               # warmth, presence and a gentle compressor, so a synthetic voice sounds recorded
    "sfx_level": "subtle",              # sound effects: off, subtle (every other cut + big numbers) or full
                                        # (the "Multilingual" voices stall on the free Edge TTS service)
    "voice_rate": 1.05,                 # 1.0 = normal; 1.05 is lively without rushing
    "script_rules": (
        "Write 150-165 words (about 63-69 seconds when spoken at this pace). "
        "Intense, emotionally gripping, and razor-sharp—like revealing a forbidden psychological truth that hits right where it hurts. "
        "First sentence is an irresistible curiosity hook exposing how our emotions are secretly manipulated, no greetings. "
        "Fast, punchy sentences, raw emotional tension (fear, ambition, guilt, lust, hope), and vivid sensory language. "
        "Unmask the hidden psychological trap with shocking clarity. "
        "End with a provocative, debate-sparking question that compels viewers to comment."
    ),
    "monthly_uploads": 10,              # Upload-Post free plan; raise if you upgrade
    "quota_reset_day": 25,              # day of the month Upload-Post resets the quota (1-28)
    "meter_used": 0,                    # the calls/uploads shown on Upload-Post's meter...
    "meter_date": "",                   # ...and the date you read it (ISO); used only if from this cycle
    "upload_mode": "auto",              # auto = Upload-Post posts approved videos; manual = you upload them
    "run_times": ["09:00", "19:00"],    # Task Scheduler times; upload spacing uses them
    "buffer": 3,                        # videos to keep waiting for review/upload
    "music_mode": "auto",               # auto = AI picks the best-fitting approved track; fixed; none
    "music_track": "",                  # the track used when music_mode is "fixed"
    "music_volume": 0.2,                # a clearly audible bed, about 5 dB under the voice
    "clean_after_days": 14,             # delete MPT render caches older than this (0 = never)
    "motion_level": "subtle",           # animated captions and camera moves: off, subtle or dynamic
    "look": "clean",                    # one colour grade over every clip: clean, cinematic or warm
    "accent_color": "#FFD60A",          # the single highlight colour (keywords and big numbers)
}
AUDIENCE_HOOKS = (
    "Men: lust, respect, primal power, fear of insignificance; "
    "Women: beauty, youth, emotional safety, craving adoration; "
    "Parents: peace of mind, relief from crushing parental guilt, child protection; "
    "Kids: grand dreams, limitless wonder, ambition, thrilling adventure; "
    "Rich: safety, stability, paranoia of loss, buying back time; "
    "Poor / Broke: desperate hope, escape from debt, desire to get rich quick, reclaiming dignity; "
    "Old: youth, vitality, fighting decay, nostalgia, lasting legacy; "
    "Young: status, identity, rebellion, burning fear of being ordinary; "
    "Lonely: belonging, community, deep connection, ending isolation; "
    "Sick: miracles, desperate hope, instant relief from agony; "
    "Healthy: fear (of losing health), mortality anxiety, biohacking obsession; "
    "Smart: shortcuts, unfair advantages, asymmetric leverage; "
    "Dumb / Insecure: validation, ego flattery, illusion of moral superiority; "
    "Faithful: certainty, divine purpose, dogmatic comfort; "
    "Faithless: rebellion, unmasking hypocrisy, raw taboo truths; "
    "Everyone: time, freedom, autonomy."
)
MUSIC_MODES = ("auto", "fixed", "none")
VOICE_ENGINES = ("edge", "kokoro", "mpt")
SFX_LEVELS = ("off", "subtle", "full")
MOTION_LEVELS = ("off", "subtle", "dynamic")
LOOKS = ("clean", "cinematic", "warm")
# Quota cycle, copied from the settings by load_settings(). Tests set it explicitly.
QUOTA = {"reset_day": 1, "meter_used": 0, "meter_date": None}

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
HERE = Path(__file__).resolve().parent


def set_base(base):
    """Point every data path at `base` (the project folder; tests use a temp dir)."""
    global BASE, SETTINGS, HISTORY, LOG_DIR, RUNS, LOCK, LEDGER, SAFE_MUSIC, MUSIC_SOURCES
    global REVIEW, APPROVED, POSTED, CHECK, THUMBS, FEEDBACK, LESSONS, WORK, CLIPS, CLIPS_SOURCES, UPLOAD_STATE, BACKUP, INFLIGHT
    BASE = Path(base)
    WORK = BASE / "work"                      # per-video leftovers that allow swapping the music later
    CLIPS = BASE / "clips"                    # your hand-downloaded clips (Mixkit, Vidsplay, ...)
    CLIPS_SOURCES = CLIPS / "SOURCES.txt"
    UPLOAD_STATE = BASE / "upload_state.json" # why automatic uploads are paused, if they are
    BACKUP = BASE / "backup"                  # originals kept before a fix (see fix_loudness)
    INFLIGHT = BASE / "upload_inflight.json"  # exists while an upload is under way; left behind if the run is killed
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
    QUOTA.update(reset_day=int(s["quota_reset_day"]), meter_used=int(s["meter_used"] or 0),
                 meter_date=s["meter_date"] or None)
    return s


def save_settings(s):
    clean = {k: s.get(k, DEFAULTS[k]) for k in DEFAULTS}
    parse_times(clean["run_times"])  # validate before writing
    for k in ("monthly_uploads", "buffer", "clean_after_days"):
        clean[k] = int(clean[k])
        if clean[k] < 0:
            raise ValueError(f"{k} can't be negative")
    if not 1 <= int(clean["quota_reset_day"]) <= 28:
        raise ValueError("the quota reset day must be between 1 and 28")
    clean["quota_reset_day"] = int(clean["quota_reset_day"])
    clean["meter_used"] = int(clean["meter_used"] or 0)
    if clean["meter_used"] < 0:
        raise ValueError("the meter reading can't be negative")
    clean["meter_date"] = clean["meter_date"] or ""
    clean["music_volume"] = float(clean["music_volume"])
    clean["voice_rate"] = float(clean["voice_rate"])
    if not 0.7 <= clean["voice_rate"] <= 1.5:
        raise ValueError("voice speed must be between 0.7 and 1.5")
    if not 0 <= clean["music_volume"] <= 1:
        raise ValueError("music volume must be between 0 and 1")
    if clean["upload_mode"] not in ("auto", "manual"):
        raise ValueError("upload mode must be auto or manual")
    if clean["music_mode"] not in MUSIC_MODES:
        raise ValueError(f"music mode must be one of {MUSIC_MODES}")
    if clean["voice_engine"] not in VOICE_ENGINES:
        raise ValueError(f"voice engine must be one of {VOICE_ENGINES}")
    if clean["sfx_level"] not in SFX_LEVELS:
        raise ValueError(f"sound effects must be one of {SFX_LEVELS}")
    clean["voice_master"] = bool(clean["voice_master"])
    if clean["motion_level"] not in MOTION_LEVELS:
        raise ValueError(f"motion must be one of {MOTION_LEVELS}")
    if clean["look"] not in LOOKS:
        raise ValueError(f"look must be one of {LOOKS}")
    accent = str(clean["accent_color"])
    if not (len(accent) == 7 and accent[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in accent[1:])):
        raise ValueError("the highlight colour must look like #FFD60A")
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
    """Start and end of the quota cycle containing `now`. The cycle resets on QUOTA["reset_day"]."""
    d = QUOTA["reset_day"]
    if now.day >= d:
        start = datetime(now.year, now.month, d)
    else:
        prev = datetime(now.year, now.month, 1) - timedelta(days=1)
        start = datetime(prev.year, prev.month, d)
    nxt = datetime(start.year + (start.month == 12), start.month % 12 + 1, d)
    return start, nxt - timedelta(seconds=1)


def used_this_month(ledger, now):
    """Uploads used in the current cycle. The meter reading counts when it was taken this cycle;
    the higher of the two numbers is used, so the app never plans more than the meter allows."""
    start, _ = month_bounds(now)
    count = sum(datetime.fromisoformat(e["time"]) >= start for e in ledger if not e.get("manual"))
    if QUOTA.get("meter_date") and datetime.fromisoformat(QUOTA["meter_date"]) >= start:
        return max(count, int(QUOTA.get("meter_used") or 0))
    return count


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

# ---- Upload mode: automatic through Upload-Post, or manual by you ---------------------------

YOUTUBE_UPLOAD_URL = "https://www.youtube.com/upload"     # opens the Studio upload dialog when signed in


def load_upload_state():
    try:
        return json.loads(UPLOAD_STATE.read_text(encoding="utf-8")) if UPLOAD_STATE.exists() else {}
    except ValueError:
        return {}


def save_upload_state(state):
    if state:
        UPLOAD_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    else:
        UPLOAD_STATE.unlink(missing_ok=True)


def clear_upload_block():
    """You fixed whatever stopped Upload-Post (or want to try again): allow automatic uploads again."""
    save_upload_state({})


def classify_upload_error(error):
    """"quota" (limit reached), "refused" (another HTTP 4xx: key or plan problem) or "transient"."""
    text = (error or "").lower()
    if re.search(r"\b(402|429)\b", text) or any(w in text for w in ("quota", "limit", "exceed", "upgrade")):
        return "quota"
    if re.search(r"\b4\d\d client error", text):
        return "refused"
    return "transient"


def note_upload_result(status, error=None, now=None):
    """Remember why automatic uploads should pause, so a failing upload isn't retried at every slot
    (each retry could use up another of the few free API calls)."""
    now = now or datetime.now()
    if status == "posted":
        save_upload_state({})
        return
    if status != "failed":
        return
    kind = classify_upload_error(error)

    def stamp(t):
        return t.isoformat(timespec="seconds")
    if kind == "quota":
        state = {"blocked_until": stamp(month_bounds(now)[1] + timedelta(seconds=1)), "failures": 0,
                 "reason": "Upload-Post says the upload limit is reached"}
    elif kind == "refused":
        state = {"blocked_until": stamp(now + timedelta(hours=24)), "failures": 0,
                 "reason": f"Upload-Post refused the upload ({(error or '')[:50]})"}
    else:
        failures = int(load_upload_state().get("failures", 0)) + 1
        state = {"failures": failures}
        if failures >= 2:
            state.update(blocked_until=stamp(now + timedelta(hours=6)), reason="two uploads in a row failed")
    save_upload_state(state)


def effective_upload_mode(now, settings, ledger):
    """("auto" | "manual", reason). Manual when you chose it, when this cycle's free uploads are used,
    or while an Upload-Post refusal or repeated failure has paused automatic uploads."""
    if settings.get("upload_mode") == "manual":
        return "manual", "you chose manual uploads"
    limit = int(settings["monthly_uploads"])
    reset = month_bounds(now)[1] + timedelta(seconds=1)
    if used_this_month(ledger, now) >= limit:
        return "manual", f"this cycle's {limit} free uploads are used (they reset {reset:%d %b})"
    state = load_upload_state()
    until = state.get("blocked_until")
    if until and datetime.fromisoformat(until) > now:
        return "manual", f"{state.get('reason', 'paused')}; automatic uploads retry after {until[:16].replace('T', ' ')}"
    return "auto", ""


def upload_description(meta):
    """The description sent to YouTube: your text, then the credits footage sources require."""
    return "\n\n".join(x for x in [meta.get("description", "").strip(), *meta.get("credits", [])] if x)


def manual_pack(stem):
    """Everything needed to upload an approved video by hand."""
    meta = load_meta(APPROVED, stem)
    return {"stem": stem, "file": str(pair(APPROVED, stem)[0]), "title": meta.get("title") or stem,
            "description": upload_description(meta), "topic": meta.get("topic", ""),
            "tags": ", ".join(t.strip().lstrip("#") for t in meta.get("tags", []) if t.strip())}


def mark_manual_uploaded(stem):
    """You uploaded it yourself: file it as posted. Manual uploads never count against Upload-Post's quota."""
    meta = load_meta(APPROVED, stem)
    move_pair(stem, APPROVED, POSTED)
    drop_work(stem)
    ledger = load_ledger()
    ledger.append({"time": datetime.now().isoformat(timespec="seconds"), "title": meta.get("title") or stem,
                   "file": f"{stem}.mp4", "status": "posted", "manual": True, "request_id": None})
    save_ledger(ledger)


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
    process dies. Stops a manual run and a scheduled run from both uploading.
    wait: seconds to keep retrying before giving up (one-time uploads must not be skipped)."""

    def __init__(self, wait=0):
        self.wait = wait

    def __enter__(self):
        import msvcrt
        import os
        import time
        LOG_DIR.mkdir(exist_ok=True)
        self.fd = os.open(LOCK, os.O_RDWR | os.O_CREAT)
        deadline = time.monotonic() + self.wait
        while True:
            try:
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(self.fd)
                    raise AlreadyRunning("another run is in progress")
                time.sleep(5)

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
        f"Draw from this viral psychological checklist mapping demographics to their deepest emotional hooks: {AUDIENCE_HOOKS} "
        "Focus on strong emotional tension, curiosity gaps, and the psychological mechanisms behind what people crave, buy, and fear. "
        "Each topic is one specific, curiosity-driven idea in under 12 words (e.g. 'Why luxury ads sell men status instead of cars', 'The multi-billion dollar emotion sold to guilty parents'). "
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


def voiceover(M, s, topic, script):
    """MPT's voiceover step, plus the TTS word timing it produced (for captions that follow the voice).
    Returns (sentence subtitle path, audio path, word-timing SRT text or "")."""
    seen, real_tts = {}, M.voice.tts

    def capture(*args, **kwargs):
        seen["maker"] = real_tts(*args, **kwargs)
        return seen["maker"]

    M.voice.tts = capture
    try:
        tid = str(uuid4())
        result = M.tm.start(tid, make_params(M, s, topic, script, False), stop_at="subtitle")
    finally:
        M.voice.tts = real_tts
    srt = result.get("subtitle_path")
    audio = Path(M.utils.task_dir(tid)) / "audio.mp3"
    if not srt or not audio.exists():
        raise RuntimeError(f"voiceover failed: {result.get('error')}")
    words = ""
    if seen.get("maker") is not None:
        try:
            out = audio.with_name("words.srt")
            M.voice.create_subtitle(sub_maker=seen["maker"], text=script, subtitle_file=str(out), word_level=True)
            words = out.read_text(encoding="utf-8") if out.exists() else ""
        except Exception as err:
            print(f"Word timing unavailable ({err}); captions will use estimated timing")
    return srt, audio, words


def voice_audio(work):
    """The narration file of a video: audio.wav for the studio narration, audio.mp3 for older videos."""
    work = Path(work)
    return work / "audio.wav" if (work / "audio.wav").exists() else work / "audio.mp3"


def narration(M, s, topic, script, work):
    """Voiceover for a new video: the studio narration (voices.py: sentence-by-sentence, mastered, checked against the
    script), or MoneyPrinterTurbo's own when that can't run. Always leaves subtitle.srt, words.srt and the audio file
    in `work`. Returns (sentence srt path, audio path, quality report or None)."""
    work = Path(work)
    if s["voice_engine"] != "mpt":
        try:
            import voices
            _, _, audio, qa = voices.make_voiceover(s, script, work)
            if qa["worst_match"] < 0.6:
                print(f"WARNING: the narration may not match the script (worst sentence {qa['worst_match']:.0%})")
            return work / "subtitle.srt", audio, qa
        except Exception as err:
            print(f"Studio narration failed ({str(err)[:300]}); using MoneyPrinterTurbo's voiceover instead")
    srt, audio, words = voiceover(M, s, topic, script)
    shutil.copyfile(audio, work / "audio.mp3")
    shutil.copyfile(srt, work / "subtitle.srt")
    if words:
        (work / "words.srt").write_text(words, encoding="utf-8")
    return work / "subtitle.srt", work / "audio.mp3", None


def camera_for(beats, s, seed):
    """footage.compose's `camera` argument: a different gentle move for every cut, or None when motion is
    off or this ffmpeg can't do it (checked on three synthetic frames)."""
    level = s["motion_level"]
    if level == "off":
        return None
    import motion                                          # lazy: uploads never need it
    cuts = sum(len(footage.cut_lengths(e - b)) for b, e, _ in beats)
    moves = motion.plan_moves(cuts, seed, level)
    probe_filter = next((f for f in (motion.camera_filter(m, level, 1.0) for m in moves) if f), None)
    if probe_filter:
        r = footage.run([footage.ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", f"color=c=gray:s={footage.W}x{footage.H}:d=0.3:r=30",
                         "-vf", probe_filter, "-frames:v", "3", "-f", "null", "-"], timeout=60)
        if r.returncode:
            print(f"Camera moves unavailable in this ffmpeg ({r.stderr[-120:].strip()}); cuts stay still")
            return None
    return lambda i, seconds: motion.camera_filter(moves[i], level, seconds) if i < len(moves) else None


def motion_final(M, s, script, work, out, track):
    """Animated captions, one look and a ducked music mix in a single ffmpeg pass (see motion.py)."""
    import motion
    work = Path(work)
    cache = work / "motion.json"
    keywords = json.loads(cache.read_text(encoding="utf-8")).get("keywords") if cache.exists() else None
    if keywords is None:
        try:
            keywords = motion.parse_keywords(ask(M.llm, motion.keyword_prompt(script)))
        except Exception as err:
            print(f"Keyword choice skipped ({err}); only numbers will be highlighted")
            keywords = []
    timing = work / "words.srt" if (work / "words.srt").exists() else work / "subtitle.srt"
    total = footage.probe(voice_audio(work))[0]
    font = Path(M.utils.font_dir()) / motion.FONT_FILE
    ass, info = motion.make_plan(timing.read_text(encoding="utf-8"), total, keywords, s["accent_color"], font_file=font)
    info["design"] = motion.check_ass(ass)
    for problem in info["design"]:
        print("Design check:", problem)
    music = footage.fit_audio(SAFE_MUSIC / track, total + 0.1, work / "music_fit.mp3") if track else None
    sfx = None
    if s["sfx_level"] != "off" and (work / "cuts.json").exists():     # older videos have no cut list: no effects
        import zlib
        import sound
        sfx, events = sound.sfx_track(work / "sfx.wav", total, json.loads((work / "cuts.json").read_text(encoding="utf-8")),
                                      info["callouts"], s["sfx_level"], zlib.crc32(work.name.encode()))
        info["sfx_events"] = len(events)
    made = motion.render_final(work, ass, font, "motion.mp4", s["look"], music, s["music_volume"], sfx=sfx)
    shutil.move(str(made), str(out))
    cache.write_text(json.dumps({"keywords": keywords, **info, "estimated_timing": timing.name != "words.srt"},
                                indent=2), encoding="utf-8")
    return bool(track)


def repair_footage(ask_llm, topic, beats, queries, ranked, weak, searchers, vision, work, lessons_text):
    """One more try for the beats where no clip fit: fresh search words, new candidates, another look.
    Returns (ranked, indices of the beats that are still weak)."""
    sub = [beats[i] for i in weak]
    tried = "\n".join(f'{n + 1}. "{sub[n][2]}" (already tried: {", ".join(queries[i])})' for n, i in enumerate(weak))
    reply = ask_llm(
        f"Stock footage for a fast vertical YouTube Short about: {topic}. For these voiceover beats no clip fit, so the "
        "search words were wrong. Give THREE new, different search queries per beat: 1-3 concrete, common English words "
        "naming what a camera would literally film (an object, a place, an action, a reaction), the kind of words stock "
        "video sites use. No abstract ideas, brand names or quotes from the narration.\n"
        f"{tried}\n\nReply with only a JSON array like [{{\"i\": 1, \"queries\": [\"a\", \"b\", \"c\"]}}].")
    fresh = footage.parse_queries(reply, len(sub))
    for n, q in enumerate(fresh):
        if not q:
            fresh[n] = [" ".join(sorted(footage.words(sub[n][2]), key=len, reverse=True)[:2]) or "city lights"]
    new = footage.gather(sub, fresh, searchers)
    still = []
    got = footage.choose_with_vision(topic, sub, new, vision, Path(work) / "repair", lessons_text, weak_out=still)
    left = []
    for n, i in enumerate(weak):
        if n in still or len(new[n]) < 2:                       # nothing to judge, or nothing fit again
            left.append(i)
        else:
            ranked[i] = got[n] + [c for c in ranked[i] if c not in got[n]]
    print(f"Footage repair: {len(weak) - len(left)} of {len(weak)} weak beat(s) fixed")
    return ranked, left


def quality_checks(video, work, narration=None, weak=()):
    """Automatic checks on a finished video (qa.py). Returns the report, or None if they couldn't run: a failed
    check only flags the video for you, it never blocks it. `weak` lists the beats with no strongly matching clip."""
    try:
        import qa
        cache = Path(work) / "motion.json"
        design = json.loads(cache.read_text(encoding="utf-8")).get("design", []) if cache.exists() else []
        report = qa.check_video(video, narration, design, weak=weak)
        print("Quality checks:", qa.summary(report))
        for c in report["checks"]:
            if not c["ok"]:
                print(f"  - {c['name']}: {c['detail']}")
        return report
    except Exception as err:
        print(f"Quality checks skipped ({type(err).__name__}: {str(err)[:150]})")
        return None


def fix_loudness(folders=None):
    """Match the audio of videos made before the studio mix (about -19 LUFS) to YouTube's -14 LUFS, in review and
    approved. The picture is copied untouched and the original is kept in backup/. A new file replaces the old one
    only if it measures right, is as long as before and has a bit-identical picture; otherwise the video is left as
    it was. Returns [(file name, LUFS before, LUFS after)]."""
    import qa
    import sound
    lo, hi = qa.LIMITS["lufs"]
    done = []
    for folder in folders or (REVIEW, APPROVED):
        for stem in stems(folder):
            video, meta_file = pair(folder, stem)
            before = qa.check_video(video)["measured"]
            if before.get("lufs") is None or lo <= before["lufs"] <= hi:
                continue
            keep = BACKUP / folder.name
            keep.mkdir(parents=True, exist_ok=True)
            fixed = keep / f"{stem}.fixed.mp4"
            try:
                sound.normalize_video_audio(video, fixed)
                after = qa.check_video(fixed)["measured"]
                if not (lo <= after.get("lufs", -99) <= hi and abs(after["duration"] - before["duration"]) < 0.4
                        and sound.picture_hash(fixed) == sound.picture_hash(video)):
                    raise RuntimeError("the new file didn't measure right")
                if not (keep / video.name).exists():
                    shutil.copyfile(video, keep / video.name)          # the original stays recoverable
                fixed.replace(video)
            except Exception as err:
                fixed.unlink(missing_ok=True)
                print(f"Left as it was: {video.name} ({type(err).__name__}: {str(err)[:150]})")
                continue
            meta = load_meta(folder, stem)
            meta["qa"] = quality_checks(video, WORK / stem, meta.get("narration"))
            meta["audio_fixed"] = f"loudness matched to -14 LUFS (was {before['lufs']}); original kept in backup/{folder.name}/"
            meta_file.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
            done.append((video.name, before["lufs"], after["lufs"]))
            print(f"Fixed {video.name}: {before['lufs']} -> {after['lufs']} LUFS")
    return done


def finish_video(M, s, topic, script, work, out, track, fresh=False):
    """The final mix. Videos made with motion graphics (and new ones, when motion is on) go through
    motion_final; older videos keep MoneyPrinterTurbo's captions, and so does anything that goes wrong.
    Returns True if music was mixed in."""
    work = Path(work)
    if s["motion_level"] != "off" and (fresh or (work / "motion.json").exists()):
        try:
            return motion_final(M, s, script, work, out, track)
        except Exception as err:
            print(f"Motion graphics failed ({type(err).__name__}: {str(err)[:300]}); using the plain mixer instead")
    mixed = mix_final(M, s, topic, script, work / "combined.mp4", voice_audio(work), work / "subtitle.srt", out, track)
    try:                                       # even the plain mixer's output gets YouTube's loudness
        import sound
        loud = Path(out).with_name("loud.mp4")
        sound.normalize_video_audio(out, loud)
        loud.replace(out)
    except Exception as err:
        print(f"Loudness match skipped ({type(err).__name__}: {str(err)[:120]})")
    return mixed


class Clock:
    """Prints and records how long each stage of a render takes, so a slow step is easy to find."""

    def __init__(self):
        self.last, self.rows = time.time(), {}

    def mark(self, name):
        now = time.time()
        self.rows[name] = round(now - self.last, 1)
        self.last = now
        print(f"[{name}] {self.rows[name]:.0f}s")


def render_one(M, s):
    clock = Clock()
    ask_llm = lambda prompt: ask(M.llm, prompt)           # noqa: E731
    lessons = build_lessons(ask_llm)
    applied = sum(len(v) for v in lessons.values())
    if applied:
        print(f"Lessons applied from your rejections: {applied} rule(s)")
    topic = pick_topic(M.llm, s, lessons)
    # MPT caps the script prompt at 2000 characters
    script_prompt = (f"{s['script_rules']}\n"
                     f"Demographic emotional hooks map: {AUDIENCE_HOOKS}\n"
                     f"{lessons_block(lessons, 'script')}").strip()[:1900]
    script = M.llm.generate_script(video_subject=topic, language=s["language"], video_script_prompt=script_prompt)
    if not script or script.startswith("Error"):
        raise RuntimeError(f"script failed: {script}")
    print("Topic:", topic)
    clock.mark("topic and script")

    stem = f"{datetime.now():%Y%m%d-%H%M}-{slugify(topic)}"
    work = WORK / stem
    work.mkdir(parents=True, exist_ok=True)
    try:
        # 1. Narration and its exact timing (per sentence for the footage, per word for the captions)
        srt, audio, voice_qa = narration(M, s, topic, script, work)
        total = footage.probe(audio)[0]
        beats = footage.make_beats(footage.parse_srt(Path(srt).read_text(encoding="utf-8")), total)
        print(f"Voiceover {total:.1f}s -> {len(beats)} beats")
        clock.mark("narration")

        # 2. Find, look at and place the footage
        flessons = lessons_block(lessons, "footage")
        queries = plan_queries(ask_llm, topic, beats, flessons)
        searchers = build_searchers(M)
        if not searchers:
            raise RuntimeError("no footage source is set up (add a Pixabay key in Setup)")
        cands = footage.gather(beats, queries, searchers)
        vision, weak = ask_vision_factory(M), []
        ranked = footage.choose_with_vision(topic, beats, cands, vision, work, flessons, weak_out=weak)
        if weak:
            try:
                ranked, weak = repair_footage(ask_llm, topic, beats, queries, ranked, weak, searchers, vision, work, flessons)
            except Exception as err:                         # the repair is a bonus: never lose the video over it
                print(f"Footage repair skipped ({type(err).__name__}: {str(err)[:150]})")
        clock.mark("footage search and picks")
        cache = Path(M.config.root_dir) / "storage" / "cache_videos"
        combined, used = footage.compose(beats, ranked, work, cache, camera=camera_for(beats, s, stem))
        clock.mark("cutting the clips")

        # 3. Music: the best-fitting approved track (or the one you fixed, or none)
        track = choose_track(s, usable_tracks(), ask_llm, topic, script, recent_tracks())
        print("Music:", track or "none (voice only)")

        # 4. Final mix
        (work / "cuts.json").write_text(json.dumps(footage.cut_starts(beats)), encoding="utf-8")
        final = work / "final.mp4"
        finish_video(M, s, topic, script, work, final, track, fresh=True)
        clock.mark("final pass")
        qa_report = quality_checks(final, work, voice_qa, [i + 1 for i in weak])
        clock.mark("quality checks")
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
        "motion": s["motion_level"] if (work / "motion.json").exists() else "off",
        "look": s["look"],
        "narration": {"engine": voice_qa["engine"], "voice": voice_qa["voice"], "match": voice_qa["mean_match"],
                      "worst": voice_qa["worst_match"], "retried": voice_qa["retried"]} if voice_qa else {"engine": "mpt"},
        "weak_beats": [i + 1 for i in weak],
        "qa": qa_report,
        "timings": clock.rows,
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
    if not all((work / n).exists() for n in ("combined.mp4", "subtitle.srt")) or not voice_audio(work).exists():
        raise RuntimeError("the working files for this video are gone (older videos can't change music)")
    if track and track not in [n for n, _, _ in usable_tracks()]:
        raise RuntimeError("that track isn't in the approved list")
    meta = load_meta(folder, stem)
    s = load_settings()
    out = work / "remix.mp4"
    finish_video(M, s, meta.get("topic", ""), meta.get("script", ""), work, out, track)
    shutil.move(str(out), str(pair(folder, stem)[0]))
    meta["qa"] = quality_checks(pair(folder, stem)[0], work, meta.get("narration"))
    meta["music"] = track or "none"
    pair(folder, stem)[1].write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (THUMBS / f"{stem}.png").unlink(missing_ok=True)
    print(f"REMIXED {stem} with {track or 'no music'}")


# ---- Uploading -------------------------------------------------------------------

def upload_marked(upload_post, stem, label, **kwargs):
    """upload_post.cross_post_video with a marker file around it. If the run is killed in the middle (a window
    closed, the PC lost power) the marker stays behind and recover_interrupted_upload() deals with it next time."""
    INFLIGHT.write_text(json.dumps({"stem": stem, "title": label, "pid": os.getpid(),
                                    "started": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    try:
        return upload_post.cross_post_video(**kwargs)
    finally:
        INFLIGHT.unlink(missing_ok=True)


def recover_interrupted_upload():
    """An upload that was started but never finished may or may not have reached YouTube. It is never retried
    blindly (that could post it twice): the video goes to check/ for a look in YouTube Studio, like any upload with
    an unclear result. Returns the video's name, or None if nothing was interrupted."""
    if not INFLIGHT.exists():
        return None
    try:
        info = json.loads(INFLIGHT.read_text(encoding="utf-8"))
    except ValueError:
        info = {}
    INFLIGHT.unlink(missing_ok=True)
    stem = str(info.get("stem") or "")
    video = pair(APPROVED, stem)[0]
    if not stem or not video.exists():
        return None
    move_pair(stem, APPROVED, CHECK)
    ledger = load_ledger()
    ledger.append({"time": datetime.now().isoformat(timespec="seconds"), "title": info.get("title") or stem,
                   "file": video.name, "status": "unconfirmed", "request_id": None,
                   "note": f"the run stopped during the upload that began {info.get('started', '?')}"})
    save_ledger(ledger)
    print(f"UPLOAD INTERRUPTED: '{info.get('title') or stem}' was being uploaded when the run stopped. It may already be "
          "on YouTube: look in Studio, then mark it under History > Needs checking.")
    return stem


def upload_next(upload_post, svc):
    """Upload the oldest approved video. Returns (status, title, error);
    status is "posted", "unconfirmed", "failed" or "none" (nothing approved)."""
    mode, why = effective_upload_mode(datetime.now(), load_settings(), load_ledger())
    if mode == "manual":
        print(f"MANUAL MODE: not uploading automatically ({why}). Use the Upload page in the app.")
        return "manual", None, why
    queue = stems(APPROVED)
    if not queue:
        print("UPLOAD DUE but nothing is approved. Approve a video in the Review page to keep the schedule.")
        return "none", None, None
    stem = queue[0]
    video, meta_file = pair(APPROVED, stem)
    meta = load_meta(APPROVED, stem)
    title = meta.get("title") or stem
    # Footage sources that require a visible credit (Vidsplay, Coverr) are named in the description
    description = upload_description(meta)
    result = upload_marked(
        upload_post, stem, title,
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
    note_upload_result(status, error)
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
    from app.services import llm, upload_post, video, voice
    from app.services import task as tm
    from app.utils import utils
    # Approval gate: MPT must never upload straight after rendering.
    config.app["upload_post_auto_upload"] = False
    return SimpleNamespace(config=config, VideoParams=VideoParams, llm=llm, tm=tm, video=video, voice=voice,
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
    if mode != "dry":
        recover_interrupted_upload()

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
    QUOTA.update(reset_day=1, meter_used=0, meter_date=None)

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
    # vision stage: beats where nothing fits are reported, and the repair pass finds them better clips
    import tempfile as _tv
    two = [[{"id": "a0", "source": "x"}, {"id": "a1", "source": "x"}], [{"id": "b0", "source": "x"}, {"id": "b1", "source": "x"}]]
    weak = []
    with _tv.TemporaryDirectory() as tv:
        shot = [(0, 3, "x"), (3, 6, "y")]
        ranked = footage.choose_with_vision("t", shot, two, lambda p, f: '{"1": [2], "2": []}', tv, log=lambda m: None, weak_out=weak)
        assert weak == [1] and ranked[0][0]["id"] == "a1" and [c["id"] for c in ranked[1]] == ["b0", "b1"], (weak, ranked)
        found = [("fake", lambda q, d: [{"id": f"n:{q}:{k}", "dur": 9, "source": "x"} for k in range(2)])]
        ranked, left = repair_footage(lambda p: '[{"i": 1, "queries": ["red car", "road"]}]', "t", shot, [["q1"], ["q2"]],
                                      ranked, [1], found, lambda p, f: '{"1": [2]}', tv, "")
        assert left == [] and ranked[1][0]["id"].startswith("n:") and len(ranked[1]) > 2, (left, ranked[1])
        ranked, left = repair_footage(lambda p: "no json", "t", shot, [["q1"], ["q2"]], ranked, [1], found,
                                      lambda p, f: '{"1": []}', tv, "")
        assert left == [1]                                            # still nothing fits: it stays flagged
    clock = Clock()
    clock.mark("a")
    assert list(clock.rows) == ["a"] and clock.rows["a"] >= 0

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
    import os
    import motion
    font = Path(os.environ.get("MPT_DIR", "")) / "resource" / "fonts" / motion.FONT_FILE
    motion.self_test(font if font.is_file() else None)
    import narrate
    import qa
    import sound
    import voices
    qa.self_test()
    sound.self_test()
    assert [k for _, k in narrate.split_sentences("Your phone isn't dying. It's math! Does heat matter? Yes.\n\nSmall habits, big years.")] \
        == [".", "!", "?", "p", "."]
    assert narrate.clean_spoken("Hello \U0001F48D world [scene: x] (aside) wow — yes") == "Hello world wow, yes"
    assert narrate.pause_after(".", 0, False) == narrate.HOOK_PAUSE and narrate.pause_after("?", 3, False) == 0.40 \
        and narrate.pause_after(".", 5, True) == 0.0 and narrate.pause_after("!", 2, False, 0.5) == 0.13
    heard = [("Your", 0, .2), ("phone", .2, .5), ("costs", .5, .9), ("eight", .9, 1.1), ("hundred", 1.1, 1.4),
             ("dollars", 1.4, 1.7), ("today", 1.7, 2.0)]
    times = narrate.map_words(["Your", "phone", "costs", "$800", "today"], heard)
    assert times[0] == (0, .2) and times[4] == (1.7, 2.0) and times[3] == (0.9, 1.7), times      # the number is placed between its neighbours
    assert narrate.spoken_match("It keeps 80% of its capacity", "it keeps eighty percent of its capacity") == 1.0
    assert narrate.spoken_match("The cat sat on the mat", "a dog ran far away") < 0.3
    assert voices.to_srt([(0, 1.5, "Hi there")]) == "1\n00:00:00,000 --> 00:00:01,500\nHi there\n\n"
    assert voices.edge_name("en-US-GuyNeural-Male") == "en-US-GuyNeural" and voices.available("mpt") == (True, "")
    if voices.available("kokoro")[0]:                 # the whole studio narration, offline: Kokoro + Whisper + mastering
        with _tf.TemporaryDirectory() as t3:
            try:                                      # an Edge voice name on the Kokoro engine is refused up front
                voices.make_voiceover({**DEFAULTS, "voice_engine": "kokoro", "voice": "en-US-GuyNeural-Male"}, "Hi.", Path(t3))
                raise AssertionError("a non-Kokoro voice was accepted")
            except RuntimeError:
                pass
            _, _, wav, qa = voices.make_voiceover({**DEFAULTS, "voice_engine": "kokoro", "voice": "af_heart"},
                                                  "Phones age fast. Heat is the reason.", Path(t3))
            assert qa["sentences"] == 2 and qa["worst_match"] >= 0.8 and footage.probe(wav)[0] > 2.0, qa
            assert len(footage.parse_srt((Path(t3) / "subtitle.srt").read_text(encoding="utf-8"))) == 2
            assert len(footage.parse_srt((Path(t3) / "words.srt").read_text(encoding="utf-8"))) == 7
    else:
        print("(studio narration check skipped:", voices.available("kokoro")[1] + ")")
    with _tf.TemporaryDirectory() as t4:              # fixing a quiet old video: backed up, verified, picture untouched
        set_base(t4)
        try:
            APPROVED.mkdir(parents=True)
            made = [("quiet", 0.03), ("fine_src", 0.02)]
            for name, amp in made:
                r = footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i",
                                 "testsrc2=size=1080x1920:rate=30:d=8", "-f", "lavfi", "-i",
                                 f"anoisesrc=d=8:c=pink:a={amp}:r=44100", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                                 "-shortest", str(Path(t4) / f"{name}.mp4")])
                assert r.returncode == 0, r.stderr
            shutil.copyfile(Path(t4) / "quiet.mp4", APPROVED / "quiet.mp4")
            sound.normalize_video_audio(Path(t4) / "fine_src.mp4", APPROVED / "fine.mp4")      # already at the right level
            for name in ("quiet", "fine"):
                (APPROVED / f"{name}.json").write_text('{"title": "t"}', encoding="utf-8")
            original = sound.picture_hash(APPROVED / "quiet.mp4")
            done = fix_loudness((APPROVED,))
            assert [d[0] for d in done] == ["quiet.mp4"] and -16 <= done[0][2] <= -12.5, done
            assert (BACKUP / "approved" / "quiet.mp4").exists() and sound.picture_hash(APPROVED / "quiet.mp4") == original
            assert "audio_fixed" in load_meta(APPROVED, "quiet") and fix_loudness((APPROVED,)) == []
        finally:
            set_base(HERE)
    with _tf.TemporaryDirectory() as t5:              # an upload killed midway is parked for checking, never retried blindly
        from types import SimpleNamespace as NS
        quota_before = dict(QUOTA)                    # load_settings() (inside upload_next) changes it; later tests assume it
        set_base(t5)
        try:
            APPROVED.mkdir(parents=True)
            for name in ("a", "b"):
                (APPROVED / f"{name}.mp4").write_bytes(b"x")
                (APPROVED / f"{name}.json").write_text(json.dumps({"title": name.upper()}), encoding="utf-8")
            assert recover_interrupted_upload() is None                       # nothing was under way
            seen = {}

            def fake_post(**kw):
                seen["marker"] = json.loads(INFLIGHT.read_text(encoding="utf-8"))["stem"]     # marked while the request runs
                return {"success": True, "request_id": "r1"}
            status, _, _ = upload_next(NS(cross_post_video=fake_post), NS(youtube_privacy_status="public"))
            assert status == "posted" and seen["marker"] == "a" and not INFLIGHT.exists() and stems(POSTED) == ["a"]
            INFLIGHT.write_text(json.dumps({"stem": "b", "title": "B", "started": "2026-11-03T10:11:16", "pid": 1}), encoding="utf-8")
            assert recover_interrupted_upload() == "b" and stems(CHECK) == ["b"] and not INFLIGHT.exists()
            last = load_ledger()[-1]
            assert last["status"] == "unconfirmed" and last["file"] == "b.mp4", last
            resolve_check("b", False)                                           # "it never arrived": back in the queue
            assert stems(APPROVED) == ["b"] and all(e["file"] != "b.mp4" for e in load_ledger())
            INFLIGHT.write_text("{broken", encoding="utf-8")
            assert recover_interrupted_upload() is None and not INFLIGHT.exists()      # a damaged marker is harmless
            with KeepAwake():                                                   # never raises, even where it can't act
                pass
        finally:
            QUOTA.update(quota_before)
            set_base(HERE)
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
            for key, bad in (("motion_level", "wild"), ("look", "neon"), ("accent_color", "red"), ("accent_color", "#12345"),
                             ("voice_engine", "robot"), ("sfx_level", "loud")):
                try:
                    save_settings({**DEFAULTS, key: bad})
                    raise AssertionError(f"{key}={bad} saved")
                except ValueError:
                    pass
            assert save_settings({**DEFAULTS, "motion_level": "dynamic", "look": "warm", "accent_color": "#00ff88"})["look"] == "warm"
            SETTINGS.unlink()                      # leave the defaults for the checks below

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
            with RunLock():                              # a second lock waits, then gives up
                try:
                    with RunLock(wait=1):
                        raise AssertionError("second lock acquired while the first is held")
                except AlreadyRunning:
                    pass
            with RunLock(wait=1):
                pass

            # cleanup only removes old entries
            cache = Path(tmp) / "storage" / "cache_videos"
            cache.mkdir(parents=True)
            (cache / "old.mp4").write_bytes(b"12345")
            assert clean_mpt_cache(tmp, 14, now=datetime.now() + timedelta(days=15)) == 5
            assert clean_mpt_cache(tmp, 0) == 0

            # Upload-Post cycle: resets on the 25th; the meter reading counts only if taken this cycle
            QUOTA.update(reset_day=25, meter_used=0, meter_date=None)
            assert month_bounds(datetime(2026, 11, 1, 10)) == (datetime(2026, 10, 25),
                                                               datetime(2026, 11, 24, 23, 59, 59))
            assert month_bounds(datetime(2026, 11, 25))[0] == datetime(2026, 11, 25)
            assert month_bounds(datetime(2026, 12, 30))[0] == datetime(2026, 12, 25)
            led = [{"time": "2026-10-26T11:15:33"}, {"time": "2026-10-20T09:00:00"}]
            assert used_this_month(led, datetime(2026, 11, 1, 10)) == 1
            QUOTA.update(meter_used=6, meter_date="2026-11-01")
            assert used_this_month(led, datetime(2026, 11, 1, 10)) == 6
            QUOTA.update(meter_date="2026-10-01")                  # taken in the previous cycle: ignored
            assert used_this_month(led, datetime(2026, 11, 1, 10)) == 1
            assert len(plan_uploads(datetime(2026, 11, 1, 10), [], 10, times, datetime(2026, 11, 24, 23))) == 10
            QUOTA.update(reset_day=1, meter_used=0, meter_date=None)

            # Upload mode: auto until the free uploads are used, Upload-Post refuses, or you choose manual
            now2, s2 = datetime(2026, 11, 10, 12), dict(DEFAULTS)
            few = [{"time": "2026-11-02T09:00:00"}]
            full = [{"time": f"2026-11-0{i}T09:00:00"} for i in range(1, 10)] + [{"time": "2026-11-09T19:00:00"}]
            assert effective_upload_mode(now2, s2, few)[0] == "auto"
            assert effective_upload_mode(now2, {**s2, "upload_mode": "manual"}, few)[0] == "manual"
            assert effective_upload_mode(now2, s2, full)[0] == "manual"
            assert used_this_month(full[:4] + [{"time": "2026-11-09T09:00:00", "manual": True}] * 6, now2) == 4
            assert classify_upload_error("429 Client Error: Too Many Requests") == "quota"
            assert classify_upload_error("Monthly upload limit reached") == "quota"
            assert classify_upload_error("403 Client Error: Forbidden for url: x") == "refused"
            assert classify_upload_error("Read timed out") == "transient"
            note_upload_result("failed", "Read timed out", now2)                      # one failure: keep going
            assert effective_upload_mode(now2, s2, few)[0] == "auto"
            note_upload_result("failed", "Read timed out", now2)                      # two in a row: pause
            assert effective_upload_mode(now2, s2, few)[0] == "manual"
            note_upload_result("posted", None, now2)
            assert load_upload_state() == {}
            note_upload_result("failed", "429 Client Error: Too Many Requests", now2)
            assert load_upload_state()["blocked_until"].startswith("2026-12-01")
            assert effective_upload_mode(now2, s2, few)[0] == "manual"
            assert effective_upload_mode(datetime(2026, 12, 1, 0, 1), s2, few)[0] == "auto"   # the block ends at the reset
            clear_upload_block()
            assert load_upload_state() == {}
            # a manual upload: credits are in the description, the file is filed as posted, the quota is untouched
            APPROVED.mkdir(exist_ok=True)
            (APPROVED / "m1.mp4").write_bytes(b"x")
            (APPROVED / "m1.json").write_text(json.dumps({"title": "T", "description": "d", "tags": ["#a", "b"],
                                                          "credits": ["Footage: Vidsplay.com"]}), encoding="utf-8")
            pack = manual_pack("m1")
            assert pack["description"] == "d\n\nFootage: Vidsplay.com" and pack["tags"] == "a, b"
            mark_manual_uploaded("m1")
            assert not (APPROVED / "m1.mp4").exists() and (POSTED / "m1.mp4").exists()
            assert load_ledger()[-1]["manual"] is True and used_this_month(load_ledger(), datetime.now()) == 0
        finally:
            QUOTA.update(reset_day=1, meter_used=0, meter_date=None)
            set_base(HERE)
    import lf_tests
    lf_tests.run()
    print("self-test passed")


def upload_next_now():
    """One upload, outside the normal spacing (used by the one-time upload tasks).
    Still respects the monthly quota and the approval gate: only approved videos are posted."""
    s = load_settings()
    M = load_mpt()
    svc = M.upload_post.upload_post_service
    recover_interrupted_upload()                  # an earlier run killed mid-upload: park it before counting
    now = datetime.now()
    used = used_this_month(load_ledger(), now)
    limit = int(s["monthly_uploads"])
    record = {"time": now.isoformat(timespec="seconds"), "mode": "upload-next", "upload_due": True,
              "reason": f"{used}/{limit} used this cycle", "upload": None, "title": None,
              "rendered": None, "errors": []}
    if used >= limit:
        record["note"] = "free uploads used: manual mode"
    elif not (svc.is_configured() and "youtube" in svc.platforms):
        record["errors"].append("Upload-Post is not enabled for YouTube")
    else:
        status, title, error = upload_next(M.upload_post, svc)
        record.update(upload=status, title=title)
        if status == "none":
            record["errors"].append("nothing approved to upload")
        elif status in ("failed", "unconfirmed"):
            record["errors"].append(f"upload {status}: {error}")
    record["exit"] = 1 if record["errors"] else 0
    log_run(record)
    return record["exit"]


class KeepAwake:
    """Asks Windows not to go to sleep while a run is in progress: a render or an upload suspended by standby is lost
    (a laptop in Modern Standby was woken mid-upload on 2026-11-03)."""

    @staticmethod
    def _state(flags):
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
        except Exception:                          # not Windows, or no permission: carry on without
            pass

    def __enter__(self):
        self._state(0x80000001)                    # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        return self

    def __exit__(self, *exc):
        self._state(0x80000000)                    # ES_CONTINUOUS alone: back to normal
        return False


def main(args):
    with KeepAwake():
        return run_command(args)


def run_command(args):
    if "--self-test" in args:
        self_test()
        return 0
    if "--doctor" in args:
        return doctor()
    if "--longform" in args:                  # long films: their own lock, so a long render never holds up the uploads
        import longform
        return longform.main(args[args.index("--longform") + 1:])
    if "--dry-run" in args:
        return run("dry")
    if "--audition" in args:                  # a mastered sample of each good free voice, to choose by ear
        import voices
        folder = BASE / "samples" / "voices"
        made = voices.audition(folder, rate=float(load_settings()["voice_rate"]))
        for label, path in made:
            print(f"{label}: {path}")
        print(f"{len(made)} samples in {folder}")
        return 0 if made else 1
    if "--fix-loudness" in args:              # old videos: match the audio to -14 LUFS (originals are kept in backup/)
        try:
            with RunLock():
                done = fix_loudness()
        except AlreadyRunning:
            print("Another run is in progress; try again when it has finished.")
            return 1
        print(f"{len(done)} video(s) fixed")
        return 0
    if "--upload-next" in args:
        try:
            with RunLock(wait=3600):
                return upload_next_now()
        except AlreadyRunning:
            print("Gave up after an hour waiting for the other run. Nothing was uploaded.")
            return 1
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
