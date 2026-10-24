---
name: make-youtube
description: Branded Genius YouTube scripts in two pipelines (PRD v6 weekly): "make short video script" (about 1 min, HOST + ROMAN dialogue, one style) and "make long video script" (about 12 min, Roman only, 3 styles); per week 2 long-form and 4 short-form German topics from real incidents, a verified research TXT per topic, three script styles (A investigativ, B direkte Warnung, C menschlich) as German teleprompter files plus German-English scripts, and a storyboard for each style for the editing agency. Roman records, the agency edits; nothing renders a video. Use for "plan youtube November", "research BG-x", "check sources BG-x", "write scripts BG-x", "generate storyboards BG-x", "select style B for BG-x", "upload youtube BG-x", "youtube status". Separate from the social skills; shares only BG IDs, approval, storage and the tracker.
---

# Make YouTube (research and production planning)

Everything here is free: `ca youtube` makes folders, templates and checks; you research and
write. No paid model is called by `ca`. Deliverables are scripts only (no video, voice or host).

Two independent pipelines (config/youtube.json `formats`: own prompt, word target, presenter,
folder and Drive folder):

| | Short-form ("make short video script") | Long-form ("make long video script") |
|---|---|---|
| Plan | `ca youtube plan <YYYY-MM> --format short` | `ca youtube plan <YYYY-MM> --format long` |
| Length | about 1 min, 140-160 words | about 12 min, 1,600-1,800 words |
| Presenter | `HOST:` (AI host, asks) and `ROMAN:` (analyses), every paragraph labelled | Roman only, no labels |
| Prompt | `references/short-form-prompt.md` | `references/long-form-prompt.md` (5-10 topics, hook → segments → conclusion, balanced) |
| Folder | `outputs/YouTube Short-Form/<English Topic Title> <YYYY-MM-DD>/` with the 3 files directly | `outputs/YouTube Long-Form/<English Topic Title> <YYYY-MM-DD>/Style A|B|C/`, 3 files each |

