# PRD: German content quality, CEO text overlays, YouTube scripts and image-generation reliability

**File:** `GERMAN_CONTENT_AND_IMAGE_WORKFLOW_PRD.md` (repository root)
**Version:** 1.0, 21 Oct 2026
**Owner:** Roman (Branded Genius)
**Implementer:** Claude Code. Codex Desktop is the operator and runs the skills and the Higgsfield plugin.
**Builds on:** PRD v6.1 (`docs/PRD-v6-design-topics-cleanup.md`) and the later fix commits listed in §1.3. Where this PRD is silent, v6.1 and the brand guidelines still apply. The brand guidelines are the top authority.

---

## 0. How to use this PRD

- There are three phases, implemented one after the other. Each phase gets its own Claude Code prompt, written only after the previous phase's real results have been reviewed.
- **Phase 1:** German editorial quality for social media.
- **Phase 2:** YouTube research and script quality.
- **Phase 3:** CEO text overlay and image-generation reliability, including the rule and fallback audit.
- Each phase starts by **inspecting** the files named for it, and reports what it found before editing.
- **Smallest targeted change wins.** Change only what this PRD authorizes. Anything outside that scope is reported as a question, never changed silently.
- **Evidence labels.** The author of this PRD could not open the repository; it lives only on Roman's PC. So every statement about the code carries a label:
  - **[C] Confirmed:** reported by Claude Code in a commit report on this branch.
  - **[P] Planned:** required by an earlier PRD; the implementation has not been confirmed.
  - **[?] Assumption:** to be checked in the repository.

  Claude Code verifies [P] and [?] items during inspection and corrects this PRD's assumptions in its report. It does not invent paths, functions or bugs.

---

## 1. Project overview and existing workflow

### 1.1 What the system does
- It is a Python CLI (`ca`, Typer) plus Codex skills in `.agents/skills/` **[C]**. `AGENTS.md` maps the operator's plain-language phrases to skills, and "ok" is the approval word **[C]**.
- **Branch:** `phase-v5-german-brand`. It is local only and never pushed or merged **[C]**.
- **Audience:** German business decision makers, mostly Mittelstand owners and managers, writing to people in Germany. Brand: Branded Genius (brandedgenius.de).
- **Platforms and categories:**
  - Instagram carousel ("du")
  - Facebook post ("Sie")
  - Facebook ad ("Sie")
  - LinkedIn image post ("Sie")
  - YouTube production documents ("Sie"); there is no finished video. **[P] v6 R1/R7**

### 1.2 Operator flow (Codex)
1. **Topics:** Gmail newsletters (label `Newsletters`) + scraper + typed topics, mixed with the topic pool in `config/topic_pool.json` **[C]**. Rejected, deleted and already-generated topics are excluded **[P]**.
2. **Calendar:** "make calendar next week" / "plan month …", approved per row with "approve …" / "reject …" **[C]**. Each item gets a BG ID.
3. **Copy:** "rewrite copy for <week>" writes the copy and shows it for review. This is a free approval gate before any paid image **[C, commit c2eedff]**.
4. **Images:** "generate approved for <week>" runs the free checks, then one combined dry run with a cost estimate. After "ok", it runs `ca calendar generate --build --authorize <DR-id>` with a parallel pool of 4 **[C, a6f240d]**.
5. **Output:** packages in a platform tree (`outputs/<Platform>/<Type>/<YYYY-MM>/<date>_<BG-ID>_<slug>/` with `final/`, `source/`, `caption_de.txt`, `package.json`). Internal files go under `outputs/_system/`. `ca outputs collect` copies the finals for review **[C]**. Drive upload and the Google Sheet tracker never overwrite manager-owned fields **[C]**.
6. **YouTube:** "plan youtube <month>" → "research BG-…" → source check → "write scripts BG-…" → "select style X for BG-…" **[P] v5 §5**. Folder layout: `YouTube Long-Form/<Topic Name>/research.txt` and `Style A|B|C/{script_de_teleprompter.txt, script_de_en_bilingual.txt, storyboard.txt}` **[P] v6 R7**.

### 1.3 The two image branches (current state)
| | Branch A: CEO (Roman) | Branch B: no CEO |
|---|---|---|
| Generator | Higgsfield Soul 2.0, character "Roman Traenkle 2", run by Codex through the plugin via job files (`outputs/_system/higgsfield/<key>/job.json`, `ca higgsfield record/fail/accept/retry`) **[C]** | OpenRouter `openai/gpt-image-2` **[C]** |
| Text | The app draws headline, body, CTA and chips (composite mode, design kit, Pillow **[?]**) on the empty side **[C]** | Designer mode: the model renders the German text itself; the app adds only the real logo on a sampled dark plate **[C]**. Composite mode is the fallback. |
| Composition | Roman on one outer side (mostly right), with holograms on his side. Rotation over 3 backgrounds × 3 poses × 3 hologram styles × 2 sides **[P] v6 R4** | Approved dark-navy look from `assets/reference/creative/` **[C]** |
| Logo | **None, and no website, on any Roman creative** (brand rule, v6 R4.6) **[P]** | Real logo in the corner; carousels have the logo and website on the last slide only **[P]** |
| Checks | Placement (outer 40%), 48 px clearance from the person and holograms, body 32 px under the headline, calendar icon only on booking CTAs **[C]**. No auto-regeneration; the operator accepts or retries **[C]** | Text read-back (Unicode-normalised, umlauts exact) **[C]**. One regeneration, then composite fallback **[C]**. Network errors are retried twice and don't count as attempts; HTTP 402 stops the batch **[C]**. Every charged attempt is logged in the ledger **[C]** |

