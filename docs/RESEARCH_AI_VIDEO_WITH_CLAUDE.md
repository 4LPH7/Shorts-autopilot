# Making AI video with Claude: roles, renderers, voices and policy

**Research snapshot:** 2026-11-04 (every external source below was checked on this date)
**Question:** What is the most reliable way to use Claude in this app's pipeline for faceless 9:16 Shorts (20-60 s) and 8-10 minute animated explainers, and which renderer, voice, generation and policy facts bear on that?
**Source standard:** Anthropic, Microsoft, Google, OpenAI, Runway and YouTube first-party pages, GitHub repositories read through the GitHub API, and this project's own code. No code was changed and no paid call was made. Prices are a dated snapshot.
**Builds on:** [RESEARCH_AI_VIDEO_AUTOMATION_QUALITY.md](RESEARCH_AI_VIDEO_AUTOMATION_QUALITY.md) (craft and skills), [RESEARCH_FREE_SHORTS_AND_LONG_VIDEO_WORKFLOWS.md](RESEARCH_FREE_SHORTS_AND_LONG_VIDEO_WORKFLOWS.md) (free tiers, stock licences, ElevenLabs free-tier rights) and [VIDEO_GENERATION_PLAN.md](VIDEO_GENERATION_PLAN.md) (pipeline decisions). Points settled there are linked, not repeated.

## Summary

