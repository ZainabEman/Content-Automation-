---
name: text-overlay
description: Review and preview the German text the app draws on Roman's founder images (FB-R1, FA-R1, LI-R1, composite mode), for free and without generating anything. Use it after a founder image is built or accepted ("preview overlay BG-x"), before Roman sees it, when an overlay looks wrong, and to show all founder variants with short, medium and maximum copy ("overlay contact sheet"). On a failure it shortens the copy (german-editorial) before any new image.
---

# Text overlay (Roman's founder images)

The app draws headline, body, chips and CTA on Roman's picture (`workflows/design_render.py`). The image model never writes text on a Roman image, and the overlay never moves, crops or changes the picture. There's no logo and no website on a Roman image.

What the code enforces, and where the numbers live:

- **Fit:** binary search on the size, balanced German line breaks (`workflows/line_breaks.py`), down to the layout's `textLimits.minFontPx`, raised to `roman.minFontPx` in `config/design_directions.json` (body 28 px at 1080 px). Copy that doesn't fit at the floor stops with "text too long". Nothing is ever clipped.
- **Breaks:** no break after an article, a preposition or a number; no one-word last line in a headline; "KI-…" compounds and headline words never split. Body text breaks at a soft hyphen (U+00AD) the writer set only as the last resort.
- **Safe box:** the text column keeps `HOLOGRAM_GAP_PX` (48 px) from Roman's person box and from every hologram or icon. Headline, body, chips and CTA share one left axis. The body sits 32 px under the headline. The block's top is level with the top of Roman's head.
- **Contrast:** measured on the real pixels under each text (3:1 headline, 4.5:1 other text). A text below that gets the design kit's scrim behind it.

## Run the free preview

- One image: `uv run ca design overlay BG-123` re-renders the overlay on the picture the build used. It runs the build's checks and writes `outputs/_system/previews/overlay/<variant>_<layout>_<topic>.png` plus its manifest. Nothing is generated, and the package is unchanged.
- Other copy: `uv run ca design overlay BG-123 --copy shorter.json` (a JSON object with the same fields: `headline`, `sub`, `features`, `icons`, `cta`).
- All variants: `uv run ca design overlay --sheet` draws every founder variant on both sides with short, medium and maximum copy (`config/design_preview_copy.json` `_romanLengths`). It writes `founder_contact_sheet.png`.

## Review checklist (look at the PNG, then read the printed lines)

1. **Readable at phone size:** scale the PNG to about 400 px wide. The headline and body must still read easily (the printed px per text).
2. **No overlap:** no text touches Roman, a hologram, an icon or the CTA button (`overlap: passed`).
3. **Balanced:** the headline lines have similar lengths and there's no one-word last line. There's no big gap between headline and body, and the block sits at Roman's head height.
4. **Natural German breaks:** every line reads as a phrase. Article and noun, preposition and object, and number and unit stay together.
5. **Exact text:** `exactText: passed`, meaning the drawn strings equal the approved copy, letter for letter.
6. **Contrast and calm:** each contrast is at or above its need (3 or 4.5), and `textZoneCalm: passed`.

## On a failure

1. "text too long", a cramped block or an awkward break: shorten the copy with german-editorial (one idea, fewer words). Keep the headline within the layout's word hint, then preview again with `--copy`.
2. Overlap or calm failures with copy that fits: report it to the user with the preview path. The overlay never moves Roman, and the picture is never changed.
3. Only when the picture itself is wrong (placement, a busy text side), ask the user before any new Higgsfield attempt. That's a costed attempt after a new dry run and the user's "ok" (make-content / make-calendar).
4. When the preview passes, rebuild the package (`ca content build`). An accepted Higgsfield image costs nothing again.
