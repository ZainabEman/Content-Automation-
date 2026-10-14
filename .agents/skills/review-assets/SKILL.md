---
name: review-assets
description: The review gate for generated Branded Genius content. Shows what waits for review and one item's files, checks, costs and feedback; regenerates parts after the user's review revise. Use for "what needs review", "show BG-x for review", "regenerate BG-x" and "redo slide 3 of BG-x". Decisions (approve, reject, revise) are the user's; paid regeneration needs the user's "ok" to its dry run.
---

# Review assets

## Rules

- **Decisions are the user's.** Approve, reject or revise only after the user's own words: `uv run ca item approve BG-x`, `uv run ca item reject BG-x "<reason>"`, `uv run ca item revise BG-x "<feedback>"` (review gate). Never decide for them.
- An approved review uploads the approved version (config/storage.json `upload.requireReview`); report the upload line it prints (mock uploads say "(mock)").
- Regeneration costs money for image parts: show the dry run, stop for **"ok"**, then `--authorize <DR-id>`. Text-only changes of an animated carousel are free.
- Unchanged parts are kept; the reviewed version stays in `<package>/versions/v<n>/`.

## Steps

1. "what needs review" → `uv run ca review list`. Show the list; ask which to look at.
2. "show BG-x for review" → `uv run ca review show BG-x`: version, file paths (open the images or MP4s for the user), checks, costs, last feedback. Ask: **"Approve, reject or revise?"** Stop and wait.
3. "regenerate BG-x" (after the user's revise) → `uv run ca regenerate BG-x`; "redo slide 3 of BG-x" → `uv run ca regenerate BG-x --only slide3` (text only: `--only text`). It prints the dry run and `Dry run ID: DR-…`; stop for "ok". Exit code 1 "regenerate follows a review revise": ask the user for their feedback first, then `ca item revise`.
4. Only after the user's "ok" to that dry run: `uv run ca regenerate BG-x --only <the same parts> --authorize <DR-id>`. It keeps v<n>, starts v(n+1) (review not_reviewed again) and makes the parts again; continue person and set checks as in make-content (`uv run ca content build "<folder>"`). Then step 2 again.
