# Shorts Autopilot

A Windows app that runs a faceless YouTube Shorts channel almost on its own. It writes and renders Shorts with [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo), waits for **your approval**, then uploads the approved ones through [Upload-Post](https://upload-post.com). Uploads are spread evenly so every free monthly upload is used, without long gaps.

![Dashboard](docs/screenshot.png)

## What it does

```
 Twice a day (Windows Task Scheduler)
 ┌──────────────────────────────────────────────────────────────────────┐
 │ 1. Upload    if an upload slot is due → post the oldest approved video │
 │ 2. Render    if fewer than 3 videos are waiting → make a new one:     │
 │              topic → script → search words → Pixabay clips (filtered) │
 │              → voiceover + captions + approved music → review/        │
 │ 3. Clean     delete MoneyPrinterTurbo caches older than 14 days       │
 └──────────────────────────────────────────────────────────────────────┘
          review/  ──you approve in the app──►  approved/  ──►  YouTube
```

- **Topics never repeat.** An LLM (Claude by default) picks a fresh topic in your niche every time.
- **Footage matches the script.** The script is written first, then short concrete search words are chosen per sentence. Each Pixabay clip's tags are checked by the LLM, and off-topic clips are dropped.
- **Readable captions:** bold font, large text, thick outline, centered so the Shorts UI doesn't cover them.
- **Copyright-safe music:** only tracks you've approved are used, otherwise voice only. See [SAFETY.md](SAFETY.md).
- **Approval required:** nothing is posted until you approve it.
- **Quota-aware schedule:** the remaining uploads are spread over the remaining run times of the month.

## Requirements

| What | Why | Cost |
|---|---|---|
| Windows 10/11, 8 GB RAM, ~10 GB free disk | rendering | - |
| [git](https://git-scm.com) and [uv](https://docs.astral.sh/uv/) | the installer uses them to set up MoneyPrinterTurbo | free |
| An LLM: [Claude Code](https://claude.com/claude-code) CLI (default, uses your Claude plan), or a DeepSeek / Gemini / OpenAI / OpenRouter key, or local Ollama | writes topics, scripts, search words, titles | plan or API cost |
| [Pixabay API key](https://pixabay.com/api/docs/) | stock footage (Pexels has paused new keys) | free |
| [Upload-Post](https://upload-post.com) account with your YouTube channel connected | uploading | free plan: 10 uploads a month |

## Install

1. Clone this repo, for example to `D:\PROJECTS\shorts-autopilot`.
2. *(Optional)* To keep MoneyPrinterTurbo somewhere other than `D:\MPT`, copy `env.example.bat` to `env.bat` and edit `MPT_DIR`.
3. Double-click **`install.bat`**. It:
   - clones MoneyPrinterTurbo **v1.3.9** into `MPT_DIR` (skipped if it's already there)
   - installs Python 3.11 and MPT's packages with uv
   - applies `patches/mpt-material.patch`
   - opens the app
4. In the app, open the **Setup** tab and work down the checklist until every row is green ✔:
   - **Script writer:** choose `claude_code` (no key) or a provider and paste its key, then **Save**.
   - **Stock footage:** paste your Pixabay key, then **Save**.
   - **Upload-Post:** tick Enabled, paste the API key and enter the **profile name**, then **Save**. The profile name is the user listed on Upload-Post's *Users* page (often `default`), not your email.
   - **Daily schedule:** click **Register / repair schedule**.
   - Click **Run full check**: it tests the LLM, footage and Upload-Post in about 20 seconds.
   - Click **Create desktop shortcut** if you like.
5. On the **Dashboard**, click **Render one video now** and review it once it's done (about 10–15 minutes).

Later, open the app from the desktop shortcut or **`Shorts Autopilot.bat`**.

## Using the app

| Tab | What you do there |
|---|---|
| **Dashboard** | Uploads used this month, the next upload slot, queue sizes, schedule state and the last run. **Alerts** flag anything that needs you, such as an upload due with nothing approved. The **upload calendar** shows every planned slot this month and next, and which approved video will go out. **Recent runs** shows each run's upload and render result. Buttons: Run now, Render one video now, Dry run. |
| **Review** | Videos waiting for approval, each with a thumbnail, a ▶ Play button, the script, and an editable **YouTube title, description and tags**. **Approve** moves it to the upload queue; **Reject** deletes it. The approved queue shows the upload order, and **Back to review** pulls one out. |
| **History** | Every upload (it counts against the quota), with status and Upload-Post request id. Uploads with an unclear outcome show under **Needs checking**: look in YouTube Studio, then mark **It's live** or **Not uploaded**. |
| **Music** | Your approved music list. **Add track...** asks for the source and a license confirmation. No tracks means voice-only videos. |
| **Settings** | Niche, language, voice, script rules, uploads per month, run times, number of videos to keep waiting, music volume, cache cleanup, YouTube privacy. Changing the run times re-registers the schedule. You can also pause or resume the schedule here. |
| **Setup** | Health checklist with a fix button on every row (see Install). |
| **Logs** | The full run log, with a *Problems only* filter. |

### Your routine
Every day or two, open **Review**, watch the new videos, fix titles if needed and **Approve** the good ones. The Dashboard turns red when an upload slot is close and nothing is approved.

## How upload spacing works

The task runs at each **run time** (default 09:00 and 19:00). On every run:

```
remaining = monthly_uploads - uploads already made this month
slots_left = run times left this month, including this one
upload now if  remaining >= slots_left               (must use every run to fit)
            or runs since the last upload >= slots_left / remaining
```

This spreads uploads evenly and uses the whole free quota. Example with 10 uploads a month:

| Month | Uploads |
|---|---|
| A full month (November) | 3, 6, 9, 12, 15, 18, 21, 23, 26, 28: about every 3 days |
| Joining late (9 left on 26 Oct) | 27 Oct, then 09:00 and 19:00 from 28 to 31 Oct |

If nothing is approved when a slot comes, that slot is skipped and later slots catch up. It never goes over the monthly limit. On a paid Upload-Post plan, raise **Uploads per month** in Settings.

## Files and folders

```
shorts-autopilot/
├─ Shorts Autopilot.bat     open the app
├─ install.bat              one-time setup on a new PC
├─ run_daily.bat            one run (Task Scheduler and the app call it)
├─ setup_schedule.ps1       registers the "MPT Daily Shorts" task
├─ autopilot_gui.pyw        the app (Tkinter)
├─ daily_shorts.py          the engine: all rules and logic
├─ patches/mpt-material.patch
├─ env.example.bat          → env.bat (your MPT folder; not committed)
├─ safe_music/SOURCES.txt   approved music list (audio files are not committed)
│
│  created while running (all git-ignored):
├─ review/  approved/  posted/  check/     videos (.mp4 + .json metadata)
├─ uploads.json             upload ledger (drives the quota)
├─ topics_used.txt          topic history (no repeats)
├─ settings.json            your Settings tab values
└─ logs/daily.log, logs/runs.jsonl, .thumbs/
```

Each video is an `.mp4` plus a `.json` with `topic`, `title`, `description`, `tags`, `music`, `script` and `rendered`. You can edit the JSON by hand too.

## Settings reference (`settings.json`)

| Key | Default | Meaning |
|---|---|---|
| `niche` | money psychology and surprising personal finance facts | what every video is about |
| `language` | `en-US` | script and metadata language |
| `voice` | `en-US-ChristopherNeural-Male` | Edge TTS voice (free) |
| `script_rules` | 120–140 words, hook first, end with a question | instructions for the script writer |
| `monthly_uploads` | `10` | Upload-Post plan limit |
| `run_times` | `["09:00", "19:00"]` | when the task runs |
| `buffer` | `3` | stop rendering once this many videos are waiting |
| `music_volume` | `0.12` | background music level |
| `clean_after_days` | `14` | delete MPT caches older than this (0 = never) |

MoneyPrinterTurbo's own settings (LLM, keys, Upload-Post, privacy) live in `MPT_DIR\config.toml`. The Setup tab edits them safely: it reads the file fresh and changes only the needed keys.

## Command line

Run from the MPT folder with MPT's Python, or simply through `run_daily.bat`:

```bat
run_daily.bat              :: a normal run (what the schedule does)
run_daily.bat --dry-run    :: show what would happen, change nothing
run_daily.bat --render     :: render one video now, never uploads
run_daily.bat --doctor     :: JSON health report
python daily_shorts.py --self-test      :: logic tests (no MPT needed)
python autopilot_gui.pyw --screenshot out.png [Tab]   :: app smoke test
```

## MPT patch

`patches/mpt-material.patch` makes two small changes to MoneyPrinterTurbo's Pixabay search:
1. **Real footage only** (`video_type=film`): no cartoons.
2. **Keeps each clip's tags**, so the relevance filter can check them.

Updating MoneyPrinterTurbo (for example with `git pull`) can undo it, and the Dashboard will then show a warning. Click **Setup → Apply patch**. If MPT's code changed too much, the patch won't apply cleanly; re-make the two edits by hand in `app/services/material.py` (search for `"video_type"` and `"asset_id"`). Without the patch everything still works, but footage can include animations and the tag filter is off.

## Troubleshooting

| Problem | Fix |
|---|---|
| Settings you saved get reverted | MoneyPrinterTurbo's WebUI (port 8501) rewrites `config.toml` from memory. Close it while using the automation; the Setup tab warns when it's open. |
| A key typed into MPT's WebUI doesn't save | WebUI text fields only save when you press Enter or click away. Prefer the Setup tab. |
| "Pexels key issuance paused" | Use Pixabay (the default here). |
| Footage repeats or looks random | Run **Setup → Run full check**: Pixabay should find sample clips, and the patch must be applied. Some niches simply have little vertical stock footage. |
| An upload is in **Needs checking** | The connection dropped mid-upload. Look in YouTube Studio, then click *It's live* or *Not uploaded*. It's never retried automatically, so you don't get double posts. |
| A Short got a copyright claim | See [SAFETY.md](SAFETY.md): remove the track in the Music tab and fix the video in Studio. |
| Nothing ran at 09:00 | The PC must be on or asleep (it wakes for the task), not shut down. A missed run starts when the PC comes back. Check **Settings → Schedule** and **Logs**. |
| "Another run is in progress" | Normal when a manual run overlaps a scheduled one. Only one runs at a time. |
| Disk filling up | MPT caches are cleaned after `clean_after_days`. Posted videos stay in `posted/`; delete old ones when you like. |

## Credits and license

- Video generation: [MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo) by harry0703 (MIT). The patch in `patches/` modifies its code.
- Footage: [Pixabay](https://pixabay.com/service/license-summary/). Uploading: [Upload-Post](https://upload-post.com).
- Shorts Autopilot is MIT licensed, see [LICENSE](LICENSE). Use it within YouTube's policies; you're responsible for what your channel posts.
