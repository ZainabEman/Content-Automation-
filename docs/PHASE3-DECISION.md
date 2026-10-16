# Phase 3 – Instagram animated carousel: audit and decision

Audit date: 2026-10-10. Read-only: no code changed, no paid calls. Nano Banana is paused (no new
work for it; it stays in the code until Phase 4). ComfyUI with Roman's LoRA is the future image
source, and RunPod has no credit yet. **Unverified** marks facts that no official page confirmed.

## 1. Current state

- **Carousel today** (`instagram_carousel`, `config/deliverables.json`):
  - 6–8 slides, default 7: hook, problem, steps or insights, example, CTA.
  - Each slide is one `social_creative` image, 4:5 at `IMAGE_DESIGN_SIZE` (2K).
  - In today's code (to be changed), Roman appears on slide 1 and the last slide (layout B or
    C), with a person check. The middle slides are information visuals without people (chat,
    diagram, mini checklist, before/after).
  - Slides 2+ attach slide 1 as a style reference, and a set check compares every slide with
    slide 1.
- **Text and logo:** the image model (Nano Banana) draws the text; the app pastes the logo. The
  Phase 2 text overlay has no carousel zones yet.
- **Caption and storage:** one caption + hashtags per package (post text). Drive sync uploads
  the images and MP4s to `Instagram/<Content ID>/`, and the Content Tracker gets one row per
  package.
- **make-video skill:** the app never calls Higgsfield. It writes `requests/scene-N.json`
  (prompt, ≤15 s, 9:16, start image, identity photos), and Codex uses the Higgsfield plugin to
  make each clip after an "ok" on the cost. Codex then records the clip with
  `ca job complete --credits` (no retries), and `ca video resume` assembles the result.
- **Video code:** `media/assemble.py` uses FFmpeg (imageio-ffmpeg):
  - 1080×1920 at 30 fps only;
  - image scenes become an 8% slow zoom (`zoompan`);
  - scenes are joined with `concat`;
  - text is burned in with `drawtext` in a system font (Arial), plus `captions.srt`.
  There is no 4:5 output and no per-slide MP4 export.

## 2. Higgsfield

The "plugin" is the hosted MCP server `https://mcp.higgsfield.ai/mcp` (`.mcp.json`). It needs
a Higgsfield sign-in and is not signed in here, so its live tool list could not be read.

| Topic | Finding |
|---|---|
| MCP tools | Official: image and video generation, Soul characters, Higgsfield Audio, credit balance checks. Tool names (e.g. `generate_video`, async with a job ID) come from third-party guides: **unverified**. Image-to-video ("from a text prompt and/or a starting image") is not named on the official page: **unverified**. |
| MCP billing | Official: uses the account's **plan credits** at standard rates; no API key. It "isn't the Higgsfield API". |
| API | A separate developer product with an API key, REST + Python/TS SDK, async jobs (poll or webhook) and 20 concurrent requests. Billed **pay-as-you-go in USD**, separate from any plan; failed requests are not charged; the balance expires after 1 year. **Usable from a script.** |
| API prices (official, Sept 2026) | Kling 2.5 from $0.042/s (5 s or 10 s); Kling 2.6 from $0.070/s; Kling 3.0 Pro $0.084/s; Wan 3.0 from $0.068/s; Seedance 2.0 from $0.141/s; Seedance 2.5 from $0.206/s. Discounts of 30–50% are shown. Aspect ratios and audio surcharges are not stated. |
| Plan prices | Third-party guides conflict: about $9–19/month for 120–270 credits, up to about $99–129/month for 900–3,000 credits. Credits expire monthly; top-ups are about $5 per 100 credits. A 5 s clip is about 15–70 credits depending on the model. **Unverified.** |
| Clip length | 5 s is common (Kling 2.5: 5 s or 10 s); 4 s exists for Seedance. |
| Aspect ratio | The sample carousels are **1:1**, which image-to-video models commonly support. Kling reportedly takes its aspect ratio from the input image (third-party, **unverified**). Fallback: crop and scale locally to 1080×1080. |
| Your notes | v1 quoted 91 credits for 13 s (about 7 credits/s, so about 35 credits per 5 s clip). The workspace had 0 credits. |

Video models garble small text and logos. So the start image is always **text-free**, and the
app puts the text and logo on top of the finished clip.

## 3. Decisions (2026-10-10; these override earlier drafts)

0. **No Roman on any carousel slide.** All slides are topic-related visuals only, so there is no
   person check for carousels and no identity photos or LoRA.
1. Person check: not applicable.
2. **Set check:** runs automatically. Mismatches are only reported, in the summary and the
   tracker notes; it never stops the run.
3. **Design: a hybrid led by Higgsfield** (budget available on demand).
   - Higgsfield image-to-video animates the elements that move in the sample (robots,
     illustrations, neon icons, UI holograms).
   - Slides that are pure graphic or text motion are animated locally for free.
   - Text and logo are always rendered by the app on top of the video.
4. **Style reference:** the sample carousels in `assets/reference/creative/carousels/`
   (section 4). The new carousel must match them.
