---
name: clips
description: Short clips from an approved Branded Genius YouTube final via Opus Pro, run by a person (manual provider). Use for "make clips from BG-x", "import clips for BG-x <folder>" and "select clips … for BG-x". Free in the app; the selection is the user's.
---

# Clips

## Rules

- Opus Pro is manual (config/clips.json `provider: manual`); there is no Opus Pro API call. Never upload the video anywhere yourself.
- Clips need the video's production final and its review approved.
- The selection is the user's: run `select` only with the numbers they gave (4–5 by default; another count only when they insist: `--force`).

## Steps

1. "make clips from BG-x" → `uv run ca clips handoff BG-x`. Tell the user where the note is: the final video, 10–12 candidates, 9:16, 15–90 s; they run Opus Pro and put the clips in one folder.
2. "import clips for BG-x <folder>" → `uv run ca clips import BG-x "<folder>"`. Each clip becomes a candidate short (BG ID, "Candidate N"); files that are not vertical or not 15–90 s are named and skipped. Show the candidates (open them for the user) and ask which to keep.
3. "select clips 2 5 7 9 for BG-x" → `uv run ca clips select BG-x 2 5 7 9`: those are approved, the rest rejected "not selected". Then review-assets for each clip and distribute ("prepare BG-x for all platforms").
