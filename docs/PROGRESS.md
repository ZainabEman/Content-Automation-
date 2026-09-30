# Project progress

Log format: `M<n>.T<n>: <title> — YYYY-MM-DD — <result>`

## Log

M1.A: job core + image interface + mock — 2026-09-30 — done; jobs/limits/retry/log, generate_image() + mock, `ca image`, 35 offline tests pass
M1.B: reference library + brand profile — 2026-09-30 — done; refs scan/list/primary, set.json + _resized copies, brand.json draft + `ca brand show`, 52 offline tests pass
M1.B: brand language field — 2026-09-30 — done; brand.json reviewed (English, drafts kept), primary photos set to 1, 2, 6, 7
M1.C1: workflows + playbook — 2026-09-30 — done; ca refs frames, 3 workflows + prompt builder, ca image --workflow, Make images playbook, 70 offline tests pass
M1.C2: Gemini adapter + fixes — 2026-09-30 — done; Gemini Interactions adapter (fake-client tests, no live call), mock excluded from daily limit, 3 spread style refs, --dry-run; 93 offline tests pass
M2.A: agent steps + video/voice foundation — 2026-09-30 — done; awaiting_agent + steps[] + ca job status/complete/fail (timeout), video/avatar/voice interfaces + ffmpeg mocks, ElevenLabs timestamps adapter + SRT helper (fake-client check, no live call), plan.json schema; ruff/mypy clean, smoke ok
