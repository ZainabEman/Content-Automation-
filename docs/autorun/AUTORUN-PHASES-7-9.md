# AUTORUN LITE — Phases 7, 8, 9
Branded Genius Content Automation. Save as `docs/autorun/AUTORUN-PHASES-7-9.md`. This file is the spec. Don't write PRD files.

## 0. Run rules (quota-saving)
- Read only this file + the last LOG.md entry. Don't re-read the old autorun file or reports. Use Grep for lookups; no subagents.
- Do steps in order with no pauses. **Resume:** continue at the first step not marked DONE in `docs/autorun/LOG.md`.
- **Per step:**
  1. Implement the minimum that meets the bullets.
  2. Add 1 basic test per new command (happy path only).
  3. Run `uv run ruff check <changed files> && uv run pytest <new test files> -q`.
  4. Commit only if the exit code is 0.
- After every step:
  - add a 2-line LOG entry (step, hash, needs-review)
  - print `P<N>S<M> done <hash>` in chat and nothing else
- **Full check, once at the very end:** `uv run ruff check . && uv run mypy --strict <usual targets> && uv run pytest -q`. Fix only what fails.
- **Don't:** paste code or output, write extra docs, refactor unrelated code, or add features not listed here.

## 1. Hard rules
- **Context:**
  - Codex Desktop skills (`.agents/skills/*/SKILL.md` + phrases in AGENTS.md) call the `ca` CLI.
  - State lives only in `registry/` (BG IDs, 5 statuses, versions, jobs, dry runs/authorizations, audit log).
  - Plugin calls happen only in skills: request file → `ca jobs check` → plugin → `ca … record`.
  - Paid work = dry run → user "ok" → `--authorize <dryrun_id>`.
- **No paid or real external calls**, including Google, Higgsfield, HeyGen, OpenRouter, RunPod and Opus Pro. Tests use fakes and tiny FFmpeg fixtures. Paid tests are the user's manual steps.
- **Out of scope:** LoRA, ComfyUI, RunPod, person images, Phase 10 (reports, live tests, merge).
- Never read or print `.env`, `.secrets/` or tokens.
- **Git:**
  - Commit `phase <N> step <M>: …`.
  - Never push, merge, rebase or reset.
  - Branches: `phase-7-review` from `phase-6-scripts`; `phase-8-production` from Phase 7; `phase-9-distribution` from Phase 8.
