# RunPod + ComfyUI setup (IMAGE_PROVIDER=comfyui)

The app sends a ComfyUI workflow (API format) to a RunPod Serverless endpoint running
[runpod-workers/worker-comfyui](https://github.com/runpod-workers/worker-comfyui) and gets the
image back as base64. The models live on a RunPod network volume. Nothing runs on this PC.

Keep `IMAGE_PROVIDER=openrouter` (Nano Banana) until the comparison run in Phase 2 Step 5 has
passed. The app never switches provider by itself: a failed ComfyUI job fails and says so.

Items marked **unverified** were not confirmed on an official page; check them while setting up.

## 1. Network volume

RunPod → Storage → New Network Volume.

- **Region:** one that offers 48 GB GPUs (L40, L40S, RTX 6000 Ada) for Serverless. The endpoint
  must be in the same region.
- **Size:** 75 GB. The models are about 50 GB together (estimate), plus the LoRAs and some room.
  The cost is $0.07 per GB per month, so about $5.25 a month.

Folder layout on the volume. Serverless workers see it at `/runpod-volume`; a Pod sees the same
volume at `/workspace`.

```
models/
  unet/            qwen_image_2512_fp8_e4m3fn.safetensors   (Qwen-Image-2512 diffusion model)
                   z_image_turbo_bf16.safetensors           (Z-Image Turbo diffusion model)
  clip/            qwen_2.5_vl_7b_fp8_scaled.safetensors    (Qwen-Image text encoder)
                   qwen_3_4b.safetensors                    (Z-Image text encoder)
  vae/             qwen_image_vae.safetensors               (Qwen-Image VAE)
                   ae.safetensors                           (Z-Image VAE)
  loras/           the person's LoRAs (section 7), named as loraName in config/comfyui.json
  upscale_models/  only if upscaleNode.enabled (pick an upscaler whose licence allows
                   commercial use)
```

ComfyUI's own docs name these folders `diffusion_models/` and `text_encoders/`. The
worker-comfyui customization guide lists the older names `unet/` and `clip/`, which ComfyUI
reads for the same purpose. **Unverified:** whether the worker also maps the new names on the
volume. Worker 5.11.0 checks every model file before it runs a workflow and lists the missing
ones. If it reports a file as missing, move it to `diffusion_models/` or `text_encoders/`.

## 2. Copy the models onto the volume

1. Deploy the cheapest Pod that can attach the volume, then open its web terminal.
2. Create the folders:
   `mkdir -p /workspace/models/{unet,clip,vae,loras}`
3. Download each file with `wget -O <folder>/<file> <link>`. Copy the links from the official
   ComfyUI pages:
   - [Qwen-Image-2512](https://docs.comfy.org/tutorials/image/qwen/qwen-image-2512): fp8
     diffusion model, `qwen_2.5_vl_7b_fp8_scaled`, `qwen_image_vae`.
   - [Z-Image Turbo](https://docs.comfy.org/tutorials/image/z-image/z-image-turbo):
     `z_image_turbo_bf16`, `qwen_3_4b`, `ae`. The diffusion model is at
     `https://huggingface.co/Comfy-Org/z_image_turbo/resolve/main/split_files/diffusion_models/z_image_turbo_bf16.safetensors`.
4. Check the sizes with `ls -lh /workspace/models/*`, then **terminate the Pod**. It is billed
   while it runs.

The file names must match the workflows in `config/comfyui/workflows/*.json`.

## 3. Serverless endpoint

RunPod → Serverless → New Endpoint → Docker image.

| Setting | Value |
|---|---|
| Container image | `runpod/worker-comfyui:5.11.0-base` (the release checked on 2026-10-10) |
| GPU | 48 GB (L40, L40S, RTX 6000 Ada) |
| Active (minimum) workers | 0 (nothing runs, and nothing is billed, between jobs) |
| Max workers | 1 |
| Idle timeout | 15 s, the same value as `idleSeconds` in config/comfyui.json (see section 5) |
| Execution timeout | 600 s (matches `timeoutSeconds`; the app cancels the job then) |
| FlashBoot | on |
| Network volume | the volume from step 1 |
| Environment | none. Without S3 settings the worker returns images as base64. |

**Unverified:** that the ComfyUI inside `5.11.0-base` is new enough for Qwen-Image-2512 and
Z-Image, which need a ComfyUI release from late 2025 or newer. If the first test run reports
an unknown node or model type, build your own image `FROM runpod/worker-comfyui:5.11.0-base`
with an updated ComfyUI. See the worker's `docs/customization.md`.

## 4. .env

```
RUNPOD_API_KEY=...        # RunPod → Settings → API Keys (if possible, limit it to this endpoint)
RUNPOD_ENDPOINT_ID=...    # shown on the endpoint page
COMFYUI_CONFIG_FILE=config/comfyui.json
```

Then run `uv run ca doctor`. It checks the keys, `config/comfyui.json` and both workflows. Until
Step 4 sets `loraName` and `triggerWord`, it warns that images with the person will be refused.

To use ComfyUI (only after Step 5), set `IMAGE_PROVIDER=comfyui` and
`IMAGE_MODEL=qwen_image_2512` or `IMAGE_MODEL=z_image_turbo`.

## 5. Cost

`config/comfyui.json` holds the GPU class, the price per second, the estimated seconds per image
for each model, the cold start and the idle time.

- **One cold start per package:** a package build sends all of its images to RunPod
  back-to-back, so one warm worker makes them, and only then are the person checks shown. The
  estimate counts one cold start + idle per build. A redo after a failed check is a new build,
  with its own cold start.
- **Idle timeout:** keep the endpoint's idle timeout and `idleSeconds` the same. 15 s (the
  default) leaves room for the few seconds the app needs between images (text, logo, saving).
  Lower is cheaper after the last image, but the next image may then find the worker cold.
  Higher wastes up to that many seconds after every build.
- **Dry run:** shows the cost marked "estimate": images × seconds per image × price, plus one
  cold start + idle per package.
- **After each job:** details.json stores RunPod's `delayTimeMs` and `executionTimeMs` in
  `providerMetrics`, and the actual cost is (delay + execution) × price. Queue time is counted,
  but the idle time after the last image and the gaps between images are not. The RunPod
  billing page has the exact amount.
- **Build summary:** shows the actual and the estimate side by side. Update `secondsPerImage` and
  `coldStartSeconds` from those numbers after the first runs.

## 6. When something goes wrong

- **Timeout:** the job is cancelled on RunPod, so the GPU stops billing. The app reports it and
  does not retry.
- **Worker error or empty output:** the job fails with RunPod's message and the RunPod job ID.
- **A file is missing on the volume:** worker 5.11.0 names it before running. Fix the folder or
  the file name.
- **Nano Banana instead:** set `IMAGE_PROVIDER=openrouter` yourself, then run a new dry run for
  the cost. The app never falls back on its own.

## 7. Train Roman's LoRA on RunPod

This uses Ostris AI Toolkit (MIT) on a temporary Pod that writes to the same network volume.
Do it only after the written consent is on file and the cost estimate from step 3 has an "ok".

1. Put `CONSENT.md` in `assets/reference/identity/person_01/`, with `Name:`, `Date:` (YYYY-MM-DD)
   and `Scope:` covering training and cloud upload. Optionally add more photos in `extra/` and
   short captions in `captions.json` (`{"3.jpg": "navy suit, office"}`).
2. Run `uv run ca lora prepare`. It checks the photos and writes
   `outputs/lora/dataset_<date>.zip`. For a face the detector missed, check it by eye and add
   `--keep <file>`.
3. Run `uv run ca lora config --model qwen` (and `--model zimage`). It writes
   `outputs/lora/r0man_bg_<workflow>.yaml` and prints the Pod estimate. Get the user's "ok".
4. RunPod → Pods → Deploy, using the AI Toolkit template linked in the AI Toolkit README
   (template `0fqzfjy6f3`). Pick an L40S 48 GB in the volume's region, attach the network volume
   (it mounts at `/workspace`) and set the container disk to 150 GB. The base models are
   downloaded there.
5. Open the Pod's JupyterLab or the AI Toolkit UI file upload and upload the zip and the YAML to
   `/workspace/lora/`.
6. In the Pod terminal:
   `mkdir -p /workspace/lora/datasets && unzip /workspace/lora/dataset_<date>.zip -d /workspace/lora/datasets/`
7. **Unverified:** whether the template keeps its Hugging Face cache under `/workspace`. If it
   does, run `export HF_HOME=/root/.cache/huggingface` first, so the base models (about 60 GB)
   do not fill the volume.
8. Train from the AI Toolkit folder: `python run.py /workspace/lora/r0man_bg_qwen_image_2512.yaml`.
   Or open the UI on port 8675 and paste the YAML into a new job's advanced config. If the model
   does not load (the `arch` value is unconfirmed), pick the model's preset in the UI and copy
   its model block into the YAML.
9. Every 250 steps, check the sample images in
   `/workspace/lora/output/r0man_bg_qwen_image_2512/samples/` against Roman's photos. If a
   checkpoint already looks right, stop with Ctrl+C (not while it is saving) and use that
   checkpoint.
10. Copy the result where the worker reads it:
    `mkdir -p /workspace/models/loras && cp /workspace/lora/output/r0man_bg_qwen_image_2512/r0man_bg_qwen_image_2512.safetensors /workspace/models/loras/`
11. For Z-Image, repeat steps 8–10 with `r0man_bg_z_image_turbo.yaml` on the same Pod.
12. Optional: delete `/workspace/lora/datasets` and `/workspace/lora/output`. The volume then
    keeps only the LoRAs, not Roman's photos.
13. **Terminate the Pod** (Pods → ⋮ → Terminate). Billing continues until you do, and a
    stopped Pod still bills its disk. The LoRAs stay on the network volume.
14. On this PC:
    `uv run ca lora set qwen r0man_bg_qwen_image_2512.safetensors`
    (and `uv run ca lora set zimage r0man_bg_z_image_turbo.safetensors`).
15. Run `uv run ca doctor`. It should show "ComfyUI LoRA: r0man_bg_…". Then do the Step 5
    comparison (paid, after "ok").
