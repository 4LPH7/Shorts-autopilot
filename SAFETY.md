# Content safety rules

## What the automation enforces
- **Your approval first:** nothing is uploaded unless you approved it in the Review tab. MoneyPrinterTurbo's own auto-upload is forced off on every run, and the Setup tab warns if it's ever switched on.
- **Music:** MoneyPrinterTurbo's bundled "random" songs are never used (one triggered a Content ID block from HAAWK). Only tracks in `safe_music/` that are also listed in `safe_music/SOURCES.txt` are used. With no approved tracks, videos are voice-only. Music volume stays low (0.12 by default).
- **Footage:** real footage only (no animations), checked visually for relevance. Pixabay's license allows YouTube use, including monetized videos. Coverr (official API) and Vidsplay ask for a credit, so the description gets "Footage: Coverr (coverr.co)" or "Footage: Vidsplay.com" automatically when such a clip is used. Mixkit forbids bots, so Mixkit clips are only ever added by hand in the Clips tab.
- **Sound effects:** whooshes, hits and risers are synthesised in `sound.py` from noise and sine waves. Nothing is downloaded or sampled, so no one else holds rights to them. Stock effects libraries (Pixabay's included) are a known source of false Content ID claims, so none are used.
- **Voices:** narration comes from Microsoft's free neural voices through the same public service as the Edge browser's read-aloud, or from Kokoro (Apache-2.0) running on this PC. No voice is cloned from a real person.
- **Other people's videos:** the app never downloads videos or audio from YouTube, TikTok or similar sites (no yt-dlp). Reusing someone else's footage or sound is how claims and strikes happen. The only way a video you didn't make gets into a Short is the **Clips** page's *Shorts from a video you have the rights to*: it takes a file, never a link, refuses to start unless you say where the video comes from and confirm you may reuse it in monetized Shorts, and keeps that statement (and any credit line) in the Short's record and description. See below.
- **AI label:** every upload is marked as AI-generated (YouTube's altered or synthetic content disclosure).
- **Audience:** every upload is declared "not made for kids".
- **No double posts:** a run lock stops two runs from overlapping, and an upload whose outcome is unclear goes to `check/`. It's never retried automatically.
- **Topics:** never repeated (`topics_used.txt`).

## Adding music safely
1. In YouTube Studio, open **Audio Library** and filter for **attribution not required**.
2. Download the track, then add it with **Music → Add track...** in the app. You'll confirm the source and license.

The eight Mixkit tracks that came with the app are under the Mixkit Stock Music Free License. I could not read its full text when adding them, so read it at mixkit.co/license yourself and remove any track you're not comfortable with.

Never add songs ripped from YouTube or TikTok, "no copyright" compilations, or tracks from services that register Content ID (HAAWK, AdRev, Identifyy). Avoid anything labeled "free for creators" unless it comes with a written license.

## Cutting Shorts from a video
Good sources: your own recordings, your own long films (the Long video page), videos you were given written permission to use, and videos under a licence that allows reuse in monetized videos (Creative Commons with the credit line it asks for, public domain). Download those yourself from the site that offers them, then choose the file.

Not good sources, whatever the tool: a famous video, a movie scene, a music video, someone's podcast. Content ID matches the picture and the sound, the claim lands on your Short, and repeated claims become strikes. Downloading from YouTube also breaks YouTube's terms. YouTube's reused-content rules want real transformation (commentary, criticism, teaching), which a tool can't add for you, so an auto-cut of someone else's video is not that. The app's captions, effects and music change how a clip looks, not whose it is.

The Shorts it makes wait in Review like any other, with the source, the time range and your rights statement shown, and nothing posts until you approve it.

## If a claim still happens
- Check **YouTube Studio → Content → Copyright** regularly. A claim on a Short can block it worldwide.
- Find the track named in the claim and remove it in the Music tab.
- In Studio, trim, mute or replace the song with the editor, or delete and re-upload. Only dispute if you hold a license.

## YouTube rules to keep in mind
- **Repetitive or mass-produced content** can be demonetized. Keep scripts specific and factual, and vary the niche wording now and then.
- **Misleading claims:** scripts often cite studies, so read each script before approving it.
- **Finance niche:** facts and psychology only, never "buy this stock" advice.
- **Upload pace:** the default (10 a month, spread evenly) is far below YouTube's limits.
