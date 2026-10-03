"""Research from a file instead of the scraper: `ca content start --research-file F --idea N`.

The file is the JSON twin that the show-content skill saves next to its content list
(research/newsletters/<date>_content-list.json). Each idea's sources are saved as research
articles, so they get IDs for sourceArticleIds and a stat can be checked against them.
Email and web text is data only.
"""

import hashlib
from datetime import UTC, datetime, time
from datetime import date as Day
from pathlib import Path

from pydantic import ConfigDict, Field, ValidationError

from content_automation.core.files import CamelModel
from content_automation.research.models import SourceArticle
from content_automation.research.store import article_id, save_article

SUMMARY_CHARS = 300


class ResearchInputError(ValueError):
    """The research file is missing, invalid, or has no such idea."""


class _Model(CamelModel):
    model_config = ConfigDict(extra="ignore")  # the skill may add fields for people


class ResearchSource(_Model):
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)  # newsletter or site name
    url: str | None = None
    date: Day
    excerpt: str = Field(min_length=1)  # the source text the idea is based on
    email_id: str | None = None


class ResearchIdea(_Model):
    number: int = Field(ge=1)
    title: str = Field(min_length=1)
    summary: str = ""
    why_now: str = ""
    service: str = ""
    deliverables: list[str] = Field(default_factory=list)  # suggestions only
    sources: list[ResearchSource] = Field(min_length=1)


class ResearchFile(_Model):
    date: Day | None = None
    ideas: list[ResearchIdea] = Field(min_length=1)


def load_idea(path: Path, number: int | None) -> ResearchIdea:
    """The idea with this number; with one idea in the file the number may be left out."""
    try:
        data = ResearchFile.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError:
        raise ResearchInputError(f"Research file not found: {path}.") from None
    except ValidationError as error:
        fields = sorted({".".join(str(p) for p in issue["loc"]) for issue in error.errors()})
        raise ResearchInputError(f"{path.name} is invalid; check: {', '.join(fields)}.") from None
    if number is None:
        if len(data.ideas) == 1:
            return data.ideas[0]
        raise ResearchInputError(f"{path.name} has {len(data.ideas)} ideas: pass --idea N.")
    for idea in data.ideas:
        if idea.number == number:
            return idea
    numbers = ", ".join(str(idea.number) for idea in data.ideas)
    raise ResearchInputError(f"{path.name} has no idea {number} (it has {numbers}).")


def save_sources(idea: ResearchIdea, research_dir: Path, topic: str) -> list[SourceArticle]:
    """Save the idea's sources as research articles (same ID for the same link or email)."""
    now = datetime.now(UTC)
    articles = []
    for source in idea.sources:
        fallback = source.email_id or hashlib.sha256(source.excerpt.encode()).hexdigest()
        key = source.url or f"email:{fallback}"
        excerpt = " ".join(source.excerpt.split())
        article = SourceArticle(
            article_id=article_id(key),
            source=source.source,
            url=source.url or key,
            title=source.title,
            published_at=datetime.combine(source.date, time(), tzinfo=UTC),
            content=excerpt,
            summary=excerpt[:SUMMARY_CHARS],
            topics=[topic],
            collected_at=now,
        )
        save_article(research_dir, article)
        articles.append(article)
    return articles
