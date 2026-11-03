# AI video automation for high production quality

**Research snapshot:** 2026-11-03  
**Scope:** production methods and reusable agent skills for the existing Shorts and long-form workflows.  
**Evidence standard:** official project repositories, first-party product documentation, licenses, and YouTube guidance. This is a source review, not a benchmark of generated outputs. Rankings are by fit and likely quality leverage; they do not promise views or virality.

## Recommendation

Keep the current MoneyPrinterTurbo-based Shorts renderer and the custom HyperFrames long-form renderer. Improve the decisions that feed them: source-backed story briefs, voice-first timing, shot-level visual direction, a small coherent style system, and a review loop that checks every beat as well as the final encoded file.

Use skills as craft references and checklists. They do not raise video quality by themselves, and most should not become new runtime dependencies. The highest-value path is to bring selected HyperFrames and explainer-video methods into the current pipeline, then test any additions on a small, matched batch before adopting them.

## Current project baseline

The repository already has separate vertical and landscape pipelines. Shorts use `daily_shorts.py`, MoneyPrinterTurbo, custom `motion.py`, narration and caption timing, synthesized sound effects, and automated checks. The long-form page produces resumable 8-10 minute, 16:9 animated explainers with a screenplay, beat plan, per-character voices, HyperFrames/GSAP scenes, audio mix, checks, thumbnail, and a human review/approval stage. See the [project README](../README.md), [video generation plan](VIDEO_GENERATION_PLAN.md), [daily_shorts.py](../daily_shorts.py), [motion.py](../motion.py), [longform.py](../longform.py), and [long-form production modules](../lf_screenplay.py).

The prior repo research records Intel Iris Xe graphics, 15.6 GB RAM, and no NVIDIA GPU. Recheck that machine snapshot before any GPU-heavy local generation trial; do not make the present render path depend on it. The earlier [free workflow research](RESEARCH_FREE_SHORTS_AND_LONG_VIDEO_WORKFLOWS.md) covers current vendor free tiers, costs, asset licenses, and policy details.

## Ranked skills and tools

