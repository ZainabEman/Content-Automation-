---
name: produce-video
description: Branded Genius YouTube production after the script and production brief are checked (Roman records, the editing agency edits): production status, importing recordings, edits, finals and thumbnails, the editor handoff and the thumbnail. Use for "production status", "import recording/final for BG-x <path>", "send BG-x to the editor <name>", "BG-x recorded" and "make thumbnail for BG-x". Podcasts were removed in v5 (PRD R8). The research, scripts and storyboard come from make-youtube.
---

# Produce video

## Rules

- Production status: not_started → awaiting_recording (the script and brief checks passed: write-script) → recorded → editing → edited → final. Only the legal moves; going back to editing needs the user's review revise first (`ca item revise`, only with their words).
- Imports are copies (`versions/v<n>/production/<kind>/`); the original file is never changed. A YouTube final must decode and be 16:9 at 1080p or more; a refused file: show the reason, ask for another file.
- At final the review gate opens: continue with review-assets ("show BG-x for review"); an approved final uploads to the YouTube folder.
- Never mark something recorded, edited or final without the user's words or an imported file.

## Steps

- "production status" → `uv run ca production list [--month 2026-11]` (finals vs the monthly targets).
- "import recording for BG-x <path>" → `uv run ca import BG-x "<path>" --as recording` (also `--as edit`, `--as final`, `--as thumbnail`, `--as audio`); "import final for BG-x <path>" → `--as final`.
- "BG-x recorded" (the user recorded outside the app and has no file to import) → `uv run ca production set BG-x recorded`.
- "send BG-x to the editor <name>" → `uv run ca handoff BG-x --to "<name>"`: the handoff folder (script.md, brief.md, broll.md, assets.md, README.md); tell the user where it is. The returned edit: `uv run ca import BG-x "<file>" --as edit`, then `--as final`.
- "make thumbnail for BG-x" → import the background first if none (`--as thumbnail`), then `uv run ca thumbnail BG-x` (1280×720, the brief's thumbnail text, at most 5 words).
