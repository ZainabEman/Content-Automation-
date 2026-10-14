# Integration verification (Phase 10)

The 12 integrations below are the working list. The client spec's §7 list is not in the repo yet, so this list still has to be checked against it.

How it works:
- `uv run ca verify list` shows each integration's success condition, failure path, and last offline and live result.
- `uv run ca verify run <name>` is the offline check. It confirms the config is present and the adapter loads, then runs the failure path with a fake. It never makes a live or paid call.
- An integration counts as **operational** only once a live pass is recorded. After each manual test below, the user runs `uv run ca verify record <name> --live pass|fail "<what was tested>"`.

Paid steps always show their dry run first and need the user's "ok".

## codex — Codex skills/CLI
1. In Codex Desktop, say "what can I say". The phrase list appears (`ca help commands`).
2. Say "show items" and "verification status". Each one runs its command without an error.
3. Pass: both phrases ran. Record: `uv run ca verify record codex --live pass "what can I say, show items"`.

## gmail — Gmail plugin
1. In Codex, connect the Gmail plugin to brandedgenius.de@gmail.com.
2. Say "show content". Codex names the searched account, lists the 5 newest subjects, then shows a numbered idea list.
3. Pass: the subjects match the inbox (label Newsletters). Record: `uv run ca verify record gmail --live pass "<n> subjects"`.

## web-fetch — web research fetch
1. Say "research this link <a real article URL>".
2. Pass: the article text is saved and its claims are listed (`ca claims`). A blocked site shows one error line. Record: `uv run ca verify record web-fetch --live pass "<url>"`.

## higgsfield — Higgsfield plugin (manual test 1)
1. Run the first paid animated carousel: dry run, "ok", then the make-carousel skill makes the stills and clips.
2. Run `uv run ca costs calibrate --provider higgsfield-plugin`. Add `--apply` only after looking at the result.
3. Pass: the carousel renders and every request is recorded. Record: `uv run ca verify record higgsfield --live pass "<BG-x>, <credits>"`.

## heygen — HeyGen plugin (manual test 4)
1. Set `HEYGEN_AVATAR_ID` and `HEYGEN_VOICE_ID` with `uv run ca env set` (chosen from the plugin's lists).
2. Run `uv run ca podcast heygen BG-x`: dry run, "ok", `--authorize`, the plugin, then `ca podcast record <job> <file>`.
3. Pass: the recording is imported and production is recorded. Record: `uv run ca verify record heygen --live pass "<BG-x>"`.

## comfyui — ComfyUI/RunPod — blocked: LoRA track
1. Blocked until Roman's LoRA track finishes. Do not run it before then.
2. After that: one image job with the identity workflow (dry run, "ok"), then the person check.
3. Record: `uv run ca verify record comfyui --live pass "<job>"`.

## openrouter — OpenRouter (Nano Banana fallback): client decision
1. This is a configured fallback and is off by default: no deliverable names it in `config/deliverables.json`. If the client keeps it, the dry run offers it on its own "Fallback provider" line.
2. Only if the client keeps it: `uv run ca content build "<folder>" --provider openrouter --dry-run`, then "ok", then the build with `--authorize`.
3. Pass: one image comes back. Record: `uv run ca verify record openrouter --live pass "<folder>"`.

## drive — Google Drive (API or plugin) (manual test 2)
1. Set `STORAGE_PROVIDER=plugin` (or finish `ca drive setup` for the API), then approve one review.
2. Say "upload approved files". Each request is uploaded and then recorded with `ca drive record`.
3. Pass: the files are in `<Folder>/<Content ID>/v<n>/`. Record: `uv run ca verify record drive --live pass "<BG-x>"`.

## tracker — tracker Sheet
1. Run `uv run ca drive sync` after an approved upload.
2. Pass: the item's row appears in the Content Tracker with its BG ID and status, and `ca tracking conflicts` shows none. Record: `uv run ca verify record tracker --live pass "<BG-x> row"`.

## opus-pro — Opus Pro (manual) (manual test 5)
1. `uv run ca clips handoff BG-x`. Opus Pro makes 10–12 vertical clips from the note.
2. `uv run ca clips import BG-x <folder>`, then `uv run ca clips select BG-x <4–5 numbers>`.
3. Pass: the picked clips are approved shorts. Record: `uv run ca verify record opus-pro --live pass "<BG-x>"`.

## ffmpeg — FFmpeg media (manual test 3)
1. Import one real recording of Roman: `uv run ca import BG-x <file> --as recording`. FFmpeg decodes it before the copy is made.
2. Run `uv run ca podcast audio BG-x` (MP3) or `uv run ca prepare BG-x` (platform video variants).
3. Pass: the files play. Record: `uv run ca verify record ffmpeg --live pass "<BG-x>"`.

## publishing — publishing (manual URL) (manual test 6)
1. Post one prepared item yourself (there are no direct integrations).
2. Say "BG-x is live on LinkedIn <url>" (`ca publish mark`).
3. Pass: `ca publish list` shows it as published with the URL. Record: `uv run ca verify record publishing --live pass "<url>"`.
