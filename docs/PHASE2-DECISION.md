# Phase 2 – ComfyUI decision (Step 1 audit)

Audit date: 2026-10-10. Read-only: nothing installed or generated. Prices and licences were checked
on the pages linked at the end. Anything marked **unverified** was not confirmed on an official page,
and "est." means my own estimate.

## Current image flow (what ComfyUI must plug into)

- Entry point: `ai/image/__init__.py` `generate_image()`. The adapter is picked by `IMAGE_PROVIDER`
  (`mock`, `openrouter`) and implements the `ImageProvider` protocol (`capabilities`, `generate`).
  A new provider = one adapter file + one line in the registry.
- Nano Banana: `ai/image/providers/openrouter.py`, model `google/gemini-3.1-flash-image`, estimated at
  $0.067 / $0.101 / $0.151 per image (1K / 2K / 4K).
- Identity: `assets/reference/identity/person_01/1-9.jpg` (+ `set.json`, `_resized/`). The photos are
  sent first as reference images (`workflows/image_job.py`).
- The model draws the text itself: headline, subheadline, stat and CTA button (`workflows/prompt.py`
  typography lines). A Facebook ad is 3 variants (`config/deliverables.json`).
- Logo: `workflows/logo.py` pastes it after generation (top right, white version on dark corners).
  This step does not depend on the model and stays unchanged.
- Person check: Codex views each image beside two primary photos, then runs
  `ca job review --fail` (`core/jobs.py` `ImageReview`), stops and shows the cost before a redo.

## This machine

Windows 10 Pro, Intel i7-4600U (2 cores / 4 threads, 2014), 7.9 GB RAM, Intel HD Graphics only
(no NVIDIA GPU, no CUDA, no `nvidia-smi`). Free disk: C: 53 GB, D: 98 GB. Python (uv `.venv`)
is installed. ComfyUI and CUDA are not. **Local ComfyUI is not workable:** current photoreal
models need an NVIDIA GPU with 16 GB+ VRAM.

## Comparison

| | FLUX.1 [dev] / Krea [dev] | Qwen-Image-2512 + Qwen-Image-Edit-2511 | Z-Image Turbo / Base | SDXL 1.0 (+ realistic fine-tunes) |
|---|---|---|---|---|
| Weights licence | FLUX.1 [dev] Non-Commercial: §2(a) non-commercial only, §4(a)(i) no "commercial or production purposes". Commercial use needs the BFL self-serve licence ($999/month, up to 100k images) | Apache 2.0 (Edit-2511 page: "Qwen-Image is licensed under Apache 2.0"). 2512's own page (checked 2026-10-10): `apache-2.0` | Apache 2.0 | CreativeML Open RAIL++-M. Commercial terms not shown on the page I checked: **unverified**. Each fine-tune has its own licence |
| Output licence | §2(d) allows commercial use, but §4(a) bars commercial use of "any data produced". The two clauses conflict, so plan on the paid licence | No output restriction under Apache 2.0 | Same as Qwen | **unverified** |
| Size / VRAM | 12B; ~24 GB bf16, 12–16 GB fp8 (est.) | 20B; ~40 GB bf16, 20–24 GB fp8 (est.; the official page gives no VRAM) | 6B; "fits within 16G VRAM" (official) | 3.5B; 8–12 GB (est.) |
| Realistic portraits | Good; known for waxy skin and a "same face" look, Krea is better (est.) | Good; 2512 is said to improve human realism (**unverified**) | Very good; the official page claims "strong photorealistic" output (people-specific: **unverified**) | Dated; needs a fine-tune; weaker hands (est.) |
| Text in image (headline / CTA) | Fair (est.) | Best of the four; text rendering is Qwen-Image's main strength (**unverified** here) | Good (**unverified**) | Poor (est.) |
| Character LoRA | Yes | Yes (AI Toolkit) | Yes (AI Toolkit, with its Turbo training adapter) | Yes |
| Reference-photo identity without a LoRA | PuLID-FLUX (InsightFace), Kontext [dev] (non-commercial) | Edit-2511 takes several photos and "keeps the identity" (official), Apache 2.0 | None built in | InstantID, IP-Adapter FaceID (both InsightFace) |
| Verdict | Out unless we pay $999/month | **Recommended** | Challenger for a bake-off | Out |

