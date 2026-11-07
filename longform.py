"""Long films (8-10 minutes, a cast of 4-5, animated by HyperFrames). One folder per film under longform/films:

    film.json         where it is (stage, progress, message, checks...), written atomically so the app can poll it
    screenplay.json   concept, cast, scenes and beats        voice/   one wav per line     project/  the HyperFrames project
    plan.json         the scene descriptions               audio/   voice, effects, music, mix       out/  silent.mp4, final.mp4, thumb.jpg

Stages, each resumable: new -> screenplay -> voiced -> built -> rendered -> review -> approved | rejected -> posted.
    python longform.py all <film id>       run whatever is left        python longform.py new "<topic>" [minutes]
Only an approved film may be posted, like a Short. The film lock is separate from the Shorts run lock, so a long render
never makes the scheduled uploads wait."""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import footage
import lf_audio
import lf_build
import lf_finish
import lf_plan
import lf_screenplay as sc
import lf_voice
import sound

HERE = Path(__file__).resolve().parent
FILMS = HERE / "longform" / "films"
HF = HERE / "longform" / "node_modules" / "hyperframes" / "bin" / "hyperframes.mjs"
AUDIO_PY = HERE / ".venv-audio" / "Scripts" / "python.exe"
NO_WINDOW, BELOW_NORMAL = 0x08000000, 0x00004000
ORDER = ("new", "screenplay", "voiced", "built", "rendered", "review")
ENV = {"HYPERFRAMES_NO_TELEMETRY": "1", "HYPERFRAMES_SKIP_SKILLS": "1", "PYTHONIOENCODING": "utf-8"}
# Where a film made with gates waits for a person: reading the script costs minutes, a bad render costs half an hour.
GATES = ("screenplay", "built")
GATE_TEXT = {"screenplay": "script ready: read it, check the claims, then approve it", "built": "storyboard ready: look it over, then render the film"}
GATE_BUTTON = {"screenplay": "Approve the script and continue", "built": "Looks good, render the film"}


class Film:
    def __init__(self, folder):
        self.dir = Path(folder)
        self.meta = json.loads((self.dir / "film.json").read_text(encoding="utf-8"))

    id = property(lambda self: self.dir.name)
    screenplay = property(lambda self: self.dir / "screenplay.json")
    plan = property(lambda self: self.dir / "plan.json")

    def update(self, **kw):
        self.meta.update(kw)
        tmp = self.dir / "film.json.tmp"
        tmp.write_text(json.dumps(self.meta, indent=1, ensure_ascii=False), encoding="utf-8")
        for attempt in range(8):                         # the app may be reading the file at this very moment
            try:
                os.replace(tmp, self.dir / "film.json")
                return
            except PermissionError:
                time.sleep(0.25)
        os.replace(tmp, self.dir / "film.json")

    def say(self, message, frac=None):
        print(message, flush=True)
        self.update(message=message, **({"progress": round(frac, 3)} if frac is not None else {}))


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "film"


def new_film(topic, minutes=9, cast_size=5, gates=False, style="cartoon"):
    """gates=True: the run stops for the person after the script and after the storyboard (see GATES).
    style: how the characters are drawn, "cartoon" people or "stick" figures (lf_plan.STYLES)."""
    folder = FILMS / f"{datetime.now():%Y%m%d-%H%M}-{slug(topic)}"
    folder.mkdir(parents=True)
    film = Film.__new__(Film)
    film.dir, film.meta = folder, {}
    film.update(topic=topic, minutes=minutes, cast_size=cast_size, gates=gates, style=style, approved=[], stage="new", title=topic, message="",
                progress=0.0, error="", created=datetime.now().isoformat(timespec="seconds"))
    return film


def list_films():
    return [Film(p.parent) for p in sorted(FILMS.glob("*/film.json"), reverse=True)]


class FilmLock:
    """One long job at a time (an OS file lock: released if the process dies)."""

    def __enter__(self):
        import msvcrt
        FILMS.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(FILMS / ".lock", os.O_RDWR | os.O_CREAT)
        try:
            msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            os.close(self.fd)
            raise RuntimeError("another long film is being made right now")
        return self

    def __exit__(self, *exc):
        import msvcrt
        os.lseek(self.fd, 0, 0)
        msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        os.close(self.fd)


def busy():
    try:
        with FilmLock():
            return False
    except RuntimeError:
        return True


# ---- Stages --------------------------------------------------------------------------------

