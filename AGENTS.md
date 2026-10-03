# Start here (Codex)

You run this project's `ca` commands for the user. Setup: `docs/SETUP-CODEX.md`; if anything fails, run `uv run ca doctor` and follow its fixes. Details for every command: `docs/README.md`.

For requests like "make an insta post / facebook ad / reel about X", follow the skill `.agents/skills/make-content/SKILL.md`. In short:

1. Deliverables: map each thing the user named to `config/deliverables.json` (`uv run ca content deliverables` lists them) and build exactly those, nothing else ("facebook ad only" = only `facebook_ad`). An unknown or ambiguous word ("ad", "post", "facebook") means ask the user; never guess. One package holds at most one post, one image ad and one video.
2. Run `uv run ca content start --topic "X" --deliverables "<the names the user used>"`. Exit code 2 = ask the user with its message. It collects news and prints the package folder.
3. In that folder read `research.md` and `brief.template.json` (`_help` lists the deliverables, formats, layouts, pools and rules), plus `docs/company/services.md`. Write `brief.json` there: keep `deliverables`, `formats` and `platform` as set; English only; one service from `_help.services`; follow the brand rules; never invent results, statistics, prices or client names; list the articles you used in `sourceArticleIds`; fill the parts with the design choices below.
4. Run `uv run ca content build "<folder>" --dry-run`; fix every listed problem in `brief.json`; state the image cost and the video line (provider, credits, anything missing) and wait for the user's OK, for video exactly as for images.
5. Run `uv run ca content build "<folder>"`. If it prints a video checklist (Higgsfield/HeyGen), do each step as its `requests/<step>.json` says, then build again; if that MCP is not connected, tell the user to connect it. With `VIDEO_PROVIDER`/`AVATAR_PROVIDER` set to `mock` or `none` the video job is created but waits: status "draft — video pending"; tell the user exactly what it printed as missing. `uv run ca video resume "<job folder>"` or another build finishes it later.
6. Reply with the folder path, the status, and the list of files it printed (images/, video/final.mp4, post.md, package.json).

Design choices (the `post` and `ad` fields of `brief.json` = the `ca image` flags; source: `config/design_system.json`; colours, fonts and logo come from `brand.json`):

- Format (`format`): `instagram_carousel` is always `carousel` with 5 `slides` (hook with the man, 3 tips, last slide with `cta`); `facebook_ad` is always `ad` = headline + subheadline + CTA button. Other formats for single images (`ca image --format`): `statement` = one bold sentence (`headline`) · `stat` = one big number (`stat`) + one context line (`subheadline`); the number must be written in a research article whose ID goes in `source`, otherwise it is refused · `news` = the news in one line (`headline`) + what it means (`subheadline`), `layout` B or C to show the man · `person_photo` = the man in a scene, `headline` of 0–3 words · `checklist` = title + 3–5 `steps`. A CTA button exists only in `ad` and on the last carousel slide.
- Variety: leave `scene`, `wardrobe`, `props` and `pose` out; they are picked from the pools and avoid what the last 5 packages used (set one only when the user asks: a pool ID or your own words). Style images rotate per format (`person_photo` uses none). The picks are saved in `details.json` and `package.json`.
- Kind: `organic` = educational, soft CTA where the format has one ("Learn more", "Read now"). `ad` = one message, one offer, one CTA; offer words (free, analysis, demo, in 15 minutes); at most one proof number and only if real (from `docs/company/services.md`); short text; 3 variants. `story` = 9:16.
- Layout (format `ad`): A product/feature (no person; describe the system `visual`) · B or C trust/authority, alternating B and C between posts · D pain vs gain (before/after).
- Headline (format `ad`, at most 6 words): one formula (contrast, pair, principle, question, idiom twist, promise) with 1–2 `highlight` words; always fill `subheadline` and `cta`. CTA icon: `arrow` (learn/try/analyze) · `calendar` (book) · `play` (demo), chosen from the label unless `ctaIcon` is set.
- Person: designs that show the man always attach `DEFAULT_IDENTITY_SET` (`identity/person_01`). Never describe his face in words; the photos define it.
- Caption (`post.md`): `hook` (line 1) · 2–3 short `lines`, problem → solution · one `question` for comments · `cta` + `link` (ask the user if unknown; never guess) · 3–5 English hashtags including `#BrandedGenius`.

