# Free Shorts and long-form video workflows

**Research snapshot:** 2026-11-03  
**Question:** Which genuinely free tools and workflows can support Shorts and long-form videos, and which claims in the supplied notes need qualification?  
**Source standard:** Vendor documentation, official repositories, licenses, and platform policies. Pricing and quotas are a dated snapshot and should be rechecked before using an external service.

## Executive findings

- The project already has separate production paths for vertical Shorts and 8-10 minute 16:9 explainers. Keep those paths. There is no need to add a second long-form renderer or replace the existing pipeline to get the main benefits described in the pasted text.
- The most dependable no-subscription workflow is to use the project's existing local render and review steps, use a recorded voice or an already configured voice option, and use footage that is either owned or explicitly licensed. External script, voice, and video APIs can still cost money or have usage limits.
- Hosted clipper free plans are mostly evaluation plans: they cap upload time or storage, add watermarks, block downloads, or offer only one trial. They are not a dependable free publishing pipeline.
- A repo's open-source license covers its code, not necessarily an inference API, voice, stock clip, or generated media. Check each layer separately.
- The pasted claim that platforms generally demote AI content is too broad. YouTube's policy targets mass-produced or repetitive content with little original value; AI use alone does not make content ineligible. YouTube also requires disclosure for realistic synthetic or meaningfully altered content. TikTok requires labels for realistic AI content; its help page says the label itself does not affect distribution when the content follows its rules. ([YouTube monetization policy](https://support.google.com/youtube/answer/1311392), [YouTube AI disclosure](https://support.google.com/youtube/answer/14328491), [TikTok AI content policy](https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content))

## Existing project baseline

This was a read-only review of the current checkout.

| Path | Existing role | Research implication |
|---|---|---|
| [daily_shorts.py](../daily_shorts.py), [motion.py](../motion.py), [README.md](../README.md) | MoneyPrinterTurbo-backed Shorts production, voice and captions, local FFmpeg motion, safe-media handling, review and approval. | Keep it as the primary vertical workflow. A new all-in-one generator would duplicate working features and introduce another provider and another failure path. |
| [longform.py](../longform.py), [longform_page.py](../longform_page.py), [lf_screenplay.py](../lf_screenplay.py), [lf_plan.py](../lf_plan.py), [lf_voice.py](../lf_voice.py), [lf_build.py](../lf_build.py), [lf_finish.py](../lf_finish.py), [longform/kit](../longform/kit) | Resumable 8-10 minute 16:9 explainer pipeline. It creates a screenplay and beat plan, voices lines, renders animated scenes with HyperFrames/GSAP, mixes audio, checks the finished film, and queues it for review. Google Vids cutaways are optional and added manually. | Keep this as the long-form workflow. The opportunity is to improve topic research, source notes, scene fit, voice review, and optional repurposing of the finished film into Shorts, not to build a second renderer. |
| [footage.py](../footage.py), [sound.py](../sound.py), [qa.py](../qa.py) | Existing footage sources, synthesized sound effects, audio mastering, and quality checks. | Keep provider calls optional and retain human review before publishing. Add source/license metadata when selecting any new stock asset. |

The local project can render without buying a hosted video-generation subscription, but that does not make every configured script or voice provider free. Verify the selected provider and quota before automated runs. Do not put unpublished scripts or private source material into a free API tier until its data terms are acceptable.

## Ranked choices for this project

The ranking is by fit for the current Windows/Python application, repeatable no-cost use, rights clarity, and amount of duplicated work. It is not a ranking of video quality or popularity.

