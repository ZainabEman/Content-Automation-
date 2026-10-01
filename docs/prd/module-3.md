

# Module 3 — Research + Full Pipeline
Status: build with mocks; live tests use our own free scraper (no paid API, no account). Images stay mock until the OpenRouter key (live image test in M1.E).

> Implementation mapping: use Python 3.13 with uv/`pyproject.toml`, type hints with mypy strict, Pydantic schemas, and the `ca` CLI instead of Node/npm tooling.

## Goal
Collect articles from chosen sources, let Codex find trends and content ideas, and turn the best idea into a ready-to-review content package (images + video + text) using M1 and M2 — fully traceable and documented.

## In scope
- config/sources.json (`SOURCES_FILE`): name, url, rssUrl (optional), topics, active.
- Collectors behind src/content_automation/research/collectors/__init__.py: free (default; our own
  scraper: RSS first, else the homepage's article links; articles read with trafilatura) and mock.
  Env SCRAPER_PROVIDER (free | mock); SCRAPER_MODEL is not used by either.
- Clean-up + duplicate check → SourceArticle files; per-run report; item limits.
- `uv run ca research:digest` → compact article list for Codex; ideas.json + ideas report written by Codex, validated.
- ContentBrief (JSON) → `uv run ca brief:run` → M1 image jobs + M2 video plan + post text → content package.
- Package review with `uv run ca package:review`: draft → approved | rejected (reviewer, note). Nothing is posted automatically.
- Codex playbooks "Research" and "Idea to package" in AGENTS.md.
- Module guide docs/guides/module-3-research.md; final pass on docs/README.md as the full automation manual.

## Out of scope
Automatic schedules (run on request) · paid scraping APIs · social-media scraping · auto-posting · analytics/performance tracking · Firecrawl (future adapter) · web dashboard.

## User flow
1. Once: fill config/sources.json; add audience + content pillars to `REFERENCES_DIR/brand/brand.json`.
2. Ask Codex: "Research this week and make 1 Reel + 1 carousel from the best idea."
3. Codex runs `uv run ca research collect` and `uv run ca research digest`, then writes the ideas report + ideas.json.
4. Codex picks the top idea, writes brief.json, runs `uv run ca brief:run` (handles M2 agent steps).
5. Codex replies with the package folder; you review with `uv run ca package:review`.

## Data
- `RESEARCH_DIR/articles/YYYY-MM/<articleId>.json` (default `RESEARCH_DIR=research`) — SourceArticle {articleId = hash of clean URL,
  source, url, title, author, publishedAt, content, summary, topics[], collectedAt}.
- `RESEARCH_DIR/runs/<runId>.json` (default `RESEARCH_DIR=research`) — per-source counts (found, new, duplicates, too old,
  undated, blocked by robots.txt, failed) and errors.
- `RESEARCH_DIR/reports/YYYY-MM-DD_ideas.md` (default `RESEARCH_DIR=research`) + ideas.json {ideas[{ideaId, trend, format
  (reel|carousel|linkedin|podcast|image_post), hook, whyNow, articleIds[]}]}.
- brief.json — ContentBrief {briefId, ideaId, topic, audience, platform, objective, hook, keyPoints[],
  script, imageRequirements[], videoRequirements[], voiceRequirements[], brandConstraints[], sourceArticleIds[]}.
- `PACKAGES_DIR/YYYY-MM-DD_<slug>/` (default `PACKAGES_DIR=packages`) — brief.json, images/, video/final.mp4, script.md, post.md,
  package.json {packageId, briefId, childJobIds[], status, reviewer, note, timestamps}.

## Integrations / APIs
- Our own scraper with free open-source libraries only: httpx (requests), feedparser (RSS), trafilatura
  (article text, title, date, author). No paid scraping API, no account. Polite: robots.txt, 1–2 s between
  requests, clear user agent, timeouts, RESEARCH_MAX_ITEMS_PER_SOURCE, RESEARCH_LOOKBACK_DAYS.
- Reuses M1 images and M2 video/voice (including agent steps).
- Env: `SCRAPER_PROVIDER=free` (or mock), `SOURCES_FILE=config/sources.json`, `RESEARCH_DIR=research`, `PACKAGES_DIR=packages`, `OUTPUT_DIR=outputs`, `REFERENCES_DIR=assets/reference`,
  RESEARCH_MAX_ITEMS_PER_SOURCE, RESEARCH_LOOKBACK_DAYS.

## Acceptance criteria
- [ ] `uv run pytest` passes offline with every provider set to mock.
- [ ] An invalid sources.json, ideas.json or brief.json gives a clear list of problems; nothing is spent.
- [ ] Live collect from the configured sources (RSS, or homepage links when a site has no feed) creates SourceArticle files; running it again adds 0 duplicates.
- [ ] A failing source doesn't stop the others; the run report shows counts and errors.
- [ ] Every trend in the ideas report links to its source articles.
- [ ] `uv run ca brief:run` (mock) creates a package with carousel slides, final.mp4, script.md, post.md and package.json linking all jobs, status "draft".
- [ ] `uv run ca package:review` records approved/rejected with reviewer + note.
- [ ] Traceability: from final.mp4 you can follow the links back to the brief, the idea and the source articles.
- [ ] Live end-to-end via Codex (you and your social media manager): research → ideas → package folder in the shared folder.
- [ ] docs/guides/module-3-research.md has every template section; docs/README.md covers overview, one-time setup, daily use, all module guides, troubleshooting, glossary and switching providers.

## Tasks
Every task updates the guide sections for what it built.
- M3.T1 config/sources.json with the chosen sites (RSS feeds checked, robots.txt allows us).
- M3.T2 Collectors (free, mock), clean-up, duplicate check, SourceArticle store + tests.
- M3.T3 `uv run ca research collect` command, run report, limits + tests.
- M3.T4 `uv run ca research digest`, ideas.json schema, `uv run ca research:save-ideas`, ideas report template.
- M3.T5 ContentBrief schema + `uv run ca brief:run` → package folder + package.json; end-to-end mock test.
- M3.T6 `uv run ca package:review` + `uv run ca package:list`; traceability test.
- M3.T7 Playbooks in AGENTS.md; finish the guide + full docs/README.md; live end-to-end test by you and your social media manager.