### Identity method

- **Character LoRA trained on the 9 photos (recommended):** no InsightFace and usually the best
  likeness. It costs about $2 per training run. Nine photos is the low end; 15–20 varied photos
  are safer (est.).
- **PuLID, InstantID, IP-Adapter FaceID, and ReActor/inswapper face swap:** all depend on InsightFace
  models (antelopev2 / buffalo_l / inswapper). InsightFace states that its models are "available for
  non-commercial research purposes only". The code is MIT, but a commercial model licence must be
  requested from recognition-oss-pack@insightface.ai. **Excluded**; ComfyUI nodes that download
  these models are not installed.
- **Edit model with reference photos (Qwen-Image-Edit-2511):** no InsightFace and the same idea as
  today's Nano Banana flow. Identity is weaker than a LoRA (est.). Kept as an option for a second
  pass or a fallback.

### Identity check

- **Keep the existing Codex vision person check** as the gate. It needs no new model or licence and
  is already wired to `ca job review --fail` and the redo flow.
- Optional automatic pre-score: dlib `dlib_face_recognition_resnet_model_v1` with the 5-point
  landmarks. The dlib-models README puts these models in the public domain; the 68-point model is
  excluded because its dataset is non-commercial. The score would retry clear misses before Codex
  looks. On Windows dlib needs a C++ build (est.), so it could run on the GPU worker instead.
- InsightFace ArcFace (most accurate): excluded, non-commercial (see above). AWS Rekognition
  CompareFaces would be a commercial hosted option, but its price is **unverified**.

## Execution options and cost

| Option | Setup effort | Per image (Qwen-Image fp8 + LoRA, ~1.4 MP) | API from a script | Fixed cost |
|---|---|---|---|---|
| Local | Not possible on this PC | – | – | New GPU PC |
| **RunPod Serverless** (ComfyUI worker; models on a network volume) | Medium–high: Docker worker + volume (worker template **unverified**) | ~40 s at $1.75/h (L40S 48 GB) ≈ **$0.02**; 24 GB 4090 at $1.10/h ≈ $0.015 (est.). A cold start of 60–120 s adds ≈ $0.03–0.06 | Yes: HTTPS endpoint, workflow JSON in, images out | Volume ~60 GB × $0.07 ≈ **$4.20/month** |
| RunPod Pod (ComfyUI on port 8188 via proxy URL) | Low–medium; best for building and testing the workflow | Billed per hour while on: A6000 $0.53/h, 4090 $0.74/h, L40S $1.09/h (Secure Cloud). One set ≈ 15 min ≈ $0.13–0.27 | Yes: the normal ComfyUI `/prompt` API; the script must start and stop the pod | Same volume |
| Comfy Cloud (Creator plan) | Low | 0.39 credits/s ≈ $0.0018/s → ~$0.07 (billing article may be outdated: **unverified**) | Yes, but the API is "experimental"; own LoRAs and the API need Creator or Pro | **$35/month** |
| RunComfy | Low | **unverified** (not checked) | Serverless API (**unverified**) | **unverified** |
| Hosted API without ComfyUI (hosted LoRA endpoints) | Lowest | **unverified** | Yes | None. Deviates from PRD §2 ("ComfyUI workflow") |

**Per Facebook ad set (3 images + 1 redo assumed), RunPod Serverless:** Qwen-Image ≈ $0.10–0.18,
Z-Image Turbo ≈ $0.02–0.04 (8 steps, est.). Nano Banana today is $0.20 (1K) to $0.30 (2K) plus redos.
Facebook feed images are 1080 px wide, so native ~1.3–1.6 MP output needs no upscaler.

