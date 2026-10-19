# Module guide: YouTube production planning

## What it does

This workflow prepares researched German YouTube topics and handoff materials for the recording and editing team. It does not make finished videos.

## What was built

Each approved topic can have a verified research file, three German teleprompter scripts, three German-English script files, and three storyboards: one each for styles A, B and C. Choosing a style for production is optional and does not remove the other storyboards.

## One-time setup

Use the project's normal setup in `docs/SETUP-CODEX.md`. Drive upload requires `STORAGE_PROVIDER=drive` and the existing Google Drive setup.

## How to use

1. Plan or select an approved YouTube topic with a BG ID.
2. Research it, check every source, and write scripts A, B and C from the checked facts.
3. Check the scripts, then run `uv run ca youtube storyboards BG-x`.
4. Complete every storyboard scene note before handing it to the editor. Factual visuals must point to source labels from the research file.
5. Run `uv run ca youtube upload BG-x` to upload the research, scripts, and all three storyboards and update the tracker.
6. Use `uv run ca youtube select-style BG-x B` only when the production style is chosen. This records the preference and keeps all three storyboards.

### Example Codex requests

- "Write scripts BG-098 and make storyboards for every style."
- "Upload YouTube BG-098 to Drive."
- "Select style B for BG-098."

## Commands

- `uv run ca youtube research BG-x`
- `uv run ca youtube check-sources BG-x`
- `uv run ca youtube scripts BG-x`
- `uv run ca youtube bilingual BG-x`
- `uv run ca youtube check BG-x`
- `uv run ca youtube storyboards BG-x`
- `uv run ca youtube select-style BG-x A|B|C`
- `uv run ca youtube upload BG-x`
- `uv run ca youtube status [--month YYYY-MM]`

## Outputs

Topic packages live under `outputs/youtube/<YYYY-MM>/<BG-ID>_<slug>/`. Drive stores the package under `Content Automation/YouTube/<YYYY-MM>/<BG-ID>_<slug>/`. Each topic has one tracker row with links to its research, six scripts, and three storyboards.

## Settings

`config/youtube.json` contains the script styles, speaking address, word targets, and scene timing. All audience-facing spoken lines and on-screen text are German; English is included for the editor.

## Costs and limits

Research, checks, scripts, storyboards, and YouTube upload are free in this workflow. No video is rendered.

## Troubleshooting

- A storyboard command says a style has not passed: run `uv run ca youtube check BG-x` and fix the reported script issue.
- A source check fails: correct the research from opened sources, then run `uv run ca youtube check-sources BG-x` again.
- Drive is not configured: follow `docs/SETUP-CODEX.md` before uploading.

## Switching providers

YouTube topic uploads use the configured storage provider. `STORAGE_PROVIDER=drive` writes to Google Drive; `mock` writes stand-in files and links under `outputs/drive/`. The Codex Drive plugin is not supported for these YouTube uploads.
