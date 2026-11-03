"""Turns scene descriptions into a HyperFrames project: one sub-composition per scene (the kit in longform/kit draws and
animates it) mounted by a root index.html. Pure file generation, no rendering: longform.py runs the renderer.

A scene description S (what longform.py computes from the screenplay and the voice timings):
    id, dur, cover ("cut" | "fade" | "wipe"), room {kind, tone}, cast [{id, look, x, y, face, start, mood}],
    events [{do, t, ...}], caps [{t, d, text, who, color}], clips [{t, d, src}] (optional generated footage)."""

import json
import shutil
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
KIT = HERE / "longform" / "kit"
GSAP = HERE / "longform" / "node_modules" / "gsap" / "dist" / "gsap.min.js"
KIT_JS = ("rooms.js", "rig.js", "acts.js", "cards.js", "stage.js")
W, H = 1920, 1080


def kit_js():
    return "\n".join((KIT / name).read_text(encoding="utf-8") for name in KIT_JS)


def js_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def scene_html(S):
    pre = S["id"]
    clips = "".join(
        f'<video id="{pre}-v{i}" class="clip" src="{c["src"]}" data-start="{c["t"]:.3f}" data-duration="{c["d"]:.3f}" '
        f'data-track-index="2" muted playsinline style="position:absolute;left:0;top:0;width:{W}px;height:{H}px;object-fit:cover;z-index:5"></video>'
        for i, c in enumerate(S.get("clips") or []))
    return f"""<template>
  <style>{(KIT / "base.css").read_text(encoding="utf-8")}</style>
  <div id="root" data-composition-id="{pre}" data-width="{W}" data-height="{H}">
    <div id="{pre}-cam" class="cam"><div id="{pre}-room" class="layer"></div><div id="{pre}-chars" class="layer"></div></div>
    {clips}
    <div id="{pre}-cards" class="cards"></div>
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
    hosts, t = [], 0.0
    for S in scenes:
        hosts.append(f'    <div id="{S["id"]}" data-composition-id="{S["id"]}" data-composition-src="compositions/{S["id"]}.html" '
                     f'data-start="{t:.3f}" data-duration="{S["dur"]:.3f}" data-track-index="1" data-track-kind="graphics" '
                     f'data-width="{W}" data-height="{H}"></div>')
        t += S["dur"]
    return f"""<!doctype html>
<html lang="en" data-resolution="landscape">
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
