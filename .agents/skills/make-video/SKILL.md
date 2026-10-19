---
name: make-video
description: Make the video clips of a waiting reel_short job with the Higgsfield Codex plugin, record them with `ca job complete`, and assemble final.mp4 (1080x1920). Use when `ca content build` or `ca video` prints a Codex checklist or "video pending" for a reel_short. UGC ads, podcast media and finished YouTube videos are no longer generated (v5, PRD R8): YouTube is research and production planning only (make-youtube skill).
---

# Make video

One video per package. The app never calls the plugins: it writes one request file per clip and waits. You make each clip with the plugin and record it.

## Which plugin

- `reel_short`: video scenes with the **Higgsfield** plugin. (v5: `ugc_ad`, `podcast_clip` and the `youtube` video workflow were removed; no workflow takes HeyGen avatar scenes any more.)
- Find the plugin's tools at run time; never assume a tool name. If a plugin is not available in this Codex session, stop and name the missing plugin.
- `VIDEO_PROVIDER=higgsfield-plugin` in `.env` selects this mode. With `mock` or `none` the job holds ("video pending"): tell the user the "Missing:" lines it printed.

## What a request gives you

`<job folder>/requests/scene-N.json` (one per clip):

| Field | Meaning |
| --- | --- |
| `stepId` | `scene-N`, used in the record commands |
| `capability`, `provider`, `plugin` | `video` (Higgsfield) |
| `prompt` | the shot |
| `durationSec`, `aspectRatio` | at most 15 s per clip; 9:16 |
| `startImagePath` | video: image-to-video from this picture (upload it if the tool needs a URL) |
| `identityImages`, `personRule` | the only person allowed (see below) |
| `instructions` | the same steps, numbered |
| `jobId` | the registry job of this clip: run `uv run ca jobs check <jobId>` before the plugin call |

## What you give back

For each step, exactly one of:

- `uv run ca job complete "<job folder>" --step scene-N --file "<package>/video/clips/scene-N.mp4" --provider-job-id <id> --credits <credits used>` (one MP4 per step; save downloads in the package's `video/clips/` folder; leave out the two options if the plugin reports neither).
- `uv run ca job fail "<job folder>" --step scene-N --error "<the reason>"` when generation fails. No retries; the job then fails.

Both also close the clip's registry job (credits counted against the authorization).

## Steps

1. Read every request of the job.
2. **Person.** Any person in a clip is the man in `identityImages`. Pass those photos as reference images when the plugin accepts images. If it cannot and the shot needs a person, stop and ask the user. Shots without him show no people. Never generate a different person, and never describe his face in words. HeyGen uses only his own avatar.
3. Show the user, per scene: the script or prompt, the provider, the duration, and any credit cost the plugin reports (the dry run prints these lines, the credit estimate per scene from `config/jobs.json` and `Dry run ID: DR-…`). Stop and wait for **"ok"**. A direct video then starts with `uv run ca video --plan <file> --authorize <DR-id>`; a package video is covered by the package's `--authorize` (make-content). Never pass `--authorize` without the user's "ok" to that dry run.
4. For each clip: `uv run ca jobs check <jobId>` first. Line 1 `go`: make the clip, wait until it is ready, save it, and record it (see above). `skip`: it already succeeded; do not call again. `stop`: stop and show line 2 to the user (over budget, stale or cancelled). A request without `jobId`: make it as before.
5. When every step is recorded: `uv run ca video resume "<job folder>"` assembles `final.mp4` (1080x1920; 30 fps, text burned in or `captions.srt`). For a package, then run `uv run ca content build "<package folder>"` to copy it into the package `video/` folder.
6. Report the path of `final.mp4`, the credits used and the video's BG ID (`uv run ca item status "<package folder>#<deliverable>"`, e.g. `#reel_short`).

Never say "ok" for the user, never edit `state/` or request files by hand, and show `ca` errors as they are.
