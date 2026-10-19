# PRD v5: German refocus, brand-controlled visuals and YouTube production planning

**Project:** Branded Genius Content Automation
**Version:** v5 draft, 19 Oct 2026
**Owner:** Roman (Branded Genius)
**Builds on:** the existing system described in `final project context.md` (v4, 19 Oct 2026) and `docs/PROGRESS.md` in the repo
**Status:** draft. Two parts of the brief are still missing (end of §14 storyboard and the Google Drive restructuring details). They are marked **PENDING** below and must not be guessed.

> Suggested location in the repo: `docs/PRD-v5-german-brand-youtube.md`. The Claude Code prompt that implements it is in `claude-code-prompt-v5.md`.

---

## 1. Summary

The system already works. This is an update, not a rebuild. The update changes five things:

1. **German first.** Everything the audience sees is in natural German written for people in Germany.
2. **Our brand controls the visuals.** Official brand guidelines, official brand assets, the approved graphics in the `references` folder and the graphic designer's prompt drive image generation. Competitor-derived references, layouts and prompt rules leave the active pipeline.
3. **Less is generated.** UGC ads, podcast media and finished YouTube videos are no longer generated.
4. **A new YouTube production-planning workflow.** Per topic: a verified research TXT, three different script styles, a German teleprompter script and a German-English script per style, and a storyboard for the editing agency (Takwa). Roman records; Takwa edits. The system never renders the final video.
5. **New volumes.** 8 YouTube long-form packages a month and 30–60 social graphics a month (target 2 a day), stored in an updated Google Drive structure that keeps the existing approval workflow.

The social workflow and the YouTube workflow stay **separate**: separate skills, commands, config and output folders, so a change to one cannot break the other. Shared infrastructure (registry/BG IDs, approval, cost authorization, Drive, tracker) is reused, not duplicated.

## 2. Baseline: what exists today

From `final project context.md` v4. Items marked (reported) or (unknown) there must be checked in the code before they are changed.

| Area | Today | Confidence |
|---|---|---|
| Orchestration | Codex Desktop runs skills in `.agents/skills/{show-content, make-content, make-video, make-calendar, make-carousel}`; skills call the `ca` Typer CLI | reported |
| Calendar | Weekly CSV in `calendar/<YYYY-Www>.csv`; cadence Mon LI, Tue FB, Wed LI, Thu FB, Fri IG carousel (5 a week, about 21 a month); approve/reject; BG IDs | confirmed |
| Approval and cost | Free stage 1, one combined dry run with cost, single "ok" | confirmed |
| Images | `ai/image/` with providers `openrouter, mock, comfyui, runpod`; app renders text (`text_overlay.py`) and logo (`logo.py`) | reported |
| Roman images | Always Roman LoRA (Z-Image Turbo, v2 step 3000) through ComfyUI on RunPod Serverless; RunPod not live yet | reported |
| Design | Phase D: 12 design directions (FB-1..3, LI-1..3, CS-1..3, FD-1..3), rotation (no back-to-back repeat, penalty for last 5), `ca design check` | reported |
| Design sources | 36 reference images + 7 founder images from a Word doc (captions most likely from a competitor, aurora-automation.com), stored in `assets/reference/creative/social_refs/` | reported |
| Carousel | Phase 3 animated carousel via Higgsfield (8 slides, 1:1); CS-BG company style prompt given but not confirmed run (had a "01/07" counter pill) | reported |
| Language | Renders are English; `carousel.language` defaults to `en` | confirmed |
| Storage | Google Drive `Content Automation/<Platform>/<Content ID>/`; Google Sheet "Content Tracker" with manager-owned fields never overwritten | confirmed |
| YouTube, podcasts | Not started (per v4 status checklist) | confirmed |
| UGC / video | `make-video` skill exists; HeyGen and Higgsfield plugins used; a UGC ad folder exists in Drive (per this brief) | needs inspection |
| Branches | phase-1 → phase-2 → phase-3 → (phase-4?) → `phase-d-design` (current, 7d20445); nothing merged or pushed | confirmed |

**Not described in the context doc and therefore must be inspected, not assumed:** the brand guideline file(s) and their location, the official logo files, the `references` folder Roman refers to and what it contains, the RunPod endpoint configuration and request format, the OpenRouter image model in use and whether it accepts image inputs, which text model writes copy today, the tracker columns, the teleprompter software, and what `make-video` actually does.

