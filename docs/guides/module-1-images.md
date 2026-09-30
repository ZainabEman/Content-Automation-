# Module guide: Images

> Status: Module 1 is built and tested offline (job records, reference library, brand profile,
> the three workflows, the Codex playbook, and the Gemini provider). The first real (paid)
> Gemini test happens in the LIVE task at project end.

## What it does

It makes images from a text description and saves each request in its own dated folder,
with a `details.json` file that records exactly what was asked, what was sent, and what came back.

By default it makes free **placeholder images** (the "mock" provider): your prompt as text on a
coloured card at the right shape, so you can try the whole flow without spending money. With
`IMAGE_PROVIDER=gemini` it makes real images with Google Gemini (paid, see "Costs and limits").

## What was built

- **Job records**: every request gets a folder and a `details.json` with its status
  (`queued`, `processing`, `completed`, `failed`, or `cancelled`).
  A job is only marked `completed` when all its image files really exist.
- **Daily limit**: the tool counts today's finished real (non-mock) images and refuses new
  requests once `IMAGE_DAILY_LIMIT` is reached, before contacting any provider.
- **Dry run** (`--dry-run`): shows the final prompt, which reference photos would be sent,
  how many provider calls it takes and the estimated cost, without making anything.
- **Gemini provider**: real image generation with `gemini-3.1-flash-image`.
- **Time limit and retries**: a request that takes too long is stopped and marked failed.
  Temporary provider errors (such as "busy") are retried; timeouts are not retried, so you
  are never charged twice for one request.
- **Safe logs**: secret keys are hidden (`***`) in anything the tool prints or saves.
- **One image interface** with a mock provider, so real providers can be added later
  without changing how you use it.
