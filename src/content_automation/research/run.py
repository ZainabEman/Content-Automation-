"""`ca research collect` and `ca research digest`."""

from datetime import UTC, datetime, timedelta

from content_automation.core.config import Settings
from content_automation.research.collectors import CollectRequest, collect_source, get_collector
from content_automation.research.models import RunReport, SourceArticle, SourcesError, load_sources
from content_automation.research.store import (
    known_article_ids,
    load_articles,
    save_article,
    save_run_report,
)
from content_automation.research.topics import TopicDigest, rank_by_topic

SNIPPET_CHARS = 300
DEFAULT_TOPIC_LIMIT = 10


def collect(settings: Settings) -> tuple[RunReport, str]:
    """Collect every active source; save new articles and a run report.

    Returns the report and the report file path. Raises SourcesError for a bad
    sources.json; a failing source is recorded in the report and never stops the others.
    """
    sources = [source for source in load_sources(settings.sources_file) if source.active]
    if not sources:
        raise SourcesError([f"no active sources in {settings.sources_file}"])
    collector = get_collector(settings.scraper_provider, settings)
    started = datetime.now(UTC)
    report = RunReport(
        run_id=started.strftime("%Y-%m-%d_%H%M%S"),
        provider=collector.name,
        started_at=started,
        lookback_days=settings.research_lookback_days,
        max_items_per_source=settings.research_max_items_per_source,
    )
    known = known_article_ids(settings.research_dir)
    since = started - timedelta(days=settings.research_lookback_days)
    for source in sources:
        result = collect_source(
            collector,
            CollectRequest(
                source=source,
                since=since,
                max_items=settings.research_max_items_per_source,
                known_ids=frozenset(known),
            ),
        )
        stats = result.stats
        for article in result.articles:
            if article.article_id in known:
                stats.duplicates += 1
                continue
            save_article(settings.research_dir, article)
            known.add(article.article_id)
            stats.new += 1
        report.sources.append(stats)
    report.finished_at = datetime.now(UTC)
    path = save_run_report(settings.research_dir, report)
    return report, str(path)


def digest(settings: Settings, days: int) -> list[SourceArticle]:
    """Saved articles from the last `days` days, newest first."""
    return load_articles(settings.research_dir, datetime.now(UTC) - timedelta(days=days))


def topic_digest(settings: Settings, topic: str, days: int, limit: int) -> TopicDigest:
    """Articles from the last `days` days ranked by relevance to `topic`."""
    return rank_by_topic(digest(settings, days), topic, days=days, limit=limit)


def topic_note(result: TopicDigest) -> str | None:
    if not result.weak:
        return None
    return (
        f'no strong match: only {result.strong_matches} article(s) match "{result.topic}"; '
        "added the latest articles."
    )


def digest_lines(articles: list[SourceArticle]) -> list[str]:
    """Compact list for Codex: id | source | date | title, then a 300-character snippet."""
    lines: list[str] = []
    for article in articles:
        snippet = " ".join((article.summary or article.content).split())
        if len(snippet) > SNIPPET_CHARS:
            snippet = snippet[: SNIPPET_CHARS - 3].rstrip() + "..."
        lines.append(
            f"{article.article_id} | {article.source} | "
            f"{article.published_at.astimezone(UTC):%Y-%m-%d} | {article.title}"
        )
        lines.append(f"    {snippet}")
    return lines
