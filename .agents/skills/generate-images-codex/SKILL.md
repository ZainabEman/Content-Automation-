---
name: generate-images-codex
description: Make the non-Roman images that `ca` handed to Codex (IMAGE_PROVIDER=codex_builtin, the default) with Codex's built-in image generation (gpt-image-2), then import them with `ca image import`. Use after the user said "ok" to a dry run whose build printed "CODEX IMAGES", and for "generate images" and "import images". Never for Roman (his images stay on Higgsfield Soul 2.0).
---

# Generate images (Codex built-in)

`ca` cannot call Codex's image tool. After the user's "ok", the build (`ca content build … --authorize <DR-id>` or `ca calendar generate --build --authorize <DR-id>`) writes one job per image and stops with `CODEX IMAGES: … wait for Codex` and `Then: uv run ca image import <batch>`:

- `outputs/codex_jobs/<batch>/batch.json`: the batch's jobs (at most 10 images) and their status.
- `outputs/codex_jobs/<batch>/<BG-ID>_<key>/job.json`: `prompt`, `reference_images` (paths, may be empty), `generate_size` (1024x1024 or 1024x1536 or 1536x1024), `final_canvas`, `output_path`, `status` (`awaiting_external` → `done`).

The dry run listed these images as "Codex images: N (codex_images, $0)"; the "ok" covers exactly N images (the authorization caps the count). Never generate without that "ok".

## "generate images"

1. Open `batch.json` of the batch the build named (`--all`: every batch whose status is `awaiting_external`). Work only on jobs with `status: awaiting_external`; a `done` job is never made again.
2. Per job, once:
   1. Read `job.json`. Open every file in `reference_images` (look at them; they guide style and objects only).
   2. Generate ONE image with Codex's built-in image generation at `generate_size`, from `prompt` exactly as written (no added words).
   3. The image has no text, letters, numbers, logos, watermarks or UI of any kind and shows no real person: the app draws the German text, the logo and the CTA afterwards and crops it to `final_canvas`.
   4. Save it as PNG to `output_path` (the exact path; create nothing else in the folder).
   5. Do not retry a job by yourself: if the tool fails or refuses, leave the file missing and tell the user which job and why.
3. Run `uv run ca image import <batch>` (or `--all`). It checks every file (exists, is an image), marks the job `done` and continues each package's build: crop, design, design check, package, Drive, tracker. A missing image keeps its item pending; nothing is made again by the import.
4. Report in at most 5 lines: images made, missing (with the reason), packages finished, anything the build printed as a stop (person, set or visual check: continue with make-content).

## "import images"

`uv run ca image import <batch>` or `uv run ca image import --all`. `uv run ca jobs resume` does the same for queued Codex jobs (re-import only, never a new image).

## Rules

- One image per job, generated once; the authorization's count is never exceeded (the build refuses more jobs than the "ok" covered).
- No silent fallback: never switch to OpenRouter or another tool. OpenRouter runs only when the user sets `IMAGE_PROVIDER=openrouter` in `.env` and approves a new dry run.
- Roman's images are never made here (Higgsfield Soul 2.0, `ca higgsfield list`).