| Rank | Skill or tool | Quality value and fit | License, cost, and constraints | Decision |
|---:|---|---|---|---|
| 1 | **Existing HyperFrames skill set**: `/hyperframes`, `/hyperframes-creative`, `/hyperframes-cli`, `/media-use` | Best fit because the landscape pipeline already uses HyperFrames. Its primary skill directs a story through three distinct concepts, an explicit frame-level spec, deterministic rendering, `check`, snapshots, and visual review. The media skill keeps image, footage, music, voice and effects sourcing explicit. ([core skill](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes/SKILL.md), [creative skill](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes-creative/SKILL.md), [CLI skill](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes-cli/SKILL.md), [review loop](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes/references/review-loop.md)) | HyperFrames renderer is Apache-2.0. Local rendering needs the existing Node/Chrome/FFmpeg setup; hosted render and some media services are separate and can cost money. ([license](https://github.com/heygen-com/hyperframes/blob/main/LICENSE)) | Adopt the story, storyboard, spec, and frame-review discipline in the existing project. Do not reinstall or replace the renderer just to use its skills. |
| 2 | **iart Explainer Video skill** | Strong short-form production checklist: one message, script before scene construction, one visual per spoken beat, voice/caption timing, and a reusable style system. It is directly relevant to 60-90 second explainers. ([SKILL.md](https://github.com/iart-ai/explainer-video-skills/blob/main/skills/explainer-video/SKILL.md), [repo README](https://github.com/iart-ai/explainer-video-skills/blob/main/README.md)) | MIT skill pack; it recommends Remotion or After Effects for rendering, so reuse the method rather than add that renderer. Its default CTA/problem-solution framing fits product explainers better than every documentary topic. ([license](https://github.com/iart-ai/explainer-video-skills/blob/main/LICENSE)) | Adapt its script-to-screen checklist and caption/style guidance. Add sourced-claim checks and a payoff appropriate to the topic. |
| 3 | **iart motion-skills**, selected packs only | Useful craft recipes for kinetic type, beat-synced cuts, explainer diagrams, and frame review. The project can select the `explainer-video`, `kinetic-typography`, and `motion-design` references rather than importing all packs. ([catalog](https://github.com/iart-ai/motion-skills), [pack list](https://github.com/iart-ai/motion-skills/blob/master/README.md)) | MIT; skills are mostly instructions and small helper scripts, not a replacement renderer. Review any helper scripts before running them. ([license](https://github.com/iart-ai/motion-skills/blob/master/LICENSE)) | Borrow individual checks and examples when a scene needs them; keep the current visual identity and render path. |
| 4 | **Official Remotion skills** | Good guidance on frame-based animation, captions, audio, timing, and render verification. It is useful as a second-source craft reference for specific problems, but the repo currently renders with FFmpeg and HyperFrames rather than Remotion. ([skills repo](https://github.com/remotion-dev/skills), [markup skill](https://github.com/remotion-dev/agent-plugin/blob/main/skills/remotion-markup/SKILL.md)) | The skills are not a video engine; adopting Remotion adds a separate React render stack and its own license/usage review. ([Remotion terms](https://www.remotion.dev/license)) | Reference selected rules only. Do not migrate renderers for quality gains that the current system can produce. |
| 5 | **browser-use/video-use** | Useful for transcript-first editing of raw talking-head footage: identify speech boundaries, plan cuts, then iterate and persist the edit. ([skill](https://github.com/browser-use/video-use/blob/main/SKILL.md)) | MIT project, but its installer requires FFmpeg and an ElevenLabs API key for Scribe transcription; the model/API has its own plan and cost. ([install requirements](https://github.com/browser-use/video-use/blob/main/install.md), [license](https://github.com/browser-use/video-use/blob/main/LICENSE)) | Reuse its audio-first editing idea. Keep the package out of the default faceless/animated pipeline unless raw presenter footage becomes a real workflow. |
| 6 | **Hosted image-to-video prompting guides** (Runway Gen-4 / Google Veo) | Helpful for a few optional cutaways: anchor composition and identity with a reference image, describe one simple subject/camera motion, and iterate one prompt change at a time. Runway says its Gen-4 video produces 5- or 10-second clips from an image and text prompt; its guide advises simple motion-focused prompts. Google's Veo guide uses cinematography, subject, action, context, style, and ambiance, with reference images for consistent elements. ([Runway guide](https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide), [Runway reference images](https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References), [Google Veo prompt guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1)) | Hosted generation requires a supported account/model and current plan or credits; no quality or cost benchmark was performed here. Check current terms, price, data handling, and output rights before any trial. | Keep optional and scene-specific. Use for a hero shot that stock or vector animation cannot express, not for every line or for factual evidence. |
| 7 | **FFmpeg finishing and measurement** | FFmpeg's filters expose precise operations for audio normalization, scaling, timing, subtitles, compositing, and encoding. The `loudnorm` filter implements EBU R128 normalization with integrated loudness, loudness range, and true-peak targets. ([FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html#loudnorm)) | FFmpeg is already in the project. A loudness number cannot establish that the voice sounds natural, music is tasteful, or the final video is pleasant to watch. | Keep it as the finishing/measurement layer; pair automated checks with listening and picture review. |

The relevant repositories above publish their own instructions and claims. Their examples are not independent proof that a particular formula improves retention. Keep only practices that survive review of real output and the channel's own audience data.

## Methods that produce the biggest quality gains

### 1. Lock the story before generating media

- Start with the intended viewer, one question, one defensible answer, and a one-sentence takeaway. Write an evidence note for each factual claim before asking a model to dramatize it.
- Develop three genuinely different story angles in text first. Choose the strongest argument or story, not the prettiest visual premise. HyperFrames' source workflow uses separate concept outlines and a shot-level spec before building. ([story/spec/review workflow](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes/SKILL.md), [story spine](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes-creative/references/story-spine.md))
- Structure Shorts around a quick promise, a few specific beats, and a real resolution. For 8-10 minute explainers, give each section its own question or reveal; do not inflate word count to meet a runtime target.
- Use an original point of view and concrete examples. Repetition of the same hook, script skeleton, stock sequence, and outcome can make a series interchangeable. YouTube's monetization policy evaluates originality and repetitive or mass-produced low-value content; AI use alone is not a categorical monetization violation. ([YouTube policy](https://support.google.com/youtube/answer/1311392), [YPP clarification](https://support.google.com/youtube/blog/356734251/response-to-creator-questions-about-ypp-policies-july-2025))

### 2. Make the narration the timing source

- Write in spoken language, read it aloud, and revise awkward phrases before generating the whole track. Avoid writing to a fixed word count; use the finished voice's measured duration.
- Audition the same representative paragraph across available voices at a natural speed. Listen for word stress, sentence endings, breath, pronunciation, and whether adjacent sentences sound like one thought. Keep a human-recorded option where practical; otherwise use the current Edge or Kokoro path and decide by listening.
- Generate narration before final scene durations. Align captions and transitions against that finished audio, not against estimated word counts. The current project already has Edge timing and Whisper alignment/checks for the local voice path.
- For any future TTS provider, add delivery tags sparingly and only when supported. ElevenLabs' own documentation says emotional delivery depends on context, voice data, punctuation, and settings; its examples still require testing and do not guarantee a performance. ([emotion guidance](https://elevenlabs.io/docs/help-center/product/core-capabilities/text-to-speech/how-to-produce-emotions), [TTS best practices](https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices))

### 3. Storyboard in beats; generate in shots

- Create a scene record with: narration range, narrative job, visible action, subject and setting, camera framing/move, style/reference ID, caption text, and media provenance.
- Assign one dominant visual idea per beat. Every shot should explain or advance the line currently being spoken; use graphic overlays for exact labels, numbers, and captions rather than asking a video model to render readable text.
- Set a compact style guide first: palette, type, contrast, framing, grain/texture, camera movement, and caption safe area. Carry it across all scenes. In long-form, use the existing vector characters and rooms as continuity anchors; reserve generated footage for cutaways.
- For image-to-video, first select or create the image that establishes composition, subject, lighting, and style. Prompt only the intended motion and camera behavior. Keep one shot to one main action, then iterate one variable at a time. Use approved reference images for recurring people, places, and props where the provider supports them. This follows the providers' own image-to-video guidance, not a guarantee of identity consistency. ([Runway image-to-video guide](https://help.runwayml.com/hc/en-us/articles/48324313115155-Image-to-Video-Prompting-Guide), [Runway references guide](https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References), [Veo prompting guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1))
- Avoid generating the entire film as disconnected clips. Keep generated shots short, locally reviewed, and clearly labeled in the episode record. Never use generated footage as proof of a real event or source-backed factual illustration without making its illustrative role clear.

### 4. Design motion and sound around meaning

- Motivate movement by the narration: reveal a label when it is spoken, move to a closer framing on a key detail, hold a diagram while the viewer reads it, and give the resolution enough screen time.
- Prefer a few repeatable motion primitives over effects on every cut: deliberate camera drift, clear transitions between sections, animated diagrams, and emphasized keywords. Use an effect only when it reinforces the point.
- Keep captions synchronized to the final narration, concise, and inside mobile-safe areas. Check a still at small-phone scale and verify captions do not cover faces, essential actions, or platform controls. The explainer skill recommends deriving caption and scene timing from one shared timing source. ([explainer skill](https://github.com/iart-ai/explainer-video-skills/blob/main/skills/explainer-video/SKILL.md))
- Mix for intelligibility first: voice clearly in front, music below it, effects timed to meaningful cuts. Measure integrated loudness and true peak with FFmpeg, then listen on headphones and ordinary speakers; the measurement is a consistency check, not a substitute for listening. ([FFmpeg loudnorm](https://ffmpeg.org/ffmpeg-filters.html#loudnorm))

### 5. Use a two-layer quality gate

**Automated checks** should catch duration, frame size, frame rate, missing media, black frames, audio stream errors, peak/loudness, caption timing/overflow, scene coverage, and source/license metadata. HyperFrames' `check` and snapshot workflow can catch visual/layout/runtime issues for its renderer; the current project has FFmpeg/QA checks for the final file. ([HyperFrames skill and review loop](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes/SKILL.md), [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html))

**Human review** should assess whether the story makes sense, each visual fits the spoken beat, characters and style stay consistent, the voice feels natural, music/effects distract, the ending resolves the opening, and any claim or asset needs correction. Watch and listen to the whole export at normal speed before approval. Screenshots, contact sheets, transcript checks, and automated scores help find defects; they cannot certify taste, factual accuracy, or audience response.

## Staged plan for this project

### Phase 0 - Make a reference set

- Choose one representative Short and one 8-10 minute film. Record the script, source notes, narration provider, final audio duration, style, render time, and human ratings for story, voice, visual match, captions, and sound.
- Preserve one approved style frame and one scene-transition reference for each format. Keep a short defect list instead of changing many things at once.

### Phase 1 - Improve creative direction without adding dependencies

- Add a brief/storyboard stage before the existing generation steps: audience question, evidence/claims, three story angles, chosen message, narrated beats, and visual intent per beat.
- Require a human review of the script and beat plan before expensive or long-running media generation. Store source links and asset/license metadata in the project manifest.
- Use the existing voice audition and alignment flow. Add a same-paragraph comparison and the option to record a human narration track; choose the voice and cadence by listening.

### Phase 2 - Upgrade shot planning and visual continuity

- Extend the scene plan with style ID, reference frame, visual action, camera movement, caption-safe region, and clip provenance.
- Render a storyboard/contact sheet or low-cost still preview before full render. Reject generic or mismatched footage and repeated visual filler at this step.
- Keep titles, captions, labels, diagrams, and data in deterministic HyperFrames/FFmpeg layers. Use generative video only for selected atmospheric or action cutaways.

### Phase 3 - Strengthen review and fix-the-defect iteration

- Sample the opening, every scene boundary, each text-heavy beat, and the ending. Inspect all sampled frames and compare caption, narration, and visible action.
- Watch/listen to the full encode. When a defect is found, identify its stage (script, voice, media, timing, mix, render) and rerun only that stage.
- Keep the approval gate. Add automated source, asset, duration, caption, and audio results to the review page so the human sees the remaining decisions.

### Phase 4 - Trial generative cutaways only if useful

- Use up to a few shots from one chosen provider on an already approved storyboard. First review account/plan pricing, provider terms, data retention, model limits, output rights, and generated-content disclosure needs; the earlier [free workflow research](RESEARCH_FREE_SHORTS_AND_LONG_VIDEO_WORKFLOWS.md) has the existing cost and rights survey.
- Compare generated clips against an equally timed stock/vector alternative. Score literal scene fit, continuity, useful motion, artifact rate, authoring time, render/review time, and cost. Keep the provider only if the final film improves enough to justify that burden.

### Phase 5 - Evaluate the audience response

- Compare Shorts and long-form within their own format and against the channel's own baseline. Use audience data as feedback about the topic, packaging, opening, and pacing, not as a command to exaggerate claims.
- Keep a method only when it improves judged story/voice/visual fit or reduces editing work without harming the other dimensions.

## Quality acceptance checklist

- One clear takeaway and an original, source-backed treatment.
- Narration sounds natural at a relaxed, measured pace; captions follow the final audio.
- Every scene has a visible purpose, and its image/action matches the current beat.
- The same palette, type, character/prop references, and caption rules hold across the video.
- Motion has a reason; effects and music do not compete with narration.
- No missing, broken, black, clipped, or incorrectly timed media; output specs and audio measurements are within the project's chosen limits.
- Asset sources, licenses, and realistic synthetic depictions are recorded for review.
- A person watches and listens to the complete export and approves it before upload.

## Sources

### Existing project and free workflow research

- [README](../README.md), [VIDEO_GENERATION_PLAN.md](VIDEO_GENERATION_PLAN.md), [RESEARCH_FREE_SHORTS_AND_LONG_VIDEO_WORKFLOWS.md](RESEARCH_FREE_SHORTS_AND_LONG_VIDEO_WORKFLOWS.md)

### Skills and tools

- [HyperFrames core skill](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes/SKILL.md), [creative skill](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes-creative/SKILL.md), [CLI skill](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes-cli/SKILL.md), [review loop](https://github.com/heygen-com/hyperframes/blob/main/skills/hyperframes/references/review-loop.md), [license](https://github.com/heygen-com/hyperframes/blob/main/LICENSE)
- [iart explainer-video skill](https://github.com/iart-ai/explainer-video-skills/blob/main/skills/explainer-video/SKILL.md), [repo/license](https://github.com/iart-ai/explainer-video-skills)
- [iart motion-skills catalog](https://github.com/iart-ai/motion-skills), [MIT license](https://github.com/iart-ai/motion-skills/blob/master/LICENSE)
- [Remotion skills](https://github.com/remotion-dev/skills), [Remotion license](https://www.remotion.dev/license)
- [browser-use/video-use](https://github.com/browser-use/video-use/blob/main/SKILL.md), [install requirements](https://github.com/browser-use/video-use/blob/main/install.md)
- [FFmpeg filter documentation](https://ffmpeg.org/ffmpeg-filters.html)

### Voice, generation, and platform guidance

- [ElevenLabs emotional delivery](https://elevenlabs.io/docs/help-center/product/core-capabilities/text-to-speech/how-to-produce-emotions), [TTS best practices](https://elevenlabs.io/docs/overview/capabilities/text-to-speech/best-practices)
- [Runway Gen-4 video prompt guide](https://help.runwayml.com/hc/en-us/articles/39789879462419-Gen-4-Video-Prompting-Guide), [Runway image-to-video guide](https://help.runwayml.com/hc/en-us/articles/48324313115155-Image-to-Video-Prompting-Guide), [Runway references guide](https://help.runwayml.com/hc/en-us/articles/40042718905875-Creating-with-Gen-4-Image-References)
- [Google Veo 3.1 prompt guide](https://cloud.google.com/blog/products/ai-machine-learning/ultimate-prompting-guide-for-veo-3-1)
- [YouTube monetization policy](https://support.google.com/youtube/answer/1311392), [YouTube clarification on AI use](https://support.google.com/youtube/blog/356734251/response-to-creator-questions-about-ypp-policies-july-2025)
