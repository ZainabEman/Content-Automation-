# PRD v6: design fix, Roman images via Higgsfield, topics, YouTube structure, output folders and cleanup

**Project:** Branded Genius Content Automation
**Version:** v6.1, 20 Oct 2026 (references = all of `assets/reference/creative/`; rejected = all generated images in `outputs/`)
**Owner:** Roman (Branded Genius)
**Location in the repo:** `docs/PRD-v6-design-topics-cleanup.md`
**Builds on:** PRD v5 (`docs/PRD-v5-german-brand-youtube.md`), already implemented on branch `phase-v5-german-brand`. **Where v6 and v5 differ, v6 wins.** v6 also replaces the separate "Roman via Higgsfield" prompt; its content is in R4 below.

---

## 0. How this PRD is to be implemented

- The system works. Fix and extend it in place. Do not rebuild working parts or refactor unrelated modules.
- First check `git status`, the branch and `git log`. Preserve unrelated uncommitted changes, especially `config/calendar.json`.
- Find the actual code path that causes each problem (skills, templates, fallbacks, loaders), and fix it at the source that wins.
- Reuse existing functions, storage, naming and command style. Do not build parallel systems.
- No paid or external calls while building. Mock providers in tests. Never print or commit secrets. Never push or merge.
- Validation is targeted: the checks in §5, quick existing tests for changed modules, ruff and mypy on changed files. Run the full suite only if a focused check points to a wider break.
- Keep the token budget low: no long audit report before changing things. Short final report (§6).

## 1. Goals

1. Graphics that look like the approved Branded Genius references, not like competitors and not like the drifted latest output.
2. Roman images that look like the same person every time, using Higgsfield Soul 2.0 and the "Roman Traenkle" character, with a fixed guideline set and controlled variety.
3. Topics that follow the brand guidelines and the German-society AI themes, without forcing a service pitch into every post.
4. Rejected, deleted and already-generated topics never come back.
5. YouTube packages in one clean, consistent folder structure.
6. Outputs sorted by platform so they are easy to find.
7. Obsolete RunPod, competitor, UGC and finished-video code removed safely.

## 2. Sources of truth

In this order, strictly:
1. **The Branded Genius brand guidelines in the repo.** These cover tone, audience, themes, colours, typography and logo use. If anything below conflicts with the guideline file, the guideline wins. Report the conflict.
2. **Official brand assets:** logo files (wordmark and the "bg" emblem), fonts, colour tokens.
3. **Approved company references: every image under `assets/reference/creative/`** (all subfolders), except archive folders (any folder whose name starts with `_archive`). These include the dark-navy ads, and the carousel covers and final slides. Claude Code lists what it counts (folder and number of images) in its report. If an image clearly carries a third-party watermark or another company's logo, it is listed for Roman rather than used silently.
4. **The designer's prompt** (R3.3), verbatim in `brand/designer_prompt.md`.

**Rejected examples: every image the system has generated so far under `outputs/`** (all packages, previews and job images). None of them is approved. They show what must not happen and are never used as references or loaded by the generator.
- Claude Code reviews them, records the recurring failure patterns in the R3.1 list, and copies a small, downscaled sample into `tests/fixtures/rejected/`. The sample should be about 8–12 images that together cover every pattern, because `outputs/` is git-ignored and tests must not depend on it.

Competitor material is never loaded by the generator.

## 3. Requirements

### R1. Language and tone
- Everything the audience sees is in natural, professional German for people in Germany.
- Address: "du" on Instagram carousels (as in the approved carousels). "Sie" on Facebook posts, Facebook ads, LinkedIn and YouTube. Keep this as a per-category setting, unless the brand guideline says otherwise.
- There is a free German check before every dry run: spelling, umlauts and ß, no English leftovers, no generic AI-marketing phrases.

### R2. Topics and content strategy
- **Topic pool.** Topics come from three sources, mixed:
  1. **German-society AI themes:**
     - current problems in German society
     - AI making mistakes, and dangerous AI mistakes
     - AI being misused
     - situations where AI appears to be getting out of control
     - problems caused by incorrect AI use
     - German problems that AI could help solve
     - deepfakes
     - AI scams
     - AI replacing human decisions
     - overdependence on AI
     - companies using AI incorrectly
     - risks people are ignoring
  2. **Branded Genius services** and expertise, from the verified services list.
  3. **The subscribed newsletters** (the existing Gmail flow), filtered to what fits the brand guidelines.