def rejection_lessons(limit=6):
    reasons = [f.meta["reject_reason"] for f in list_films() if f.meta.get("stage") == "rejected" and f.meta.get("reject_reason")]
    return ("Lessons from films the viewer rejected (apply them): " + " | ".join(reasons[:limit])) if reasons else ""


def write_screenplay(film, ask_llm):
    """The outline first (saved at once), then the beats batch by batch (saved after each one), so a stop or an
    unusable reply costs one batch, not the whole script. A failed reply is kept in the film folder."""
    sp = sc.load(film.screenplay) if film.screenplay.exists() else sc.new_outline(
        ask_llm, film.meta["topic"], film.meta["minutes"], film.meta["cast_size"], rejection_lessons(), film.say)
    sc.save(sp, film.screenplay)
    sc.write_beats(sp, ask_llm, progress=film.say, save=lambda part: sc.save(part, film.screenplay), debug_dir=film.dir)
    lf_plan.lines_of(sp)
    sc.save(sp, film.screenplay)
    film.update(stage="screenplay", title=sp["title"], words=sc.spoken_words(sp), progress=1.0, error="",
                message=f"screenplay written: {len(sp['scenes'])} scenes, {len(sp['cast'])} characters, {sc.spoken_words(sp)} words")


def film_voice_engine():
    """(engine, delivery note) for a film's voices: the premium engine chosen in Settings when its key is set, else Edge."""
    import daily_shorts as e
    import genmedia
    s = e.load_settings()
    engine = s.get("voice_engine", "edge")
    if engine == "gemini":
        # ponytail: Gemini's free tier is 10 voice requests a day and a film needs one per sentence, so films speak with
        # Edge and the day's requests stay with the Shorts. With billing on the key, a films-only engine setting goes here.
        return "edge", ""
    if engine in lf_voice.PREMIUM_MAP and genmedia.has(engine):
        return engine, s.get("voice_style", "")
    return "edge", ""


def voice_film(film, rate=1.0, engine=None):
    """engine: force one ("edge" for a story Short); None means the film's choice (film_voice_engine)."""
    if not AUDIO_PY.exists():
        raise RuntimeError("the audio environment isn't installed (run install.bat)")
    sp = sc.load(film.screenplay)
    lines = lf_plan.lines_of(sp)
    sc.save(sp, film.screenplay)
    out = film.dir / "voice"
    out.mkdir(exist_ok=True)
    job = out / "job.json"
    engine, style = (engine, "") if engine else film_voice_engine()
    job.write_text(json.dumps({"lines": lines, "out_dir": str(out), "ffmpeg": footage.ffmpeg_exe(), "rate": rate, "engine": engine,
                               "style": style, "parallel": 1 if engine == "gemini" else 3}), encoding="utf-8")
    film.say(f"speaking {len(lines)} lines in {len(sp['cast']) + 1} voices ({engine})", 0.1)
    r = subprocess.run([str(AUDIO_PY), str(HERE / "lf_voice.py"), str(job)], capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, **ENV}, timeout=3600 * 3, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW | BELOW_NORMAL)
    if r.returncode:
        raise RuntimeError(f"voices failed: {(r.stderr or r.stdout)[-500:].strip()}")
    film.update(stage="voiced", progress=1.0, voice_engine=engine, message=f"{len(lines)} lines spoken ({engine})", error="")