5. **Single "ok" flow** (section 7). The only fallbacks: a clip that fails twice is animated
   locally for that slide; a spend that would go over the approved max stops and asks.

## 4. The sample carousels

Found: `assets/reference/creative/carousels/carousel_01`–`carousel_11` (MP4s + extracted
frames; some have PDF exports).

| Aspect | Finding |
|---|---|
| Format | 8 slides each; **1:1, 960×960**, 24 fps, 5.04 s per slide, silent; one MP4 per slide, no transitions |
| Background | Near-black / deep navy, a blue glowing particle wave along the bottom, a faint grid or bokeh |
| Colours | Black and navy, electric/royal blue neon glow, sky blue; white text; highlight words in blue |
| Typography | Bold geometric sans (Futura-like). Headline in ALL CAPS (carousel_01) or sentence case (carousel_11), 2–5 lines, highlight words in blue; a small body line under it, with blue highlights |
| Text zone | Left ~45–50%, upper or middle; the visual on the right half |
| Visuals | Glossy white 3D robots, neon line icons (funnel, shield, checklist, magnifier), holographic UI cards and charts, a robot hand. No real people (abstract silhouettes at most) |
| Logo / extras | Branded Genius logo **only on the last slide** (top left in 01, top right in 11). carousel_01 has a "01/07" counter pill at the top right; carousel_11 has a small dot-grid mark at the top left |
| Last slide | A question CTA ("Welche Aufgabe würdest du zuerst automatisieren?") + a Like / Share / Save icon row |
| Motion | Text stays still. The illustration moves (robot head and hand, icons pop, float and pulse, glow and particles shimmer), with a slight drift. Small UI text inside the visuals got **garbled** by the video model ("www." became "Faetae"), which confirms that text must be rendered on top |
| Language | **German** (brand.json says English): to decide |

## 5. Design per carousel (8 slides, 1080×1080, 5 s, 24 fps)

- **Stills (text-free, no people):**
  - topic illustrations in the sample style, made by ComfyUI/Z-Image without a LoRA (once
    RunPod has credit) or by Higgsfield's image models (on the budget), plus the app-drawn
    background (navy, particle wave);
  - graphic-only slides (icon flows, the CTA icon row) are drawn by the app.
- **Motion:**
  - illustration slides: Higgsfield image-to-video (about 6 of 8, 5 s each) with a "subtle
    motion, camera almost still, no text" prompt;
  - graphic slides (about 2): local FFmpeg (glow pulse, icons appear one after another, slight
    drift).
- **On top (app):**
  - headline + body in the left zone (Jost or Futura, blue highlights), slightly faded in;
  - the logo on the last slide only, like the sample (to confirm);
  - no slide counter (current rule; carousel_01 has one).
- **Output:** `slide_01..08.mp4` + `slide_01..08.png` (the text-free stills and the final
  frame with text) + one caption with hashtags, then Drive `Instagram/<Content ID>/` and one
  tracker row.

## 6. Cost per carousel (6 Higgsfield clips × 5 s + 8 stills; estimates)

| Route | Clips | Stills | Estimate | Max (one retry per clip) |
|---|---|---|---|---|
| Higgsfield plugin (plan credits; PRD) | 6 × ~35 credits = ~210 credits (from your v1 rate of 91 credits / 13 s) | Higgsfield image: ~8–40 credits (**unverified**) | **~220–250 credits ≈ $11–19** (at $0.05–0.075 per credit) | ~430–460 credits ≈ $22–35 |
| Higgsfield API (USD) | Kling 2.5: 30 s × $0.042 = $1.26 (list); Kling 3.0 Pro $2.52 | ComfyUI Z-Image ≈ $0.10 (RunPod) | **≈ $1.4–2.6** | ≈ $2.7–5.2 |
| Local only (fallback) | $0 | as above | $0–0.10 | – |

The plan route is what the PRD names (the existing plugin). The API route is about 5–8×
cheaper per carousel but is a separate account. The paid test in step 6 measures the real
numbers before any setting is fixed.

## 7. Requirement: one "ok" = the full carousel, end to end

1. **Dry run:** one cost line per slide (still + clip), the total, and a **max cost** that
   includes one retry per clip. The max is in the provider's unit (credits for the plugin, with
   a dollar equivalent; dollars for the API and ComfyUI). The user says "ok" once.
2. **After the "ok", with no further stops:**
   1. stills;
   2. Higgsfield clips;
   3. local animation for the graphic slides;
   4. text and logo on top;
   5. `slide_01..N.mp4` + stills + caption/hashtags;
   6. Drive `Instagram/<Content ID>/`;
   7. Content Tracker row (Pending/Pending).
3. **make-video skill:** all clips run under the one approval, with no question per clip (this
   replaces "stop for ok" per job, for carousels).
4. **Fallbacks:** a clip is retried once, inside the max. If it fails again, that slide is
   animated locally, and the summary and the tracker caption notes name it. This replaces "no
   retries" for carousel clips.
5. **Hard stop:** only if the real spend would go over the approved max. The spend is tracked
   per clip from the credits or dollars the provider reports.
