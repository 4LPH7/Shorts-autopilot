"""Cinematic visuals: one generated keyframe per voiceover beat, all in one consistent style, moved like a camera,
instead of a montage of stock clips that never quite match each other or the words.

How a Short gets its pictures in this mode:
  1. The LLM writes a shot list from the beats (what the camera literally sees, one shot per beat, varied framing).
  2. Every shot becomes an image prompt in the chosen style pack (genmedia picks the provider: MuAPI, Gemini, or the
     free Pollinations service), generated in parallel and cached in work/<video>/keyframes/.
  3. Each keyframe is filmed for exactly the beat's length with an eased camera move (never a still frame), so the
     result reads as footage, not a slideshow. footage.compose() does the cutting through still_candidate().
Long films use room_prompt() for a painted or photographic background behind the animated characters.

Everything that costs money goes through a genmedia.Budget; a video never fails because a picture could not be
made: a missing keyframe borrows its neighbour's, and when no provider works the stock-footage path takes over."""

import json
import re
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import footage
import genmedia

W, H, FPS = footage.W, footage.H, footage.FPS

# style key -> (label, prompt text). One style per video keeps every frame feeling like one piece.
STYLES = {
    "cinematic": ("Cinematic photoreal", "cinematic photoreal still, 35mm film look, well-exposed subject lit by a motivated key light, "
                                         "teal and amber grade, rich colour, sharp focus on the subject, shallow depth of field, "
                                         "soft film grain, bright enough to read on a phone"),
    "noir": ("Dark noir", "graphic noir photograph, hard chiaroscuro key light that keeps the subject's face clearly lit, deep blacks, "
                          "one red accent, thin fog, 50mm lens, high contrast, desaturated"),
    "documentary": ("Natural documentary", "candid documentary photograph, natural available light, realistic skin and textures, "
                                           "muted true-to-life colour, 35mm, slight grain"),
    "illustrated": ("Editorial illustration", "bold editorial illustration, flat shapes with textured grain, a limited palette of deep "
                                              "navy, cream and one warm accent, strong silhouettes, print texture"),
}
RULES = ("vertical 9:16 composition, the subject in the upper two thirds of the frame, nothing important in the bottom fifth, "
         "no text, no letters, no numbers, no signs, no logos, no watermark, no captions, no split screen, no collage")
# Long-film backgrounds: what each room kind looks like, and how it is drawn
ROOM_TEXT = {"living": "a cosy living room with a sofa, a rug and a window", "bedroom": "a small bedroom with a bed, a lamp and a window",
             "hospital": "a hospital room with a bed, a monitor and a window", "classroom": "a school classroom with desks and a board",
             "street": "a city street with shop fronts and parked cars", "office": "an open-plan office with desks and screens",
             "kitchen": "a home kitchen with a counter, cupboards and a window", "park": "a city park with a bench, a path and trees",
             "cafe": "a small cafe with tables, a counter and a window", "stage": "a theatre stage with red curtains and one spotlight",
             "void": "an abstract dark studio space with a soft gradient and a pool of light on the floor"}
TONE_TEXT = {"day": "in daylight", "evening": "at golden-hour evening light", "night": "at night with warm lamps", "dawn": "at pale dawn"}
BG_STYLES = {"painted": "soft painted storybook background, gentle brush texture, warm muted colours, simple clean shapes, "
                        "empty of people and animals, the floor visible across the bottom quarter of the frame",
             "photo": "cinematic photoreal wide shot, 35mm film look, soft low-key lighting, empty of people, the floor visible "
                      "across the bottom quarter of the frame"}
MOVES_FOR_STILLS = ("push", "left", "pull", "right", "push", "up", "pull", "left")


# ---- Shot list (LLM) ------------------------------------------------------------------------------------