def room_backgrounds(film, sp, proj):
    """A generated backdrop per room and time of day (kept in film.dir/bg/, so a rebuild costs nothing), copied into the
    project: {scene id: asset path}. Off when Settings say so or no paid image provider is set up: the free service
    (Pollinations) ignores the style (photo-real behind a flat cartoon cast), sends small pictures and stamps its logo in
    a corner, so on it the films keep their drawn rooms. Scenes where someone starts sitting or lying keep the flat room
    (its furniture is where the cast is placed). A picture that fails leaves that scene's flat room, never stops the build."""
    import daily_shorts as e
    import genmedia
    import visuals
    s = e.load_settings()
    style = s.get("lf_backgrounds", "off")
    providers = [p for p in genmedia.image_providers(s.get("image_provider", "auto")) if p != "pollinations"]
    if style == "off":
        return {}
    if not providers:
        film.say("generated rooms need a paid picture service (MuAPI credits or Gemini billing): the drawn rooms stay")
        return {}
    budget = genmedia.Budget(float(s.get("gen_budget_usd", 1.0)) * 3, film.id)      # a film is worth a few Shorts
    folder = film.dir / "bg"
    folder.mkdir(exist_ok=True)
    out, skip = {}, set()
    for sc_ in sp["scenes"]:
        if any(v in ("sit", "lie") for v in (sc_.get("start") or {}).values()):
            continue
        key = f"{sc_['room']}-{sc_['tone']}-{style}"
        # cached under the provider that made it, so a picture from the free service (older films) is never reused
        dest = next((p for p in (folder / f"{key}-{q}.png" for q in providers) if p.exists()), None)
        if dest is None:
            try:
                film.say(f"background: {sc_['room']} at {sc_['tone']}")
                made, provider, _ = genmedia.image(visuals.room_prompt(sc_["room"], sc_["tone"], style), folder / f"{key}.part.png",
                                                   providers, s.get("image_model", ""), "16:9", budget, key, film.say, skip)
                dest = made.replace(folder / f"{key}-{provider}.png")
            except Exception as err:                                   # noqa: BLE001
                film.say(f"background {key} skipped: {str(err)[:120]}")
                continue
        (proj / "assets" / "bg").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dest, proj / "assets" / "bg" / dest.name)
        out[sc_["id"]] = f"assets/bg/{dest.name}"
    return out


def build_film(film):
    sp = lf_plan.apply_style(sc.load(film.screenplay), film.meta.get("style", "cartoon"))
    timings = {x["id"]: x for x in json.loads((film.dir / "voice" / "lines.json").read_text(encoding="utf-8"))}
    proj = film.dir / "project"
    bgs = room_backgrounds(film, sp, proj)
    gap, _ = lf_plan.fit_gap(sp, timings)
    scenes = lf_plan.plan(sp, timings, gap, bgs)
    total = lf_build.write_project(proj, scenes)
    film.plan.write_text(json.dumps(scenes), encoding="utf-8")
    lint_project(film)
    film.say("making the storyboard sheet", 0.6)
    sheet = storyboard(film, scenes)
    film.update(stage="built", seconds=round(total, 1), progress=1.0, error="", gap=round(gap, 2), backgrounds=len(bgs),
                storyboard=bool(sheet),
                plan_checks=lf_finish.check_plan(scenes, sp),
                message=f"project built: {len(scenes)} scenes, {int(total // 60)}:{int(total % 60):02d}")


def lint_project(film):
    """HyperFrames' own linter over the generated project: an error there would waste the whole render, so stop now."""
    node = shutil.which("node")
    if not node or not HF.exists():
        return
    r = subprocess.run([node, str(HF), "lint"], cwd=str(film.dir / "project"), capture_output=True, text=True, encoding="utf-8", errors="replace",
                       env={**os.environ, **ENV}, timeout=300, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW | BELOW_NORMAL)
    out = (r.stdout or "") + (r.stderr or "")
    found = re.search(r"(\d+)\s+error", out)
    if found and int(found.group(1)):
        raise RuntimeError("HyperFrames found errors in the project: " + " | ".join(
            ln.strip() for ln in out.splitlines() if "error" in ln.lower() or ln.strip().startswith(("✗", "[", "⚠")))[:400])


