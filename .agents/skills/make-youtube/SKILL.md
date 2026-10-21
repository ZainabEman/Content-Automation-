---
name: make-youtube
description: Branded Genius YouTube research and production planning (PRD v5 R9): 8 German topics a month from real incidents, a verified research TXT per topic, three script styles (A investigativ, B direkte Warnung, C menschlich) as German teleprompter files plus German-English scripts, and a storyboard for each style for the editing agency. Roman records, the agency edits; nothing renders a video. Use for "plan youtube November", "research BG-x", "check sources BG-x", "write scripts BG-x", "generate storyboards BG-x", "select style B for BG-x", "upload youtube BG-x", "youtube status". Separate from the social skills; shares only BG IDs, approval, storage and the tracker.
---

# Make YouTube (research and production planning)

Everything here is free: `ca youtube` makes folders, templates and checks; you research and
write. No paid model is called by `ca`. Topic folder (PRD v6 R7): `outputs/YouTube Long-Form/<Topic Name>/`
with `research.txt` and `Style A/`, `Style B/`, `Style C/` (each: `script_de_teleprompter.txt`,
`script_de_en_bilingual.txt`, `storyboard.txt`). The BG ID and the briefs are in
`outputs/_system/youtube/`. A re-run never overwrites: a changed file is written as `<name>_v2.txt`.

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

1. **"plan youtube November"** → research real German incidents for the month with web access
   (German sources first). Pick up to 8 distinct topics (AI risks, misuse, fraud, deepfakes,
   security, data protection, poor implementation, real solutions). Then
   `uv run ca youtube plan 2026-11 --topic "<German topic>" …` (one `--topic` each). It creates
   Proposed items with BG IDs and folders. Show the list with one line of why each matters and
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
   was overridden). Read the three briefs in `outputs/_system/youtube/BG-x/briefs/` (they carry
   the outline and the style's angle, opening and order) and write, per style folder,
   `script_de_teleprompter.txt` from the outline: spoken German only (german-editorial
   "Gesprochenes Deutsch"), clean paragraphs separated by one empty line, no headings, labels,
   notes, citations, fact IDs, URLs or English; the length target is `targetWords`
   (config/youtube.json). The three styles keep the same thesis and facts but differ in opening
   type, order, perspective and tone; every factual sentence must come from a fact ID. Then `uv run ca youtube bilingual BG-x` makes `script_de_en_bilingual.txt` from each teleprompter
   file; replace every "<English translation …>" under "English:" with a faithful translation
   (never change the German there): faithful and complete, every sentence, the same term for
   the same thing, not summarised and not localised. Then `uv run ca youtube check BG-x` until
   every style passes. It also reports the traceability (factual sentences without a fact ID),
   spoken-German and summarised-English warnings and the difference check: the same opening
   type, the same order of points or facts, or near-identical sentences between two styles
   (rewrite one). Show the user the three openings, then create storyboards for all three styles;
   a style choice is not needed for storyboard creation.
5. **"generate storyboards BG-x"** → `uv run ca youtube storyboards BG-x` writes
   `storyboard.txt` in each style folder (Style A, B and C), each matching its own script,
   without recording a production style. Each scene names its script paragraphs and the fact
   IDs it found. Fill every `<…>` in all three files: the visual direction (never two
   Roman-on-camera scenes in a row without a cutaway), an English b-roll or screen-capture
   suggestion for the editor, the fact IDs [F#] of every factual visual or on-screen claim, and
   no unverifiable visual shown as real (label illustrative footage). Then
   `uv run ca youtube check BG-x` again: it warns about placeholders left, two on-camera scenes in
   a row and numbers without a fact ID. The rest of the storyboard spec is PENDING: do not invent
   extra sections.
6. **"select style B for BG-x"** → `uv run ca youtube select-style BG-x B` records the style
   for production and ensures all three storyboards exist. It does not replace the other two.
7. **"upload youtube BG-x"** → `uv run ca youtube upload BG-x` uploads research, six scripts,
   all three storyboards and records their links in the tracker.
8. **"youtube status"** → `uv run ca youtube status [--month 2026-11]`.

Production after the storyboard (recording, edits, finals, thumbnail): produce-video.
