"""Turns scene descriptions into a HyperFrames project: one sub-composition per scene (the kit in longform/kit draws and
animates it) mounted by a root index.html. Pure file generation, no rendering: longform.py runs the renderer.

A scene description S (what longform.py computes from the screenplay and the voice timings):
    id, dur, cover ("cut" | "fade" | "wipe"), room {kind, tone}, cast [{id, look, x, y, face, start, mood}],
    events [{do, t, ...}], caps [{t, d, text, who, color}],
    art, focus, world (an explainer: its drawing, where the camera pushes in, the drawing's size),
    bg (optional: a generated background picture that stands in for the flat vector room, moved by the camera)."""

import json
import shutil
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE / "longform" / "kit"
GSAP = HERE / "longform" / "node_modules" / "gsap" / "dist" / "gsap.min.js"
KIT_JS = ("rooms.js", "rig.js", "acts.js", "cards.js", "art.js", "stage.js")
W, H = 1920, 1080


def kit_js():
    return "\n".join((KIT / name).read_text(encoding="utf-8") for name in KIT_JS)


def js_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def frame(S):
    """(width, height) of the picture: a film's 1920x1080, or what the plan asks for (a Short's 1080x1920). The world the
    rooms and the cast live in stays 1920x1080 either way; the frame is the camera's window onto it."""
    return tuple(S.get("frame") or (W, H))


def scene_html(S):
    pre = S["id"]
    fw, fh = frame(S)
    tall = fh > fw
    css = (KIT / "base.css").read_text(encoding="utf-8") + ((KIT / "short.css").read_text(encoding="utf-8") if tall else "")
    bg = f'<img id="{pre}-bg" class="bg" src="{S["bg"]}" alt="">' if S.get("bg") else ""
    # an explainer's drawing is made at the frame's own size (S.world), so the camera's world is that size too
    size = f' style="width:{S["world"][0]}px;height:{S["world"][1]}px"' if S.get("world") else ""
    return f"""<template>
  <style>{css}</style>
  <div id="root" data-composition-id="{pre}" data-width="{fw}" data-height="{fh}">
    <div id="{pre}-cam" class="cam"{size}>{bg}<div id="{pre}-room" class="layer"{size}></div><div id="{pre}-chars" class="layer"{size}></div></div>
    <div id="{pre}-cards" class="cards"{' data-v="1"' if tall else ''}></div>
    <div id="{pre}-cap" class="capbox"></div>
    <div id="{pre}-cover" class="cover" style="opacity:0"></div>
  </div>
  <script>
(function () {{
  const S = {js_json(S)};
  const tl = gsap.timeline({{ paused: true }});
  Stage.build(tl, S, "{pre}");
  window.__timelines["{pre}"] = tl;
}})();
  </script>
</template>
"""


def index_html(scenes, total):
    W, H = frame(scenes[0] if scenes else {})          # one frame size for the whole video
    hosts, t = [], 0.0
    for S in scenes:
        hosts.append(f'    <div id="{S["id"]}" data-composition-id="{S["id"]}" data-composition-src="compositions/{S["id"]}.html" '
                     f'data-start="{t:.3f}" data-duration="{S["dur"]:.3f}" data-track-index="1" data-track-kind="graphics" '
                     f'data-width="{W}" data-height="{H}"></div>')
        t += S["dur"]
    return f"""<!doctype html>
<html lang="en" data-resolution="{'portrait' if H > W else 'landscape'}">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width={W}, height={H}" />
    <script src="assets/gsap.min.js"></script>
    <script src="assets/kit.js"></script>
    <style>
      * {{ margin: 0; padding: 0; box-sizing: border-box; }}
      html, body {{ margin: 0; width: {W}px; height: {H}px; overflow: hidden; background: #000; }}
    </style>
  </head>
  <body>
    <div id="root" data-composition-id="main" data-start="0" data-duration="{total:.3f}" data-width="{W}" data-height="{H}">
{chr(10).join(hosts)}
    </div>
    <script>
      window.__timelines["main"] = gsap.timeline({{ paused: true }});
    </script>
  </body>
</html>
"""


def write_project(proj, scenes):
    """(Re)write the HyperFrames project in `proj`; returns the total length in seconds."""
    proj = Path(proj)
    (proj / "compositions").mkdir(parents=True, exist_ok=True)
    (proj / "assets").mkdir(exist_ok=True)
    shutil.copyfile(GSAP, proj / "assets" / "gsap.min.js")
    total = sum(S["dur"] for S in scenes)
    (proj / "assets" / "kit.js").write_text(kit_js(), encoding="utf-8")
    for S in scenes:
        (proj / "compositions" / f"{S['id']}.html").write_text(scene_html(S), encoding="utf-8")
    (proj / "index.html").write_text(index_html(scenes, total), encoding="utf-8")
    (proj / "hyperframes.json").write_text(json.dumps({
        "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
        "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
        "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
        "media": {"autoProxy": True}}, indent=2), encoding="utf-8")
    (proj / "meta.json").write_text(json.dumps({"id": proj.name, "name": proj.name,
                                                "createdAt": datetime.now().isoformat(timespec="seconds")}, indent=2), encoding="utf-8")
    return total
