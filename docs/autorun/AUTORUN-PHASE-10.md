# AUTORUN LITE — Phase 10: reporting, verification, release
Save as `docs/autorun/AUTORUN-PHASE-10.md`. This file is the spec. Don't write a PRD.

## 0. Run rules (same as Phases 7–9)
- Read only this file + the last LOG.md entry. Use Grep for lookups; no subagents. Do steps in order with no pauses. **Resume:** continue at the first step not DONE in LOG.md.
- **Per step:**
  1. Implement the minimum that meets the bullets.
  2. Add 1 basic test per new command.
  3. Run `uv run ruff check <changed> && uv run pytest <new tests> -q`.
  4. Commit `phase 10 step <M>: …` only if the exit code is 0.
- After every step, add a 2-line LOG entry and print `P10S<M> done <hash>` in chat and nothing else.
- **Full check once at the end:** `uv run ruff check . && uv run mypy --strict <usual targets> && uv run pytest -q`.
- **Hard rules:**
  - no paid or real external calls
  - no secrets
  - never push
  - no LoRA/ComfyUI work
  - skills never act for the user
  - existing phrases keep working
  - pick the simplest reversible option and note it in LOG under needs-review
- Branch: `phase-10-release` from `phase-9-distribution`.
- **Stop only if:** a paid or external call, a secret or a manual user action is needed; checks still fail after 2 tries; or data would be deleted.

## 1. Step 1: monthly target report (UC-19) + resume all (UC-21)
- **`ca report month [YYYY-MM] [--json]`** writes `outputs/reports/<YYYY-MM>.md`. It counts only recorded final states from the registry:
  - YouTube finals that are review-approved, against the target 8
  - clips selected and approved, against 32–40
  - graphics (posts, carousels, ads) review-approved, against 30–60
  - podcast finals, against the scheduled number
  - published per platform, with URLs
  - % of published items with an approved review, against the target 100%
  - Mock uploads and mock results are listed separately and never counted. Targets come from config.
- **`ca jobs resume --all`** resumes every resumable type:
  - carousel
  - queued image jobs, within an open authorization
  - stale or failed uploads, re-queued
  - outstanding plugin requests, listed for the skill
  - video/HeyGen steps
  - Anything else is listed as "needs manual action: <what>".
- Skill phrases: "monthly report", "report for <month>", "resume everything". Add them to AGENTS.md and help.

## 2. Step 2: integration verification (spec §7)
- If the client spec's §7 list exists in the repo, use it. Otherwise use these 12 and note "list to confirm against spec §7":
  1. Codex skills/CLI
  2. Gmail plugin
  3. web research fetch
  4. Higgsfield plugin
  5. HeyGen plugin
  6. ComfyUI/RunPod
  7. OpenRouter (Nano Banana fallback)
  8. Google Drive (API or plugin)
  9. tracker Sheet
  10. Opus Pro (manual)
  11. FFmpeg media
  12. publishing (manual URL)
- **`ca verify list`** shows each integration with its success condition, failure path and last result.
- **`ca verify run <name>`** (offline) checks that config is present and the adapter loads, then runs the failure path with a fake.
- **`ca verify record <name> --live pass|fail "<note>"`** is what the user runs after a manual live test.
- Results go in a registry `verifications` table. An integration counts as **operational only with a recorded live pass**, and `ca verify list` says so.
- Write `docs/VERIFICATION.md`: per integration, the manual live test steps (one short block each), using the six manual tests from REPORT-PHASES-7-9 plus Gmail, web fetch, FFmpeg, Codex, and ComfyUI (marked "blocked: LoRA track").
- **Nano Banana:** keep it as a configured fallback, off by default, used only through the Phase 7 "offered fallback" dry-run line. Note it as a client decision.
- Skill phrases: "verification status", "verify <integration>". Add them to AGENTS.md and help.

## 3. Step 3: user guide + release
- **`docs/USER-GUIDE.md`** (max 2 pages):
  - first-time setup (uv sync, .env keys by name only, Drive route choice, Codex plugins to connect)
  - then every Codex phrase, grouped by workflow in this order: research → calendar → approve → generate → review → upload → production → clips → distribute → reports
  - one line each
- Run the full check (§0).
- `git switch main && git merge --ff-only phase-10-release`. If a fast-forward isn't possible, stop and report. Never push.
- Write `docs/autorun/REPORT-PHASE-10.md` (max 20 lines): commits, test total, needs-review, client questions, and the verification status table (all "offline ok / live pending").
- Stop.
