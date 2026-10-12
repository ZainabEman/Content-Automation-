# Progress – Content Automation v2

## Phase 1

- [x] Step 1 – Audit: inspect the current automation (research, copywriting, approval, cost approval, folders) and note what to reuse.
- [x] Step 2 – Calendar: generate a proposed content calendar from collected research (date, topic, source, platform, content type).
- [x] Step 3 – Approval + generation: save the calendar, wait for approval (all or selected rows), generate content for approved rows only, LinkedIn included.
- [x] Step 4 – Drive: main content folder with LinkedIn, Facebook and Instagram folders; upload images and MP4s to the matching folder.
- [x] Step 5 – CSV: tracking CSV in the main folder, filled by the workflow without overwriting manual status or date edits.
- [x] Step 6 – Wrap-up: syntax/import check, update docs, summary.

## Phase 1 done (2026-10-10)

- Changed: weekly calendar with approval (Proposed → Approved/Rejected → Generated); only approved rows are generated, with one combined dry run and one "ok"; new `linkedin_post` (Roman optional); finished images/MP4s uploaded to Drive `<Platform>/<Content ID>/` (mock by default); "Content Tracker" Google Sheet that keeps the manager's edits; CSV export.
- Main files: `content/calendar.py`, `content/tracking.py`, `storage/` (`__init__.py`, `providers/mock.py`, `providers/drive_api.py`), `cli/__init__.py` (`ca calendar|drive|tracking`), `content/package.py` (`contentId`, `researchSource`, `uploads`), `config/calendar.json`, `config/deliverables.json`, `.agents/skills/make-calendar/`, `AGENTS.md`, `docs/guides/module-4-calendar-drive.md`, `docs/SETUP-CODEX.md` §9.
- Checks: ruff + mypy clean; no tests run and no real Google or paid calls yet (see Phase 4 test list).
- Open items: the client confirms the tracker deviation (Google Sheet instead of a CSV, PRD §5); a Sheet whose app formatting failed halfway is re-formatted only by the next `ca drive setup`.
- Setup still needed: Google Cloud project with the Drive API and Sheets API enabled; OAuth Desktop client JSON saved as `.secrets/google_oauth_client.json`; `uv run ca drive setup`; `STORAGE_PROVIDER=drive` and `DRIVE_SHARE_WITH=<manager email>` in `.env`.

## Phase 2

- [x] Step 1 – Audit + decision: hardware, local vs cloud, models, identity method, licences, cost (`docs/PHASE2-DECISION.md`).
- [x] Step 2 – Text overlay renderer + prompt change (free).
- [x] Step 3 – ComfyUI adapter + RunPod client + workflow JSON for both models (free, no calls).
- [x] Step 4 – LoRA tooling for AI Toolkit on a RunPod Pod (built free; run only after consent + "ok").
- [x] Step 4b – One-command remote LoRA training: `ca lora train-remote --model qwen|zimage|both` + `ca lora status|stop` (built free; nothing called).
- [x] Step 4c – Kaggle notebooks: free Z-Image LoRA training + likeness test (`notebooks/`, `docs/guides/kaggle-lora.md`; built, not run).
- [ ] Step 5 – Comparison run + model choice (paid, after "ok"). Waits until the RunPod account has credit (noted 2026-10-10); the LoRA training (`ca lora train-remote`) comes first.
- [ ] Step 6 – Wiring: person check + retry, Nano Banana fallback switch, AGENTS.md/docs.

## Phase 3

- [x] Step 1 – Audit + decision (`docs/PHASE3-DECISION.md`; sample carousels analysed).
- [ ] Step 2 – Design system from the sample (1:1 1080×1080, 8 slides, 5 s, left text zone, last-slide CTA, no people).
- [ ] Step 3 – Topic stills (text-free, no people; ComfyUI/Z-Image or Higgsfield image).
- [ ] Step 4 – Animation + overlay → `slide_01..08.mp4` (Higgsfield i2v for illustration slides, local for graphic slides; text/logo on top; automatic set check).
- [ ] Step 5 – Wiring: single-"ok" flow (package + calendar), Drive, tracker, summary, skills.
- [ ] Step 6 – One paid test carousel (after "ok" on its max).

## Phase 4 test list

