# Content Automation

> **v5 (2026-10-19):** UGC ads, podcast media and finished YouTube videos are no longer generated (PRD v5 R8). Only reels (`reel_short`, Higgsfield) remain as video; HeyGen avatar clips are not used by any workflow. YouTube is research and production planning: `ca youtube` and the make-youtube skill. Everything the audience sees is German.

Branded Genius's content assistant. You ask Codex in plain English ("make an Instagram post
about AI chatbots"); it researches the topic, writes the brief, makes the images and the reel,
and puts everything (with the caption, hashtags and sources) in one folder for you to review.
Nothing is posted automatically.

## Start here

- **New computer?** Follow [Set up Codex Desktop](SETUP-CODEX.md) step by step.
- **Something not working?** Ask Codex to run `uv run ca doctor`; every problem comes with a fix.

## The flow

1. **"Show content"** (or "what's new"): Codex reads your Gmail newsletters (label
   `Newsletters`, last 7 days, read-only) and shows 5-10 numbered ideas that fit our services.
2. **"Make 3"**, **"make 2 and 5"** or **"make a post about X"**: Codex writes the research and
   the text (`research.md`, `content.md`) for free, then asks **"What should I make?"**
3. You name what you want (for example "insta post and fb ad"). Codex builds exactly that: it
   shows the cost and waits for your **"ok"**, then makes the images and `post.md` (one caption
   per deliverable).
4. A video waits until Codex has made the clips with Higgsfield or HeyGen (it asks for "ok"
   again); then the package has `video/final.mp4`.

Anyone shown in an image or video is always you (your reference photos); designs without you
show no people.

## Daily use

Ask Codex for a post, ad or reel about a topic. Codex follows `AGENTS.md`:

1. `uv run ca content start --topic "…" --deliverables "<what you named>"` collects fresh news
   and creates a package folder (only for what you named: an insta post is a 5-slide carousel;
   a reel is a real video part; v5: no UGC ad or podcast clip) in
   `outputs/content/YYYY-MM-DD_<topic>/` with `research.md` and `brief.template.json`.
2. Codex writes `brief.json` (designs, reel, caption) from the research, the company
   profile (`brand/services.md`), the brand rules and the design system
   (`config/design_system.json`).
3. `uv run ca content build "<folder>" --dry-run` shows the cost; Codex waits for your OK.
4. `uv run ca content build "<folder>"` makes 2 post images (in a format that changes from
   package to package; a carousel gets one image per slide), 3 ad variants and the reel, plus
   `post.md` (caption, hashtags, call to action, source links) and `package.json`.
   If the video needs Higgsfield/HeyGen, the package says "draft — video pending" until Codex
   has made the clips; running the build again finishes only what is missing.

You can also ask for single images, videos or research (see the guides).

## Commands

| Command | What it does |
| --- | --- |
| `uv run ca doctor` | Checks the setup and explains how to fix each problem. |
| `uv run ca content deliverables` | What can be made and the names that ask for it. |
| `uv run ca content start --topic "…" \| --research-file <list.json> --idea N [--deliverables "<names>"]` | Stage 1: research + package folder (deliverables optional). |
| `uv run ca content set <folder> --deliverables "<names>"` | Stage 2: name the deliverables; writes the brief template for exactly those. |
| `uv run ca content build <folder> [--dry-run] [--authorize <DR-id>]` | Makes what is missing in a package (or shows the cost and the dry run ID; a paid build needs `--authorize` after "ok"). |
| `uv run ca item list\|status\|approve\|reject\|revise\|resubmit\|history …` | Content items by BG ID (see the [Registry guide](guides/module-5-registry.md)). |
| `uv run ca jobs list\|check\|resume\|cancel`, `uv run ca auth list`, `uv run ca audit show` | Jobs, spending authorizations and the audit log. |
| `uv run ca registry migrate [--dry-run]` | Registers calendars and packages made before the registry (once; backup first). |
| `uv run ca help commands` | Every phrase you can say in Codex, grouped by skill. |
| `uv run ca calendar new\|check\|show\|approve\|reject\|generate [--week next]` | The week's content calendar: propose, check, approve or reject rows, generate the approved ones (see the [Calendar and Drive guide](guides/module-4-calendar-drive.md)). |
| `uv run ca drive setup` / `uv run ca drive sync [<folder>]` | One-time Google sign-in, folders and Content Tracker; upload finished files and update the tracker. |
| `uv run ca tracking show\|export\|conflicts\|resolve` | Content Tracker status counts; CSV copy (local + "Content Tracker.csv" in Drive); hand-edit conflicts and how to settle them. |
| `uv run ca research collect` | Collects new articles from the sites in `config/sources.json`. |
| `uv run ca research digest [--topic "…"] [--days 14] [--limit 10]` | Lists saved articles, ranked by topic if given. |
| `uv run ca plan month YYYY-MM [--apply]` | v5: the monthly social plan, about 2 graphics a day, with the cost of the planned volume (free). |
| `uv run ca youtube plan\|research\|check-sources\|scripts\|bilingual\|check\|storyboards\|select-style\|upload\|status` | v5: YouTube research and production planning; storyboards for A, B and C (skill make-youtube). |
| `uv run ca design preview\|compare\|check` | Layout variants with sample copy, beside the approved references, and the free design check. |
| `uv run ca image …` | One image job (see the [Images guide](guides/module-1-images.md)). |
| `uv run ca video --plan <file> [--dry-run]` / `uv run ca video resume <job>` | One video job (see the [Video guide](guides/module-2-video.md)). |
| `uv run ca job status\|complete\|fail\|review <job> …` | Job records, video steps done by Codex, and the person check of an image. |
| `uv run ca refs scan\|list\|frames\|primary\|tag\|mask` | Reference photo library (`tag`: people/logo tags of a style image; `mask`: logo-free copies of the past ads). |
| `uv run ca env set HEYGEN_AVATAR_ID\|HEYGEN_VOICE_ID <id>` | Sets one HeyGen ID line in `.env` (never shows the file). |
| `uv run ca brand show` | Summary of `config/brand.json`. |
| `uv run ca hello` | Shows the settings (keys hidden). |

