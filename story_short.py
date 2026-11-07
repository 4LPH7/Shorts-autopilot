"""Animated story Shorts (20-60 seconds, 1080x1920): a narrator tells one true, surprising story while 1-3 cartoon
characters act it out. The long-film pipeline does the work: lf_screenplay writes it (one call), lf_voice speaks it with
Edge voices and lip sync, lf_plan + lf_build + the HyperFrames kit animate it on a vertical stage, lf_audio and lf_finish
mix it (-14 LUFS) and check it. The finished Short lands in Review like every other Short: it counts toward the buffer
and nothing is posted until you approve it.

    run_daily.bat --story [job.json | topic words] [--whatif]
    job = {"topic": "...", "seconds": 30, "style": "cartoon" | "stick", "story": "true" | "whatif"}
Two kinds: a true story (a twist, a payoff line) or a "What if...?" (imagined consequences from real mechanisms, ending on a
question to the viewer); a topic that starts "What if" is the second kind. With no topic the LLM suggests one that isn't
in topics_used.txt. One folder per Short under longform/shorts (not
longform/films: the Long video page lists those)."""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import lf_build
import lf_finish
import lf_plan
import lf_screenplay as sc
import longform as lf

SHORTS = lf.HERE / "longform" / "shorts"
LIMITS = {"min": 20.0, "max": 58.0}                    # YouTube's ceiling is 60 s; the checks fail anything over 58
FRAME = tuple(lf_plan.SHORT_FRAME)


def new_short(topic, seconds=30, style="cartoon", story="true"):
    """story: "true" (a real story with a payoff) or "whatif" (an imagined situation that ends on a question)."""
    folder = SHORTS / f"{datetime.now():%Y%m%d-%H%M%S}-{lf.slug(topic)}"
    folder.mkdir(parents=True)
    film = lf.Film.__new__(lf.Film)
    film.dir, film.meta = folder, {}
    film.update(kind="short", story=story if story in sc.STORY_KINDS else "true", topic=topic, seconds_wanted=int(seconds), style=style,
                stage="new", title=topic, message="", progress=0.0, error="", created=datetime.now().isoformat(timespec="seconds"))
    return film


def pick_topic(ask_llm, used, story="true"):
    """A story the channel hasn't told: the first of the LLM's ideas that isn't in `used`."""
    seen = {u.strip().lower() for u in used}
    ideas = sc.parse_json(ask_llm(sc.story_ideas_prompt(10, used, story)))
    fresh = [str(i).strip() for i in (ideas if isinstance(ideas, list) else []) if str(i).strip() and str(i).strip().lower() not in seen]
    if not fresh:
        raise RuntimeError("the LLM suggested no new story")
    return fresh[0]


# ---- Stages ------------------------------------------------------------------------------------------

def write(film, ask_llm):
    import daily_shorts as e
    sp = sc.new_short(ask_llm, film.meta["topic"], film.meta.get("seconds_wanted", 30), e.lessons_block(e.load_lessons(), "script"),
                      film.say, film.dir, film.meta.get("story", "true"))
    lf_plan.lines_of(sp)
    sc.save(sp, film.screenplay)
    film.update(stage="screenplay", title=sp["title"], words=sc.spoken_words(sp), progress=1.0, error="",
                message=f"story written: {len(sp['scenes'])} scene(s), {len(sp['cast'])} character(s), {sc.spoken_words(sp)} words")


def build(film):
    sp = lf_plan.apply_style(sc.load(film.screenplay), film.meta.get("style", "cartoon"))
    timings = {x["id"]: x for x in json.loads((film.dir / "voice" / "lines.json").read_text(encoding="utf-8"))}
    gap, _ = lf_plan.fit_gap(sp, timings, LIMITS["min"], LIMITS["max"], tall=True)
    scenes = lf_plan.plan(sp, timings, gap, tall=True)
    total = lf_build.write_project(film.dir / "project", scenes)
    if total > LIMITS["max"]:
        raise RuntimeError(f"the voiced story runs {total:.0f} s, over the {LIMITS['max']:.0f} s a Short allows: shorten the script")
    film.plan.write_text(json.dumps(scenes), encoding="utf-8")
    lf.lint_project(film)
    film.say("making the storyboard sheet", 0.6)
    sheet = lf.storyboard(film, scenes)
    film.update(stage="built", seconds=round(total, 1), gap=round(gap, 2), storyboard=bool(sheet), progress=1.0, error="",
                plan_checks=lf_finish.check_plan(scenes, sp, LIMITS), message=f"project built: {len(scenes)} scene(s), {total:.0f} s")


def finish(film, settings):
    scenes = json.loads(film.plan.read_text(encoding="utf-8"))
    final, music = lf.mix_film(film, scenes, settings, tracks=1)
    film.say("checking the finished Short", 0.8)
    checks = lf_finish.check_film(final, lf_plan.total_seconds(scenes), LIMITS, FRAME)
    stem = queue(film, sc.load(film.screenplay), final, checks, music)
    film.update(stage="queued", progress=1.0, checks=checks, review=stem, error="",
                message="waiting in Review" + ("" if checks["ok"] else ": some checks need a look"))


