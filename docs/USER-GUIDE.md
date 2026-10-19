# User guide: Content Automation in Codex

> **v5 (2026-10-19):** UGC ads, podcast media and finished YouTube videos are no longer generated (PRD v5 R8). Only reels (`reel_short`, Higgsfield) remain as video; HeyGen avatar clips are not used by any workflow. YouTube is research and production planning: `ca youtube` and the make-youtube skill. Everything the audience sees is German.

Type every phrase below in Codex Desktop. Codex runs the matching `uv run ca …` command for you. Nothing that costs money runs until you have seen its dry run and said "ok". Nothing is published automatically. Every item has a BG ID (for example BG-007).

## First-time setup
1. Install and check: `uv sync`, then `uv run ca doctor`. Follow any fix it prints.
2. Create `.env`: copy `.env.example` to `.env`. Set each value with `uv run ca env set <NAME> <value>`, which never shows the value. Keys by name:
   - `STORAGE_PROVIDER` and `DRIVE_SHARE_WITH`: the Drive route (step 3)
   - `HEYGEN_AVATAR_ID` and `HEYGEN_VOICE_ID`: chosen from the HeyGen plugin's lists
   - `OPENROUTER_API_KEY`: only if the Nano Banana fallback is kept (client decision)
   - `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`, `RUNPOD_NETWORK_VOLUME_ID` and the S3 keys: ComfyUI with Roman's LoRA (`docs/guides/runpod-zimage-setup.md`)
3. Choose the Drive route:
   - `STORAGE_PROVIDER=plugin`: the Google Drive plugin uploads each request, then "upload approved files".
   - `STORAGE_PROVIDER=drive`: the Drive API. Run `uv run ca drive setup` once.
   - `mock` is only for testing and never counts as an upload.
4. Connect these Codex plugins: Gmail (brandedgenius.de@gmail.com only), Higgsfield, HeyGen, and Google Drive (if you chose the plugin route).
5. Say "verification status". Then do the manual live tests in `docs/VERIFICATION.md`, and record each result with `uv run ca verify record <name> --live pass|fail "<note>"`.

## Research
- "show content": new ideas from the Gmail newsletters (read-only)
- "show content --all": the same, including emails used before
- "what's new": the same as "show content"
- "new ideas from my newsletters": the same as "show content"
- "find new ideas": newsletters and sources become backlog ideas
- "research this link <url>": saves the page's text as a source
- "add topic <text>": adds your own idea, kept word for word
- "show backlog": every idea with its score, pillar and flags
- "show ideas": the same as "show backlog"
- "review ideas": proposed ideas, best first, with their sources
- "merge BG-x into BG-y": moves the sources over; BG-x becomes a duplicate
- "show claims for BG-x": the item's claims and their status

## Calendar
- "make calendar": a proposed week, with BG IDs
- "make calendar next week": the same as "make calendar"
- "plan next week": fills the slots from approved ideas
- "plan next month": the month's slots, one CSV per week
- "show month": every row of the month

## Approve
- "approve all": every proposed calendar row
- "approve 1 3 5": those calendar rows
- "reject 2": that row (Codex asks for the reason)
- "show items": every item with its BG ID, statuses and version
- "what's pending": ideas to decide, then items to review
- "status BG-x": statuses, versions, jobs, files and next actions
- "approve BG-x [BG-y]": approves the open gate (the idea first, then the review)
- "reject BG-x <reason>": a reason is required
- "revise BG-x <feedback>": a new version that must be approved again
- "resubmit BG-x": proposes the idea again after a revise
- "history of BG-x": every event for the item