def shot_prompt(topic, beats, style, lessons_text=""):
    label = STYLES.get(style, STYLES["cinematic"])[0]
    lines = "\n".join(f'{i + 1}. "{t}"' for i, (_, _, t) in enumerate(beats))
    return (f"You are the director of photography for a fast vertical YouTube Short about: {topic}. The pictures are "
            f"{label} stills made by an image model, one per voiceover beat. For EVERY beat write one shot: what the camera "
            "literally sees (a concrete subject, a place, an action or a reaction, and the framing: close, medium or wide) "
            "that illustrates the words, literally or as a clear metaphor. Vary framing and subject from beat to beat; keep "
            "one recurring person or object where the story needs continuity; never two similar shots in a row. Describe "
            "people by role and look, never real public figures or brands. Never ask for text, signs, numbers, screens "
            "with writing or logos. Each shot in 15-35 words.\n"
            "Continuity: if a person recurs, describe them ONCE in full (age, build, hair, clothes) and repeat that exact "
            "description word for word in every shot they appear in, so the image model draws the same person. "
            "Every shot must name something concrete a camera can photograph; when the words are abstract, show a person "
            "reacting or an object that stands for the idea.\n"
            f"{lessons_text}\nBeats:\n{lines}\n\n"
            'Reply with only a JSON array like [{"i": 1, "shot": "...", "move": "push"}], one object per beat, '
            'move one of push, pull, left, right, up.')


def parse_shots(reply, beats):
    """One shot per beat from the LLM reply; a missing or empty shot is derived from the beat's own words."""
    shots = [None] * len(beats)
    m = re.search(r"\[.*\]", reply or "", re.S)
    if m:
        try:
            for row in json.loads(m.group(0)):
                i = int(row.get("i", 0)) - 1
                if 0 <= i < len(beats) and isinstance(row.get("shot"), str) and row["shot"].strip():
                    move = str(row.get("move", "")).lower()
                    shots[i] = {"shot": row["shot"].strip()[:400], "move": move if move in MOVES_FOR_STILLS else None}
        except (ValueError, TypeError, AttributeError):
            pass
    # a missing shot becomes another angle of its nearest neighbour: the spoken words themselves ("Notice what's
    # missing? Zero.") give an image model nothing to photograph and come out as blur
    have = [i for i, sh in enumerate(shots) if sh]
    for i, (_, _, text) in enumerate(beats):
        if shots[i] is None:
            if have:
                j = min(have, key=lambda k: (abs(k - i), k))
                angle = "a close-up detail" if abs(j - i) % 2 else "a wider reverse angle"
                shots[i] = {"shot": f"{angle} of the same scene: {shots[j]['shot']}", "move": None}
            else:
                words = " ".join(str(text).split()[:14]) or "a quiet city street at night"
                shots[i] = {"shot": f"a person in a softly lit room reacting thoughtfully, the moment that goes with: {words}", "move": None}
    return shots


def keyframe_prompt(shot, style):
    return f"{shot.rstrip('.')}. {STYLES.get(style, STYLES['cinematic'])[1]}, {RULES}."


def room_prompt(kind, tone, style="painted"):
    """The prompt for a long-film background: one per room and time of day, 16:9."""
    return (f"{ROOM_TEXT.get(kind, ROOM_TEXT['void'])} {TONE_TEXT.get(tone, '')}, wide establishing shot at eye level, "
            f"{BG_STYLES.get(style, BG_STYLES['painted'])}, 16:9, no text, no letters, no logos, no watermark.")


# ---- Keyframes -----------------------------------------------------------------------------------------

def ready(s):
    """Can this machine make pictures at all? (some provider has a key; Pollinations always counts, slowly)"""
    return bool(genmedia.image_providers(s.get("image_provider", "auto")))