**One-time costs (est.):** LoRA training with AI Toolkit on a RunPod Pod (L40S, $1.09/h): Qwen
~2.5 h ≈ $2.75, Z-Image ~1.5 h ≈ $1.65, so about $4.40 per training round (`ca lora config` prints
the estimate). Workflow build and bake-off, 8–12 GPU-hours at $0.53–1.09/h ≈ $5–13. Total ≈ **$15–25**. RunPod's minimum top-up is
**unverified**.

## Recommendation

Qwen-Image-2512 with a character LoRA trained on Roman's photos, run in ComfyUI on RunPod Serverless.
The workflow is built and tested on a RunPod Pod that shares the same network volume. Identity check:
the existing Codex vision check, with an optional dlib pre-score. Before locking this in, run a short
bake-off against Z-Image Turbo + LoRA on the same photos (about $5). Nano Banana stays the fallback
(PRD rule) until Phase 4.

## Decisions (approved 2026-10-10)

1. **Ad text:** the app renders the headline, subheadline and CTA button as an overlay after
   generation, like the logo. The model prompt asks for clean space for the text and no lettering,
   so text rendering is no longer a model criterion. Font: Futura from `assets/fonts/` when present
   (brand.json: Futura Bold headings, Futura Medium sub-headings). That folder does not exist yet, so
   the fallback is **Jost** (Google Fonts `ofl/jost`, SIL Open Font License 1.1, variable weight
   axis; exact weight range **unverified**). The user checks the Futura licence.
2. **Model:** Qwen-Image-2512 vs Z-Image Turbo, each with a character LoRA. A small comparison after
   training picks the winner on Roman's likeness first, then cost. Qwen-Image-2512's own licence page
   is checked before training.
3. **Identity:** character LoRA trained with Ostris AI Toolkit on a temporary RunPod Pod. The Pod
   writes to the same network volume the Serverless endpoint reads (changed 2026-10-10). No
   InsightFace-based tools.
4. **Check:** the existing Codex vision person check and the redo-with-cost flow stay. A dlib score
   comes later and is optional.
5. **Execution:** a RunPod Serverless ComfyUI worker, called from a script through
   `IMAGE_PROVIDER=comfyui`. Nano Banana stays the default until Phase 4 passes.
6. **Budget:** one-time ≤ $25 (training + comparison). Each paid run still needs the user's "ok" on
   the exact cost first.
7. **Blockers handled by the user:** Roman's written consent (`CONSENT.md`), the RunPod API key
   and endpoint ID in `.env`, Futura licence check.

Build steps: 2 text overlay + prompt change (free) · 3 ComfyUI adapter, RunPod client, workflow JSON
for both models (free, no calls) · 4 LoRA tooling for AI Toolkit on a RunPod Pod (run only after consent + "ok") ·
5 comparison run + model choice (paid, after "ok") · 6 wiring: person check + retry, Nano Banana
fallback switch, AGENTS.md/docs.

Overlay scope (answered 2026-10-10): every image from a provider that draws no text (ComfyUI):
Facebook posts, Facebook ads and all LinkedIn formats. Nano Banana keeps its model-drawn text.
Provider capability `draws_text` + `TEXT_OVERLAY=auto|always|never` (default auto).

## LoRA training: Ostris AI Toolkit (checked 2026-10-10)

- **Supported:** the README lists Qwen-Image, Qwen-Image-2512 and Z-Image Turbo
  (`Tongyi-MAI/Z-Image-Turbo`) as supported models. Licence: MIT.
- **Dataset:** a folder of jpg/png images, each with a same-name `.txt` caption. `[trigger]` in a
  caption is replaced by `trigger_word`. Images are downscaled into buckets, never upscaled.
