---
name: make-carousel
description: Make an animated Instagram carousel end to end under the single "ok" with the Higgsfield Codex plugin: stills, clips, `ca carousel render` (which also uploads to Drive, adds the tracker row and marks the calendar row Generated). Use when `ca content build` or `ca calendar generate --build` prints "Carousel stills: N requests" or names the make-carousel skill, and for "continue carousel <package>".
---

# Make carousel

The app never calls the plugin. After the user's "ok" on the dry run, the build writes one request file per slide still; the stills check then writes one request per clip. You make all of them under that one "ok", then the app renders, uploads and records the carousel. No question between the "ok" and the summary, except a STOP.

## First run only: list the plugin

Do this once, before the first carousel dry run (it is free): if `docs/PHASE3-DECISION.md` section 10 still says "not listed yet":

1. List the Higgsfield plugin's tools. Find its image generation tool and its image-to-video tool.
2. Fill in section 10: tool names, models, sizes or aspect ratios (1:1?), reference images (yes or no, how many), negative prompt field, clip lengths, the credits per image and per 5 s clip the plugin reports, and the date.
3. In `config/carousel_design.json`, set `stills.model`, `stills.referenceImages` (`yes` or `no`), `stills.estimatedCredits`, `clips.model` and `clips.estimatedCredits` from that listing (leave a model `""` for the tool's default), so dry runs show real numbers.

From then on use exactly the names in section 10. If the plugin is not available in this Codex session, stop and say that the Higgsfield plugin is missing.

## The single "ok"

- The dry run (`uv run ca content build "<package>" --dry-run`, or the calendar's combined dry run) lists per slide the still and the clip with their credits (estimates; local ones are free), the total and the max with one retry per request. The user's "ok" approves that max for stills and clips together. Never ask again per still or clip.
- Only after the "ok": `uv run ca content build "<package>"` (or, for Instagram rows, `uv run ca calendar generate --build`) writes the still requests (once) and `carousel/carousel.json` (the approved max and the progress). Then run the steps below for each such package.

## What a request gives you

`<package>/carousel/requests/still_NN.json` and `clip_NN.json`:

| Field | Meaning |
| --- | --- |
| `capability` | `image` (still) or `video` (clip, image-to-video) |
| `prompt` | stills: the text-free, people-free picture; clips: the subtle motion (only the right half moves, static camera); after a failed check it already says what to fix |
| `negativePrompt` | for the tool's negative field; if it has none, append "Avoid: <these terms>" to the prompt |
| `width`, `height`, `aspectRatio`, `sizeRule` | 1080x1080, 1:1, or the nearest size the tool offers (ca crops and resizes) |
| `startImagePath`, `durationSec` | clips: the still to animate (upload it if the tool needs a URL), 5 s |
| `tool`, `model` | from section 10 |
| `styleReferences`, `referenceImages` | stills: style frames; attach them only if the tool accepts reference images |
| `outputPath` | where you save the result (`stills/still_NN.png`, `clips/clip_NN.mp4`) |
| `estimatedCredits`, `maxAttempts`, `status`, `attempts`, `creditsUsed` | the budget and what happened so far |

Slides without a request use the app's own version: a local background (the final slide) or the local animation (slow zoom, moving particle wave, glow pulse).

## Steps

1. **Stills.** For every still request whose `status` is `pending`: call the image tool with its inputs, wait, save the image to `outputPath`, then `uv run ca carousel record "<package>" --still N --credits <credits used> --provider-job-id <job ID>` (leave out what the plugin does not report).
2. **Failures.** If a call fails: `uv run ca carousel record "<package>" --still N --error "<reason>"` (add `--credits` if it charged). Retry once, only when the record says "Retry ... once now". At most 2 attempts per request in total. If a record prints "STOP", stop and ask the user, showing the spend and the approved max; never go over the max.
3. `uv run ca carousel stills-check "<package>"`. If it says "Next (no question): run the Higgsfield plugin for still_NN", make those (steps 1-2) and run it again. When all stills are settled it writes the clip requests and lists them.
4. **Clips.** For every clip request whose `status` is `pending`: call the image-to-video tool with its inputs, save the MP4 to `outputPath`, record with `--clip N` (same options and failure rule as steps 1-2).
5. `uv run ca carousel clips-check "<package>"`. Re-requests as in step 3. A clip that fails twice gets the local animation by itself.
6. `uv run ca carousel render "<package>"`: `carousel/final/slide_01.mp4` … `slide_08.mp4` (1080x1080, 24 fps, 5.0 s, silent) and `slide_NN.png` with the static text (Like/Share/Save row and logo on the last slide), the set check (report only), then by itself: the package is finished, Drive `Instagram/<Content ID>/` gets the MP4s, PNGs, `caption.txt` and `originals/` (raw stills), the tracker gets one row (link = the folder; fallbacks and set-check notes in its caption notes), and the calendar row becomes Generated. If the upload stopped, `uv run ca carousel finish "<package>"` tries again (uploaded files are skipped).
7. Show the user the "Summary:" block it prints (at most 8 lines: Drive folder, slides, credits real vs estimate, fallbacks, set check, tracker, calendar).

## Continue after an interruption

"continue carousel <package>": run `uv run ca carousel continue "<package>"` and follow its lines. Progress lives in `carousel/carousel.json` and the request files: a request that passed (or fell back) is never made again. A result that was saved but not recorded is recorded (with the credits the plugin reported), not made again. Still under the original "ok"; stop and ask only on a STOP line.

Never add people, faces, text, letters, numbers or logos to a still or clip, and never rewrite a prompt (only the "Avoid:" append).
