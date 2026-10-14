# Autorun report: Phase 10 (2026-10-14)
Commits: a19fffd (S1 `ca report month`, `ca jobs resume --all`) · c65274b (S2 `ca verify`, docs/VERIFICATION.md) · 56fe914 (S3 docs/USER-GUIDE.md). phase-10-release was fast-forwarded into main at 56fe914. Nothing pushed.
Full check: ruff OK, mypy --strict 180 files OK, pytest 377 passed (all offline). The offline results below come from a sandbox run (a scratch copy of config/). The real registry has no verification rows yet; say "verify <integration>" to record them.
Needs review: a final counts in the month its last status event was recorded; podcasts are counted against the podcasts planned that month. resume --all prints the build command for queued image jobs under an open authorization instead of running it. "Operational" means the newest live result is a pass.
Client questions: does this 12-item list match spec §7 (the spec's §7 list is not in the repo)? Confirm the report targets (clips 32–40, graphics 30–60, 100% reviewed before publishing). Keep the Nano Banana/OpenRouter fallback (off by default)? Which HeyGen avatar and voice IDs?
| Integration | Status |
|---|---|
| codex: Codex skills/CLI | offline ok / live pending |
| gmail: Gmail plugin | offline ok / live pending |
| web-fetch: web research fetch | offline ok / live pending |
| higgsfield: Higgsfield plugin | offline ok / live pending |
| heygen: HeyGen plugin | offline ok / live pending |
| comfyui: ComfyUI/RunPod | offline ok / live pending (blocked: LoRA track) |
| openrouter: OpenRouter (Nano Banana fallback) | offline ok / live pending (client decision) |
| drive: Google Drive (API or plugin) | offline ok / live pending |
| tracker: tracker Sheet | offline ok / live pending |
| opus-pro: Opus Pro (manual) | offline ok / live pending |
| ffmpeg: FFmpeg media | offline ok / live pending |
| publishing: publishing (manual URL) | offline ok / live pending |
