# PRD v6: Weekly quantities, two YouTube pipelines, Drive naming (updated 22 Oct 2026)

Put in repo as `docs/PRD-v6-weekly-youtube-drive.md`.

## 1. Goal
1. "make weekly calendar" produces a fixed content set; the monthly calendar is the same set ×4.
2. The YouTube workflow splits into two independent script pipelines: Short-form (1-min host + Roman dialogue) and Long-form (12-min Roman-only news analysis). Deliverables are scripts only.
3. Drive: separate folders for Short-form and Long-form; all item folders named "<English Topic Title> <YYYY-MM-DD>"; existing folders renamed to match; the tracker is updated on every Drive push.

## 2. Quantities
| Item | Weekly | Monthly (×4) |
|---|---|---|
| Image posts (total, incl. the items below) | 14 | 56 |
| – of which with Roman | at least 2 | at least 8 |
| – of which Instagram carousels | 2 | 8 |
| Long-form YouTube scripts | 2 | 8 |
| Short-form YouTube scripts | 4 | 16 |

- The 10 remaining image posts are split across LinkedIn and Facebook posts using the existing platform split in config.
- Numbers live in config, not in code. Monthly = weekly ×4; this replaces the old 30–60 mix.
- Topics come from the existing research (German + AI topic genre, balanced positive/negative), no duplicates within the week/month.

## 3. Short-form YouTube pipeline
- About 1 minute ≈ 140–160 spoken German words (config value).
- Podcast-style dialogue with speaker labels `HOST:` (AI-generated host) and `ROMAN:`; host introduces/asks, Roman analyses; adapt per topic.
- One topic; strong hook in the first line; natural ending (takeaway, question or strong statement).
- Topics: AI news, AI problems in Germany (business, work, society), impact on people/jobs, risks, limits, controversies, positive developments.
- **One style only.** The topic folder directly contains 3 files (no style subfolders):
  - `script-en-de.md`: bilingual script (English + German, aligned per turn)
  - `teleprompter-de.txt`: German teleprompter text (identical to the German script; Roman's lines marked)
  - `storyboard.md`: storyboard with references inline (see §5)

## 4. Long-form YouTube pipeline
- About 12 minutes ≈ 1,600–1,800 spoken German words (config value); Roman only, no host.
- 5–10 topics; 2–3 min each by importance, adjusted so the total stays ≈12 min.
- Structure: strong hook (real, sourced statistic/risk/finding, not sensational; what viewers can do) → topic segments (news → why it matters → analysis/implications) with transitions → short conclusion.
- Balanced: risks and positive developments.
- **Three styles** (the existing three styles of the current YouTube package). The topic folder contains one subfolder per style, each with the same 3 files: `script-en-de.md`, `teleprompter-de.txt`, `storyboard.md`. Each storyboard belongs to and matches the style of its own folder.

## 5. References
- No separate sources/references file.
- In `storyboard.md`, every paragraph/scene that states a fact, figure or news item is followed **directly** by its reference line: article title, outlet, date and URL.
- The existing source check (dead URL, misquote) still runs on these inline references.

## 6. Drive and tracker
- Under `Content Automation/`: folders `YouTube Short-form/` and `YouTube Long-form/`.
- Every item folder on every platform: `<English Topic Title> <YYYY-MM-DD>` (topic first, then planned date). On a clash add ` (2)`.
- File names in English; file contents stay German (except the English half of the bilingual script).
- BG ID / content ID stays in the tracker and in `item.json` inside the folder, not in the folder name.
- Each item gets an English short title `title_en` (max ~6 words), generated with the copy and stored on the item.
- **Rename existing folders:** a command lists every existing item folder (Drive and local outputs) whose name doesn't match the new pattern, with its new name (`--dry-run` default). The real rename runs only after the user's "ok", renames in place (same folder ID, contents unchanged), and updates the tracker's Drive links/state. Items without `title_en` get one generated (free, text) before renaming.
- Every successful Drive upload upserts the tracker row (BG ID key) with Drive folder link and upload status, for all item types incl. both YouTube pipelines. A failed tracker write is reported, never silent.

## 7. Out of scope
Video, voice and AI host/avatar production; publishing; GHL; new providers; refactors; new test suites; paid calls.

## 8. Acceptance (light checks only)
1. Weekly config gives 14 posts (≥2 Roman, 2 carousels), 2 long-form, 4 short-form; monthly 56/8/8/8/16.
2. Short-form and long-form are separate commands/options with separate prompts, length targets, presenter config and Drive folders.
3. Short-form topic folder = 3 files directly; long-form topic folder = 3 style subfolders × 3 files.
4. References appear right after the relevant paragraph in each storyboard; no separate sources file.
5. Folder names = English topic + date; rename command dry run lists old folders and new names (mock).
6. Drive upload (mock) updates the tracker row (mock) for a post and a YouTube item.
7. ruff + mypy --strict + existing pytest pass.

## 9. Defaults chosen
- Carousels and Roman posts count inside the 14.
- Short ≈150 words, long ≈1,700 words.
- Bilingual script = English + German aligned per turn/paragraph.