## 3. Scope

**In scope**
- German for all audience-facing output (social and YouTube).
- Brand-controlled visual system for four social categories.
- Integration of the graphic designer's prompt principles.
- Controlled layout variation per platform.
- OpenRouter vs RunPod LoRA routing.
- Monthly social planning at about 2 graphics a day.
- Removal of UGC ad, podcast and finished-video generation.
- New YouTube research and production-planning workflow.
- Google Drive and tracker changes needed for the above.

**Out of scope / unchanged**
- Automatic publishing (stays manual).
- The approval words and gates ("ok", approve/reject by number or BG ID).
- Cost authorization rules (estimate, explicit "ok", never unlimited, never silent fallback).
- LoRA training.
- Opus Pro / Shorts / TikTok: not mentioned in this brief. Leave existing code untouched; see open questions.

**Removed from active generation**
- UGC ads, podcast media, finished YouTube videos.
- Competitor-derived image references, layouts and prompt instructions.

## 4. Requirements

### R1. Language

- **R1.1** All audience-facing text is German: text in images, carousel slides, Facebook posts, Facebook ads, LinkedIn images, captions, hashtags, headlines, hooks, CTAs, YouTube teleprompter scripts, Roman's spoken lines, German on-screen text in storyboards.
- **R1.2** The German must be natural and professional for people in Germany: no literal translations, no awkward phrasing, no generic AI marketing language. Use "Sie" as the default address for business audiences unless the brand guidelines or Roman's existing texts say otherwise (open question Q3).
- **R1.3** Internal docs, logs, code comments and agency instructions may be English.
- **R1.4** Every language default in config (for example `carousel.language`) becomes `de`. English generation is not deleted; it is simply no longer the default.
- **R1.5** Text rendering must handle German correctly: umlauts and ß in the chosen fonts, longer German words in fit-or-fail checks, hyphenation or line breaking that does not split words incorrectly.
- **R1.6** A free German quality pass runs on all copy before the dry run (spelling, umlauts present instead of "ae/oe/ue", no English leftovers in audience text, banned-phrase list for generic AI marketing language).

### R2. Brand-controlled visual system

- **R2.1 Sources of truth**, in priority order:
  1. official Branded Genius brand guidelines;
  2. official brand assets (logo files, fonts, colours, icons);
  3. approved graphics in the existing `references` folder;
  4. the graphic designer's prompt (R3).
- **R2.2 Competitor material leaves the active pipeline.** Every image reference, layout definition, design direction and prompt instruction that was derived from competitor graphics (the Phase D 36 + 7 references, the aurora-automation.com captions, reference groups G1–G3) is removed from what the generator loads. Files are **moved to an archive folder that the generator never reads**, not deleted, so useful research elsewhere is preserved.
- **R2.3 Reference study.** The approved references are analysed for palette, fonts and typography, text hierarchy, headline placement, image placement, logo position and size, composition and spacing, backgrounds and shapes, CTA placement, supporting graphics, and overall balance. The result is written to a brand layout spec (for example `brand/reference-analysis.md` plus machine-readable tokens and layout definitions) with the source reference file named for every rule.
- **R2.4 Reproduce closely.** Layouts reproduce these characteristics as closely as practical, adapted to topic and format. No new visual identity, no colours or fonts from competitor or unrelated inspiration images.
- **R2.5 Real logo only.** The logo is always the official file, placed by code. It is never redrawn or approximated by a model.
- **R2.6 Compositing.** Where the image model cannot render exact German text, fonts or the logo reliably, the model generates the visual components and the app composites the exact German text and the real logo. The existing app-rendered text and logo pipeline is the basis for this.
- **R2.7 Brand check.** `ca design check` (or its successor) validates against the new tokens: logo file hash, size and position per layout; colours from brand tokens only; fonts from the brand set; contrast; margins; and the category rules in R4 (for example no logo on carousel content slides).

### R3. The graphic designer's prompt

The designer's prompt, as given by Roman (verbatim, including the original spelling):

