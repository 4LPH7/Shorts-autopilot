"""What happens to a finished long film: automatic checks, a thumbnail, and the text to paste into YouTube.
Main-engine Python (ffmpeg + Pillow). Nothing here renders; longform.py calls it after the mix."""

import json
import re
import textwrap
from pathlib import Path

import footage

LIMITS = {"min": 470.0, "max": 625.0}
TARGET_LUFS = (-16.0, -12.0)
FONTS = ("C:/Windows/Fonts/seguibl.ttf", "C:/Windows/Fonts/arialbd.ttf")


def scan(path):
    """One decode of the whole file: black stretches, long silences and integrated loudness."""
    r = footage.run([footage.ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(path), "-vf", "blackdetect=d=1.2:pix_th=0.04",
                     "-af", "silencedetect=n=-50dB:d=5,loudnorm=I=-14:print_format=json", "-f", "null", "-"], timeout=1800)
    err = r.stderr
    loud = re.search(r'"input_i"\s*:\s*"(-?[\d.]+)"', err)
    return {"black": len(re.findall(r"black_start", err)), "silence": len(re.findall(r"silence_start", err)),
            "lufs": float(loud.group(1)) if loud else None}


def check_film(path, expected=None):
    """{"ok": bool, "checks": [{"name", "ok", "detail"}]}: what a person would notice first."""
    dur, w, h = footage.probe(path)
    sc = scan(path)
    rows = [("length", LIMITS["min"] <= dur <= LIMITS["max"], f"{int(dur // 60)}:{int(dur % 60):02d} (wanted 8-10 minutes)"),
            ("picture", (w, h) == (1920, 1080), f"{w}x{h}"),
            ("loudness", sc["lufs"] is not None and TARGET_LUFS[0] <= sc["lufs"] <= TARGET_LUFS[1], f"{sc['lufs']} LUFS (wanted about -14)"),
            ("no dead air", sc["silence"] == 0, f"{sc['silence']} silent stretch(es) over 5 s"),
            ("no black frames", sc["black"] == 0, f"{sc['black']} black stretch(es) over 1.2 s")]
    if expected:
        rows.append(("matches the plan", abs(dur - expected) < 3.0, f"{dur:.1f} s against {expected:.1f} s planned"))
    checks = [{"name": n, "ok": bool(ok), "detail": d} for n, ok, d in rows]
    return {"ok": all(c["ok"] for c in checks), "checks": checks, "seconds": round(dur, 1)}


def chapters(scenes_plan, screenplay):
    """[(seconds, title)] starting at 0:00, one per chapter scene (YouTube needs 3+ and the first at 0:00)."""
    out, t = [(0.0, "Intro")], 0.0
    for s, sp in zip(scenes_plan, screenplay["scenes"]):
        if sp.get("chapter") and t > 1:
            out.append((t, sp["title"]))
        t += s["dur"]
    return out


def stamp(seconds):
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def upload_pack(screenplay, scenes_plan, final, thumb):
    """Title, description (with chapter timestamps), tags and file paths, ready for the Upload page's copy buttons."""
    ch = chapters(scenes_plan, screenplay)
    body = screenplay.get("description") or screenplay.get("logline", "")
    stamps = "\n".join(f"{stamp(t)} {name}" for t, name in ch) if len(ch) >= 3 else ""
    return {"title": screenplay["title"][:100], "description": body + ("\n\n" + stamps if stamps else "") + "\n\nAI-generated voices and animation.",
            "tags": ", ".join(screenplay.get("tags", [])[:15]), "file": str(final), "thumbnail": str(thumb) if Path(thumb).exists() else ""}


def make_thumbnail(video, title, dest, at=14.0):
    """A 1280x720 thumbnail: a frame from the film under a big title. Returns dest, or None when Pillow can't do it."""
    from PIL import Image, ImageDraw, ImageFont
    raw = Path(dest).with_suffix(".frame.png")
    r = footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", "-ss", f"{at:.1f}", "-i", str(video), "-frames:v", "1", str(raw)])
    if r.returncode or not raw.exists():
        return None
    im = Image.open(raw).convert("RGB").resize((1280, 720))
    shade = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(shade)
    for y in range(720):
        d.line([(0, y), (1280, y)], fill=(8, 10, 30, int(210 * max(0, (y - 260) / 460) ** 1.4)))
    im = Image.alpha_composite(im.convert("RGBA"), shade)
    font = None
    for f in FONTS:
        try:
            font = ImageFont.truetype(f, 92)
            break
        except OSError:
            continue
    lines = textwrap.wrap(title.upper(), 16)[:3]
    draw = ImageDraw.Draw(im)
    y = 690 - 104 * len(lines)
    for i, line in enumerate(lines):
        draw.text((56, y + i * 104), line, font=font or ImageFont.load_default(), fill="#ffcc33" if i == len(lines) - 1 else "#ffffff",
                  stroke_width=7, stroke_fill="#10132b")
    im.convert("RGB").save(dest, quality=92)
    raw.unlink(missing_ok=True)
    return Path(dest)
