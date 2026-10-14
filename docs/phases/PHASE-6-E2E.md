# Phase 6 — end-to-end check

Offline script: `uv run python scripts/e2e_phase6.py` (temp folder, registry seeded with an idea,
sourced claims and five items; criterion 7 runs `scripts/e2e_phase4.py` on mock providers; no
network, no paid call). Result on 2026-10-14:

| # | Acceptance criterion (PRD §7) | Result |
|---|---|---|
| 1 | Templates exist for every formula and include the claims and the feedback | PASS |
| 2 | A valid YouTube script saves as v1 with md rendered and a duration estimate | PASS |
| 3 | Missing section, number without verified source, outdated claim, unacknowledged unverified claim each fail clearly | PASS |
| 4 | A revise then a new save creates v2; v1 is unchanged | PASS |
| 5 | Podcast and YouTube briefs validate and render | PASS |
| 6 | LinkedIn copy outside 120–250 words fails | PASS |
| 7 | Existing post and carousel builds still work on mock; old packages still render (e2e_phase4 9/9) | PASS |
| 8 | ruff + mypy --strict (160 files) + pytest (322 passed) | PASS |

## Codex phrase test (manual, free)

Use an item planned from an approved idea with claims (e.g. a `youtube_longform` row from "plan next week"; "show claims for BG-x" first).

1. "write script for BG-x" → `ca script template BG-x --json`, then `ca script save BG-x <draft>`; shows a summary line (version, words, minutes) and the check, not the full text.
2. "show script BG-x" → `ca script show BG-x` (the Markdown).
3. "check script BG-x" → `ca script check BG-x`; OK or the listed problems.
4. "rewrite script BG-x shorter hook" → `ca item revise BG-x "shorter hook"` first, then template (shows the feedback) and save as v2; `ca script show BG-x --version 1` is unchanged.
5. "write brief for BG-x" → `ca brief template BG-x --json`, `ca brief save BG-x <draft>`; "show brief BG-x" → `ca brief show BG-x`.
6. "write copy for BG-y" (a LinkedIn post with a package and brief.json) → saved copy fills `post.headline` and `captions.linkedin_post`; then `ca content build "<folder>" --dry-run` as before.
7. Ask for a script with a statistic the claims do not cover → "number without verified source"; Codex should say research is thin and suggest "research this link …".
8. "write script for BG-z" on a YouTube Short → refused: shorts get scripts in Phase 9.
