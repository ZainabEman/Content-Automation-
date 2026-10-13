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
Commit: pending   Tests: 258/258
Built: `ca item list|status|approve|reject|revise|resubmit|history` and `ca audit show` (cli/items.py, thin; --json on list/status/history/audit).
Built: registry gates.py (gate inference per action), approvals.py (approve/reject + decisions), report.py (status report, D-7 mismatches, next actions), list_items, resolve_row (D-12).
Built: D-22 in the status table (approved → revision_requested; generation starts only while the idea is approved); schema migration 2 (items.deliverable).
Built: skill .agents/skills/manage-items/SKILL.md; AGENTS.md phrases + BG ID line; 18 new CLI tests (gate inference, missing reason, multi-ID, alias/row, revise, D-22).
Decisions: B4-1 … B4-9 (PRD "Decisions taken during build")
Needs review: B4-1 generation needs an approved idea everywhere (Step 3 must give make-content items an approved idea); B4-5 exit codes 1/2; B4-6 row numbers via Content ID alias; B4-9 status reads only the mock tracker.
