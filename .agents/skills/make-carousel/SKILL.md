---
name: make-carousel
description: Make a static Instagram carousel (PNG slides at 1080x1350) in a design direction (CS-1 tool breakdown, CS-2 bold statements, CS-3 numbered steps): pictures via OpenRouter only where a slide has one, text, logo and footer drawn by the app and checked, a caption with at most 5 hashtags and alt text per slide, then Drive Instagram/<Content ID>/. Use for "make an insta post about TOPIC", "make an insta carousel about TOPIC [as <direction>]" and the Friday calendar row.
---

# Make carousel

A static carousel is a normal package part: make-content stage 1 and 2, one dry run with the cost, one "ok", then the build. No plugin, no animation, no MP4.

## Steps

1. Start: `uv run ca content start --topic "TOPIC" --deliverables "instagram carousel" --request "<the user's exact words>"`; "as <direction>" adds `--as CS-2` (exit code 2: unknown or not a carousel direction; ask). It prints `Design direction: CS-… (…)`: never one of the last 2 carousels' directions; seeded by the Content ID. Show it to the user.
2. Write `content.md` and `brief.json` as in make-content. `carousel.slides` = the template's 6-8 slides: slide 1 `cover`, then `body` slides, the last one `final` (a question that invites comments and the CTA with the offer). Per slide fill only `copy` (that format's fields), `illustration` (what the picture shows: no text, no people) and `altText` (what the slide shows and says). Caption: 3-5 hashtags including #BrandedGenius.
3. `uv run ca content build "<folder>" --dry-run`: the design direction, every slide's copy drawn once to check it fits (free), then the pictures via openrouter (CAROUSEL_IMAGE_MODEL; the key stays in `.env`, never shown) with the cost estimate and `Dry run ID: DR-…`. Fix every listed problem and run it again. Show the user the direction, the slide count and the cost. Stop for **"ok"**.
4. Only after "ok": `uv run ca content build "<folder>" --authorize <DR-id>`. Each slide: the image without text, then the app's text and (last slide) the logo, saved at 1080x1350 in `images/carousel-N.png`. The set check follows (make-content step 6); then `uv run ca content build "<folder>"` again.
5. Done: `carousel/caption.txt` and `carousel/alt_text.txt` are written; the finished package uploads the PNGs and both files to Drive `Instagram/<Content ID>/`, adds its tracker row (Pending/Pending) and marks its Approved calendar row Generated. Report the folder, the Drive lines and the cost.

With STORAGE_PROVIDER=plugin the upload in step 5 is a manifest: if `<folder>/upload_manifest.json` exists, upload each entry with the Google Drive plugin, then `uv run ca drive record "<folder>" --results <json>` (upload skill, "Upload manifest"); the tracker row and the calendar row follow from the record.

Never say "ok" for the user and never pass `--authorize` without the user's "ok" to that dry run.
