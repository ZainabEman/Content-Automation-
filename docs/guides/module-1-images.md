# Module guide: Images

> Status: Part A is built (job records, image interface, test "mock" images).
> Reference photos, named workflows and the real Gemini provider come in the next tasks.

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

## One-time setup

1. Install uv using the [official installer](https://docs.astral.sh/uv/getting-started/installation/).
2. In the project folder, run `uv sync`.
3. Make sure `.env` exists (copy `.env.example` if not) and contains `IMAGE_PROVIDER=mock`.
4. Check it works: `uv run ca hello`.

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

## Outputs

Each request creates: `outputs/YYYY-MM-DD/HHmm_<short-name>/`

- `image-1.png`, `image-2.png`, …: the images.
- `details.json`: the record. Key fields: `status`, `request` (your words), `prompt` (text sent),
  `provider`, `model`, `params` (shape, size, count), `outputs` (file names), `error` (why it
  failed, if it did), `estCostUsd`, `createdAt`.

If a folder name is already taken, `-2`, `-3`, … is added. A failed job keeps its folder and
`details.json` (with the error) but has no images.

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

## Switching providers

Change `IMAGE_PROVIDER` (and `IMAGE_MODEL`) in `.env`. Nothing else changes for you.
For developers: a new provider is one file in `src/content_automation/ai/image/providers/`
plus one line in the provider list in `src/content_automation/ai/image/__init__.py`.