- **Config:** YAML (`job: extension`, `config.process[0]` of type `sd_trainer`), run with
  `python run.py <config>.yaml`. The UI runs on port 8675. `ca lora config` writes the YAML from
  the defaults of `config/examples/train_lora_qwen_image_24gb.yaml`: rank 16 / alpha 16, 2000
  steps, lr 1e-4, adamw8bit, bf16, batch 1, buckets 512/768/1024, a save and a sample every 250
  steps.
- **RunPod:** the README links an official Pod template (template `0fqzfjy6f3`).
- **Unconfirmed:**
  - No VRAM figures and no training times are given.
  - There is no example config for Qwen-Image-2512 or Z-Image. Their `arch` and `name_or_path`
    values in `config/lora.json` (`qwen_image` + `Qwen/Qwen-Image-2512`; `zimage` +
    `Tongyi-MAI/Z-Image-Turbo`) are best guesses. So is the Z-Image training adapter file
    (`ostris/zimage_turbo_training_adapter/..._v1.safetensors`, named in third-party guides).
    The UI presets ("Qwen-Image-2512", "Z-Image Turbo (w/ Training Adapter)") are the
    reference; correct `config/lora.json` from them on the Pod.
  - The time estimates (Qwen 2 h, Z-Image 1 h on an L40S, plus 0.5 h setup) are mine. A
    third-party note reports about 1 h for 3000 Z-Image steps on an RTX 5090.
  - The 48 GB GPU, with qfloat8 for Qwen and no 3-bit accuracy recovery adapter (that adapter
    was made for Qwen-Image base), is my choice.

## Free LoRA training and likeness test on Kaggle (checked 2026-10-10)

**Decision:** the LoRA is trained and likeness-tested free on Kaggle
(`notebooks/kaggle_train_lora.ipynb`, `notebooks/kaggle_test_lora.ipynb`, guide
`docs/guides/kaggle-lora.md`). Image generation stays on RunPod Serverless later (needs credit).
`ca lora train-remote` remains the paid alternative.

**Model:**

- **Z-Image Turbo only.**
  - Two AI Toolkit guides (third-party) give at least 16 GB VRAM without offloading, and
    10–12 GB with offloading, float8 and low-VRAM mode.
  - musubi-tuner's official docs recommend 12 GB or more for image LoRAs (fp8, block swap).
    For Turbo they advise the De-Turbo model, or Turbo with Ostris' training adapter.
- **Qwen-Image-2512 (20B) does not fit 16 GB:** AI Toolkit's smallest Qwen config is the 24 GB
  one. A Qwen LoRA would need a paid GPU with 24 GB or more, so Step 5 starts with the
  Kaggle-trained Z-Image LoRA.

**Kaggle limits.** Kaggle's docs page did not load, so these come from secondary sources and
are **unverified**:

- GPU: T4 x2 or P100, 16 GB each.
- About 30 GPU hours per week and about 12 h per session, including committed "Save & Run All"
  runs.
- Internet needs a verified phone number.
- About 20 GB of saved output in `/kaggle/working`.
- Datasets are read-only under `/kaggle/input`; private datasets can be attached.

**The notebooks:**

- **Training:** AI Toolkit's example defaults (rank 16, 2000 steps, lr 1e-4, adamw8bit, a
  checkpoint and samples every 250 steps, all checkpoints kept). Low-VRAM options: float8
  transformer and text encoder, `low_vram`, cached latents and text embeddings.
  - It uses fp16 on the T4/P100, which have no native bf16, and bf16 on newer GPUs.
  - It stops itself after 9 h and zips everything, and retries once at 512/768 px if memory
    runs out before the first checkpoint.
  - It reads the arch name from the cloned toolkit and takes the newest adapter file from
    `ostris/zimage_turbo_training_adapter`.
- **Test:** diffusers `ZImagePipeline`, 8 steps, no CFG, 1024 px, 6 fixed prompts × strength
  0.7/0.9/1.0 with fixed seeds, a contact sheet. It loads the LoRA through diffusers, or
  merges it directly into the weights; it stops if fewer than 90% of the layers match.
