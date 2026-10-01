


# Module 1 — Core + Image Branch
Status: build and test with the mock provider now; live test at project end (M1.T7), done through OpenRouter in M1.E.

> Implementation mapping: use Python 3.13 with uv/`pyproject.toml`, type hints with mypy strict, Pydantic schemas, and the `ca` CLI instead of Node/npm tooling.

## Goal
Build the shared engine for all branches, plus on-brand images of one person, requested in plain English through Codex, saved to a shared folder with full traceability, and documented for the team.

## In scope
- Core: validated env config, job records (details.json), job states, dated output folders, timeout/retry, logs that never print secrets, daily image limit.
- Image interface `generate_image()` in src/content_automation/ai/image/__init__.py; adapters: mock, openrouter (the direct Gemini adapter was removed in M1.E).
- Reference library: identity / product / brand / creative sets kept separate; stable IDs; 4 "primary" identity photos. Creative ads and carousels are style references, not identity references.
- Workflows: person_lifestyle, person_product, social_creative (post, ad, carousel slide).
- Aspect presets 1:1, 4:5, 9:16, 16:9; 1–4 variations per request.
- Codex playbook "Make images" in AGENTS.md.
- Module guide docs/guides/module-1-images.md (template sections: What it does · What was built · One-time setup · How to use (example Codex requests) · Commands · Outputs · Settings · Costs & limits · Troubleshooting · Switching providers), linked from docs/README.md.

## Out of scope
Video, voice, research (M2/M3) · web page, database, login · ComfyUI · LoRA training · auto-posting to social media.

## User flow
1. Scan existing folders in place with `uv run ca refs scan`; no `incoming/` folder is used. The type is the first folder under `assets/reference` (`identity`, `brand`, `creative`, or `product`) and a set is a subfolder, for example `identity/person_01`, `creative/facebook_ads`, or `creative/carousels/<name>`. `set.json` and resized copies in `_resized/` stay inside each set folder. `brand.json` is drafted in M1.T3 from `assets/reference/brand/guidelines/*.pdf` for review.
2. Ask Codex: "3 Instagram options of Sara at a café, 4:5".
3. Codex picks the workflow, writes the final prompt, and runs `uv run ca image -- …`.
4. Codex replies with the folder path and one line per image.

## Data
- `REFERENCES_DIR/<type>/<setPath>/set.json`: setId, name, type (identity|product|brand|creative),
  assets[{assetId = first 12 chars of SHA-256, file, width, height, primary}]. Keep originals in place and resized copies in `_resized/` (≤1536px) inside each set folder.
- `REFERENCES_DIR/brand/brand.json`: colors, fonts, tone, do/don't; draft it in M1.T3 from `assets/reference/brand/guidelines/*.pdf` for review.
- `OUTPUT_DIR/YYYY-MM-DD/HHmm_<slug>/` (default `OUTPUT_DIR=outputs`): image-N.png + details.json
  {jobId, workflowId, workflowVersion, requestedBy, request, prompt, provider, model,
   params{aspectRatio, imageSize, count}, identityAssetIds, productAssetIds, brandAssetIds,
   status (queued|processing|completed|failed|cancelled), outputs[], error,
   providerRequestIds, estCostUsd, createdAt, updatedAt}

## Integrations / APIs
- OpenRouter Image API (POST /api/v1/images), model google/gemini-3.1-flash-image.
  Limits: ≤14 reference images in total (identity: IMAGE_IDENTITY_REFS_MAX); sizes 1K/2K/4K.
  Est. cost $0.067 per 1K image; the charge is saved as actualCostUsd. Key: OPENROUTER_API_KEY.
- Env: `IMAGE_PROVIDER` (mock|openrouter), `IMAGE_MODEL`, `OUTPUT_DIR=outputs`, `REFERENCES_DIR=assets/reference`,
  `USER_NAME`, `IMAGE_DAILY_LIMIT`, `IMAGE_TIMEOUT_MS`, `IMAGE_IDENTITY_REFS_MAX`, and `OPENROUTER_API_KEY`.
- Pillow for validating and resizing images. No other services.

## Acceptance criteria
- [ ] `uv run pytest` passes offline with IMAGE_PROVIDER=mock.
- [ ] A test fails if app code imports an adapter file instead of src/content_automation/ai/image/__init__.py.
- [ ] A missing or invalid env var gives one clear message naming it; no secrets printed.
- [ ] `ca refs scan` registers existing folders in place, validates JPG/PNG/WebP assets (≥512px), and preserves stable IDs when rescanned.
- [ ] Identity, product, brand and creative assets are stored and recorded separately; creative ads/carousels are style references.
- [ ] Each workflow (mock) creates a dated folder with N images and a details.json marked "completed".
- [ ] A forced mock failure gives details.json "failed" with the error, no images, and a non-zero exit code.
- [ ] If a set has more than 4 identity photos, only the 4 primary ones are sent, and they are listed in details.json.
- [ ] When the daily limit is reached, the request is refused before any provider call.
- [ ] IMAGE_PROVIDER=openrouter with no key gives a clear "OPENROUTER_API_KEY missing" error.
- [ ] The image adapter is checked against a fake response: request shape, image saved, errors mapped.
- [ ] You and your social media manager each ask Codex in plain English and get the mock folder.
- [ ] docs/guides/module-1-images.md has every template section, uses plain language, and your social media manager can follow it alone to import photos and make an image; docs/README.md links it.
- [ ] LIVE (M1.T7): 1 real image saved; at least 7 of 10 identity test scenes judged the same person; guide updated with live notes.

## Tasks
Every task updates the guide sections for what it built.
- M1.T1 Core: config, job records, folders, timeout/retry, logger, daily limit + tests.
- M1.T2 Image interface, provider registry, mock adapter, import-boundary test.
- M1.T3 Reference library: refs:scan, refs:list, in-place set.json, `_resized/` copies, and brand.json drafted from guideline PDFs for review.
- M1.T4 Workflows + `uv run ca image` command, aspect presets, variations, end-to-end mock test.
- M1.T5 Image adapter + fake-response checks (no live call); OpenRouter since M1.D.
- M1.T6 Codex playbook in AGENTS.md; finish the module guide + docs/README.md; test by asking Codex.
- M1.T7 (at project end) Add key, live test, 10-scene identity check, tune prompts, update guide.
