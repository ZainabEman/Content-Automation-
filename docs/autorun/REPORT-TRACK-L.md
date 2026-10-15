# Autorun report: Track L, Roman LoRA → ComfyUI/RunPod (2026-10-15)
Commits on `track-l-lora` (from main; not merged, not pushed): 563cfe1 (Phase 10 report and log) · 39f7082 (L1 LoRA, workflow, sizing) · 6279185 (L2 person check, redo, ads, providers) · f1d5065 (L3 guide, verify, strength).
Full check: ruff OK, mypy --strict 185 files OK, pytest 386 passed (all offline). Allowed free calls: the Hugging Face listing (one GET) and the BfDI homepage (one GET).
Needs review: the LoRA was not in `outputs/lora/zimage/`, so `MANIFEST.json` and the step-3000 file were copied there from `Downloads/roman_lora_v2.zip`. Both are git-ignored, and the sha256 matches the manifest.
Needs review: `IMAGE_PROVIDER=mock` now outranks a deliverable's provider (`--provider` still wins). Mock images skip the face check, and the check says so. The dry-run max is the estimate plus one redo per person image. Group scenes are detected by words (group, team, colleagues, audience, crowd).
Needs review: the 24 GB price ($0.00031/s) has not been re-checked. BfDI now points at its current press page, linked from its homepage, but stays disabled because that page was not fetched. Person posts and ads now default to comfyui, so they need the RunPod setup before they can be built.
Side effect: `uv run ca verify run comfyui` was run once on the real registry. It applied migration 10 (backup in `state/backups/`) and recorded an offline pass.
Your next steps (`docs/guides/runpod-zimage-setup.md`):
1. Create a ~30 GB network volume in a region that offers a 24 GB GPU (check current RunPod prices).
2. Upload the four files to the paths listed in `config/comfyui.json` `models` and `models/loras/`.
3. Create the endpoint: `runpod/worker-comfyui:5.10.0-base`, 0/1 workers, idle 5 s, timeout 600 s, FlashBoot, volume attached.
4. Put the RunPod keys in `.env` by name, then run `uv run ca verify run comfyui`.
5. In Codex: "make a linkedin post about <topic> with Roman", check the dry run, then "ok".
6. Compare the likeness, trying `ca lora strength 0.8` against 1.0. Then run `ca verify record comfyui --live pass|fail "<note>"`, and after 5–10 images `ca costs calibrate --provider comfyui`.
