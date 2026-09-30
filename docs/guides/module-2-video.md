# Module guide: Video

> Status: Module 2 is being built. Part A is done: the building blocks for video clips,
> talking-avatar clips and voiceovers, the "agent step" commands, and the video plan format.
> The `ca video` command that makes a finished video comes in a later part.

## What it does

It will turn a plain-English request ("a 30-second Instagram Reel about our new coffee") into
a finished vertical video (1080×1920) with a voiceover and captions, saved in its own dated
folder with a `details.json` record of every step, like the image jobs in Module 1.

A video is made of **scenes** (each 15 seconds or less). Each scene is one of:

- **video**: a generated clip (Higgsfield), optionally starting from one of your Module 1 images;
- **avatar**: a talking avatar reading part of the script (HeyGen);
- **image**: a still image.

The voiceover is made by ElevenLabs, and its word timings are turned into captions.

## What was built

- **Three building blocks**, one each for video clips, avatar clips and voiceovers. Each can
  use a real provider or a free **mock** (placeholder) provider, so you can try everything
  without spending credits:
  - mock video/avatar: a coloured clip that shows the scene text, at the right length and shape;
  - mock voice: a quiet tone as long as the script would take to say, with made-up word timings.
- **ElevenLabs voice**: real voiceovers with the time of every word, saved as `voice.mp3`,
  plus captions (`captions.srt`). Temporary ElevenLabs errors (busy, server trouble) are retried.
- **Agent steps**: Higgsfield and HeyGen are used through Codex (it calls them for you with
  your plan credits). When a job reaches such a step it **pauses** (`awaiting_agent`) and writes
  a request file saying exactly what to make. Codex makes the clip, then records it with
  `ca job complete`, or records a problem with `ca job fail`.
- **Time limit**: a step that waits longer than `AGENT_STEP_TIMEOUT_MIN` minutes (default 30)
  is marked failed the next time `ca job status` runs.
- **Safety rules**: a job is never marked completed while a step is unfinished or a file is
  missing; a failed or timed-out step makes the whole job "failed".
- **Video plan (`plan.json`)**: the plan Codex writes before anything is made (hook, script,
  call to action, voice, scenes). It is checked first, and every problem is listed in plain
  words, so a bad plan never spends credits. A scene over 15 seconds is refused.

## One-time setup

1. Module 1 setup (see [Module 1: Images](module-1-images.md)).
2. Nothing else is needed for the free mock providers.
3. For real voiceovers (later LIVE task): in `.env` set `VOICE_PROVIDER=elevenlabs`,
   `VOICE_MODEL=eleven_multilingual_v2`, `ELEVENLABS_VOICE_ID=<your voice ID>` and your
   `ELEVENLABS_API_KEY`. Never paste the key into chat.
4. Higgsfield and HeyGen are connected in Codex in a later part.

## How to use

Making a full video with `ca video` comes in a later part. For now, the job commands below are
what Codex uses when a job pauses for an agent step.

### Example Codex requests

- "What's the status of the job in outputs/2026-09-30/1405_coffee-reel?"
- "The Higgsfield clip for scene-2 is saved in Downloads; record it for that job."
- "HeyGen failed for scene-1; mark it failed with the error message."

## Commands

| Command | What it does |
| --- | --- |
| `uv run ca job status <job folder>` | Shows the job and every step; marks steps that waited too long as failed. |
| `uv run ca job complete <job folder> --step scene-1 --file <path>` | Records the clip for a waiting step (the file is copied into the job folder). Optional: `--provider-job-id`, `--credits`. |
| `uv run ca job fail <job folder> --step scene-1 --error "what happened"` | Records a failed step; the job ends as failed. |

## Outputs

Each video job gets a folder `outputs/YYYY-MM-DD/HHmm_<name>/` containing:

| File | What it is |
| --- | --- |
| `details.json` | The record: status and every step (`stepId`, `capability`, `provider`, `mode`, `status`, `file`, `providerJobId`, `creditsUsed`, `error`). |
| `voice.mp3` | The voiceover. |
| `voice-timings.json` | When each word is spoken. |
| `captions.srt` | Captions made from the word timings. |
| `requests/scene-N.json` | What Codex is asked to make for an agent step (prompt, length, shape, start image, which tool). |
| `clips/scene-N.mp4` | One clip per scene. |
| `plan.json`, `script.md`, `final.mp4` | Added in later parts. |

Job status can be `queued`, `processing`, `awaiting_agent` (paused for Codex),
`completed`, `failed` or `cancelled`.

## Settings

| Setting | Meaning |
| --- | --- |
| `VIDEO_PROVIDER`, `VIDEO_MODEL` | Video clips: `mock` for now (Higgsfield comes later). |
| `AVATAR_PROVIDER`, `AVATAR_MODEL`, `HEYGEN_AVATAR_ID` | Avatar clips: `mock` for now (HeyGen comes later). |
| `VOICE_PROVIDER`, `VOICE_MODEL` | Voiceover: `mock` or `elevenlabs` (model e.g. `eleven_multilingual_v2`). |
| `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` | ElevenLabs key (only in `.env`) and default voice. |
| `AGENT_STEP_TIMEOUT_MIN` | Minutes an agent step may wait before it is marked failed (default 30). |

## Costs and limits

- Mock providers are free.
- ElevenLabs uses your plan credits (about one credit per character of script); the credits
  used are saved in `details.json` as `creditsUsed`.
- Scenes are at most 15 seconds; a whole video at most 90 seconds.

## Troubleshooting

- **"No details.json in …"**: pass the job folder itself (the one that contains `details.json`).
- **"Step 'scene-1' is completed, not awaiting_agent"**: that step was already recorded.
- **"This job is already failed"**: the job stopped (a step failed or timed out); start a new job.
- **"ELEVENLABS_API_KEY missing"** or **"No voice ID"**: add them to `.env`.
- **"plan.json has N problem(s)"**: fix each listed line in the plan; nothing was spent.

## Switching providers

Change the provider name in `.env` (`VIDEO_PROVIDER`, `AVATAR_PROVIDER`, `VOICE_PROVIDER`) and
its model (`…_MODEL`). Set them back to `mock` to work for free. Adding a new provider takes one
new adapter file plus these two settings.
