---
name: make-carousel
description: Make the slide stills of an animated Instagram carousel with the Higgsfield Codex plugin under the single "ok": run every request in <package>/carousel/requests/, record each with `ca carousel record`, then run `ca carousel stills-check`. Use when `ca content build` or `ca calendar generate --build` prints "Carousel stills: N requests" or names the make-carousel skill.
---

# Make carousel

The app never calls the plugin. After the user's "ok" on the dry run, the build writes one request file per slide still. You make all of them under that one "ok".

## First run only: list the plugin

Do this once, before the first carousel dry run (it is free): if `docs/PHASE3-DECISION.md` section 10 still says "not listed yet":

1. List the Higgsfield plugin's tools. Find its image generation tool (and its image-to-video tool, for later).
2. Fill in section 10: tool names, image models, sizes or aspect ratios, reference images (yes or no, how many), the credits per image the plugin reports, and the date.
3. In `config/carousel_design.json` → `stills`, set `model` (leave `""` for the tool's default), `referenceImages` (`yes` or `no`) and `estimatedCredits` from that listing, so dry runs show real numbers.

From then on use exactly the names in section 10. If the plugin is not available in this Codex session, stop and say that the Higgsfield plugin is missing.

## The single "ok"

- The dry run (`uv run ca content build "<package>" --dry-run`, or the calendar's combined dry run) lists, per slide, the still's credits (an estimate), the total and the max with one retry per still. The user's "ok" approves that max. Never ask again per still.
- Only after the "ok": `uv run ca content build "<package>"` writes the requests (once) and `carousel/carousel.json` (the approved max).

## What a request gives you

`<package>/carousel/requests/still_NN.json`:

| Field | Meaning |
| --- | --- |
| `prompt` | the text-free, people-free prompt; after a failed check it already says what to fix |
| `negativePrompt` | for the tool's negative field; if it has none, append "Avoid: <these terms>" to the prompt |
| `width`, `height`, `aspectRatio`, `sizeRule` | 1080x1080, 1:1, or the closest size the tool offers (ca crops and resizes) |
| `tool`, `model` | from section 10 |
| `styleReferences`, `referenceImages` | style frames; attach them only if the tool accepts reference images |
| `outputPath` | where you save the image |
| `estimatedCredits`, `maxAttempts`, `status`, `attempts`, `creditsUsed` | the budget and what happened so far |

A slide without a request (the final slide) uses the app-drawn background: nothing to make.

## Steps

1. Read every request whose `status` is `pending`.
2. For each one: call the image tool with those inputs, wait until it is ready, save the image to `outputPath`, then record it: `uv run ca carousel record "<package>" --still N --credits <credits used> --provider-job-id <job ID>` (leave out what the plugin does not report).
3. If the call fails: `uv run ca carousel record "<package>" --still N --error "<reason>"` (add `--credits` if it charged). Retry once, only when the record says "Retry still_NN once now". At most 2 attempts per still in total.
4. If a record prints "STOP", stop and ask the user, showing the spend and the approved max. Never go over the max.
5. When every pending request is recorded: `uv run ca carousel stills-check "<package>"`. If it says "Next (no question): run the Higgsfield plugin for still_NN", make those (steps 2-3), then run stills-check again. A still that fails twice gets the local background by itself.
6. Report per slide (passed, local, local fallback) and the credits spent against the estimate and the max. Clips, overlay and MP4s follow in Phase 3 Step 4 (not built yet).

Never add people, faces, text, letters, numbers or logos to a still, and never rewrite a prompt (only the "Avoid:" append).