- **Claude writes and checks; it does not make the video.** Current Claude models take text and image input and give text output ([models overview](https://platform.claude.com/docs/en/about-claude/models/overview)). The vision FAQ says Claude "cannot generate, produce, edit, manipulate, or create images" ([vision](https://platform.claude.com/docs/en/build-with-claude/vision)). Audio and video input are not listed. Everything audible or visible in a finished video comes from other tools: TTS, the HyperFrames renderer, ffmpeg and any generation API.
- **The 2026-11-04 usage-limit failure has a documented cause and a documented fix.** The app calls `claude -p` on the subscription login. No local log showed why the 300 s timeout happened; it is a single call with no Claude retry. The subscription login draws from the same five-hour and weekly limits as claude.ai and interactive Claude Code ([support](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan), [Agent SDK with a plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)). For unattended use, an API key with the Python SDK is the more reliable path: the SDK has typed errors, retries, `request-id`s, streaming, structured outputs, prompt caching and spend caps ([Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python), [errors](https://platform.claude.com/docs/en/api/errors)).
- **An earlier statement here is now out of date.** The free-workflows doc says a Claude subscription does not include API use. As of 2026-11-04 (Anthropic says the offer is rolling out), Max includes **$100 a month** and Ultra **$200 a month** of API credits. The credits cover the API, Message Batches and the Agent SDK when run with an API key from the linked Console organization. They can be claimed after 7 days on the plan, expire at the end of each billing cycle, and are not offered on Pro ([monthly API credits](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-ultra-and-team-plans)).
- **Keep HyperFrames.** It is Apache-2.0 with no per-render fee, renders headless, already produces this project's 9:16 and 16:9 output, and ships Claude Code skills. Remotion would also be free for a one-person operation, but switching gains nothing here. Motion Canvas has no headless render. Manim suits math diagrams, not puppets.
- **Voice licensing is the largest unresolved risk.** No Microsoft page grants or forbids commercial use of the Edge Read Aloud voices that `edge-tts` calls. The same voices are sold through Azure AI Speech: 0.5M characters a month free, then $15 per 1M characters, with word-boundary and viseme events. Kokoro (Apache-2.0 weights) is the local alternative. OpenAI TTS shuts down on 2027-01-06.
- **The generated-video market moved in the last six weeks.** The Sora API shut down on 2026-09-24. Veo 3.1 preview shut down on the Gemini API on 2026-10-22; its replacement, Gemini Omni Flash, costs about $0.10/s at 720p and supports 9:16. Generated video stays an opt-in cutaway.
- **YouTube's risk is sameness, not AI.** "AI-generated content made with generic or unoriginal templates" cannot monetize, and the reused-content penalty can apply to a whole channel ([YPP policies](https://support.google.com/youtube/answer/1311392)). Non-realistic animation and AI help with scripts need no disclosure; realistic synthetic scenes and AI music do ([disclosure](https://support.google.com/youtube/answer/14328491)).

## 1. Claude's role in a video pipeline

### What Claude can and cannot do

| Pipeline job | Claude? | Evidence |
|---|---|---|
| Topic ideas, research brief, screenplay, beat plan, shot list, titles | Yes (text output) | [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Write HTML/CSS/GSAP compositions, ffmpeg commands, Python glue | Yes (code is text) | Same; [Claude Code](https://code.claude.com/docs/en/headless) |
| Check rendered frames, contact sheets or thumbnails | Yes (image input) | [Vision](https://platform.claude.com/docs/en/build-with-claude/vision) |
| Produce images, video, voice, music or sound effects | **No** | Vision FAQ; models list text output only |
| Listen to the mix or watch the MP4 | Not listed as an input. Sample frames to images and send transcripts as text. | [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview) |
| Detect AI-generated images, count precisely, give exact coordinates | Unreliable, per Anthropic | Vision "Limitations" section |

### Models (Claude API, checked 2026-11-04)

| Model ID | Fit here | Input / output per MTok | Cache read | Batch (−50%) | Context / max output |
|---|---|---|---|---|---|
| `claude-haiku-5-5` | Frame triage, JSON repair, captions, topic de-duplication | $0.10 / $0.50 (prompts ≤100k tokens); $0.50 / $2.50 above | $0.01 | $0.05 / $0.25 | 1M / 128K |
| `claude-sonnet-5-5` | Default for screenplays, beat plans, storyboard judgement | $2 / $10 | $0.10 (0.05×) | $1 / $5 | 1M / 128K |
| `claude-opus-5-5` | Hardest long-form outlines; thinking is always on | $4 / $20 | $0.20 (0.05×) | $2 / $10 | 1M / 128K |
| `claude-fable-5-1` | Not needed for this workload | $10 / $50 | $0.25 | $5 / $25 | 1M / 128K |

Sources: [models overview](https://platform.claude.com/docs/en/about-claude/models/overview), [pricing](https://platform.claude.com/docs/en/about-claude/pricing). A 5-minute cache write costs 1.25× input and a 1-hour write 2×. Every model except Haiku 5.5 bills the full 1M context at standard rates. Claude 4.7 and later models use a tokenizer that produces about 30% more tokens for the same text.

Two API changes affect how this project asks for JSON. Opus 5.5 and Sonnet 5.5 reject assistant prefill and forced `tool_choice` with a 400 error ([errors](https://platform.claude.com/docs/en/api/errors)). Structured outputs (`output_config.format` with a JSON schema) are GA on all current models ([structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)). The CLI's equivalent is `--json-schema` ([headless](https://code.claude.com/docs/en/headless)). That replaces the "reply again with ONLY the valid JSON" retries in `lf_screenplay.py`.

### Claude Code, the Agent SDK, skills, caching and batches

| Surface | What it gives this project | Limits that matter |
|---|---|---|
| **Claude Code CLI, `claude -p`** (what MoneyPrinterTurbo's `claude_code` provider and `daily_shorts.ask_vision` call) | Non-interactive runs with `--output-format json`. The JSON includes `is_error`, `result`, `total_cost_usd` and per-model usage. `--json-schema`, `--model`, `--fallback-model`, `--max-turns` and `--max-budget-usd` are print-mode flags. A failed retry emits `system/api_retry` events. ([headless](https://code.claude.com/docs/en/headless), [CLI reference](https://code.claude.com/docs/en/cli-reference)) | On the subscription login it uses plan limits. `--bare`, which the docs recommend for scripts, skips OAuth entirely and needs `ANTHROPIC_API_KEY`. MPT's `build_claude_code_env` removes every `ANTHROPIC_*` variable on purpose (`D:\MPT\app\services\llm.py`). Moving to a key is therefore a code change, not a setting. |
| **Agent SDK** (Python/TypeScript) | The Claude Code agent loop as a library, for agents that need tools. ([overview](https://code.claude.com/docs/en/agent-sdk/overview)) | The docs say: "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK." Whether a personal app that runs its owner's logged-in CLI falls under this is **not stated**. Script writing needs no agent loop, so the plain Client SDK is the simpler choice. |
| **Skills** (`SKILL.md` in `.claude/skills/` or `~/.claude/skills/`) | Load on demand in development sessions: the HyperFrames skills, plus the craft skills in the quality doc. ([skills](https://code.claude.com/docs/en/skills)) | MPT runs the CLI with `--safe-mode`, which turns off skills ([CLI reference](https://code.claude.com/docs/en/cli-reference)). Skills improve the kit you write, not unattended script calls. |
| **API prompt caching** | Re-send a long, stable prefix (system prompt, style rules, outline) at 0.05× input on Sonnet/Opus 5.5. Cached reads do not count toward input-tokens-per-minute limits. ([caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [rate limits](https://platform.claude.com/docs/en/api/rate-limits)) | Minimum cacheable prompt is 512 tokens on the current models. The cache lasts 5 minutes by default or 1 hour; there are at most 4 breakpoints. Adding or removing images invalidates only the message-level cache; the tools and system prefix stay cached. The cached prefix must come first in the prompt. |
| **Message Batches API** | 50% off for work that can wait: overnight topic lists, next week's titles, bulk re-scoring. ([batch](https://platform.claude.com/docs/en/build-with-claude/batch-processing)) | Most batches finish within an hour, but the guarantee is only 24 hours. Use the 1-hour cache with batches. A poor fit for the interactive screenplay step. |

### Vision for checking frames

- **Cost:** an image costs ⌈width/28⌉ × ⌈height/28⌉ tokens. Models from Claude 4.7 on accept up to a 2,576 px long edge and 4,784 visual tokens without resizing ([vision](https://platform.claude.com/docs/en/build-with-claude/vision)). A full 1080×1920 Shorts frame is 39 × 69 = **2,691 tokens**. That is about $0.0054 on Sonnet 5.5, $0.00027 on Haiku 5.5 and $0.011 on Opus 5.5 per frame (illustrative arithmetic from list prices).
- **Limits:** 600 images per API request. A request with more than 20 images gets a stricter per-image size limit, which a ≤3,000 px long edge always satisfies. Files can be 10 MB each and the request 128 MB.
- **Fit:** checking that a caption sits clear of a face, that a beat's picture matches its line, or that a scene is blank, clipped or off-palette suits it. Exact counts, positions and AI-image detection are listed limitations; keep those deterministic in `qa.py`.
- `daily_shorts.ask_vision` already does this through the CLI with `timeout=300`. It shares the subscription limits and the timeout failure of the script path.

### Usage limits: subscription vs. API

| | Claude Code on a Pro/Max/Ultra login | Claude API with a key |
|---|---|---|
| What limits you | A five-hour session limit plus a weekly limit (Ultra: weekly only, when verified). "All activity in both tools counts against the same limits", so chat and interactive coding compete with the app. ([support](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan)) | Per-minute RPM/ITPM/OTPM (Start tier: 4,000 RPM and 2M ITPM for Sonnet 5.5; new organizations may begin in a lower Evaluation tier) and a monthly tier spend cap (Start $500) ([rate limits](https://platform.claude.com/docs/en/api/rate-limits)) |
| At the limit | The run fails until reset, unless usage credits are enabled | 429 with `retry-after` for rate limits. The spend-cap 429 has **no** `retry-after` and carries `error_code: enforced_spend_limit_reached`. A spend limit you set returns 400. |
| Cost | Inside the plan fee | Pay per token; Max/Ultra monthly credits apply when using an API key from the linked Console org |
| Retries and timeouts | Up to the caller. `daily_shorts.ask()` calls MPT's `_generate_response` once: one `subprocess.run` with a 300 s timeout. On an error it falls back to OmniRoute rather than retrying Claude. | The SDK retries connection errors, 408, 409, 429 and ≥500 twice by default with backoff, and times out after 10 minutes. Non-streaming calls expected to run over ~10 minutes raise an error; stream those ([Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)). |

**Most reliable call for an unattended app:** the Python SDK with an API key from a Console workspace that has a spend limit set. Recommended settings (these values are this document's choice, not Anthropic's):

- `max_retries=4`; stream any reply longer than a few thousand tokens.
- `timeout=httpx2.Timeout(600, connect=10)`.
- Treat `enforced_spend_limit_reached` and 400 spend-limit errors as **stop and tell the user**, not retry.
- Log `_request_id` and `usage` per call.

If the CLI stays as a fallback:

- Set `--model` explicitly and add `--fallback-model`.
- Add `--max-budget-usd`.
- Raise the timeout above 300 s for outline calls, because Opus 5.5 always thinks.
- Read `total_cost_usd` from the JSON to learn real per-video token costs before estimating.

## 2. Code-to-video renderers Claude can drive

| Renderer | Licence and cost | Headless render | 9:16 | Audio sync | Speed and scaling |
|---|---|---|---|---|---|
| **HyperFrames** (`heygen-com/hyperframes`) | Apache-2.0; no per-render fee or commercial threshold ([repo](https://github.com/heygen-com/hyperframes)). Latest v0.9.12 (2026-11-04); this project has 0.9.8. | `npx hyperframes render`: headless Chrome seeks each frame, ffmpeg encodes. Deterministic with `--docker`. ([CLI docs](https://github.com/heygen-com/hyperframes/blob/main/docs/packages/cli.mdx)) | Output equals the composition size. This project already renders 9:16 Shorts (`story_short.py`, `longform/kit/short.css`). | Audio elements placed with `data-start`/`data-duration`/`data-volume`; the CLI includes `normalize-audio` (LUFS matching) | `--workers` 1-24, each a Chrome of about 256 MB; `--gpu` optional; AWS Lambda chunked rendering. Local records here: a 595.5 s film (later rejected) rendered in 838 s and a 41 s Short in 61 s. Quality and worker count were not recorded, so treat these as single data points. |
| **Remotion** | Free for individuals and for-profit organizations "with up to 3 employees" ([LICENSE](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md)). Larger companies pay $25/seat/month or $0.01/render with a $100 minimum ([pricing](https://www.remotion.pro/license)). | CLI `npx remotion render`, Node `renderMedia()`, Lambda ([render](https://www.remotion.dev/docs/render), [renderMedia](https://www.remotion.dev/docs/renderer/render-media)) | Any width/height | Audio included by default; `muted` to drop it | `concurrency` defaults to half the CPU threads |
| **Motion Canvas** | MIT; last release v3.17.2 (2024-12-14) | **No.** Rendering is the editor's RENDER button in a browser; output is an image sequence, or video through its ffmpeg exporter package ([rendering](https://motioncanvas.io/docs/rendering), [repo](https://github.com/motion-canvas/motion-canvas)) | Configurable in the editor | Built to sync to voice-over; audio-in-export not stated | Browser-bound; unsuitable for an unattended app |
| **Revideo** (now `midrender/revideo`) | MIT; no tagged releases; last push 2026-07-15 | `renderVideo()` headless API and a render endpoint ([repo](https://github.com/midrender/revideo)) | Configurable | `<Audio/>`/`<Video/>` with frame-accurate sync, per its README | Can split renders across workers |
| **Manim Community** | MIT; v0.22.1 (2026-10-27) | `manim -qh file.py Scene` ([configuration](https://docs.manim.community/en/stable/guides/configuration.html)) | `-r 1080,1920` or `pixel_width`/`pixel_height` | `Scene.add_sound(file, time_offset)` (source: `manim/scene/scene.py`) | Presets up to 2160p60; Python-native |

**Verdict:** none of the alternatives beats the HyperFrames kit the project has already built. It works for both aspect ratios, has no licence cost and has agent skills. Its documented risk is render time on this CPU-only PC: a 10-minute film takes about 14 minutes in the local record. Tune `--workers` before considering another engine. Manim could be added for a single math-heavy scene type, rendered to a clip and placed as a video in a composition. It is not a renderer swap.

## 3. Voices: licences and word timing

| Voice | Licence for monetised YouTube | Word timing for lip sync and captions | Cost |
|---|---|---|---|
| **edge-tts** (Edge Read Aloud service) | **Unverified.** The library is LGPLv3 (one file MIT) ([LICENSE](https://github.com/rany2/edge-tts/blob/master/LICENSE)), but that covers the code, not the voices. No Microsoft page grants or forbids commercial use. The newest Microsoft Q&A answer, from an "External Staff" moderator, says there "isn't any public documentation that explicitly addresses commercial usage rights for Edge Read Aloud voices or edge-tts" ([Q&A, 2026-06-22](https://learn.microsoft.com/en-au/answers/questions/5925556/commercial-use-of-edge-read-aloud-voices-via-edge)). An unbadged 2024 answer warns this "could be a violation" ([Q&A](https://learn.microsoft.com/en-us/answers/questions/2088770/are-opensource-edge-tts-free-for-commercial-use)). Neither is a licence; the endpoint is undocumented. | `WordBoundary` events, but v7 defaults to `SentenceBoundary` ([source](https://github.com/rany2/edge-tts/blob/master/src/edge_tts/communicate.py)). `narrate.py` already passes `boundary="WordBoundary"`. | Free, with no published quota |
| **Azure AI Speech** (same voice family) | A contracted, paid Microsoft service. All 11 Edge voice names in `voices.py`, `narrate.py` and the long-form files appear in Azure's voice list (the `*MultilingualNeural` voices plus Guy, Jenny, Christopher, Eric, Roger, Ana and en-GB Sonia) ([language support](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts)). A clause on YouTube monetisation was not retrieved. | SDK `WordBoundary` events with audio offset and duration, plus `VisemeReceived` for mouth shapes ([synthesis how-to](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-speech-synthesis)) | F0: 0.5M characters a month free ([pricing](https://azure.microsoft.com/en-us/pricing/details/speech/)); S1 neural $15 per 1M characters (Azure retail prices API, East US) |
| **Kokoro-82M** (`hexgrad/kokoro`) | Apache-2.0 code and "Apache-licensed weights" ([README](https://github.com/hexgrad/kokoro)) | Per-token `start_ts`/`end_ts` from predicted durations in the English pipeline (`kokoro/pipeline.py`); other languages unverified. Repo last pushed 2025-08-06. | Local CPU |
| **Piper** | The original `rhasspy/piper` is archived; development moved to `OHF-Voice/piper1-gpl` (GPL-3.0). Its docs say Piper "is intended for personal use and text to speech research only" and that each voice's `MODEL_CARD` sets its own licence ([VOICES.md](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/VOICES.md)). | Experimental per-phoneme sample counts after patching the voice ([ALIGNMENTS.md](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/ALIGNMENTS.md)) | Local CPU |
| **ElevenLabs** | Commercial use on paid plans only (see the free-workflows doc) | `POST /v1/text-to-speech/{voice_id}/with-timestamps` returns per-character start/end times ([API](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps)) | Paid plan |
| **Gemini TTS** (`gemini-3.8-flash-tts`, `-flash-lite-tts`) | Output rights under the Gemini API terms: not retrieved. Paid-tier content is not used to improve Google products (free-workflows doc). | **No timestamps.** Audio-only output, 24 kHz PCM/WAV, up to 2 speakers per request ([speech generation](https://aistudio.google.com/docs/speech-generation)). Needs Whisper alignment, as now. | Free tier exists. Paid: $0.50 in / $9.00 out per 1M tokens until 2026-12-31, then $1.00 / $18.00 ([pricing](https://aistudio.google.com/docs/pricing)). The free tier's 10 requests/day is this project's observation; the [rate-limit page](https://aistudio.google.com/docs/rate-limits) defers to AI Studio. |
| **OpenAI TTS** (`gpt-4o-mini-tts`, `tts-1`, `tts-1-hd`) | Usage policies require telling listeners the voice is AI-generated ([TTS guide](https://developers.openai.com/api/docs/guides/text-to-speech)) | Not documented | **Shuts down 2027-01-06** ([deprecations](https://developers.openai.com/api/docs/deprecations)). Do not adopt. |

The project's word-timed lip sync in `lf_voice.py` works from word times plus the waveform, so any engine with word or character timing can feed it: Edge/Azure word boundaries, Kokoro token times, ElevenLabs character times, or Whisper alignment.

## 4. Generated video and images

| Provider and model (checked 2026-11-04) | Status | Price | 9:16, audio |
|---|---|---|---|
| **Gemini Omni Flash** `gemini-omni-1.1-flash` (Gemini API) | GA on the paid tier only | Billed at 5,792 output tokens per second of 720p × $17.50/MTok, about **$0.10/s** ([pricing](https://aistudio.google.com/docs/pricing)) | 9:16 and 16:9; 360p-4K (1080p and 4K upscaled); audio by default; reference images and first/last frame; extensions up to 40 s; SynthID on every video ([Omni docs](https://aistudio.google.com/docs/omni)) |
| **Veo 3.1** on the Gemini API | **Shut down 2026-10-22**; Omni Flash is the named replacement ([video docs](https://aistudio.google.com/docs/video)) | — | — |
| **Veo 3.1 via Runway API** | Available | 40 credits/s with audio ($0.40/s), 20 without ($0.20/s); `veo3.1_fast` $0.15 / $0.10 per second ([Runway pricing](https://docs.dev.runwayml.com/guides/pricing/), $0.01 per credit) | Per Runway's model docs (not checked here) |
| **Runway Gen-4 / Gen-4.5** (Runway API) | Available | `gen4_turbo` $0.05/s; `gen4.5` $0.12/s; `aleph2` $0.28/s | Not checked here |
| **Kling via Runway API** | Available | `kling3.0_pro` $0.12/s without audio, $0.17/s with; `kling_4` 1080p $0.188/s (discounted to 2026-11-30) | Not checked here |
| **Kling, direct API** | Kling's pricing page renders client-side and gave no readable prices. **USD price not verified.** | — | — |
| **Sora 2 / Videos API** (OpenAI) | **Shut down 2026-09-24**, no replacement listed ([deprecations](https://developers.openai.com/api/docs/deprecations)) | — | — |
| **Still images** for storyboards or backgrounds | Available | `gemini-nano-banana-2.1` $0.0336 (1K); `gemini-3.1-flash-image` $0.067 (1K) ([pricing](https://aistudio.google.com/docs/pricing)); Runway `gen4_image` 720p $0.05 | — |

At $0.10/s, an all-generated 60-second Short costs about $6 per attempt (at least two clips, since extensions reach 40 s at most) and a 10-second cutaway about $1 (illustrative, before retries).

**How Claude orchestrates generation.** Claude writes the shot prompt as structured output. Suggested fields: subject, one action, camera, style ID, reference-image ID, duration and whether audio is wanted. Python then calls the provider and polls the long-running job. Omni uses URI delivery for videos over 4 MB. Claude checks two or three extracted frames with vision against the beat, and the clip is placed as an ordinary `<video>` in the HyperFrames composition. Claude never touches the media itself.

## 5. YouTube policies that bear on this

| Policy | What YouTube says | Consequence for this project |
|---|---|---|
| **Altered or synthetic content disclosure** ([Help 14328491](https://support.google.com/youtube/answer/14328491)) | Disclose realistic AI-made or altered content: a real person saying or doing something they didn't, altered real events or places, realistic scenes that didn't happen. AI music that is the main focus is listed too. Non-realistic or animated content, AI help with a script or outline, captions and "Cloning one's own voice to create voice overs or dubs" are listed as not needing disclosure. Disclosure alone "won't limit a video's audience or impact its eligibility to earn money." YouTube may add a label itself, for example from C2PA metadata, and creators who repeatedly fail to disclose can be penalised. | The cartoon and stick-figure films need no disclosure. Any realistic generated cutaway (Omni, Veo, Kling) does, and C2PA metadata or YouTube's own detection may trigger an automatic label. TTS narration of a fictional or faceless narrator is not named either way; a synthetic voice of a real person would fall under the "real person" criterion. |
| **YPP "inauthentic content"** (renamed from "repetitious" on 2025-07-15) ([Help 1311392](https://support.google.com/youtube/answer/1311392)) | "Generic or repetitive content includes content that looks like it's made with a template." Named examples include "AI-generated content made with generic or unoriginal templates" and characters "put in the same situation over and over again with the same outcome". A section on "AI Personas Related to Sensitive Topics" covers content that "presents itself as a human expert providing advice". Its examples are an AI "doctor", "AI-generated podcast hosts offering financial guidance, investment tips, or wealth management advice", and AI personas giving legal advice. The same intro and outro across videos is fine if each video has a distinct story. Reused-content violations can remove monetization from the whole channel. | Mass output from one prompt and one kit is the risk. Rotate story structures and endings per episode. Keep the brief's original angle and sources, and keep a narrator who never poses as a credentialed financial or health adviser. |
| **Content ID and music** ([Help 2797370](https://support.google.com/youtube/answer/2797370), [Help 6013276](https://support.google.com/youtube/answer/6013276), [Audio Library](https://support.google.com/youtube/answer/3376882)) | Rights holders' reference files are matched automatically; owners can block, monetize or track. A claim is not a strike. Music downloaded from YouTube's Audio Library "won't be claimed", and YouTube says it isn't responsible for "royalty-free" music from elsewhere. | Keep the synthesised effects in `sound.py` (a past false claim prompted them). Prefer `safe_music/` or Audio Library tracks, and log each track's source. |

## 6. Recommendations for this project (ranked)

1. **Move script and vision calls to the Claude API with a key; keep the CLI as a fallback.** This addresses both 2026-11-04 failures: the shared subscription limit (§1, usage table) and the single 300 s subprocess with no Claude retry (`daily_shorts.ask` → `D:\MPT\app\services\llm.py`). Keep the existing OmniRoute fallback behind it. Use the Python SDK with explicit `model="claude-sonnet-5-5"` and `max_retries`, streaming for long replies, a Console workspace spend limit, and stop on spend-cap errors. If the account is Max or Ultra, link a Console organization so the $100/$200 monthly credits pay for it. MPT's `claude_code` adapter strips `ANTHROPIC_*`, so add a small direct-SDK path in the project's own `ask` helper rather than re-pointing MPT. MPT's LiteLLM adapter might reach Anthropic too, but its caching and structured-output pass-through were not checked.
2. **Ask for JSON with structured outputs.** Pass a schema for the outline, beat batches, short screenplay and topic list (`output_config.format`, or `--json-schema` on the CLI path). The "reply again with ONLY the valid JSON" loop in `lf_screenplay.py` becomes a rare fallback. Note the schema limits: no `minLength`, `minimum` or recursion.
3. **Cache the stable prefix in `write_beats`.** It calls Claude once per batch of 4 scenes, and every call repeats the cast, the full outline and the rules. Today `beats_prompt` opens with the per-batch line ("Write the script for scenes …"), so nothing can be cached. Reorder it: the stable cast, outline and rules go first as a system block with a `cache_control` breakpoint, and the scene IDs and the "last beats" tail go last. Later batches then pay 0.05× on that prefix, and it stops counting toward ITPM. Use the 1-hour TTL if a batch call can take longer than about 5 minutes. Expect savings only above the 512-token minimum, and verify with `cache_read_input_tokens`.
4. **Add a storyboard check before the full render.** Render one still per scene and per caption beat (HyperFrames snapshots or ffmpeg). Send them as a contact sheet to Haiku 5.5 for "blank, clipped, unreadable, off-palette" triage, then the flagged ones plus the beat text to Sonnet 5.5 for "does the picture match the line". A 40-frame Short costs about $0.01 on Haiku or $0.22 on Sonnet at 2,691 tokens per full frame. Shrinking frames to a contact sheet cuts that further. Keep counts and positions in `qa.py`, and keep the human gate.
5. **Resolve the voice licence before monetising.** Put Azure AI Speech behind the existing voice interface as the commercial path for the same `*MultilingualNeural` voices. The free tier covers about 60 ten-minute scripts a month at roughly 8,000 characters each (illustrative). Its word-boundary and viseme events fit `lf_voice.py`. Keep Kokoro as the local licensed fallback. Treat edge-tts as unverified for monetised uploads. Do not adopt Piper (personal/research use) or OpenAI TTS (shuts down 2027-01-06).
6. **Keep HyperFrames; update it and tune workers.** Move from 0.9.8 to the current release only after a matched test render. Measure `--workers` values against the 838 s record on this 15.6 GB machine at about 256 MB per worker. A Remotion or Revideo migration would cost a rewrite of `longform/kit` for no documented gain. Manim is worth a look only for a math-diagram scene type.
7. **Keep generated video off by default, and re-point the trial.** Sora and Veo-on-Gemini are gone, so any adapter should target Omni Flash (about $0.10/s, 9:16, SynthID) or one Runway model. Gate it with a per-video cap. Tick the disclosure box for any realistic shot, and record prompt, model and cost in the film record, as `VIDEO_GENERATION_PLAN.md` already requires.
8. **Write the YouTube rules into the brief and review page.** Vary structure and endings across a series, ban a narrator or character who poses as a doctor, financial adviser or lawyer giving advice, record each music track's source, and flag realistic synthetic shots for disclosure. These are the specific triggers in the YPP and disclosure pages, not AI use itself.
9. **Measure before budgeting.** Log `usage`/`total_cost_usd` and `request-id` per call for a week, then set the cap. Every cost figure above is list-price arithmetic, not a measured bill.

## Sources (all checked 2026-11-04)

### Anthropic
- [Models overview](https://platform.claude.com/docs/en/about-claude/models/overview), [Pricing](https://platform.claude.com/docs/en/about-claude/pricing), [Vision](https://platform.claude.com/docs/en/build-with-claude/vision), [Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [Batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing), [Structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs), [Errors](https://platform.claude.com/docs/en/api/errors), [Rate limits](https://platform.claude.com/docs/en/api/rate-limits), [Python SDK](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)
- [Claude Code headless](https://code.claude.com/docs/en/headless), [CLI reference](https://code.claude.com/docs/en/cli-reference), [Skills](https://code.claude.com/docs/en/skills), [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview)
- Support: [Claude Code with Pro/Max/Ultra](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-or-max-plan), [Agent SDK with your plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), [Monthly API credits](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-ultra-and-team-plans), [Max plan](https://support.claude.com/en/articles/11049741-what-is-the-max-plan)

### Renderers (GitHub API for licence, release and activity)
- [HyperFrames](https://github.com/heygen-com/hyperframes), [CLI docs](https://github.com/heygen-com/hyperframes/blob/main/docs/packages/cli.mdx)
- [Remotion LICENSE](https://github.com/remotion-dev/remotion/blob/main/LICENSE.md), [company pricing](https://www.remotion.pro/license), [render](https://www.remotion.dev/docs/render), [renderMedia](https://www.remotion.dev/docs/renderer/render-media)
- [Motion Canvas](https://github.com/motion-canvas/motion-canvas), [rendering](https://motioncanvas.io/docs/rendering)
- [Revideo](https://github.com/midrender/revideo)
- [Manim](https://github.com/ManimCommunity/manim), [configuration](https://docs.manim.community/en/stable/guides/configuration.html)

### Voices
- [edge-tts](https://github.com/rany2/edge-tts), [LICENSE](https://github.com/rany2/edge-tts/blob/master/LICENSE), [Microsoft Q&A 5925556](https://learn.microsoft.com/en-au/answers/questions/5925556/commercial-use-of-edge-read-aloud-voices-via-edge), [Microsoft Q&A 2088770](https://learn.microsoft.com/en-us/answers/questions/2088770/are-opensource-edge-tts-free-for-commercial-use)
- [Azure Speech pricing](https://azure.microsoft.com/en-us/pricing/details/speech/), [Azure retail prices API](https://prices.azure.com/api/retail/prices) (meter "S1 Neural Text To Speech Characters"), [Azure synthesis events](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-speech-synthesis), [Azure voice list](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support?tabs=tts)
- [Kokoro](https://github.com/hexgrad/kokoro), [Piper (archived)](https://github.com/rhasspy/piper), [piper1-gpl](https://github.com/OHF-Voice/piper1-gpl)
- [ElevenLabs with-timestamps](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps)
- [Gemini speech generation](https://aistudio.google.com/docs/speech-generation), [Gemini pricing](https://aistudio.google.com/docs/pricing), [Gemini rate limits](https://aistudio.google.com/docs/rate-limits)
- [OpenAI TTS guide](https://developers.openai.com/api/docs/guides/text-to-speech), [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations)

### Generation
- [Gemini Omni Flash](https://aistudio.google.com/docs/omni), [Gemini video (Veo shutdown notice)](https://aistudio.google.com/docs/video), [Runway API pricing](https://docs.dev.runwayml.com/guides/pricing/), [OpenAI pricing](https://developers.openai.com/api/docs/pricing)

### YouTube
- [Altered or synthetic content disclosure](https://support.google.com/youtube/answer/14328491), [YPP monetization policies](https://support.google.com/youtube/answer/1311392), [How Content ID works](https://support.google.com/youtube/answer/2797370), [Content ID claims](https://support.google.com/youtube/answer/6013276), [YouTube Audio Library](https://support.google.com/youtube/answer/3376882)

### Could not be verified
- Kling's own USD API prices: the page renders client-side.
- A Microsoft statement on commercial use of Edge Read Aloud voices: none found.
- Gemini TTS free-tier daily limit: not published outside AI Studio.
- An Azure clause specific to YouTube monetisation: not retrieved.
- Output rights for Gemini TTS audio under the Gemini API terms: not retrieved.
- Whether running one's own logged-in CLI from a personal app falls under the Agent SDK's third-party note: not stated.

### Project files read
- `D:\MPT\app\services\llm.py` (`claude_code` adapter, 300 s default, env scrubbing, `--safe-mode`)
- `daily_shorts.py` (`ask_vision`)
- `lf_screenplay.py` (`write_beats` batches, JSON retry)
- `narrate.py` (`WordBoundary`)
- `longform.py` (render command, `render_seconds`)
- `longform/node_modules/hyperframes/package.json` (0.9.8)
- `longform/films/*/film.json` and `longform/shorts/*/film.json` (render times)