- Skills never approve, reject, select or say "ok" for the user. Published needs a URL. Mock results stay labelled mock.
- Old packages and files must still load. Existing phrases keep working.
- If unsure, pick the simplest reversible option, put the value in `config/*.json` (`"_note": "client to confirm"` if it's a client choice), and note it in LOG under needs-review.
- **Stop only if:** a paid or external call, a secret or a manual user action is needed; checks still fail after 2 tries; or user data would be deleted.

## 2. PHASE 7: review gate + finishing graphics/carousels (branch `phase-7-review`)
**Step 1: fixes + review + regeneration**
- **Fixes:**
  - store the design picks before the provider call, so a rebuild reuses them
  - an authorization auto-closes when all its jobs are finished
  - migrated decisions use actor `migration`
  - ad primary text moves into the ad brief field
- `ca review list` (generated, not reviewed) and `ca review show BG-x` (version, asset paths, checks, costs, last feedback). Decisions use the existing `ca item approve/reject/revise` on the review gate.
- **Regeneration:**
  - A review revise makes v(n+1) in `<package>/versions/v<n>/`.
  - `ca regenerate BG-x [--only part,…]` makes a dry run for those parts. Unchanged parts are copied. Text-only changes re-render the overlay for free.
  - After regeneration, review goes back to not_reviewed.

**Step 2: upload after approval + carousel formats + retry**
- `config/storage.json` `upload.require_review: true`. With it, there's no auto-upload after generation; a review approve queues the upload of the approved version to `<Platform>/<Content ID or BG ID>/v<n>/`.
- `ca drive setup` adds the folders YouTube, Shorts, Podcasts, Facebook Ads and TikTok (mock).
- **`STORAGE_PROVIDER=plugin`:** `ca` writes upload requests, the skill uploads them with the Drive plugin, and `ca drive record <job> --file-id --link` records the result.
- **Carousel `--format static|animated|single_video`** (default animated, client to confirm):
  - static = 8 PNGs, stills only
  - single_video = the 8 clips joined with FFmpeg
  - the dry run shows the cost of the chosen format
- **`ca jobs retry [BG-x|--all-failed]`:** dry run → "ok" → `--authorize`, capped at max_attempts.
- `ca costs report` shows estimate vs actual per job type. `ca costs calibrate --provider X [--apply]` writes to config only with `--apply`.

**Step 3: graphics finishing + skills**
- Provider per deliverable in `config/deliverables.json` + a `--provider` override.
- Image checks: size, not blank.
- Ad strict check: the overlay and ad copy pass the `ca script check` number/claim rules.
- A configured fallback provider is offered as its own dry-run line, used only with "ok". Never silent.
- **New skill `review-assets`:** "what needs review", "show BG-x for review", "regenerate BG-x", "redo slide 3 of BG-x".
- **Update make-carousel (format), make-content (provider/fallback), and the upload skill (plugin route).**
- Also add: "retry failed jobs", "show costs".
- Add all new phrases to AGENTS.md and `ca help commands`.

## 3. PHASE 8: YouTube + podcast production (branch `phase-8-production`)
**Step 1: production status + import + handoff**
- **New status dimension `production`** for youtube/podcast:
  - not_started → awaiting_recording → recorded → editing → edited → final
  - going back to editing needs a revise
  - it starts at awaiting_recording when the script and brief checks pass
  - the review gate opens at final
  - `ca production list [--month]` shows finals vs targets (8 YouTube/month); `ca production set BG-x <status>` allows only the legal moves
- **`ca import BG-x <file> --as recording|edit|final|thumbnail|audio`:**
  - copies into `versions/v<n>/production/<as>/`
  - checks with ffprobe (it decodes; a YouTube final must be 16:9 and ≥1080p)
  - registers an artifact and moves the status
  - originals are never changed
- **`ca handoff BG-x --to "<name>"`:** builds a `handoff/` folder (script.md, brief.md, B-roll list, assets list, a README) and sets editing.

**Step 2: thumbnail + podcast + wiring + skills**
- `ca thumbnail BG-x`: 1280×720 through the existing overlay, using an imported image as the background, with text ≤5 words from the brief.
- **Podcast:**
  - **roman:** import the recording.
  - **heygen:** the existing make-video plugin pattern. If the voice ID is missing from config, the dry run stops with "HeyGen voice ID not configured (client)".
  - `ca podcast audio BG-x`: MP3 with FFmpeg loudnorm (-16 LUFS, config).
- Approved finals upload to the YouTube/Podcasts folders. The tracker gets a Production status column.
- **New skill `produce-video`:** "production status", "import recording/final for BG-x <path>", "send BG-x to the editor <name>", "BG-x recorded", "make thumbnail for BG-x", "export podcast audio for BG-x".
- **Update make-video (HeyGen podcast).** Add the phrases to AGENTS.md and help.

## 4. PHASE 9: clips + distribution (branch `phase-9-distribution`)
**Step 1: Opus Pro clips (manual provider)**
- The provider setting `clips.provider: manual` (default); `api` is a stub that raises "not configured".
- `ca clips handoff BG-x` needs production=final and review approved. It writes a handoff note: the video path, the request for 10–12 candidates, and 9:16.
- `ca clips import BG-x <folder>` creates candidate `short` items (parent = the video). ffprobe checks: vertical, 15–90 s.
- `ca clips select BG-x 2 5 7 9`: the selected clips are approved; the rest are rejected with "not selected". The count must be 4–5 (config) unless `--force`.

**Step 2: prepare + publish + skills + final check**
- `config/platforms.json`: sizes for YouTube 16:9; Shorts/TikTok/Reels 9:16; IG 1:1/4:5; LinkedIn 1:1; FB 1:1; FB ads 1:1, 4:5 and 9:16.
- `ca prepare BG-x [--platforms]` resizes the approved version into `versions/v<n>/platforms/<p>/`.
- `ca copy template/save BG-x --platform` reuses the Phase 6 check.
- A platform is ready when its variant + copy exist and review is approved.
- **Publishing:**
  - `ca publish list --ready`
  - `ca publish mark BG-x --platform p --url <url>` (URL required) → published
  - `ca publish fail BG-x --platform p "<reason>"`
  - no direct integrations (`config/publishing.json` `integrations: {}`)
  - the tracker gets Publication status + URL (compact per platform), and prepared variants upload after approval
- **New skills:**
  - `clips`: "make clips from BG-x", "import clips for BG-x <folder>", "select clips … for BG-x"
  - `distribute`: "prepare BG-x for all platforms", "what's ready to publish", "BG-x is live on LinkedIn <url>", "BG-x failed on TikTok <reason>"
- Add the phrases to AGENTS.md and help.
- Run the **full check** (§0).
- Write `docs/autorun/REPORT-PHASES-7-9.md` (max 30 lines): commits, test total, needs-review, client questions, and the user's manual tests:
  - the first paid Higgsfield carousel, then `ca costs calibrate`
  - the Drive plugin upload test
  - one Roman recording import
  - HeyGen once the voice ID exists
  - one Opus Pro run
  - one real post with its URL recorded
  - a Codex phrase test list of every new phrase, one per line
- Stop. Don't start Phase 10.
