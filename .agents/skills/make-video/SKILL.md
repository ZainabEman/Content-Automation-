---
name: make-video
description: Make the video clips of a waiting video job with the Higgsfield and HeyGen Codex plugins, record them with `ca job complete`, and assemble the 1080x1920 final.mp4. Use when `ca content build` or `ca video` prints a Codex checklist or "video pending" for a reel_short, ugc_ad or podcast_clip video.
---

# Make video

One video per package. The app never calls the plugins: it writes one request file per clip and waits. You make each clip with the plugin and record it.

## Which plugin

- `reel_short` and `ugc_ad`: video scenes with the **Higgsfield** plugin.
- `podcast_clip`: avatar scenes with the **HeyGen** plugin and the person's own avatar; its b-roll video scenes with Higgsfield.
- Find the plugin's tools at run time; never assume a tool name. If a plugin is not available in this Codex session, stop and name the missing plugin.
- `VIDEO_PROVIDER=higgsfield-plugin` and `AVATAR_PROVIDER=heygen-plugin` in `.env` select this mode. With `mock` or `none` the job holds ("video pending"): tell the user the "Missing:" lines it printed.

## What a request gives you

`<job folder>/requests/scene-N.json` (one per clip):

| Field | Meaning |
| --- | --- |
| `stepId` | `scene-N`, used in the record commands |
| `capability`, `provider`, `plugin` | `video` (Higgsfield) or `avatar` (HeyGen) |
| `prompt` | video: the shot; avatar: the exact words, spoken word for word |
| `durationSec`, `aspectRatio` | at most 15 s per clip; 9:16 |
| `startImagePath` | video: image-to-video from this picture (upload it if the tool needs a URL) |
| `identityImages`, `personRule` | the only person allowed (see below) |
| `options.avatarId` | avatar: the HeyGen avatar (empty: see below) |
| `instructions` | the same steps, numbered |

## What you give back

For each step, exactly one of:

- `uv run ca job complete "<job folder>" --step scene-N --file "<package>/video/clips/scene-N.mp4" --provider-job-id <id> --credits <credits used>` (one MP4 per step; save downloads in the package's `video/clips/` folder; leave out the two options if the plugin reports neither).
- `uv run ca job fail "<job folder>" --step scene-N --error "<the reason>"` when generation fails. No retries; the job then fails.

## Steps

1. Read every request of the job. For `podcast_clip`, if `options.avatarId` is empty (`HEYGEN_AVATAR_ID` not set): list the avatars with the HeyGen plugin, let the user pick their own, and give them the exact line `HEYGEN_AVATAR_ID=<avatar id>` for `.env`. Use that avatar.
2. **Person.** Any person in a clip is the man in `identityImages`. Pass those photos as reference images when the plugin accepts images. If it cannot and the shot needs a person, stop and ask the user. Shots without him show no people. Never generate a different person, and never describe his face in words. HeyGen uses only his own avatar.
3. Show the user, per scene: the script or prompt, the provider, and any credit cost the plugin reports. Stop and wait for **"ok"**.
4. Make each clip, wait until it is ready, save it, and record it (see above).
5. When every step is recorded: `uv run ca video resume "<job folder>"` assembles `final.mp4` (1080x1920, 30 fps, text burned in or `captions.srt`). For a package, then run `uv run ca content build "<package folder>"` to copy it into the package `video/` folder.
6. Report the path of `final.mp4` and the credits used.