Recent changes that this PRD builds on and must not undo:

- **a6f240d:**
  - no reference images in designer mode (`designerImages: false`)
  - a guard against brand and logo words outside the quoted copy
  - the logo plate
  - the Unicode text check
  - network retry and 402 stop
  - cost ledger
  - batch `--parallel`
  - composite layout fixes
  - `ca outputs collect`
- **c2eedff:**
  - `brand/copy_examples.json` (the brand's reference copy verbatim, plus weak examples)
  - `config/copy_rules.json` (audience, reader angles, jargon list, category rules, rubric, CTA list mapped to service IDs)
  - `src/content_automation/content/copy_check.py` (copy check, copy review, approval gate)
  - `content/brief.py` `copyPlan` (reader angle, 3 scored headlines, visual concept)
  - `ca content copy` / `ca calendar copy`
  - a 3-chip row on FB-R1, FA-R1 and LI-R1 in `config/design_directions.json` and `design_render.py`
- **Known stale tests:** `tests/test_direction_build.py` and `tests/test_design_v6.py` still expect reference images in designer mode **[C]**.

### 1.4 What already works and must be preserved
- **Branch B look:** BG-127 passed on the first try and matched the references.
- **Branch A visual direction:** Roman's look, framing, backgrounds and holograms are accepted.
- **Gates:** the approval, dry-run and "ok" gates, and the cost ledger.
- **Data:** topic management, the calendar, the registry and BG IDs.
- **Integrations:** the Gmail label flow, Drive and the tracker with manager-owned fields.
- **Contracts:** output folder names, file names and `package.json`.

---

## 2. Problems and intended outcomes

| ID | Problem (Roman's observation) | Intended outcome |
|---|---|---|
| A | German copy (hooks, headlines, subtitles, bullets, captions, CTAs) is generic, unclear, awkward, repetitive or hard to understand. It often reads like a news summary or an instruction to technicians. Examples: "BROWSER-AGENTEN BRAUCHEN BEDIENBARE SEITEN", "Öffnen Sie die Originalseite vor jeder Veröffentlichung.", CTA "Quelle prüfen". | Each piece carries one meaningful, specific idea for a German business reader, in natural German. It is platform-appropriate and gives a reason to read or act. |
| B | Text overlays on CEO images are weak: hierarchy, spacing, line breaks, balance, contrast and empty gaps. On BG-123 the headline overlapped a hologram, and there was a big gap between headline and body. | Controlled, legible, balanced typography in the existing design language. Roman's composition stays unchanged. |
| C | YouTube scripts lack a clear argument and natural spoken German, and the three styles differ too little. | A clear central argument, spoken German, three genuinely different editorial approaches on the same verified facts, aligned English and useful storyboards. |
| D | Too many image failures, retries and fallbacks, too much time and cost. Run 1: 12 of 14 OpenRouter images failed. Run 2: wordmark, logo corner, umlaut, ReadError and 402 failures, 90–200 s per image, about $0.21 per image. | Fewer unnecessary attempts and lower cost per accepted image. The essential safeguards stay. Causes are evidenced, not assumed. |

**Already partly addressed, to be measured rather than re-fixed:**
- Problem A: commit c2eedff.
- Problem D: commit a6f240d.

Phases 1 and 3 start by checking what those commits already cover.

---

## 3. Strict scope boundaries and non-goals

### 3.1 Must not change without Roman's explicit authorization
1. **Visual design:** existing designs, templates, layouts, colours, fonts and brand identity. This includes `config/design_directions.json` variants and the design kit look.
2. **Higgsfield:** the trained Soul 2.0 character and the identity-generation workflow (job files, plugin steps, prompts, rotation). The only exception is a minimal fix for a specific failure that Phase 3 evidences, explicitly listed and approved.
3. **OpenRouter:** the `openai/gpt-image-2` model selection. Successful designer prompts and generation settings, including size and quality, stay unless Phase 3 evidence names a specific cause and Roman approves the change.
4. **Topic sources:** the Gmail integration and label behaviour, topic management and the weekly or monthly calendar logic.
5. **Manual data:** approval states, manager-edited content, scheduling data and manager-owned tracker fields.
6. **Output contracts:** output formats, file names and folder structures, including the YouTube tree and its file names.
7. **Other areas:** other platforms, integrations and modules, and publishing behaviour or external services.
8. **Providers:** API providers, models, subscriptions, and new paid services or APIs. Ask first.
9. **Code base:** no general refactors, renames of unrelated functions, file reorganisation, dependency upgrades or architecture changes.

### 3.2 Non-goals
- No new visual design system, and no new aesthetic.
- No replacement of the CEO model or of the image models.
- No multi-agent orchestration, and no new observability infrastructure.
- No long or expensive test phase, benchmark or paid test generations. Roman judges the visual quality himself.

### 3.3 Brand rules that override this PRD
- **No logo on Roman images.** The brief lists "logo placement" for CEO overlays, but brand rule v6 R4.6 says Roman creatives carry **no logo and no website**. Phase 3 keeps that rule. Logo work applies only where the brand allows a logo (Branch B and the last carousel slide). Open question Q1 asks Roman to confirm.
- **No unverified claims.** Never claim a service, result, client, price or statistic that isn't verified.
- **AI disclosure.** The disclosure field and label on Roman images stay (EU AI Act Art. 50).

---

## 4. Research findings (what we take, what we leave)

_Read on 21 Oct 2026. Only ideas are adopted. No repository is installed or copied._

| # | Resource | Status / licence | Adopt (ideas only) | Leave |
|---|---|---|---|---|
| 1 | [social-media-skills/skills](https://github.com/social-media-skills/skills) | MIT, 160★, 10 commits; plain SKILL.md + `references/` + `evals/evals.json` | (a) A brand-profile done-check: "a stranger could write an on-voice post"; a concrete lexicon and banned words instead of adjectives; 3–5 real example posts. Our `copy_examples.json` already plays this role. (b) **Small evals per skill:** input, then a list of expectations that must all hold, including negative cases (refuse an invented customer story, refuse engagement bait). (c) **LinkedIn:** the hook in the first ~140 characters before "…mehr anzeigen", 1–2-line paragraphs, at most one soft CTA, close on a real question, 3–5 hashtags. (d) **Style pass:** one "only-us" element per piece (a real number, case or opinion); never invent anecdotes; read-aloud test. (e) **Overlays:** at most 2 fonts, break lines where meaning holds, never mid-word; "shorter → bigger". (f) **Video:** runtime math and a read-aloud stopwatch pass; no two "talking head" scenes in a row in the storyboard. | WoopSocial publishing and routing; unattributed statistics; US-centric hooks; long cross-referencing skills (too much context) |
| 2 | [exiao copywriting SKILL.md](https://github.com/exiao/skills/blob/main/writing/copywriting/SKILL.md) | **No licence file:** ideas only, no text copied | (a) A brief intake: one primary action, the ideal reader, the problem in the reader's own words, objections, the differentiator, the outcome, proof points and prior knowledge. This feeds P1-R1. (b) "Emotional promise + rational explanation". (c) Every "wir" that can be "Sie/du" becomes "Sie/du"; no superlatives; at most the 3 strongest points. (d) **CTA** = action verb + what the reader gets; no "Mehr erfahren" as the default. (e) 2–3 alternatives with a one-line rationale. | Landing-page and app-store sections; US direct-response tone and rhetorical-question openers as a default |
| 3 | [servicestandard.gov.de: Verständlich schreiben](https://servicestandard.gov.de/handbuch/anleitungen/verstaendlich-schreiben-mit-einfacher-sprache/) | Federal guidance, updated 02.09.2025 | Lintable rules: subject–verb–object order; active voice; verbs instead of Nominalstil ("Die Antragstellung erfolgt" → "Sie stellen den Antrag"); cut filler words and unnecessary modal verbs; question every adjective; prefer the familiar word; write out abbreviations and symbols; the same name for the same thing, with no switch between registers; **avoid hyphenation at line ends**. | The 12-word cap as a hard rule is too strict for business posts. Use it as a warning (~15–20 words for captions). It is a hard target only for overlay headlines. |
| 4 | [ghedo44/postcanvas](https://github.com/ghedo44/postcanvas) | MIT; Python, Pillow 12, Pydantic 2; v1.0.1 (Jul 2026); 1 maintainer, 1★ | **Port the algorithms, don't add the dependency:** (a) shrink-to-fit by binary search between max and min font size, then an overflow error; (b) balanced line wrap that minimises squared slack, with the last line free; (c) widow control (minimum words on the last line); (d) WCAG relative-luminance contrast; (e) a per-check policy of ignore, warn or error; (f) render returns a list of issues with code, severity and message. | As a dependency: young, needs Pillow 12 (our pin unknown). Its contrast test uses a declared solid background, not photo pixels, and it splits long words without a hyphen (bad for German compounds). |
| 5 | [OpenAI Skills guide](https://developers.openai.com/api/docs/guides/tools-skills) | Official | `SKILL.md` stays short and procedural, with a sharp "what and when" description; details go in `references/`; repeatable actions become CLI calls (`scripts/` or our `ca` commands), not prose; writes need approval. | n/a |
| 6 | [deepagents social-media skill](https://github.com/langchain-ai/deepagents/blob/main/examples/content-builder-agent/skills/social-media/SKILL.md) | MIT (LangChain), example code | Research first: the writer reads a research note before drafting. This matches our editorial brief (proof field) and the YouTube research.txt. Keep a short quality checklist in the skill. | Its LinkedIn length figures (outdated), "no text in image" (contradicts our overlays), emoji thread formats |
| 7 | [Codex cookbook: iterating workflows](https://developers.openai.com/cookbook/examples/codex/iterating-development-workflows-with-codex) | Official, Aug 2026 | Small, independently verifiable scope; observable acceptance criteria; record exact commands and pass/fail; "do not infer completion from the existence of code"; turn verified failures into regression tests; tighten an existing skill before creating another; stop after each phase. | Process for its own sake |
| + | pyphen (German hyphenation) | Pure Python; GPL/LGPL/MPL tri-licence; the German dictionary is LGPL 2+ | Only if Phase 3 needs it. Order: shrink → balanced wrap → soft hyphens (U+00AD) written in the copy → dictionary hyphenation only for a single body-text token that still overflows → otherwise flag the copy for shortening. Never in headlines. | Adding it to Phase 1 or 2 |
| + | Spoken German (*Schreiben fürs Hören*, La Roche/Buchholz; radio guides) | Book (paid); free summaries are of low authority | One thought per sentence; no nested clauses; active voice, no Nominalstil; keep both parts of the verb close together (Verbklammer); most important point first; only the numbers that are needed; repeat names instead of switching synonyms. | No free official German standard exists. The pace (~130 wpm is an English figure) should be calibrated on Roman's real takes. |

**Conclusion:** adopt rules and algorithms, and install nothing in Phases 1 and 2. The only possible new dependency is pyphen in Phase 3, and only with Roman's approval.

---

## 5. Proposed skill structure and responsibilities

The goal is to keep **one source of writing rules** and to reuse the existing data files, not to duplicate them.

```
.agents/skills/
  german-editorial/            NEW (Phase 1); used by every skill that writes German text
    SKILL.md                   short: when to use, the procedure (brief → draft → self-review → check), links below
    references/
      editorial-brief.md       the 6-question brief per piece (audience, problem, one idea, proof, objection, action)
      german-style.md          clarity rules for business German (Phase 1) + a spoken-German section (Phase 2)
      platforms.md             per-category rules (IG carousel, FB post, FB ad, LinkedIn, image text, captions)
      review-rubric.md         scoring rubric + "reject or rewrite" triggers
  text-overlay/                NEW (Phase 3); Roman/composite typography review and preview procedure
    SKILL.md
    references/overlay-rules.md
  <existing skills>            make-calendar, the content/copy skill, YouTube skills: ONLY add a pointer to german-editorial and remove rules that duplicate it
```

**Single source of data:**
- Rules that code enforces stay in config: `config/copy_rules.json`, `brand/copy_examples.json` and the design kit config. The skill's Markdown files explain them for the writer (Codex) and point to them. They do not restate numbers that code enforces; they name the config key instead.
- If an existing skill already holds writing rules, Claude Code moves them into `german-editorial` and leaves a pointer. The skill name and folder follow the existing naming convention **[?]**.
- **Who writes:** Codex writes all copy and scripts inside the skills. That adds no paid API, as today **[?]**: confirm whether any `ca` command calls a text model, and through which provider. `ca` code holds the deterministic, free checks.

---

## 6. Phase 1: German editorial quality across social media

### 6.1 Objective
Improve the German copy of every social category, both the image text and the caption: hooks, headlines, sublines, chips or bullets, CTAs, captions and hashtags. Build on c2eedff, don't replace it.

### 6.2 Inspection first (report before editing)
1. Where German text is created:
   - each skill and template that fills the brief (`brief.template.json` **[?]**, `content/brief.py` `copyPlan` **[C]**)
   - caption generation **[?]**
   - carousel slide copy **[?]**
   - the German quality check before the dry run, with its banned phrases **[P] v6 R1**
   - `copy_check.py` and `copy_rules.json` **[C]**
2. What text the writer receives as input: the newsletter excerpt, the topic pool entry and the service list. The PRD assumes copy quality suffers because the source text is passed through with little transformation **[?]**. Confirm or refute this.
3. Where the same text is reused across platforms, for example one headline or caption used for LinkedIn, Facebook and Instagram **[?]**.
4. Whether captions get the same treatment as image text. The PRD assumes c2eedff focused on image text **[?]**.
5. Layout limits per variant (characters or lines per headline, body and chip), and where they are enforced (the fit-or-fail dry run **[P]**).
6. Output of the inspection: a short findings list, with file:function and a one-line issue each.

### 6.3 Requirements
- **P1-R1 Editorial brief before writing.** Each item gets a short brief before any copy is written:
  - **audience:** which German business reader
  - **problem or situation:** in the reader's words
  - **one core idea:** one sentence
  - **proof:** a source fact with its source, or a verified service fact
  - **likely objection:** the reader's doubt
  - **desired action**

  Store it with the existing `copyPlan` (extend it, don't replace it). The c2eedff "reader angle" is part of this brief.
- **P1-R2 German style rules** (`german-style.md`). These are business German, not Einfache Sprache:
  - **Sentences:** short and active, one statement each. Captions mostly under ~20 words per sentence.
  - **Verbs:** use verbs instead of noun chains (Nominalstil); "prüfen" instead of "die Durchführung einer Prüfung".
  - **Words:** concrete nouns and numbers instead of buzzwords. One consistent term per concept. No unexplained jargon or anglicisms where a common German word exists; established terms like "KI" or "Chatbot" are fine.
  - **Correctness:** correct umlauts and ß, German quotation marks and dashes as the brand uses them **[?]**, and correct "Sie" or "du" per category.
  - **No filler:** no empty marketing phrases ("revolutionär", "im digitalen Zeitalter", "Game-Changer", "nahtlos", and so on). Extend the existing banned list rather than creating a new one.
- **P1-R3 Hooks and headlines.**
  - Use the pattern library and examples from c2eedff: contrast pair, benefit pair, reader question and bold future statement.
  - **Truth:** a hook must be true and covered by the brief's proof. No clickbait, no fear without a way out, no implied client results.
  - **Variety:** no instruction-style headlines aimed at technicians, and no headline that is just a news title. The same hook pattern may not be used more than twice in one week.
  - **Reader focus:** write "Sie/du" instead of "wir" where possible. Include one specific element per piece: a real number, case or opinion from the proof.
  - **CTA:** action verb + what the reader gets; "Mehr erfahren" only as a soft CTA for insight posts.
- **P1-R4 Platform differentiation** (`platforms.md`). The same topic gets platform-specific copy:
  - **LinkedIn:** the hook within the first ~140 characters (before "…mehr anzeigen"), 1–2-line paragraphs, a business takeaway, a soft CTA and 3–5 hashtags. The existing 120–250-word range stays **[C v1]**.
  - **Facebook post:** conversational "Sie", a shorter caption, and a question or soft CTA.
  - **Facebook ad:** offer-led, a primary text with the benefit, and a CTA from the CTA list.
  - **Instagram carousel:** "du", a cover hook, one idea per slide, a last slide with engagement, and caption hashtags.
  - **Similarity check:** a free check flags captions or headlines for the same topic across platforms that are near-identical. Reuse the existing near-duplicate or similarity helper if one exists **[P] v6 R6**.
- **P1-R5 Claims check (free, deterministic).** These elements must appear in the brief's proof or source fields, or in the verified services list:
  - numbers, percentages, euro amounts and years
  - named organisations
  - "Studie"/"laut" statements

  If one doesn't, the item fails with "unbelegte Aussage" and is rewritten once. Statements about Branded Genius services must match the verified services list.
- **P1-R6 Review rubric and one rewrite** (`review-rubric.md`, extending the c2eedff rubric). Codex scores each piece on:
  1. clear single idea
  2. relevance for the reader
  3. specificity
  4. natural German
  5. hook strength
  6. truth or proof
  7. CTA fit
  8. platform fit

  Anything below the threshold gets one rewrite. If it still fails, the copy review shows it flagged, and nothing is silently dropped.
- **P1-R7 Deterministic check extensions** (in `copy_check.py`; free, no network). Add only what is missing:
  - a sentence-length warning
  - a noun-chain heuristic (a density of -ung/-heit/-keit/-tion nouns per sentence, as a warning)
  - the filler and anglicism list
  - "Sie"/"du" consistency within an item
  - layout fit against the existing variant limits
  - hook-pattern repetition per week
  - P1-R4 similarity
  - P1-R5 claims

  Warnings are shown in the copy review. Only clear failures block the item.
- **P1-R8 Schema compatibility.** Field names and lengths downstream (designer prompt strings, composite renderer, `caption_de.txt`, `package.json`, tracker columns) stay compatible. New fields are additive and optional for old briefs.
- **P1-R9 Skill wiring.** Every skill that writes social copy points to `german-editorial`. `AGENTS.md` changes only where the flow changed. `german-editorial` gets a small `evals.json` (5–8 cases incl. negatives: invented customer story, unsupported statistic, technician-style headline, wrong Sie/du). Codex can run it on request; it is not a test suite.

### 6.4 Boundaries
- No changes to:
  - image generation, design or layout config, or the designer prompt
  - the calendar or topic logic
  - YouTube files (Phase 2)
- No new provider or paid model.
- Don't regenerate or rewrite past packages.

### 6.5 Dependencies
- c2eedff files (`copy_rules.json`, `copy_examples.json`, `copy_check.py`, `copyPlan`).
- The verified services list and the brand guidelines.

### 6.6 Acceptance criteria
1. A free copy run for the current test week (or 5 mock items covering all four categories) shows, for each item, the brief, the final copy and the rubric scores. Roman judges whether it is more specific, coherent and natural. Claude Code does not claim it is.
2. No two platforms share an identical headline or caption for the same topic. The similarity check passes or flags.
3. An unsupported number or claim in a test input is caught and rewritten or flagged.
4. Image copy stays within the existing layout limits: the fit check passes.
5. ruff and mypy pass on the changed files. Existing copy-check tests pass, and at most 3 small new tests cover the new checks. No image calls, no network.

---

## 7. Phase 2: YouTube research and script quality

### 7.1 Objective
Better research, a clear argument, spoken German, three genuinely different styles, an aligned English translation and useful storyboards. Phase 2 reuses `german-editorial` and adds a spoken-German section to it, not a second rulebook.

### 7.2 Inspection first
- The commands, skills and files for:
  - planning, research and the source check (`ca youtube check-sources` **[P] v5 R9.5**)
  - script writing, the bilingual file and the storyboard
- Check against v5 R9.4–R9.10 and v6 R7, which were planned, and report what is actually implemented.
- **Open points to settle by inspection:**
  - The deliverables, per topic or per style. v6 R7 says research.txt per topic and a storyboard per style. Roman's brief mentions a reference document per style, and v5 said one storyboard for the selected style. Report what the code does today. **Preserve that; don't change it** (Q2).
  - The style definitions in use. v5 R9.7 planned: A Investigativ, B Direkte Warnung, C Menschlich.

### 7.3 Requirements
- **P2-R1 Source quality.**
  - **Prefer primary and reputable sources.** For example: official or government bodies (BSI, Destatis, the EU), company statements, and established German media (tagesschau, heise, Handelsblatt, FAZ, SZ, Zeit, t3n, netzpolitik.org). Studies are named with their publisher (for example Bitkom).
  - **Newsletters** count as leads. Cite the original source where possible.
  - **Social posts** only illustrate, with clear attribution, and are never sole proof of a fact.
- **P2-R2 Fact IDs.**
  - **In research.txt:** each verified fact gets an ID ([F1], [F2] …) with publisher, title, date, URL and the supporting quote or paraphrase. The existing sections stay: Verified facts / Interpretation / Proposed solutions, and the verification block.
  - **In the storyboard:** the source column uses these IDs.
  - **Not in the teleprompter file,** which stays free of citations.
  - **Format:** additive; it changes no file names.
- **P2-R3 Argument outline before drafting.** Add it as a section in research.txt; no new file unless Roman approves. It contains:
  - one central thesis
  - 3–4 supporting points, each with fact IDs
  - what it means for German businesses or people
  - the practical takeaway
  - per style, the editorial angle and the opening type

  All three scripts are drafted from this outline.
- **P2-R4 Three distinct styles.**
  - **Differences:** the styles keep the same facts and thesis, but differ in opening type, structure, perspective and tone. Keep the existing style names and definitions if they exist; otherwise use v5 R9.7.
  - **Difference check:** extend the existing check **[P]**. It flags pairs with the same opening type, the same order of sections, or high sentence overlap.
  - **Style C** keeps illustrative scenarios labelled ("Stellen Sie sich vor …").
- **P2-R5 Spoken German** (a section in `german-style.md`):
  - **Sentences:** 8–15 words, with the verb early and few nested clauses. Spoken connectors ("Und genau hier …", "Das heißt …") without filler.
  - **Speakable text:** numbers and abbreviations written as spoken ("21 Prozent", "KI"), no brackets, slashes or symbols.
  - **Address:** "Sie".
  - **Honesty:** Roman never claims experiences he didn't have.
  - **Speech:** keep both parts of the verb close together (Verbklammer), the most important point first, only the numbers that are needed, and names repeated rather than swapped for synonyms.
  - **Length:** the length target follows the existing setting. The words-per-minute figure is configurable; the default is ~130 until calibrated on Roman's real recordings.
  - **Storyboard:** no two "Roman on camera" scenes in a row without a cutaway.
- **P2-R6 Bilingual alignment.**
  - **Source:** the bilingual file is generated from the final teleprompter text.
  - **German side:** the German is identical, paragraph for paragraph. Keep or extend the existing check.
  - **English side:** faithful and complete, with consistent terms. Not summarised and not localised. Plus a free check that the number of German and English blocks is equal.
- **P2-R7 Storyboard usefulness.** Keep the existing fields: scene, time, German line, English, visual direction, graphics, exact German on-screen text with English, sources, transitions. Additions:
  - script paragraph numbers per scene
  - fact IDs for every factual visual or on-screen claim
  - a b-roll or screen-capture suggestion per scene in English for the editor
  - no unverifiable visuals presented as real
- **P2-R8 Re-runs** keep the existing versioning (no silent overwrite).

### 7.4 Boundaries
- Don't change file names, folder layout, the number of deliverables, topic discovery genres, the selection flow, or the Drive and tracker links.
- No video generation and no new paid services.

### 7.5 Acceptance criteria
1. One topic, either an existing one or a mock, regenerated for free with the following results:
   - the outline exists
   - each script follows its own style
   - every factual sentence maps to a fact ID in research.txt (the source check report)
   - the teleprompter file has no headings, English or citations
   - the bilingual German is identical, and the block counts are equal
   - the storyboard references fact IDs and paragraphs
2. The style difference check passes for the three styles.
3. Roman reads one script aloud and judges how natural it sounds. Claude Code does not claim this.
4. ruff and mypy pass on the changed files, plus the existing YouTube tests and at most 3 small new tests.

---

## 8. Phase 3: CEO text overlay and image-generation reliability

### 8.1 Objective
- **Typography:** better typography on Roman images (Branch A composite) inside the existing design language.
- **Reliability:** fewer unnecessary failures, retries, fallbacks, time and cost across both branches.
- **Branch B:** stays visually as it is (gpt-image-2, designer prompt and settings). Only text-accuracy handling and evidenced reliability causes are in scope.

### 8.2 Part 3a: rule and fallback audit (before any change)
Claude Code inventories every rule or condition that can do any of these:
- reject an image
- retry or regenerate it
- switch to the fallback or composite mode
- delay a job
- stop a batch
- add a model call (the text read-back included)

Scope: both branches, prompt guards, design checks, the Higgsfield placement check, network handling and the batch logic.

**Inventory table** (one row per rule, kept short):

| Rule / condition | File:function or config key | Purpose | Trigger | Action | Retry / fallback / reject / delay / extra call? | Evidence it is needed | Recommendation (keep / simplify / combine / change / remove) | Expected effect (quality, reliability, time, cost) |
|---|---|---|---|---|---|---|---|---|

**Evidence sources:** existing data only, no new infrastructure:
- the logs (`core/log.py` output **[C]**)
- the cost ledger **[C]**
- the registry and job files
- the run outputs of the W44 runs

**Statistics per failure cause:** count attempts, failures, the seconds each took, and cost. Group failures by cause:
- prompt or provider rejection
- validation failure (with the rule name)
- network or provider error (incl. 429 and 5xx)
- timeout
- malformed response
- plugin failure (Higgsfield)
- code error

Where the evidence is thin, it says so.

**Known candidates to examine.** These are observations, not conclusions:
1. **Text read-back:** exact match vs readable variants. What fails, and is each mismatch real?
2. **Designer-mode failure:** regeneration vs composite fallback. Could the composite reuse the already generated scene (no second paid call), as v6 planned?
3. **Logo plate:** is the remaining logo or wordmark failure rate zero since a6f240d?
4. **Image size and quality:**
   - observed cost about $0.21 per image, consistent with gpt-image-2 "high" quality (public prices, Oct 2026: about $0.006 low, $0.053 medium, $0.211 high at 1024²)
   - report the setting actually used
   - **changing it needs Roman's approval**
5. **Per-image time** (90–200 s): provider latency vs our waiting or polling, and the parallel pool's effect.
6. **Roman placement check:** rejection rate, and whether a crop or shift resolves it more often than a regeneration.
7. **Duplicated or overlapping checks** that run the same test twice, and checks that run on outputs that cannot fail them.

### 8.3 Part 3b: CEO text overlay (Branch A composite)
**Inspection:**
- the composite renderer (`design_render.py` **[C]**) and the design-kit config (`config/design_directions.json` **[C]**)
- the font setup (Jost, Futura if present **[P]**)
- how the safe area is derived from Roman's position and the holograms
- line breaking, size fitting, contrast and the check order
- the BG-123 output as the reference case

**Method:** deterministic rendering by the app stays the method for exact German text. The image model never renders text on Roman images.

**Requirements:**
- **P3-R1 Type scale:** headline, body, chips and CTA sizes, weights and line heights, defined as ratios of the canvas in the existing design-kit config. Use the existing values where they exist; only fill gaps. Minimum sizes at 1080 px width keep text readable on a phone (for example body ≥ 28 px, as a configurable floor).
- **P3-R2 Fit:** fit text into the safe box by binary search on the font size with balanced wrapping (algorithm as in postcanvas, ported, not installed). Use the floor values above; if they are not met, fail with "text too long", and Phase 1 shortens the copy. The fit runs before the render, so it never clips or overflows.
- **P3-R3 German line breaks:**
  - break at word and phrase boundaries
  - no one-word last line (no orphan or widow) in headlines
  - don't split article and noun, preposition and object, or number and unit
  - avoid hyphenation at line ends. In order: shrink, then balanced wrap, then soft hyphens written in the copy, then dictionary hyphenation (pyphen, needs approval) only for one body-text word that still overflows. Never in headlines; otherwise flag the copy for shortening
  - keep "KI-…" compounds together
  - balanced line lengths for multi-line headlines
- **P3-R4 Safe area:** the text box is the empty side minus margins, minus the person box and the hologram boxes plus 48 px clearance **[C]**. Roman's position and the image are never changed by the overlay.
- **P3-R5 Hierarchy and spacing:**
  - headline → body → chips → CTA, with spacing from the design kit (body 32 px under the headline **[C]**)
  - one left alignment axis
  - the text block's vertical position optically balanced against Roman's head height, instead of a fixed top
  - no large empty gaps
- **P3-R6 Contrast:** measure WCAG contrast against the actual background pixels under each text box, for example against the 90th-percentile luminance, not an assumed solid colour. The existing thresholds stay: 4.5 for body, 3.0 for headlines. If it fails, apply the existing panel or scrim from the design kit, never a new style.
- **P3-R7 CTA and chips** only where the variant has them. The icon follows the meaning **[C]**. No logo or website on Roman creatives (§3.3).
- **P3-R8 Free preview:** a command or option that re-renders the overlay on an existing image (an accepted Higgsfield attempt), with no generation. If one exists, reuse it **[?]**. It also renders a contact sheet with short, medium and maximum copy for each Roman variant.
- **P3-R9 Text-overlay skill:** `text-overlay/SKILL.md` gives Codex:
  - the review checklist: readable at phone size, no overlap, balanced, German breaks natural, exact text
  - how to run the free preview
  - what to do on failure: shorten the copy (Phase 1 rules) before any regeneration

### 8.4 Part 3c: targeted reliability changes
- Implement only rows from the 3a inventory whose recommendation is backed by evidence. Anything touching the model, quality, size, prompts or the Higgsfield workflow is listed for Roman's approval, not changed.
- **Preferred kinds of change:**
  - cheaper correction before regeneration: re-render text in composite mode on the existing scene, or crop or shift
  - fewer duplicate checks
  - clear stop conditions
  - no retry for causes a retry cannot fix
- **Keep:**
  - brand compliance (no third-party or model-drawn logos, no logo on Roman images)
  - exact text
  - valid files and correct dimensions and aspect ratios
  - the cost ledger and gates
  - the 402 stop and network retries
- Fix the two stale tests (§1.3) as part of this phase, because Phase 3 touches that code.

### 8.5 Boundaries
No changes to:
- the gpt-image-2 selection
- the designer prompt, unless an audited failure needs a minimal, approved change
- the Higgsfield character or job flow, beyond an approved minimal fix
- the layouts and colours
- the output contracts

Also: no paid generation during the implementation.

### 8.6 Acceptance criteria
1. The audit table is delivered with evidence counts and an explicit statement of any uncertainty.
2. The free preview of BG-123 (accepted attempt) and the contact sheet show:
   - no overlap or clipping
   - natural German breaks
   - contrast above the thresholds
   - Roman unchanged

   Roman judges the look.
3. Rendered text equals the approved copy exactly (string comparison of the render input; no OCR needed for composite).
4. Each implemented reliability change names its audit row and its expected effect. Nothing essential (§8.4 Keep) is removed.
5. The checks pass:
   - ruff and mypy on the changed files
   - the updated design tests
   - the rejected-fixture tests (`tests/fixtures/rejected/` still fail for the right reasons)

   No paid calls.

---

## 9. Risks and dependencies

| Risk | Mitigation |
|---|---|
| The PRD's assumptions about the code are wrong (no repository access when written) | Inspection first in every phase. Claude Code corrects the assumptions in its report. |
| Writing rules end up in two places and conflict | A single `german-editorial` skill. Config holds the enforced numbers; skills point to them. |
| Stricter copy checks cause more blocked items | Most new checks are warnings. Blocking only for: unsupported claims, wrong "Sie"/"du", layout overflow, banned phrases. |
| Shorter copy for the layout loses meaning | The rubric scores a "single clear idea" first. The caption carries the detail. |
| Codex self-review is lenient | Roman's copy approval stays the final gate (c2eedff). |
| Reliability changes lower quality | Evidence-based only, safeguards kept. Roman reviews the first real run. |
| Quality or size changes for gpt-image-2 alter the look | Not changed without Roman's approval; at most proposed with evidence. |
| Missing fonts (Futura) | Use the existing fallback font (Jost); a font change is out of scope. |
| Hyphenation library licence | Only if needed, with a permissive or LGPL-compatible licence and no network. Otherwise no hyphenation in headlines. |

**External dependencies:** OpenRouter credits, the Higgsfield plugin in Codex, the Gmail and Drive tokens. None of them is changed by this PRD.

---

## 10. Lightweight verification (all phases)

- **Linting:** ruff and mypy on the changed files only.
- **Tests:** the existing tests of the touched modules, plus at most 3 small new tests per phase for new deterministic checks.
- **Examples:** a free mock or dry run on 5 items (Phase 1), 1 topic (Phase 2) and existing images (Phase 3).
- **No paid calls:** no paid or external calls, no Drive or tracker writes and no publishing in any check.
- **Honest reports:** the report says exactly what was run and what wasn't. "Verified" only for what was actually checked.

---

## 11. Deliverables per phase

| Phase | Deliverables |
|---|---|
| 1 | Inspection findings. The `german-editorial` skill (SKILL.md + 4 references). Extended `copyPlan` brief. Extended `copy_check.py` checks and `copy_rules.json` entries. Skill pointers and minimal `AGENTS.md` changes. Before/after copy for 5 items (free). Short report. One commit. |
| 2 | Inspection findings (what is implemented vs v5/v6). Fact IDs and the argument outline in research.txt. Spoken-German section in `german-style.md`. Style definitions and difference check. Alignment checks. Storyboard additions. One free example topic. Short report. One commit. |
| 3 | The audit table (3a). Overlay improvements, free preview and contact sheet. The `text-overlay` skill. Evidence-based reliability changes. A list of changes needing Roman's approval. Fixed stale tests. Short report. One commit. |

**Commits:** one per phase on `phase-v5-german-brand`. Never push or merge.

---

## 12. What must not change without authorization (summary)

- **Look:** designs, templates, layouts, colours, fonts and brand identity.
- **Higgsfield:** the Soul 2.0 CEO character and the identity workflow.
- **OpenRouter:** `openai/gpt-image-2`, its prompts and its settings (quality and size included).
- **Topics and data:** the Gmail label flow, topic management, the calendar, approvals, manager-owned fields and scheduling data.
- **Contracts:** output formats, file names and folders (the YouTube tree included).
- **Everything else:** other modules, platforms, integrations, publishing and external services. No new providers, models, subscriptions or paid services. No refactors or dependency upgrades.

---

## 13. Open questions (answer before or during the phases)

| ID | Question | Default until answered |
|---|---|---|
| Q1 | The brief asks for logo placement on CEO images, but the brand rule says no logo or website on Roman creatives. Keep "no logo"? | Keep "no logo" |
| Q2 | YouTube: should the reference/sources document be per topic (research.txt, as planned) or per style, and should there be one storyboard per style or only for the selected style? | Keep whatever the code does today |
| Q3 | The gpt-image-2 quality setting: switch from high to medium if the audit confirms "high"? (About 4x cheaper; needs your OK.) | No change |
| Q4 | Futura font files for overlays: available? | Jost |
| Q5 | YouTube script length target | Existing setting (v5 default 10–12 min) |