Deferred from Phase 1 (no tests until Phase 4):

- [ ] `ca calendar new` real run (newsletter list, digest, own topics), then `check` and `show`.
- [ ] Approve / reject (all, some; a Generated row is refused).
- [ ] `ca calendar generate` dry run: one combined cost per row + total.
- [ ] One paid build after "ok" (`generate --build`, person/set checks, row turns Generated).
- [ ] Mock sync (`STORAGE_PROVIDER=mock`): files, fake links, `tracking.csv`, calendar copy.
- [ ] Real `ca drive setup` + `ca drive sync` (folders, sharing, Content Tracker header, dropdowns, date format).
- [ ] Idempotent re-sync: no file uploaded twice, no duplicate folders or rows.
- [ ] Failed-upload retry: `upload_failed` recorded, row skipped and listed, next sync uploads it and adds the row.
- [ ] Tracker upsert keeps the manager's statuses, dates, formatting, sorted rows, extra and reordered columns.
- [ ] `ca tracking export` (local CSV + read-only "Content Tracker.csv" replaced in place) and `ca tracking show`.
- [ ] LinkedIn caption checks (120–250 words, hook on line 1, 3–5 hashtags incl. #BrandedGenius).
- [ ] "No person" LinkedIn image (`post.person: false`): flagged in the dry run, no identity photos, no person check.

Deferred from Phase 2:

- [ ] Nano Banana prompts byte-identical with the overlay off (compare real prompts before/after Phase 2).
- [ ] ComfyUI upscale quality: model size (e.g. 1104×1376) → target (2K, 1638×2048) with Pillow Lanczos; optional upscale node (`upscaleNode`) against Lanczos only.

## Decisions

Approved 2026-10-10 (after the Step 1 audit).

- Calendar: `calendar/<YYYY-Www>.csv` (e.g. `2026-W42.csv`), read-only copy in Drive `Content Automation/Calendar/`. Columns: Row, Planned date, Topic, Research source (`newsletter:<date>#<n>` | `topic:<text>` | `article:<id>`), Platform, Content type (deliverable name), Status (Proposed/Approved/Rejected/Generated), Package, Content ID (`2026-W42-03`).
- Cadence in `config/calendar.json`; default 5 posts/week: LinkedIn Mon+Wed, Facebook Tue+Thu, Instagram carousel Fri.
- Codex commands: "make calendar [next week]", "approve all" / "approve 1 3 5", "reject 2", "generate approved" (stage 1 per approved row, then one combined dry run with cost per row + total and one "ok"; person and set checks unchanged), "sync drive".
- LinkedIn: new deliverable `linkedin_post` = 1 image (1:1, current Nano Banana) + text. Roman by default; the writer may omit him when the topic fits, and the dry run flags that choice. Caption 120–250 words, hook in line 1, 3–5 hashtags.
- Drive: Python script with the Drive API (not a Codex plugin); OAuth Desktop client, scope `drive.file`; client JSON in `.secrets/google_oauth_client.json` (git-ignored); one browser sign-in at `ca drive setup`. The script creates `Content Automation/{LinkedIn,Facebook,Instagram,Calendar}/<Content ID>/` itself.
- Tracking file: the Google Sheet "Content Tracker", read and updated cell by cell with the Sheets API (changed in Step 5; no CSV re-uploads), with a CSV export option; the app writes only its own columns and never touches Approval status, Publishing status or Publication date once set. Deviation from PRD §5, to confirm with the client.
- Files to add: `content/calendar.py`, `content/tracking.py`, `storage/` (`providers/drive_api.py`, `providers/mock.py`, `STORAGE_PROVIDER`), `.agents/skills/make-calendar/SKILL.md`, `docs/guides/module-4-calendar-drive.md`.
- Files to change: `cli/__init__.py` (`ca calendar new|check|show|approve|reject|generate`, `ca drive setup|sync`; sync also at the end of a finished build), `config/deliverables.json`, `brief.py`, `quality.py`, `package.py`, `core/config.py`, `doctor.py`, `.env.example`, `.gitignore`, `pyproject.toml` (google-api-python-client, google-auth-oauthlib), `docs/README.md`.
- AGENTS.md edits: Skills (`make-calendar`), strict selection + Format list (`linkedin_post`, LinkedIn caption line), person rule (Roman optional on LinkedIn), Playbooks ("Calendar", "Drive sync"; "Idea to package" from an approved row), Plugins line (Drive is a script, not a plugin).
- v1 log moved to `docs/PROGRESS-v1.md`.
- Step 2: `ca calendar new` fills slots in weekday order: picks (`--topic`, `--idea`, `--article`) first, then the newest list and the 14-day digest; sources already planned in another week are skipped; `--replace` only while every row is Proposed. `/calendar/` is git-ignored like `/research/`.
- Step 3: `Package` is written at stage 1 (it links the row to its package); the row turns Generated when package.json says `draft` (every part made). `generate` = stage 1 + combined dry run (free); `generate --build` builds each ready row once; rows waiting for a person/set check continue with `ca content build`; failed rows are skipped and reported. "No person" = brief `post.person: false` (LinkedIn only) → design without the man (`postFamily.compositionNoPerson`, no layout letter, no identity photos, no person check).
- Step 4: `storage/` (`STORAGE_PROVIDER` mock = `outputs/drive/` with fake links, the default; drive = Drive API, Google libraries imported lazily). `ca drive setup` is the only browser step (token and folder IDs in `.secrets/`); `ca drive sync [folders]` defaults to every calendar package plus this/next week's calendar copy. package.json gains `contentId` (stamped by `ca calendar generate`; otherwise the folder name is the Drive folder) and `uploads` (per file: provider, ID, link or `upload_failed`). Auto-sync only when a package is complete (`draft`); in-review images are never uploaded. Calendar copy after new/approve/reject/generate, read-only via a Drive content restriction. A same-name file already in the target folder is updated, never duplicated.
- Step 5: `content/tracking.py` holds the merge rules for both providers: columns found by header (extra columns and a new order survive), upsert by Content ID, only changed workflow cells written, Pending/Pending/blank only on a new row, rows never deleted. Drive: `ca drive setup` makes and formats the Sheet once (frozen bold header, dropdowns, date validation + yyyy-mm-dd, wrapped Caption); a Sheet found by name is never re-formatted; the tab is tracked by sheetId. A row is written only for a complete package whose files all uploaded; others are listed as "Tracker waits for". Ad versions: one block per ad image (`— Version N —`, image, headline/subheadline/button, caption); package.json gains `researchSource` (stamped with the Content ID). `ca tracking export` (default `outputs/content-tracker.csv` + read-only "Content Tracker.csv" in the main folder) and `ca tracking show`. Google Cloud steps in `docs/SETUP-CODEX.md` section 9; PRD §5 deviation line updated to the Sheets API.

Phase 2 – approved 2026-10-10 (after the Step 1 audit; details and links in `docs/PHASE2-DECISION.md`).

- Ad text: the app renders the headline, subheadline and CTA button as an overlay after generation (like the logo); the model prompt asks for clean space for the text and no lettering. Font: Futura files from `assets/fonts/` when present (brand.json: Futura Bold headings, Futura Medium sub-headings); `assets/fonts/` does not exist yet, so the fallback is Jost (Google Fonts `ofl/jost`, SIL Open Font License 1.1, variable weight). Scope: see the next line.
- Model: Qwen-Image-2512 vs Z-Image Turbo (both Apache 2.0 per the audit), each with a character LoRA; a small comparison after training picks the winner on Roman's likeness first, then cost. Qwen-Image-2512's own licence page: `apache-2.0` (checked 2026-10-10, before training).
- Identity: character LoRA from the photos in `assets/reference/identity/person_01/`, trained with Ostris AI Toolkit. Training + likeness test: free on Kaggle (Z-Image Turbo; changed 2026-10-10, see below); paid alternative: a temporary RunPod Pod (`ca lora train-remote`). No InsightFace-based tools (PuLID, InstantID, IP-Adapter FaceID, ReActor/inswapper).
- Check: the existing Codex vision person check + redo-with-cost flow stays unchanged; a dlib score is later and optional.
- Execution: RunPod Serverless ComfyUI worker, called from a script through `IMAGE_PROVIDER=comfyui` (new adapter in `ai/image/providers/`). Nano Banana (`openrouter`) stays the default until Phase 4 passes.
- Budget: one-time ≤ $25 (LoRA training + comparison); every paid run still needs the user's "ok" on the exact cost first.
- Handled by the user: Roman's written consent (`CONSENT.md` in the identity folder), RunPod API key + endpoint ID in `.env`, Futura licence check.
- Overlay scope (answered 2026-10-10): every image from a provider that draws no text (ComfyUI): Facebook posts, Facebook ads and all LinkedIn formats; Nano Banana keeps its model-drawn text. Provider capability `draws_text` (openrouter and mock true; comfyui false in Step 3) + `TEXT_OVERLAY=auto|always|never` (default auto). Phase 3 reuses the renderer for carousel slides.
- Step 2: `workflows/text_overlay.py` (Pillow): base image → text → logo. Zones per format in design_system.json `textOverlay` (panel per layout A/B/C → left/right, D → bottom, no person → left; footer strip), wrap then shrink within the size range, an error instead of cut text, checked in the dry run before any cost; zones may not reach the logo corner (`logo.logo_zone`); scrim (dark shade of the background colour) when the measured contrast is below the zone's minimum. Prompt with the overlay: no text/letters/logos, calm negative space in the named areas, no typography or font lines; without it byte-identical. Fonts: `assets/fonts/` Jost Regular–ExtraBold + OFL.txt; families `["Futura", "Jost"]`, so Futura files dropped in win (other font files are git-ignored). `ca overlay preview --format <name> --image <file> [--layout X | --no-person]` (free) writes `outputs/overlay-preview/`.
- Step 3: adapter `ai/image/providers/comfyui.py` (next to openrouter.py, registry name `comfyui`) + RunPod client `providers/runpod.py`: async `/run`, poll `/status` (`pollSeconds`), cancel at `timeoutSeconds`; no retry and no fallback, errors end with "switch with IMAGE_PROVIDER=openrouter". `IMAGE_MODEL` = workflow (`qwen_image_2512` | `z_image_turbo`); `config/comfyui/workflows/<name>.json` (API format) + `<name>.map.json` (node/input per prompt, negative, seed, width, height, steps, cfg, lora_name, lora_strength; `loraBypass` for no-person images: the LoRA node is removed). Identity = LoRA: `capabilities.identity_prompt` (trigger word from config) replaces the photo identity block, no reference images are sent; photo workflows with a person are refused under comfyui. Sizes: model size per aspect (multiples of 16, ~1.5 MP) → `targetLongSide` per IMAGE_DESIGN_SIZE with Lanczos. Cost: `config/comfyui.json` (48 GB serverless $0.000486/s, seconds per image, cold start + idle per request) → dry run "estimate" + cost basis; details.json `providerMetrics` (delayTimeMs, executionTimeMs, seeds) and `actualCostUsd` from RunPod times; build summary shows actual vs estimate per part (package.json `estCostUsd`). Job time budget follows `timeoutSeconds`. `ca doctor` checks RUNPOD_* and the ComfyUI config. Guide: `docs/guides/runpod-comfyui.md`. Worker 5.11.0 format in PHASE2-DECISION.md. Step 5: compare node settings with the official templates.
- Step 4: `ca lora prepare` (refused without `CONSENT.md`: Name, Date, Scope training + upload; photos from person_01/ + extra/: one face (OpenCV 4.x Haar frontal + profile, `--keep` for a face checked by eye), ≥768 px short side, no duplicates (sha256 + dHash); <9 refused, <15 warned; upright, EXIF stripped, short side 1024, captions `r0man_bg, <captions.json or "a man">`) → `outputs/lora/dataset_<date>.zip`. `ca lora config --model qwen|zimage` → AI Toolkit YAML (example defaults, Pod paths `/workspace/lora/...`) + estimate (L40S $1.09/h × hours from `config/lora.json`). `ca lora set <model> <file>` → `loraName` in comfyui.json. Trigger word `r0man_bg` in comfyui.json; `idleSeconds` 15. Cost fix: provider capability `batch_images` (comfyui): a package build makes all images back-to-back, then the person checks (one per build; Nano Banana keeps its stop-after-each-image flow); the estimate counts one cold start per build; the RunPod actual is (delay + execution) × price. New dependency: opencv-python-headless (<5, Apache 2.0). Guide section 7 "Train Roman's LoRA on RunPod".
- Step 4b: `src/content_automation/lora_remote.py` + `ca lora train-remote --model qwen|zimage|both [--yes]`, `ca lora status`, `ca lora stop`. Without `--yes`: consent check, `ca lora prepare` if no dataset, estimate (L40S $1.09/h × (0.5 h setup + 2 h Qwen + 1 h Z-Image)) and the cap at `remote.maxHours` (4 h, `config/lora.json`). With `--yes`: dataset + per-run YAMLs (`training_folder` `/workspace/lora/output/<run>`) + `train.sh` uploaded through the volume's S3 API (boto3, new dependency; bucket = volume ID, endpoint per datacenter from `GET /networkvolumes/{id}`), Pod via REST `POST /v1/pods` (AI Toolkit template `0fqzfjy6f3`, `NVIDIA L40S`, volume at /workspace, 150 GB container disk, `dockerStartCmd` = the script). The script trains each model in turn (`timeout`), copies every .safetensors to `models/loras/<run>_<file>`, writes `lora/runs/<run>/status`, then terminates the Pod (runpodctl / REST, every minute). Locally: poll every 30 s, samples to `outputs/lora/<model>/samples/<run>/step_<n>/`, `outputs/lora/runs/<run>/train.json` (status, cost = costPerHr × time, checkpoints); Pod terminated at the hard limit, on Ctrl+C, any error (3 failed polls in a row) or 5 min after a final status. One Pod at a time (local record + Pods named `ca-lora-`). New .env: `RUNPOD_NETWORK_VOLUME_ID`, `RUNPOD_S3_ACCESS_KEY`, `RUNPOD_S3_SECRET_KEY` (doctor warns). AGENTS.md playbook "Train LoRA" + make-content rule: "train lora" → this command, always behind the cost "ok". Guide section 8 (section 7 = manual fallback).
- Training = Kaggle, free (decided 2026-10-10): `notebooks/kaggle_train_lora.ipynb` (AI Toolkit, low-VRAM, bf16 (emulated on T4) or fp32, never fp16; stops on 0/NaN loss in the first 30 steps; resumes from the newest usable checkpoint; stops itself after 9 h; one zip) and `notebooks/kaggle_test_lora.ipynb` (6 prompts × strength 0.7/0.9/1.0, fixed seeds, contact sheet). Only Z-Image Turbo fits Kaggle's 16 GB; a Qwen-Image-2512 LoRA needs ≥24 GB (paid). Generation = RunPod Serverless later (needs credit). Kaggle's terms on commercial use of trained outputs are unverified: read them before production use. Guide: `docs/guides/kaggle-lora.md`.

Phase 3 – decided 2026-10-10 (details in `docs/PHASE3-DECISION.md`; these override earlier Phase 3 notes).

- Nano Banana paused: nothing new is built for it; it stays in the code until Phase 4.
- No Roman on any carousel slide: topic visuals only, so no person check, identity photos or LoRA for carousels.
- Design: a hybrid led by Higgsfield (budget on demand). Higgsfield image-to-video animates the illustration elements that move in the sample; pure graphic/text slides are animated locally (free); text and logo are always rendered by the app on top.
- Style: must match the sample carousels in `assets/reference/creative/carousels/` (8 slides, 1:1, 5 s, dark navy + blue particle wave, neon icons and white 3D robots, left text zone, logo on the last slide, a CTA with a Like/Share/Save row).
- One "ok" = the full carousel, end to end (dry run: cost per slide, total, max with one retry per clip). Then without stops: stills → Higgsfield clips → local graphic slides → text/logo on top → `slide_01..N.mp4` + stills + caption/hashtags → Drive `Instagram/<Content ID>/` → tracker row (Pending/Pending) → one summary (Drive link, slides, real cost vs estimate, fallbacks). Only fallbacks: a clip that fails twice → local animation for that slide (named in the summary and the tracker notes); a spend that would exceed the max → stop and ask. The set check runs automatically and only reports. The same flow applies to "generate approved" for Instagram rows. The make-video skill runs all clips under the one approval.
- Open (PHASE3-DECISION §9): carousel language (the samples are German), logo on the last slide only, plugin credits vs API, the still source.
