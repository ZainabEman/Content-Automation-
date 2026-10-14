"""Research records: sources.json entries, saved articles and run reports."""

from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.core.files import CamelModel


class SourcesError(ValueError):
    """sources.json is missing or invalid; ``problems`` lists every issue."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        lines = "\n".join(f"- {problem}" for problem in problems)
        super().__init__(f"sources.json has {len(problems)} problem(s):\n{lines}")


class Source(CamelModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    url: str = Field(pattern=r"^https?://")
    rss_url: str | None = Field(default=None, pattern=r"^https?://")
    topics: list[str] = Field(default_factory=list)
    active: bool = True  # v1 switch, still read
    # v2 (Phase 5 P5-D8): all optional, so v1 entries load unchanged.
    language: str = "en"
    region: str | None = None
    type: Literal["rss", "html"] | None = None  # None: RSS if rssUrl is set, else the homepage
    pillar_hints: list[str] = Field(default_factory=list)
    trust: Literal["primary", "secondary", "unknown"] = "unknown"
    enabled: bool = True
    note: str | None = Field(default=None, alias="_note")

    @model_validator(mode="after")
    def _check_type(self) -> Self:
        if self.type == "rss" and not self.rss_url:
            raise ValueError('type "rss" needs an rssUrl')
        return self

    @property
    def runs(self) -> bool:
        """Collected only if neither `active` (v1) nor `enabled` (v2) is false."""
        return self.active and self.enabled

    @property
    def use_feed(self) -> bool:
        return bool(self.rss_url) and self.type != "html"


class SourcesFile(CamelModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    note: str | None = Field(default=None, alias="_note")
    sources: list[Source]


class SourceArticle(CamelModel):
    """RESEARCH_DIR/articles/YYYY-MM/<articleId>.json"""

    article_id: str  # hash of the clean URL
    source: str
    url: str
    title: str
    author: str | None = None
    published_at: datetime
    content: str
    summary: str
    topics: list[str] = Field(default_factory=list)
    collected_at: datetime


class SourceStats(CamelModel):
    """What happened to one source in one run."""

    source: str
    found: int = 0  # article links found (feed entries or homepage links)
    new: int = 0
    duplicates: int = 0
    too_old: int = 0
    no_date: int = 0
    blocked: int = 0  # not allowed by robots.txt
    failed: int = 0  # articles that could not be fetched or read
    via: str = ""  # "rss" or "homepage"
    errors: list[str] = Field(default_factory=list)


class RunReport(CamelModel):
    """RESEARCH_DIR/runs/<runId>.json"""

    run_id: str
    provider: str
    started_at: datetime
    finished_at: datetime | None = None
    lookback_days: int
    max_items_per_source: int
    sources: list[SourceStats] = Field(default_factory=list)
    new_articles: list[str] = Field(default_factory=list)  # article IDs saved by this run

    @property
    def new(self) -> int:
        return sum(stats.new for stats in self.sources)

    @property
    def duplicates(self) -> int:
        return sum(stats.duplicates for stats in self.sources)


def load_sources(path: Path) -> list[Source]:
    """Read and check sources.json; raise SourcesError listing every problem."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise SourcesError([f"cannot read {path}"]) from None
    try:
        sources = SourcesFile.model_validate_json(text).sources
    except ValidationError as error:
        problems = []
        for issue in error.errors(include_url=False):
            location = ".".join(
                f"[{part + 1}]" if isinstance(part, int) else str(part) for part in issue["loc"]
            ).replace(".[", "[")
            problems.append(f"{location or 'file'}: {issue['msg']}")
        raise SourcesError(problems) from None
    names = [source.name for source in sources]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise SourcesError([f"source names must be unique: {', '.join(duplicates)}"])
    return sources
