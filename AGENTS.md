# Working rules

- Stack: Python 3.13, uv, Typer, Pydantic, pytest, mypy strict, and Ruff. Run project commands with `uv run`.
- Background architecture: `docs/blueprints/blueprint.md`; read it only when needed.
- Before each task, read `docs/PROGRESS.md` and that task's PRD; inspect the code first, do only that task, keep working code, and avoid big rewrites.
- Providers: each capability has one public interface in its entry package (`content_automation/ai/<cap>/__init__.py`; scraper: `content_automation/research/collectors/__init__.py`).
- Put one adapter module per provider under that capability's `providers/`; choose with `<CAP>_PROVIDER` and `<CAP>_MODEL`, and always provide a mock adapter.
- App code imports capability entry packages only; a test enforces this boundary. A new provider takes one adapter file and two environment changes.
- Images: `generate_image()` lives in `content_automation.ai.image`; adapters are mock and OpenRouter (real images), selected by `IMAGE_PROVIDER` and `IMAGE_MODEL`.
- Adapter modes are `code` (the app calls the API) and `agent` (Codex calls the MCP tool; the app records it through job commands).
- Keep keys only in `.env`. Never print, log, commit, or put keys in docs or prompts; never ask for keys in chat.
- Every job writes `details.json`; never mark a job completed without its output file, and record failures with the error.
- Tests run offline with mocks. Credit-spending calls require a task explicitly marked LIVE and an estimate stated first.
- Each task updates `docs/guides/module-N-<name>.md` from `docs/guides/_TEMPLATE.md` in plain language for non-coders; `docs/README.md` links every guide.
- Finish each task: No new tests. Before commit: `uv run ruff check` + one smoke run of the new command. Full `uv run pytest -q` only at the end of a module. Add one line to `docs/PROGRESS.md`; commit as `M<n>.T<n>: <title>`; reply in at most five lines with changes, tests, blockers, and what the user must do.

## Playbooks

### Make images

0. Read `docs/company/services.md` first: base scenes, headlines and captions on it (English only; never invent results, statistics, prices or client names).
1. Pick the workflow: the person in a scene → `person_lifestyle`; the person delivering one of the company's services → `person_service` (`--service "…"`: the service in words; `uv run ca brand show` lists `services`); a designed post, ad or carousel slide → `social_creative` (`--variant post|ad|carousel_slide`; add `--headline "…"` for exact on-image text, `--logo` for the logo, and `--style creative/<set>` if a style is named; the default is `creative/facebook_ads`).
2. Identity: `--set identity/person_01` unless another person is named (`uv run ca refs list` shows the sets). Add it to social_creative only if the person should appear. Consent: person_01 is the company lead, who provided his own photos for his company's marketing; use only identity sets of people who agreed to this use.
3. Aspect ratio by platform: IG feed 4:5 · story/reel 9:16 · LinkedIn 1:1 · YouTube 16:9. Default `--count 3` unless a number is given (max 4).
4. `--prompt`: a rich scene description (action, setting, light, camera/lens, mood). Leave out brand colours, tone and rules; the builder adds them.
5. Pass the user's exact words as `--request "…"`.
6. Run: `uv run ca image --workflow <id> --set … --prompt "…" --aspect … --count … --request "…"`. If `IMAGE_PROVIDER` is not `mock` (real images use `openrouter`), first run the same command with `--dry-run` and state the estimated cost.
7. Success (exit 0): reply with the printed folder path, `actualCostUsd` from its `details.json` if set, and one line per image (`image-N.png`: what it shows).
8. Failure: show the error message and the next step: a missing set → `uv run ca refs scan` / `ca refs list`; a daily limit → wait or raise `IMAGE_DAILY_LIMIT`; `OPENROUTER_API_KEY missing` → the user adds the key to `.env` (never ask for it in chat); HTTP 402 → the user adds OpenRouter credits; a provider error → read `error` in the folder's `details.json`.

### Make videos

1. Workflow: Reel/Short → `reel_short` (≤90 s); ad → `ugc_ad` (≤60 s); talking head or podcast → `podcast_clip` (≤90 s, avatar scenes plus optional video b-roll). Voiceover is off in the MVP.
2. Write `outputs/plans/<short-name>.json` (fields in `docs/guides/module-2-video.md`): scenes numbered 1…N, each ≤15 s, adding up to `durationSec`; video `prompt` = a rich shot description; avatar `prompt` = the exact words (≈2.5 words/s); short `onScreenText`; take services, messages and captions from `docs/company/services.md` (English only; never invent results, statistics, prices or client names).
3. Start images: `startImageAssetId` = an ID from an image job's `outputAssetIds` or a set's `set.json`, or `<jobId>/image-N.png`; image scenes need one.
4. Run `uv run ca video --plan <file> --dry-run`; fix every listed problem; state the credits.
5. Run `uv run ca video --plan <file> --request "<the user's exact words>"`.
6. If it prints the `awaiting_agent` checklist: for each step read `requests/scene-N.json`, call the MCP tool it names, save the clip, run the printed `uv run ca job complete …` (on failure retry once, then `ca job fail`); then `uv run ca video resume "<job folder>"`.
7. Success: reply with the `final.mp4` path and one line per scene; if `notes` in `details.json` say the text was not burned in, mention `captions.srt`.
8. Failure: show the error; plan problems → fix the plan and rerun; otherwise read `error` in the job's `details.json`.

### Research

### Idea to package
