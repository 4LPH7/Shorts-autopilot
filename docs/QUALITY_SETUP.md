# The best-quality setup

**Built:** 2026-11-04. **Status:** in the code, self-tested, and run once end to end (see *What was verified*). This page is the
practical guide; the earlier research pages ([quality methods](RESEARCH_AI_VIDEO_AUTOMATION_QUALITY.md),
[free workflows](RESEARCH_FREE_SHORTS_AND_LONG_VIDEO_WORKFLOWS.md), [upgrade plan](VIDEO_GENERATION_PLAN.md)) still hold; this one
turns them into a working pipeline and says what it costs.

## Why the videos looked cheap

Three things, in order of how much they hurt:

1. **A montage of unrelated stock clips.** Every beat was a different Pixabay clip, shot by a different person, with a different
   colour, lens and subject. However well Claude picked them, the video read as "stock slideshow", and the vision picks cost minutes.
2. **The voice.** `en-US-GuyNeural` (and the other free Microsoft voices) is the single most recognisable "made by a bot" tell on YouTube.
3. **Long films drawn as flat vector rooms with stick figures**, spoken by the same free voices.

## What is built now

| Layer | File | What it does |
|---|---|---|
| Providers | `genmedia.py` | One small API over MuAPI (images, image-to-video), Gemini (images, voices), ElevenLabs and MiniMax (voices) and the free Pollinations image service. Standard library only, so both Python environments can use it. Every paid call lands in `logs/genmedia.jsonl` with its cost; a per-video budget (`gen_budget_usd`) stops runaway spend. |
| Pictures | `visuals.py` | **Cinematic mode:** the LLM writes a shot list (one shot per voiceover beat, varied framing, continuity), every shot becomes a keyframe in one *style pack* (cinematic photoreal, dark noir, natural documentary or editorial illustration), and every keyframe is filmed for exactly the beat's length with an eased camera move, never a still. The result cuts, grades and captions through the existing `motion.py` pass, so loudness, captions, sound effects and QA are unchanged. |
| Voices | `narrate.py`, `voices.py`, `sound.py` | Three premium engines next to Edge and Kokoro: **Gemini** (30 voices, told how to read in plain words), **ElevenLabs** (word timing from the API) and **MiniMax**. Premium voices speak the whole script in **one request**; Whisper then times every word and checks every sentence against the script, exactly as before. Each engine has its own mastering chain. |
| Long films | `lf_voice.py`, `longform.py`, `lf_plan.py`, `lf_build.py`, `longform/kit` | The cast speaks in the premium engine chosen in Settings (one distinct voice per character type), except Gemini: a film needs one request per sentence, so when the Shorts use Gemini the films speak with Edge (`film_voice_engine` in `longform.py`; switch it there once billing is on). Every room gets a **generated background** (painted or photographic) behind the animated characters instead of the flat vector room. Scenes where someone sits or lies down keep the vector room, because its furniture is where the character is placed. |
| App | `autopilot_gui.pyw` | Settings → **Pictures** (visuals, style, provider, budget, long-film rooms) and **Delivery** (how the voice reads); Setup → **Pictures and voices** (MuAPI and Gemini keys, spend in the last 30 days). `--doctor` reports the providers. |

The old stock path is still there (`Visuals = Stock footage`), and it is the automatic fallback whenever no picture can be made.
**Hybrid** keeps stock clips and generates a picture only for the beats no clip fits.

## What to enable, in order of payoff

| Step | Cost | What it unlocks | How |
|---|---|---|---|
| 1. Gemini voice (already on) | free | A real narrator instead of Guy. The free tier allows **10 requests a day per model**; one Short is one request, so two renders a day fit. `voice_style` in Settings is the delivery note the voice follows. | Done: `voice_engine = gemini`, `voice = Charon`. Audition the others with **Audition voices** (Algenib, Orus, Enceladus, Sulafat are the strongest for this niche). |
| 2. **MuAPI credits** | about **$5** lasts roughly 700 keyframes (45 Shorts) at the default `z-image-turbo` ($0.007 a picture) | Fast, sharp keyframes (4-10 s each, in parallel). Your MuAPI key is already in MoneyPrinterTurbo's config; the account has **no credits**, so today the free service fills in. | Top up at https://muapi.ai/dashboard. Nothing else to change. |
| 3. Gemini billing | pay as you go (a Nano Banana picture is about $0.04; TTS about a cent a Short) | Gemini's own image models (`gemini-2.5-flash-image` and the Nano Banana family) and the end of the 10-a-day voice cap (long films would need it, one request per sentence; they use Edge until `film_voice_engine` is switched to Gemini). | Enable billing on the key's project in Google AI Studio. The code already prefers MuAPI for pictures and Gemini for voices. |
| 4. ElevenLabs key (optional) | from about $5 a month on their starter plan | The most natural narration available, with word timing straight from the API (no Whisper estimate). | `ELEVENLABS_API_KEY` in the environment, or `elevenlabs_api_key` in `config.toml`; `voice_engine = elevenlabs`, `voice = George` (or any voice id). |
| 5. Hero clips (later) | $0.10-0.18 per 5 s clip on MuAPI (`seedance-lite-i2v`) | Real motion on two or three beats a video instead of a camera move over a still. `genmedia.muapi_i2v()` is written but **has not run** on this account (no credits). | Fund MuAPI, then wire `hero_clips` when you want it. |