6. **Set check:** automatic. Mismatches go to the summary and the tracker notes; never a stop.
   There is no person check: no people on the slides.
7. **End:** one short summary with the Drive link, the slide count, the real cost against the
   estimate, any local fallbacks and any set-check notes.
8. **"generate approved"** (calendar) uses the same flow: an approved Instagram row runs all the
   way to Drive and the tracker.

Kept: CLAUDE.md / PRD "no paid generation without an approved cost estimate" (the one "ok"
approves the max). Uploading to Drive is not publishing.

## 8. Build steps

- **Step 2 – Design system from the sample.**
  - Carousel spec: 1:1 1080×1080, 8 slides, 5 s at 24 fps.
  - Background, colours, text zone (left), typography, highlights.
  - The last-slide CTA with the Like/Share/Save row, the logo rule, no people.
  - Carousel zones in `textOverlay`, and roles and prompts per slide type.
- **Step 3 – Topic stills.** Text-free, no-people illustration stills per slide in the sample
  style (ComfyUI/Z-Image or Higgsfield image), plus app-drawn backgrounds and graphic slides.
  Saved per slide.
- **Step 4 – Animation + overlay → MP4s.**
  - Higgsfield image-to-video requests (one approval, one retry, local fallback).
  - Local FFmpeg animation for graphic slides.
  - Text and logo on top; export `slide_01..08.mp4` + stills; automatic set check.
- **Step 5 – Wiring.**
  - Package and calendar "generate approved" with the single-"ok" flow: the dry run shows per
    slide costs, total and max; spend tracking and the hard stop.
  - Drive `Instagram/<Content ID>/`, the tracker row with notes, the final summary.
  - make-video skill and AGENTS.md updates.
- **Step 6 – One paid test carousel** (after your "ok" on its max). Measures the real
  credits/dollars per clip, the 1:1 output, the motion quality against the sample and the
  timings; then the settings are fixed in config.

## 9. Open points

1. **Language:** the samples are German, while brand.json says English. Which language do new
   carousels use?
2. **Logo:** last slide only (like the sample) or every slide (as the app does today)?
3. **Route:** Higgsfield plugin (plan credits, as the PRD says) or the API (USD, cheaper)? And
   the per-carousel max you want to approve.
4. **Stills:** Higgsfield image models (now, on the budget) or ComfyUI/Z-Image (when RunPod has
   credit)?

Answered 2026-10-12: (1) brand.json `carousel.language`, default `en`; (2) last slide only;
(3) the Higgsfield plugin (plan credits, no API key), all requests under the single "ok" with
one retry each, costs in credits; (4) Higgsfield image model now, `stills.provider`
higgsfield|comfyui for later. Details in `docs/PROGRESS.md` (Phase 3 decisions).

## 10. Higgsfield plugin tools (filled in by Codex on the first run)

Status: **listed 2026-10-16.** Codex listed the Higgsfield plugin tools and checked model
constraints and dry-run estimates before the first carousel dry run. `config/carousel_design.json`
now records the selected image and video models and estimates.

| Item | Value |
| --- | --- |
| Date listed | 2026-10-16 |
| Image tool (name) | `mcp__codex_apps__higgsfield_generate_image` |
| Image models | `gpt_image_2_5` (selected; default 1k resolution, flare variant) |
| Sizes / aspect ratios (1:1? 1080x1080 or the closest) | 1:1 supported; 1k output is the closest listed size to the 1080x1080 canvas, then `ca` crops/resizes |
| Reference images (yes/no, how many, upload or URL) | Yes (`image_references`); catalog gives no maximum; uploaded media UUIDs or authorized HTTPS image URLs |
| Negative prompt field (yes/no) | No dedicated field in the generation tool schema; append `Avoid:` to the prompt |
| Credits per image (as the plugin reports) | 0.25 credits per image (default 1k/low, 1:1 estimate; `estimate_image_cost`) |
| Image-to-video tool (name, for Step 4) | `mcp__codex_apps__higgsfield_generate_video` |
| Video models, clip lengths, 1:1 support | `seedance_2_5` (selected); image reference via `start_image`, 4-30 seconds (5 supported), 1:1 supported |
| Credits per 5 s clip | 35 credits (720p, silent image-reference estimate; `estimate_video_cost`) |

## Sources

- Higgsfield MCP: https://higgsfield.ai/creator-hub/help-center/integrations/what-is-higgsfield-mcp
- Higgsfield API: https://higgsfield.ai/blog/higgsfield-api, prices https://open.higgsfield.ai/pricing
- Plan prices (third-party, conflicting): https://www.scopeful.org/blog/higgsfield-pricing-2026,
  https://www.layer3labs.io/guides/higgsfield-ai-pricing, https://voyager.so/blog/higgsfield-pricing
- MCP tool names (third-party): https://mcp.directory/blog/higgsfield-mcp-guide
- Kling aspect from the input image (third-party):
  https://www.eachlabs.ai/tr/kling/kling-o3/kling-o3-4k-image-to-video
