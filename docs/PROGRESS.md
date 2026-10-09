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

- [ ] ComfyUI audit: hardware, local vs cloud, cost.
- [ ] Decide the model, the identity method and the licence.
- [ ] ComfyUI API connection.
- [ ] Identity workflow with Roman's 9 photos.
- [ ] Logo compositing.
- [ ] Identity check + retry.
- [ ] Nano Banana fallback switch.
- [ ] AGENTS.md / docs update.

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
