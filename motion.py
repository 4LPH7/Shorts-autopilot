"""Motion graphics for the Shorts: captions that follow the spoken words, camera moves, one colour grade
and a ducked, loudness-matched audio mix. The helpers build text and ffmpeg filters, so they can be
tested without rendering; only render_final() runs ffmpeg.

The rules come from the anti-slideshow design laws of bangtutorial/bang-motion (MIT): motion must be
motivated, one accent colour, emphasis on few words, at most two text levels, and nothing inside the
screen areas the Shorts app covers. No code was copied; the ideas are encoded as checks (check_plan).
"""

import json
import random
import re
import shutil
from pathlib import Path

import footage

W, H, FPS = footage.W, footage.H, footage.FPS
SAFE_RIGHT, SAFE_BOTTOM = 910, 1536      # the Shorts buttons cover the right ~15% and the bottom ~20%
CAPTION_Y, CALLOUT_Y = 1180, 430
ACCENT = "#FFD60A"
FONT_FAMILY, FONT_FILE = "Be Vietnam Pro", "BeVietnamPro-Bold.ttf"
# A caption line should not end on these: they belong with the word that follows
FUNCTION_WORDS = frozenset("a an the and or but so to of in on at for with from by as is are was were be it its "
                           "this that these those your you my our their his her i we they he she not no".split())
NUMBER = re.compile(r"^[$€£]?\d[\d,.]*(%|[kKmMbBx])?$")


# ---- Word timing -----------------------------------------------------------------------

def clean_word(text):
    """A caption word without emoji or stray symbols (numbers like $5,000 and 10% survive)."""
    return re.sub(r"[^\w$€£%'’.,&+/-]", "", text).strip(".,")


def spread(start, end, tokens):
    """Give each token a slice of start..end in proportion to its length."""
    weights = [len(t) + 1 for t in tokens]
    total, t0, out = sum(weights), start, []
    for tok, wt in zip(tokens, weights):
        t1 = t0 + (end - start) * wt / total
        out.append((round(t0, 3), round(t1, 3), tok))
        t0 = t1
    return out


def parse_words(srt_text):
    """[(start, end, word)] from an SRT with one word per cue (what Edge voices give us). A cue that holds
    several words is split in proportion, so a sentence-level SRT also works (timing is then an estimate)."""
    out = []
    for s, e, txt in footage.parse_srt(srt_text):
        tokens = [w for w in (clean_word(t) for t in txt.split()) if w]
        out += spread(s, e, tokens) if len(tokens) > 1 else [(s, e, tokens[0])] if tokens else []
    return out


def group_phrases(words, max_words=3, max_chars=14, pause=0.3):
    """Short caption phrases: cut at spoken pauses, after max_words or max_chars, and never leave a
    function word dangling at the end of a phrase cut mid-sentence. [[(start, end, word), ...], ...]"""
    phrases, cur = [], []
    for w in words:
        if cur:
            gap = w[0] - cur[-1][1]
            chars = sum(len(x[2]) + 1 for x in cur) + len(w[2])
            if gap > pause or len(cur) >= max_words or chars > max_chars:
                carry = []
                if gap <= pause:
                    while len(cur) > 1 and cur[-1][2].lower() in FUNCTION_WORDS:
                        carry.insert(0, cur.pop())
                phrases.append(cur)
                cur = carry
        cur.append(w)
    if cur:
        phrases.append(cur)
    return phrases


# ---- What gets emphasised ----------------------------------------------------------------

def is_number(word):
    return bool(NUMBER.match(word))


def keyword_prompt(script, n=10):
    return ("Pick the words of this voiceover script worth showing in a highlight colour on screen: "
            f"at most {n} single words that carry the point (a surprising fact, the key object, a strong verb). "
            "Never pick filler words. Use the exact spelling from the script.\n\n"
            f"Script:\n{script}\n\nReply with only a JSON array of lowercase words, like [\"markup\", \"decoy\"].")


def parse_keywords(reply, limit=14):
    m = re.search(r"\[.*?\]", reply or "", re.S)
    try:
        items = json.loads(m.group(0)) if m else []
    except ValueError:
        items = []
    words = [clean_word(str(x)).lower() for x in items]
    return [w for w in words if w][:limit]


