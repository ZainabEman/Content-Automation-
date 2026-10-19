---
name: make-youtube
description: Branded Genius YouTube research and production planning (PRD v5 R9): 8 German topics a month from real incidents, a verified research TXT per topic, three script styles (A investigativ, B direkte Warnung, C menschlich) as German teleprompter files plus German-English scripts, and a storyboard for the editing agency for the chosen style. Roman records, the agency edits; nothing renders a video. Use for "plan youtube November", "research BG-x", "check sources BG-x", "write scripts BG-x", "select style B for BG-x", "youtube status". Separate from the social skills; shares only BG IDs, approval, storage and the tracker.
---

# Make YouTube (research and production planning)

Everything here is free: `ca youtube` makes folders, templates and checks; you research and
write. No paid model is called by `ca`. Topic folder: `outputs/youtube/<YYYY-MM>/<BG-ID>_<slug>/`.

## Rules (always)

- German for everything the audience hears or sees, natural for people in Germany, "Sie"
  (config/youtube.json `address`). Internal notes and the agency's explanations may be English.
- Real incidents, current developments and documented problems first; relevant to Germany; no
  exaggerated fear or clickbait.
- **Never invent** a news story, statistic, URL, article title, quotation or event. Write only
  what you read on a page you opened. Unknown → leave it out or write "unknown".
- German sources first (config/sources_de.json is a starting list, not a filter); international
  primary sources may supplement.
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
2. **"research BG-x"** → `uv run ca youtube research BG-x` writes `research_<slug>.txt`. Fill
   every section from the pages you opened: sources as `[S1] Title | Publisher | YYYY-MM-DD`
   (section 5) and `[S1] https://full-url` (section 6); facts as `- <fact exactly as the source
   states it> [S1]`; quotations as `- "<exact words>" — <name, role> [S2]` (or "none");
   sections 11a verified facts, 11b interpretation, 11c proposed solutions. Run the command again
   until it says "complete".
3. **"check sources BG-x"** → `uv run ca youtube check-sources BG-x` (opens each URL; free).
   It writes status, final URL, title and date, checks every quotation in the page text and flags
   facts the source does not mention, into the file's VERIFICATION section. "needs human check"
   means words were found, not that the claim is true: read those yourself. FAILED → fix the
   research (another source, the exact quotation, a corrected fact) and run it again. Only the
   user may override: `--override "<their reason>"` with their own words (logged).
4. **"write scripts BG-x"** → `uv run ca youtube scripts BG-x` (refused until the check passed or
   was overridden). Read the three briefs in `.briefs/` and write, per style folder,
   `teleprompter_DE.txt`: spoken German only, clean paragraphs separated by one empty line, no
   headings, labels, notes, citations, URLs or English; about 1,300-1,600 words (Q4 default). The
   three styles must differ in hook, story, delivery and structure, and use only the verified
   facts. Then `uv run ca youtube bilingual BG-x` makes `script_DE-EN.txt` from each teleprompter
   file; replace every "<English translation …>" under "English:" with a faithful translation
   (never change the German there). Then `uv run ca youtube check BG-x` until every style
   passes; length warnings are reported, the difference check flags styles that are too similar
   (rewrite one). Show the user the three openings and **stop** for their choice.
5. **"select style B for BG-x"** → `uv run ca youtube select-style BG-x B` (registry +
   package.json) writes `storyboard_<style>.md`: one block per scene with timecode, the German
   line, the English, and `<…>` fields for visual direction, graphics, on-screen text (exact
   German + English explanation), sources and pacing. Fill every `<…>`; factual visuals cite
   the research [S#]. The rest of the storyboard spec is PENDING: do not invent extra sections.
6. **"youtube status"** → `uv run ca youtube status [--month 2026-11]`.

Production after the storyboard (recording, edits, finals, thumbnail): produce-video.
