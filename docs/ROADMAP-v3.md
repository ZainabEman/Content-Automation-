# Roadmap v3 (13 Oct 2026)
Each phase gets its own PRD in docs/phases/ before building, then about 4–7 build steps (one Claude Code prompt each). Every phase ends with: new or updated Codex skills + AGENTS.md phrases, ruff + strict mypy + offline pytest, a mock end-to-end run, PROGRESS.md updated, a commit on the phase branch.

| Phase | Name | Main spec items | Depends on |
|---|---|---|---|
| 4 | Content-item foundation | UC-01, 07, 09, 15 (model), 17, 20/21 (framework), audit log, BR-03/09/10/11 | Phase 3 |
| 5 | Strategy, research and idea backlog | UC-02, 03, 04, 05, 06 (calendar v2: new platforms, cadence for the monthly targets, dependencies, content-language config) | 4 |
| 6 | Editorial formulas, scripts and briefs | UC-08: graphics/social, carousel, YouTube, podcast formulas; production briefs; a source ref for each claim | 5 |
| 7 | Review gate and finishing graphics/carousels | UC-10 (non-LoRA parts), 11 (format choice), 15, 16 (upload only approved assets; new Drive folders; plugin vs API decision), 20 (retry within budget); first paid Higgsfield test + cost calibration | 6 |
| 8 | YouTube long-form and podcasts | UC-12, 14; production statuses; import of human-made files (recordings, edits); HeyGen voice | 7 |
| 9 | Short clips and distribution | UC-13 (Opus Pro API or manual handoff/import), UC-18 (per-platform prep; ready/published/failed + URL; manual publishing by default) | 8 |
| 10 | Reporting, verification and release | UC-19, UC-21 (resume all), spec §7 tests of the 12 integrations, Nano Banana decision, optional packaging of the skills as a Codex plugin, merge branches | all |
| L (parked) | LoRA/ComfyUI integration | pick the checkpoint, `ca lora set`, RunPod live, Phase 2 Step 6 wiring (person check + 1 redo, ad check, authorized fallback), strength tuning | training done + RunPod credit; best after 7 |
