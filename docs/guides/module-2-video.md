# Module guide: Video

> Status: `ca video` turns a video plan into a finished `final.mp4`. With the free mock providers
> it works offline; with Higgsfield (video) and HeyGen (avatar) Codex makes the clips through
> their MCP connections (see "Connect Higgsfield and HeyGen in Codex"). The exact MCP tool names
> are confirmed and documented when the connections are first used.
>
> **Voiceover is disabled in the MVP** (`VOICE_PROVIDER=none`): videos use the sound of their
> own clips (for example the avatar's speech). The ElevenLabs voice code is kept for later.

## What it does

It turns a plain-English request ("a 30-second Instagram Reel about our AI workshops") into a
finished vertical video (1080×1920, 30 frames per second, MP4) with on-screen text and
captions burned in. Each video is saved in its own dated folder with a `details.json` record of
every step, like the image jobs in Module 1.

A video is made of **scenes** (each 15 seconds or less). Each scene is one of:

- **video**: a generated clip (Higgsfield), optionally starting from one of your Module 1
  images or reference photos;
- **avatar**: a talking avatar saying some words (HeyGen);
- **image**: one of your existing images, shown with a slow zoom.

## What was built

- **Three video workflows**:
  - `reel_short` (up to 90 s): video scenes plus optional image scenes. For Reels and Shorts.
  - `ugc_ad` (up to 60 s): video scenes plus optional image scenes. For short ads.
  - `podcast_clip` (up to 90 s): one or more avatar scenes speaking the script, plus optional
    video scenes as b-roll.
- **Video plan (`plan.json`)**: the plan Codex writes before anything is made (hook, script,
  call to action, scenes). It is checked first, and every problem is listed in plain words,
  so a bad plan never spends credits. A scene over 15 seconds is refused.
- **`ca video`**: checks the plan, creates the job folder, makes each scene, and joins
  everything into `final.mp4`. `--dry-run` shows the scenes, providers and credits first.
- **Assembly**: every clip is resized to 1080×1920 (with black bars if its shape differs),
  30 fps, and joined in scene order. Each clip keeps its own sound; silent clips get silence.
  Video scenes are cut to their planned length; avatar clips are never cut, so no words are lost.
- **On-screen text**: a scene's `onScreenText` is shown near the top for the whole scene.
  An avatar's words are shown as captions near the bottom, one sentence (or half a long
  sentence) at a time. The same text is saved as `captions.srt` for platforms that accept
  caption files.
- **Start images**: a scene can start from a Module 1 image or a reference photo, named by its
  ID (see "How to use"). The picture used is recorded in `details.json`.
- **Agent steps**: Higgsfield and HeyGen are used through Codex (it calls them for you with
  your plan credits). When a job reaches such a step it **pauses** (`awaiting_agent`) and
  prints a numbered checklist. Codex makes each clip, records it with `ca job complete`, then
  runs `ca video resume` to finish the video.
- **Time limit**: a step that waits longer than `AGENT_STEP_TIMEOUT_MIN` minutes (default 30)
  is marked failed the next time `ca job status` or `ca video resume` runs.
- **Safety rules**: a job is never marked completed while a step is unfinished or a file is
  missing; a failed or timed-out step makes the whole job "failed".
- **Building blocks for later**: mock providers (free placeholder clips) and the ElevenLabs
  voice adapter (not used while voiceover is disabled).

## One-time setup

1. Module 1 setup (see [Module 1: Images](module-1-images.md)).
2. Nothing else is needed for the free mock providers: `.env` has `VIDEO_PROVIDER=mock`,
   `AVATAR_PROVIDER=mock` and `VOICE_PROVIDER=none`.
3. For real clips, connect Higgsfield and HeyGen in Codex (below).

### Connect Higgsfield and HeyGen in Codex

Both services are used through Codex with your own Higgsfield and HeyGen accounts and plan
credits; no API key goes into `.env`.

1. In the Codex app open **Settings**, then **MCP servers**, then **Add server**.
2. Enter the name `higgsfield`, choose **Streamable HTTP**, and enter the URL
   `https://mcp.higgsfield.ai/mcp`. Save.