The 3 files: `script-en-de.md` (English + German, per paragraph), `teleprompter-de.txt` (German;
in short-form Roman's lines are the `ROMAN:` ones), `storyboard.md` (references inline).
`research.txt` stays in the topic folder as your local working file; it is never uploaded and
there is no separate sources file. The BG ID, `titleEn` and the briefs are in
`outputs/_system/youtube/`. A re-run never overwrites: a changed file is written as `<name>_v2`.

## Rules (always)

- **Writing rules:** the german-editorial skill, `references/german-style.md` (including
  "Gesprochenes Deutsch" for the teleprompter) and `references/review-rubric.md`. Everything the
  audience hears or sees is German; internal notes and the agency's explanations may be English.
- Real incidents, current developments and documented problems first; relevant to Germany; no
  exaggerated fear or clickbait.
- **Never invent** a news story, statistic, URL, article title, quotation or event. Write only
  what you read on a page you opened. Unknown → leave it out or write "unknown".
- **Source tiers** (P2-R1): 1. primary and official sources (BSI, Destatis, the EU, police,
  courts, ministries, company statements) and studies named with their publisher (for example
  Bitkom); 2. established German media (tagesschau, heise, Handelsblatt, FAZ, SZ, Zeit, t3n,
  netzpolitik.org); 3. international primary sources as a supplement. Newsletters are leads only:
  open and cite the original source. A social post only illustrates, with clear attribution, and
  is never the sole proof of a fact. `config/sources_de.json` is a starting list, not a filter.
- Never imply Roman experienced or witnessed something he did not. Style C scenarios are
  illustrative and say so ("Stellen Sie sich vor …").
- Stop for the user's words where a step says so; never approve or override for the user.

## Steps

1. **"make short video script"** / **"make long video script"** / "plan youtube November" →
   research real German news with web access (German sources first). Short-form: one negative German topic
   per script (a global story only when it clearly hits Germany) (negative tech developments in Germany, AI risks, harm to people and jobs, AI
   limits and controversies; never positive news), built as negative hook → one sourced stat →
   2-3 points → solution (`references/short-form-prompt.md`). Long-form: 5-10 topics per
   script, risks and positive developments balanced. No topic twice in the week or month. Then
   `uv run ca youtube plan 2026-11 --format short|long --topic "<German topic>" --title-en
   "<English title, at most about 6 words>" …` (one pair each; the month holds 16 short-form and
   8 long-form). It creates Proposed items with BG IDs and folders named
   "<English Topic Title> <YYYY-MM-DD>". Show the list with one line of why each matters and
   its first sources; **stop** for "approve BG-x" / "reject BG-x <reason>" (manage-items:
   `uv run ca item approve|reject …`).
2. **"research BG-x"** → `uv run ca youtube research BG-x` writes `research.txt`. Fill
   every section from the pages you opened: sources as `[S1] Title | Publisher | YYYY-MM-DD`
   (section 5) and `[S1] https://full-url` (section 6); facts with a fact ID as
   `- [F1] <fact exactly as the source states it> [S1] | Beleg: "<the supporting words from the
   page>"` (the Beleg is optional: quoted, the check finds it word for word, also on an English
   page; unquoted, it is a paraphrase), the same fact keeps its ID in sections 7 and 11a;
   quotations as `- "<exact words>" — <name, role> [S2]` (or "none"); sections 11a verified
   facts, 11b interpretation, 11c proposed solutions; section 12 the **argument outline** the
   three scripts are drafted from: `Thesis:`, `Point 1-4:` each with its `[F#]`, `Meaning:` (for
   German businesses or people), `Takeaway:` and per style `Style A: angle: … | opening: <type>
   | order: 1, 2, 3` (opening types: `openingTypes` in config/youtube.json; every style a
   different opening and order). Run the command again until it says "complete".
3. **"check sources BG-x"** → `uv run ca youtube check-sources BG-x` (opens each URL; free).
   It writes status, final URL, title and date, checks every quotation in the page text and
   reports every fact ID with its source and status (a quoted Beleg must be in the page), into
   the file's VERIFICATION section. "needs human check"
   means words were found, not that the claim is true: read those yourself. FAILED → fix the
   research (another source, the exact quotation, a corrected fact) and run it again. Only the
   user may override: `--override "<their reason>"` with their own words (logged).
4. **"write scripts BG-x"** → `uv run ca youtube scripts BG-x` (refused until the check passed or
   was overridden). Read the briefs in `outputs/_system/youtube/BG-x/briefs/` (long-form: three,
   with the outline and the style's angle, opening and order; short-form: one, with the dialogue
   rules) and write `teleprompter-de.txt` (long-form: per style folder; short-form: in the topic
   folder, every paragraph starting `HOST:` or `ROMAN:`) from the outline: spoken German only (german-editorial
   "Gesprochenes Deutsch"), clean paragraphs separated by one empty line, no headings, labels,
   notes, citations, fact IDs, URLs or English; the length target is the format's
   `targetWords` (config/youtube.json formats). The three long-form styles keep the same thesis and facts but differ in opening
   type, order, perspective and tone; every factual sentence must come from a fact ID. Then `uv run ca youtube bilingual BG-x` makes `script-en-de.md` from each teleprompter
   file; replace every "<English translation …>" under "English:" with a faithful translation
   (never change the German there): faithful and complete, every sentence, the same term for
   the same thing, not summarised and not localised. Then `uv run ca youtube check BG-x` until
   every style passes. It also reports the traceability (factual sentences without a fact ID),
   spoken-German and summarised-English warnings and the difference check: the same opening
   type, the same order of points or facts, or near-identical sentences between two styles
   (rewrite one). Show the user the openings, then create the storyboards (long-form: all three
   styles; a style choice is not needed for storyboard creation).
5. **"generate storyboards BG-x"** → `uv run ca youtube storyboards BG-x` writes
   `storyboard.md` (long-form: in each style folder, each matching its own script and style;
   short-form: one in the topic folder),
   without recording a production style. Each scene names its script paragraphs and the fact
   IDs it found. Fill every `<…>` in all three files: the visual direction (never two
   Roman-on-camera scenes in a row without a cutaway), an English b-roll or screen-capture
   suggestion for the editor, and no unverifiable visual shown as real (label illustrative
   footage). **References inline:** every scene that states a fact, figure or news item is
   followed directly by its `**Reference:** <article title>, <outlet>, <YYYY-MM-DD>, <URL>`
   line(s) (filled from research.txt section 5 where the fact IDs are known; fill the rest from
   the same section). Then `uv run ca youtube check BG-x` again: a reference URL that is not a
   research.txt source is an error (the source check never opened it); it warns about
   placeholders left, two on-camera scenes in a row and numbers without a reference line. The rest of the storyboard spec is PENDING: do not invent
   extra sections.
6. **"select style B for BG-x"** (long-form) → `uv run ca youtube select-style BG-x B` records
   the style for production and ensures all three storyboards exist. It does not replace the
   other two.
7. **"upload youtube BG-x"** → with `STORAGE_PROVIDER=plugin`, `uv run ca youtube upload BG-x`
   writes an `upload_manifest.json` for the finished scripts and storyboards under Drive
   `Content Automation/YouTube Short-form/` or `YouTube Long-form/` (same topic and style tree
   as locally; `research.txt` stays local). Follow the upload skill to create or reuse folders
   and upload only its entries, then record results with
   `uv run ca youtube record BG-x --results <results.json>`. This upserts the local tracker row;
   then the manifest queues `tracker.csv` in `Calendar/`, which must also be uploaded and
   recorded. A tracker failure is printed and must be resolved before upload is reported done.
   `STORAGE_PROVIDER=drive` uses the separate Google API connection; do not use it when the
   Codex Drive plugin is the connected destination.
8. **"youtube status"** → `uv run ca youtube status [--month 2026-11]`.

Production after the storyboard (recording, edits, finals, thumbnail): produce-video.