def pick_emphasis(phrases, keywords=(), cap=0.18, skip=()):
    """{(phrase index, word index)} shown in the accent colour: the chosen keywords and numbers, at most one
    per phrase and about `cap` of all words, so the colour stays rare enough to mean something.
    Words starting at a time in `skip` (numbers already shown big) are left alone."""
    wanted = {k.lower() for k in keywords}
    budget = max(1, int(sum(len(p) for p in phrases) * cap))
    picks = []
    for i, p in enumerate(phrases):
        hits = [j for j, (t, _, w) in enumerate(p) if (w.lower() in wanted or is_number(w)) and t not in skip]
        if hits:
            picks.append((i, max(hits, key=lambda j: (is_number(p[j][2]), len(p[j][2])))))
    picks.sort(key=lambda ij: (is_number(phrases[ij[0]][ij[1]][2]), len(phrases[ij[0]][ij[1]][2])), reverse=True)
    return set(picks[:budget])


def pick_callouts(words, limit=3, gap=6.0, hold=1.1):
    """Big on-screen numbers for spoken amounts, [(start, end, text)]. Only numbers really in the script,
    never invented. Money and percentages come first, then other numbers and years; at most `limit`, each at
    least `gap` seconds from the others, so they stay an event instead of wallpaper."""
    def weight(w):
        return 3 if re.search(r"[$€£]", w) else 2 if "%" in w else 1

    found = [c for c in words if re.search(r"[$€£%]|\d{2,}", c[2]) and is_number(c[2])]
    chosen = []
    for s, e, w in sorted(found, key=lambda c: (-weight(c[2]), c[0])):
        if len(chosen) < limit and all(abs(s - c[0]) >= gap for c in chosen):
            chosen.append((s, e + hold, w))
    return sorted(chosen)


# ---- ASS captions ----------------------------------------------------------------------

FONT_K = 0.651                           # libass draws ASS "Fontsize" F with an em of F * FONT_K pixels (measured, Be Vietnam Pro)
CAP_EM, NUM_EM = 92, 176                 # caption and big-number text, as real pixel em sizes
CAP_SIZE, NUM_SIZE = round(CAP_EM / FONT_K), round(NUM_EM / FONT_K)
MAX_LINE = 840                           # widest caption line: from the left margin to the Shorts buttons
TEXT_X = (70 + (W - 170)) // 2           # centre of the area left free by the Shorts buttons on the right
LEAD, HOLD, POP_MS, FADE_MS = 0.04, 0.2, 120, 70
DARK = "13101A"                          # text on an accent block
_FONT = {"path": None, "cache": {}}


def set_font(path):
    """Tell the layout which font file the captions use, so word widths can be measured exactly."""
    _FONT["path"], _FONT["cache"] = (str(path) if path else None), {}


def text_width(text, em=CAP_EM):
    """Width in pixels of `text` at an em of `em` pixels, measured with the real font (estimated without it)."""
    if _FONT["path"]:
        try:
            from PIL import ImageFont
            font = _FONT["cache"].get(em) or _FONT["cache"].setdefault(em, ImageFont.truetype(_FONT["path"], em))
            return float(font.getlength(text))
        except Exception:
            pass
    return len(text) * em * 0.58


def ass_rgb(hex_color):
    """#RRGGBB -> ASS BBGGRR (falls back to the default accent for anything malformed)."""
    h = hex_color.lstrip("#") if re.fullmatch(r"#?[0-9a-fA-F]{6}", hex_color or "") else ACCENT.lstrip("#")
    return (h[4:6] + h[2:4] + h[0:2]).upper()


def ass_time(t):
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def ass_header(accent=ACCENT):
    acc = ass_rgb(accent)
    fmt = ("Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
           "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
           "MarginL, MarginR, MarginV, Encoding")
    tail = "-1,0,0,0,100,100,0,0,1"
    return (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\n\n[V4+ Styles]\n"
            f"Format: {fmt}\n"
            f"Style: Cap,{FONT_FAMILY},{CAP_SIZE},&H00FFFFFF,&H00FFFFFF,&H00140E0A,&H70000000,{tail},8,4,5,70,170,0,1\n"
            f"Style: Ink,{FONT_FAMILY},{CAP_SIZE},&H00{DARK},&H00{DARK},&H00140E0A,&H00000000,{tail},0,0,5,70,170,0,1\n"
            f"Style: Num,{FONT_FAMILY},{NUM_SIZE},&H00{acc},&H00{acc},&H00140E0A,&H70000000,{tail},10,5,5,70,170,0,1\n\n"
            "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")