### Free-tier reality (what runs with no money at all)

| Service | Free | Limit | What the pipeline does |
|---|---|---|---|
| Gemini TTS | yes | 10 requests a day per model | Whole script in one request; a poor match is retried once (two requests at most). |
| Gemini images | no (`limit: 0` on the free tier) | | Skipped for the rest of the video after the first refusal. |
| MuAPI | no (credits) | | Skipped for the rest of the video after `INSUFFICIENT_CREDITS`. |
| Pollinations | yes | one picture every 45 s per address, a small logo in the corner | Frames are made one at a time (about 12 minutes for a Short) at extra height, and the logo band is cropped off. Softer than the paid models. |
| Edge / Kokoro voices | yes | | The previous engines, still available. |

## How a Short is made now

```
topic -> script (Claude) -> narration: Gemini/ElevenLabs/MiniMax, one request, Whisper word timing + script check
      -> beats from the sentence timing
      -> shot list (Claude): one shot per beat, framing, continuity, a camera move
      -> keyframes: MuAPI -> Gemini -> Pollinations, in one style pack, cached in work/<video>/keyframes/
      -> each keyframe filmed for the beat's length with an eased push/pull/slide (never a hold)
      -> captions, look, synthesised sound effects, ducked music, -14 LUFS, QA (motion.py, sound.py, qa.py: unchanged)
      -> review/  (the JSON records visuals: mode, style, provider, cost, borrowed beats)
```

Timing on this PC with MuAPI funded: narration 15-40 s, keyframes 1-2 min, cutting 1 min, final pass 1 min. With only the
free image service: add about 12 minutes of waiting.

## Settings added

| Key | Default | Meaning |
|---|---|---|
| `visual_mode` | `cinematic` | `cinematic` (generated keyframes), `stock` (clips, the old way), `hybrid` (clips, a generated picture where none fits) |
| `visual_style` | `cinematic` | `cinematic`, `noir`, `documentary`, `illustrated`: the style pack every picture shares |
| `image_provider` | `auto` | `auto` tries every provider with a key, the free one last; or `muapi`, `gemini`, `pollinations` |
| `image_model` | blank | a provider's endpoint or model name (MuAPI default `z-image-turbo`; try `nano-banana-2-lite`, `seedream-5.0`, `flux-2-pro`) |
| `gen_budget_usd` | `1.0` | the most generated media may cost per video (a long film gets three times this) |
| `voice_engine` | `edge` in the defaults, `gemini` on this PC | `gemini`, `elevenlabs`, `minimax`, `edge`, `kokoro`, `mpt` |
| `voice_style` | documentary narrator | how a Gemini voice reads, in words (ElevenLabs and MiniMax ignore it) |
| `voice_model` | blank | a premium engine's model (Gemini: `gemini-2.5-flash-preview-tts` follows the delivery note; the 3.x TTS models read it aloud, so they get the bare text) |
| `lf_backgrounds` | `painted` | `painted`, `photo` or `off`: generated backgrounds in long films, from a paid picture service only (on the free one films keep their drawn rooms: it ignored the painted style, sent 1024x576 pictures and stamped its logo) |

## What was evaluated

Trendshift's front page and its [AI video topic](https://trendshift.io/topics/ai-video), checked on 2026-11-03, plus the skills
marketplace (skills.sh and claude-plugins). Decisions, with the reason:

| Found | What it is | Decision |
|---|---|---|
| [mromidev/claude-animated-shorts](https://github.com/mromidev/claude-animated-shorts) (1,000 stars in four days) | A Claude skill for animated story Shorts: 2D characters in a three.js world, rendered with Remotion. The format is hot (a creator cited in its social mentions went from 50k to 130k subscribers in 26 days with it). | Not adopted now: it is a *story* format with its own Remotion render stack, not an explainer. A second lane worth a pilot if the channel wants narrative Shorts; the technique (one fixed cast, a world, a twist) is also what the long films do. |
| [edenfunf/reelmimic](https://github.com/edenfunf/reelmimic) (1.8k) | "Show it a video you love, get a new video in the same style": an agent crew rebuilds someone else's video. | Not used: it starts from other people's videos (see SAFETY.md). |
| [Pika-Labs/Pika-H3-Flex](https://github.com/Pika-Labs/Pika-H3-Flex), Kinoloom, H3 ComfyUI nodes | Local video and audio generation models. | Need an NVIDIA card; this PC has Intel Iris Xe. Hosted generation through MuAPI gives the same models (Seedance, Hailuo, Kling, Veo) per clip. |
| "Faceless 9:16 explainer reels in a cut-paper style, free, local, no API keys" (Claude skill on the topic page) | Voice-timed scenes drawn in code. | The idea is the `illustrated` style pack; a code-drawn cut-paper look could be a fifth pack later. |
| "AI 动画单元剧" (fixed characters, a storyboard grid generated in one shot with Seedance) | Character consistency by generating a character sheet and all storyboard frames in one image. | Noted for the long films: one sheet per cast would keep generated cutaways consistent. Not built. |
| MoneyPrinterTurbo, Vibe Knowledge, Digital Human Koubo, SenseNova Code2Video | Already in use / ideas already in the plan / talking heads / a 27B model | As decided in the earlier research. |
| Skills: `101-skills/ai-video-generation` (944k installs), `elevenlabs/text-to-speech` (18k), `heygen-com/media-use` (1.26M, installed), `higgsfield-youtube-thumbnail` (112k), `j8647877-hash/youtube-shorts-creator` (Veo + Nano Banana + Gemini TTS + Ken Burns), `fal-ai-community/fal-generate` (installed) | Agent-time instructions for the same providers. | None installed: a skill is advice for an agent session, not code the scheduler can run at 09:00 unattended. `genmedia.py` makes the same REST calls directly. `youtube-shorts-creator` is the same recipe as the cinematic mode (Gemini pictures + Ken Burns + Gemini TTS), which is a useful confirmation. fal.ai would need a `FAL_KEY`; MuAPI was chosen because its key is already in the config. |
| MuAPI's catalogue (791 models, read from its `/models` endpoint) | Images from $0.003 (`flux-schnell`) to $0.12 (`nano-banana-pro`); image-to-video from $0.06; Suno and Lyria music from $0.04. | `z-image-turbo` as the default picture model (fast, photoreal, $0.007); `seedance-lite-i2v` for hero clips later; Suno/Lyria music is a possible replacement for the eight Mixkit tracks (not built). |

## What was verified

- `python daily_shorts.py --self-test` passes, including a filmed keyframe that `freezedetect` does not read as frozen, the shot-list
  parsing, the camera-move planner (never two zooms in a row, never a hold), gap filling, and the new settings checks.
- Gemini TTS, live: the 2.5 TTS model follows the delivery note; the 3.8 model reads it aloud (so it only gets the bare text); the
  whole-script mode timed 46 words over 14 s with every sentence matching the script.
- Gemini images, live: refused on this key (`limit: 0`, free tier). MuAPI, live: key valid, `INSUFFICIENT_CREDITS`. Pollinations, live:
  one 1080x2048 picture in 12 s, then a 45 s wait between pictures.
- The app renders the Settings and Setup pages with the new fields.
- **An end-to-end Short on a fixed script** (`work/_probe/e2e3/final.mp4`, 45 s, 1080x1920): Gemini narration (Charon), shot list
  from Gemini text, 7 keyframes from the free service (MuAPI refused for lack of credits and was skipped for the rest of the video),
  21 filmed cuts, captions, music, -14 LUFS. Every QA check passed except one narration flag that came from a voice report made
  before the contraction fix in `spoken_match` ("They're" heard as "They are").
- Fixed along the way: MuAPI's 1536 px size cap, Pollinations' rate limit being treated as a refusal (keyless calls are now serialised
  46 s apart), concat lists with relative paths, too-dark style prompts (the cinematic pack now asks for a well-exposed subject, and the
  live look is *Clean* because the pictures already carry a grade), no character continuity (the shot list now repeats one full
  description of a recurring person), and blurry fallback shots (a missing shot is now another angle of its neighbour).
- **A real `--render` could not run from this session:** the Claude CLI said "Not logged in" here and OmniRoute was not running. If the
  scheduled 09:00 run fails the same way, run `claude` once and log in (or start OmniRoute).

## Not done, and why

- **Image-to-video hero clips, ElevenLabs and MiniMax voices** are written against their documented APIs but have not run here: no
  credits, no keys. They are off by default; the first run of each is a test, not a production video.
- **Veo** is not on this Gemini key. If it appears after billing is enabled, `genmedia` can take a `veo` branch next to MuAPI's.
- **Gemini 3.x TTS models** cannot take a delivery note yet (the API rejects a system instruction and reads an inline one aloud).
- **Long films with Gemini voices** need the paid tier (a film is a few hundred requests). Edge remains the default for films until then;
  the app says so in the error if the quota runs out.
- **Generated music** (Suno, Lyria through MuAPI) was not wired: the approved Mixkit tracks work and are claim-safe.
