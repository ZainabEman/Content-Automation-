

# Module 2 — Video & Voice Branch
Status: build with mocks; live tests use existing Higgsfield / HeyGen / ElevenLabs plan credits.

> Implementation mapping: use Python 3.13 with uv/`pyproject.toml`, type hints with mypy strict, Pydantic schemas, and the `ca` CLI instead of Node/npm tooling.

## Goal
Turn a plain-English request into a finished short vertical video (UGC ad, Reel/Short, podcast clip), saved to the shared folder with full traceability and documented for the team.

## In scope
- Interfaces: generate_video() src/content_automation/ai/video/__init__.py, generate_avatar_video() src/content_automation/ai/avatar/__init__.py, generate_voice() src/content_automation/ai/voice/__init__.py.
- Adapter modes: "code" (called by our app) and "agent" (Codex calls the MCP tool; the app records the result).
- Adapters: higgsfield-mcp (agent), heygen-mcp (agent), elevenlabs (code), mock for each.
- Agent-step framework: job pauses as awaiting_agent; job:complete / job:fail / job:status commands; timeout; retry once.
- plan.json written by Codex (hook, script, scenes), validated before any credits are spent.
- Workflows: ugc_ad, reel_short, podcast_clip. M1 images can be used as scene start frames.
- Assembly with FFmpeg: clips + voiceover + burned-in captions → final.mp4 (1080×1920, H.264/AAC).
- Codex playbook "Make videos" in AGENTS.md.
- Module guide docs/guides/module-2-video.md (same template as M1) + docs/providers/*.md (MCP tool notes), linked from docs/README.md.

## Out of scope
Research-driven topics (M3) · auto-posting · background music · episodes over 90s · automating avatar/voice cloning (done by hand on the providers' websites) · Higgsfield/HeyGen paid APIs (future adapters) · editing UI.

## User flow
1. Ask Codex: "30-sec Instagram Reel about <topic>, use yesterday's café image".
2. Codex writes plan.json and runs `uv run ca video -- --plan <file>`.
3. The app makes the voice (ElevenLabs), then pauses at each agent step and prints what's needed.
4. Codex calls Higgsfield/HeyGen via MCP, waits, saves each clip, and runs `uv run ca job:complete -- …`.
5. The app assembles final.mp4; Codex replies with the folder path and a summary.

## Data
- plan.json {workflowId, platform, durationSec, hook, script, cta, voice{voiceId},
  scenes[{n, type: video|avatar|image, prompt, startImageAssetId?, durationSec ≤15, onScreenText?}]}
- Job folder `OUTPUT_DIR/YYYY-MM-DD/HHmm_<slug>/` (default `OUTPUT_DIR=outputs`): plan.json, script.md, voice.mp3, captions.srt,
  requests/scene-N.json, clips/scene-N.mp4, final.mp4, details.json
  (M1 fields + steps[{stepId, provider, mode, status, file, providerJobId, creditsUsed}]).
- Job states add awaiting_agent.

## Integrations / APIs
- Higgsfield MCP https://mcp.higgsfield.ai/mcp — OAuth, plan credits, clips ≤15s.
- HeyGen remote MCP https://mcp.heygen.com/mcp/v1/ — OAuth, web-plan premium credits.
- ElevenLabs API — text-to-speech with timestamps (→ captions.srt); plan credits.
- FFmpeg via imageio-ffmpeg (no manual install).
- Env: `VIDEO_PROVIDER=mock`, `VIDEO_MODEL`, `AVATAR_PROVIDER=mock`, `AVATAR_MODEL`, `HEYGEN_AVATAR_ID`,
  `VOICE_PROVIDER=mock`, `VOICE_MODEL`, `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID`, `AGENT_STEP_TIMEOUT_MIN`, and `OUTPUT_DIR=outputs`.

## Acceptance criteria
- [ ] `uv run pytest` passes offline with every provider set to mock.
- [ ] Import-boundary test covers the video, avatar and voice entry files.
- [ ] An invalid plan.json gives a clear list of problems; nothing is spent.
- [ ] A scene over 15s is split or refused before any provider call.
- [ ] Each workflow (mock) creates final.mp4 (plays, 1080×1920), voice.mp3, captions.srt, script.md, and a details.json marked "completed".
- [ ] Agent step: the job pauses at awaiting_agent; job:complete resumes it; job:fail or a timeout ends as "failed", never "completed".
- [ ] An M1 image used as a start frame is linked by assetId in details.json.
- [ ] ElevenLabs: fake-response tests pass, plus one live 10-second voice test.
- [ ] MCPs verified: tool lists plus one tiny live test each, documented in docs/providers/ with credits used.
- [ ] Live end-to-end: you and your social media manager each ask Codex for a 30-sec Reel and get final.mp4 in the shared folder.
- [ ] docs/guides/module-2-video.md has every template section, and your social media manager can follow it alone; docs/README.md links it.

## Tasks
Every task updates the guide sections for what it built.
- M2.T1 Connect Higgsfield + HeyGen MCPs in Codex; list tools; tiny live tests; write docs/providers/*.md.
- M2.T2 Agent-step framework: modes, awaiting_agent, job:complete/fail/status, resume, timeout + tests.
- M2.T3 Video/avatar/voice interfaces, registry, mocks, import-boundary tests.
- M2.T4 ElevenLabs adapter + captions (SRT) + tests + one live short test.
- M2.T5 Higgsfield + HeyGen agent adapters (request files + playbook steps from T1 docs).
- M2.T6 FFmpeg assembly (clips + voice + captions → final.mp4) + tests with mock clips.
- M2.T7 plan.json schema + ugc_ad / reel_short / podcast_clip + `uv run ca video`; end-to-end mock test.
- M2.T8 "Make videos" playbook in AGENTS.md; finish the guide; live end-to-end test by you and your social media manager.
