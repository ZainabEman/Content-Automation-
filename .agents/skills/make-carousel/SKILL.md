---
name: make-carousel
description: Make a static Instagram carousel (6-8 PNG slides at 1080x1350) in a post format (ig_checklist, ig_mistake_fix, ig_myth_fact, ig_steps): one OpenRouter image per slide, the text and the logo (last slide only) rendered by the app, a caption with at most 5 hashtags and alt text per slide, then Drive Instagram/<Content ID>/. Use for "make an insta post about TOPIC", "make an insta carousel about TOPIC [as <format>]" and the Friday calendar row.
---

# Make carousel

A static carousel is a normal package part: make-content stage 1 and 2, one dry run with the cost, one "ok", then the build. No plugin, no animation, no MP4.

## Steps

1. Start: `uv run ca content start --topic "TOPIC" --deliverables "instagram carousel" --request "<the user's exact words>"`; "as <format>" adds `--as <format>` (exit code 2: unknown format or not an Instagram format; ask). It prints `Post format: ig_… (instagram, 1080x1350, no person)`: the pick is never the format of the last 2 Instagram carousels; seeded by the Content ID. Show the format to the user.
2. Write `content.md` and `brief.json` as in make-content. `carousel.slides` = the template's 6-8 slides: slide 1 `cover`, then `body` slides, the last one `final` (a question that invites comments and the CTA with the offer). Per slide fill only `copy` (that format's fields), `illustration` (what the picture shows: no text, no people) and `altText` (what the slide shows and says). Caption: 3-5 hashtags including #BrandedGenius.
3. `uv run ca content build "<folder>" --dry-run`: the post format, every slide's text checked to fit its zone, then the slides x 4:5 via openrouter (CAROUSEL_IMAGE_MODEL; the key stays in `.env`, never shown) with the cost estimate and `Dry run ID: DR-…`. Fix every listed problem and run it again. Show the user the format, the slide count and the cost. Stop for **"ok"**.
4. Only after "ok": `uv run ca content build "<folder>" --authorize <DR-id>`. Each slide: the image without text, then the app's text and (last slide) the logo, saved at 1080x1350 in `images/carousel-N.png`. The set check follows (make-content step 6); then `uv run ca content build "<folder>"` again.
5. Done: `carousel/caption.txt` and `carousel/alt_text.txt` are written; the finished package uploads the PNGs and both files to Drive `Instagram/<Content ID>/`, adds its tracker row (Pending/Pending) and marks its Approved calendar row Generated. Report the folder, the Drive lines and the cost.

Never say "ok" for the user and never pass `--authorize` without the user's "ok" to that dry run.
