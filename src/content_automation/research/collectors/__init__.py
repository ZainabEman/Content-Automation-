"""Scraper capability: the only public entry point for article collectors.

App code calls ``collect_source()``; adapters live in ``providers/`` and are chosen by
``SCRAPER_PROVIDER``: ``free`` (default; our own polite scraper: RSS first, else the
homepage's article links, articles read with trafilatura) or ``mock`` (offline).
An adapter returns the new articles of one source plus counts; a failure is reported
in that source's stats and never stops the other sources.
"""

import importlib
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode
from content_automation.research.models import Source, SourceArticle, SourceStats

# How our scraper names itself to websites (also used by `ca doctor`).
USER_AGENT = "BrandedGeniusResearchBot/0.1 (content research; respects robots.txt)"

# Provider name -> adapter module. Adding a provider = one adapter file + one line here.
_ADAPTERS: dict[str, str] = {
    "free": "content_automation.research.collectors.providers.free",
    "mock": "content_automation.research.collectors.providers.mock",
}


class CollectorError(Exception):
    """Base class for scraper errors."""


class UnknownCollectorError(CollectorError):
    """SCRAPER_PROVIDER names an adapter that does not exist."""


class CollectRequest(BaseModel):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    source: Source
    since: datetime  # only articles published after this
    max_items: int = Field(ge=1)  # newest article links looked at per source
    known_ids: frozenset[str] = frozenset()  # already saved: skipped without fetching
    timeout_s: float | None = None  # per HTTP request (sources.json run)
    deadline: datetime | None = None  # the run cap: no new request after it
    max_failures: int | None = None  # the source stops after this many failed articles
    max_new: int | None = None  # at most this many new articles from this source


class CollectResult(BaseModel):
    stats: SourceStats
    articles: list[SourceArticle] = Field(default_factory=list)


class Collector(Protocol):
    """Adapter contract. Each adapter module exposes ``create_provider(settings)``."""

    name: str
    mode: AdapterMode

    def collect(self, request: CollectRequest) -> CollectResult: ...


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def get_collector(name: str, settings: Settings | None = None) -> Collector:
    module_name = _ADAPTERS.get(name)
    if module_name is None:
        raise UnknownCollectorError(
            f"Scraper provider '{name}' is not available. Set SCRAPER_PROVIDER to one of: "
            f"{', '.join(available_providers())}."
        )
    collector: Collector = importlib.import_module(module_name).create_provider(settings)
    return collector


def collect_source(collector: Collector, request: CollectRequest) -> CollectResult:
    """Collect one source; any unexpected failure becomes an error in its stats."""
    try:
        return collector.collect(request)
    except Exception as error:  # one source must never stop the others
        stats = SourceStats(source=request.source.name)
        stats.errors.append(f"{type(error).__name__}: {error}")
        return CollectResult(stats=stats)
