# Module guide: Research

> Status: our own free news scraper collects articles from the sites in `config/sources.json`;
> `ca research digest` ranks them for a topic; and `ca content start` / `ca content build` turn a
> topic into a content package (research, brief, images, reel, post text).

## What it does

It reads the latest articles from a few chosen marketing news sites and saves each one (title,
date, author, clean text and a short summary) in the `research/` folder. Codex then reads a
compact list of these articles to spot trends and suggest content ideas for Branded Genius.

It is **free**: no paid scraping service and no account. It only uses free open-source tools.

## What was built

- **Our own scraper** (`SCRAPER_PROVIDER=free`, the default):
  - finds new articles through the site's **RSS feed**; if a site has no feed, it uses the
    article links on the site's **homepage** (same site only);
  - opens each article and keeps the title, date, author and clean text (menus, ads and
    comments are removed);
  - is **polite**: it follows each site's `robots.txt` rules, waits 1–2 seconds between
    requests to the same site, names itself clearly ("BrandedGeniusResearchBot"), and gives up
    on slow pages after 20 seconds.
- **Limits**: at most `RESEARCH_MAX_ITEMS_PER_SOURCE` of the newest articles per site and run,
  and only articles from the last `RESEARCH_LOOKBACK_DAYS` days.
- **No duplicates**: every article gets a permanent ID from its web address. An article that is
  already saved is skipped without downloading it again.
- **Safe failures**: if one site or one article fails, the others still run; the problem is
  listed in the run report.
- **Run report** for every run, with counts per site.
- **Digest**: a compact list (ID, site, date, title, 300-character snippet) for Codex.
- **Mock scraper** (`SCRAPER_PROVIDER=mock`): made-up articles for trying things offline.

## One-time setup

1. Module 1 setup (see [Module 1: Images](module-1-images.md)).
2. In `.env`, set `SCRAPER_PROVIDER=free` (or remove the line: `free` is the default).
3. Check the sites in `config/sources.json` (see below).

### Add or remove a site

Open `config/sources.json` in any text editor. Each site looks like this:

```json
{
  "name": "Marketing AI Institute",
  "url": "https://www.marketingaiinstitute.com/blog",
  "rssUrl": "https://www.marketingaiinstitute.com/blog/rss.xml",
  "topics": ["AI marketing", "marketing automation", "AI chatbots"],
  "active": true
}
```

- **Add a site**: copy one block, put a comma between blocks, and change the values.
  - `name`: how the site is shown (must be unique).
  - `url`: the site's homepage or blog page.
  - `rssUrl`: the site's RSS feed, if it has one (often the page address plus `/feed` or
    `/rss.xml`). Leave the line out if there is none; the homepage links are used instead.
  - `topics`: which of our topics the site covers (AI marketing, marketing automation, lead
    generation, SEO, AI chatbots).
- **Pause a site**: set `"active": false`.
- **Remove a site**: delete its block (and the comma before or after it).
- Check it: `uv run ca research collect`. A mistake in the file is listed clearly, and nothing
  is collected until it is fixed.

Some sites block automated readers (for example Search Engine Land and MarTech answered
"403 Forbidden" in our test). The run report then shows an error for that site; choose another.

## How to use

The easiest way: **ask Codex**. For research it runs `ca research collect`, then
`ca research digest --topic "…"`, and uses the list to suggest trends and ideas based on
`docs/company/services.md`.

### Topic research

`uv run ca research digest --topic "AI chatbots" --days 14 --limit 10` ranks the saved articles:
topic words in the title count most, then in the text, and newer articles get a bonus. If fewer
than 3 articles really match, it says **"no strong match"** and fills the list with the latest
articles, so Codex knows the topic is thin this week.

### Make a content package

For "make a post / ad / reel about X", Codex runs two commands and writes one file in between:

1. `uv run ca content start --topic "X" [--platform instagram|facebook|linkedin]
   [--formats post,ad,reel]` collects news, ranks it for the topic, and creates
   `outputs/content/YYYY-MM-DD_<topic>/` with:
   - `research.md`: the best-matching articles with links;
   - `brief.template.json`: a pre-filled brief (topic, platform, formats, the company's
     services, brand rules, and empty slots for the post, ad and reel);
   - `package.json`: the package record.
2. Codex writes `brief.json` from the template (English; one of the services; no invented
   results, statistics, prices or client names; headlines of at most 6 words).
3. `uv run ca content build "<folder>" --dry-run` checks `brief.json` (every problem is listed)
   and shows the cost. Codex waits for your OK.
