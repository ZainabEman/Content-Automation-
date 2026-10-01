"""Offline mock adapter: three made-up articles per source, no network."""

from datetime import UTC, datetime, timedelta

from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode
from content_automation.research.collectors import CollectRequest, CollectResult
from content_automation.research.models import SourceArticle, SourceStats
from content_automation.research.store import article_id, clean_url

ARTICLES_PER_SOURCE = 3


class MockCollector:
    name = "mock"
    mode: AdapterMode = "code"

    def collect(self, request: CollectRequest) -> CollectResult:
        source = request.source
        stats = SourceStats(source=source.name, via="mock")
        articles: list[SourceArticle] = []
        now = datetime.now(UTC)
        for index in range(1, min(ARTICLES_PER_SOURCE, request.max_items) + 1):
            url = clean_url(f"{source.url.rstrip('/')}/mock-article-{index}")
            stats.found += 1
            key = article_id(url)
            if key in request.known_ids:
                stats.duplicates += 1
                continue
            topic = source.topics[(index - 1) % len(source.topics)] if source.topics else "news"
            text = (
                f"Mock article {index} from {source.name} about {topic}. "
                "This placeholder text stands in for a real article so the research flow "
                "can be tried offline without fetching anything."
            )
            articles.append(
                SourceArticle(
                    article_id=key,
                    source=source.name,
                    url=url,
                    title=f"Mock: {topic} update {index}",
                    author="Mock Author",
                    published_at=now - timedelta(hours=index),
                    content=text,
                    summary=text,
                    topics=list(source.topics),
                    collected_at=now,
                )
            )
        return CollectResult(stats=stats, articles=articles)


def create_provider(settings: Settings | None = None) -> MockCollector:
    return MockCollector()
