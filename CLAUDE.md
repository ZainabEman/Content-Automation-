# Content Automation v2

Python CLI (`uv run ca …`) that turns research (Gmail newsletters and user topics) into
social content: copy, branded images (Nano Banana 2 via OpenRouter) and videos (Higgsfield,
HeyGen), with approval and cost-approval gates and one job folder per output. v2 adds a
content calendar with approval, LinkedIn, Google Drive folders with a tracking CSV, ComfyUI
images with Roman's identity, and Higgsfield animated Instagram carousels. Full spec: docs/PRD.md.

## Rules

- Codex Desktop is the controller; all user commands are typed in Codex.
- Inspect current code before changing it; preserve research, copywriting, approval,
  cost-approval and folder logic.
- No paid generation without an approved cost estimate shown first.
- Keep Nano Banana 2/OpenRouter available until its replacement passes Phase 4 tests.
- No automatic publishing in v1.

## Workflow

Read docs/PROGRESS.md first. Read only the PRD section for the current step. Do not write or
run tests until Phase 4; a syntax/import check is enough. Never print whole files; end each
step with a summary of max 5 lines.
