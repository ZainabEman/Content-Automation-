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
