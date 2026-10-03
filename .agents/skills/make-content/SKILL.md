---
name: make-content
description: Make Branded Genius social content (Instagram carousel, Facebook ad, reel or other video) as one content package with the `ca content` commands. Use when the user asks for a post, ad, reel, video or podcast clip about a topic; not for single test images or research-only questions.
---

# Make content

The deliverables and their names live in `config/deliverables.json`; `uv run ca content deliverables` prints them. That file is the only source of truth for what a word means.

## 1. Pick exactly what the user named

- Map each thing the user asked for to a deliverable by its exact name (alias). Build those and nothing else: "facebook ad only" is only `facebook_ad`; two names are those two.
- An Instagram post is a carousel ("insta post", "instagram post", "ig post" -> `instagram_carousel`, 5 slides: hook, 3 tips, CTA). "video", "reel", "insta reel", "facebook video" -> `reel_short`; "ugc ad" -> `ugc_ad`; "podcast clip" -> `podcast_clip`.
- If a word is not a listed name, or could mean two deliverables (for example "ad", "post", "facebook"), ask the user which one they mean. Never guess and never add extras.
- One package makes at most one post, one image ad and one video. If the user wants two videos, ask which comes first or make two packages.

## 2. Start the package

```
uv run ca content start --topic "<topic>" --deliverables "<the names the user used, comma-separated>"
```

Exit code 2 means a name was unknown or ambiguous: ask the user with the message it printed, then run it again. On success it prints the package folder.

## 3. Write brief.json

In the folder, read `research.md`, `brief.template.json` and `docs/company/services.md`, then write `brief.json` from the template. Keep `deliverables`, `formats` and `platform` as the template set them. Fill every `<...>`: English only, one service from `_help.services`, no invented results, statistics, prices or client names, and the design rules in AGENTS.md ("Design choices"). For a video, `reel.workflow` is fixed by the deliverable; `podcast_clip` scenes are `"avatar"` (the exact words, about 2.5 words per second) or `"video"` (b-roll).

## 4. Dry run, then wait for "ok"

```
uv run ca content build "<folder>" --dry-run
```

Fix every listed problem in `brief.json` and run it again until it is clean. Then tell the user the image cost and the video line (provider and credits) and wait for their "ok", for video exactly as for images. If the dry run says the video will be pending, say what is missing.

## 5. Build

```
uv run ca content build "<folder>"
```

- Images are made at once. The video runs with `VIDEO_PROVIDER` / `AVATAR_PROVIDER` from `.env`.
- If it prints a Codex checklist (Higgsfield/HeyGen MCP), do each step as its `requests/<step>.json` says, then build again. If that MCP is not connected in this session, do not retry: tell the user to connect it, and leave the package pending.
- If a provider is `mock` or `none`, the build does not fail: the video job is created, the package says "draft — video pending", and it prints exactly what to set. Tell the user that list. Later, `uv run ca video resume "<job folder>"` or another `ca content build` finishes it.

## 6. Reply

Give the folder path, the status, and the files it printed (images/, video/final.mp4 when done, post.md, package.json). If the video is pending, repeat what is missing.
