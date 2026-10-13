# Autorun log — Phases 4–6

Plan: `docs/autorun/AUTORUN-PHASES-4-6.md`. One entry per step (§3.4). A step's commit hash is
filled in by the next step (an entry is committed together with its own step).

## 2026-10-13 15:49 — Phase 4 Step 2.0: D-22/D-23 — DONE
Commit: 1e71ce2   Tests: 240/240
Built: PRD §14 gains D-22 (idea-gate revise from approved; no generation until approved again) and D-23.
Built: AGENTS.md working rules: checks before every commit, `phase <N> step <M>:` commits. CLAUDE.md: Nano Banana decision in Phase 10.
Built: autorun plan moved from the repo root to docs/autorun/ (the plan names that path); this log started.
Decisions: none (D-22 code and its tests follow in Step 2, which lists the D-22 test cases)
Needs review: none

## 2026-10-13 16:08 — Phase 4 Step 2: item commands + manage-items skill — DONE
Commit: 5f7ccee   Tests: 258/258
Built: `ca item list|status|approve|reject|revise|resubmit|history` and `ca audit show` (cli/items.py, thin; --json on list/status/history/audit).
Built: registry gates.py (gate inference per action), approvals.py (approve/reject + decisions), report.py (status report, D-7 mismatches, next actions), list_items, resolve_row (D-12).
Built: D-22 in the status table (approved → revision_requested; generation starts only while the idea is approved); schema migration 2 (items.deliverable).
Built: skill .agents/skills/manage-items/SKILL.md; AGENTS.md phrases + BG ID line; 18 new CLI tests (gate inference, missing reason, multi-ID, alias/row, revise, D-22).
Decisions: B4-1 … B4-9 (PRD "Decisions taken during build")
Needs review: B4-1 generation needs an approved idea everywhere (Step 3 must give make-content items an approved idea); B4-5 exit codes 1/2; B4-6 row numbers via Content ID alias; B4-9 status reads only the mock tracker.

## 2026-10-13 19:03 — Phase 4 Step 3: dry runs, authorizations, jobs, idempotency + wiring — DONE
Commit: pending   Tests: 276/276
Built: registry dryruns.py (state/dryruns/DR-….json, expiry, used, scope/cost checks), auth.py (one per provider/unit per dry run, legacy), jobs.py (D-6 key with redo_n, reuse, budget stop, stale, check), progress.py (generation/upload derivation, D-16), runtime.py (scope used by the pipelines), link.py (packages and calendar rows → items); schema migration 3; config/jobs.json; D-2 kinds in config/deliverables.json.
Built: wiring — `ca image`, `ca content build`, `ca calendar generate --build`, `ca video` take `--authorize <dryrun_id>`; run_image_job is a registry job; carousel requests carry jobId (record closes, checks reject + redo, max from the authorization); video agent steps carry jobId (`ca job complete|fail` close); `ca job review --fail` rejects the image job; Drive uploads and tracker writes are jobs; content start/set register items (D-3).
Built: `ca jobs list|check|resume|cancel`, `ca auth list` (cli/jobs.py); skills make-calendar, make-content, make-carousel, make-video, manage-items + AGENTS.md updated (dry-run ID, `--authorize` after "ok", `ca jobs check` before every plugin call).
Built: 18 new tests (reuse/redo, budget stop, unauthorized paid job, stale, check, derivation, dry runs, per-provider authorizations, image job reuse, `ca image` authorize, carousel interrupted + resumed, legacy carousel, agent step, Drive upload jobs).
Decisions: B4-10 … B4-24 (PRD "Decisions taken during build")
Needs review: B4-10 make-content request approves the idea; B4-11 legacy packages approved at build; B4-14 `ca video --authorize` added; B4-15 video credit estimates (client to confirm); B4-16 estimate charged when no actual; B4-22 generated from the pipeline, not "all jobs succeeded"; B4-23 no auto-close of authorizations.
