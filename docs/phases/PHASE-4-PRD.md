# Phase 4 PRD — Content-item foundation (v3 spec)
Branch: phase-4-items (from phase-3-carousel). Date: 13 Oct 2026.

## 1. Goal
Every piece of content gets one stable ID (BG-###) and one record holding its idea, sources, versions, five separate statuses, jobs, costs and history. All existing workflows (calendar, LinkedIn/Facebook posts, carousel, Drive, tracker) read and write that record. The user drives it from Codex Desktop by ID: "status BG-024", "approve BG-024", "reject BG-024 too generic", "revise BG-024 focus on Mittelstand".

## 2. Spec coverage
UC-01 (status by ID; check for existing results before repeating), UC-07 (approve/reject/revise by ID), UC-09 (authorization log), UC-15 (version model; regeneration comes in Phase 7), UC-17 (new tracker columns + conflict report), UC-20/21 (generic job state; carousel is the first job type wired in), BR-03, 04, 07, 09, 10, 11, NFR audit log / stable IDs / no duplicate paid operations.

## 3. Out of scope
New research/strategy (Phase 5); scripts/formulas (6); the review gate that holds Drive upload until asset approval (7; today's upload after generation stays); YouTube/podcast/Opus/publishing (8–9); LoRA/ComfyUI (track L); any real Google, Higgsfield, RunPod or OpenRouter call.

## 4. Decisions
D1 Storage: SQLite state/registry.db via stdlib sqlite3, git-ignored. schema_version table + numbered migrations. Before any schema migration or `registry migrate`, copy the DB to state/backups/registry-<timestamp>.db. All writes in transactions. No ORM.
D2 IDs: "BG-" + number zero-padded to 3 digits (BG-007; later BG-1000). Sequential, never reused, even after a reject or delete. Start number from config/registry.json ("next_id": 1). Legacy Content IDs (2026-W42-03) and package slugs are stored as aliases; every command accepts a BG ID or an alias, and a row number in calendar context.
D3 Item kinds: post, carousel, graphic, youtube, short, podcast, ad. Phase 4 creates only post and carousel. Items have platforms (list) and optional parent_id (a Short points to its YouTube item).
D4 Five independent statuses (BR-11); transitions enforced in one module:
- idea: proposed → approved | rejected | revision_requested; revision_requested → proposed; approved ↔ rejected allowed until generation starts.
- generation: not_started → queued → running → generated | partial | failed; failed/partial → queued (retry); generated → queued only through a new version.
- review: not_reviewed → approved | rejected | changes_requested; only while generation = generated.
- upload: not_uploaded → uploading → uploaded | failed; failed → uploading.
- publication: per platform in `publications`: not_ready → ready → published | failed (stored only; used in Phase 9).
An illegal transition raises a clear error naming the current status and the allowed next ones; nothing is written.
D5 Gate inference: approve/reject act on the open gate: the idea gate if idea = proposed; the review gate if generation = generated and review = not_reviewed. If neither is open, explain and do nothing. --gate idea|review overrides. The output always names the gate that changed.
D6 Versions: v1 is created with the item. revise <feedback> stores the feedback, creates v(n+1) as pending, and sets the affected gate to revision_requested/changes_requested. In Phase 4 every revise is a material change, so the new version needs approval again. approved_version is tracked separately from current_version. Old versions and files are never deleted.
D7 Jobs and idempotency: every external or paid operation (image/still/clip generation, Drive upload, tracker write) is a job row: type, provider, item, version, idempotency key = sha256(item, version, job type, normalized inputs), status, attempts, max_attempts, estimate, actual, authorization_id, result path, error, timestamps. Before running, look for a succeeded job with the same key: reuse its result and log job_reused. A running job older than its timeout is shown as stale and never re-run automatically.
D8 Authorizations: the existing "ok" after a dry run creates an authorization row: scope (item IDs + job types), max amount + unit (USD or credits, per provider), spent, status open/closed/exceeded. A job may start only if spent + its estimate <= max; otherwise stop and report. Never unlimited.
D9 Audit log: append-only events table: timestamp (UTC ISO), actor (user/system), command, item_id, version, event type, details JSON. Minimum events: command_run, item_created, status_changed, decision (with reason/feedback), version_created, authorization_created/exceeded/closed, job_started/succeeded/failed/reused, upload_succeeded/failed, tracker_synced, conflict_found, migration_run. Details pass through a redaction function (.env values, token/key-like strings, OAuth JSON). No update/delete API for events.
D10 Views, not sources: the calendar CSV and tracker Sheet become views of the registry. The calendar CSV gets a "BG ID" column; its Status column is derived from the idea/generation statuses. Store the CSV hash on each write; if the CSV was edited by hand since, stop, show the diff and ask. Never overwrite silently.
D11 Library boundary: all registry logic in a new package registry/ (db, ids, statuses, items, versions, jobs, auth, audit, migrate). The CLI and skills call only this package; no SQL elsewhere.

## 5. Data model (minimum)
items(id, kind, title, topic, platforms, parent_id, planned_date, source_refs JSON, package_path, current_version, approved_version, idea_status, generation_status, review_status, upload_status, created_at, updated_at, notes)
aliases(alias, item_id)
versions(item_id, version, created_at, reason, feedback, package_path, status pending|active|approved|superseded)
decisions(id, item_id, version, gate, action approve|reject|revise, text, actor, created_at)
jobs (as D7); authorizations (as D8)
publications(item_id, platform, status, url, published_at, updated_at)
events (as D9)

## 6. Commands (CLI → Codex phrase → effect)
| CLI | Codex phrase | Effect |
|---|---|---|
| ca item list [--status] [--kind] [--week] | "show items", "what's pending" | ID, kind, title, 5 statuses, version |
| ca item status BG-024 | "status BG-024" | statuses, versions, last decisions, jobs, cost spent, Drive/tracker state, next allowed actions |
| ca item approve BG-024 [--gate] | "approve BG-024", "approve BG-024 BG-025" | D5 |
| ca item reject BG-024 "<reason>" | "reject BG-024 too generic" | reason required |
| ca item revise BG-024 "<feedback>" | "revise BG-024 make it about …" | D6 |
| ca item history BG-024 | "history of BG-024" | events for the item |
| ca audit show [--since] [--type] | "show audit log" | events |
| ca jobs list [--unfinished/--failed] | "what failed", "unfinished jobs" | jobs |
| ca jobs resume [BG-024] | "resume unfinished jobs" | resumes registered job types (carousel in Phase 4); others listed as "not resumable yet" |
| ca auth list | "show authorizations" | spent/max |
| ca registry migrate [--dry-run] | (one-off, run by the user) | §9 |
| ca tracking conflicts | "tracker conflicts" | §8 |
| ca help commands | "what can I say" | short phrase list |
Existing phrases keep working ("approve all", "approve 1 3 5", "reject 2", "generate approved", "ok", "continue carousel …"); they now go through the registry and print BG IDs. Several IDs per approval are allowed. Reject/revise need text; if it's missing, the skill asks for it.

## 7. Codex Desktop integration (skills)
- New skill .agents/skills/manage-items/SKILL.md for every command in §6. Rules: map the user's words to one ca command; never approve, reject or authorize on its own, only after explicit user words; always show BG IDs and the gate that changed; show errors as they are.
- Update the make-calendar, make-content, make-carousel and show-content skills to show BG IDs and go through the registry.
- AGENTS.md: add the phrases to the Skills map + one line: "Every item has a BG ID; accept a BG ID, Content ID or row number."

## 8. Tracker (mock only in this phase)
New workflow-owned columns: BG ID, Version, Idea status, Generation status, Review status, Upload status, Publication status, URL, Last updated. Key = BG ID (Content ID kept as a column). Manager-owned columns unchanged and never written. Conflict report: compare the Sheet to the registry; list hand-edited workflow-owned cells, rows missing on either side, duplicate IDs; write nothing for those rows until the user decides. Mock storage only; the real Sheets test is in Phase 10.

## 9. Migration
ca registry migrate --dry-run lists what would be created from calendar CSVs, packages in outputs/content/, carousel.json files, drive_state.json and mock tracker rows. Without --dry-run: back up (D1), create items oldest first, assign BG IDs, store Content IDs/slugs as aliases, map statuses (Proposed→idea proposed; Approved→idea approved; Rejected→idea rejected; Generated→idea approved + generation generated; uploaded packages→upload uploaded), record v1, log migration_run. Idempotent: a second run creates nothing new.

## 10. Acceptance criteria (offline, mock storage, no paid calls)
1. Making a calendar gives each row a BG ID; "status BG-00x" shows the five statuses.
2. approve/reject/revise by ID work, store reasons/feedback, and refuse illegal moves with a clear message.
3. revise creates v2; the item needs approval again; v1 remains.
4. "generate approved" on mock providers creates one authorization + jobs; running it again reuses succeeded jobs (no new calls, job_reused logged).
5. A job whose estimate would exceed the authorization is not started.
6. A carousel interrupted midway appears in ca jobs list --unfinished and is finished by ca jobs resume.
7. ca audit show lists every command, decision, authorization, job and upload; no secret values appear (test with a fake key in the env).
8. A hand-edited calendar CSV stops the write and shows a diff; a hand-edited tracker cell produces a conflict report and is not overwritten.
9. Migration on existing data is idempotent.
10. ruff + strict mypy clean; offline pytest unit tests for status transitions, ID allocation, idempotency, authorization limits, redaction and the migration mapping.

## 11. Build steps (one Claude Code prompt each)
1. Registry core ✔
2a. §13 decisions, status fixes, doc cleanup.
2. Item commands (list/status/approve/reject/revise/resubmit/history) + audit show + manage-items skill + AGENTS.md.
3. Dry runs + authorizations + jobs + idempotency + `ca jobs check`; wire in calendar generate, content build, image generation, carousel and Drive upload.
4. Calendar as a view (BG ID column, new statuses, hand-edit guard, row numbers per week, --replace) + the migration command with fixtures.
5. Tracker columns + last-written values + conflict report (mock).
6. Remaining skill updates, ca help commands, docs, mock end-to-end run of §10, PROGRESS.md.

## 12. Open questions
- Q1 (client): Is there already a BG numbering in use, and what number should we start from?
- Q2 (client): Content language DE or EN (needed by Phase 5, not 4).

## 13. Conflicts with the current code
Found in the read-only audit on 13 Oct 2026 (branch phase-3-carousel at 5bc0bd5). Each item: what the code does today, then the recommendation (→).

1. **One item = one kind vs multi-deliverable packages.** A package.json holds a list of deliverables (e.g. facebook_post + instagram_carousel + reel_short); make-content "make 2 and 5" makes such packages. → One item per (package, deliverable); items share `package_path`; alias `<slug>#<deliverable>`, the bare slug resolves only when it is unambiguous.
2. **"Phase 4 creates only post and carousel" (D3).** make-content already builds facebook_ad, reel_short, ugc_ad and podcast_clip, and existing packages contain them. → Map every deliverable to a kind in config/deliverables.json (ads → ad, reel_short/podcast_clip → short) and register them all; only their job wiring waits.
3. **Items outside the calendar.** `ca content start` ("make a post about X") creates packages with no calendar row and no Content ID; §6 and §9 cover only calendar rows and migration. → `ca content start` creates the item(s) and prints the BG ID (step 2 or 3).
4. **"ok" creates an authorization (D8).** "ok" exists only in chat; no `ca` command receives it. The paid runs are `ca content build` and `ca calendar generate --build`, not tied to a dry run, and carousel.json already stores its own `approvedMaxCredits`. → The build command (run only after "ok") creates the authorization from the estimate saved by the preceding dry run, refuses if there is none or the inputs changed, and carousel.json's max becomes a copy of it.
5. **Plugin jobs run in Codex, not in `ca` (D7).** Higgsfield and HeyGen calls are made by the make-carousel and make-video skills; `ca` only writes request files (carousel_plugin.write_still_requests/_write_clip_requests, video_job._run_scene) and records results (`ca carousel record`, `ca job complete`/`fail`). The registry cannot see or block the plugin call. → Open the job row when the request file is written, close it on record/complete, and make the skills check the job's status with a `ca` command before every plugin call.
6. **Idempotency vs deliberate redos (D7).** The person check's redo (`ca job review --fail`, then regenerate after a cost "ok") repeats the same inputs on purpose, and the carousel's one retry per request does the same; a key of (item, version, type, inputs) would reuse the rejected result. → Add the attempt number or the redo's decision ID to the key; only an identical, unrequested rerun is reused.
7. **Existing state duplicates the registry.** Job state, costs and uploads already live in carousel.json (stage, attempts, creditsUsed), job details.json (steps, creditsUsed, actualCostUsd) and package.json (item status, costUsd, uploads). → In Phase 4 the registry is the source for statuses, authorizations and jobs, written at the same points; those files keep per-file pipeline detail, and a mismatch is reported, not silently fixed.
8. **Calendar CSV header is fixed.** calendar.read_calendar refuses any header other than the 9 current columns; the Drive copy is read-only. Adding "BG ID" breaks every existing CSV. → Read both headers; `ca registry migrate` rewrites old CSVs with the new column after a backup.
9. **Calendar Status values (D10).** STATUSES are Proposed/Approved/Rejected/Generated and calendar check rejects any other value; revision_requested and generation failed/partial have no CSV value. → Add "Revision requested" and "Failed" to STATUSES; keep the derivation table in content/calendar.py.
10. **When reject is still allowed (D4).** Today an Approved row may become Rejected at any point before Generated, even after stage 1 or a failed build. → "Generation starts" = generation queued or later; stage 1 (free) does not count, and reject stays allowed after a failed generation.
11. **Content IDs and --replace (D2).** Content IDs are `<week>-<row 2 digits>`, made in calendar.new_calendar and as a fallback in calendar.generate_rows; `ca calendar new --replace` rebuilds a week and reuses the same IDs for new topics, so aliases would collide. → On --replace, mark the old items rejected ("replaced") and move the alias to the new item; history keeps both.
12. **Row numbers.** "approve 1 3 5" acts on `--week` (default next week); rows are not unique across weeks. → A row number resolves only within the calendar week the command names (default next, as today); otherwise ask.
13. **Drive folders and tracker key (§8).** Drive folders are `<Platform>/<Content ID>/` (package ID when there is none), keyed that way in drive_state.json `contentFolders`; the tracker upserts by Content ID (tracking.plan_upsert). Existing Sheet rows have no BG ID. → Keep Drive folder names unchanged in Phase 4 (new folders are Phase 7); match tracker rows by BG ID, then fall back to the Content ID column to adopt an existing row and fill its BG ID, never adding a duplicate.
14. **Tracker column names (§8).** The Sheet already has manager-owned "Approval status" (Pending/Approved/Rejected), "Publishing status" (Pending/Posted) and "Publication date", and a workflow "Image/video link". The new "Review status", "Publication status" and "URL" sit next to near-identical names, and `ca drive setup` formats a Sheet only once. → Ask the client: rename the new columns (e.g. "Workflow review") or add "Publication status"/"URL" only in Phase 9; append new columns without re-formatting an existing Sheet.
15. **Hand-edit detection in the tracker (§8).** tracking.plan_upsert overwrites any workflow cell that differs and keeps no record of what it last wrote, so a hand edit cannot be told from a stale value. Rows exist only for finished, fully uploaded packages. → Store the last-written value (or hash) per item and column in the registry; only items with upload = uploaded count as "missing in the Sheet".
16. **Upload status vs per-file records (D4).** Uploads are tracked per file in package.json (`uploaded` | `upload_failed`, provider mock or drive; a mock upload never counts as a Drive one); there is no "uploading" state. → Derive the item's upload status from its files (all uploaded → uploaded, any failed → failed) and store the provider, so a mock upload is never shown as a Drive upload.
17. **state/ and the ID counter (D1, D2).** There is no state/ folder or Settings field for it, and .gitignore does not cover it. config/registry.json is tracked, so it cannot hold the live counter. → Add `state_dir` to Settings and `/state/` to .gitignore in step 1; registry.json only seeds the counter when the DB is created, and the DB keeps it so no ID is reused.
18. **Migration inputs (§9).** This machine has no calendar CSVs, carousel.json files, drive_state.json or mock tracker; outputs/content/ holds 4 packages, none with a Content ID, one an older v1 package.json without `deliverables`, and statuses are free text ("draft — video failed"). → Build the migration against test fixtures for every source, handle packages without a Content ID (slug alias only) and v1 files, and map unknown package statuses to generation partial with a note.
19. **Revise has no way back to approval (D4–D6).** revise sets the gate to revision_requested/changes_requested, but approve acts only on proposed/not_reviewed and nothing moves revision_requested → proposed, while §10.3 says the item "needs approval again". → Let `ca item revise` create v(n+1) and reopen the gate (proposed / not_reviewed), recording revision_requested in history; approve then approves v(n+1).
20. **What a Phase 4 version holds (D6).** Nothing regenerates content before Phase 7, so v2 after an idea-gate revise has the same topic and package. → In Phase 4, v(n+1) shares v1's package_path and stores the feedback (plus a new topic if the user gave one); `ca item status` says "regeneration: Phase 7".
21. **Test and workflow rules.** CLAUDE.md says "no tests until Phase 4" and points to docs/PRD.md (v2); AGENTS.md says "No new tests" and commits as `M<n>.T<n>`. pytest 9.1.1 is installed and configured, and 11 test files (61 tests) exist, but v2 has not run them (PROGRESS.md: "no tests run"). → In step 1, point CLAUDE.md/AGENTS.md at docs/ROADMAP-v3.md and docs/phases/, allow tests, and run the existing suite once as a baseline (fix or mark stale tests).

## 14. Decisions on §13 (13 Oct 2026)
D-1 One item per (package, deliverable); items of one package share package_path.
D-2 Every deliverable maps to a kind via a "kind" field in config/deliverables.json: LinkedIn/Facebook post → post, ad → ad, reel and podcast clip → short, carousel → carousel, single graphic → graphic. All are registered.
D-3 `ca content start` creates the item(s) and prints the BG IDs.
D-4 Every dry run is saved as state/dryruns/<dryrun_id>.json (scope, estimate per provider/unit, max). A build only runs with `--authorize <dryrun_id>`, which the skill passes only after the user says "ok". That creates one authorization per provider/unit, grouped by dryrun_id. The carousel max copies the authorization max; carousel.json no longer sets its own.
D-5 Plugin work (Higgsfield/HeyGen): a job opens (queued) when ca writes the request file and closes on `ca carousel record` / `ca job complete|fail`. Before each plugin call the skill runs `ca jobs check <job_id>` → go | skip (already succeeded, reuse) | stop (over budget, stale, or cancelled).
D-6 Idempotency key = sha256(item, version, job type, normalized inputs, redo_n). Normal reruns use redo_n = 0 and are reused. Deliberate redos (person-check redo, carousel retry) increment redo_n and must fit the authorization.
D-7 The registry owns statuses, jobs, authorizations and decisions. package.json, carousel.json and details.json keep pipeline detail. `ca item status` reports mismatches between them; it never auto-fixes.
D-8 read_calendar accepts the old 9-column and the new header. `ca registry migrate` rewrites old CSVs to the new header after a backup.
D-9 CSV Status values add "Revision requested" and "Failed".
D-10 Idea gate: reject (and approve back from rejected) allowed while generation ∈ {not_started, failed, partial}. Once generated, decisions move to the review gate.
D-11 `calendar new --replace`: old items → idea rejected with reason "replaced"; the Content ID alias moves to the new item; history stays on the old item.
D-12 Row numbers resolve only within the named week (default: next week). Every output echoes the BG IDs it acted on.
D-13 Drive folder name = Content ID if the item has one, else the BG ID. Tracker rows match by BG ID, then Content ID, and the BG ID is filled in.
D-14 New tracker columns in Phase 4: BG ID, Version, Idea status, Generation status, Review status, Upload status, Last updated. Publication status and URL wait for Phase 9. Final column names: client to confirm.
D-15 Store the last-written value per tracker cell; a cell that differs from it was edited by hand and goes to the conflict report.
D-16 Item upload status is derived from its files: uploading while any file is in progress, failed if any failed, uploaded when all succeeded. The provider is stored; mock uploads show as "uploaded (mock)" and never count as real uploads in reports.
D-17 Done in Step 1 (state/, .gitignore, config seeds the counter only).
D-18 Build and test the migration against fixtures (old v1 package, v2 package, calendar CSV, carousel.json, drive_state.json, mock tracker) as well as the 4 local packages.
D-19 Revise:
 - Idea gate: `revise BG-x "<feedback>" [--title "<new topic>"]` creates v(n+1). With --title (the Codex skill rewrites the topic from the feedback and shows it), idea goes revision_requested → proposed on the new version in one call. Without --title it stays revision_requested until `ca item resubmit BG-x --title "..."`.
 - Review gate: allowed when review ∈ {not_reviewed, approved}. Sets review → changes_requested and creates v(n+1) pending. When the new version starts generating (Phase 7), generation generated → queued and review changes_requested → not_reviewed. Review rejected is final (revise instead of reject to keep an item alive).
D-20 Until Phase 7, v(n+1) shares v1's package_path and stores the feedback.
D-21 CLAUDE.md/AGENTS.md updated in Step 2a; the full suite is the baseline from now on.
D-22 An idea-gate revise is allowed when idea ∈ {proposed, approved} and generation ∈ {not_started, failed, partial}.
 - approved → revision_requested. The item can't generate until it is approved again.
 - A second revise while the item is revision_requested is refused, with a hint to use `resubmit`.
 - Starting a new version requires an approved idea (keep).
D-23 AGENTS.md working rules: replace "No new tests" with "ruff + mypy --strict + offline pytest must pass before every commit"; the commit format becomes `phase <N> step <M>: …`. CLAUDE.md: the Nano Banana note now says "decision in Phase 10 (roadmap v3)".

## Decisions taken during build
IDs B4-n; each is also listed under "Needs review" in docs/autorun/LOG.md.
- B4-1 (Step 2) Generation can start (→ queued, also a retry or a new version) only while the idea is approved. D-22 says so after a revise; applying it to every start keeps one rule. Why: no generation without an approval (BR-04).
- B4-2 (Step 2) Schema migration 2 adds items.deliverable (e.g. linkedin_post), needed for D-1 (one item per package and deliverable) and for the per-part mismatch check in `ca item status`.
- B4-3 (Step 2) An approve on either gate sets approved_version = the current version (D6); a reject leaves approved_version as it was.
- B4-4 (Step 2) Gate inference per action: approve also reopens a rejected idea and reject also closes an approved idea while generation is not_started/failed/partial (D-10); the idea gate is tried first (D5).
- B4-5 (Step 2) Reject reasons and revise feedback are taken as all remaining words, so `ca item reject BG-7 too generic` works without quotes. Exit codes: 2 = usage (missing text, bad option or week), 1 = refused or not found. With several IDs each failure is listed and the exit code is 1; with one ID only its error line is printed.
- B4-6 (Step 2) A row number resolves through the Content ID alias `<week>-<row:02>` (the format calendar.new_calendar writes), so no CSV is read; an unregistered row is an error.
- B4-7 (Step 2) Every `ca item` and `ca audit` command logs command_run (actor user), read-only ones too (§5 Step 2.4 says every command).
- B4-8 (Step 2) Settings STATE_DIR (default `state`) and REGISTRY_FILE (default `config/registry.json`); the database is `<STATE_DIR>/registry.db`.
- B4-9 (Step 2) `ca item status` reads the tracker only from the mock file (STORAGE_PROVIDER=mock); with the Google Sheet it says "not checked here (ca tracking show)", so the command stays offline.
