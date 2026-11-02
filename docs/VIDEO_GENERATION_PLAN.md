# Shorts Autopilot video generation upgrade plan

**Research snapshot:** 2026-11-02  
**Status:** Plan, plus two steps built on 2026-11-02: the voice and script-length settings, and the motion graphics layer (`motion.py`, see below). No other dependencies installed, model weights downloaded or paid API calls made.

## Recommendation

Keep Shorts Autopilot's Python desktop app, scheduler, review queue, approval step, and upload flow. Improve the video pipeline in layers:

1. Use the existing MoneyPrinterTurbo integration more fully for longer scripts, voice options, pauses, and timed captions.
2. Add a source-backed script and scene plan, with an approval checkpoint before rendering.
3. Add Kokoro as an optional local voice provider and align captions to the finished voice audio.
4. Add HyperFrames as an optional renderer for a distinctive, repeatable editorial-motion style; retain MoneyPrinterTurbo for the current stock-footage path.
5. Add local or hosted AI-generated B-roll only as an opt-in per-scene source after a cost, hardware, and license preflight.

This should improve quality without replacing the working automation around render review and publishing. The default should remain low-cost, resumable, and human-approved.

## Decisions in force

- **Voice speed 1.05** (default). It is lively without rushing. Set in `daily_shorts.py` and `settings.json`.
- **Script length 150–165 words**, which should give **63–69 seconds** of narration at 1.05. This is an estimate from the 1.12 render (55.3 s): the logged voiceover length on the first real render at 1.05 is the check.
- **MoneyPrinterTurbo stays the backbone for scripts, footage search and the fallback voiceover.** Narration now comes from the studio narration step (Microsoft neural voices by default, Kokoro optional); HyperFrames and any paid generation remain optional and off by default.
- **Human approval before every upload.** Nothing is published straight after rendering.

## Motion graphics layer (built 2026-11-02)