3. Add a second server: name `heygen`, **Streamable HTTP**, URL `https://mcp.heygen.com/mcp/v1/`.
4. For each server select **Authenticate** and sign in with that service's account.
5. In `.env` set `VIDEO_PROVIDER=higgsfield-mcp` and `AVATAR_PROVIDER=heygen-mcp`.
6. For avatar videos: ask Codex "List my HeyGen avatars", pick one, and put its ID in `.env` as
   `HEYGEN_AVATAR_ID=`.
7. Run `uv run ca doctor`.

The same servers can also be added to `C:\Users\<your name>\.codex\config.toml` (the Codex app,
CLI and IDE extension share this file):

```toml
[mcp_servers.higgsfield]
url = "https://mcp.higgsfield.ai/mcp"

[mcp_servers.heygen]
url = "https://mcp.heygen.com/mcp/v1/"
```

With the Codex CLI, sign in with `codex mcp login higgsfield` and `codex mcp login heygen`.
Official guide: <https://learn.chatgpt.com/docs/extend/mcp>. This project's `.mcp.json` lists
the same two servers for Claude Code.

## How to use

The easiest way: **ask Codex in plain English**. Codex follows the "Make videos" playbook in
`AGENTS.md`: it writes `plan.json`, checks it with a dry run, runs `ca video`, handles any
agent steps, and replies with the path to `final.mp4`.

### The plan

Codex writes a plan like this (you can also write one yourself):

```json
{
  "workflowId": "reel_short",
  "platform": "instagram_reel",
  "durationSec": 10,
  "hook": "3 AI tools that save you 5 hours a week",
  "script": "Three AI tools that give small businesses five hours back every week.",
  "cta": "Follow for part 2",
  "scenes": [
    {"n": 1, "type": "video", "prompt": "Slow push-in on a founder at a laptop, bright office",
     "startImageAssetId": "d99b6a261a2a", "durationSec": 4,
     "onScreenText": "3 AI tools that save you 5 hours a week"},
    {"n": 2, "type": "image", "prompt": "The café photo", "startImageAssetId": "d723ee4ff6af",
     "durationSec": 3, "onScreenText": "Tool 1: an AI writing assistant"},
    {"n": 3, "type": "video", "prompt": "Close-up of hands typing, soft window light",
     "durationSec": 3, "onScreenText": "Follow for part 2"}
  ]
}
```

Rules:

- Scenes are numbered 1, 2, 3…, each at most 15 seconds, and they add up to `durationSec`.
- For **avatar** scenes, `prompt` is exactly what the avatar says (about 2.5 words per second).
- **Image** scenes need `startImageAssetId`.
- `startImageAssetId` is either the ID of a Module 1 image (listed as `outputAssetIds` in that
  image job's `details.json`), the ID of a reference photo (in its `set.json`), or
  `<jobId>/image-N.png` for a Module 1 image.
- `voice` is optional and ignored while voiceover is disabled.

### Example Codex requests

- "Make a 30-second Instagram Reel about our AI workshops, using yesterday's café image."
- "A 20-second Facebook ad for our strategy consulting, with 'Book a free call' at the end."
- "A 45-second podcast clip where the avatar explains why small businesses should automate reports."

### When a job pauses

With Higgsfield or HeyGen, `ca video` stops at `awaiting_agent` and prints a checklist. For each
step, Codex opens `requests/scene-N.json`, which holds the prompt, length, 9:16 shape, start
image (or, for HeyGen, the script and avatar) and numbered instructions: use the connected
MCP's generation tool, check its status until the clip is ready, download it, and run
`ca job complete`. When all are recorded, it runs `ca video resume <job folder>` (or, for a
content package, `ca content build <package folder>`).

## Commands

| Command | What it does |
| --- | --- |
| `uv run ca video --plan plan.json --dry-run` | Checks the plan; shows scenes, providers, start images and credits. Makes nothing. |
| `uv run ca video --plan plan.json [--request "…"]` | Makes the video. Prints the path to `final.mp4`, or a checklist if it pauses for Codex. |
| `uv run ca video resume <job folder>` | Continues a paused video: lists what is still missing, or assembles `final.mp4`. |
| `uv run ca job status <job folder>` | Shows the job and every step; marks steps that waited too long as failed. |
| `uv run ca job complete <job folder> --step scene-1 --file <path>` | Records the clip for a waiting step (the file is copied into the job folder). Optional: `--provider-job-id`, `--credits`. |
| `uv run ca job fail <job folder> --step scene-1 --error "what happened"` | Records a failed step; the job ends as failed. |

## Outputs

Each video job gets a folder `outputs/jobs/YYYY-MM-DD/HHmm_<name>/` containing:

| File | What it is |
| --- | --- |
| `final.mp4` | The finished video: 1080×1920, 30 fps, H.264 video with AAC sound. |
| `captions.srt` | All on-screen text and captions with their times. |
| `plan.json` | The plan the video was made from. |
| `script.md` | Hook, script, call to action and a table of the scenes, easy to read. |
| `clips/scene-N.mp4` (or `.png`) | Each scene's clip or image. |
| `requests/scene-N.json` | For agent steps: what Codex was asked to make (prompt, length, shape, start image, which tool). |
| `details.json` | The record: status, every step (`stepId`, `capability`, `provider`, `mode`, `status`, `file`, `providerJobId`, `creditsUsed`, `error`), the start images used (`inputs`), and `notes` (for example whether the text was burned in). |

Job status can be `queued`, `processing`, `awaiting_agent` (paused for Codex),
`completed`, `failed` or `cancelled`.

## Settings

| Setting | Meaning |
| --- | --- |
| `VIDEO_PROVIDER`, `VIDEO_MODEL` | Video clips: `mock` (free placeholders) or `higgsfield-mcp` (made by Codex). `VIDEO_MODEL` is passed on as the model (`mock`/`default` = the tool's default). |
| `AVATAR_PROVIDER`, `AVATAR_MODEL`, `HEYGEN_AVATAR_ID` | Avatar clips: `mock` or `heygen-mcp` (made by Codex); `HEYGEN_AVATAR_ID` is the avatar to use. |
| `VOICE_PROVIDER` | `none` (default): no voiceover. `mock` and `elevenlabs` are kept for later. |
| `VOICE_MODEL`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | Only for a later voiceover (the key stays in `.env`). |
| `AGENT_STEP_TIMEOUT_MIN` | Minutes an agent step may wait before it is marked failed (default 30). |

## Costs and limits

- Mock providers are free, and so are image scenes (they reuse existing pictures).
- Higgsfield and HeyGen use your plan credits; the dry run shows "TBD until the MCP is
  connected" until they are measured. Codex records the credits of each clip as `creditsUsed`.
- Scenes are at most 15 seconds. Videos: `ugc_ad` up to 60 seconds; `reel_short` and
  `podcast_clip` up to 90 seconds.
- Making `final.mp4` takes a few seconds per scene on this computer.

## Troubleshooting

- **"plan.json has N problem(s)"**: fix each listed line in the plan; nothing was made or spent.
- **"… is not in the reference sets or M1 image outputs"**: check the ID in the image job's
  `details.json` (`outputAssetIds`) or use `<jobId>/image-N.png`; run `uv run ca refs scan`
  if it is a new reference photo.
- **"the avatar's words take about Ns to say"**: shorten the words or make the scene longer.
- **Status `awaiting_agent`**: normal with Higgsfield/HeyGen; follow the printed checklist,
  then run `uv run ca video resume <job folder>`.
- **"No details.json in …"**: pass the job folder itself (the one that contains `details.json`).
- **"Step 'scene-1' is completed, not awaiting_agent"**: that step was already recorded.
- **"This job is already failed"**: the job stopped (a step failed or timed out); read
  `error` in `details.json` and start a new job.
- **`notes` in details.json says "Text NOT burned in"**: this computer's FFmpeg or fonts
  cannot draw text; upload `captions.srt` with the video instead.

## Switching providers

Change the provider name in `.env` (`VIDEO_PROVIDER`, `AVATAR_PROVIDER`) and its model
(`…_MODEL`). Set them back to `mock` to work for free. Adding a new provider takes one new
adapter file plus these two settings. Voiceover stays off (`VOICE_PROVIDER=none`) in the MVP.