def script_text(sp):
    """What the approver reads on the Review page: who says what, then the claims, the uncertain ones first."""
    names = {"narrator": "Narrator", **{c["id"]: c["name"] for c in sp["cast"]}}
    lines = [f"{names.get(b['who'], b['who'])}: {b['text']}" for s in sp["scenes"] for b in s["beats"]]
    claims = sorted(sc.claims(sp), key=lambda c: not c[3])
    if claims:
        lines += ["", "Claims to verify before approving:"] + [("CHECK  " if chk else "- ") + claim for _, _, claim, chk in claims]
    return "\n".join(lines)


def queue(film, sp, final, checks, music):
    """The Short and its metadata into Review, the same pair every other Short has. Returns its name there."""
    import daily_shorts as e
    stem = film.dir.name
    e.REVIEW.mkdir(exist_ok=True)
    shutil.copyfile(final, e.REVIEW / f"{stem}.mp4")
    voices = {c["name"]: lf_finish.voice_name(c["voice"]) for c in sp["cast"]}
    voices["Narrator"] = lf_finish.voice_name("narrator-" + sp["narrator"]["voice"])
    (e.REVIEW / f"{stem}.json").write_text(json.dumps({
        "topic": sp.get("topic", film.meta["topic"]), "title": sp["title"][:100],
        "description": (sp.get("description") or sp.get("logline", "")).strip() + "\n\nAI-generated voices and animation.",
        "tags": sp.get("tags", [])[:15], "music": music[0][0] if music else "none", "motion": "animated", "look": film.meta.get("style", "cartoon"),
        "narration": {"engine": "edge", "voice": ", ".join(f"{k}: {v}" for k, v in voices.items())}, "weak_beats": [],
        "visuals": {"mode": "animated story", "style": film.meta.get("style", "cartoon"), "used": "animated"},
        "qa": {"passed": checks["ok"], "checks": checks["checks"], "seconds": checks.get("seconds")},
        "credits": [], "clips": [], "script": script_text(sp),
        "claims": [{"claim": c, "check": chk} for _, _, c, chk in sc.claims(sp)],
        "story": {"folder": str(film.dir), "kind": film.meta.get("story", "true"), "music_source": music[0][1] if music else ""},
        "rendered": datetime.now().isoformat(timespec="seconds")}, indent=2, ensure_ascii=False), encoding="utf-8")
    with e.HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(sp.get("topic", film.meta["topic"]) + "\n")
    return stem


def run(film, settings, ask_llm, quality="looks"):
    """Whatever is left for this Short, from where it stopped. Raises with film.meta['error'] set."""
    steps = {"new": lambda: write(film, ask_llm), "screenplay": lambda: lf.voice_film(film, float(settings.get("voice_rate", 1.05)), "edge"),
             "voiced": lambda: build(film), "built": lambda: lf.render_film(film, quality), "rendered": lambda: finish(film, settings)}
    try:
        while film.meta["stage"] in steps:
            steps[film.meta["stage"]]()
    except Exception as err:
        film.update(error=f"{type(err).__name__}: {err}", message="stopped: " + str(err)[:200])
        raise


def story_kind(asked, topic, flag=False):
    """"whatif" when asked for (job or --whatif) or when the topic reads "What if...", else "true"."""
    if asked in sc.STORY_KINDS:
        return asked
    return "whatif" if flag or topic.lower().lstrip().startswith("what if") else "true"


def main(args):
    """--story [job.json | topic words] [--resume <folder name>] [--draft]: one story Short into Review."""
    import daily_shorts as e
    s = e.load_settings()
    M = e.load_mpt()
    ask_llm = lambda prompt: e.ask(M.llm, prompt)                         # noqa: E731
    words = [a for a in args if a not in ("--draft", "--whatif")]
    if "--resume" in words:
        film = lf.Film(SHORTS / words[words.index("--resume") + 1])
    else:
        job = json.loads(Path(words[0]).read_text(encoding="utf-8")) if words and words[0].lower().endswith(".json") else {"topic": " ".join(words)}
        topic = str(job.get("topic") or "").strip()[:200]
        story = story_kind(job.get("story"), topic, "--whatif" in args)
        if not topic:
            used = e.HISTORY.read_text(encoding="utf-8").splitlines() if e.HISTORY.exists() else []
            topic = pick_topic(ask_llm, used, story)
        seconds = max(20, min(55, int(job.get("seconds") or 30)))
        film = new_short(topic, seconds, job.get("style") if job.get("style") in lf_plan.STYLES else "cartoon", story)
    print(f"Story Short: {film.meta['topic']} ({film.dir.name})")
    try:
        run(film, s, ask_llm, "draft" if "--draft" in args else "looks")
    except Exception as err:
        print(f"STORY SHORT FAILED: {type(err).__name__}: {err}")
        return 1
    print(f"READY FOR REVIEW: {e.REVIEW / (film.meta['review'] + '.mp4')} ({film.meta.get('seconds')} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