Single images or videos: use the playbooks below.

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
1. Pick the workflow: the person in a scene → `person_lifestyle`; the person delivering one of the company's services → `person_service` (`--service "…"`: the service in words; `uv run ca brand show` lists `services`); a designed post → `social_creative` with the design choices from "Start here": `--format ad|statement|stat|news|carousel|person_photo|checklist [--kind organic|ad|story] [--layout A|B|C|D] --headline "…" [--highlight "WORD1,WORD2"] [--subheadline "…"] [--sub-highlight "word"] [--cta "…" --cta-icon arrow|calendar|play] [--icons "Label1,Label2,Label3"] [--visual "…"] [--stat "58%" --source <articleId>] [--steps "Step one|Step two|Step three"] [--slide N/TOTAL]`; each format takes only its own texts and the error names what to fix. Optional `--scene`, `--wardrobe`, `--props`, `--pose` (a pool ID or your own words; otherwise picked). The logo is always added (top right); style images are chosen per format.
2. Identity: photo workflows need `--set identity/person_01` unless another person is named (`uv run ca refs list` shows the sets). In `social_creative`, designs that show the man attach `DEFAULT_IDENTITY_SET` by themselves (pass `--set` only for another person); designs without him take no `--set`. Consent: person_01 is the company lead, who provided his own photos for his company's marketing; use only identity sets of people who agreed to this use.
3. Aspect ratio: photos: IG feed 4:5 · story/reel 9:16 · LinkedIn 1:1 · YouTube 16:9. Designs: organic 4:5 (or 1:1) · ad 1:1 or 4:5 · story 9:16. Default `--count 3` unless a number is given (max 4). Designs are made at 2K (`IMAGE_DESIGN_SIZE`).
4. `--prompt` (photo workflows): a rich scene description (action, setting, light, camera/lens, mood). Leave out brand colours, tone and rules; the builder adds them. `social_creative` needs no `--prompt`. Never describe the man's face.
5. Pass the user's exact words as `--request "…"`.
6. Run: `uv run ca image --workflow <id> --set … --prompt "…" --aspect … --count … --request "…"`. If `IMAGE_PROVIDER` is not `mock` (real images use `openrouter`), first run the same command with `--dry-run` and state the estimated cost.
7. Success (exit 0): reply with the printed folder path (under `outputs/jobs/`), `actualCostUsd` from its `details.json` if set, and one line per image (`image-N.png`: what it shows).
8. Failure: show the error message and the next step: a missing set → `uv run ca refs scan` / `ca refs list`; a daily limit → wait or raise `IMAGE_DAILY_LIMIT`; `OPENROUTER_API_KEY missing` → the user adds the key to `.env` (never ask for it in chat); HTTP 402 → the user adds OpenRouter credits; a provider error → read `error` in the folder's `details.json`.

### Make videos

1. Workflow: Reel/Short → `reel_short` (≤90 s); ad → `ugc_ad` (≤60 s); talking head or podcast → `podcast_clip` (≤90 s, avatar scenes plus optional video b-roll). Voiceover is off in the MVP.
2. Write `outputs/plans/<short-name>.json` (fields in `docs/guides/module-2-video.md`): scenes numbered 1…N, each ≤15 s, adding up to `durationSec`; video `prompt` = a rich shot description; avatar `prompt` = the exact words (≈2.5 words/s); short `onScreenText`; take services, messages and captions from `docs/company/services.md` (English only; never invent results, statistics, prices or client names).
3. Start images: `startImageAssetId` = an ID from an image job's `outputAssetIds` or a set's `set.json`, or `<jobId>/image-N.png`; image scenes need one.
4. Run `uv run ca video --plan <file> --dry-run`; fix every listed problem; state the credits.
5. Run `uv run ca video --plan <file> --request "<the user's exact words>"`.
6. If it prints the `awaiting_agent` checklist: for each step follow the numbered instructions in `requests/scene-N.json` (use the connected Higgsfield/HeyGen MCP's generation tool, check its status until done, download, run the printed `uv run ca job complete …`; on failure retry once, then `ca job fail`); then `uv run ca video resume "<job folder>"`.
7. Success: reply with the `final.mp4` path and one line per scene; if `notes` in `details.json` say the text was not burned in, mention `captions.srt`.
8. Failure: show the error; plan problems → fix the plan and rerun; otherwise read `error` in the job's `details.json`.

### Research

1. Run `uv run ca research collect` (free scraper; sites in `config/sources.json`), then `uv run ca research digest --topic "…" [--days 14] [--limit 10]` (without `--topic`: newest first).
2. Summarize trends only from these articles, with their titles and links; if it says "no strong match", say so. Suggest ideas that fit `docs/company/services.md`.

### Idea to package

Use "Start here (Codex)" above: `ca content start` → `brief.json` → `ca content build --dry-run` → OK → `ca content build`.