def make_keyframes(shots, style, work, s, budget, log=print, parallel=4):
    """work/keyframes/NN.png for every shot, in parallel, cached by prompt.
    Returns ({index: {"path", "provider", "model"}}, report). A frame that fails is left out; the caller borrows a
    neighbour (fill_gaps). Never raises for one bad frame; stops early when the budget is reached."""
    folder = Path(work) / "keyframes"
    folder.mkdir(parents=True, exist_ok=True)
    providers = genmedia.image_providers(s.get("image_provider", "auto"))
    model = s.get("image_model", "") or ""
    if providers == ["pollinations"]:
        parallel = 1                                   # the free service allows one image at a time
        log("Images: only the free Pollinations service is set up: about 45 s a frame (add a MuAPI or Gemini key for fast, sharp frames)")
    skip, made, report = set(), {}, {"providers": {}, "failed": [], "style": style}

    def one(i):
        prompt = keyframe_prompt(shots[i]["shot"], style)
        dest, meta = folder / f"{i + 1:02d}.png", folder / f"{i + 1:02d}.json"
        if dest.exists() and meta.exists():
            try:
                old = json.loads(meta.read_text(encoding="utf-8"))
                if old.get("prompt") == prompt:
                    return i, dest, old.get("provider", "cache"), old.get("model", "")
            except ValueError:
                pass
        try:
            path, provider, used = genmedia.image(prompt, dest, providers, model, "9:16", budget, f"beat {i + 1}", log, skip)
        except genmedia.BudgetExceeded as err:
            raise err
        except Exception as err:                         # noqa: BLE001
            return i, None, type(err).__name__, str(err)[:160]
        meta.write_text(json.dumps({"prompt": prompt, "provider": provider, "model": used, "shot": shots[i]["shot"]}, indent=1),
                        encoding="utf-8")
        return i, path, provider, used

    try:
        with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
            for i, path, provider, used in pool.map(one, range(len(shots))):
                if path:
                    made[i] = {"path": str(path), "provider": provider, "model": used}
                    report["providers"][provider] = report["providers"].get(provider, 0) + 1
                    log(f"Keyframe {i + 1}/{len(shots)} <- {provider} {used}")
                else:
                    report["failed"].append(i + 1)
                    log(f"Keyframe {i + 1} failed ({provider}: {used})")
    except genmedia.BudgetExceeded as err:
        log(f"Images stopped: {err}")
        report["budget_stop"] = str(err)
    return made, report


def fill_gaps(frames, n):
    """{index: frame} for every beat: a missing frame borrows the nearest made one. Returns (frames, borrowed indices)."""
    if not frames:
        return {}, list(range(n))
    out, borrowed = {}, []
    have = sorted(frames)
    for i in range(n):
        if i in frames:
            out[i] = frames[i]
        else:
            out[i] = frames[min(have, key=lambda j: (abs(j - i), j))]
            borrowed.append(i)
    return out, borrowed


def still_candidate(i, frame, provider="generated", model=""):
    """A footage candidate that compose() films from a still picture instead of cutting from a clip. `frame` is a
    path or the dict make_keyframes returns."""
    if isinstance(frame, dict):
        provider, model, frame = frame.get("provider", provider), frame.get("model", model), frame["path"]
    return {"id": f"gen:{i + 1:02d}", "source": f"generated:{provider}", "path": str(frame), "still": True, "dur": 1e9,
            "w": W, "h": H, "provider": provider, "model": model, "tags": ""}


# ---- Filming a still ---------------------------------------------------------------------------------------

render_still = footage.render_still          # the ffmpeg primitive lives with the other cutting helpers


def plan_still_moves(n, seed, moves_hint=None):
    """A camera move for every cut: never a hold (a still that does not move is the slideshow tell), at most half zooms,
    never the same move twice in a row; the shot list's suggestion is used where it fits."""
    import random
    rng = random.Random(seed)
    start, zooms, out = rng.randrange(len(MOVES_FOR_STILLS)), ("push", "pull"), []
    for i in range(n):
        want = moves_hint[i] if moves_hint and i < len(moves_hint) else None
        prev = out[-1] if out else None
        options = ([want] if want else []) + [MOVES_FOR_STILLS[(start + i + k) % len(MOVES_FOR_STILLS)] for k in range(len(MOVES_FOR_STILLS))]
        out.append(next((m for m in options if m != prev and not (m in zooms and prev in zooms)), "up"))
    return out