- **No forced service pitch.** Remove the hard rule that every post must map to a service. A post may relate to a service, or simply cover a theme from the pool in an informative style. The safety rule stays: never claim a service, result, client, price or statistic that isn't verified.
- The theme list and the source mix live in config, for example `config/topic_pool.json`. Defaults: about 50% society themes, 30% services, 20% newsletters. The planner spreads themes so the same theme doesn't repeat back to back.
- Topic proposals and copy follow the brand guidelines strictly: tone, claims, audience, do's and don'ts.

### R3. Visual design (non-Roman graphics)

#### R3.1 What went wrong in the generated output (all of `outputs/` is rejected; each pattern needs a fix at the root cause and a regression test)
The patterns below were seen in the latest images. Claude Code adds any other recurring pattern it finds in `outputs/`.
1. **Layout coordinates printed in the image**, for example "x 6-34%" and "y 47-60%". Zone numbers are reaching the image-model prompt or a debug overlay. Fix: describe zones to the model in words only. Debug overlays appear only in preview mode.
2. **Garbled fake text and a doubled logo**, for example "v-inmleie" in a CTA, and "BRANDED" printed over a number. The model is drawing text and a logo where the app should.
3. **A flat bright royal-blue fill** (#004BA0) as the background. The approved look is a near-black, deep-midnight-navy base, with royal blue only as glow, lines and accents.
4. **Large empty panels with tiny icons, and a CTA pill colliding with its arrow circle.** The layouts don't match the references.
5. **A real photo of Roman as the final image, with a flat blue text block.** This is forbidden (see R4).
6. **The logo overlapped** by other elements.

#### R3.2 The approved look
Confirm every point against the reference files. **If this text and the files disagree, the files win.** Sample the real colours from the files and store them as brand tokens with the source file named. Don't guess hex values.

**Feed posts, Facebook ads, LinkedIn** (feed_ads references):
- **Base:** near-black or midnight navy, with a subtle vignette and soft blue glow. Never a flat bright-blue fill.
- **Text side** (usually the left 45–50%, sometimes mirrored): either a large dark-navy rounded panel with a thin glowing blue outline and one angled cut edge, or text directly on the dark base.
- **Headline:** heavy geometric sans, ALL CAPS, white, 3–5 short lines, with 1–2 keywords in the light-blue accent.
- **Body:** 2–3 lines, sentence case, regular weight, white. One keyword may be in light blue.
- **Optional icon row:** 3–4 circular outline icons with short German labels.
- **Visual side:** a rich photorealistic or 3D scene that fills its half. Examples:
  - glowing holographic UI
  - connected rounded-square icon nodes with thin blue lines
  - an AI brain or chip
  - a phone with a chat
  - an anonymous professional in a navy suit in a dark modern office

  Never an empty box.
- **Decoration** (a few, not all): diagonal blue bars, a dot grid near the logo, a chevron row, a particle-wave mesh in a corner, thin blue frame lines.
- **CTA:** wide rounded rectangle with a dark fill and a glowing blue outline, white text, and a circle-arrow icon on the right (or a calendar or play icon on the left). The text never touches the icon.
- **Logo:** the official BRANDED GENIUS wordmark, small, in the top-left or top-right corner, with clear space. Not on Roman creatives (R4.6).
- **Website:** optional, small, in a bottom corner. Not on Roman creatives.

**Instagram carousels** (carousel references):
- **Base:** pure black. A cyan dot grid top-left, thin glowing blue circle arcs touching the frame edges, and a blue particle-wave mesh along the bottom.
- **Headline:** bold geometric sans in sentence case, left-aligned in the left ~50%, white with keywords in bright blue. An optional short blue divider line. Uses "du".
- **Visual:** one per slide, on the right. Either neon blue line art (outline people, a handshake, a road with pins), a glossy white 3D robot with glowing blue eyes, or a glowing chip.
- **Slides:** 5–6, all in one style, with **no slide numbers**.
- **Logo and website:** only on the last slide. The last slide has the "bg" emblem and wordmark top-right, and a bottom engagement bar: a rounded rectangle with three columns, each with an outline icon:
  - LIKEN / wenn du zustimmst
  - TEILEN / mit deinem Netzwerk
  - SPEICHERN / für später
- **No logo or website on any other slide.**

**Typography:** take the fonts from the brand guideline and assets. If the guideline doesn't name them, report the closest match to the references and its licence status. Don't keep Jost silently if it doesn't match.

#### R3.3 The designer's prompt (verbatim, original spelling)
> Be my expert graphic designer and show your skill and generate for me a professional, creative, ad style post
> that I can post on LinkedIn using Brandit Genius brand style guide and logo  should also be at the side corner. It must match the motive and aim of Branded Genius.
>
> Must be 3:4

Her method: she gave this prompt to the image model together with the logo and the brand style guide. Keep what makes it work:
- the expert-designer role
- an ad-style, professional, creative result
- the real brand guide and logo as inputs
- a logo at the side corner
- matching Branded Genius's motive and aim (mission and themes in context)
- creative freedom within the brand
- an explicit format

Adapt the platform and format per category.

#### R3.4 Generation method (OpenRouter, using the configured model; don't switch models)
- **Designer mode** (the default for non-Roman feed posts, ads, LinkedIn and carousel slides). The prompt is built from:
  - the designer's prompt
  - the category and platform
  - the topic
  - the layout variant
  - the exact German headline, body and CTA strings in quotes
  - the R3.2 rules in plain words
  - explicit negatives: no coordinates or numbers that aren't part of the copy, no fake text, no extra logos, no watermarks, no flat bright-blue fill

  Attach the brand guideline (or its key pages), the logo, and 2–3 matching approved references as image inputs, if the configured model accepts them. If it doesn't, describe the references in words and report it. Tell the model to leave the logo corner empty. The app places the real logo file.
- **Text verification.** After generation, read the text in the image (OCR, or a vision check through the configured provider, with the cost shown in the dry run). Compare it exactly with the intended German strings, including umlauts, ß and punctuation. Any extra stray text also fails. There is one automatic retry; if it fails again, use composite mode.
- **Composite mode** (the fallback, and always for Roman images). The model, or Higgsfield for Roman, renders only the scene, with the text side kept dark and empty. The app draws everything else from a reusable **design kit** built to match R3.2:
  - panel
  - headline and body
  - icon row
  - CTA button
  - decorations
  - logo (where allowed)
  - engagement bar

  The result must look like the references, not like a flat template.

#### R3.5 Variety without drift
- Use the existing rotation, now over: text side, panel or no panel, visual type, decoration set and CTA style, all within R3.2.
- The same platform never gets near-identical consecutive images. No three in a row may share the same layout and background treatment.

#### R3.6 Design checks (extend `ca design check`)
The checks are:
- no stray text or coordinates
- the OCR text equals the intended text
- the logo is the official file, in an allowed corner, with clear space, and only where allowed
- no logo or website on Roman creatives
- nothing overlaps the logo, the CTA or Roman
- the base colour is within the sampled dark range
- contrast is at least 4.5 for body text and 3.0 for headlines
- margins are respected
- the carousel rules hold

Every image in `tests/fixtures/rejected/` must fail with the right reason.

### R4. Roman images (Higgsfield Soul 2.0)

- **R4.1 Provider.** Every image that shows Roman uses the Higgsfield plugin in Codex, model Soul 2.0, with the saved character "Roman Traenkle". Store the name in config and confirm the plugin's exact reference syntax. A real photo is never the final image; real photos are identity references only.
- **R4.2 How it runs.** Claude Code and `ca` can't call Codex plugins. So `ca` writes one job file per image:
  - prompt
  - character
  - model
  - aspect ratio
  - expected output path
  - credit estimate

  The Codex skill then runs the plugin and saves the image, and `ca` continues with the composite and the checks. It can be resumed. Each image gets at most 2 attempts, and both attempts count toward the cost. Nothing runs before the dry run's "ok". There is no silent fallback: if Higgsfield is unavailable, the job fails clearly.
- **R4.3 Roman guidelines** (replace the old Roman prompts and archive them):
  - **Fixed in every prompt:**
    - The character reference.
    - Framing: small in frame, a wide medium shot from the waist up, camera pulled far back. He is at the far edge of the image on the planned side, filling only the outer 20% of the width, with the frame edge cutting through his far shoulder and arm. There is no person in the centre or the other side.
    - Pose: body angled slightly toward the empty side, face turned to the camera, head level, eyes into the lens.
    - Wardrobe: a tailored dark navy suit and a crisp white shirt.
    - Lighting: a soft, even frontal key light on his face, with a subtle blue rim light on his shoulders and hair.
    - Negative space: the empty two-thirds is quiet. The room fades into deep near-black navy shadow at very low contrast, with no holograms, neon, light sources or bright reflections there.
    - Colour: deep midnight navy and near-black overall, a royal blue #004BA0 glow around him, and sky blue #69BFF8 only as small highlights on the holograms.
    - Camera: photorealistic corporate photography, 35mm, f/2.8, eye level. Roman sharp, holograms crisp, background softly blurred.
    - No text, letters, numbers or logos.
  - **3 backgrounds:**
    - BG-1: penthouse office at blue hour (floor-to-ceiling windows, blurred skyline, dark glossy desk with a silver laptop and a black mug).
    - BG-2: glass boardroom at night (frosted glass, a glossy black conference table with a blue glow, empty leather chairs).
    - BG-3: technology lab at night (a dark wall with a few vertical blue LED strips, blurred server racks, a polished dark floor).
  - **3 poses:**
    - P-1: seated at the desk, hands loosely clasped, calm and confident.
    - P-2: standing, one hand on the end of the table, a composed half-smile.
    - P-3: standing, arms crossed, calm and confident.

    Pose and background compatibility is stored as data: P-1 and P-2 use the desk or table that the background provides, adding a lab desk or workbench in BG-3.
  - **3 hologram styles,** confined to the third on his side:
    - H-1 hub: a glowing hub with a ring linked to 5 circular icons (chat, calendar, envelope, people, bar chart), plus a particle wave in the corner.
    - H-2 workflow: rounded-square icon nodes (document, envelope, calendar, gear, check mark) linked by glowing lines.
    - H-3 neural network: a network linked to 3 circular icons (chat, calendar, bar chart).
  - **2 sides,** for variety. S-R puts Roman on the right, as in the samples. S-L puts him on the left; it is written into the prompt, never made by flipping the image.
  - **Rotation:** 54 combinations. The same background, pose or hologram style is never used twice in a row on the same platform. The same side is never used three times in a row. A full combination is never repeated within the last 12 Roman images. The combination ID is stored in package.json, the registry and the tracker. Overrides are allowed, for example "use S-L BG-1 P-2 H-3 for BG-…".
  - **Golden fixtures:** Roman's three original prompts (Appendix A) go into `tests/fixtures/roman_prompts/`. The builder must reproduce them, whitespace-normalised, for S-R/BG-1/P-1/H-1, S-R/BG-2/P-2/H-2 and S-R/BG-3/P-3/H-3, using the "@Roman" token as in the originals.
- **R4.4 Aspect ratios.** Soul 2.0 supports only 9:16, 3:4, 2:3, 1:1, 4:3, 16:9 and 3:2. Validate every job against this list.
  - LinkedIn is generated at 3:4 and carousels at 1:1, with no crop.
  - Facebook posts and ads are generated at 3:4 and cropped to 4:5. The crop must not cut Roman's head or hands; if no safe crop exists, the image fails.
- **R4.5 Composite.** The app adds the German headline, body and CTA in the empty two-thirds, using the design kit. These checks run afterwards:
  1. Roman is in the outer ~25% on the planned side, and there is no person in the empty area.
  2. No overlap with Roman or the holograms, with a gap of at least 48 px at 1080 px width.
  3. The area behind the text is calm enough (detail and brightness variance).
  4. Contrast and margins pass.
  5. The German is correct and the tone is professional.
  6. Codex does a final visual check: readable, no overlap, German correct.
- **Operator acceptance:** after the user's explicit approval, `ca higgsfield accept --accept-text-zone-calm` may waive only the calm-text-area check for the accepted image. The override is logged with the accepted attempt; all other checks, including the final visual check, still block on failure.
- **R4.6 Roman creatives carry no logo and no company website.** This applies in every category.
- **R4.7** Every Roman image gets the AI-disclosure field and label (EU AI Act Art. 50).
- **R4.8** Images of people other than Roman may only show anonymous professionals, as in the references, and are never presented as Roman.

### R5. Providers and RunPod removal
- There are only two image providers:
  - **OpenRouter** (configured model) for every non-Roman image.
  - **Higgsfield Soul 2.0** for Roman.

  Don't change their credentials, model, character or plugin wiring beyond what R3 and R4 need.
- **Remove RunPod/ComfyUI completely:**
  - provider code
  - request, status and cost code
  - LoRA-on-RunPod commands
  - `config/comfyui.json` and the workflow JSONs
  - RUNPOD_* keys in `.env.example` and the loaders (never edit the real `.env`; list the keys Roman can delete)
  - dependencies used only by RunPod
  - fallbacks and tests
  - docs and AGENTS.md lines that describe it as active

  Grep before every deletion. Keep the LoRA training notebooks and docs only if they are documented as history; otherwise list them for Roman. After this, no active code or config mentions runpod or comfyui.

### R6. Topic rejection, deletion and duplicates
- **Rejected:** stored in the existing persistent store, and excluded from every suggestion source and every weekly or monthly plan, across restarts and new runs.
- **Deleted:** removed from the active list, with the deletion stored (soft-delete if that's the existing pattern). No cache, newsletter or scraper re-import, or regenerated suggestion may bring it back. Historical records may stay but never become active suggestions. If no delete command exists, add one in the existing style (for example `ca item delete <BG-ID>`) with a Codex phrase in AGENTS.md.
- **Previously generated:** new plans check all generated, rejected and deleted topics first. A light near-duplicate check (normalised text plus a similarity threshold in config) blocks reworded repeats, but allows genuinely different angles on the same broad theme.
- The calendar output, the registry and the tracker must show the same status. Fix it in the persistence and filtering logic, not just in what's displayed.

### R7. YouTube package structure
```
YouTube Long-Form/<Topic Name>/
  research.txt
  Style A/  script_de_teleprompter.txt  script_de_en_bilingual.txt  storyboard.txt
  Style B/  (same three files)
  Style C/  (same three files)
```
- The topic folder is the readable title, made safe for Windows and Google Drive. The BG ID is kept in the metadata.
- **research.txt:** one per topic, with findings and real, traceable source links. The existing source check stays.
- **Styles:** three genuinely different styles. Each has:
  - its own German-only teleprompter script
  - its own bilingual German/English script, generated from the teleprompter script and aligned with it
  - its own storyboard, matching that style's script

  There is no shared storyboard.
- **Storyboard fields** (from v5 R9.10):
  - scene number
  - time or duration
  - German line
  - English translation
  - visual direction
  - graphics
  - exact German on-screen text, with its English explanation
  - sources for factual visuals
  - transition and pacing notes
- **Re-runs** reuse the folder and fill in missing files, and never silently overwrite. They create a new version (for example `_v2`) or use the existing versioning.
- **Content:** about 8 topics a month for a German audience, on real German AI developments, applications and problems, from the R2 theme pool. Roman-led explainers and AI-host/Roman podcast-style formats are allowed as script formats only. No finished-video generation.

### R8. Output folders, sorted by platform
```
outputs/
  Instagram/Carousels/<YYYY-MM>/<YYYY-MM-DD>_<BG-ID>_<short-slug>/
  Facebook/Posts/<YYYY-MM>/<YYYY-MM-DD>_<BG-ID>_<short-slug>/
  Facebook/Ads/<YYYY-MM>/<YYYY-MM-DD>_<BG-ID>_<short-slug>/
  LinkedIn/Posts/<YYYY-MM>/<YYYY-MM-DD>_<BG-ID>_<short-slug>/
  YouTube Long-Form/<Topic Name>/
  _system/  jobs/  previews/  test-runs/  logs/      (internal, never uploaded)
```
Each social package contains:
- `final/`: publish-ready images only. Carousel files are named `slide_01.png` … `slide_06.png`; the file names are numbered, but the slides themselves show no numbers.
- `caption_de.txt`: caption, hashtags, CTA and alt text. Ads also get primary text, headline, description and the CTA button.
- `package.json`: metadata, provider, layout or Roman combination, check results and costs.
- `source/`: the raw model or Higgsfield images, before the overlay.

Other rules:
- The date is the planned publish date. The slug is short, ASCII and lowercase.
- All path constants, the skills and the Drive upload code use this tree. New Drive uploads mirror it.
- A migration command (for example `ca outputs migrate`) handles the existing local outputs. They are all rejected, so it moves them unchanged into `outputs/_system/rejected_legacy/`, keeping their original relative paths. They are not moved into the new platform tree. It is a dry run by default and only moves files with `--apply`. Nothing is deleted, and tracker or Drive records are not changed.
- Content items whose packages were rejected keep their BG IDs and topics in the registry, so the duplicate check still knows them. They can be regenerated with the new design on request.
- **Google Drive:** nothing that's already there is moved, renamed or deleted.

### R9. Cleanup of obsolete code
- Remove competitor references and competitor-derived layouts and prompts from every active source. Delete them only if nothing references them; otherwise archive them where no loader reads.
- Remove the obsolete UGC-ad and finished-video code and dependencies, including an unreachable HeyGen adapter, after checking imports.
- **Preserve:**
  - brand assets and approved references
  - the Higgsfield and OpenRouter config
  - topic management and planning
  - manager approval and rejection
  - Google Drive integration
  - tracker/CSV sync
  - Instagram, Facebook and LinkedIn generation
  - YouTube research and scripts
  - caption and hashtag generation
- No Google Drive deletions.

## 4. Unchanged from v5
German audience content; the four categories (Instagram carousel, Facebook post, Facebook ad, LinkedIn image); about 2 graphics a day; 8 YouTube packages a month; approval gates, the dry-run estimate and the "ok" before paid calls; manager-owned tracker fields are never overwritten.

## 5. Acceptance checks (targeted, offline)
1. Every image in the rejected sample (`tests/fixtures/rejected/`) fails the design checks, each with the right reason. No image-model prompt contains coordinates or zone numbers.
2. A mock preview sheet of every layout variant per category, next to the approved references, is saved at `outputs/_system/previews/design_fix_vs_references.png`.
3. A mock Roman package has no logo and no website. A mock carousel has its logo and website only on the last slide, and no slide numbers.
4. The Roman prompt builder reproduces the 3 golden fixtures. The rotation never repeats a background, pose or hologram twice in a row.
5. A topic plan without a service link is valid. A copy claim about an unverified service fails.
6. Rejected and deleted topics don't reappear after a new run in a fresh process or after a re-import. A reworded topic that was already generated is blocked; a different angle is allowed.
7. One mock YouTube topic produces exactly the R7 tree. A second run creates no duplicate folder and overwrites nothing.
8. One mock package per social category lands in the R8 tree with all four parts. The migration dry run lists the moves.
9. `rg -i "runpod|comfyui"` finds nothing in active code or config.
10. `git diff`: the Higgsfield and OpenRouter config, `.env` and unrelated user changes are untouched.

## 6. Final report (short)
- Each problem fixed, with its root cause in one line.
- Important files changed or deleted.
- The checks that were run and their results ("not verified" for anything that needs credentials or external services).
- Remaining blockers.
- The `.env` keys Roman can delete.
- Files left in place because they were uncertain.
- The migration dry-run summary.
- Whether the configured OpenRouter model accepts image inputs.
- The fonts found in the guideline.

## 7. Open items
- The Google Drive restructuring details (from v5) are still pending. Only new uploads use the new tree.
- The teleprompter app is unknown, so scripts are plain UTF-8 text.
- The OCR or vision-check method and its cost are to be confirmed on the first paid test.

## Appendix A. Roman's original prompts (golden fixtures, verbatim)

### A.1 S-R / BG-1 / P-1 / H-1
```
@Roman, small in frame, wide medium shot from the waist up, camera pulled far back. He sits at the far right edge of the image, occupying only the rightmost 20% of the frame width, the right frame edge cutting through his far shoulder and arm. The center and left of the image contain no person. Seated at a dark glossy desk, hands loosely clasped, body angled slightly toward the left, face turned toward the camera with head level, eyes looking directly into the lens, calm confident expression. Tailored dark navy suit, crisp white shirt. Soft even frontal key light on his face, subtle blue rim light on his shoulders and hair.

Setting: a real penthouse office at blue hour, floor-to-ceiling windows behind him with a softly blurred city skyline and a deep blue sky. The dark glossy desk extends from the right edge, with an open silver laptop and a black coffee mug near him.

Holographic layer: confined to the right third of the frame, a small glowing translucent hub floating just behind his shoulder, a thin ring of light connected by fine lines to five small circular holographic icons (chat bubble, calendar, envelope, people, bar chart). A faint wave of tiny blue particles drifts along the bottom right corner area only.

The left two-thirds of the frame is quiet negative space: the same room fading into deep near-black navy shadow, very low contrast, no holograms, no neon, no light sources, no bright reflections, only a faint dark suggestion of window frames, so text added later stays readable.

Light and color: deep midnight navy and near-black overall, royal blue #004BA0 glow around him, sky blue #69BFF8 only as small highlights on the holograms.

Photorealistic corporate photography, 35mm lens, f/2.8, eye level, Roman in sharp focus, holograms crisp, room softly blurred. No text, letters or numbers anywhere, no logos.
```


### A.2 S-R / BG-2 / P-2 / H-2
```
@Roman, small in frame, wide medium shot from the waist up, camera pulled far back. He stands at the far right edge of the image, occupying only the rightmost 20% of the frame width, the right frame edge cutting through his far shoulder and arm. The center and left of the image contain no person. One hand resting on the end of a long dark conference table, body angled slightly toward the left, face turned toward the camera with head level, eyes looking directly into the lens, composed confident half-smile. Tailored dark navy suit, crisp white shirt. Soft even frontal key light on his face, subtle blue rim light on his shoulders and hair.

Setting: a real modern glass boardroom at night, frosted glass wall behind him, a glossy black conference table reflecting a soft blue glow near him, empty leather chairs softly blurred.

Holographic layer: confined to the right third of the frame, a compact glowing workflow hovering behind him: a few small rounded-square holographic icon nodes (document, envelope, calendar, gear, check mark) connected by thin glowing lines, the glow reflecting faintly on the table beside him.

The left two-thirds of the frame is quiet negative space: the far end of the boardroom fading into deep near-black navy shadow, very low contrast, no holograms, no neon, no LED lines, no light sources, no bright reflections, so text added later stays readable.

Light and color: deep midnight navy and near-black overall, royal blue #004BA0 glow around him, sky blue #69BFF8 only as small highlights on the holograms.

Photorealistic corporate photography, 35mm lens, f/2.8, eye level, Roman in sharp focus, holograms crisp, room softly blurred. No text, letters or numbers anywhere, no logos.
```


### A.3 S-R / BG-3 / P-3 / H-3
```
@Roman, small in frame, wide medium shot from the waist up, camera pulled far back. He stands at the far right edge of the image, occupying only the rightmost 20% of the frame width, the right frame edge cutting through his far shoulder and arm. The center and left of the image contain no person. Arms crossed, body angled slightly toward the left, face turned toward the camera with head level, eyes looking directly into the lens, calm confident expression. Tailored dark navy suit, crisp white shirt. Soft even frontal key light on his face, subtle blue rim light on his shoulders and hair.

Setting: a real high-end technology lab at night, dark wall behind him with a few vertical blue LED strips, blurred server racks with tiny blue lights in the background behind him, polished dark floor.

Holographic layer: confined to the right third of the frame, a small glowing translucent neural network made of fine blue lines and light points floating above and behind his shoulder, connected by thin light paths to three small circular holographic icons (chat bubble, calendar, bar chart).

The left two-thirds of the frame is quiet negative space: the lab fading into deep near-black navy shadow, very low contrast, no holograms, no LED strips, no neon, no light sources, no bright reflections, so text added later stays readable.

Light and color: deep midnight navy and near-black overall, royal blue #004BA0 glow around him, sky blue #69BFF8 only as small highlights on the holograms.

Photorealistic corporate photography, 35mm lens, f/2.8, eye level, Roman in sharp focus, hologram crisp, background softly blurred. No text, letters or numbers anywhere, no logos.
```
