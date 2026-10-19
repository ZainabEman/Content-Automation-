# v5 implementation notes (German refocus, brand visuals, YouTube planning)

PRD: `docs/PRD-v5-german-brand-youtube.md`. Branch `phase-v5-german-brand`, created 2026-10-19 from
`phase-d-design` (7d20445). The uncommitted `config/calendar.json` change (an extra Tuesday LinkedIn
slot) came along unchanged; creating the branch needed no switch, so nothing was committed as WIP.
Nothing is pushed or merged. No paid or external call was made in this run.

---

## Phase 0: audit (read-only)

### a) Brand sources

| Item | Where | Notes |
|---|---|---|
| Brand guideline | `assets/reference/brand/guidelines/Branded Genius Brand Style Guide.pdf` | one page, "MARKEN STYLEGUIDE"; the PDF is a single embedded JPEG (5475×7275, DCTDecode), no text layer. Sections: Vision & Mission (Roman Tränkle), Logo-Nutzung (full colour, Dunkles Logo, Weißes Logo, Graustufen-Logo), Anwendungsbeispiele (A4, A5, envelope, card), Farbauswahl, Typografie. |
| Colours (guide) | guide "FARBAUSWAHL" | Medium Gray #969595, White #FFFFFF (silver/metallic gradient, "GENIUS"); Sky Blue #69BFF8, Royal Blue #004BA0 (blue gradient, "BRANDED"). The swatches show tints (lighter steps) of each colour. |
| Fonts (guide) | guide "TYPOGRAFIE" | Heading Futura Bold, Sub-head Futura Medium, Logo font Good Times (logo only). |
| Fonts present | `assets/fonts/` | Jost Regular/Medium/SemiBold/Bold/ExtraBold + OFL.txt (stand-in for Futura). **No Futura file and no Good Times file is present.** Jost has ä ö ü Ä Ö Ü ß (checked in Phase 1). |
| Logo files | `assets/reference/brand/logo/` | `logo (1).png` 3000×2000 RGBA, sha256 `ff800645…df418` = the official file used by code (`brand.json logoFile`, `logoVariants.full_colour`). Others: `Logo .svg`, `25bg.svg` (vector, not used by code), `cFkuqb.jpg` 2578×706 (wordmark on white), `Flavicon.png/.jpg` (bg monogram), `set.json`, `_resized/`. |
| Tokens | `config/brand.json` | colours, tokens, gradients, typography with a `source` per entry citing guide p.1 (Phase D, D-1: guide strictly; dark designs Royal Blue, never navy/black). Matches the guide. `language: "en"`, `carousel.language: "en"`. |
| Design system | `config/design_system.json` | Phase 1-2 post layouts (person posts, ads); style refs = `creative/facebook_ads_masked` (Branded Genius's own ads with logos masked). |

### b) Reference folders and classification

`REFERENCES_DIR=assets/reference` (`.env`); the folder is git-ignored. Classification evidence = what is visible in the files.

| Folder / files | Class | Evidence |
|---|---|---|
| `assets/reference/creative/facebook_ads/01.jpg … 06.jpg` (1254×1254) | **APPROVED COMPANY** | every image carries the Branded Genius wordmark (top left or top right) and German copy ("Ihr Vertrieb schläft…", "Weniger Routine. Mehr Wachstum.", "Jede Anfrage verdient eine Antwort", "Wie viel Potenzial…", "Arbeiten Sie smarter…", "KI, die Ihr Unternehmen wirklich voranbringt"); CTA pills "Kostenlos testen", "Beratung buchen", "Live-Demo ansehen", "Jetzt analysieren", "Strategiegespräch buchen", "Mehr erfahren". |
| `assets/reference/creative/facebook_ads_masked/01-06.png` | APPROVED COMPANY (derived) | the same six ads with the logo covered by `ca refs mask`. |
| `assets/reference/creative/carousels/carousel_01 … carousel_11` (MP4 slides, `_frames/` JPEG stills 960×960, PDFs) | **APPROVED COMPANY** | German copy; the last slide of every set carries the bg monogram + "BRANDED GENIUS" wordmark top right; Like/Teilen/Speichern row; PRD R4 calls them "the company's samples". carousel_01–03 show the "01/07"/"08/08" counter pill (to be dropped, R4). |
| `assets/reference/creative/carousel_style/*.png`, `palette.json` | APPROVED COMPANY (derived) | style frames made by `ca carousel style` from the carousels (Phase 3); palette retired by D-1. |
| `assets/reference/brand/*` | official brand assets | guideline + logo files. |
| `assets/reference/identity/person_01/` | identity (Roman) | LoRA training / identity sheet only, never a design reference. |
| `assets/reference/creative/social_refs/` (R01–R36, C1–C7 per `config/social_refs.json`) | **COMPETITOR/THIRD-PARTY** | **not present on disk.** `config/social_refs.json` and PROGRESS D-6 say they are third-party layouts (brands, logos, captions not ours; docx captions = competitor posts, aurora-automation.com per PRD §2). The originals sit outside the repo in `~/Downloads/refrences/` (36 WhatsApp images) and `~/Downloads/consistent person refrence images data.docx`; left untouched (outside the project). |
| `assets/reference/creative/carousels/company_2026-10` | — | **does not exist** (searched the repo and ~/Documents, ~/Downloads, ~/Desktop). |
| Designer's own outputs (R3 benchmark) | UNKNOWN | no file in the repo is labelled as the graphic designer's output; none found. |
| UNSURE | none | every image file found could be classified from its content. |

Q2 answer: the approved "references" folder is `assets/reference/creative/` (`facebook_ads/` + `carousels/`). No LinkedIn reference exists; LinkedIn layouts are derived from the ads (same company style) plus the designer's prompt (3:4, logo at the side corner).

### c) Where competitor material reaches the active pipeline

| Place | What | Reaches generation? |
|---|---|---|
| `config/design_directions.json` | all 12 directions (FB-1..3, LI-1..3, CS-1..3, FD-1..3): layouts, zones, visual prompts derived from R01–R36 / C1–C7 (`referenceIds`) | yes: loaded by `content/directions.py` → `direction_pick`, `direction_job`, `design_render`, `design_check`, `direction_brief`, `design_preview` |
| `config/social_refs.json` | id → original file + use per competitor ref | only by docs/tests (no `src` loader) |
| `config/design_preview_copy.json` | sample copy per direction | yes (preview, e2e) |
| `tests/test_design_directions.py` | asserts the 12 ids and R/C references | tests only |
| `config/design_directions.json` `roman` block | LoRA prompt pools (outfits, settings, quiet luxury) | from Roman's decisions (D-6, D-8), not from competitor refs: kept |
| Image prompts | the direction `visual.prompt` strings ("one clean 3D object on plain royal blue…") | yes |

### d) Image generation

- Registry `ai/image/__init__.py` `_ADAPTERS`: `mock`, `openrouter`, `comfyui`, `template`.
- OpenRouter: model default `google/gemini-3.1-flash-image` (`IMAGE_MODEL`, `CAROUSEL_IMAGE_MODEL` defaults in `core/config.py`; `.env` sets neither). The adapter sends reference images as `input_references` (base64 data URLs, up to 14; documented from the endpoint listing in `providers/openrouter.py`). **The configured model accepts image inputs** (code/config evidence only; not called).
- `.env` (names only): `IMAGE_PROVIDER=comfyui`, `IMAGE_MODEL=z_image_turbo`, `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`, `RUNPOD_NETWORK_VOLUME_ID`, `OPENROUTER_API_KEY`, `STORAGE_PROVIDER=drive`. Values not read.
- ComfyUI on RunPod Serverless: `providers/comfyui.py` + `providers/runpod.py`: `POST https://api.runpod.ai/v2/{endpoint}/run {"input":{"workflow":{…}}}` → poll `GET …/status/{id}` (`pollSeconds` 3, cancel at `timeoutSeconds` 600), no retry, no fallback. Workflow `config/comfyui/workflows/z_image_turbo.json` (+ `.map.json`: nodes for prompt, negative, seed, width, height, steps, cfg, lora_name, lora_strength; `loraBypass`). Models on the volume: z_image_turbo_bf16, qwen_3_4b, ae.
- LoRA: `config/comfyui.json` `workflows.z_image_turbo.loraName = r0man_bg_v2_step3000.safetensors`, trigger `r0man_bg`, strength 0.9 → `ca lora set` (or the same edit) **was run** for Z-Image. Qwen loraName is still a placeholder.
- Roman routing (7d20445, D-8): a direction's `visual.subject` fixes its provider: `roman_lora` → `comfyui`, `illustration` → `openrouter` with `CAROUSEL_IMAGE_MODEL`, `none` → `template`; `direction_settings()` never swaps (mock stays mock); a founder pick without comfyui set up is refused; FD-1 = LoRA on green, cut out by the app. Verified in `content/directions.py`, `workflows/direction_job.py`, `workflows/image_workflows.py::_prepare_direction`.

### e) Current image prompts vs the designer's prompt (R3.1)

| Prompt | Adds | Loses (vs designer) |
|---|---|---|
| Direction illustration prompts (`design_directions.json visual.prompt`, e.g. "{illustration}. One clean 3D object on a plain deep royal blue background … no text") | strict no-text rule, blocked words, exact copy and logo drawn by the app, fixed zones, contrast and logo checks | the expert-designer role and quality bar; the brand guide as an input (only hex words); the logo as an input; purpose (Branded Genius mission/services); creative latitude (one object on a flat colour); the platform's format is implicit |
| LoRA prompts (`content/roman.py`, pools) | identity safety (trigger, alone, blocked props), quiet-luxury rules | same losses as above; Roman-only by design (keep) |
| `workflows/prompt.py` `build_design_prompt` (Phase 1-2 person posts/ads, design_system.json) | brand colours and fonts in words, layout A–D, masked company ads as style refs, identity photos | the designer's open brief; it is now used only by the older `ca image` workflows |
| Designer prompt (R3) | role + quality bar, guide + logo as inputs, purpose, latitude, explicit format 3:4 | no text-accuracy rule (German text and logo may be drawn wrong), no free zones |

### f) Text generation

No LLM API is called by `ca` for copy. The Codex agent writes `content.md`, `brief.json`, captions and hashtags from the templates (`make-content`, `write-script`), and `ca` checks them (`content/quality.py`, `content/script_check.py`). Language is set in `config/content.json` (`language: en`, `layoutLanguage` mix), `config/brand.json` (`language`, `carousel.language` = `en`), `content/package.py` (`"language": "English"` in the brief template) and `content/distribution.py` (`language="en"`).

### g) Video, avatar, podcast, UGC, YouTube

| Piece | Decision | Reason |
|---|---|---|
| `ugc_ad` deliverable + video workflow | remove | R8 |
| `podcast_clip` deliverable + workflow, `ca podcast heygen/record/audio`, `content/podcast.py`, podcast formula/brief, calendar `podcast_episode` | remove | R8 |
| `youtube` video workflow (HeyGen avatar 16:9), `ca video upload` (YouTube final) | remove | R8 (finished YouTube videos) |
| `ai/avatar` (HeyGen plugin adapter) | remove if nothing else uses it after the above | R8.2 |
| `reel_short` + `ca video`, `ai/video` (Higgsfield plugin), `ai/voice` | keep | not named in R8; open question |
| `make-video` skill | trim to reels only | its UGC/podcast/YouTube parts go |
| `produce-video` skill, `ca production`, `ca import/handoff/thumbnail` | keep for YouTube, drop podcast | Roman records, Takwa edits: production tracking of the recording/final still applies |
| `clips` skill, `ca clips` (Opus Pro), `distribute` | keep untouched | PRD §3 / Q7 |
| Phase 3 animated carousel (Higgsfield) | already deleted 2026-10-16 (PROGRESS "Post formats + static carousel") | R4.3 "keep but off" cannot apply: the code is gone; the static carousel is already the default |
| Drive folder "YouTube" | keep | R8.3 |

### h) Research

`ca research collect` (scraper over `config/sources.json`), `ca research fetch` / `run` (newsletter links → `research/fetch.py`: httpx GET, robots.txt check, trafilatura text + metadata; `TRANSPORT` hook for test mocks), `ca research digest`, idea backlog with claims (`registry/claims.py`). So `ca` can fetch URLs; the YouTube source check reuses `research/fetch.py`.

### i) Calendar, registry, design history, tracker, Drive

- Calendar: weekly CSV `calendar/<YYYY-Www>.csv` as a registry view; `config/calendar.json` slots (weekly) + `plan` (v2, month view `ca calendar plan --month`). Registry (Phase 4) done: BG IDs, items, versions, jobs, authorizations, audit.
- Design history: package.json `direction` + `createdAt` (D-7), read by `direction_pick.recent_directions`.
- Tracker: Google Sheet "Content Tracker", header-name matching (`content/tracking.py`), registry columns from `config/tracker.json`, appended at the end; manager fields never overwritten.
- Drive: `ca drive setup` creates `Content Automation/{LinkedIn,Facebook,Instagram,Calendar}` (+ `YouTube`); folder IDs in `config/drive_folders.json` (LinkedIn, Instagram, Facebook, YouTube, Calendar, root) and `state/`; `STORAGE_PROVIDER=plugin` writes `upload_manifest.json` for the Codex Drive plugin.

### j) Teleprompter

No information in the code or docs (only the PRD). Default: plain UTF-8 TXT (R9.8). Q5 stays open.

### Conflict table

| PRD | Current | Planned change |
|---|---|---|
| R1.4 German default | `content.json language en`, `brand.json language/carousel.language en`, brief template "English" | `de` everywhere audience-facing; English kept as an option |
| R1.6 German quality pass | none | `content/german.py` + hook in the quality checks before the dry run |
| R2.2 competitor out | 12 directions from R/C refs | move to `config/_archive/`; new variants from approved refs |
| R2.4 / D-1 palette | references use near-black navy; guide has only 4 colours; D-1 = Royal Blue dark | guide wins (D-1 kept); disagreement listed for Roman |
| R3 designer prompt | one-object prompts, no guide/logo inputs | designer templates per category; guide image + logo + approved refs as `style_refs` |
| R4 carousel 5–6, 1:1, no counter | 6–8 slides, 4:5 1080×1350 | 5–6 slides, 1:1 1080×1080, no counter, logo + website last slide only |
| R4 Facebook ad separate | `facebook_ad` = old ad workflow (3 variants with the person) | new FA variants (direction format `fb_ad`), own folder, ad fields |
| R4 LinkedIn 3:4 | 4:5 1080×1350 | 3:4 1080×1440, logo at the side corner |
| R5 rotation key | direction id only | variant id + background treatment |
| R6 explicit `requires_roman` | implied by the direction subject | explicit flag at planning time, stored in package.json; routing reads it |
| R7 monthly planner | weekly slots + calendar v2 month plan from the backlog | `ca plan month YYYY-MM` with the category mix |
| R8 removals | ugc_ad, podcast, youtube video live | removed (above) |
| R9 YouTube | old formula + brief, HeyGen video | `ca youtube` group + make-youtube skill |
| R10 Drive | LinkedIn/Facebook/Instagram/YouTube/Calendar | add Instagram Carousels, Facebook Posts, Facebook Ads, YouTube/<YYYY-MM> (code only) |
| R11 tracker | registry columns | + Category, Language, Layout Variant, Requires Roman, Selected Script Style |

### File-level plan

- Phase 1: `config/deliverables.json`, `workflows/video_workflows.py`, `video_plan.py`, `content/package.py`, `content/podcast.py` (delete), `cli/__init__.py` (podcast group, video upload), `ai/avatar` (if unused), `config/formulas.json`, `config/calendar.json` plan types, `config/production.json`, skills/AGENTS.md; archive `config/design_directions.json` → `config/_archive/`, `config/social_refs.json` → `config/_archive/`; `tests/test_archive_isolation.py`; `content/german.py`; language defaults.
- Phase 2: `brand/reference-analysis.md`, `config/brand.json` (sources), `config/designer_prompts.json` + `content/designer_prompt.py`, new `config/design_directions.json` (variants), `content/directions.py` (fb_ad, 3:4, treatment, carousel rules), `direction_pick.py` (variant + treatment), `design_check.py` (category rules), `design_render.py` (as needed), preview sheet script.
- Phase 3: `content/routing.py` (requires_roman), package.json field, tests incl. secret scan.
- Phase 4: `content/month_plan.py`, `ca plan month`, `config/deliverables.json` mix.
- Phase 5: `youtube/` package, `ca youtube`, `config/sources_de.json`, `.agents/skills/make-youtube/`.
- Phase 6: storage folder names, tracker columns, `docs/v5-drive-actions.md`.
- Phase 7: docs.

---

## Phase 1: removals, competitor archive, German defaults (done)

Removed (PRD R8):
- `ugc_ad` and `podcast_clip` deliverables (`config/deliverables.json`) and the `ugc_ad`, `podcast_clip`, `youtube` video workflows (`workflows/video_workflows.py`, `video_plan.py`: `VideoWorkflow = "reel_short"`, max 90 s).
- `ca podcast heygen|record|audio`, `content/podcast.py` (deleted), the podcast brief type (`content/briefs.py`), the podcast formula and `podcast_episode` (formulas, calendar plan types and slot), podcast targets/loudness (`config/production.json`), the podcast row of `ca report month`, `PRODUCTION_KINDS` = youtube only, the HeyGen podcast branch of `ca jobs resume-all`, the HeyGen integration of `ca verify`.
- `ca video upload` (YouTube final.mp4 to Drive).
- Skills/AGENTS.md: make-video trimmed to reels (Higgsfield), produce-video and write-script without podcast, AGENTS.md lines for make-video, produce-video, the strict-selection list, the Make videos playbook, the plugin list.

Kept, and why:
- `reel_short`, `ca video`, `ai/video` (Higgsfield plugin), `ai/voice`: reels are not named in R8 (question for Roman).
- `ai/avatar` (HeyGen adapter) stays as dormant code: no workflow accepts avatar scenes any more, so nothing can reach it; removing it means rewriting the shared video-job engine (`workflows/video_job.py`, `content/package.py`), a risky change with no benefit. Removal is a follow-up if wanted. HeyGen is a Codex plugin, not a Python dependency, so no package was removed; no Python dependency was used only by the removed workflows (elevenlabs/voice and imageio-ffmpeg are still used by reels).
- `ca thumbnail` (moved to `content/thumbnail.py`), `ca production`, `ca import`, `ca handoff`: YouTube production tracking (Roman records, Takwa edits).
- Registry kind `podcast` and `review_upload` handling of old podcast items: old rows stay readable (R8.5).
- `ca clips` / Opus Pro and `ca script|brief` for YouTube: untouched (Q7). The old YouTube formula is replaced by the 8-step formula of R9.6 (`config/formulas.json youtube_longform`, 10–12 min, 1,300–1,600 words).
- Google Drive: not touched.

Competitor archive (R2.2):
- `config/social_refs.json` → `config/_archive/social_refs_competitor.json` (git mv).
- `assets/reference/_archive_competitor/README.md` (git-ignored folder): the R01–R36 / C1–C7 images were never inside the project; their originals stay in `~/Downloads/refrences/` and `~/Downloads/consistent person refrence images data.docx`, untouched.
- `core/archive.py`: `is_archived()`; the reference library skips `_archive*` folders in `scan` and `list_sets`.
- `config/design_directions.json` (the 12 competitor-derived directions with their prompts) moves to the archive **in Phase 2, in the same commit as its replacement**: the renderer, picker, design check and e2e need a direction file, and every commit must stay green. Until then it is still active (decision, logged).
- `tests/test_archive_isolation.py`: static (no source/config/skill names an archive path) + runtime (a Python audit hook records every file opened while directions load, every format picks, every layout renders, illustration prompts build, the brand loads and the library scans a folder with an archive; nothing under `_archive*` may be opened).

German (R1.4–R1.6):
- Defaults `de`: `config/content.json`, `config/brand.json` (`language`, `carousel.language`), `ContentLanguage()`, `BrandProfile`/`BrandCarousel`, the on-image text language (`workflows/prompt.py`), the distribution template, the brief template instructions (German, "Sie", no AI marketing language). English stays possible (a platform override to `en` brings back the old English/German layout mix).
- `content/german.py` + `config/german_quality.json`: umlaut/ß transliterations and common misspellings (errors), words starting Ae/Oe/Ue (warning), English leftovers (phrase or two function words: error; one: warning; loanword allow-list), banned AI-marketing phrases (error), du/Sie (warning, Q3 default Sie). Runs in the dry run (`_quality_problems`, all reader texts) and in `ca script save/check` for German templates (internal briefing sections skipped). Limitation: no full dictionary spell check offline (only the list).
- The existing copy checks (`content/quality.py`: specific-line, automation, result numbers, buzzwords) only knew English words; German channels, timings, sequence words, result units and buzzwords were added so German copy is judged the same way.
- Rendering: Jost has ä ö ü Ä Ö Ü ß „ “ – (test). Long words break only at their own hyphens ("KI-" | "gestützte") or at a soft hyphen (U+00AD) the writer sets, shown as "-" at the line end; a word without a break point that is too wide still fails the fit (never cut). `upper` keeps "ß" → "SS".
- `brand/services.md` offer line is German now: "kostenfreie KI-Potenzialanalyse" (the site says "KI-Potenzialanalyse anfragen", "kostenfrei"); the CTA check matches it.
- `config/design_preview_copy.json` and the Phase 4 e2e briefs are German.

Tests touched: test_thumbnail (was test_podcast), test_scripts (8-step formula, German fixtures, no podcast), test_report_resume, test_verify (11 integrations), test_layout_language, test_copy_rules (English card rules only with a platform set to `en`), test_ideas_sources, test_distribution, test_design_render, test_direction_build; 3 pre-existing strict-mypy errors in tests fixed. New: test_archive_isolation, test_german.

Open (for Roman):
- The approved carousels speak "du" ("Dein nächster Kunde…"), the approved ads "Sie". Default stays "Sie" (Q3); a "du" text is a warning, not an error.
- Reels (`reel_short`): keep or remove?

---

## Phase 2: brand visual system (done)

- `brand/reference-analysis.md`: palette, type, hierarchy, placement, logo, CTA, supporting graphics from the 6 approved ads and 11 approved carousels, each rule with its source; 6 disagreements with the guide listed (the guide wins).
- `config/brand_refs.json`: the approved references (A01–A06 ads, K01–K11 carousel cover + last slide) with sha256 and use. Competitor ids never appear in active config (test).
- `config/brand.json`: tokens unchanged (already sourced from the guide, D-1); the reference analysis added to `sources`; language `de`.
- **Layout variants** (`config/design_directions.json`, 18): carousel CS-1..4 (1:1, 5–6 slides: cover, 3–4 points, closing question with Liken/Teilen/Speichern; logo and optional website on the last slide only; no counters), Facebook post FB-1..4 + FB-R1 (4:5), Facebook ad FA-1..3 + FA-R1 (4:5, CTA pill on the image), LinkedIn LI-1..4 + LI-R1 (3:4, logo at a side corner). Each names its approved references and a background treatment. Founder (Roman) variants are inside their category (id with R, LoRA on comfyui), not a fifth category (R4.1). The Phase D file moved to `config/_archive/design_directions_phaseD_competitor.json`, its sample copy to `config/_archive/design_preview_copy_phaseD.json`. New German sample copy: `config/design_preview_copy.json`.
- Schema (`content/directions.py`): formats `fb_single | fb_ad | li_single | carousel` (no `founder` format), fixed canvas per category, `treatment`, carousel 5–6 slides, logo/footer only on the closing layout, LinkedIn logo corner, no counter fields, ids `(FB|FA|LI|CS)-R?n`. Renderer: `dots` shape, outline-only panels, fixed icon labels, optional footer (website), drawn lines recorded, logo sized in whole pixels (no 1 % stretch from rounding). Previews of full-bleed pictures use a dark stand-in like the references.
- **Rotation** (`content/direction_pick.py`, R5.3): never the previous variant on the platform (carousels: not the last 2), and never a treatment the last two packages both used. requires_roman (the calendar's "roman" row or "as LI-R1") picks the founder variant of that category. History: package.json `direction` (+ new `category`, `treatment`, `requiresRoman`, `language`). Registry migration 11 adds `layout_variant`, `background_treatment`, `requires_roman`, `language`, `script_style` to items (`registry/items.py set_design`, logged as item_updated); written at stage 1 and again at build time.
- **Facebook ads** are their own category: `facebook_ad` = 1 creative in an FA variant + `ad.adFields` (primaryText, headline, description, ctaButton from `config/meta_cta.json`, checked; German check on the texts). Nothing is placed or paid.
- **Designer prompt** (R3): `config/designer_prompts.json` + `content/designer_prompt.py`. The designer's six elements are the fixed core; added: category, topic, the headline as context only, the variant's picture and its free zones (where the app draws text and the logo), the approved references. Image inputs: object refs = the guide page (the JPEG inside the PDF, cached at `outputs/cache/brand_style_guide.jpg`, 1600 px) and the official logo; style refs = up to 3 approved references of the variant. A paid job without these inputs is refused; the mock records them as missing. The model is told never to draw the logo or any text; the app pastes the real logo and the exact German text (R3.5). Roman (LoRA on ComfyUI): Z-Image txt2img takes no image inputs, so his variants keep the photographic LoRA prompt with the free text side ({space}).
- **R3.3 model check (code/config only, nothing called):** the configured OpenRouter model `google/gemini-3.1-flash-image` accepts up to 14 input images (`providers/openrouter.py`, from the endpoint listing). No model switch. UNKNOWN: whether it accepts a 3:4 aspect; the adapter allows only 1:1, 4:5, 9:16, 16:9, so LinkedIn pictures are generated at 4:5 and cover-cropped to 3:4 (about 6 % lost top and bottom; the free zones are inside). Options for Roman: (a) keep 4:5 + crop (now; $0.101 per 2K image estimate); (b) one paid test call (about $0.10) to see whether 3:4 is accepted, then add it to the adapter.
- **Design check** (R2.7): plus brand fonts only, texts inside the 64 px margin (bleed footer bars exempt), carousel logo/website only on the last slide, no "01/07"-style counters, LinkedIn logo at a side corner. All 26 preview layouts pass.
- **Contact sheet**: `uv run ca design compare` → `outputs/previews/design/v5_vs_references.png` (18 rows: approved references left, v5 renders right; free). Designer's own outputs: none found (the sheet adds `creative/designer/*` when Roman drops them there).
- Carousel animation (R4.3/Q1): the Higgsfield animated carousel was already deleted on 2026-10-16 (PROGRESS); static slides are the only path. Nothing to switch off.
- Dormant: `workflows/cutout.py` (green-screen cut-out) is no longer used by any variant (no FD-1); kept, tested.

---

## Phase 3: image routing (done)

- Inspected before changing (R6.4): RunPod Serverless ComfyUI worker, `POST https://api.runpod.ai/v2/{RUNPOD_ENDPOINT_ID}/run {"input":{"workflow":…}}` → poll `/status/{id}`; workflow `config/comfyui/workflows/z_image_turbo.json` (+ map: prompt, negative, seed, size, steps, cfg, lora_name, lora_strength); LoRA `r0man_bg_v2_step3000.safetensors`, trigger `r0man_bg`, strength 0.9; models on the network volume per `config/comfyui.json`. Key names in `.env`: RUNPOD_API_KEY, RUNPOD_ENDPOINT_ID, RUNPOD_NETWORK_VOLUME_ID (values not read). Nothing was called.
- 7d20445 logic reused unchanged: a variant's `visual.subject` fixes its provider (`roman_lora` → comfyui, `illustration` → openrouter), `direction_settings()` never swaps, mock stays mock.
- New `content/routing.py`: `image_route(requires_roman)` and `check_route()`, called in `_prepare_direction` (so in every dry run, before any cost is approved): the variant must match the flag planned at stage 1 (`package.json requiresRoman`, passed as `WorkflowInputs.requires_roman`), and a Roman job without RUNPOD_API_KEY / RUNPOD_ENDPOINT_ID fails with those names, "no fallback to another provider or a real photo". A global IMAGE_PROVIDER does not decide (test with IMAGE_PROVIDER=comfyui: a non-Roman variant still goes to openrouter). The job record carries `route`.
- AI disclosure (R6.7, Q8 default yes incl. ads): there was no field yet ("planned"); package.json `aiDisclosure` = "KI-generiertes Bild (Roman, erstellt mit einem KI-Modell)" for every requires_roman package; stage 1 prints the route and "AI disclosure on". Tracker column in Phase 6.
- Credentials stay in `.env` / settings (SecretStr). `tests/test_routing.py` runs prepare + mock builds with fake RunPod and OpenRouter keys and scans prompts, job inputs and every JSON/TXT/MD file in the job folders: no key (nor its tail) appears. The Phase 4 e2e already checks the audit log for secrets.

---

## Phase 4: monthly social planner (done)

- `ca plan month YYYY-MM [--topic …] [--apply]` (`content/month_plan.py`, `cli/plan.py`). Count = graphicsPerDay × days within 30–60 (Nov: 60, Feb: 56); mix from `config/deliverables.json monthlyPlan` (PRD default per 60: LinkedIn 16, Facebook post 16, Instagram carousel 16, Facebook ad 12) scaled by largest remainder; a carousel is one asset. Days get 2 assets: the category furthest behind its share, never twice a day, not yesterday's category while another is left (no category on 3 days in a row, tested).
- requires_roman: every 8th LinkedIn/Facebook post or ad (`romanEvery`, editable); never carousels.
- The variant of each asset is simulated with the real rotation in date order; the plan proves R5.3 (no platform has 3 consecutive images with the same variant + treatment; tested over Nov 2026, Dec 2026, Feb 2027).
- Topics: approved unplanned ideas first, then `--topic`; best fit per category (verified service fit → ad, how-to/list wording → carousel, news/study wording → LinkedIn); service fit via `content/relevance.py` (unchanged logic). German keywords and plurals were added to the 5 verified services in `config/services.json` (German topics did not match: "KI-Chatbots" vs "chatbot").
- Each asset carries its German metadata template (caption, hashtags, headline, hook, CTA, alt text; ads: primaryText, headline, description, ctaButton; Roman: aiDisclosure). Hashtags: the existing limits (3–5, `config/formulas.json`); LinkedIn planned with exactly 3 so it also fits the context doc's "LinkedIn 0–3" (conflict logged; #BrandedGenius is required by the brief check). Post and ad slots now have `altText` (required for layout variants; German check).
- Dry run of the planned volume: pictures × the provider estimate (OpenRouter 2K $0.101; ComfyUI per config/comfyui.json). November 2026: 60 graphics, 124 pictures, about $12.20 (estimate). Each build keeps its own dry run and "ok".
- Output: `calendar/<YYYY-MM>-month-plan.json` and `.csv` (git-ignored). `--apply` writes assets with an approved idea into the weekly calendar CSVs as Approved rows (calendar v2 path: registry child items, inherited approval; Format "roman" for requires_roman); assets with only a typed topic are listed, not applied. Weekly commands unchanged.
- One free local run of `ca plan month 2026-11` was made on this machine to check the output: it applied registry migration 11 to `state/registry.db` (the registry backed it up first: `state/backups/registry-20261019T135115Z.db`) and wrote `calendar/2026-11-month-plan.json/.csv`. No `--apply`, no row written, nothing generated or called.
- R7.5 topic sources: the newsletter/scraper/manual flow is unchanged; `config/sources_de.json` (Phase 5) is the German starting list.

---

## Phase 5: YouTube research and production planning (done)

- Separate package `src/content_automation/youtube/` (topic, research, sources, scripts, workflow), command group `ca youtube` (`cli/youtube.py`), skill `.agents/skills/make-youtube/`, config `config/youtube.json` + `config/sources_de.json`. Shared only: registry (BG IDs, `ca item approve|reject`, audit, `set_design`), storage/tracker (Phase 6).
- Who researches (R9.3, inspected): `ca` has no LLM call; the Codex agent researches with web access and writes the German texts; `ca youtube` gives templates, folders and every free check. `check-sources` is the only step that opens URLs (free, no cost); tests serve local HTML fixtures through an httpx MockTransport.
- `ca youtube plan YYYY-MM --topic …`: up to 8 topics a month (config), Proposed `youtube` items (`youtube_longform`) with BG IDs, planned dates spread over the month, one folder each (R9.11). Topics come from the agent's research (real incidents first); nothing is invented by the command.
- Research TXT (R9.4): all 11 points incl. 11a/b/c, numbered sources `[S#]`, structure check (no placeholders, ≥2 sources with URL/title/publisher, every fact/quotation cites a listed source).
- `ca youtube check-sources BG-x [--override "reason"]` (R9.5): status, final URL, title (og:title or <title>), date (article:published_time, <time>…); quotations must be in the page text; facts whose numbers/key words are not in their source are flagged; "needs human check" for the rest, never "verified". Results replace the VERIFICATION section; package.json `sourceCheck`; failed → `ca youtube scripts` refused until fixed or overridden (override logged as a `decision` event by the user, plus package.json).
- Scripts (R9.6–R9.9): `ca youtube scripts` writes three internal English briefs (`.briefs/`, so the style folders hold exactly the R9.11 files) with the 8-step formula, the style's approach and the verified facts. Teleprompter check: no citations/URLs, no headings/labels, the German pass (no English leftovers, umlauts, banned phrases), no first-person experience phrases, style C needs an illustrative marker; length outside 1,300–1,600 words is a warning (Q4 open). `ca youtube bilingual` makes `script_DE-EN.txt` FROM the teleprompter (German word for word, English placeholders; English kept for unchanged paragraphs); `ca youtube check` verifies the German is identical paragraph for paragraph and every English block is filled, plus the difference check (shared word trigrams in openings and whole texts).
- `ca youtube select-style BG-x B` (R9.10): registry `script_style`, package.json `selectedStyle`, `storyboard_<style folder>.md`: one Markdown block per scene (paragraphs merged to ≥20 s at 130 wpm) with timecode, German line, English, visual direction, graphics, exact German on-screen text + English explanation, sources (verified facts found in the scene → their [S#]), transitions/pacing, placeholders. **PENDING:** the rest of the storyboard spec and its format (Q6): TODO in `youtube/scripts.py` (STORYBOARD_PENDING) and a line at the top of every storyboard.
- Formula: the 8-step YouTube formula is in `config/formulas.json youtube_longform` (Phase 1), used by the briefs and by the older `ca script` path.
- Mock package: `uv run python scripts/youtube_mock_package.py` → `outputs/previews/youtube/BG-001_deepfake-anrufe-im-namen-der-geschaeftsfuehrung/` (+ README). It runs plan → approve → research → a failing check (dead URL, misquote, unsupported fact; scripts refused) → fixed research → passed check → briefs → 3 teleprompters → bilingual → English → check → select B → storyboard. MOCK: the sources are invented test pages on example.org; the scripts are short (format preview, ~180–220 words, length warning shown).
- Tests: `tests/test_youtube.py` (11): template/structure, check passes, dead URL + misquote caught (§7.12), fact matching, fetch failure never raises, teleprompter rules, bilingual identity, difference check, slug, the 8-topic cap + approval gate + reject, one topic end to end in the R9.11 layout (§7.11).

---

## Phase 6: Drive and tracker code (done, code only)

- New folders in `storage.FOLDER_NAMES`: `Instagram Carousels`, `Facebook Posts` (plus the existing `Facebook Ads`, `LinkedIn`, `YouTube`). `ca drive setup` creates missing folders only; nothing is renamed or moved (R10.3 PENDING). Uploads of v5 packages go to their category folder (`package_folder_key`: package.json `category`); packages without a category (made before v5) keep their platform folder. Review uploads use the item's layout variant. The plugin manifest creates missing folders the same way.
- Drive API uploads take nested content folders (`YouTube/<YYYY-MM>/<BG-ID>_<slug>/<style>/`), remembered per key in drive_state.
- `ca youtube upload BG-x`: research file, storyboard and the six script files (internal `.briefs/` and package.json stay local) to `YouTube/<YYYY-MM>/<BG-ID>_<slug>/`, then one tracker row (Content ID = BG ID, Caption = the links). Mock and drive providers; the Codex-plugin path for YouTube topics is not built (clear message).
- Tracker (R11): registry columns `Category`, `Language`, `Layout Variant`, `Requires Roman`, `Selected Script Style` (config/tracker.json), appended after the existing columns and matched by header name; written values are recorded, so a hand edit is a conflict (not overwritten); manager fields never written (test).
- `docs/v5-drive-actions.md`: the exact operations waiting for Roman's "ok" (new folders via `ca drive setup`, the five headers, the UGC folder: list first, then trash after "ok"). Nothing was run against Google.
- Tests: `tests/test_drive_v5.py` (folders kept + added, category routing, nested Drive folders on a stubbed Drive service, headers at the end without touching manager fields), YouTube e2e now uploads to mock Drive and checks the tracker row.

---

## Phase 7: docs and final check (done)

- Docs: AGENTS.md (make-youtube, "plan month November", "apply the plan", layout variants, Facebook ad category, person rule via founder variants, German captions, LinkedIn 3:4, carousel playbook, Drive layout; removed UGC/podcast/YouTube-video phrases), CLAUDE.md (v5 summary), skills (make-calendar, make-carousel, make-content, write-script, show-content, upload, produce-video, make-video; new make-youtube), `ca help commands` (v5 phrases), PROGRESS.md (v5 section), README, USER-GUIDE, module-2/3 guides and SETUP-CODEX (v5 note at the top; removed workflows marked).
- Final run: `uv run ruff check .` clean; `uv run mypy --strict src tests` clean (235 files); `uv run pytest` 517 passed (baseline was 465). `scripts/e2e_v5.py` 9/9 (in the suite as tests/test_e2e_v5.py), `scripts/e2e_phase4.py` 8/8 (in the suite), `scripts/e2e_phase6.py` 7/7, `scripts/e2e_phase5.py` 9/9 after updating its criterion 9 (it checked "German sources disabled", which the live fix d5d9607 had already changed before v5; v5 wants them).
- Previews (git-ignored): `outputs/previews/design/v5_vs_references.png`, `outputs/previews/youtube/BG-001_deepfake-anrufe-im-namen-der-geschaeftsfuehrung/` (+ README.txt; MOCK).
- External calls in this run: none (no OpenRouter, RunPod, Google, Higgsfield, HeyGen, Gmail or web request). Local only: one free `ca plan month 2026-11` on this machine's registry (migration 11 applied, backup `state/backups/registry-20261019T135115Z.db`, plan files in `calendar/`).

### Acceptance criteria (PRD §7)

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | No audience-facing English in a mock end-to-end run (automated) | PASS | `scripts/e2e_v5.py` §7.1: German check over every reader text of the 4 built briefs, every text drawn on the rendered designs, the 3 teleprompter files (`ca youtube check`) |
| 2 | Generator loads no file from the competitor archive | PASS | `tests/test_archive_isolation.py` (static scan + audit-hook runtime test over load, pick, prompt build, render, brand, reference scan) |
| 3 | Contact sheet of all variants beside the approved references; Roman approves before the first paid batch | PASS (sheet) / NOT TESTABLE OFFLINE (approval) | `uv run ca design compare` → `outputs/previews/design/v5_vs_references.png`; Roman's approval is pending |
| 4 | Carousels: 5–6 slides, no counter, logo only last, website only last (automated) | PASS | loader rules (`tests/test_design_directions.py`), design check (`tests/test_design_check.py::test_v5_category_rules`), built carousel in `scripts/e2e_v5.py` §7.4 (5 slides) |
| 5 | Facebook posts and ads: separate templates, packages, Drive folders | PASS | FB-1..4/FB-R1 vs FA-1..3/FA-R1; `scripts/e2e_v5.py` §7.5 (separate packages, categories); `tests/test_drive_v5.py` (Facebook Posts vs Facebook Ads) |
| 6 | LinkedIn 3:4, real logo at a side corner, hash matches the official file | PASS (offline) | loader corner rule, design check (sha256 of the official file, corner), `scripts/e2e_v5.py` §7.6 (1080×1440). The sandbox registers its stand-in as the official logo; the real file's hash is in `config/brand.json` (`ff800645…`) and is checked the same way on this machine (`ca design compare` used the real logo) |
| 7 | Simulated month: no platform with 3 consecutive images of the same variant + treatment | PASS | `tests/test_month_plan.py` (Nov 2026, Dec 2026, Feb 2027), `tests/test_direction_pick.py::test_no_third_treatment_in_a_row`, `scripts/e2e_v5.py` §7.7 |
| 8 | Routing: requires_roman → RunPod, others → OpenRouter; no silent fallback; no secret in logs/outputs | PASS | `tests/test_routing.py` (5 tests incl. the secret scan), `tests/test_direction_build.py::test_every_roman_image_is_a_lora_job` |
| 9 | Monthly planner: 30–60 assets with a format mix, carousel = one | PASS | `tests/test_month_plan.py`, `scripts/e2e_v5.py` §7.9 (60 assets, 4 categories) |
| 10 | UGC, podcast and finished-video commands and skills gone; YouTube planning, carousel and research still pass | PASS | `tests/registry/test_thumbnail.py::test_podcast_commands_are_gone`; `VideoWorkflow = "reel_short"`; no `ugc_ad`/`podcast_clip` deliverables; skills/AGENTS.md updated; suite 517 passed incl. youtube, carousel, research tests |
| 11 | YouTube mock run: research TXT, 3 styles × 2 files, storyboard in the R9.11 layout; bilingual German = teleprompter; teleprompter has no English, citations or headings | PASS | `tests/test_youtube.py::test_one_topic_end_to_end`, `scripts/e2e_v5.py` §7.11 |
| 12 | Source check catches a dead URL and a quotation not in the page (fixtures) | PASS | `tests/test_youtube.py::test_source_check_catches_a_dead_url_and_a_misquote`, `scripts/e2e_v5.py` §7.12 |
| 13 | ruff, strict mypy, full offline suite pass; no paid or external call without an estimate and "ok" | PASS | ruff clean, mypy strict clean, 517 passed; no external call was made in this run |

### Questions only Roman can answer

1. **Q2 / references:** confirm that the approved references are `assets/reference/creative/facebook_ads/01–06` and `creative/carousels/carousel_01–11`; add the graphic designer's own outputs to `assets/reference/creative/designer/` (none found) so the comparison sheet shows them. No reference image was UNSURE.
2. **Background colour (D-1 vs references):** every approved graphic is near-black navy; the guide has 4 colours and D-1 says dark designs are Royal Blue. Allow a near-black (or a darker Royal Blue shade) as a dark token? See the sheet.
3. **Q3:** "Sie" (default, used) or "du"? The company carousels use "du", the ads "Sie".
4. **Q4:** YouTube length 10–12 min (default, used as a warning)?
5. **Q5:** which teleprompter app? (plain UTF-8 TXT for now)
6. **Q6 / R9.10 PENDING:** the rest of the storyboard spec and its format.
7. **Q7:** Opus Pro / Shorts clips (kept, untouched): still wanted?
8. **Q8:** AI disclosure also on Facebook ads with Roman (default yes, used).
9. **Q9 / R10.3 PENDING:** the Drive restructuring details; and the exact name/location of the UGC ad folder.
10. **Reels:** `reel_short` (Higgsfield) is kept (not named in R8). Keep or remove? HeyGen is unreachable now; remove its dormant adapter too?
11. **3:4 at OpenRouter:** LinkedIn pictures are made at 4:5 and cropped to 3:4 (the adapter's aspect list); a one-image paid test (about $0.10) would show whether the model accepts 3:4.
12. **Meta CTA list** (`config/meta_cta.json`) and **German source domains** (`config/sources_de.json`) were not checked online: please confirm or correct.
13. **LinkedIn hashtags:** context doc says 0–3, the code's rule is 3–5; planned as exactly 3 (incl. #BrandedGenius). OK?
14. **Monthly mix and Roman share:** PRD default mix (16/16/16/12 per 60) and Roman every 8th post/ad; change in `config/deliverables.json monthlyPlan`.
15. **Futura:** licensed Futura files are still missing (Jost stand-in).

### PRD §9 defaults used

Q1 static carousels (animation already deleted 2026-10-16) · Q2 references as above · Q3 "Sie" · Q4 10–12 min · Q5 UTF-8 TXT · Q6 Markdown, one block per scene · Q7 clips untouched · Q8 disclosure on ads too · Q9 new folders only, nothing renamed/moved.

---

## Roman via Higgsfield (2026-10-20)

### Audit (read-only, before the change)

- **Roman prompts and identity rules (today):** `config/design_directions.json` → `roman` (LoRA prompt pools: prefix `r0man_bg, a man`, outfits, angles, expressions, business/quiet-luxury settings, the "alone" rule, blocked props, LoRA strength 0.8–1.0, approved real photos 2/4/5/6/9 for the identity sheet). Prompt builder: `content/roman.py roman_prompt()` (seeded by the Content ID, quiet luxury 1 in 4, `{space}` from the layout's text side, free prompt checks). Founder variants: `FB-R1`, `FA-R1`, `LI-R1` in `config/design_directions.json` (visual subject `roman_lora`, provider `comfyui`, the LoRA prompt `ROMAN_PROMPT`: Roman right of centre, full bleed, text left on a scrim). The FD-1..FD-3 directions of Phase D are archived (`config/_archive/design_directions_phaseD_competitor.json`). Identity rules (D-8): Roman only by his LoRA, never a real photo; person check with an identity sheet (`ca job review --person pass|fail`).
- **requires_roman routing (today):** set at planning (the calendar's "roman" row or "as LI-R1"), stored in package.json `requiresRoman` and the registry; `content/routing.py check_route()` maps it to `comfyui` (RunPod Serverless, Z-Image Turbo + LoRA `r0man_bg_v2_step3000`) and fails clearly without RUNPOD_API_KEY/RUNPOD_ENDPOINT_ID; `workflows/direction_job.direction_settings()` uses the variant's provider, never swapped.
- **Higgsfield flow (today):** the Phase 3 animated carousel (Higgsfield stills and clips, `ca carousel record`) was deleted on 2026-10-16; there is no carousel Higgsfield code left. The live pattern is the reel video agent step: `ai/video/providers/higgsfield_plugin.py` (agent mode) writes `<job>/requests/scene-N.json` (prompt, aspect, start image, identity images, numbered instructions), the job pauses as `awaiting_agent`, Codex finds the plugin tool at run time, makes the clip, records it with `ca job complete "<job>" --step scene-N --file … --credits …` (or `ca job fail`, no retries), then `ca video resume`. Image jobs (`workflows/image_job.py`) had only code-mode providers (mock, openrouter, comfyui, template).
- **Higgsfield Soul, characters, aspect ratios, credits (what the repo says):** `docs/PHASE3-DECISION.md` §10 (plugin listing of 2026-10-16): image tool `mcp__codex_apps__higgsfield_generate_image`, model then selected `gpt_image_2_5`, reference images via `image_references` (uploaded media UUIDs or HTTPS URLs), no negative-prompt field, about 0.25 credits per 1k image for that model; §2: the MCP officially offers "Soul characters". **UNKNOWN in the repo:** the Soul 2.0 model id in the plugin, how a saved character is referenced (the `@Roman Traenkle` token, a character id parameter, or both), Soul 2.0's credits per image, and its aspect ratios (the list used here, 9:16, 3:4, 2:3, 1:1, 4:3, 16:9, 3:2, comes from the user's brief, not from the code or a listing). Old unverified estimates: 5 credits per still, $0.075 per credit (deleted `config/carousel_design.json`).
- **Person detection available offline:** OpenCV Haar cascades (bundled with opencv-python-headless; used by `ca lora prepare` and the face check in `workflows/person_check.py`); rembg needs a model download (not used here).

### Decision (2026-10-20)

- **Roman via Higgsfield Soul 2.0:** Codex makes his images with the Higgsfield plugin, from
  the saved character "Roman Traenkle". The prompt comes from the new guidelines
  (`config/roman_image_guidelines.json`, `brand/roman-image-guidelines.md`); the old LoRA
  guidelines are archived in `config/_archive/roman_lora_guidelines_v5.json`.
- **RunPod disabled:** the RunPod/ComfyUI LoRA route is off by config: `content/routing.py
  DISABLED`, `ROMAN_IMAGE_PROVIDER` defaults to `higgsfield_soul`. Its code stays.
  `ROMAN_IMAGE_PROVIDER=comfyui` is refused with a clear message, and there is no fallback.
  Non-Roman images stay on OpenRouter (Nano Banana 2 kept).
- **Founder variants:** FB-R1, FA-R1 and LI-R1 now use `provider higgsfield_soul` and
  `pick side`, with two mirrored layouts, `roman_right` (S-R) and `roman_left` (S-L). The
  scrim covers only the text two-thirds and fades out before Roman's third.
- **Flow:**
  1. Stage 1 picks the combination by rotation (or takes an override) and stores
     `romanCombination`.
  2. The dry run shows "≈ 5 Higgsfield credits per attempt (estimate, not calibrated), at
     most 2 attempts".
  3. After the user's "ok", the build writes `outputs/higgsfield/<key>/job.json` with the
     prompt, the character, Soul 2.0, the aspect, the count, the expected output path and
     the estimate. It stops (item `waiting`) and shows Codex's numbered steps; no registry
     job exists yet.
  4. Codex runs the plugin, saves the PNG and runs `ca higgsfield record <key> --file …
     --credits …` (or `ca higgsfield fail`).
  5. The next build runs the person-zone check and the safe crop, draws the German text,
     the logo and the CTA, then runs `ca design check` and the strict Roman checks
     (`workflows/roman_check.py`).
  6. The person check and the visual review follow. A failed zone check asks for attempt 2;
     after 2 attempts the item fails. Every attempt's credits count toward the cost.
- **Tracker:** Layout Variant shows "LI-R1 S-L/BG-2/P-3/H-1".

### UNKNOWN (Higgsfield plugin; nothing was called in this run)

- **Character reference syntax:** UNKNOWN. The default is an `@Roman Traenkle` token at the
  start of the prompt (config `characterToken`). The job instructions ask Codex to also
  select the saved character if the tool has a character or reference parameter, and to
  record the syntax that worked here.
- **Soul 2.0 model id and tool name:** UNKNOWN. §10 of PHASE3-DECISION lists
  `mcp__codex_apps__higgsfield_generate_image`, but Soul 2.0 is not confirmed. Codex
  finds the tool at run time.
- **Soul 2.0 aspect ratios:** taken from the user's brief (9:16, 3:4, 2:3, 1:1, 4:3, 16:9,
  3:2) and not checked against the plugin.
- **Credits per image and USD per credit:** UNKNOWN. Config uses 5 credits and $0.075 per
  credit, marked "estimate, not calibrated". A credit amount that the plugin does not
  report is counted as the estimate and marked as such.
- **Spelling:** Hunspell is not installed on this machine, so spelling is Codex's
  visual-review step (recorded per image).
- **Check thresholds:** the calm-zone thresholds (brightness spread 30, detail 12) and the
  skin-tone person detection are calibrated only on drawn stand-ins. Real Soul 2.0 output
  should be checked on the first images.