## Generate
- "generate approved": stage 1, then one combined dry run
- "ok": builds exactly what that dry run showed (your only spending approval)
- "make 3": a package from idea 3
- "make 2 and 5": one package each
- "make a post about X": a package about X
- "make an insta post / facebook ad / reel about X": a package with only those deliverables
- "use comfyui": this build on ComfyUI with Roman's LoRA (its dry run, then "ok")
- "use the fallback": only the offered fallback line's own dry run, then "ok" (never for ads)
- "write script for BG-x": a checked, versioned script
- "write copy for BG-x": the copy for a post, carousel or ad
- "write brief for BG-x": the production brief
- "rewrite script BG-x <feedback>": a new version; the old one is kept
- "show script BG-x": the saved script
- "check script BG-x": runs the check again
- "show brief BG-x": the saved production brief
- "continue carousel <folder>": where the carousel stopped, and its next step
- "make a post about X as FB-2": that design direction instead of the automatic pick
- "preview designs": all 12 design directions drawn with sample copy (free, outputs/design/preview)
- "check designs": the free brand, logo, text-fit, contrast and claims check of rendered designs
- "show authorizations": what each "ok" allows (spent of max)
- "show costs": estimate against actual, per job type
- "train lora": parked (LoRA track)

## Review
- "what needs review": generated items not reviewed yet
- "show BG-x for review": version, files, checks, costs and the last feedback
- "regenerate BG-x": a dry run for the parts; "ok" first
- "redo slide 3 of BG-x": only that slide; the other slides are kept

## Upload
- "upload approved files": the Drive plugin uploads each request, then it is recorded
- "sync drive": uploads finished files and the tracker rows
- "show tracker": tracker rows and status counts
- "export tracker": the tracker as a CSV file
- "tracker conflicts": hand edits, missing rows and duplicate IDs

## Production
- "production status": YouTube production (Roman records, the agency edits), finals against the targets
- "import recording/final for BG-x <path>": a checked copy; the status moves on
- "send BG-x to the editor <name>": the handoff folder for the editor
- "BG-x recorded": moves the production status (legal moves only)
- "make thumbnail for BG-x": a 1280x720 thumbnail with the brief's text

## Clips
- "make clips from BG-x": the note for Opus Pro (run manually)
- "import clips for BG-x <folder>": candidate shorts (vertical, 15–90 s)
- "select clips … for BG-x": approves your picks; the rest are marked not selected

## Distribute
- "prepare BG-x for all platforms": a variant for each platform, plus its copy
- "what's ready to publish": the platforms that are ready
- "BG-x is live on LinkedIn <url>": marks it published, with the URL
- "BG-x failed on TikTok <reason>": marks it failed, with the reason

## Reports
- "monthly report": this month's recorded finals and posts against the targets (mocks never count)
- "report for <month>": the same for that month (saved to `outputs/reports/<YYYY-MM>.md`)
- "verification status": all 12 integrations; each is operational only after a recorded live pass
- "verify <integration>": the offline check only (never a live call)
- "what failed": failed or cancelled jobs
- "unfinished jobs": queued or running (stale) jobs
- "resume unfinished jobs": the carousel's next step
- "resume everything": every resumable job; the rest is listed as needing manual action
- "retry failed jobs": a dry run, then "ok"
- "show audit log": the newest events
- "what can I say": every phrase, with the command behind it

## New in v5 (German, brand visuals, YouTube planning)

- "plan month November": about 2 graphics a day across Instagram carousels, Facebook posts, Facebook ads and LinkedIn, with the cost of the planned volume (free). "apply the plan" puts the rows with an approved idea into the weekly calendars.
- "make an insta carousel about TOPIC": 5-6 square slides, no slide numbers, logo and website only on the last slide.
- "make a facebook ad about TOPIC": one ad creative plus primary text, headline, description and a Meta button choice (nothing is placed or paid).
- "compare designs": every layout variant beside the company's own graphics, `outputs/previews/design/v5_vs_references.png` (free). Please review it before the first paid batch.
- "plan youtube November", "research BG-x", "check sources BG-x", "write scripts BG-x", "select style B for BG-x", "upload youtube BG-x", "youtube status": the YouTube research and production planning (skill make-youtube). Roman records, the editing agency edits.
- Drive: new folders Instagram Carousels, Facebook Posts and Facebook Ads are created on the next `ca drive setup`; nothing existing is renamed or moved (docs/v5-drive-actions.md lists what waits for your "ok").