> "Be my expert graphic designer and show your skill and generate for me a professional, creative, ad style post that I can post on LinkedIn using Brandit Genius brand style guide and logo should also be at the side corner. It must match the motive and aim of Branded Genius.
>
> Must be 3:4"

Her process: the prompt was given **together with the logo and relevant context** (the brand style guide). The outputs are the company's preferred benchmark.

What makes it effective, and must be preserved:
- **Role and quality bar:** the model acts as an expert designer and is asked for professional, creative, ad-style work, not a plain illustration.
- **Brand style guide as input:** the model sees the actual guide, not a summary of hex codes.
- **The real logo as an input**, with a placement rule (side corner).
- **Purpose and audience:** a post for LinkedIn that matches the motive and aim of Branded Genius (so the brand's mission and services must be in the context).
- **Creative latitude** within the brand, instead of a rigid template.
- **Explicit format:** 3:4.

Requirements:
- **R3.1** Compare the designer's prompt with every current image prompt and image-generation skill, and write the comparison down (what the current prompts add, what they lose).
- **R3.2** Build a **designer prompt template** per category (LinkedIn, Facebook post, Facebook ad, carousel) that keeps the six elements above and adds the topic, the German headline/copy, the target layout variant and the relevant approved reference images.
- **R3.3** The prompt system must actually pass the brand guideline content, the logo image and the selected approved reference images to the model where the provider supports image inputs. If the configured OpenRouter model does not accept image inputs, report this and propose options with cost; do not silently switch models (BR "no silent change of provider").
- **R3.4** Keep the designer's approach as the core. Do not replace it with generic image-generation prompts.
- **R3.5** Text accuracy rule: final German text and the logo are applied by the app (R2.6) unless a test shows the model renders them exactly. The model is told which zones to keep free for text and logo, so the composition still follows the designer's layout intent.
- **R3.6 Benchmark check:** a preview contact sheet places new outputs next to the approved references (and the designer's own outputs, if they are in the references folder) for Roman's visual review before any paid batch.

### R4. Four social graphic categories

Exactly four main categories, each with its own generation handling and its own output folder. Final sizes come from the approved references; the defaults below apply where the references do not decide.

| Category | Default size | Key rules |
|---|---|---|
| **Instagram carousel** | 1:1, 1080×1080 (as in the company's samples) | 5 or 6 slides. **No slide numbers or counters** (removes the CS-BG "01/07" pill). **Logo only on the last slide.** Website optional and, if used, only on the last slide. Consistent layout, type, colours across slides. Concise, informative German. Counts as **one** asset in the calendar. |
| **Facebook post** | 4:5, 1080×1350 | Single static feed graphic, German text, brand identity. |
| **Facebook ad** | 4:5, 1080×1350 (plus 1:1 if needed) | Separate category, folder and handling from Facebook posts. German promotional copy, one clear message, CTA. Outputs: creative, primary text, headline, description, CTA button choice from Meta's standard list. No ad is placed or paid for by the system. |
| **LinkedIn post image** | **3:4, 1080×1440** (designer's prompt) | Professional graphics on AI applications, AI-related business problems, practical solutions, services and expertise. German text. Logo at the side corner. |

- **R4.1** Founder-led (Roman) graphics are not a fifth category; they are a variant inside these four, routed per R6.
- **R4.2** Each category has its own prompt templates, layout variants, checks and Drive folder.
- **R4.3** Carousel animation (the Phase 3 Higgsfield pipeline) is kept in the code but is not the default output; static slides are. See Q1.

### R5. Visual variety without brand drift

- **R5.1** Each category has a small controlled set of layout variants (suggested 3–5) derived from the approved references, varying headline position, text/image arrangement, main visual placement, whitespace, supporting graphic placement, approved background treatments and CTA placement.
- **R5.2** Variants never introduce colours, fonts or styles outside the brand tokens.
- **R5.3** Rule: **no three consecutive near-identical images on the same platform.** The existing Phase D rotation (no back-to-back repeat of the same direction, penalty for the last 5) already satisfies this and is reused, now keyed on the new layout variants and the background treatment.
- **R5.4** History source: use the existing design history (registry or `state/design_history.json`) and, if the tracker has a layout column, that too. Store the chosen layout variant id in package.json, the registry and the tracker (new column, see R11).

### R6. Image routing: OpenRouter and RunPod

- **R6.1** Images that do **not** need Roman's consistent face: OpenRouter, with the configured image model and the R3 prompt system.
- **R6.2** Images that **do** need Roman's consistent face: the trained Roman LoRA through the RunPod endpoint (today implemented as ComfyUI on RunPod Serverless with Z-Image Turbo + LoRA v2 step 3000).
- **R6.3** Routing is decided per job by an explicit `requires_roman` flag set at planning time (founder-led variant or Roman requested), not by the global `IMAGE_PROVIDER`. This matches the existing 7d20445 routing rule; verify it in the code rather than rewriting it.
- **R6.4** Before changing the integration: inspect the actual RunPod endpoint config, model files, request format and current implementation, and report them.
- **R6.5** Credentials only in environment variables or the existing `.secrets/` / `.env` setup. Never in source, prompts, logs, package files or the tracker.
- **R6.6** No silent fallback between providers. If RunPod is unavailable, a Roman job fails with a clear message.
- **R6.7** LoRA images of Roman keep the planned AI-disclosure field (EU AI Act Art. 50).

### R7. Monthly social production

- **R7.1** Target 2 graphics a day, about 30–60 a month. A carousel counts as one asset.
- **R7.2** A monthly planner (for example `ca plan month 2026-11`) proposes a calendar across the four categories and content types (static posts, carousels, educational, promotional, Facebook ad creatives, other branded social graphics). The weekly calendar commands keep working.
- **R7.3** The planner picks the most suitable format per topic and spreads formats so the same type is not generated every day. The mix is configurable (for example in `config/deliverables.json`) with a sensible default, such as per 60: LinkedIn 16, Facebook post 16, Instagram carousel 16, Facebook ad 12.
- **R7.4** Each asset gets German publishing metadata: caption, hashtags (platform rules in §13 of the context doc: Instagram ≤ 5, LinkedIn 0–3), headline, hook, CTA, alt text, and for ads the ad fields in R4.
- **R7.5** Topic sources for social: the existing newsletter/scraper/manual topic flow, plus the German sources added for YouTube (R9.3). Topic → service matching (5 verified services or insight-only) stays.
- **R7.6** The dry run shows the monthly or weekly cost at the new volume before the "ok".

### R8. Remove UGC, podcast and finished-video generation

- **R8.1** Remove the active generation processes for UGC ads, podcast media and finished YouTube videos: skills, commands, Codex phrase mappings in `AGENTS.md`, config entries, and dependencies used only by them.
- **R8.2** Inspect first. Keep anything the new workflows still need (for example Higgsfield code used by carousels, HeyGen only if something else uses it).
- **R8.3** Keep YouTube planning and all reusable research materials. Do not delete the YouTube directory.
- **R8.4** Google Drive: remove **only** the UGC ad folder. This is an external, hard-to-undo action: list its contents first and do it only after Roman's explicit confirmation; move it to the Drive trash rather than deleting permanently.
- **R8.5** Old tracker rows and Drive files for UGC are not deleted.

### R9. YouTube research and production planning

#### R9.1 Volume and selection
- 8 topics a month; 3 script styles per topic (24 candidate scripts); 2 files per style (24 teleprompter + 24 bilingual); 1 storyboard per topic for the selected style.
- Topics go through the same approve/reject gate as social topics, with their own BG IDs.

#### R9.2 Editorial direction
- Real AI-related problems for German individuals, businesses, employees and society: wrong AI decisions, misuse, scams and fraud, deepfakes and impersonation, AI replacing human judgement, overdependence, security risks, poor implementation in companies, privacy and data protection, overlooked risks, real problems AI can help solve, safe and effective use.
- Prioritise real incidents, current developments, documented problems and practical solutions over hypothetical future risks.
- Specifically relevant to German viewers, not translated international content.
- No exaggerated fear, misleading clickbait, unsupported claims or fabricated personal stories.

#### R9.3 Research and German sources
- Research before writing. Prioritise German newspapers and news organisations, public broadcasters, official government sites, German cybersecurity and data protection authorities, research institutions and universities, reputable German industry publications, original papers, official company statements, and reliable incident reports.
- Use what fits the topic; do not force the same publishers every time. International primary sources may supplement.
- Add an editable German source list (for example `config/sources_de.json`) as a starting point, not a hard filter. Example entries to verify and adjust: tagesschau.de, ZDFheute, Deutschlandfunk, heise online, golem.de, t3n, Handelsblatt, FAZ, Süddeutsche Zeitung, DER SPIEGEL, ZEIT ONLINE, BSI, BfDI and the Länder data protection authorities, BKA (Bundeslagebild Cybercrime), Bundesnetzagentur, Verbraucherzentrale, Bitkom, Fraunhofer institutes.
- Who performs web research (Codex with web access, or an LLM call from `ca`) depends on what exists today; inspect and report.

#### R9.4 Research TXT file (one per topic, in the topic's main folder)
Plain UTF-8 TXT containing:
1. Topic name and working title (German, with an English gloss).
2. Why the topic matters to German viewers.
3. Summary of the real incident, problem or finding.
4. Relevant publication and event dates.
5. Article titles and publisher names.
6. Full source URLs.
7. Key statistics and supporting facts, each with its source.
8. Quotations where useful, accurately attributed.
9. Claims that need careful qualification.
10. Conflicting information and source limitations.
11. Three clearly separated sections: **Verified facts**, **Interpretation**, **Proposed solutions**.

#### R9.5 Source verification
- Never invent news stories, statistics, URLs, article titles, quotations or events.
- A free check command (for example `ca youtube check-sources <BG-ID>`) fetches every URL and records status, final URL, page title and date where available; checks that each quotation appears in the page text; and flags each fact whose source does not mention it. Results are written into the research file's verification section.
- A topic with failed checks cannot move to script writing unless the failure is fixed or Roman overrides it (logged).
- Claim support that cannot be checked automatically is marked "needs human check", never "verified".

#### R9.6 Storytelling formula (default, adaptable)
1. Hook (question, real incident, surprising verified finding or concrete situation)
2. Warning (the problem or risk)
3. Critical situation (what happened / is happening)
4. Why it matters (for German individuals, businesses or society)
5. Why it happens (causes, limitations, misuse, implementation failures)
6. What could go wrong (realistic risks)
7. Correct response (responsible use, practical solutions)
8. Conclusion (useful takeaway)

This replaces the old YouTube formula and absorbs the old podcast formula.

#### R9.7 Three genuinely different styles
- Same topic, same verified core facts; clearly different hook, storytelling, delivery and presentation. Not three rewrites of one text.
- Starting styles, adapted per topic: **A Investigativ** (start with a real incident, uncover causes and consequences), **B Direkte Warnung** (immediate risk or question, evidence, practical response), **C Menschlich** (realistic everyday or workplace scenario tied to verified facts and solutions).
- Professional, natural spoken German appropriate for a CEO. Never imply Roman personally experienced or witnessed something he did not. Scenarios in style C are labelled as illustrative in the script ("Stellen Sie sich vor …"), not presented as real events.
- A free difference check flags style pairs whose openings or structure are too similar.
- Target length: see Q4 (default 10–12 minutes, about 1,300–1,600 spoken German words).

#### R9.8 Teleprompter script (German only), one per style
- Entirely German spoken content; natural, comfortable sentences; clean paragraphs; readable line breaks; complete script.
- No English, no editor notes, no citations, no technical instructions, no headings or labels that could be read aloud.
- Plain UTF-8 TXT unless the actual teleprompter's requirements say otherwise. Do not claim compatibility with an unverified proprietary format (Q5).

#### R9.9 Bilingual script (German-English), one per style, for Takwa
- For every German line or logical paragraph, the English translation directly underneath, both clearly labelled:

  ```
  German:
  Künstliche Intelligenz kann wichtige Entscheidungen beeinflussen, aber ihre Ergebnisse sind nicht immer zuverlässig.

  English:
  Artificial intelligence can influence important decisions, but its outputs are not always reliable.
  ```
- Preserves every German line of the matching teleprompter script, nothing omitted or summarised in either language; consistent terms.
- **Generated from the teleprompter file**, not written separately, and a free check verifies that the German text in the bilingual file is identical to the teleprompter file, paragraph for paragraph.

#### R9.10 Storyboard for the editing agency
One per topic, for the selected style (the select command, for example `select style B for BG-…`, triggers it). The editor reads English, so each scene explains both what Roman says and what appears on screen. Each scene includes:
- scene or segment number;
- approximate timecode or estimated duration;
- German spoken line or script excerpt;
- English translation or explanation;
- visual direction;
- suggested graphics, diagrams, animations, screenshots or illustrations;
- exact German on-screen text where applicable;
- English explanation of that on-screen text;
- source references for factual visuals (from the research file);
- notes on transitions, pacing and supporting footage;
- clear placeholders … **PENDING: the brief is cut off here ("Clear placeholders s…"). The remaining storyboard requirements, and the file format, are not yet known.** Until they arrive, the storyboard is a UTF-8 Markdown file with one block per scene (not a wide table), so it reads well in any viewer.

#### R9.11 YouTube folder per topic
```
YouTube/<YYYY-MM>/<BG-ID>_<slug>/
  research_<slug>.txt
  style-A_investigativ/
    teleprompter_DE.txt
    script_DE-EN.txt
  style-B_direkte-warnung/
    teleprompter_DE.txt
    script_DE-EN.txt
  style-C_menschlich/
    teleprompter_DE.txt
    script_DE-EN.txt
  storyboard_<selected-style>.md
  package.json
```
Exact Drive names depend on the PENDING Drive section (R10).

#### R9.12 Separation
A separate Codex skill (for example `.agents/skills/make-youtube`) and a separate `ca youtube …` command group, with its own config and prompts. It reuses only the shared registry, approval, authorization, storage and tracker layers.

### R10. Google Drive structure

- **R10.1** Known from the brief: support the new categories and the YouTube workflow; keep existing approval workflows and useful assets; separate folders for Facebook posts and Facebook ads; keep the YouTube directory; remove only the UGC ad folder (R8.4).
- **R10.2** Proposed default until the details arrive:
  ```
  Content Automation/
    Instagram Carousels/<Content ID>/
    Facebook Posts/<Content ID>/
    Facebook Ads/<Content ID>/
    LinkedIn/<Content ID>/
    YouTube/<YYYY-MM>/<Content ID>_<slug>/   (R9.11)
  ```
- **R10.3 PENDING:** Roman's detailed Drive restructuring instructions were cut off. Do not rename or move existing Drive folders until they arrive. New folders may be created.
- **R10.4** Uploads stay idempotent, use the existing `drive.file` scope, and never move or delete existing files without explicit confirmation.

### R11. Tracker and approvals

- Reuse the Google Sheet "Content Tracker" and its header-name matching. Never overwrite manager-owned fields.
- Add columns only where needed, for example: Category (Instagram Carousel / Facebook Post / Facebook Ad / LinkedIn / YouTube), Language, Layout Variant, Requires Roman, Selected Script Style. New columns are added at the end so existing manual columns are untouched.
- YouTube rows: one row per topic, with links to the research file, the six scripts and the storyboard.
- Approval flow unchanged: propose → approve/reject → free stage → dry run with cost → "ok" → build → Drive → tracker. YouTube text generation is cheap but still goes through the dry-run estimate if it uses a paid API.

## 5. Operator commands (Codex phrases, suggested)

| Phrase | Effect |
|---|---|
| "plan month November" | Monthly social calendar at about 2 a day (R7) |
| "make calendar next week" | Unchanged weekly flow, now German and with the 4 categories |
| "plan youtube November" | 8 German YouTube topic proposals with first sources |
| "approve 1 3 5" / "reject 2" / by BG ID | Unchanged |
| "research BG-123" | Research TXT + source check (R9.4, R9.5) |
| "write scripts BG-123" | 3 styles × 2 files (R9.7–R9.9) |
| "select style B for BG-123" | Marks the choice, writes the storyboard (R9.10) |
| "generate approved" | Unchanged gate, now with routing per R6 |

## 6. Changes to earlier decisions

| Earlier (context v4) | New |
|---|---|
| #12 References used for layout only; included competitor references | Only approved company references; competitor material archived and unused |
| #13 12 design directions from the Phase D references | Layout variants rebuilt from approved references; rotation logic kept |
| Phase 3: 8 slides; CS-BG with "01/07" counter | 5–6 slides, no numbers; logo and optional website on last slide only |
| §8.1 default canvas 4:5; LinkedIn 1:1 | LinkedIn 3:4 (designer's prompt); others from references |
| Weekly cadence of 5 posts | About 2 graphics a day, monthly planner |
| `carousel.language = en`, English renders | German default everywhere audience-facing |
| Platforms included podcasts, UGC, finished YouTube | Removed from generation; YouTube becomes research and production planning |
| YouTube formula (4 steps), podcast formula (5 steps) | One 8-step storytelling formula for YouTube |
| #15 Roman always via LoRA on ComfyUI/RunPod | Unchanged in principle; confirmed as the RunPod LoRA route |

## 7. Acceptance criteria

1. No audience-facing English in any generated social or YouTube output in a mock end-to-end run (automated check).
2. The generator loads no file from the competitor archive (automated test).
3. A contact sheet of all layout variants for the 4 categories sits next to the approved references, and Roman approves it before the first paid batch.
4. Carousels: 5–6 slides, no number or counter on any slide, logo only on the last slide, website only on the last slide if present (automated check).
5. Facebook posts and Facebook ads have separate templates, packages and Drive folders.
6. LinkedIn images are 3:4 and carry the real logo at the side corner; the logo hash matches the official file.
7. Over a simulated month, no platform has three consecutive images with the same layout variant and background treatment.
8. Routing: `requires_roman` jobs go to RunPod, all others to OpenRouter; no silent fallback; no secret in any log or output (tests).
9. The monthly planner produces 30–60 assets with a format mix, a carousel counting as one.
10. UGC, podcast and finished-video commands and skills are gone; YouTube planning, carousel and research code still pass their tests.
11. YouTube mock run for one topic produces the research TXT, 3 styles × 2 files and a storyboard in the R9.11 layout; the bilingual file's German matches the teleprompter file exactly; the teleprompter file contains no English, no citations and no headings.
12. Source check catches a dead URL and a quotation that is not in the page (tests with fixtures).
13. ruff, strict mypy and the full offline test suite pass. No paid or external call was made without an estimate and an "ok".

## 8. Implementation phases

| # | Phase | Stop for Roman? |
|---|---|---|
| 0 | Read-only audit: inventory, conflicts, file-level plan | Yes |
| 1 | Removal (UGC, podcast, finished video) and competitor archive; German defaults | No |
| 2 | Brand system: reference analysis, tokens, designer prompt templates, 4 categories, layout variants, rotation, checks, contact sheet | Yes (visual review) |
| 3 | Image routing OpenRouter / RunPod (inspect, then adjust) | No |
| 4 | Monthly social planner and German publishing metadata | No |
| 5 | YouTube workflow: topics, research TXT, source check, 3 styles, teleprompter, bilingual, storyboard | Yes (sample review) |
| 6 | Drive and tracker changes (new folders only until PENDING details arrive); UGC folder trash after confirmation | Yes (confirm Drive actions) |
| 7 | Docs, skills, AGENTS.md, PROGRESS.md, full test suite, mock end-to-end | Yes (final report) |

## 9. Open questions

- **Q1** Carousels: static slides only, or keep the Higgsfield animation as an option? (Default: static, animation kept but off.)
- **Q2** Which folder exactly is the approved `references` folder, and are the designer's own outputs in it? (Claude Code inspects and reports.)
- **Q3** "Sie" or "du" for social and YouTube? (Default: "Sie".)
- **Q4** Target YouTube length? (Default: 10–12 minutes.)
- **Q5** Which teleprompter software or app does Roman use?
- **Q6** Storyboard format for Takwa (Markdown, Google Doc, spreadsheet, PDF)? PENDING with the rest of §14.
- **Q7** Opus Pro / Shorts clips depended on finished videos. Are they still wanted once Takwa delivers the edit?
- **Q8** Should Facebook ads carry the AI-disclosure label when Roman appears? (Default: yes, per R6.7.)
- **Q9** Google Drive restructuring details (PENDING).

## 10. Pending sections

- End of §14 (storyboard), from "Clear placeholders s…" onwards.
- Everything after §14 in the brief, including the Google Drive restructuring details.

When these arrive, update R9.10, R9.11, R10 and the open questions, and bump the version.