def pill_shape(w, h, r):
    """ASS drawing of a rounded rectangle from (0,0) to (w,h). libass aligns a drawing by its positive extent,
    so it is drawn in the positive quadrant and \\an5 then centres it on \\pos."""
    k = r * 0.5523
    return (f"m {r:.0f} 0 l {w - r:.0f} 0 b {w - r + k:.0f} 0 {w:.0f} {r - k:.0f} {w:.0f} {r:.0f} l {w:.0f} {h - r:.0f} "
            f"b {w:.0f} {h - r + k:.0f} {w - r + k:.0f} {h:.0f} {w - r:.0f} {h:.0f} l {r:.0f} {h:.0f} "
            f"b {r - k:.0f} {h:.0f} 0 {h - r + k:.0f} 0 {h - r:.0f} l 0 {r:.0f} b 0 {r - k:.0f} {r - k:.0f} 0 {r:.0f} 0")


def phrase_events(phrase, index, emphasis, accent, end_limit):
    """[(layer, start, end, style, text)]: every word is its own event, placed from measured widths, so a word can
    pop in without moving its neighbours. A keyword sits on a rounded accent block. A phrase too wide for the
    screen is shrunk, never wrapped."""
    widths = [text_width(w) for _, _, w in phrase]
    space = text_width(" ")
    total = sum(widths) + space * (len(phrase) - 1)
    fit = min(1.0, MAX_LINE / total)
    x = TEXT_X - total * fit / 2
    t_end = min(phrase[-1][1] + HOLD, end_limit)
    acc = ass_rgb(accent)
    out = []
    for j, (start, _, word) in enumerate(phrase):
        xc = x + widths[j] * fit / 2
        x += (widths[j] + space) * fit
        t0 = start - LEAD if j == 0 else start
        if t_end <= t0:
            continue
        hot = (index, j) in emphasis
        rest = round(100 * fit)
        big = round(rest * (1.22 if hot else 1.12))
        scale = f"\\fscx{big}\\fscy{big}\\t(0,{POP_MS},\\fscx{rest}\\fscy{rest})\\fad({FADE_MS},0)"
        if hot:
            w, h = widths[j] * fit + 56, CAP_EM * 1.12 * fit
            shape = pill_shape(w, h, h * 0.34)
            out.append((0, t0, t_end, "Ink", f"{{\\an5\\pos({xc:.0f},{CAPTION_Y + 4}){scale}\\1c&H{acc}&\\p1}}{shape}{{\\p0}}"))
        out.append((1, t0, t_end, "Ink" if hot else "Cap", f"{{\\an5\\pos({xc:.0f},{CAPTION_Y}){scale}\\blur1}}{word}"))
    return out


def build_ass(phrases, emphasis, callouts, total, accent=ACCENT):
    """The whole caption file. phrases/emphasis/callouts come from group_phrases/pick_emphasis/pick_callouts."""
    lines = [ass_header(accent)]
    for i, phrase in enumerate(phrases):
        limit = phrases[i + 1][0][0] - LEAD if i + 1 < len(phrases) else total
        for layer, t0, t1, style, text in phrase_events(phrase, i, emphasis, accent, limit):
            lines.append(f"Dialogue: {layer},{ass_time(t0)},{ass_time(t1)},{style},P{i},0,0,0,,{text}\n")
    for s, e, text in callouts:
        pop = f"\\an5\\pos({TEXT_X},{CALLOUT_Y})\\blur1\\fscx78\\fscy78\\t(0,160,\\fscx100\\fscy100)\\fad(120,240)"
        lines.append(f"Dialogue: 2,{ass_time(s - LEAD)},{ass_time(min(e, total))},Num,,0,0,0,,{{{pop}}}{text}\n")
    return "".join(lines)


# ---- Design-rule checks (the bang-motion laws, as mechanical tests) ------------------------

