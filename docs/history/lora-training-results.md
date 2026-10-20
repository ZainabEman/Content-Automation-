# Roman LoRA (Z-Image Turbo): training runs and results (updated 14 Oct 2026)

## Current choice: v2, step 3000
- File: `r0man_bg_v2_step3000.safetensors` (about 85 MB; on Kaggle the final file is named `r0man_bg_v2_z_image_turbo.safetensors`, without a step number).
- Place in the repo at `outputs/lora/zimage/` (git-ignored), then `uv run ca lora set zimage outputs/lora/zimage/r0man_bg_v2_step3000.safetensors`.
- Trigger: `r0man_bg, a man`. Base model: Z-Image Turbo (ComfyUI weights `z_image_turbo_bf16.safetensors`). Inference: 9 steps, CFG 1.0, strength 0.8-1.0.
- Chosen as the best so far by the user's likeness check. A full 1024 px checkpoint comparison (steps e.g. 1500/2400/3000, strengths 1.0/0.8) is still optional.

## v2 run (real photos only)
- Dataset: 17 real photos -> 29 training images: 5 green-screen selfies (2, 4, 5, 6, 9), garage 48/51 and gym 54 (full-resolution originals, weighted x2), 9 street photos 56-64 (1200x1600 originals); each non-selfie also used as a head-and-shoulders crop. All AI-generated images excluded.
- Training: ai-toolkit f7a1fb9a, rank 16 / alpha 16, AdamW lr 1e-4, bf16, qfloat8 base, cached text embeddings, 512 px, batch 1. Session 1: 0-1500 (8.5 h); session 2 resumed from checkpoint 1400 to 3000 (9.9 h). Loss steady 0.36-0.45, no NaN. Kaggle account `rayhan1111`, dataset `roman-pics`.
- At 1500 steps the haircut/build were learned but the face varied between samples (undertrained); continuing to 3000 was the fix.

## v1 run (superseded)
- 22 photos, of which 17 appear AI-generated -> learned the AI look (darker hair, smoother skin, bulkier build). Kept only as a fallback (step 1100).

## Known issues for production prompts
- The trigger word can appear as visible text on screens/signs. Avoid text surfaces or ask for a blank screen; the app renders real text as an overlay.
- In crowd scenes other people may pick up his look. Prefer Roman alone; try strength 0.8 for group shots.

## Inference notes
- Loads in plain diffusers (`ZImagePipeline.load_lora_weights`), keys `diffusion_model.layers.N.*`: standard ComfyUI-style format.
- On a 16 GB T4 the bf16 model needs block offloading (about 5 min/image). On RunPod (48 GB) no such limit.

## If likeness needs to improve further
1. 5-10 sharp close-up photos of his face taken by someone else, different angles.
2. Train at 768-1024 px on a bigger GPU (RunPod, about $5).
