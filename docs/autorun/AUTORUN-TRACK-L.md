# AUTORUN LITE — Track L: Roman LoRA → ComfyUI/RunPod production
Save as `docs/autorun/AUTORUN-TRACK-L.md`. This file is the spec. Don't write a PRD.

## 0. Run rules (same as Phase 10)
- Read only this file + the last LOG entry. Use Grep for lookups; no subagents. Do steps in order with no pauses. **Resume:** continue at the first step not DONE in LOG.md.
- **Per step:**
  1. Implement the minimum.
  2. Add 1 basic test per new command or check.
  3. Run `uv run ruff check <changed> && uv run pytest <new tests> -q`.
  4. Commit `track L step <M>: …` only if the exit code is 0.
- After every step, add a 2-line LOG entry and print `L<M> done <hash>` in chat and nothing else.
- **Full check once at the end:** `uv run ruff check . && uv run mypy --strict <usual targets> && uv run pytest -q`.
- **Hard rules:**
  - no paid calls: RunPod jobs, endpoint creation and uploads are the user's manual steps
  - never read or print `.env` or `.secrets/`
  - never commit the LoRA, photos or `outputs/`
  - never push
  - skills never say "ok" for the user
  - no InsightFace, no FLUX
  - no silent fallback
- **Allowed free calls:** a GET of the Hugging Face file listing for `Comfy-Org/z_image_turbo`, and one GET to find BfDI's current press feed.
- Branch: `track-l-lora` from `main`. First commit the uncommitted `docs/autorun/LOG.md` and `REPORT-PHASE-10.md` there.
- **Stop only if:** a paid call, a secret or a manual user action is needed; checks still fail after 2 tries; or data would be deleted.

## 1. Facts
- **LoRA file:** `outputs/lora/zimage/r0man_bg_v2_step3000.safetensors`.
  - About 85 MB, with a MANIFEST.json next to it.
  - Keys `diffusion_model.layers.N.*` (ComfyUI format).
- **Base model:** Z-Image Turbo (`z_image_turbo_bf16.safetensors`, plus the Qwen3-4B text encoder and the VAE from the Comfy-Org split files).
- **Inference settings:** 9 steps, CFG 1.0, about 1024 px. LoRA strength 1.0 by default, 0.8 for group scenes.
- **Prompt rules:**
  - Start every person prompt with `r0man_bg, a man, ` then describe the outfit and scene.
  - Don't put screens, signs or posters in the scene (the trigger word can appear as text).
  - Prefer Roman alone in the frame.
  - The app draws all text itself.
- **Already built (Phase 2, never run live):**
  - `ai/image/providers/comfyui.py` + `runpod.py`
  - `config/comfyui.json`
  - `config/comfyui/workflows/z_image_turbo.json` + its mapping
  - `ca lora set`
  - The adapter refuses person images until a LoRA is set.
- **Settled:** Nano Banana/OpenRouter is a configured fallback, **off by default**. It's offered only as a separate dry-run line and used only with "ok". This replaces the old "fallback until Phase 4" note.

## 2. Step 1: register the LoRA + check the workflow and sizing
- Run `uv run ca lora set zimage outputs/lora/zimage/r0man_bg_v2_step3000.safetensors` (local only). Record the sha256 from MANIFEST.json in config.
- Check `z_image_turbo.json` and fix it if needed:
  - a LoraLoader (model-only) node referencing the LoRA filename from config
  - strength from config (default 1.0)
  - 9 steps, CFG 1.0
  - 1024 px default size, with size per deliverable
  - the person prompt gets the trigger prefix automatically
  - no-person prompts don't get the LoRA (strength 0, or the node bypassed)
- **Prompt builder:**
  - strips or blocks scene words that ask for screens, signs or posters in person images
  - "group" scenes use strength 0.8 (config)
- Get the real Z-Image filenames from the HF listing. Put them, plus the exact volume paths the workflow expects, in `config/comfyui.json` under `models`.
- Resize the planned RunPod setup in config/docs to a 24 GB GPU class and a ~30 GB network volume (the 48 GB / 75 GB sizes were for the dropped Qwen-Image). Mark them "check current RunPod prices".
- **BfDI:** find the current press/RSS URL with one GET. If it works, enable it; otherwise leave it disabled with a note.

## 3. Step 2: person check + one automatic redo + ad strict check + provider switch
- **Automatic face check** (free and local): OpenCV Haar cascade (`opencv-python-headless`, Apache 2.0).
  - Exactly 1 face for "Roman alone" scenes, ≥1 for group scenes.
  - The face box must not sit in the text-overlay zone.
- **Visual check by Codex:** the make-content skill opens the image next to 2 reference photos from `assets/reference/identity/person_01/` and judges:
  - does it look like Roman
  - is there no stray text or trigger word visible
  - are the hands and face free of obvious defects
  - It records the result with `ca job review <job> --person pass|fail "<reason>"` (extend the existing `ca job review`). Codex never passes an image it didn't look at.
- **One automatic redo:**
  - On a face-check fail or a Codex fail, the job redoes once with redo_n+1 and a new seed.
  - The redo is only allowed if the dry run already included it. The dry-run max = 2 images per person deliverable.
  - A second fail → status failed, the reasons are shown, and the user is offered: retry (new dry run) or the no-person version.
- **Facebook ads (strict):**
  - both checks must pass
  - the Phase 7 ad copy strict check must pass
  - never a fallback provider for ads
- **Provider switch:**
  - `--provider comfyui|openrouter|mock` per run
  - default per deliverable in `config/deliverables.json`: comfyui for person posts
  - the phrase "use comfyui" / "use the fallback" → the skill adds `--provider`
  - the fallback is only ever the offered dry-run line
- Add the phrases to AGENTS.md and help.

## 4. Step 3: RunPod setup guide + verification + finish
- Write `docs/guides/runpod-zimage-setup.md` (one page, numbered, for the user):
  1. create the network volume (~30 GB, a region that has the GPU)
  2. upload the diffusion model, text encoder, VAE and LoRA to the exact paths from config (`models/diffusion_models/…`, `models/text_encoders/…`, `models/vae/…`, `models/loras/r0man_bg_v2_step3000.safetensors`) via RunPod S3 or a temporary pod
  3. create a Serverless endpoint: `runpod/worker-comfyui:5.11.0-base`, 0 active / max 1 worker, idle 5 s, execution timeout 600 s, FlashBoot, volume attached
  4. put RUNPOD_API_KEY, RUNPOD_ENDPOINT_ID, RUNPOD_NETWORK_VOLUME_ID and the S3 keys in `.env`, **by name only**
  5. in Codex: "make a linkedin post about <topic> with Roman" → check the dry run → "ok"
  6. compare the likeness with real photos and try strength 0.8 vs 1.0 (`ca lora strength 0.9`, a config write logged in the audit)
  7. run `ca verify record comfyui --live pass|fail "<note>"`
  8. after 5–10 images: `ca costs calibrate --provider comfyui`
  - Include "if likeness is poor: 5–10 close-ups taken by someone else, retrain at 768–1024 px on a RunPod GPU".
- `ca verify run comfyui`: the offline checks (LoRA set + sha256 matches, workflow has the LoRA node, env names present without printing values, the endpoint ID format). Update the "blocked: LoRA track" note to "live pending (user setup)".
- Add `ca lora strength <0.5–1.2>` if it doesn't exist.
- Run the full check (§0).
- Write `docs/autorun/REPORT-TRACK-L.md` (max 15 lines): commits, test total, needs-review, and the user's next steps (the guide). Stop. **Don't merge to main.**
