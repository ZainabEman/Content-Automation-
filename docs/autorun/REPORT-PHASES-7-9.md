# Autorun report — Phases 7–9 (2026-10-14)
Commits: P7 cd836bb 0aa8930 fe57415 · P8 c1340cd 213014a · P9 bf556ea 77d7e03 6bf9de9 (phase-7-review → phase-8-production → phase-9-distribution; nothing pushed or merged).
Full check: ruff OK, mypy --strict 176 files OK, pytest 374 passed (offline; Phase 4 e2e 9/9 with requireReview off in its sandbox).
Needs review: authorizations close at the end of a command once all their items are generated (a failed job keeps one open); requireReview: true replaces the upload after generation; a regenerated v(n+1) lives in the package, v<n> stays in versions/v<n>/.
Needs review: the thumbnail is the overlay fonts on a scrim (no logo); a HeyGen podcast is one request for the whole script; clips become shorts for YouTube, TikTok and Instagram; per-platform copy uses the social_graphic formula.
Client questions: default carousel format, max_attempts 2, provider/fallback per deliverable, 8 YouTube + 2 podcast finals a month, clips (10–12 asked, 4–5 kept), platform sizes, tracker column names, the HeyGen voice ID.
Manual tests (the user's; paid or external): 1) the first paid Higgsfield carousel, then `uv run ca costs calibrate --provider higgsfield-plugin` (`--apply` after a look); 2) the Drive plugin upload (STORAGE_PROVIDER=plugin, approve a review, "upload approved files");
3) one Roman recording import; 4) HeyGen once HEYGEN_VOICE_ID exists (`ca podcast heygen BG-x`); 5) one Opus Pro run (handoff → import → select); 6) one real post with its URL recorded (`ca publish mark`).
Codex phrase test (every new phrase):
- what needs review
- show BG-x for review
- regenerate BG-x
- redo slide 3 of BG-x
- upload approved files
- retry failed jobs
- show costs
- production status
- import recording/final for BG-x <path>
- send BG-x to the editor <name>
- BG-x recorded
- make thumbnail for BG-x
- export podcast audio for BG-x
- make clips from BG-x
- import clips for BG-x <folder>
- select clips … for BG-x
- prepare BG-x for all platforms
- what's ready to publish
- BG-x is live on LinkedIn <url>
- BG-x failed on TikTok <reason>