def check_ass(ass, moves=()):
    """Problems in a generated caption file; an empty list means every rule holds."""
    bad = []
    sizes = {m.group(1) for m in re.finditer(r"^Style: \w+,[^,]+,(\d+),", ass, re.M)}
    if len(sizes) > 2:
        bad.append(f"{len(sizes)} text sizes (max 2 levels)")
    accent = re.search(r"^Style: Num,[^,]+,\d+,&H00([0-9A-F]{6})", ass, re.M)
    colours = set(re.findall(r"\\1c&H([0-9A-F]{6})&", ass))
    if accent and colours - {accent.group(1)}:
        bad.append(f"more than one accent colour: {sorted(colours - {accent.group(1)})}")
    events = [m.groups() for m in re.finditer(r"^Dialogue: (\d+),([\d:.]+),([\d:.]+),(\w+),(P\d+)?,0,0,0,,(.*)$", ass, re.M)]
    words = [e for e in events if e[3] in ("Cap", "Ink") and "\\p1" not in e[5]]
    hot = sum(e[3] == "Ink" for e in words)
    if words and hot / len(words) > 0.25:
        bad.append(f"too many highlighted words: {hot}/{len(words)}")
    for e in words:
        if e[5].rstrip().endswith("."):
            bad.append(f"caption word ends with a period: {e[5][-12:]}")
    for x, y in re.findall(r"\\pos\((\d+),(\d+)\)", ass):
        if int(x) > SAFE_RIGHT or int(y) > SAFE_BOTTOM - 80:
            bad.append(f"text at ({x},{y}) is inside an area the Shorts app covers")
    spans = {}
    for _, a, b, _, name, _ in (e for e in events if e[3] in ("Cap", "Ink") and e[4]):
        lo, hi = spans.get(name, (a, b))
        spans[name] = (min(lo, a), max(hi, b))
    ordered = sorted(spans.values())
    for (a0, a1), (b0, _) in zip(ordered, ordered[1:]):
        if b0 < a1:
            bad.append(f"two caption lines on screen at once near {b0}")
            break
    if len(moves) >= 6 and sum(m in ("push", "pull") for m in moves) / len(moves) > 0.6:
        bad.append("camera moves are mostly zoom (the slideshow tell)")
    return bad


# ---- Camera, look and final mix ---------------------------------------------------------

AMOUNT = {"subtle": 0.045, "dynamic": 0.085}      # how far the picture zooms
PUNCH = {"subtle": 0.0, "dynamic": 0.03}          # quick settle at the start of every cut
PAN_BOOST = 1.5                                    # slides need a bit more room than zooms
# Zoom on every other cut at most: zoom on every cut is the slideshow tell
CYCLE = ("push", "left", "pull", "right", "push", "up", "pull", "hold")


def plan_moves(n, seed, level):
    """One camera move per cut, reproducible for a seed: never the same twice in a row, at most half zoom."""
    if level == "off" or n <= 0:
        return ["hold"] * max(n, 0)
    rng = random.Random(seed)
    start, mirror = rng.randrange(len(CYCLE)), rng.random() < 0.5
    flip = {"left": "right", "right": "left"}
    moves = [CYCLE[(start + i) % len(CYCLE)] for i in range(n)]
    return [flip.get(m, m) if mirror else m for m in moves]


def camera_filter(kind, level, seconds, fps=FPS):
    """ffmpeg filter that moves a W x H picture like a camera: an eased push, pull or slide, or None (hold).
    `perspective` samples with sub-pixel cubic interpolation: measured jitter 0.01 px per frame, where
    crop/zoompan jump by about 0.5 px (visible as shimmer on fine detail)."""
    if level not in AMOUNT or kind == "hold":
        return None
    amt, punch = AMOUNT[level], PUNCH[level]
    p = f"min(on/{max(1, round(seconds * fps) - 1)},1)"
    ease = f"({p}*{p}*(3-2*{p}))"
    settle = f"+{punch}*exp(-on/5)" if punch else ""
    if kind == "push":
        z = f"(1+{amt}*{ease}{settle})"
    elif kind == "pull":
        z = f"(1+{amt}*(1-{ease}){settle})"
    else:
        z = f"(1+{amt * PAN_BOOST}{settle})"
    wv, hv = f"({W}/{z})", f"({H}/{z})"
    sx, sy = {"left": (f"(1-{ease})", "0.5"), "right": (ease, "0.5"), "up": ("0.5", f"(1-{ease})")}.get(kind, ("0.5", "0.5"))
    x, y = f"(({W}-{wv})*{sx})", f"(({H}-{hv})*{sy})"
    return (f"perspective=x0='{x}':y0='{y}':x1='{x}+{wv}':y1='{y}':x2='{x}':y2='{y}+{hv}':"
            f"x3='{x}+{wv}':y3='{y}+{hv}':sense=source:interpolation=cubic:eval=frame")


