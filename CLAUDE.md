# Content Automation v2

Python CLI (`uv run ca …`) that turns research (Gmail newsletters and user topics) into
social content: copy, branded images (Nano Banana 2 via OpenRouter) and videos (Higgsfield,
HeyGen), with approval and cost-approval gates and one job folder per output. v2 adds a
content calendar with approval, LinkedIn, Google Drive folders with a tracking CSV, ComfyUI
images with Roman's identity, and Higgsfield animated Instagram carousels. Plan:
docs/ROADMAP-v3.md; spec per phase: docs/phases/PHASE-<n>-PRD.md (the v2 docs/PRD.md is replaced).
v5 (docs/PRD-v5-german-brand-youtube.md, notes: docs/v5-implementation-notes.md): German for
everything the audience sees; layout variants from the approved company graphics only (the
competitor archive is never read); 4 categories (Instagram carousel, Facebook post, Facebook ad,
LinkedIn); requires_roman → RunPod LoRA, else OpenRouter; `ca plan month`; `ca youtube` for
research and production planning; UGC, podcast and finished-video generation removed.

## Rules

- Codex Desktop is the controller; all user commands are typed in Codex.
- Inspect current code before changing it; preserve research, copywriting, approval,
  cost-approval and folder logic.
- No paid generation without an approved cost estimate shown first.
- Keep Nano Banana 2/OpenRouter available; decision in Phase 10 (roadmap v3).
- No automatic publishing in v1.

## Workflow

Read docs/PROGRESS.md first. Read only the docs/phases/PHASE-<n>-PRD.md section for the current
step. ruff + mypy --strict + offline pytest must pass before every commit; never call paid or
external services in tests. Never print whole files; end each step with a summary of max 5 lines.
