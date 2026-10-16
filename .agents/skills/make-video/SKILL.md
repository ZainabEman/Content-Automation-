---
name: make-video
description: Make the video clips of a waiting video job with the Higgsfield and HeyGen Codex plugins, record them with `ca job complete`, and assemble final.mp4 (1080x1920; youtube 1920x1080). Use when `ca content build` or `ca video` prints a Codex checklist or "video pending" for a reel_short, ugc_ad, podcast_clip or youtube video, and for "make youtube video about TOPIC".
---

# Make video

One video per package. The app never calls the plugins: it writes one request file per clip and waits. You make each clip with the plugin and record it.

## Which plugin

- `reel_short` and `ugc_ad`: video scenes with the **Higgsfield** plugin.
- `podcast_clip` and `youtube`: avatar scenes with the **HeyGen** plugin, the person's own avatar and the voice in `HEYGEN_VOICE_ID`; its b-roll video scenes with Higgsfield.
- Find the plugin's tools at run time; never assume a tool name. If a plugin is not available in this Codex session, stop and name the missing plugin.
- `VIDEO_PROVIDER=higgsfield-plugin` and `AVATAR_PROVIDER=heygen-plugin` in `.env` select this mode. With `mock` or `none` the job holds ("video pending"): tell the user the "Missing:" lines it printed.

## What a request gives you

`<job folder>/requests/scene-N.json` (one per clip):

| Field | Meaning |
| --- | --- |
| `stepId` | `scene-N`, used in the record commands |
| `capability`, `provider`, `plugin` | `video` (Higgsfield) or `avatar` (HeyGen) |
| `prompt` | video: the shot; avatar: the exact words, spoken word for word |
| `durationSec`, `aspectRatio` | at most 15 s per clip; 9:16 (youtube: 16:9) |
| `startImagePath` | video: image-to-video from this picture (upload it if the tool needs a URL) |
| `identityImages`, `personRule` | the only person allowed (see below) |
| `options.avatarId`, `options.voiceId` | avatar: the HeyGen avatar and voice; pass both explicitly in every request, never rely on the avatar's default voice |
| `instructions` | the same steps, numbered |
| `jobId` | the registry job of this clip: run `uv run ca jobs check <jobId>` before the plugin call |

## What you give back

For each step, exactly one of:

- `uv run ca job complete "<job folder>" --step scene-N --file "<package>/video/clips/scene-N.mp4" --provider-job-id <id> --credits <credits used>` (one MP4 per step; save downloads in the package's `video/clips/` folder; leave out the two options if the plugin reports neither).
- `uv run ca job fail "<job folder>" --step scene-N --error "<the reason>"` when generation fails. No retries; the job then fails.

Both also close the clip's registry job (credits counted against the authorization).

## HeyGen avatar and voice (before any job)

Both `HEYGEN_AVATAR_ID` and `HEYGEN_VOICE_ID` are required. If one is empty, `ca content build` / `ca video` stop **before the video job exists** (nothing is marked failed) and say which one. Then:

1. With the HeyGen plugin, list the account's avatars (his own first) or voices (own or cloned voices first). Let the user choose.
2. Set only that line: `uv run ca env set HEYGEN_AVATAR_ID <id>` or `uv run ca env set HEYGEN_VOICE_ID <id>`. Never open, print or edit `.env` any other way.
3. Pre-check before the "ok": confirm with the plugin that both IDs exist in the account (the avatar and the voice resolve). If one does not, stop and ask the user to choose again; do not start the video.

## Steps

1. Read every request of the job (`options.avatarId` and `options.voiceId` are filled from `.env`).
2. **Person.** Any person in a clip is the man in `identityImages`. Pass those photos as reference images when the plugin accepts images. If it cannot and the shot needs a person, stop and ask the user. Shots without him show no people. Never generate a different person, and never describe his face in words. HeyGen uses only his own avatar.
3. Show the user, per scene: the script or prompt, the provider, the avatar and voice (HeyGen scenes), the duration, and any credit cost the plugin reports (the dry run prints these lines, the credit estimate per scene from `config/jobs.json` and `Dry run ID: DR-…`). Stop and wait for **"ok"**. A direct video then starts with `uv run ca video --plan <file> --authorize <DR-id>`; a package video is covered by the package's `--authorize` (make-content). Never pass `--authorize` without the user's "ok" to that dry run.
4. For each clip: `uv run ca jobs check <jobId>` first. Line 1 `go`: make the clip, wait until it is ready, save it, and record it (see above). `skip`: it already succeeded; do not call again. `stop`: stop and show line 2 to the user (over budget, stale or cancelled). A request without `jobId`: make it as before.
5. When every step is recorded: `uv run ca video resume "<job folder>"` assembles `final.mp4` (1080x1920, youtube 1920x1080; 30 fps, text burned in or `captions.srt`). For a package, then run `uv run ca content build "<package folder>"` to copy it into the package `video/` folder.
6. Report the path of `final.mp4`, the credits used and the video's BG ID (`uv run ca item status "<package folder>#<deliverable>"`, e.g. `#reel_short`).

Never say "ok" for the user, never edit `state/` or request files by hand, and show `ca` errors as they are.

## YouTube ("make youtube video about TOPIC")

A 16:9 1920x1080 video: the HeyGen avatar speaks the script; optional Higgsfield b-roll (`video`) and picture (`image`) scenes. Same pattern as make-carousel: dry run with the estimate → the user's "ok" → plugin calls → `ca` records each file. No YouTube publishing.

1. IDs first: `uv run ca doctor` or the dry run's `STOP:` lines show whether `HEYGEN_AVATAR_ID` and `HEYGEN_VOICE_ID` are set. If either is missing: stop, list the account's avatars or voices with the HeyGen plugin and ask the user to choose; set it with `uv run ca env set <NAME> <id>` only after their answer. Never guess or pick an ID yourself.
2. Write `outputs/plans/<short-name>.json` (AGENTS.md → Make videos) with `"workflowId": "youtube"`, `"platform": "youtube"`: ≤600 s, scenes ≤15 s, at least one `avatar` scene (`prompt` = the exact words, ≈2.5 words/s).
3. `uv run ca video --plan <file> --dry-run`: fix every problem; show the user per scene the words or prompt, avatar, voice, seconds, the credit estimate (`config/jobs.json`) and `Dry run ID: DR-…`. Stop for **"ok"**.
4. After "ok": `uv run ca video --plan <file> --request "<the user's exact words>" --authorize <DR-id>`, then Steps 2–4 above for every request (HeyGen with `options.avatarId` + `options.voiceId` and `aspectRatio` 16:9; record each MP4 with `ca job complete`).
5. `uv run ca video resume "<job folder>"` → `final.mp4` 1920x1080.
6. Drive: `uv run ca video upload "<job folder>" [--content-id <Content ID>]` → `Content Automation/YouTube/<Content ID>/final.mp4` (default ID: the job folder's name; mock storage until `STORAGE_PROVIDER=drive`). Report the path, the link and the credits used.

## HeyGen podcast (Phase 8)

A podcast item whose production brief says `recordingSource: heygen` (produce-video):
1. `uv run ca podcast heygen BG-x`: the dry run (credits per segment). "HeyGen voice ID not configured (client)": stop and tell the user; the client chooses the voice (`uv run ca env set`). Otherwise show the cost and stop for **"ok"**.
2. Only after the user's "ok": `uv run ca podcast heygen BG-x --authorize <DR-id>` writes `state/heygen/<jobId>.json` (script, voiceId, avatarId).
3. `uv run ca jobs check <jobId>` (go / skip / stop), then the HeyGen plugin with exactly that script, voice and avatar; save the file it returns.
4. `uv run ca podcast record <jobId> "<file>" --credits <what the plugin reported>`: the job is recorded and the file imported as the recording (production → recorded). A failed plugin call: report it; never retry without the user's yes.
