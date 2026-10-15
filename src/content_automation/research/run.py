"""`ca research collect` and `ca research digest`."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from math import ceil

from content_automation.core.config import Settings
from content_automation.research.collectors import CollectRequest, collect_source, get_collector
from content_automation.research.models import (
    RunReport,
    SourceArticle,
    SourcesError,
    SourceStats,
    load_run_limits,
    load_sources,
)
from content_automation.research.store import (
    known_article_ids,
    load_articles,
    save_article,
    save_run_report,
)
from content_automation.research.topics import TopicDigest, rank_by_topic

SNIPPET_CHARS = 300
DEFAULT_TOPIC_LIMIT = 10


def progress_line(stats: SourceStats) -> str:
    """"tagesschau.de: 5 new, 2 dup" or "heise online: timeout" (one line per source)."""
    reason = ""
    if stats.errors:
        reason = "timeout" if any("Timeout" in error for error in stats.errors) else (
            stats.errors[-1].split(": ", 1)[-1][:80])
    if reason and not stats.found and not stats.new:
        return f"{stats.source}: {reason}"
    line = f"{stats.source}: {stats.new} new, {stats.duplicates} dup"
    line += f", {stats.failed} failed" if stats.failed else ""
    return line + (f" ({reason})" if reason else "")


def collect(settings: Settings, *, limit: int | None = None,
            progress: Callable[[str], None] | None = None) -> tuple[RunReport, str]:
    """Collect every active source; save new articles and a run report.

    Returns the report and the report file path. Raises SourcesError for a bad
    sources.json; a failing source is recorded in the report and never stops the others.
    sources.json "run": each request times out after requestTimeoutSeconds, a source stops after
    maxFailuresPerSource failed articles, and the run stops after maxRunSeconds (what was saved
    is kept: partial results). limit: at most this many new articles, spread over the sources.
    progress: called with one line per source as it finishes.
    """
    sources = [source for source in load_sources(settings.sources_file) if source.runs]
    if not sources:
        raise SourcesError([f"no active sources in {settings.sources_file}"])
    limits = load_run_limits(settings.sources_file)
    collector = get_collector(settings.scraper_provider, settings)
    started = datetime.now(UTC)
    deadline = started + timedelta(seconds=limits.max_run_seconds)
    share = max(1, ceil(limit / len(sources))) if limit else None
    say = progress or (lambda line: None)
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
        left = None if limit is None else limit - len(report.new_articles)
        skipped = ("the run's time cap" if datetime.now(UTC) >= deadline else
                   f"limit {limit} reached" if left is not None and left <= 0 else None)
        if skipped is not None:
            report.sources.append(SourceStats(source=source.name, errors=[f"skipped: {skipped}"]))
            say(f"{source.name}: skipped ({skipped})")
            continue
        cap = None if share is None or left is None else min(share, left)
        result = collect_source(
            collector,
            CollectRequest(
                source=source,
                since=since,
                max_items=settings.research_max_items_per_source,
                known_ids=frozenset(known),
                timeout_s=limits.request_timeout_seconds,
                deadline=deadline,
                max_failures=limits.max_failures_per_source,
                max_new=cap,
            ),
        )
        stats = result.stats
        for article in result.articles:
            if article.article_id in known:
                stats.duplicates += 1
                continue
            if cap is not None and stats.new >= cap:
                break
            save_article(settings.research_dir, article)
            report.new_articles.append(article.article_id)
            known.add(article.article_id)
            stats.new += 1
        report.sources.append(stats)
        say(progress_line(stats))
    if datetime.now(UTC) >= deadline:
        say(f"Run cap {limits.max_run_seconds:g} s reached: partial results "
            f"({len(report.new_articles)} new article(s) kept).")
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