- `ca lora prepare` already writes what the training notebook expects: one folder of
  `NN.jpg` + `NN.txt`, each caption starting with the trigger word. No change was needed.

**Unverified:**

- No source shows Z-Image LoRA training on a Kaggle or Colab T4. The risks are fp16 stability
  and speed; the time per step is unknown.
- AI Toolkit's Z-Image arch name, and whether diffusers reads AI Toolkit's LoRA format.
- Kaggle's terms on **commercial use of trained outputs**. The terms page did not load. Read
  https://www.kaggle.com/terms before using the LoRA in production.
- Licences that are confirmed: Z-Image Turbo Apache 2.0, AI Toolkit MIT.

Sources: https://github.com/kohya-ss/musubi-tuner/blob/main/docs/zimage.md,
https://www.runcomfy.com/trainer/ai-toolkit/z-image-turbo-lora-training,
https://neurocanvas.net/blog/zimage-lora-training-guide/,
https://atlassc.net/2026/02/05/run-ai-toolkit-on-google-colab-to-train-loras,
https://huggingface.co/datasets/John6666/forum3 (z_image_turbo_colab_kaggle_1.md).

## Remote LoRA training: `ca lora train-remote` (RunPod docs checked 2026-10-10)

**Chosen path (simplest reliable):**

1. Upload to the network volume through its S3-compatible API.
2. Create the Pod with the REST API; its start command is a script on the volume.
3. The Pod terminates itself; this computer watches it and terminates it on every failure.

**Confirmed in the RunPod docs:**