Request: take the best motion-graphics ideas from [bang-motion](https://github.com/bangtutorial/bang-motion) and [Trendshift](https://trendshift.io/) so the videos look designed rather than generated.

| Project | Licence | How it was used |
|---|---|---|
| bang-motion (976 stars) | MIT | Ideas only so far: its design laws (motion must be motivated, one accent colour, few emphasised lines, at most two text levels, no zoom-only motion, safe zones). They are encoded as mechanical checks in `motion.check_ass`. Keep its copyright notice if any text or code is ever ported. |
| HyperFrames | Apache-2.0 | Still the Phase 4 renderer for fully designed scenes. Not needed for the stock-footage path. |
| kinetograph (437), code-video-showcase (266), editing-gameplay-montages (73), reel-studio (92), space-handdrawn-motion-video (39), geneva (27) | none published | Read for ideas only. Without a licence, no code may be copied. |

**Built in `motion.py`** (ffmpeg and libass only, no new dependency):

- Captions timed to each spoken word, from Edge TTS word boundaries (estimated from sentence timing if those are missing). Two or three words per line, never ending on a function word, no emoji.
- One accent colour for a few AI-chosen keywords and numbers (about one word in six), and a large pop-up for spoken amounts that really are in the script.
- A different eased camera move per cut, at most every other cut a zoom. Measured on a still frame: `perspective` with cubic sampling jitters 0.006–0.009 px per frame, `zoompan` on a 2x upscale 0.41–0.53 px, an integer crop 0.46 px, so `perspective` is used.
- One colour grade over all clips (clean, cinematic, warm), and music ducked under the voice (sidechain) with the mix matched to -14 LUFS, all in a single final ffmpeg pass.
- Safe zones: nothing in the bottom 20% or right 15% of the frame.
- Fallbacks: estimated word timing, then MoneyPrinterTurbo's own captions. Older videos and the Motion = Off setting keep the old path.

**Deliberately not built:** cross-dissolve transitions (hard cuts with a camera settle are the Shorts norm, and xfade would shift the timeline), a progress bar, count-up numbers (digits change the line width), per-word scale pops (they re-centre the line), emoji or sticker overlays, and AI-generated B-roll.

**Open choice:** the defaults are the safest ones (Motion = Subtle, Look = Clean). Watch two or three new videos before switching to Cinematic or Dynamic.

## Production upgrade: research and decisions (2026-11-02, second pass)

Request: research ghost-editor, an ffmpeg skill, claude-shorts, MotionClone, motion-skills, yt-dlp, Whisper, the awesome-claude-video-skills list, Three.js skills and HyperFrames, and use what fits to lift video quality and narration. Each was checked on GitHub (README, licence, activity) and, where installed, in its own skill files. This PC has no NVIDIA GPU (Intel Iris Xe), 15.6 GB RAM and 20 threads, which rules out anything GPU-bound.

| Tool | What it actually is | Licence | Decision |
|---|---|---|---|
| [ghost-editor](https://github.com/kurbaitaev/ghost-editor) | A Claude Code skill that edits **talking-head** reels; needs a Mac with Apple silicon, Whisper, OpenCV and a Gemini key for its B-roll check. Ships a CC0 meme-sound pack. | MIT | Ideas only (keyword on a coloured block, sound-effect discipline). It needs a camera take, so it can't drive a faceless channel. |
| [claude-shorts](https://github.com/AgriciDaniel/claude-shorts) and [Ansub/claude-shorts](https://github.com/Ansub/claude-shorts) | Cut shorts out of long videos (faster-whisper, Remotion captions, GPU recommended, WSL on Windows). | none stated / other | Ideas only: word-level highlight captions, snapping cuts to word boundaries. |
| [claude-faceless-shorts-creator](https://github.com/hassancs91/claude-faceless-shorts-creator) | A faceless-Shorts factory (Remotion, ElevenLabs). | none stated | Ideas: a beat grammar (hook, setup, reveal, twist, loop), frame 0 as the thumbnail, an SFX cue sheet, checking frames at phone scale. |
| [iart-ai/motion-skills](https://github.com/iart-ai/motion-skills) | 56 agent skills in 19 packs for motion graphics (including code-made music). | MIT (README) | Craft reference for me, not a runtime dependency. |
| [MotionClone (blixvip)](https://github.com/blixvip/MotionClone) | Rebuilds *someone else's* reference video as a HyperFrames project through a Codex/ChatGPT login. | none stated | **Not used.** It copies other people's videos and needs another account. |
| MotionClone (LPengYang, ICLR 2025) | Diffusion-based motion transfer. | n/a | **Not used.** GPU-only, and AI-generated video is what this channel avoids. |
| [HyperFrames](https://github.com/heygen-com/hyperframes) | HTML to MP4 through headless Chrome and ffmpeg, about 450 ready blocks. Its `media-use` skill documents free local Kokoro voice, Whisper transcripts and sound effects. | Apache-2.0 | **Approach adopted, renderer deferred.** Chrome-based frame capture is slow without a GPU (the awesome list's benchmark: 23.5 minutes for a 15 s film, authoring included); the current ffmpeg and libass pass finishes a minute of video in about 30 s. Revisit for rich title cards. |
| Kokoro-82M with kokoro-onnx | A small open text-to-speech model with 54 voices; runs on the CPU. | Apache-2.0 / MIT | **Used** as a voice engine (offline). |
| Whisper via faster-whisper | Speech recognition with word timestamps. | MIT | **Used** for word timing with Kokoro and to check every sentence against the script. |
| edge-tts called directly | Microsoft's free neural voices, including the newest Multilingual ones, with word boundaries. | LGPL-3.0 | **Used.** MoneyPrinterTurbo's wrapper timed out on those voices; direct calls work for all 16 tested. |
| Three.js skills ([CloudAI-X](https://github.com/CloudAI-X/threejs-skills), wolffe) | Agent skills for 3D and WebGL. | none stated / MIT | **Not used.** WebGL in headless Chrome would run on software rendering here, and 3D adds little to a stock-footage explainer. |
| [ffmpeg skill (n0an)](https://github.com/n0an/ffmpeg-skill) | Recipes for ffmpeg commands. | n/a | ffmpeg is already the core; the new filter graphs are tested here rather than copied. |
| yt-dlp | Downloads video and audio from YouTube and other sites. | Unlicense | **Not used for other people's content.** Reusing it is how Content ID claims and strikes happen (the reason for SAFETY.md) and it breaches YouTube's terms. It remains fine for your own uploads. |
| [awesome-claude-video-skills](https://github.com/zhuyansen/awesome-claude-video-skills) | A curated, security-graded list of 401 repos. | other | Used as the map of the field. |

**Sound effects.** HyperFrames bundles 21 effects from the Pixabay Content License, and ghost-editor ships CC0 ones. Both are allowed for commercial use, but stock audio libraries are a known source of false Content ID claims, and a claim already cost one video. The effects are therefore synthesised in `sound.py` from noise and sine waves: nothing is downloaded and nobody else holds rights to them.

**What was built from this** (see the README for how it works): studio narration (`narrate.py`, `voices.py`), voice mastering and synthesised sound effects (`sound.py`), per-word captions with keyword blocks (`motion.py`), automatic quality checks (`qa.py`), and an audition of ten voices. The Phase 3 item "Kokoro as an optional local voice provider with captions aligned to the finished audio" below is therefore done.

## Current project baseline

- `daily_shorts.py` asks MoneyPrinterTurbo to write a script, sets a vertical 9:16 video, voice, rate, subtitles, and music, then puts finished videos into the existing review queue.
- `footage.py` already supports Pixabay, Coverr, and a user-managed local clip library. It handles clip sizing and source credits.
- The desktop app already has Settings, Review, approval/rejection, music changes, scheduling, and upload management.
- The project therefore already has topic-to-video automation. Its largest opportunities are richer scene direction, a recognizable visual identity, more natural voice, exact narration/caption timing, and stronger automated render checks.

## Research scope and ranking method

The [Trendshift AI video topic](https://trendshift.io/topics/ai-video) was reviewed as a discovery list, then candidate repositories were checked against their own READMEs, metadata, and license pages. The ranking below is by **fit and implementation value for this Windows/Python Shorts Autopilot**, not by stars alone. Star counts are a snapshot and change over time.

The supplied [4LPH7 GitHub Stars page](https://github.com/4LPH7?tab=stars) was blocked by the research browser's robots policy. The connected GitHub repository tool does not expose user-star-list pages. I did not bypass that restriction, so this report does not claim to have audited the contents of that Stars page.

## Ranked repository shortlist

| Rank | Repository | Fit | Worth taking | Integration decision |
|---:|---|---:|---|---|
| 1 | [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) — 137k stars, MIT | 9.7/10 | This is already the project's engine. Current upstream advertises multiple script/LLM providers, stock and generated footage, Edge/Azure/Kokoro/ElevenLabs and other TTS options, voice samples, word-by-word captions, pause markers, music, batch variants, and CLI/API/WebUI workflows. | **Adopt selected upstream features after checking the installed MPT version.** Do not duplicate its full pipeline. Prefer its existing media and settings interfaces where stable. |
| 2 | [HyperFrames](https://github.com/heygen-com/hyperframes) — 77k stars, Apache-2.0 | 9.3/10 | HTML/CSS/JavaScript video compositions, editable project files, animation adapters, captions/overlays, preview, lint, and deterministic frame-by-frame rendering. Strong fit for designed explainers, charts, typography, and repeatable branded scenes. | **Add as an optional renderer.** Call its CLI from Python with a validated scene manifest and keep the current MPT renderer as fallback. It requires Node.js 22+ and FFmpeg. |
| 3 | [Vibe Knowledge](https://github.com/andyhuo520/vibe-knowledge) — 238 stars, MIT | 8.8/10 | Research-to-script-to-voice-to-code-render flow; source references for each sentence; many coherent visual style packs; QA and publishing bundle; optional generated motion shots. Its examples demonstrate roughly 1–3 minute explainers and a free base style. | **Port the workflow ideas.** Use per-claim source notes, style packs, and a base/enhanced visual tier. Its public samples are Chinese and its repository is an agent skill, so do not depend on its whole runtime. |
| 4 | [AI Video Factory](https://github.com/ersinkoc/AI-Video-Factory) — 105 stars, MIT | 8.6/10 | Topic-to-story stages, explicit script/storyboard approvals, resumable/idempotent work, four motion modes, character/style libraries, blind visual review, provider routing, content-hash caching, and cost estimates before paid calls. | **Port the workflow architecture, not the app.** Its Claude-agent, web-Studio, Remotion, and paid-provider stack would be a large rewrite here. |
| 5 | [Kokoro](https://github.com/hexgrad/kokoro) — 9.9k stars, Apache-2.0 | 8.4/10 | Open-weight 82M TTS model with a local Python pipeline; useful for voice auditions without a per-video voice API bill. | **Add an optional local TTS adapter and voice audition.** Listen to blind A/B samples before selecting a default; model quality is subjective, and model/voice asset terms should be checked separately. |
| 6 | [paper-reel](https://github.com/haiderfarooq3/paper-reel) — 77 stars, MIT | 8.1/10 | Uses the voice as the timeline clock, aligns words locally, triggers props on spoken words, and renders expressive word-level captions. Clear example of a complete visual style. | **Port timing and style patterns.** Its documented setup is macOS-specific, so adapt the ideas to Windows rather than installing it as a runtime dependency. |
| 7 | [ComfyUI](https://github.com/Comfy-Org/ComfyUI) + [WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper) — 144k + 6.8k stars; GPL-3.0 app / Apache-2.0 wrapper | 7.4/10 | Local model orchestration and image/video conditioning for bespoke B-roll; can offer a local alternative to stock footage for a few important shots. | **Optional, experimental visual provider only.** Custom nodes, model weights, VRAM, installs, and per-model licenses need separate review. Never make it required for ordinary renders. |
| 8 | [Kinoloom](https://github.com/harlixay7/Kinoloom) — 21 stars, MIT | 6.9/10 | Local Windows film workflow, character/location continuity, short-clip chaining, and shot QA. The author reports testing on one RTX 3070 8 GB machine with 64 GB RAM. | **Use as a benchmark/reference.** It is a one-machine film studio with separately supplied weights and model-specific terms, which is more than this Shorts pipeline needs. |
| 9 | [Pika H3 Flex](https://github.com/Pika-Labs/Pika-H3-Flex) — 463 stars; model weights use the MiniMax H3 Community License | 6.6/10 | Reference-guided video, six-step generation, synchronized audio, native 480p/768p, and higher-resolution hosted API options. Could make a few hero shots more cinematic. | **Hold for a later provider trial.** Check the model agreement, compute needs, API prices, and output rights before offering it in Settings. |
| 10 | [Remotion](https://github.com/remotion-dev/remotion) — 69.9k stars, Remotion License | 6.3/10 | Mature React-based programmatic video rendering and many examples. Good compositional control, but it overlaps with HyperFrames for this use case. | **Do not choose as the first renderer.** Remotion is source-available under its own license. Individuals and small teams may qualify for free use; larger automated-video use can require a company plan, with current automator pricing at $0.01/render and a $100/month minimum. Recheck the current terms before use. |
| 11 | [SenseNova 6.8 Code2Video](https://github.com/OpenSenseNova/SenseNova-6.8-Code2Video) — 321 stars; model has 27B parameters | 5.9/10 | Code-driven motion graphics make exact text, charts, coordinates, and timing editable and reproducible. | **Research reference only.** Use the ideas for precise graphics; do not make a 27B model a production dependency. Confirm model license and hardware requirements before any trial. |
| 12 | [Digital Human Koubo](https://github.com/andyhuo520/digital-human-koubo) — 1.7k stars, MIT | 5.4/10 | Talking-head avatar, lip sync, voice cleanup, captions, and packaging components. | **Out of the default path.** This project currently targets faceless explainers; an avatar can make videos feel more synthetic, and its examples use paid Renoise credits. Revisit only if a presenter format is deliberately chosen. |

### Trendshift entries not worth integrating now

The topic page also surfaces research demonstrations such as L3G-World, Looking-Ahead, Hy-Nomas, WorldCast, and SolarRenderer; narrowly scoped H3 workflow nodes; an adult video generator; a SaaS starter built around hosted generation credits; and an unofficial Mac client for paid generation services. They may be interesting experiments, but they do not improve the current pipeline enough to justify maintenance, licensing, or provider coupling. Re-evaluate them only if a future format specifically needs their capability.

## Features worth bringing into Shorts Autopilot

### 1. A source-backed story plan

Before TTS or footage selection, create a short episode plan containing:

- the viewer question and one-sentence answer;
- a human opening moment, story beats, reveal, and useful ending;
- sources attached to factual claims, plus a flag for claims needing human verification;
- a scene list with narration, visual intent, on-screen text, and candidate media source;
- a selected style pack and target duration.

Require approval of script and storyboard before paid or slow media generation. This borrows the sourcing and approval ideas from Vibe Knowledge and AI Video Factory while preserving the current Review queue for the final MP4.

### 2. Voice-first timing and natural delivery

- Support the existing Edge voice plus optional Kokoro/local or user-recorded narration.
- Add preview clips so the user can compare voices and rates before rendering a full episode.
- Default target: **63–69 seconds of measured speech** (150–165 words at speed 1.05). Accept 60–75 seconds. Outside that range, revise the script once rather than padding it. Word count is only a draft guide; the generated audio duration decides.
- Align captions and scene changes to the final narration, using the existing MPT timing features where available or a local transcription aligner such as the `whisper.cpp` pattern used by paper-reel.
- Preserve pauses, short spoken phrases, contractions, and sentence-level emphasis. Avoid forcing every script into the same cadence.

### 3. A distinctive visual identity

Start with three user-selectable modes:

1. **Stock documentary:** current Pixabay/Coverr/local library flow, with better scene-to-script matching.
2. **Editorial motion:** HyperFrames templates for kinetic typography, simple diagrams, source cards, timelines, and highlight overlays over real footage.
3. **Hybrid:** mostly stock/local media, with a small number of opt-in generated clips for the most important scenes.

Create a small set of coherent styles rather than hundreds of loosely different presets. For this niche, start with an editorial collage/motion-graphics style that can show real examples and precise text. Use generated footage as illustration, not evidence, and label it where viewers could mistake it for documentary footage.

### 4. Resumable jobs and honest cost controls

Record a versioned episode manifest and save each finished stage atomically. Cache voice, aligned captions, selected clips, and renders by input/settings hash. A failed job should resume from its last valid artifact rather than repeat paid calls.

Keep provider credentials in the existing settings/config system, never in episode manifests. Hosted video generation stays disabled by default. Before a paid call, show provider, clip count, estimated cost, and a per-video spending cap; allow cancel and fall back to current stock footage.

### 5. Reviewable quality checks

Generate a QA report with:

- actual video and narration duration;
- 9:16 dimensions, frame rate, playable audio/video, and missing-media checks;
- caption timing/overflow checks and a short subtitle preview;
- audio clipping and voice/music balance checks;
- scene coverage (every narration beat has a suitable visual);
- a list of factual claims without sources and media needing rights/credit review.

Keep human approval as the gate to upload. Automated scores should identify what needs attention, not claim that a clip is accurate, natural, or ready by themselves.

## Proposed pipeline and project boundaries

```text
topic
  → research notes and sources
  → script + duration target
  → script approval
  → voice preview / final narration
  → word alignment + scene manifest
  → stock / local / optional generated visuals
  → MPT or HyperFrames render
  → automated QA report + human review
  → existing approve / schedule / upload flow
```

Keep the new responsibilities in small modules rather than growing `daily_shorts.py` indefinitely:

- `episode_plan.py`: schema, validation, source notes, scene manifest, atomic stage state.
- `voice_providers/`: current MPT/Edge path and optional local Kokoro adapter behind one interface.
- `alignment.py`: word/phrase timing derived from the finished voice file.
- `visual_providers/`: current stock/local footage plus an opt-in ComfyUI/provider adapter.
- `renderers/`: current MPT renderer and optional HyperFrames renderer.
- `quality_report.py`: duration, media, caption, audio, source/credit checks.

Continue to use the current `review/`, `approved/`, `posted/`, and scheduler behavior. The renderer must return the same final MP4 and metadata contract the rest of the app already consumes.

## Implementation sequence

### Phase 0 — Verify the benchmark and resource envelope

- Record one current output as a baseline: script, narration duration, resolution, render time, available local GPU/RAM, and a human quality score for voice, story, visuals, and captions.
- Compare the current Edge voice against Kokoro using the same 20–30 second sample; do not install or download weights until the local resource and license check is complete.
- Render one deterministic editorial test using HyperFrames with stock footage, captions, a source card, and one diagram.
- Compare rendered output by watching and listening, not by star count or model claims.

**Exit:** choose the first visual style and decide whether Kokoro and HyperFrames provide a noticeable quality improvement on this machine.

### Phase 1 — Improve the existing MPT path

- Check the installed MoneyPrinterTurbo version and identify which upstream voice, pause, word-caption, batch, and generated-footage options it actually exposes.
- Add measured-duration handling: once the voiceover is made, a length outside 60–75 seconds triggers one script revision with a concrete story beat. Log the measured length in the run record so the target can be tuned from real renders.
- Add a small script structure: cold open, one central insight, specific example, reveal, takeaway. Keep sources with factual claims.
- Offer voice sample playback and store voice/rate in Settings.

**Exit:** a 150–165 word script (63–69 seconds at speed 1.05) renders through the current pipeline with natural pacing, readable captions, and no regression to review/upload.

### Phase 2 — Episode manifest and resumable stages

- Introduce a versioned JSON episode manifest with stable scene IDs, style ID, narration, source notes, media references, voice choice, output settings, and stage status.
- Save after script approval, final voice, alignment, footage selection, and render.
- Hash stage inputs; re-render only changed stages and keep prior successful output for comparison.
- Never put secrets or private API credentials in the manifest.

**Exit:** interrupted jobs resume without repeating completed or paid stages, and an old version can be compared with the new one.

### Phase 3 — Voice and caption timing

- Add Kokoro behind the voice interface while keeping Edge/MPT as the default fallback.
- Generate narration before selecting final shot lengths; run local word alignment on the actual voice track.
- Derive subtitle and scene timings from alignment, then provide an editable text/timing correction pass.
- Keep voice rate moderate and use punctuation/pauses to create emphasis rather than speed changes alone.

**Exit:** word/phrase captions remain aligned after voice edits, and the user can compare engines without changing the rest of the episode.

### Phase 4 — HyperFrames editorial renderer

- Build one 9:16 template with safe caption areas, configurable fonts/colors, scene transitions, source cards, and animated keywords.
- Read the approved manifest and source local media; render each frame deterministically.
- Add preview, lint, render, and cancellation subprocess management in Python.
- Keep MPT stock montage as an explicit fallback and avoid requiring Node/HyperFrames for existing jobs.

**Exit:** a template render is repeatable from the same inputs, uses the exact approved narration, and produces an MP4 and QA report compatible with Review.

### Phase 5 — Optional AI-generated B-roll

- First implement one provider adapter only, behind a user-selected visual mode and a per-video budget.
- Generate only scenes where stock/local footage cannot express the idea; cap clip duration and number of generations.
- Keep original prompts, model/provider/version, license/source metadata, returned files, and cost in the episode record.
- Fall back to stock/local footage on timeout, model failure, or over-budget status.
- Pilot ComfyUI/Wan first for self-hosted control if hardware permits. Treat Pika H3 Flex as a separate gated trial due model terms and the hosted API path.

**Exit:** generated scenes are visibly useful, licensed for the intended use, within the configured cost/resource limit, and do not block ordinary video production.

### Phase 6 — Pilot and tune

- Produce a small matched batch in stock, editorial, and hybrid modes using the same topic/script quality target.
- Review hook clarity, source quality, voice naturalness, caption readability, visual fit, and completion/retention data.
- Keep only styles/providers that improve the result enough to justify their maintenance or generation cost.

**Exit:** one default style is selected based on real outputs and audience response; optional modes remain optional.

## Acceptance criteria for the upgraded version

- The measured narration of every video falls within 60–75 seconds, and the default target is 63–69 seconds.
- Every factual claim that drives the story has a source note or a clear human-verification flag.
- Captions and scene changes are based on the final voice track, not the original estimated word count.
- Repeated episodes have a deliberate house style while scene content remains specific to each script.
- A missing AI provider, GPU, API key, or generated clip falls back to the current stock/local workflow.
- Costs and licenses are visible before optional paid generation; no paid provider is invoked by default.
- Every final video remains in the existing Review queue and requires approval before upload.

## Content guardrails

These apply to every niche, script and visual style, including future upgrades:

- **Name topics, not vulnerabilities.** A niche describes what the videos explain (for example, "how subscription pricing works"). It must not list groups with the emotion to press on, such as "Men: lust" or "The Sick: grasping at miracles". Settings should be reviewed whenever the niche text changes.
- **Protective framing when manipulation is the subject.** Videos that explain how marketing or scams work are fine when they cite sources and warn the viewer. They must not read as a playbook for targeting a group.
- **No fear-based health or money offers, miracle claims, sexual content, or personal investment advice.**
- **Every factual claim has a source note**, and a human checks it before approval.
- **Emotion is shaped by evidence.** Hooks can be strong, but a hook may not state a claim the script cannot support.

## Research references

- [Trendshift: AI video generation topic](https://trendshift.io/topics/ai-video)
- [MoneyPrinterTurbo README](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/README-en.md) and [editable local video project design](https://github.com/harry0703/MoneyPrinterTurbo/blob/main/docs/video-projects.md)
- [HyperFrames introduction](https://github.com/heygen-com/hyperframes/blob/main/docs/introduction.mdx), [CLI](https://github.com/heygen-com/hyperframes/blob/main/packages/cli/README.md), and [license](https://github.com/heygen-com/hyperframes/blob/main/LICENSE)
- [Vibe Knowledge](https://github.com/andyhuo520/vibe-knowledge)
- [AI Video Factory](https://github.com/ersinkoc/AI-Video-Factory)
- [Kokoro](https://github.com/hexgrad/kokoro)
- [paper-reel](https://github.com/haiderfarooq3/paper-reel)
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI) and [WanVideoWrapper](https://github.com/kijai/ComfyUI-WanVideoWrapper)
- [Kinoloom](https://github.com/harlixay7/Kinoloom)
- [Pika H3 Flex model card and license](https://huggingface.co/Pika-Labs/Pika-H3-Flex)
- [Remotion license terms](https://www.remotion.dev/docs/terms)
- [SenseNova Code2Video](https://github.com/OpenSenseNova/SenseNova-6.8-Code2Video)
- [Digital Human Koubo](https://github.com/andyhuo520/digital-human-koubo)