| Rank | Option | What is free, and what is not | Recommendation |
|---:|---|---|---|
| 1 | Existing Shorts and long-form pipelines | Local orchestration/rendering is already in the project. Script-writing APIs, online voices, uploaded/generated assets, storage, and publishing integrations may have separate limits or costs. | Use as the default. First record which configured providers are being called and what they cost. Make a real no-spend episode using a human-written script, recorded narration, local render, and reviewed free-license footage. |
| 2 | Pexels and Mixkit Free License assets | Pexels allows free commercial use without attribution, subject to restrictions such as no implied endorsement and limits around identifiable people/brands. Mixkit has separate Free and Restricted stock-video licenses; only its Free License permits commercial use. ([Pexels license](https://www.pexels.com/license/), [Pexels commercial-use FAQ](https://help.pexels.com/hc/en-us/articles/360042295214-Can-I-use-the-photos-and-videos-for-a-commercial-project), [Mixkit license](https://mixkit.co/license/), [Mixkit Free stock-video license](https://mixkit.co/license/modal/videoFree/)) | Continue the existing sources. Save the source URL, asset ID, and license class with each selected clip. Do not treat a whole catalog as having one blanket license. |
| 3 | OpenShorts, self-hosted (`mutonby/openshorts`) | The core repo is MIT licensed and supports long-to-short clipping, transcription, reframing, captions, and an Ollama option. Its docs list Docker, 8GB+ RAM, and a typical CPU processing time of 5-8 minutes for an 8-minute video. Gemini, ElevenLabs, fal.ai, and Upload-Post are external services/keys for their respective features. The `cloud/` directory has a separate commercial license and is not MIT. ([repository](https://github.com/mutonby/openshorts), [license exception](https://github.com/mutonby/openshorts/blob/main/cloud/LICENSE)) | Best candidate to study for a future long-to-short feature, but do not copy or deploy the whole application as the new core. First prototype a local clip-selection/reframe stage against the project's own rendered long-form files. Do not use it to download other creators' YouTube videos without rights. |
| 4 | Video-Use (`browser-use/video-use`) | The editing skill is MIT licensed and describes transcript-first editing, cut decisions, subtitles, overlays, and rendered-output self-review. It is an editing agent workflow, not a complete free content factory; the coding agent/model used to run it may have its own plan or API costs. ([repo and license](https://github.com/browser-use/video-use), [skill instructions](https://github.com/browser-use/video-use/blob/main/SKILL.md)) | Borrow the audio-first review and self-evaluation ideas. The current project already has transcript/beat timing, render checks, and approval gates, so adding another agent runtime is low priority. |
| 5 | AI-Youtube-Shorts-Generator (`Anil-matcha`) | MIT code for turning existing long-form video into clips, but its README requires an OpenAI API key. The repo being free does not make the API free. ([repo](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator), [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)) | Use as an implementation reference only. It overlaps with the repurposing feature better handled inside the existing application. |
| 6 | Agnes Video Generator | MIT application that calls Agnes AI services using an API key; its own project docs claim the API is free and has no usage limits, while its features documentation describes a shared rate limiter. This is a hosted-model dependency, not offline generation, and the project source alone does not establish a durable free quota or commercial output rights. ([repo/license](https://github.com/lcy362/agnes-video-generator), [API-key setup](https://github.com/lcy362/agnes-video-generator/blob/master/docs/public/getting-started.md), [rate-limited feature description](https://github.com/lcy362/agnes-video-generator/blob/master/docs/public/features.md)) | Treat as an experiment only after reviewing the current Agnes API terms, privacy policy, model availability, and output rights. Do not make production depend on a vendor's unsupported promise of unlimited free generation. |
| 7 | Clipchamp Free | Microsoft's current page says free users can export unlimited videos up to 1080p without a watermark and includes basic editing, AI subtitles, voiceovers, and silence removal. ([official pricing](https://clipchamp.com/en/pricing/)) | Good manual fallback for occasional editing or a human finishing pass. It is not a replacement for the project's resumable, unattended render pipeline. |
| 8 | n8n Community Edition | Free self-hosted use is allowed for internal workflows under n8n's Sustainable Use License. This is not the same as an OSI open-source license; hosting it as a service or letting outside users configure workflows requires a commercial license. ([n8n license FAQ](https://support.n8n.io/article/can-i-use-your-license-for-my-use-case)) | No need to add it now. The project already has Python orchestration and Windows Task Scheduler. Consider only if external webhooks or multi-service workflow editing becomes a real need. |

### Ambiguous or separate repository names

- Several unrelated GitHub projects use the name `OpenShorts`. The product linked to `openshorts.app` is `mutonby/openshorts`; do not assume similarly named repositories share its code, license, or cloud service. ([mutonby repository](https://github.com/mutonby/openshorts), [another independent OpenShorts repo](https://github.com/bogdan-dilaj/openshorts))
- `Clap.app` is not a reliably identified product in the supplied notes. The matching clipper appears to be **Klap** at `klap.app`; the same search also returns unrelated products named Clap or ClapClip. Treat the pasted name as a likely typo and confirm the exact domain before connecting an account.
- `AutoShorts.ai` and `AutoShorts.app` are different services. Do not merge their plans or feature descriptions.
- The supplied name `Cance` could not be confidently identified as a video-generation API from an authoritative first-party source. Leave it out of an integration plan until a correct vendor or repository link is supplied.

## Free hosted tools: useful for trials, weak as a production foundation

| Product | Current first-party free offer or limitation | Practical verdict |
|---|---|---|
| OpenShorts Cloud | First source video up to 60 minutes, then 20 source minutes/month; free outputs are watermarked. Paid plans start at $12/month for 100 minutes without a watermark. ([official pricing](https://www.openshorts.app/pricing)) | Useful to evaluate the clip-selection quality on one owned video; not a clean, recurring free publishing route. |
| OpusClip | Free plan lists 60 credits/month, a watermark, no editing, and exports available for three days. ([official pricing](https://www.opus.pro/pricing)) | Good for a short comparison test, not for a watermark-free production line. |
| Exemplary AI | Its English pricing page currently lists 60 upload minutes/month, 14-day data retention, and 20 AI content generations on Free. Export resolution and watermark conditions are not clear in that page's comparison; regional versions show different allowances. ([official pricing](https://exemplary.ai/pricing), [localized pricing example](https://exemplary.ai/es/precios)) | A one-off test is reasonable; verify actual download, watermark, and retention behavior before investing in a workflow. The pasted claim of "200 free credits" was not confirmed on the current English pricing page. |
| Choppity | Free lists one hour of AI analysis and 2GB storage, but no clip downloads or scheduling; project storage is short. ([official pricing](https://www.choppity.com/pricing/), [plan details](https://help.choppity.com/en/articles/7110470-plans-and-pricing-explained)) | Preview and edit a clip, but the free tier cannot complete a publishable export. |
| Klap | Official pages conflict: its clip-generator page advertises one free video with no watermark, while the homepage describes preview/edit on the free trial and says downloading/posting requires a paid plan. ([clip-generator page](https://klap.app/tools/ai-clip-generator), [homepage FAQ](https://klap.app/)) | Treat as a trial only; verify that an export file can actually be downloaded before using it in a plan. Paid pricing is subscription-based. |
| AutoShorts.ai | Its own pricing page shows a $0 plan for one video but marks it "Temporarily paused"; paid posting-frequency plans start at $19/month. ([official site](https://autoshorts.ai/)) | The pasted free offer is currently paused on this domain. |
| AutoShorts.app | Separate product; advertises three free clips, watermarked and limited to 15-minute source videos at 720p. ([official site and terms](https://www.autoshorts.app/en)) | A trial, not unlimited no-watermark publishing. |
| InVideo AI vs InVideo Editor | InVideo AI's own help says free credits are limited and reset weekly, while a separate pricing page shows watermarked export limits and no generative features; its editor's manual timeline editing and exports are free, but AI agent work/media generation use credits. ([AI free plan help](https://help.invideo.io/en/articles/9380226-can-i-use-invideo-ai-for-free), [AI pricing](https://invideo.io/pricing/), [editor credit guide](https://help.invideo.io/en/articles/11528140-invideo-plans-and-credits-everything-you-need-to-know)) | Distinguish the free manual editor from metered AI generation. The official pages differ, so check the signed-in plan and credit display before a run. |
| Canva | Magic Video can assemble user-provided clips/photos into a 60-second video and is included with Canva plans; prompt-generated Canva AI video is an 8-second clip and plan access/usage is limited. Canva says AI output may not be exclusive or cleared for every commercial use. ([Magic Video help](https://www.canva.com/help/magic-video/), [AI video help](https://www.canva.com/help/video-clip/), [content license](https://www.canva.com/en_in/policies/content-license-agreement/)) | Useful for a manual template-based one-off; not a free unlimited text-to-finished-video API. |
| CapCut | Auto captions are available on desktop/web/mobile, but features vary by region/version. CapCut says only materials expressly marked "Commercial Use" may be used commercially. ([caption help](https://www.capcut.com/help/how-to-recognise-subtitles), [CapCut legal terms](https://www.capcut.com/trust/legal)) | Acceptable as a manual editor if every template/music/asset used is cleared for the intended commercial use; not a needed project dependency. |

## Free is conditional: API, voice, and generation costs

- Gemini API has a limited free tier for selected models. Google says Free-tier content may be used to improve its products, while Paid-tier content is not used for that purpose. Check the chosen model's quota, region, and data handling before calling it from an automation job. ([Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing), [billing/data terms](https://ai.google.dev/gemini-api/docs/billing))
- Anthropic's API uses prepaid usage credits; a Claude consumer subscription does not include API use. ([Anthropic API billing](https://support.anthropic.com/en/articles/8977456-how-do-i-pay-for-my-api-usage), [Claude plan vs API explanation](https://support.anthropic.com/en/articles/9876003-i-subscribe-to-a-paid-claude-ai-plan-why-do-i-have-to-pay-separately-for-api-usage-on-console))
- OpenAI API models and tools have usage pricing. A limited API-credit benefit is tied to certain paid ChatGPT Pro/Business subscriptions and eligibility; it is not a universal free API allowance. ([API pricing](https://developers.openai.com/api/docs/pricing), [subscription credit conditions](https://developers.openai.com/api/docs/guides/chatgpt-api-credits))
- Replicate charges by model and usage; video models can be billed per output second. For example, its current pricing lists Wan image-to-video models at $0.09 or $0.25 per second of output. ([official pricing](https://replicate.com/pricing))
- ElevenLabs' free tier can generate audio, but its docs say free-tier output is for non-commercial use with attribution; commercial rights are included when generating on paid plans. ([billing and license notes](https://elevenlabs.io/docs/overview/administration/billing))

Therefore, avoid a workflow described as "free" if it actually means free code plus an external API, free trial credits, or a watermark-bearing export. Keep API use behind per-run estimates, a hard cap, and an opt-in setting.

## Rights and platform-policy corrections

1. **Only clip material you can use.** YouTube's terms restrict downloading or otherwise using service content except where the service permits it, you have prior written permission, or applicable law allows it. YouTube API developer policy separately prohibits API clients from downloading/importing/caching audiovisual content without YouTube's prior written approval. Feed the clipper an original source file or material you are licensed to reuse; do not make generic YouTube URL downloading the default. ([YouTube Terms](https://www.youtube.com/t/terms), [YouTube API audiovisual-content policy](https://developers.google.com/youtube/terms/developer-policies#handling-youtube-data-and-content))
2. **Originality matters more than whether a tool uses AI.** YouTube's current monetization policy calls mass-produced/repetitive low-value work "inauthentic content" and requires original, authentic work. Reused clips may be eligible when the creator adds significant commentary, substantive modification, or educational/entertainment value, but copyright still applies. The policy does not say that AI alone triggers demonetization or a ranking penalty. ([YouTube monetization policy](https://support.google.com/youtube/answer/1311392), [YouTube clarification](https://support.google.com/youtube/blog/356734251/response-to-creator-questions-about-ypp-policies-july-2025))
3. **Disclose realistic synthetic depictions.** YouTube requires disclosure for realistic AI-generated or meaningfully altered depictions of real people/events/places; minor production assistance and non-realistic animation are not listed as requiring disclosure. TikTok requires a label for realistic AI-generated images/audio/video and says applying its AI label alone does not affect distribution when the post follows its rules. ([YouTube disclosure rules](https://support.google.com/youtube/answer/14328491), [TikTok AI-generated content rules](https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content))
4. **Keep licenses per asset.** Pexels permits commercial use with restrictions around endorsement, trademarks, and identifiable people. Mixkit's Restricted License covers personal/noncommercial use only; select Free License assets for monetized video. Canva's generated designs may be commercial-use eligible but not exclusive, and the creator remains responsible for third-party rights. ([Pexels](https://www.pexels.com/license/), [Mixkit](https://mixkit.co/license/), [Canva AI/content terms](https://www.canva.com/en_in/policies/content-license-agreement/))

## Recommended implementation plan

### Phase 0 - Establish the actual zero-cost baseline

- List which script model, voice, asset API, and upload service the current settings invoke. Record whether each is local, free-tier, usage-metered, or subscription-based.
- Render one vertical Short and one existing 8-10 minute film with all paid-generation options disabled. Use owned narration or an existing local voice and only approved/local media.
- Save an episode manifest with provider/model, source URL or asset ID, license class, generated media flag, measured render time, and any external API call/credit usage.

### Phase 1 - Improve what is already built

- Keep the Shorts and HyperFrames long-form pipelines as the renderers. Spend effort on stronger source-backed scripts, natural voice auditions, beat-to-scene matching, clean captions, and manual quality review.
- Extend the review report to list unsupported factual claims, asset/license references, and realistic AI depictions that need disclosure.
- Add a simple cost ledger and disable unattended provider calls when the configured monthly/run cap is missing or exceeded.

### Phase 2 - Repurpose the project's own long films

- Add a distinct "make Shorts from this approved film" action using the project's own rendered MP4 or scene/line timings as the source.
- Select only complete thoughts with an opening and payoff. Let the creator choose among candidate start/end ranges and review the text before rendering.
- Reframe the approved excerpt, preserve the project's caption/motion style, and store the source film ID, line IDs, clip range, and media references. Do not ingest an arbitrary YouTube link by default.
- Compare this small local implementation with OpenShorts on the same owned source if its features are needed; do not import its `cloud/` directory or API integrations.

### Phase 3 - Optional external trial, only if it fills a real gap

- For clip selection, trial OpenShorts Cloud or one free clipper on an owned recording, but test the downloaded final file, watermark, retention, privacy, and commercial rights before adopting it.
- For generated B-roll, keep it disabled by default. Require provider, model, output seconds, estimated price, license/terms link, and a user-set maximum before each paid request.
- Use free trial output only for internal quality review when it has a watermark, uncertain rights, or a strict storage cap.

### Phase 4 - Evaluate from channel evidence

- Review Shorts and long-form separately using their own YouTube Studio metrics and compare with the channel's prior videos, not generic "virality" scores from vendor pages.
- Track human editing minutes, service minutes/credits, error recovery, and rights-review time along with view/retention metrics. Keep only additions that measurably save effort or improve the finished video.

## Source register

All external sources below were accessed on 2026-11-03. The cited pricing and quota figures are snapshots, not guarantees.

### Project and open-source tools

- [OpenShorts source repository](https://github.com/mutonby/openshorts), [MIT root license](https://github.com/mutonby/openshorts/blob/main/LICENSE), [commercial-license exception for cloud/](https://github.com/mutonby/openshorts/blob/main/cloud/LICENSE), [official pricing](https://www.openshorts.app/pricing)
- [AI-Youtube-Shorts-Generator repo](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator)
- [Video-Use repo](https://github.com/browser-use/video-use), [Video-Use skill](https://github.com/browser-use/video-use/blob/main/SKILL.md)
- [Agnes Video Generator repo](https://github.com/lcy362/agnes-video-generator), [setup](https://github.com/lcy362/agnes-video-generator/blob/master/docs/public/getting-started.md), [features and API limiter](https://github.com/lcy362/agnes-video-generator/blob/master/docs/public/features.md)
- [n8n Sustainable Use License FAQ](https://support.n8n.io/article/can-i-use-your-license-for-my-use-case)

### Cloud editing and clipping

- [OpusClip pricing](https://www.opus.pro/pricing)
- [Exemplary AI pricing](https://exemplary.ai/pricing)
- [Choppity pricing](https://www.choppity.com/pricing), [plan details](https://help.choppity.com/en/articles/7110470-plans-and-pricing-explained)
- [Klap free clip generator](https://klap.app/tools/ai-clip-generator), [Klap homepage](https://klap.app/), [Klap pricing](https://embed.klap.app/pricing)
- [AutoShorts.ai](https://autoshorts.ai/), [AutoShorts.app](https://www.autoshorts.app/en)
- [InVideo AI free plan](https://help.invideo.io/en/articles/9380226-can-i-use-invideo-ai-for-free), [InVideo AI pricing](https://invideo.io/pricing/), [InVideo Editor credits](https://help.invideo.io/en/articles/11528140-invideo-plans-and-credits-everything-you-need-to-know)
- [Canva Magic Video](https://www.canva.com/help/magic-video/), [Canva AI video clips](https://www.canva.com/help/video-clip/)
- [Clipchamp pricing](https://clipchamp.com/en/pricing/), [CapCut auto-captions](https://www.capcut.com/help/how-to-recognise-subtitles), [CapCut commercial-asset terms](https://www.capcut.com/trust/legal)

### API, voice, stock, and platform policy

- [Gemini API pricing and free-tier data note](https://ai.google.dev/gemini-api/docs/pricing), [Gemini billing/data FAQ](https://ai.google.dev/gemini-api/docs/billing)
- [Anthropic API prepaid credits](https://support.anthropic.com/en/articles/8977456-how-do-i-pay-for-my-api-usage), [Claude plan/API separation](https://support.anthropic.com/en/articles/9876003-i-subscribe-to-a-paid-claude-ai-plan-why-do-i-have-to-pay-separately-for-api-usage-on-console)
- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing), [eligible ChatGPT API-credit benefit](https://developers.openai.com/api/docs/guides/chatgpt-api-credits)
- [Replicate pricing](https://replicate.com/pricing)
- [ElevenLabs free/paid rights](https://elevenlabs.io/docs/overview/administration/billing)
- [Pexels license](https://www.pexels.com/license/), [Mixkit license types](https://mixkit.co/license/)
- [YouTube Terms](https://www.youtube.com/t/terms), [YouTube API audiovisual content policy](https://developers.google.com/youtube/terms/developer-policies#handling-youtube-data-and-content), [YouTube monetization policy](https://support.google.com/youtube/answer/1311392), [YouTube AI disclosure](https://support.google.com/youtube/answer/14328491), [TikTok AI content policy](https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content)