- **Pods (REST v1, `https://rest.runpod.io/v1`, bearer auth):**
  - `POST /pods` takes `templateId`, `gpuTypeIds` (e.g. `NVIDIA L40S`), `cloudType`,
    `networkVolumeId`, `volumeMountPath` (`/workspace`), `containerDiskInGb`, `dataCenterIds`,
    `dockerStartCmd` (overrides the image's start command) and `env`.
  - The response has `id`, `desiredStatus` (RUNNING, EXITED or TERMINATED), `costPerHr` and
    `adjustedCostPerHr`.
  - Also used: `GET /pods/{podId}`, `GET /pods`, `DELETE /pods/{podId}` and
    `GET /networkvolumes/{networkVolumeId}`.
- **Network volume S3 API:**
  - The endpoint is `https://s3api-<datacenter>.runpod.io/`, the region is the datacenter ID
    and the bucket is the volume ID.
  - Keys: RunPod console → Credentials → S3 API Keys (access key `user_...`, secret `rps_...`,
    shown once).
  - Supported: PutObject (under 500 MB), GetObject, ListObjectsV2, HeadObject, DeleteObject,
    CopyObject and multipart; no pre-signed URLs.
  - Available in 15 datacenters (listed in the guide, section 1).
- **Inside a Pod:** `RUNPOD_POD_ID` and a "Pod-scoped" `RUNPOD_API_KEY`. `runpodctl pod delete
  <pod-id>` deletes a Pod.

**Unverified:**

- What the Pod-scoped key may do, and so whether a Pod can delete itself with it. The script
  tries `runpodctl pod delete`, the older `runpodctl remove pod`, then the REST call, every
  minute. This computer terminates the Pod in any case: at the hard limit, on Ctrl+C or an
  error, or 5 minutes after the script reports it has finished.
- Whether `runpodctl` is in the AI Toolkit image.
- Where AI Toolkit lives in the template's image; the script searches for `run.py`.
- Whether `dockerStartCmd` fully replaces the template's own start.
- The response format of `GET /pods` (assumed to be a list).
- The real cost: the Pod's `costPerHr` × the time it existed. That is an approximation; the
  RunPod billing page has the exact amount.

**Safety:**

- **One Pod at a time:** the local `train.json` plus the account's Pods named `ca-lora-...`.
- **Hard limit:** `remote.maxHours` (4 h); the Pod's own `timeout` ends 10 minutes earlier.
- **Failure on the Pod:** the Pod terminates itself.
- **Ctrl+C or any error while watching** terminates the Pod. Three failed polls in a row count
  as an error.
- `ca lora status` and `ca lora stop`.

## RunPod worker-comfyui (checked 2026-10-10)

- Release used: **5.11.0** (released 21 Sep; the releases page shows no year). It checks every
  model file a workflow needs before running and lists all missing ones. Image:
  `runpod/worker-comfyui:5.11.0-base` with the models on a network volume
  (`/runpod-volume/models/...`).
- `POST https://api.runpod.ai/v2/<endpoint>/run` with `{"input": {"workflow": {...API format...},
  "images": [{"name", "image": base64}]}}`. `images` is optional and the app sends none (the
  identity is the LoRA). The response is `{"id", "status"}`.
- `GET .../status/<id>` returns `status` (IN_QUEUE, IN_PROGRESS, COMPLETED, FAILED, CANCELLED or
  TIMED_OUT), `delayTime` and `executionTime` in ms, and `output.images` = [{`filename`,
  `type`: `base64` or `s3_url` (only with S3 configured), `data`}]. `output.errors` lists
  non-fatal problems. `POST .../cancel/<id>` is used when the app's time budget runs out.
- Sources: https://github.com/runpod-workers/worker-comfyui (README),
  https://github.com/runpod-workers/worker-comfyui/releases,
  https://github.com/runpod-workers/worker-comfyui/blob/main/docs/customization.md.
- Model files (official ComfyUI docs): Qwen-Image-2512 `qwen_image_2512_fp8_e4m3fn`,
  `qwen_2.5_vl_7b_fp8_scaled` and `qwen_image_vae`, 50 steps. Z-Image Turbo
  `z_image_turbo_bf16`, `qwen_3_4b` and `ae`, 8 NFEs. **Unverified:** the CLIP loader types,
  samplers, shift and cfg in `config/comfyui/workflows/*.json`. Compare them with the official
  templates in Step 5.

## Links

- FLUX.1 [dev] licence: https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/LICENSE.md
- BFL self-serve licence pricing: https://help.bfl.ai/articles/9272590838-self-serve-dev-license-overview-pricing
- BFL self-hosted commercial terms: https://bfl.ai/legal/self-hosted-commercial-license-terms
- Qwen-Image-2512 (apache-2.0): https://huggingface.co/Qwen/Qwen-Image-2512
- Qwen-Image-Edit-2511 (Apache 2.0): https://huggingface.co/Qwen/Qwen-Image-Edit-2511
- Z-Image Turbo (Apache 2.0): https://huggingface.co/Tongyi-MAI/Z-Image-Turbo
- SDXL 1.0 (CreativeML Open RAIL++-M): https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0
- InsightFace licence (models non-commercial): https://github.com/deepinsight/insightface
- dlib models (public domain; the 68-point model is non-commercial): https://github.com/davisking/dlib-models
- RunPod pricing: https://www.runpod.io/pricing
- Comfy Cloud pricing / docs / billing: https://comfy.org/pricing, https://docs.comfy.org/development/cloud/overview.md, https://support.comfy.org/articles/8020405733-billing-on-comfy-cloud
- Jost font (SIL OFL 1.1): https://github.com/google/fonts/tree/main/ofl/jost
- ComfyUI model docs: https://docs.comfy.org/tutorials/image/qwen/qwen-image-2512, https://docs.comfy.org/tutorials/image/z-image/z-image-turbo
- Ostris AI Toolkit (MIT): https://github.com/ostris/ai-toolkit, example config https://github.com/ostris/ai-toolkit/blob/main/config/examples/train_lora_qwen_image_24gb.yaml