LOOKS_FILTER = {
    "clean": "eq=contrast=1.04:saturation=1.06,unsharp=luma_msize_x=5:luma_msize_y=5:luma_amount=0.45",
    "cinematic": ("eq=contrast=1.07:saturation=1.06,colorbalance=rs=-0.02:bs=0.03:rh=0.03:bh=-0.025,"
                  "vignette=angle=PI/2.3,noise=alls=3:allf=t"),
    "warm": ("eq=contrast=1.04:saturation=1.08,colorbalance=rs=0.03:gs=0.01:bs=-0.03:rm=0.03:bm=-0.025:rh=0.025:bh=-0.03,"
             "vignette=angle=PI/2.4"),
}


LOUD = "I=-14:TP=-1.5:LRA=9"
MUSIC_IN, MUSIC_OUT = 0.5, 1.8          # seconds the music takes to fade in at the start and out at the end


def audio_graph(has_music, music_volume, measure=False, measured=None, has_sfx=False, seconds=0.0):
    """Inputs 1 = voice, then sound effects (if any), then music (if any) -> [aout]: stereo 48 kHz, the music ducked
    under the voice (sidechain) and faded in and out, the whole mix matched to YouTube's -14 LUFS so every video is
    equally loud and the voice always wins. measure=True ends in a loudnorm analysis (JSON on stderr); `measured`
    (that analysis) makes the real pass exact and linear; with neither, loudnorm adapts in one pass."""
    voice = "[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0"          # the voice is mono, the music stays stereo
    parts, mix = [f"{voice},asplit=2[vo][sc]" if has_music else f"{voice}[vo]"], ["[vo]"]
    if has_sfx:
        parts.append("[2:a]aresample=48000,pan=stereo|c0=c0|c1=c0[fx]")
        mix.append("[fx]")
    if has_music:
        vol = round(float(music_volume) * 1.35, 3)      # ducking takes some back, so start a little louder
        fades = f"afade=t=in:d={MUSIC_IN}"
        if seconds:
            fades += f",afade=t=out:st={max(0.0, seconds - MUSIC_OUT):.2f}:d={MUSIC_OUT}"
        parts.append(f"[{3 if has_sfx else 2}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol},{fades}[mus]")
        parts.append("[mus][sc]sidechaincompress=threshold=0.03:ratio=9:attack=8:release=350[duck]")
        mix.append("[duck]")
    mixer = (f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0:dropout_transition=0"
             if len(mix) > 1 else "[vo]anull")
    if measure:
        norm = f"loudnorm={LOUD}:print_format=json"
    elif measured:
        norm = (f"loudnorm={LOUD}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
                f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
                f"offset={measured['target_offset']}:linear=true,aresample=48000")
    else:
        norm = f"loudnorm={LOUD},aresample=48000"
    return ";".join(parts) + f";{mixer},{norm}[aout]"


def audio_inputs(audio, sfx, music):
    """ffmpeg input arguments in the order audio_graph expects: picture, voice, sound effects, music."""
    args = ["-i", "combined.mp4", "-i", Path(audio).name]           # relative to the work folder
    for extra in (sfx, music):
        if extra:
            args += ["-i", str(Path(extra).resolve())]
    return args