def storyboard(film, scenes):
    """One frame from the middle of every scene on a contact sheet (out/storyboard.jpg), made before the long render so a
    wrong room, a crowded card or a missing character is found in a minute, not after half an hour. None if it can't be made."""
    node = shutil.which("node")
    if not node or not HF.exists():
        return None
    times, t0 = [], 0.0
    for s in scenes:
        times.append(round(t0 + min(s["dur"] - 0.5, max(1.0, s["dur"] * 0.45)), 2))
        t0 += s["dur"]
    try:
        r = subprocess.run([node, str(HF), "snapshot", "--no-end", "--at", ",".join(str(t) for t in times)], cwd=str(film.dir / "project"),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", env={**os.environ, **ENV}, timeout=900,
                           stdin=subprocess.DEVNULL, creationflags=NO_WINDOW | BELOW_NORMAL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    # a long film's frames come on several sheets (contact-sheet-1.jpg, -2.jpg, ...): stacked into one picture, in order
    found = set(re.findall(r"([A-Za-z]:\\[^\r\n]*?contact-sheet(?:-\d+)?\.jpg)", (r.stdout or "") + (r.stderr or "")))
    sheets = sorted((Path(p) for p in found if Path(p).exists()), key=lambda p: int(re.sub(r"\D", "", p.stem) or 0))
    if r.returncode or not sheets:
        return None
    from PIL import Image
    imgs = [Image.open(p).convert("RGB") for p in sheets]
    board = Image.new("RGB", (max(i.width for i in imgs), sum(i.height for i in imgs)), "#1c1c1c")
    y = 0
    for img in imgs:
        board.paste(img, (0, y))
        y += img.height
    dest = film.dir / "out" / "storyboard.jpg"
    dest.parent.mkdir(exist_ok=True)
    board.save(dest, quality=90)
    return dest


def render_film(film, quality="looks", workers=3):
    node = shutil.which("node")
    if not node or not HF.exists():
        raise RuntimeError("HyperFrames isn't installed (run: npm install --ignore-scripts in the longform folder)")
    out = film.dir / "out"
    out.mkdir(exist_ok=True)
    silent = out / "silent.mp4"
    silent.unlink(missing_ok=True)
    film.say("rendering the picture (this takes a while)", 0.0)
    began = time.monotonic()
    p = subprocess.Popen([node, str(HF), "render", str(film.dir / "project"), "--output", str(silent), "--quality", quality, "--fps", "30",
                          "--workers", str(workers)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                         env={**os.environ, **ENV}, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW | BELOW_NORMAL)
    tail, last = [], -1
    seen = [time.monotonic()]

    def watchdog():                                       # a render that makes no progress for 25 minutes is stuck
        while p.poll() is None:
            if time.monotonic() - seen[0] > 1500:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, creationflags=NO_WINDOW)
                return
            time.sleep(30)
    threading.Thread(target=watchdog, daemon=True).start()
    for line in p.stdout:
        seen[0] = time.monotonic()
        m = re.search(r'@hf-progress (\{.*\})', line)
        if m:
            try:
                d = json.loads(m.group(1))
            except ValueError:
                continue
            pct = int(d.get("pct", 0))
            if pct != last:
                last = pct
                film.say(f"rendering the picture: {pct}%", pct / 100)
        else:
            tail = (tail + [line.rstrip()])[-8:]
    if p.wait() or not silent.exists() or silent.stat().st_size < 100_000:
        raise RuntimeError("the render failed: " + " | ".join(tail)[-500:])
    film.update(stage="rendered", progress=1.0, error="", message="picture rendered", render_seconds=round(time.monotonic() - began))


def finish_film(film, settings):
    scenes = json.loads(film.plan.read_text(encoding="utf-8"))
    sp = sc.load(film.screenplay)
    total = lf_plan.total_seconds(scenes)
    out = film.dir / "out"
    final, used_music = mix_film(film, scenes, settings)
    film.say("checking the finished film", 0.8)
    thumb = lf_finish.make_thumbnail(final, sp["title"], out / "thumb.jpg", at=min(14.0, total / 4))
    checks = lf_finish.check_film(final, total, film.meta.get("limits") or lf_finish.LIMITS)    # an explainer has its own length
    pack = lf_finish.upload_pack(sp, scenes, final, out / "thumb.jpg")
    (film.dir / "upload_pack.json").write_text(json.dumps(pack, ensure_ascii=False, indent=1), encoding="utf-8")
    (film.dir / "manifest.json").write_text(json.dumps(lf_finish.manifest(sp, scenes, used_music, film.meta), ensure_ascii=False, indent=1), encoding="utf-8")
    film.update(stage="review", progress=1.0, checks=checks, error="", message="ready to watch" if checks["ok"] else "ready, but some checks need a look",
                thumb=bool(thumb))


def mix_film(film, scenes, settings, tracks=2):
    """Voices, effects and up to `tracks` safe-music tracks mixed under the rendered picture, loudness matched to YouTube
    (-14 LUFS): (out/final.mp4, [(music file, its source)])."""
    total = lf_plan.total_seconds(scenes)
    audio = film.dir / "audio"
    audio.mkdir(exist_ok=True)
    out = film.dir / "out"
    film.say("mixing voices, sound effects and music", 0.1)
    starts, t0 = [], 0.0
    for s in scenes:
        starts += [(x["id"], t0 + x["t"]) for x in s["lines"]]
        t0 += s["dur"]
    raw = lf_audio.voice_track(film.dir / "voice", starts, total, audio / "voice_raw.wav")
    voice = sound.master_voice(raw, audio / "voice.wav", film.meta.get("voice_engine", "edge"))     # each engine has its own chain
    cuts, hits = lf_audio.sfx_plan(scenes)
    sfx, _ = sound.sfx_track(audio / "sfx.wav", total, cuts, hits, settings.get("sfx_level", "subtle"), seed=len(film.id))
    music, used_music = None, []
    if settings.get("music_mode", "auto") != "none":
        import daily_shorts as e
        entries = [(n, s_, t) for n, s_, t, ok in e.music_entries() if ok]
        files = [e.SAFE_MUSIC / n for n in lf_audio.pick_music(entries, tracks, seed=len(film.id))]
        if files:
            music = lf_audio.music_track(files, total, audio / "music.wav", audio)
            used_music = [(f.name, {n: s_ for n, s_, _ in entries}.get(f.name, "")) for f in files]
    mixed = lf_audio.mix(voice, sfx, music, audio / "mix.wav", float(settings.get("lf_music_gain", 0.32)))
    joined = lf_audio.mux(out / "silent.mp4", mixed, out / "joined.mp4")
    film.say("matching the loudness to YouTube", 0.6)
    final = sound.normalize_video_audio(joined, out / "final.mp4")
    joined.unlink(missing_ok=True)
    return final, used_music


def run_all(film, settings, ask_llm=None, quality="looks"):
    """Whatever is left for this film, from where it stopped. Raises on failure with film.meta['error'] set."""
    steps = {"new": lambda: write_screenplay(film, ask_llm), "screenplay": lambda: voice_film(film, float(settings.get("lf_voice_rate", 1.0))),
             "voiced": lambda: build_film(film), "built": lambda: render_film(film, quality), "rendered": lambda: finish_film(film, settings)}
    if film.meta.get("kind") == "explainer":          # a narrated explainer (explainer.py): its own script, drawings and build
        import explainer
        steps.update(new=lambda: explainer.write(film, ask_llm), voiced=lambda: explainer.build(film))
    with FilmLock():
        try:
            while film.meta["stage"] in steps:
                stage = film.meta["stage"]
                if film.meta.get("gates") and stage in GATES and stage not in film.meta.get("approved", []):
                    film.update(message=GATE_TEXT[stage], progress=1.0, error="")
                    return
                if stage == "new" and ask_llm is None:
                    raise RuntimeError("no script writer is available")
                steps[stage]()
        except Exception as err:
            film.update(error=f"{type(err).__name__}: {err}", message="stopped: " + str(err)[:200])
            raise


def approve_gate(film, stage):
    """The person has looked at this stop (the script, or the storyboard): the next run goes past it."""
    film.update(approved=sorted(set(film.meta.get("approved", [])) | {stage}), error="")


def approve(film):
    film.update(stage="approved", message="approved")


def reject(film, reason):
    film.update(stage="rejected", reject_reason=reason.strip(), message="rejected: " + reason.strip()[:120])


def mark_posted(film):
    film.update(stage="posted", message="posted")


def redo_from(film, stage):
    """Go back to `stage` (e.g. 'screenplay' to re-voice and re-render) after editing the screenplay."""
    if stage in ORDER:
        film.update(stage=stage, error="", progress=0.0, message=f"will redo from {stage}")


def main(args):
    import daily_shorts as e
    s = e.load_settings()
    cmd = args[0] if args else "help"
    if cmd == "new":
        f = new_film(" ".join(a for a in args[1:] if not a.isdigit() and a not in ("--gates", "--stick")), int(next((a for a in args[1:] if a.isdigit()), 9)),
                     gates="--gates" in args, style="stick" if "--stick" in args else "cartoon")
        print(f.id)
        return 0
    if cmd in ("all", "script", "voice", "build", "render", "finish"):
        film = Film(FILMS / args[1])
        stage = {"script": "new", "voice": "screenplay", "build": "voiced", "render": "built", "finish": "rendered"}.get(cmd)
        if stage:
            film.update(stage=stage)
        ask_llm = None
        if film.meta["stage"] == "new":
            M = e.load_mpt()
            ask_llm = lambda prompt: e.ask(M.llm, prompt)            # noqa: E731
        try:
            run_all(film, s, ask_llm, "draft" if "--draft" in args else "looks")
        except Exception as err:
            print(f"FILM FAILED: {err}")
            return 1
        print(f"FILM {film.meta['stage'].upper()}: {film.meta.get('title')}")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
