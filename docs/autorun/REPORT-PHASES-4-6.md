# Autorun report — Phases 4–6 (2026-10-14)

Nothing was pushed or merged, and no paid or external service was called. Branches: `phase-4-items` → `phase-5-research` → `phase-6-scripts` (each one starts from the last commit of the one before).

| Phase | What was built | Commits | Checks |
|---|---|---|---|
| 4 Items & approvals | Registry (BG IDs, statuses, versions, decisions, audit log), item commands and the manage-items skill, dry runs with authorizations, idempotent jobs, the calendar as a registry view with migration, mock tracker columns, help commands | 1e71ce2 5f7ccee 9e45ffd e277f7a 15215fe 29c8926 | 294 tests, e2e 9/9 |
| 5 Research & backlog | Ideas with sources and claims (`ca` decides each claim's status), newsletter senders, `ca research fetch/run`, German candidate sources (disabled), dedupe, scoring, review queue, `ca ideas`/`ca claims`, calendar v2 (`ca calendar plan --week/--month`, inherited approval, shorts, month view), research-ideas skill | fcbbe3b 85fe0fe 4f8de32 d2983bd e0fa281 e07ced5 ff9d4d5 | 311 tests, e2e 9/9 |
| 6 Scripts & briefs | `config/formulas.json` (5 formulas), artifacts table, `ca script template/save/check/show` (mechanical checks, BR-07 number rule), `ca brief …` (YouTube, podcast, social), social copy fills brief.json, write-script skill | 935521a 06aaeb2 7ec406f 3712344 a6c5606 e3b52b1 e030af1 4cd19b1 | 322 tests, e2e 7/7 |

Each phase ends with ruff, mypy --strict (src, tests, scripts) and the full offline pytest suite passing.

**Decisions** (full lists in the PRDs' "Conflicts" sections: PHASE-4 §13, C5-1…C5-21, C6-1…C6-5):
- Calendar v2 is an optional `plan` block in calendar.json. YouTube, podcast and shorts are plan-only, and `generate` skips them with "not producible until Phase 8/9".
- One idea fills one row per platform. A Short and a TikTok are planned 2 days after each video.
- Scripts are saved in `<package>/scripts/<BG-x>/v<n>/`, or in `outputs/…/items/<BG-x>/scripts/v<n>/` when the item has no package. Only the current version can be written. A save that fails the check writes no file and is logged `artifact_invalid`.
- Claims can come from the item or from any item above it, up to its idea. Any digit counts as a number. A disputed claim must name a source of each side in the section notes.

**Needs review:**
- B4-44: rebuild reuse depends on the design picks.
- "plan next week" now runs `ca calendar plan` instead of `ca calendar new`. "make calendar next week" still runs the old flow.
- A topic you add again is merged into the existing idea as a second note.
- The caption is mapped only when the copy has this shape: hook line, 3–5 takeaways, a question.
- Ad primary text stays in the script.
- A production brief can be saved before its script (you get a warning).

**Client questions:**
- Are the strategy pillars, keywords and target shares right? Are the score weights 40/20/15/15/10 right?
- Are the newsletter sender purposes right? The German source feed URLs are not verified yet.
- Content language: German or English (`config/content.json`)?
- Calendar targets: 10 posts, 2 YouTube videos and 1 carousel a week, a podcast every second week. Should the single Instagram graphic be turned on?
- Are the formula section word ranges right? Is 10–20 minutes the right podcast length? Are the tracker column names right?

**Manual Codex test scripts:** [PHASE-4-E2E.md](../phases/PHASE-4-E2E.md), [PHASE-5-E2E.md](../phases/PHASE-5-E2E.md) and [PHASE-6-E2E.md](../phases/PHASE-6-E2E.md), each in its "Codex phrase test" section. Offline checks: `uv run python scripts/e2e_phase4.py`, then `e2e_phase5.py`, then `e2e_phase6.py`.