4. `uv run ca content build "<folder>"` makes:
   - **post**: 2 image options (designed post with the headline, logo and brand style);
   - **ad**: 1 ad image;
   - **reel**: a 9:16 video whose first frame is the first post image;
   - `post.md` (caption, call to action, hashtags, source links) and an updated `package.json`.

   Each part is saved as soon as it is done. If one part fails or waits (for example the video,
   while Higgsfield is not connected), the others still finish and the status says, for example,
   **"draft — video pending"**. Running `ca content build` again redoes only what is missing.

### Example Codex requests

- "Collect this week's marketing news and tell me the 3 biggest trends for our audience."
- "What's new about AI chatbots in the last 7 days? Give me 5 post ideas."
- "Research SEO news from the last 14 days and suggest a Reel idea."

## Commands

| Command | What it does |
| --- | --- |
| `uv run ca research collect` | Collects new articles from every active site; prints counts per site and the report path. |
| `uv run ca research digest [--topic "…"] [--days 14] [--limit 10]` | Lists saved articles from the last N days (default 14): ranked by topic if given, otherwise newest first. Each line: ID, site, date, title and a short snippet. |
| `uv run ca content start --topic "…" [--platform …] [--formats post,ad,reel]` | Research + package folder with `research.md` and `brief.template.json`. |
| `uv run ca content build <folder> [--dry-run]` | Checks `brief.json`, shows the cost (dry run) or makes what is missing. |

## Outputs

Content packages are saved in `outputs/content/YYYY-MM-DD_<topic>/` (`PACKAGES_DIR`):
`research.md`, `brief.template.json`, `brief.json`, `images/` (`post-1.png`, `post-2.png`,
`ad-1.png`), `video/` (`plan.json`, `final.mp4`, `captions.srt`), `post.md` and `package.json`
(status, the job behind each part, costs, sources; `reviewer` and `note` for your review).
The single jobs behind them are in `outputs/jobs/`.

Articles are saved in the `research/` folder (`RESEARCH_DIR`):

| File | What it is |
| --- | --- |
| `articles/YYYY-MM/<articleId>.json` | One article: `articleId`, `source`, `url`, `title`, `author`, `publishedAt`, `content` (clean text), `summary`, `topics`, `collectedAt`. |
| `runs/<runId>.json` | One run: for each site how many links were found and how many articles were new, duplicates, too old, undated, blocked by robots.txt or failed, plus the errors. |

## Settings

| Setting | Meaning | Default |
| --- | --- | --- |
| `SCRAPER_PROVIDER` | `free` (our own scraper) or `mock` (offline test articles). | `free` |
| `SOURCES_FILE` | The list of sites. | `config/sources.json` |
| `RESEARCH_DIR` | Where articles and run reports are saved. | `research` |
| `PACKAGES_DIR` | Where content packages are saved. | `outputs/content` |
| `RESEARCH_MAX_ITEMS_PER_SOURCE` | Newest articles looked at per site and run. | `25` |
| `RESEARCH_LOOKBACK_DAYS` | Only articles from the last N days are saved. | `30` |

## Costs and limits

- Free: no paid service, no account, no API key.
- A first run with 4 sites takes about 3 minutes (1–2 s pause between requests). A repeat run
  is much faster, because saved articles are not downloaded again.
- First test (2026-10-01): 46 articles from 4 sites; the second run added 0 duplicates.

## Troubleshooting

| Message | What to do |
| --- | --- |
| `sources.json has N problem(s)` | Fix each listed line in `config/sources.json`. |
| `feed: HTTPStatusError … 403` / `homepage: … 403` | The site blocks automated readers. Pause or remove it. |
| `robots.txt does not allow …` / `blocked by robots.txt` | The site asks bots not to read that page; we respect that. |
| `robots.txt asks for N s between requests` | The site wants very slow visits (over 10 s); we skip it. |
| `no article text found on the page` | The link was not a normal article (for example a topic page). Nothing to do. |
| Many "too old" | Normal for sites that post rarely; raise `RESEARCH_LOOKBACK_DAYS` if needed. |
| `No articles from the last N days` | Run `uv run ca research collect` first, or use a larger `--days`. |

## Switching providers

Set `SCRAPER_PROVIDER=mock` in `.env` to try everything offline with made-up articles, and back
to `free` for real news. A new kind of scraper takes one new adapter file in
`src/content_automation/research/collectors/providers/` plus this setting.