def measure_loudness(work, audio, sfx, music, music_volume, seconds):
    """loudnorm's reading of the finished audio mix (a quick audio-only pass), or None if it can't be read."""
    cmd = [footage.ffmpeg_exe(), "-hide_banner", "-nostats"] + audio_inputs(audio, sfx, music)
    cmd += ["-filter_complex", audio_graph(bool(music), music_volume, measure=True, has_sfx=bool(sfx), seconds=seconds),
            "-map", "[aout]", "-t", f"{seconds:.2f}", "-f", "null", "-"]
    found = re.search(r'\{[^{}]*"input_i"[^{}]*\}', footage.run(cmd, timeout=300, cwd=work).stderr, re.S)
    try:
        data = json.loads(found.group(0))
        if all(abs(float(data[k])) < 1000 for k in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")):
            return data
    except (AttributeError, KeyError, ValueError):
        pass
    return None


def make_plan(words_srt, total, keywords=(), accent=ACCENT, font_file=None):
    """(ass text, summary) for a video from its word timing. font_file lets the layout measure the real words."""
    set_font(font_file)
    words = parse_words(words_srt)
    phrases = group_phrases(words)
    callouts = pick_callouts(words)
    shown_big = {c[0] for c in callouts}       # a number already shown big is not highlighted a second time
    emphasis = pick_emphasis(phrases, keywords, skip=shown_big)
    ass = build_ass(phrases, emphasis, callouts, total, accent)
    return ass, {"words": len(words), "phrases": len(phrases), "highlighted": len(emphasis),
                 "numbers": [c[2] for c in callouts], "callouts": [list(c) for c in callouts], "keywords": list(keywords)}


def voice_file(work):
    """The narration of a video: audio.wav for videos made with the studio narration, audio.mp3 for older ones."""
    work = Path(work)
    return work / "audio.wav" if (work / "audio.wav").exists() else work / "audio.mp3"


def render_final(work, ass_text, font_file, out_name, look="clean", music=None, music_volume=0.2, sfx=None):
    """Picture (combined.mp4) + voice + captions + look + sound effects + ducked music -> work/out_name, in one
    ffmpeg pass. Raises if ffmpeg fails or the result is not as long as the voiceover."""
    work = Path(work)
    (work / "fonts").mkdir(exist_ok=True)
    shutil.copyfile(font_file, work / "fonts" / FONT_FILE)
    (work / "captions.ass").write_text(ass_text, encoding="utf-8")
    audio = voice_file(work)
    seconds = footage.probe(audio)[0]
    measured = measure_loudness(work, audio, sfx, music, music_volume, seconds)
    graph = (f"[0:v]{LOOKS_FILTER.get(look, LOOKS_FILTER['clean'])},ass=captions.ass:fontsdir=fonts[v];"
             + audio_graph(bool(music), music_volume, measured=measured, has_sfx=bool(sfx), seconds=seconds))
    cmd = [footage.ffmpeg_exe(), "-y", "-v", "error"] + audio_inputs(audio, sfx, music)
    cmd += ["-filter_complex", graph, "-map", "[v]", "-map", "[aout]", "-t", f"{seconds:.2f}", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-maxrate", "14M", "-bufsize", "28M",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", out_name]
    r = footage.run(cmd, timeout=1800, cwd=work)
    out = work / out_name
    if r.returncode or not out.exists():
        raise RuntimeError(f"final render failed: {r.stderr[-400:]}")
    got = footage.probe(out)[0]
    if abs(got - seconds) > 0.35:
        raise RuntimeError(f"final video is {got:.1f}s but the voiceover is {seconds:.1f}s")
    return out


# ---- Self-test (called by daily_shorts --self-test) ---------------------------------------

def self_test(font_file=None):
    srt = "".join(f"{i}\n00:00:{a} --> 00:00:{b}\n{w}\n\n" for i, (a, b, w) in enumerate((
        ("00,000", "00,300", "You're"), ("00,300", "00,600", "losing"), ("00,600", "01,700", "$5,000"),
        ("01,700", "01,800", "a"), ("01,800", "02,200", "year"), ("03,000", "03,300", "Here's"),
        ("03,300", "03,800", "why")), 1))
    words = parse_words(srt)
    assert [w[2] for w in words] == ["You're", "losing", "$5,000", "a", "year", "Here's", "why"]
    assert clean_word("\U0001F48Dring.") == "ring" and clean_word("10%") == "10%" and clean_word("...") == ""
    est = parse_words("1\n00:00:00,000 --> 00:00:02,000\nOne two three four\n")      # sentence timing is spread
    assert len(est) == 4 and est[0][0] == 0 and abs(est[-1][1] - 2.0) < 0.01
    phrases = group_phrases(words)
    assert [[w[2] for w in p] for p in phrases] == [["You're", "losing"], ["$5,000", "a", "year"], ["Here's", "why"]]
    mid = group_phrases([(i * 0.3, i * 0.3 + 0.25, w) for i, w in enumerate("we sold the best of it all today".split())])
    assert all(p[-1][2] not in FUNCTION_WORDS for p in mid[:-1]), mid          # no line ends on "the" or "of"
    assert pick_emphasis(phrases, ["why"]) == {(1, 0)} and pick_emphasis(phrases, ["why"], skip={0.6}) == {(2, 1)}
    assert [c[2] for c in pick_callouts([(0, 1, "3"), (2, 3, "10%"), (4, 5, "$20"), (11, 12, "1,947")])] == ["$20", "1,947"]
    assert [c[2] for c in pick_callouts([(0, 1, "500"), (7, 8, "80%"), (14, 15, "10%"), (21, 22, "$800"), (28, 29, "20%")])] \
        == ["80%", "10%", "$800"]
    assert parse_keywords('Sure! ["Markup", "decoy", 7]') == ["markup", "decoy", "7"] and parse_keywords("nope") == []
    ass, info = make_plan(srt, 4.0, ["year"])
    assert info["numbers"] == ["$5,000"] and info["highlighted"] == 1, info      # the big number is not highlighted twice
    assert check_ass(ass, plan_moves(8, "s", "subtle")) == [], check_ass(ass)
    assert check_ass(ass.replace("\\1c&H0AD6FF&", "\\1c&H0000FF&", 1)), "a second accent colour must be flagged"
    assert check_ass(ass + "Dialogue: 0,0:00:01.00,0:00:02.00,Cap,,0,0,0,,{\\an5\\pos(1000,1700)}x\n"), "unsafe zone flagged"
    assert check_ass(ass, ["push", "pull"] * 4), "zoom-only motion must be flagged"
    for n in range(1, 41):
        m = plan_moves(n, "seed", "subtle")
        assert len(m) == n and all(a != b for a, b in zip(m, m[1:])), m
        assert n < 6 or sum(k in ("push", "pull") for k in m) / n <= 0.6, m
    assert plan_moves(5, "a", "off") == ["hold"] * 5 and plan_moves(9, "x", "dynamic") == plan_moves(9, "x", "dynamic")
    assert camera_filter("hold", "subtle", 3) is None and camera_filter("push", "off", 3) is None
    assert "zoompan" not in camera_filter("push", "dynamic", 3)
    assert ass_rgb("#FFD60A") == "0AD6FF" and ass_rgb("nonsense") == "0AD6FF" and ass_time(3661.5) == "1:01:01.50"

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:                     # every camera move and look through real ffmpeg
        tmp = Path(tmp)
        for level in AMOUNT:
            for kind in CYCLE:
                f = camera_filter(kind, level, 1.0)
                if f:
                    r = footage.run([footage.ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:d=0.4",
                                     "-vf", f, "-frames:v", "5", "-f", "null", "-"], timeout=60)
                    assert r.returncode == 0, (kind, level, r.stderr[-300:])
        if not font_file:
            print("(caption render check skipped: set MPT_DIR so the font can be found)")
            return
        run = lambda *a: footage.run([footage.ffmpeg_exe(), "-y", "-v", "error", *a])          # noqa: E731
        assert run("-f", "lavfi", "-i", f"testsrc2=size={W}x{H}:rate={FPS}:d=2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                   str(tmp / "combined.mp4")).returncode == 0
        for name, secs in (("audio.mp3", 2), ("music.mp3", 3)):
            assert run("-f", "lavfi", "-i", f"sine=frequency=330:duration={secs}", str(tmp / name)).returncode == 0
        for look in LOOKS_FILTER:
            for music in (None, tmp / "music.mp3"):
                out = render_final(tmp, ass, font_file, f"o-{look}.mp4", look, music, 0.2)
                dur, w, h = footage.probe(out)
                assert (w, h) == (W, H) and abs(dur - 2.0) < 0.35, (look, dur, w, h)
                assert "48000 Hz, stereo" in footage.run([footage.ffmpeg_exe(), "-hide_banner", "-i", str(out)]).stderr
        assert run("-f", "lavfi", "-i", "sine=frequency=900:duration=1", str(tmp / "sfx.wav")).returncode == 0
        assert measure_loudness(tmp, tmp / "audio.mp3", tmp / "sfx.wav", tmp / "music.mp3", 0.2, 2.0)["input_i"], \
            "loudness analysis of voice + effects + music must be readable"
        out = render_final(tmp, ass, font_file, "o-sfx.mp4", "clean", tmp / "music.mp3", 0.2, sfx=tmp / "sfx.wav")
        assert abs(footage.probe(out)[0] - 2.0) < 0.35 and "stereo" in footage.run([footage.ffmpeg_exe(), "-hide_banner", "-i", str(out)]).stderr
        assert voice_file(tmp).name == "audio.mp3"
        graph = audio_graph(True, 0.2, has_sfx=True, seconds=58)
        assert "[3:a]" in graph and "[2:a]" in graph and "afade=t=out:st=56.20" in graph and "amix=inputs=3" in graph, graph
        assert "[2:a]" in audio_graph(True, 0.2) and "amix=inputs=2" in audio_graph(True, 0.2) and "anull" in audio_graph(False, 0.2)