- **Reference library**: the tool reads your photo folders where they are (nothing is moved
  or deleted), checks each photo, gives it a permanent ID, and makes a smaller copy for sending.
  Four kinds are kept separate: `identity` (the person), `product`, `brand` (logos), and
  `creative` (past ads and carousels, used only as **style** examples, never as the person's face).
- **Primary photos**: for each person, the 4 best photos are marked "primary". These are
  the ones sent to the image model.
- **Brand profile** (`brand.json`): colours, fonts, tone and do/don't rules, drafted from the
  brand style guide PDF for you to check.
- **Video frames**: carousel videos are turned into still frames (3 per video) so they can be
  used as style examples.
- **Three workflows** that turn a short scene description into a full prompt: they add the
  right reference photos, say what each photo is for (the person, the product, the logo, or
  style only), and add the brand rules from `brand.json` automatically.

## One-time setup

1. Install uv using the [official installer](https://docs.astral.sh/uv/getting-started/installation/).
2. In the project folder, run `uv sync`.
3. Make sure `.env` exists (copy `.env.example` if not) and contains `IMAGE_PROVIDER=mock`.
4. Check it works: `uv run ca hello`.

### Add your photos

Put photos in `assets/reference/`. The **first folder** is the kind, the **folder inside it** is a set:

```
assets/reference/
  identity/person_01/        photos of one person (clear face, different angles)
  product/<product-name>/    product photos
  brand/logo/                logos
  brand/guidelines/          brand style guide PDF (read for brand.json, not sent)
  creative/facebook_ads/     past ads (style examples)
  creative/carousels/<name>/ carousel slides (style examples)
```

- Use **JPG, PNG or WebP**. SVG and PDF files are listed as "rejected". To use a PDF
  carousel, export its pages as PNG/JPG images.
- **Videos** (MP4): run `uv run ca refs frames` once. It saves 3 still frames of each video
  (at 10%, 50% and 90%) in a `_frames/` folder next to it; the scan then uses those frames.
- Photos must be at least **512 px** on the short side (logos: **256 px**).

### Scan the folders

```
uv run ca refs frames   (only if you added videos)
uv run ca refs scan
```

This lists each set with how many photos were accepted, rejected (with the reason) and marked
primary. Run it again any time you add, change or remove photos. IDs and your primary choices are kept.

### Choose the 4 primary photos

The first scan marks the first 4 photos (by file name) of each person as primary. To choose
others, see the file names in the set folder and run:

```
uv run ca refs primary --set identity/person_01 --files 2.jpg,5.jpg,7.jpg,9.jpg
```

Pick sharp, well-lit photos where the face is clearly visible, ideally from different angles.

### Check brand.json

Open `assets/reference/brand/brand.json` in any text editor, or run `uv run ca brand show`.
Fix anything wrong, remove each item from `needsReview` once you have checked it, and change
`"status": "draft"` to `"status": "approved"` when you are happy. `logoFile` is the file in
`brand/logo/` that is added when you ask for the logo.

## How to use

The easiest way: **ask Codex in plain English**. Codex follows the "Make images" playbook in
`AGENTS.md`. It picks the workflow, the photos and the shape, writes a detailed scene
description, runs the command, and replies with the folder and one line per image.

The three workflows:

| Workflow | Use it for | Needs |
|---|---|---|
| `person_lifestyle` | The person in a real-life scene | `--set` (the person); style set optional |
| `person_product` | The person using or showing a product | `--set` and `--product` |
| `social_creative` | A designed post, ad (`--variant ad`) or carousel slide (`--variant carousel_slide`) | Nothing required; optional person, product, `--headline`, `--logo`, `--style` (default: Facebook ads) |

If Codex doesn't specify them, the shape is 4:5 (Instagram feed) and it makes 3 versions. Brand colours,
tone and "don't" rules are added automatically, so you don't need to repeat them.

### Example Codex requests

1. "3 Instagram options of me working at a café"
   ```
   uv run ca image --workflow person_lifestyle --set identity/person_01 --aspect 4:5 --count 3 --prompt "Working on a laptop at a bright modern café, relaxed smile, morning window light, 35mm, shallow depth of field" --request "3 Instagram options of me working at a café"
   ```
2. "A story of me speaking on stage at a marketing conference"
   ```
   uv run ca image --workflow person_lifestyle --set identity/person_01 --aspect 9:16 --count 3 --prompt "Speaking on a conference stage with a microphone, audience in soft focus, blue stage lights, low angle, 24mm" --request "A story of me speaking on stage at a marketing conference"
   ```
3. "2 LinkedIn photos of me holding our new mug"
   ```
   uv run ca image --workflow person_product --set identity/person_01 --product product/<mug-set> --aspect 1:1 --count 2 --prompt "Holding the mug at a clean desk in a bright home office, candid smile, natural light, 50mm" --request "2 LinkedIn photos of me holding our new mug"
   ```
4. "A Facebook ad saying 'Grow faster with AI', with our logo"
   ```
   uv run ca image --workflow social_creative --variant ad --headline "Grow faster with AI" --logo --aspect 4:5 --count 3 --prompt "Bold headline on a light-grey background, blue gradient shapes, a laptop showing rising charts" --request "A Facebook ad saying 'Grow faster with AI', with our logo"
   ```
5. "A carousel title slide '3 AI tools every marketer needs' in the style of carousel 1"
   ```
   uv run ca image --workflow social_creative --variant carousel_slide --style creative/carousels/carousel_01 --headline "3 AI tools every marketer needs" --aspect 4:5 --count 3 --prompt "Title slide with a large bold headline, clean light-grey background, subtle blue gradient accents" --request "A carousel title slide '3 AI tools every marketer needs' in the style of carousel 1"
   ```

### Running a command yourself

- `--workflow`: one of the three workflows above. Leave it out for "raw" mode: the prompt is
  sent exactly as written, with no photos or brand rules.
- `--prompt`: what the picture should show (required).
- `--set`, `--product`, `--style`: which reference sets to use (see `uv run ca refs list`).
- `--variant`, `--headline`, `--logo`: for `social_creative` only.
- `--aspect`: `1:1` square, `4:5` Instagram portrait, `9:16` story/reel, `16:9` wide.
- `--count`: how many versions, 1 to 4. Default 1 (Codex uses 3).
- `--request`: your original words, saved in `details.json`.
- `--style-count`: how many style images to send (default 3, Gemini's maximum). They are taken
  from different videos/files, spread across the set.
- `--dry-run`: show the prompt, reference photos, number of calls and estimated cost. Nothing
  is created, nothing is sent, and it does not count toward the daily limit. No API key needed.

If something required is missing, the tool stops with a clear message **before** creating a
job or contacting any provider.

## Commands

| Command | What it does |
|---|---|
| `uv run ca hello` | Shows your settings (keys are hidden). |
| `uv run ca image --workflow <id> --set … --prompt "…" [--product …] [--style …] [--variant …] [--headline "…"] [--logo] [--aspect 4:5] [--count N] [--request "…"]` | Makes images with a workflow and prints the output folder. |
| `uv run ca image --prompt "…" [--aspect 4:5] [--count N]` | Raw mode: sends the prompt as written. |
| `uv run ca image … --dry-run` | Shows prompt, references, calls and estimated cost; makes nothing. |
| `uv run ca refs frames` | Saves 3 still frames of each reference video into `_frames/`. |
| `uv run ca refs scan` | Checks the reference folders and updates each set's `set.json`. |
| `uv run ca refs list [--type identity]` | Shows every set with accepted, rejected and primary counts. |
| `uv run ca refs primary --set <set> --files a.jpg,b.jpg` | Chooses up to 4 primary photos of a person. |
| `uv run ca brand show` | Shows a short summary of `brand.json` and what still needs review. |

## Outputs

Each request creates: `outputs/YYYY-MM-DD/HHmm_<short-name>/`

- `image-1.png`, `image-2.png`, …: the images.
- `details.json`: the record. Key fields: `status`, `workflowId` and `workflowVersion`,
  `request` (your words), `prompt` (the full text sent), `inputs` (scene, sets, variant, headline),
  `identityAssetIds` / `productAssetIds` / `brandAssetIds` / `styleAssetIds` (exactly which
  reference photos were sent), `provider`, `model`, `params` (shape, size, count), `outputs`
  (file names), `error` (why it failed, if it did), `estCostUsd`, `createdAt`.

If a folder name is already taken, `-2`, `-3`, … is added. A failed job keeps its folder and
`details.json` (with the error) but has no images.

The reference scan writes, inside each set folder:

- `set.json`: the list of photos with their ID, size, `primary` flag, and `status`
  (`ok` or `rejected` with a `reason`).
- `_resized/`: smaller, upright copies (at most 1536 px) that are sent to the image model.
  Don't edit this folder; it is rebuilt by `ca refs scan`.
- `_frames/` (video folders only): still frames made by `ca refs frames`.

## Settings

Set these in `.env`:

| Setting | Meaning | Default |
|---|---|---|
| `IMAGE_PROVIDER` | Which service makes images: `mock` (free test images) or `gemini` (real, paid). | `mock` |
| `IMAGE_MODEL` | Model name. For Gemini: `gemini-3.1-flash-image`. For the mock, `mock-fail` and `mock-timeout` simulate problems; anything else works. | `gemini-3.1-flash-image` |
| `GEMINI_API_KEY` | Your Gemini API key. Only needed when `IMAGE_PROVIDER=gemini` (not for `--dry-run`). Keep it only in `.env`; never share it. | empty |
| `IMAGE_DAILY_LIMIT` | Maximum real images per day (mock images don't count). | `10` |
| `IMAGE_TIMEOUT_MS` | How long to wait for each image, in milliseconds. | `120000` (2 min) |
| `IMAGE_MAX_RETRIES` | Extra tries after a temporary error such as "busy" or "rate limit" (0 = none). | `1` |
| `OUTPUT_DIR` | Where output folders are created. | `outputs` |
| `REFERENCES_DIR` | Where reference photo folders live. | `assets/reference` |
| `USER_NAME` | Your name, saved as `requestedBy`. | `User` |

## Costs and limits

- **Mock** images are free (`estCostUsd` is 0) and don't count toward the daily limit.
- **Gemini** (`gemini-3.1-flash-image`), estimated per image: **1K $0.067**, 2K $0.101, 4K $0.151.
  The tool uses 1K. Each image is a separate call, so 3 images at 1K ≈ $0.20. The estimate is
  saved as `estCostUsd` in `details.json`; always check `--dry-run` first.
- Up to 4 images per request; shapes 1:1, 4:5, 9:16, 16:9.
- Reference photos per request: up to **4 identity**, **3 style**, and at most **10 product,
  logo and style images together**. Requests over this are refused before anything is sent.
- The daily limit (`IMAGE_DAILY_LIMIT`) counts real images that were actually made today; when
  it is reached, requests are refused before any provider call.
- Temporary errors (rate limit, server busy) are retried per image; images already made are
  never requested twice. Timeouts are not retried.

## Troubleshooting

| Message | What to do |
|---|---|
| `Missing or invalid environment variables: X` | Fix setting X in `.env`. |
| `Daily image limit reached` | Wait until tomorrow or raise `IMAGE_DAILY_LIMIT`. |
| `GEMINI_API_KEY missing` | Add the key to `.env`, or use `IMAGE_PROVIDER=mock`. `--dry-run` works without a key. |
| `Gemini rate limit or quota reached (HTTP 429)` | Wait a few minutes, or check the quota/billing in Google AI Studio. |
| `Gemini rejected the API key` | Check `GEMINI_API_KEY` in `.env`. |
| `Gemini returned no image` | Often a safety block: reword the prompt or use other reference photos. The reason is shown. |
| `… references together (max 10)` | Use fewer product images or a lower `--style-count`. |
| `Invalid image request: aspect_ratio` | Use one of 1:1, 4:5, 9:16, 16:9. |
| `Failed: …` and exit code 1 | Open the printed folder's `details.json` and read `error`. |
| `rejected x.jpg: too small` | Use a larger photo (512 px short side; logos 256 px). |
| `rejected x.svg` / `x.pdf` | Export it as PNG or JPG and put the image in the set folder. |
| `skipped …: no JPG/PNG/WebP images` | The folder only has PDFs or other files; add images. If it has videos, run `uv run ca refs frames`. |
| `… needs --set` / `needs --product` | Add the missing option (see `uv run ca refs list` for set names). |
| `… does not use --logo` (or another option) | That workflow ignores the option; remove it or use `social_creative`. |
| `… need --workflow` | `--set`, `--product`, etc. only work together with `--workflow`. |
| `logoFile '…' is not a usable image` | Set `logoFile` in `brand.json` to a file listed in `brand/logo/set.json` as `ok`. |
| `duplicate of y.jpg` | The same photo is in the set twice; one copy is enough. |
| `Set '…' not found` | Run `uv run ca refs scan`, then `uv run ca refs list` to see set names. |
| `brand.json is invalid; check: …` | Fix the named field (colours must look like `#004BA0`). |

## Switching providers

To go live with Gemini, edit `.env`:

```
IMAGE_PROVIDER=gemini
IMAGE_MODEL=gemini-3.1-flash-image
GEMINI_API_KEY=<your key>
```

Then run a `--dry-run` to check the prompt and cost, and run the command again without
`--dry-run`. To go back to free test images, set `IMAGE_PROVIDER=mock`. Nothing else changes.

For developers: a new provider is one file in `src/content_automation/ai/image/providers/`
(with `create_provider(settings)` and its limits) plus one line in the provider list in
`src/content_automation/ai/image/__init__.py`.

