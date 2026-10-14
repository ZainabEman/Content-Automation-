# Phase 5 — end-to-end check

Offline script: `uv run python scripts/e2e_phase5.py` (temp folder, mock scraper/storage, link
fetches through httpx's MockTransport; no network, no paid call). Result on 2026-10-14:

| # | Acceptance criterion (PRD §7) | Result |
|---|---|---|
| 1 | Newsletter list → ideas with sources, purposes, original URLs, run counts | PASS |
| 2 | A duplicate from another source is merged; sources kept | PASS |
| 3 | Claims: 1 secondary → unverified, 2 publishers → verified, old → outdated; no `--status` | PASS |
| 4 | A manual topic keeps its text and goes through dedupe and scoring | PASS |
| 5 | An off-strategy idea is flagged, not dropped | PASS |
| 6 | `calendar plan --month` meets targets, keeps pillar balance, blocks shorts | PASS |
| 7 | Planned rows are child items (parent_id) with inherited approval in the log | PASS |
| 8 | `generate approved` skips youtube/podcast/short ("not producible until Phase 8/9") | PASS |
| 9 | German candidate sources present but disabled | PASS |
| 10 | ruff + mypy --strict (152 files) + pytest (311 passed) | PASS |

## Codex phrase test (manual, free)

Type these in Codex, in order; each should run the command shown and stop where it says.

1. "find new ideas" → Gmail (read-only) list, then `ca research run`; a counts line. Stops at "Approve, reject or revise which ideas?".
2. "research this link https://…" → `ca research fetch <url>`; prints `SRC-####` or why it failed (never a made-up summary).
3. "add topic why German clinics trust AI triage" → `ca ideas add "…"`; the text is kept as typed.
4. "show backlog" / "show ideas" → `ca ideas list`.
5. "review ideas" → `ca ideas review`; stops for the user's decision.
6. "show claims for BG-001" → `ca claims list BG-001` (statuses decided by `ca`).
7. "merge BG-002 into BG-001" → `ca ideas merge BG-002 BG-001`.
8. "approve BG-001 BG-003" → `ca item approve …` (manage-items; only after these words).
9. "plan next week" → `ca calendar plan --week next`: rows Approved by inheritance, shorts 2 days after videos, targets and pillar balance lines.
10. "plan next month" then "show month" → `ca calendar plan --month next`, `ca calendar show --month next`.
11. "generate approved" → YouTube/podcast/short rows skipped with "not producible until Phase 8/9"; posts go through stage 1 and one dry run; stops for "ok".
12. "make calendar next week" → the old weekly flow (`ca calendar new`) still works.
