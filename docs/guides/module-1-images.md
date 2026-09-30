# Module guide: Images

> Status: Parts A and B are built (job records, image interface, test "mock" images,
> reference photo library, brand profile). Named workflows and the real Gemini provider come next.

## What it does

It makes images from a text description and saves each request in its own dated folder,
with a `details.json` file that records exactly what was asked, what was sent, and what came back.

Today it only makes **placeholder images** (the "mock" provider). They show your prompt as
text on a coloured card at the right shape. This lets you try the whole flow without spending money.

## What was built

- **Job records**: every request gets a folder and a `details.json` with its status
  (`queued`, `processing`, `completed`, `failed`, or `cancelled`).
  A job is only marked `completed` when all its image files really exist.
- **Daily limit**: the tool counts today's finished images and refuses new requests
  once `IMAGE_DAILY_LIMIT` is reached, before contacting any provider.
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

- Use **JPG, PNG or WebP**. SVG, PDF and video files are listed as "rejected" or skipped.
  To use a PDF carousel or a video as a style example, export the slides as PNG/JPG images.
- Photos must be at least **512 px** on the short side (logos: **256 px**).

### Scan the folders

```
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
`"status": "draft"` to `"status": "approved"` when you are happy.

## How to use

Run one command with your description. The tool prints the folder where the images were saved.

```
uv run ca image --prompt "A woman at a sunny café, soft light" --aspect 4:5 --count 3
```

- `--prompt`: what the picture should show (required).
- `--aspect`: shape of the picture: `1:1` square, `4:5` Instagram portrait, `9:16` story/reel, `16:9` wide. Default `1:1`.
- `--count`: how many versions to make, from 1 to 4. Default 1.
- `--request`: optional. Your original words, saved in `details.json` for the record.

### Example Codex requests

The Codex playbook comes in a later task. For now you can ask Codex:

- "Run `uv run ca image` with the prompt 'test café scene', aspect 4:5, 2 images, and tell me the folder."

## Commands

| Command | What it does |
|---|---|
| `uv run ca hello` | Shows your settings (keys are hidden). |
| `uv run ca image --prompt "…" [--aspect 4:5] [--count N] [--request "…"]` | Makes images and prints the output folder. |
| `uv run ca refs scan` | Checks the reference folders and updates each set's `set.json`. |
| `uv run ca refs list [--type identity]` | Shows every set with accepted, rejected and primary counts. |
| `uv run ca refs primary --set <set> --files a.jpg,b.jpg` | Chooses up to 4 primary photos of a person. |
| `uv run ca brand show` | Shows a short summary of `brand.json` and what still needs review. |

## Outputs

Each request creates: `outputs/YYYY-MM-DD/HHmm_<short-name>/`

- `image-1.png`, `image-2.png`, …: the images.
- `details.json`: the record. Key fields: `status`, `request` (your words), `prompt` (text sent),
  `provider`, `model`, `params` (shape, size, count), `outputs` (file names), `error` (why it
  failed, if it did), `estCostUsd`, `createdAt`.

If a folder name is already taken, `-2`, `-3`, … is added. A failed job keeps its folder and
`details.json` (with the error) but has no images.

The reference scan writes, inside each set folder:

- `set.json`: the list of photos with their ID, size, `primary` flag, and `status`
  (`ok` or `rejected` with a `reason`).
- `_resized/`: smaller, upright copies (at most 1536 px) that are sent to the image model.
  Don't edit this folder; it is rebuilt by `ca refs scan`.

## Settings

Set these in `.env`:

| Setting | Meaning | Default |
|---|---|---|
| `IMAGE_PROVIDER` | Which service makes images: `mock` (free test images). `gemini` comes later. | `mock` |
| `IMAGE_MODEL` | Model name passed to the provider. For the mock, `mock-fail` and `mock-timeout` simulate problems. | `gemini-3.1-flash-image` |
| `IMAGE_DAILY_LIMIT` | Maximum images per day. | `10` |
| `IMAGE_TIMEOUT_MS` | How long to wait for the provider, in milliseconds. | `120000` (2 min) |
| `IMAGE_MAX_RETRIES` | Extra tries after a temporary error (0 = none). | `1` |
| `OUTPUT_DIR` | Where output folders are created. | `outputs` |
| `REFERENCES_DIR` | Where reference photo folders live. | `assets/reference` |
| `USER_NAME` | Your name, saved as `requestedBy`. | `User` |

## Costs and limits

- The mock provider is free (`estCostUsd` is 0).
- Up to 4 images per request; shapes 1:1, 4:5, 9:16, 16:9.
- Up to 4 identity photos, 10 product/brand images and 10 style images per request
  (requests over this are refused before anything is sent).
- The daily limit counts only images that were actually made today.

## Troubleshooting

| Message | What to do |
|---|---|
| `Missing or invalid environment variables: X` | Fix setting X in `.env`. |
| `Daily image limit reached` | Wait until tomorrow or raise `IMAGE_DAILY_LIMIT`. |
| `Image provider 'gemini' is not available` | The Gemini provider is not built yet; use `IMAGE_PROVIDER=mock`. |
| `Invalid image request: aspect_ratio` | Use one of 1:1, 4:5, 9:16, 16:9. |
| `Failed: …` and exit code 1 | Open the printed folder's `details.json` and read `error`. |
| `rejected x.jpg: too small` | Use a larger photo (512 px short side; logos 256 px). |
| `rejected x.svg` / `x.pdf` | Export it as PNG or JPG and put the image in the set folder. |
| `skipped …: no JPG/PNG/WebP images` | The folder only has videos, PDFs or other files; add images or ignore it. |
| `duplicate of y.jpg` | The same photo is in the set twice; one copy is enough. |
| `Set '…' not found` | Run `uv run ca refs scan`, then `uv run ca refs list` to see set names. |
| `brand.json is invalid; check: …` | Fix the named field (colours must look like `#004BA0`). |

## Switching providers

Change `IMAGE_PROVIDER` (and `IMAGE_MODEL`) in `.env`. Nothing else changes for you.
For developers: a new provider is one file in `src/content_automation/ai/image/providers/`
plus one line in the provider list in `src/content_automation/ai/image/__init__.py`.
