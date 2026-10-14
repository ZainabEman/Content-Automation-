# RunPod setup for Roman's Z-Image LoRA

This is your one-time setup for making images with Roman on RunPod (ComfyUI, Z-Image Turbo and his LoRA). Every step below that costs money is yours to take. The app makes no RunPod call until you have seen a dry run and said "ok". All sizes and prices are estimates, so check current RunPod prices before you start.

1. **Create the network volume.** In RunPod, go to Storage → New Network Volume. Make it about 30 GB, in a region that offers a 24 GB GPU (RTX 4090, L4 or RTX A5000) for Serverless. The models take about 21 GB (12.3 + 8.0 + 0.3 GB) and the LoRA 0.1 GB; the rest is room to spare.
2. **Upload the four files** to the volume, at exactly these paths (they are listed in `config/comfyui.json` under `models`). Use RunPod's S3 API or a small temporary Pod, and stop the Pod when you are done.
   - `models/diffusion_models/z_image_turbo_bf16.safetensors`
   - `models/text_encoders/qwen_3_4b.safetensors`
   - `models/vae/ae.safetensors`
   - `models/loras/r0man_bg_v2_step3000.safetensors`, copied from `outputs/lora/zimage/`. Its sha256 is recorded in config.

   The three model files come from the Hugging Face repo `Comfy-Org/z_image_turbo` (folder `split_files/`).
3. **Create the Serverless endpoint.** Go to Serverless → New Endpoint → Docker image `runpod/worker-comfyui:5.11.0-base`, and set:
   - GPU: 24 GB
   - workers: 0 active, max 1
   - idle timeout: 5 s
   - execution timeout: 600 s
   - FlashBoot: on
   - the network volume from step 1 attached
4. **Fill in `.env`.** Set these by name: `RUNPOD_API_KEY`, `RUNPOD_ENDPOINT_ID`, `RUNPOD_NETWORK_VOLUME_ID`, `RUNPOD_S3_ACCESS_KEY`, `RUNPOD_S3_SECRET_KEY`. Never paste the values into Codex. Then run `uv run ca verify run comfyui`: it checks the LoRA, the workflow and the endpoint ID format, and never shows a value.
5. **Make a first image.** In Codex, say "make a linkedin post about <topic> with Roman". Check the dry run: it shows ComfyUI, the cost and one possible redo. Then say "ok".
6. **Check the likeness.** Compare the image with his real photos. If needed, try `uv run ca lora strength 0.8` against `1.0`. Each change is written to config and logged in the audit. Group scenes use 0.8 automatically.
7. **Record the result:** `uv run ca verify record comfyui --live pass|fail "<what you compared>"`.
8. **Calibrate costs.** After 5–10 images, run `uv run ca costs calibrate --provider comfyui` (add `--apply` only after you have looked at the result).

If the likeness is poor, ask someone else to take 5–10 close-ups of Roman, then retrain the LoRA at 768–1024 px on a RunPod GPU (`docs/guides/runpod-comfyui.md`, section 7).