def camera_for_stills(beats, s, seed, moves_hint=None):
    """footage.compose's `camera` argument for generated pictures: a move on every cut whatever the motion setting
    (off counts as subtle here), or None if this ffmpeg can't do perspective moves."""
    import motion
    level = s.get("motion_level", "subtle")
    level = "subtle" if level not in motion.AMOUNT else level
    cuts = sum(len(footage.cut_lengths(e - b)) for b, e, _ in beats)
    hints = []
    if moves_hint:
        for (b, e, _), mv in zip(beats, moves_hint):
            hints += [mv] * len(footage.cut_lengths(e - b))
    moves = plan_still_moves(cuts, seed, hints)
    probe = motion.camera_filter(moves[0], level, 1.0)
    r = footage.run([footage.ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", f"color=c=gray:s={W}x{H}:d=0.3:r=30",
                     "-vf", probe, "-frames:v", "3", "-f", "null", "-"], timeout=60)
    if r.returncode:
        return None
    return lambda i, seconds: motion.camera_filter(moves[i % len(moves)], level, seconds)


# ---- Self-test (called by daily_shorts --self-test) ----------------------------------------------------------

def self_test(tmp):
    """Pure parsing plus one real still through ffmpeg: it must play for the asked length and must not read as frozen."""
    import subprocess
    beats = [(0.0, 3.4, "Your phone is listening"), (3.4, 7.0, "and it sells what it hears")]
    shots = parse_shots('text before [{"i": 1, "shot": "A phone face down on a kitchen table, close", "move": "push"}, {"i": 9, "shot": "x"}] after', beats)
    assert shots[0]["shot"].startswith("A phone") and shots[0]["move"] == "push", shots
    assert shots[1]["shot"].startswith("a close-up detail of the same scene: A phone") and shots[1]["move"] is None, shots
    assert parse_shots("not json", beats)[0]["shot"].startswith("a person"), "fallback shot with no neighbours"
    assert "no text" in keyframe_prompt("a desk", "cinematic") and "9:16" in keyframe_prompt("a desk", "nope")
    assert "16:9" in room_prompt("cafe", "night") and "cafe" in room_prompt("cafe", "night")
    moves = plan_still_moves(12, "seed", ["push"] * 12)
    assert "hold" not in moves and all(a != b for a, b in zip(moves, moves[1:])), moves
    frames, borrowed = fill_gaps({1: "b.png"}, 3)
    assert frames == {0: "b.png", 1: "b.png", 2: "b.png"} and borrowed == [0, 2]
    assert still_candidate(3, "x.png")["id"] == "gen:04"
    c = still_candidate(0, {"path": "k.png", "provider": "muapi", "model": "z-image-turbo"})
    assert c["still"] and c["source"] == "generated:muapi" and c["path"] == "k.png"
    tmp = Path(tmp)
    src = tmp / "still.png"
    r = footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:d=1", "-frames:v", "1", str(src)])
    assert r.returncode == 0, r.stderr
    import motion
    out = render_still(src, tmp / "still.mp4", 2.5, motion.camera_filter("push", "subtle", 2.5))
    dur = footage.probe(out)[0]
    assert abs(dur - 2.5) < 0.1, dur
    r = subprocess.run([footage.ffmpeg_exe(), "-v", "info", "-i", str(out), "-vf", "freezedetect=n=0.001:d=1.0", "-f", "null", "-"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert "freeze_start" not in r.stderr, "a moving still must not read as a frozen picture"
    return "visuals: shot parsing, moves, gap filling, one still filmed and not frozen"
