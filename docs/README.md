# Content Automation

Branded Genius's content assistant. You ask Codex in plain English ("make an Instagram post
about AI chatbots"); it researches the topic, writes the brief, makes the images and the reel,
and puts everything (with the caption, hashtags and sources) in one folder for you to review.
Nothing is posted automatically.

## Start here

- **New computer?** Follow [Set up Codex Desktop](SETUP-CODEX.md) step by step.
- **Something not working?** Ask Codex to run `uv run ca doctor`; every problem comes with a fix.

## Daily use

Ask Codex for a post, ad or reel about a topic. Codex follows `AGENTS.md`:

1. `uv run ca content start --topic "…"` collects fresh news and creates a package folder in
   `outputs/content/YYYY-MM-DD_<topic>/` with `research.md` and `brief.template.json`.
2. Codex writes `brief.json` (designs, reel, caption) from the research, the company
   profile (`docs/company/services.md`), the brand rules and the design system
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
| `uv run ca content start --topic "…" [--platform instagram\|facebook\|linkedin] [--formats post,ad,reel]` | Research + package folder with the brief template. |
| `uv run ca content build <folder> [--dry-run]` | Makes what is missing in a package (or shows the cost). |
| `uv run ca research collect` | Collects new articles from the sites in `config/sources.json`. |
| `uv run ca research digest [--topic "…"] [--days 14] [--limit 10]` | Lists saved articles, ranked by topic if given. |
| `uv run ca image …` | One image job (see the [Images guide](guides/module-1-images.md)). |
| `uv run ca video --plan <file> [--dry-run]` / `uv run ca video resume <job>` | One video job (see the [Video guide](guides/module-2-video.md)). |
| `uv run ca job status\|complete\|fail <job> …` | Job records and video steps done by Codex. |
| `uv run ca refs scan\|list\|frames\|primary` | Reference photo library. |
| `uv run ca brand show` | Summary of `brand.json`. |
| `uv run ca hello` | Shows the settings (keys hidden). |

## Folders

| Folder | What is in it |
| --- | --- |
| `outputs/content/` | Content packages, one folder per topic and day (`PACKAGES_DIR`). |
| `outputs/jobs/` | Every single image or video job with its `details.json` (`OUTPUT_DIR`). |
| `research/` | Collected articles and run reports (`RESEARCH_DIR`). |
| `assets/reference/` | Your photos, logo, style examples and `brand.json`. |
| `config/sources.json` | The news sites to read. |
| `config/design_system.json` | The look of designed graphics: layouts, poses, text rules. |
| `docs/company/services.md` | Company profile: services, message, content rules. |

## Guides

- [Set up Codex Desktop](SETUP-CODEX.md)
- [Module 1: Images](guides/module-1-images.md)
- [Module 2: Video](guides/module-2-video.md)
- [Module 3: Research and content packages](guides/module-3-research.md)
- [Guide template](guides/_TEMPLATE.md)

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
| Images | `IMAGE_PROVIDER` | `openrouter` (real, paid) or `mock` (free placeholders) |
| Video clips | `VIDEO_PROVIDER` | `higgsfield-mcp` (via Codex) or `mock` |
| Avatar clips | `AVATAR_PROVIDER` | `heygen-mcp` (via Codex) or `mock` |
| Voiceover | `VOICE_PROVIDER` | `none` (MVP) |
| News | `SCRAPER_PROVIDER` | `free` (our own scraper) or `mock` |

## Glossary

- **Package**: one folder with everything for one topic (images, video, post text, sources).
- **Brief** (`brief.json`): Codex's plan for a package: designs (layout, texts), reel, caption.
- **Design system**: the fixed look of our graphics; colours, fonts and logo come from `brand.json`.
- **Job**: one image or video request, with its record `details.json`.
- **Mock**: a free stand-in that makes placeholders, for trying things out.
- **MCP**: a connection that lets Codex use an outside service (Higgsfield, HeyGen) with your account.
- **Agent step**: a part of a job that Codex does through an MCP; the job waits until it is recorded.
- **Dry run**: shows what would happen and what it costs, without making anything.

## For developers

- Plans: [Module 1](prd/module-1.md), [Module 2](prd/module-2.md), [Module 3](prd/module-3.md),
  [blueprint](blueprints/blueprint.md), [progress log](PROGRESS.md).
- Python 3.13 with uv: `uv sync`, then `uv run ca --help`. Keys stay in `.env` only.
