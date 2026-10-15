# RunPod + ComfyUI setup (IMAGE_PROVIDER=comfyui)

The app sends a ComfyUI workflow (API format) to a RunPod Serverless endpoint running
[runpod-workers/worker-comfyui](https://github.com/runpod-workers/worker-comfyui) and gets the
image back as base64. The models live on a RunPod network volume. Nothing runs on this PC.

Keep `IMAGE_PROVIDER=openrouter` (Nano Banana) until the comparison run in Phase 2 Step 5 has
passed. The app never switches provider by itself: a failed ComfyUI job fails and says so.

Items marked **unverified** were not confirmed on an official page; check them while setting up.

## 1. Network volume

RunPod → Storage → New Network Volume.

- **Region:** one that offers 24 GB GPUs (RTX 4090, L4, RTX A5000) for Serverless,
  and that supports the volume S3 API, which `ca lora train-remote` needs. Supported (2026-10-10):
  EU-CZ-1, EU-RO-1, EUR-IS-1, EUR-NO-1, US-CA-2, US-GA-2, US-IL-1, US-KS-2, US-MD-1, US-MO-1,
  US-MO-2, US-NC-1, US-NC-2, US-NE-1, US-WA-1. The endpoint must be in the same region.
- **Size:** ~30 GB (Track L, Z-Image Turbo only; the 75 GB were for the dropped Qwen-Image). The
  models are about 21 GB (config/comfyui.json `models`), plus the LoRA and some room. Check current
  RunPod prices (it was $0.07 per GB per month, so about $2.10 a month).

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
volume. Worker 5.10.0-base checks every model file before it runs a workflow and lists the missing
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
| Container image | `runpod/worker-comfyui:5.10.0-base` (the release checked on 2026-10-10) |
| GPU | 24 GB (RTX 4090, L4, RTX A5000; Z-Image Turbo only); check current RunPod prices |
| Active (minimum) workers | 0 (nothing runs, and nothing is billed, between jobs) |
| Max workers | 1 |
| Idle timeout | 15 s, the same value as `idleSeconds` in config/comfyui.json (see section 5) |
| Execution timeout | 600 s (matches `timeoutSeconds`; the app cancels the job then) |
| FlashBoot | on |
| Network volume | the volume from step 1 |
| Environment | none. Without S3 settings the worker returns images as base64. |

**Unverified:** that the ComfyUI inside `5.10.0-base` is new enough for Qwen-Image-2512 and
Z-Image, which need a ComfyUI release from late 2025 or newer. If the first test run reports
an unknown node or model type, build your own image `FROM runpod/worker-comfyui:5.10.0-base`
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
- **A file is missing on the volume:** worker 5.10.0-base names it before running. Fix the folder or
  the file name.
- **Nano Banana instead:** set `IMAGE_PROVIDER=openrouter` yourself, then run a new dry run for
  the cost. The app never falls back on its own.

## 7. Train Roman's LoRA on RunPod (manual fallback)

The normal way is one command: section 8. These manual steps are the fallback. Both use Ostris
AI Toolkit (MIT) on a temporary Pod that writes to the same network volume.
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

## 8. One-command training (`ca lora train-remote`)

Codex runs this when you say "train lora". It does the Pod work from section 7 by itself.

**Once, in the RunPod console:**

1. Add credit.
2. Create the network volume (section 1) in a datacenter that supports the S3 API.
3. Create an API key with read/write access to Pods and network volumes.
4. Create an S3 API key: Credentials → S3 API Keys.

Then put these in `.env`:

```
RUNPOD_API_KEY=...
RUNPOD_NETWORK_VOLUME_ID=...   # the volume's ID
RUNPOD_S3_ACCESS_KEY=...       # user_... (your RunPod user ID)
RUNPOD_S3_SECRET_KEY=...       # rps_... (shown only once)
```

`uv run ca doctor` then shows "LoRA training (ca lora train-remote): network volume and S3 key
set".

**Each training:**

1. `uv run ca lora train-remote --model both` (or `qwen` / `zimage`). This is free. It checks the
   consent, makes the dataset if there is none, and shows the estimate: the GPU price per hour ×
   (setup + training hours per model), plus the cap at the hard limit (`remote.maxHours` in
   `config/lora.json`, 4 h).
2. After your "ok": run the same command with `--yes`. In order, it:
   1. uploads the dataset, the AI Toolkit YAMLs and a start script to the network volume
      through its S3 API;
   2. creates one Pod from the AI Toolkit template: L40S, the volume at `/workspace`, the
      script as start command;
   3. shows the Pod's progress, downloads new sample images to
      `outputs/lora/<model>/samples/<run>/step_<n>/`, and records everything in
      `outputs/lora/runs/<run>/train.json` (the cost is the Pod's hourly rate × the time it
      existed).
3. On the Pod, the script trains the models one after another into `lora/output/<run>/`. It
   copies every checkpoint and the final LoRA to `models/loras/<run>_<file>`, writes its status,
   and terminates the Pod.
4. At the end it prints the sample folders and one `uv run ca lora set <model> <file>` command
   per checkpoint. Look at the samples and pick the one most like Roman.

**Safety:**

- **One Pod at a time.** A run that is still active, or any Pod named `ca-lora-...`, blocks a
  new one.
- **Hard limit.** This computer terminates the Pod at `maxHours`. The Pod's own limit ends 10
  minutes earlier.
- **Ctrl+C and errors.** Ctrl+C or any error while watching terminates the Pod. Three failed
  status checks in a row count as an error.
- **Failure on the Pod.** If training fails on the Pod, it terminates itself.
- **Stuck after finishing.** If the Pod reports it is finished but is still running 5 minutes
  later, this computer terminates it.
- `uv run ca lora status` shows a run, also after this computer was closed: Pod state, hours,
  the cost so far, new samples. `uv run ca lora stop` terminates the Pod now.

**Unverified (check on the first run):**

- whether the Pod's own `RUNPOD_API_KEY` may delete the Pod (it tries `runpodctl pod delete`,
  then the REST API, every minute);
- whether `runpodctl` is in the AI Toolkit image;
- where the toolkit lives in the image (the script searches for `run.py`);
- whether the start command fully replaces the template's own start.

If the Pod cannot terminate itself, this computer still does, as long as `train-remote` is
running or `ca lora status` / `ca lora stop` is used.
