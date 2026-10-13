# Phase 4 — end-to-end results and manual Codex test (13 Oct 2026)

Branch `phase-4-items`. Script: `scripts/e2e_phase4.py` (offline, temp folder, mock providers; the mock
image provider is counted as paid there, so the dry run → "ok" → `--authorize` path runs as with a
real provider). Pytest wrapper: `tests/test_e2e_phase4.py`. Run: `uv run python scripts/e2e_phase4.py`.

## Acceptance criteria (PRD §10)

| # | Criterion | Result | How it was checked |
|---|---|---|---|
| 1 | Making a calendar gives each row a BG ID; "status BG-00x" shows the five statuses | PASS | `ca calendar new` (3 topics) → BG-001..BG-003 in the CSV; `ca item status BG-001` lists idea, generation, review, upload, publication |
| 2 | approve/reject/revise by ID work, store reasons/feedback, refuse illegal moves clearly | PASS | calendar approve by row (echoes the BG ID); `ca item reject BG-002 too generic` (reason stored); reject without a reason → exit 2; approve on a closed gate → one line, exit 1 |
| 3 | revise creates v2; the item needs approval again; v1 remains | PASS | `ca item revise BG-003 … --title …` → v1 active, v2 pending, idea proposed; approve → approved (v2) |
| 4 | "generate approved" on mock providers creates one authorization + jobs; running again reuses succeeded jobs | PASS | stage 1 for 2 rows, briefs, combined dry run with `DR-…`; `--build` without `--authorize` refused; with it: 1 authorization, 2 image jobs, both rows Generated, uploads + tracker rows; a crash-like rebuild of the last package → `job_reused`, no new image folder |
| 5 | A job whose estimate would exceed the authorization is not started | PASS | a job over the remaining budget: `ca jobs check` → stop, job stays queued, `authorization_exceeded` logged; the user cancels it |
| 6 | An interrupted carousel appears in `ca jobs list --unfinished` and is finished by `ca jobs resume` | PASS | 3 of 7 stills recorded → 4 unfinished still jobs listed; `ca jobs resume BG-x` names still_04..07; the rest checked (`go`) and recorded → nothing unfinished |
| 7 | `ca audit show` lists every command, decision, authorization, job and upload; no secret appears | PASS | command_run, decision, authorization_created, job_succeeded, upload_succeeded, status_changed, version_created, tracker_synced present; a fake key in the environment and in a command line is not in the output or the database |
| 8 | A hand-edited calendar CSV stops the write with a diff; a hand-edited tracker cell gives a conflict and is not overwritten | PASS | edited Topic → `calendar approve` exit 2 with the diff and both options, `--discard-edits` restores; edited tracker cell → sync says "not written (conflicts)", `ca tracking conflicts` shows it, the edit stays |
| 9 | Migration on existing data is idempotent | PASS | fixtures (old CSV, v1 + v2 packages, carousel.json, drive_state, mock tracker): 7 created, then 0 created / 7 skipped |
| 10 | ruff + strict mypy clean; offline pytest | PASS | `uv run ruff check .`, `uv run mypy --strict src tests scripts`, `uv run pytest`: 294 passed |

Notes: job reuse needs the same inputs. A part's design picks (scene, pose …) are chosen when it is
planned and rotate away from the last packages, so a rebuild after other packages were made can pick
differently and is then a new job (logged, inside the authorization). The e2e simulates the crash on
the last package built. Needs review: keep the picks before the provider call.

## Manual test in Codex Desktop

Before you start: in `.env` use `IMAGE_PROVIDER=mock` and `STORAGE_PROVIDER=mock` for a free run (with
`openrouter` the "ok" step spends money). Run `uv run ca registry migrate --dry-run`, then
`uv run ca registry migrate` once, so older packages have BG IDs. Type these phrases in order:

| # | You type | Expected result |
|---|---|---|
| 1 | what can I say | The phrase list grouped by skill (`ca help commands`). |
| 2 | make calendar next week | A proposed week; every row has a BG ID (e.g. BG-011…BG-015); "Approve all, approve some or reject rows?" |
| 3 | approve BG-011 BG-012 | Two lines `BG-011 idea: proposed → approved (v1)` and `BG-012 …`. |
| 4 | reject BG-013 too generic | `BG-013 idea: proposed → rejected (v1) — reason: "too generic"`. |
| 5 | reject BG-014 | Codex asks for the reason (nothing changes until you give one). |
| 6 | revise BG-014 focus on dental practices in the Mittelstand | Codex shows a new topic, then `BG-014 idea: revise → proposed; v2 created (pending)`. |
| 7 | status BG-014 | Five statuses, versions v1 and v2 with your feedback, the last decisions, next allowed actions. |
| 8 | approve BG-014 | `BG-014 idea: proposed → approved (v2)`. |
| 9 | generate approved | Stage 1 per approved row (BG IDs shown), briefs written by Codex, then one combined dry run with the cost per row and the total; Codex stops for "ok". With a paid provider it ends with `Dry run ID: DR-…`; with the free mock provider there is nothing to authorize. |
| 10 | ok | Paid provider: `--build --authorize DR-…` ("Authorized: …"); mock: `--build`. Each row is built and Generated, Drive (mock) uploads, tracker rows. |
| 11 | show authorizations | Paid provider: spent of max for that dry run; mock: "No authorizations." |
| 12 | unfinished jobs | "No jobs match." (or a carousel waiting for the plugin). |
| 13 | tracker conflicts | "no conflicts" (edit a workflow cell in the mock tracker CSV and ask again: the row is listed as a hand edit). |
| 14 | history of BG-011 | Every event of BG-011 in order. |
| 15 | show audit log | The newest events: commands, decisions, authorization, jobs, uploads. |