## Folders

| Folder | What is in it |
| --- | --- |
| `outputs/content/` | Content packages, one folder per topic and day (`PACKAGES_DIR`). |
| `outputs/jobs/` | Every single image or video job with its `details.json` (`OUTPUT_DIR`). |
| `research/` | Collected articles and run reports (`RESEARCH_DIR`). |
| `calendar/` | The weekly content calendars, `<YYYY-Www>.csv` (not in git). |
| `outputs/drive/` | Stand-in for Google Drive while `STORAGE_PROVIDER=mock` (folders + `tracking.csv`). |
| `assets/reference/` | Your photos, logo and style examples (not in git). |
| `config/brand.json`, `config/references.json` | The brand profile; the style tags, primary photos and logo areas to cover (in git). |
| `config/sources.json` | The news sites to read. |
| `config/deliverables.json` | What can be asked for by name (insta post, facebook ad, reel, ...). |
| `config/design_system.json` | The look of designed graphics: layouts, poses, text rules. |
| `brand/services.md` | Company profile: services, message, content rules. |

## Guides

- [Set up Codex Desktop](SETUP-CODEX.md)
- [Module 1: Images](guides/module-1-images.md)
- [Module 2: Video](guides/module-2-video.md)
- [Module 3: Research and content packages](guides/module-3-research.md)
- [Module 4: Calendar, Google Drive and the Content Tracker](guides/module-4-calendar-drive.md)
- v5: [PRD](PRD-v5-german-brand-youtube.md) · [implementation notes and acceptance table](v5-implementation-notes.md) · [Drive actions waiting for "ok"](v5-drive-actions.md) · [reference analysis](../brand/reference-analysis.md) · `ca plan month`, `ca youtube …`, `ca design compare`
- [Module 5: Content items, approvals and spending (the registry)](guides/module-5-registry.md)
- [Module 6: YouTube production planning](guides/module-6-youtube.md)
- [Guide template](guides/_TEMPLATE.md)
- [Pre-Codex check](PRE-CODEX-CHECK.md): what was checked before Codex testing, and what only Codex can check

## Troubleshooting

1. Run `uv run ca doctor` and follow the **Fix:** lines.
2. A content package says "draft — … failed": read `error` for that part in `package.json`,
   fix it, and run `uv run ca content build "<folder>"` again (finished parts are kept).
3. "draft — video pending": the reel waits for Codex to make the clips with Higgsfield/HeyGen;
   follow the printed checklist, then build again.
4. Each guide has its own troubleshooting table.

## Switching providers

All choices are lines in `.env`; nothing else changes.

| What | Setting | Options |
| --- | --- | --- |
| Images | `IMAGE_PROVIDER` | `codex_builtin` (default: Codex's built-in image generation, $0; `ca image import`), `openrouter` (opt-in, paid) or `mock` (free placeholders) |
| Video clips | `VIDEO_PROVIDER` | `higgsfield-plugin` (Codex plugin), `mock` or `none` |
| Avatar clips | `AVATAR_PROVIDER` | `heygen-plugin` (Codex plugin), `mock` or `none` |
| Voiceover | `VOICE_PROVIDER` | `none` (MVP) |
| News | `SCRAPER_PROVIDER` | `free` (our own scraper) or `mock` |
| Files and tracker | `STORAGE_PROVIDER` | `plugin` (Codex Google Drive plugin + upload manifests), `drive` (separate Google API connection), or `mock` (`outputs/drive/`) |

## Glossary

- **Package**: one folder with everything for one topic (images, video, post text, sources).
- **Brief** (`brief.json`): Codex's plan for a package: designs (layout, texts), reel, caption.
- **Design system**: the fixed look of our graphics; colours, fonts and logo come from `config/brand.json`, and the brand guide's rules apply to every format.
- **Job**: one image or video request, with its record `details.json`.
- **Mock**: a free stand-in that makes placeholders, for trying things out.
- **Plugin**: an app installed in Codex (Gmail, Higgsfield, HeyGen) that Codex uses with your account.
- **Skill**: written instructions Codex follows for one kind of request (`.agents/skills/`).
- **Agent step**: a part of a job that Codex does with a plugin; the job waits until it is recorded.
- **Dry run**: shows what would happen and what it costs, without making anything.

## For developers

- Plans: [Module 1](prd/module-1.md), [Module 2](prd/module-2.md), [Module 3](prd/module-3.md),
  [blueprint](blueprints/blueprint.md), [progress log v1](PROGRESS-v1.md).
- v2: [PRD](PRD.md), [progress log v2](PROGRESS.md).
- Python 3.13 with uv: `uv sync`, then `uv run ca --help`. Keys stay in `.env` only.
