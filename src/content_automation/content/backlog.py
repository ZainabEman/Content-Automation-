"""The idea backlog's way in (Phase 5 P5-D6, D7, D9, D10, D11, D13).

Every candidate — a scraper article, a newsletter idea, a manual topic — takes the same path:
- a duplicate (a source URL already linked to an idea, or a title close to an idea's title,
  see find_duplicate) is merged into the older idea: its sources are added there;
- otherwise a new idea (kind idea, proposed) with its sources linked;
- a first pillar from the strategy keywords (Codex scores it later); no pillar → flagged
  off_strategy, never dropped.
`ca research run` reports collected / duplicates / off_strategy / flagged claims / failed fetches.
"""

import difflib
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from content_automation.content.research_input import ResearchFile
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.registry.ideas import create_idea, get_details, list_ideas, update_details
from content_automation.registry.sources import (
    SourceType,
    Trust,
    add_source,
    item_sources,
    link_source,
    set_text_path,
)
from content_automation.registry.strategy import Strategy
from content_automation.research.fetch import NewsletterConfig, fetch_article
from content_automation.research.models import load_sources
from content_automation.research.run import collect
from content_automation.research.store import find_article

_WORD = re.compile(r"[a-zäöüß0-9]+")
STOP_WORDS = frozenset({"the", "a", "an", "and", "or", "for", "of", "to", "in", "on", "with",
                        "how", "why", "what", "der", "die", "das", "und", "für", "mit", "von"})


@dataclass
class SourceInput:
    type: SourceType
    url: str | None = None
    original_url: str | None = None
    title: str | None = None
    publisher: str | None = None
    language: str | None = None
    published_at: str | None = None
    purpose: str | None = None
    trust: Trust = "unknown"
    text: str | None = None  # saved as research/sources/<SRC>.txt
    text_path: str | None = None  # or a file that already holds it (an article JSON)
    role: str | None = None


@dataclass
class Candidate:
    title: str
    summary: str = ""
    sources: list[SourceInput] = field(default_factory=list)
    original_text: str | None = None  # a manual topic, verbatim
    assumptions: list[str] = field(default_factory=list)


@dataclass
class RunCounts:
    collected: int = 0
    ideas: int = 0
    duplicates: int = 0
    off_strategy: int = 0
    flagged_claims: int = 0
    failed_fetches: int = 0
    unknown_senders: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    def summary(self) -> str:
        unknown = (f"; unknown senders (reported, kept): {', '.join(self.unknown_senders)}"
                   if self.unknown_senders else "")
        return (f"Research run: collected {self.collected}, new ideas {self.ideas}, duplicates "
                f"{self.duplicates}, off_strategy {self.off_strategy}, flagged claims "
                f"{self.flagged_claims}, failed fetches {self.failed_fetches}{unknown}.")


def words(text: str) -> set[str]:
    return {word for word in _WORD.findall(text.lower()) if word not in STOP_WORDS}


def similarity(first: str, second: str) -> float:
    """Title closeness 0-1: the higher of difflib's ratio and the token overlap (Jaccard)."""
    ratio = difflib.SequenceMatcher(None, first.lower(), second.lower()).ratio()
    a, b = words(first), words(second)
    overlap = len(a & b) / len(a | b) if a | b else 0.0
    return max(ratio, overlap)


def pillar_guess(text: str, strategy: Strategy) -> str | None:
    """The strategy pillar with the most keyword hits in `text` (None: off strategy)."""
    lowered = text.lower()
    hits = {pillar.key: sum(1 for keyword in pillar.keywords if keyword in lowered)
            for pillar in strategy.pillars}
    best = max(hits.items(), key=lambda pair: pair[1], default=("", 0))
    return best[0] if best[1] > 0 else None


def find_duplicate(conn: sqlite3.Connection, candidate: Candidate,
                   strategy: Strategy) -> str | None:
    """The older idea this candidate repeats: a URL match always, else a close title."""
    urls = {url for source in candidate.sources
            for url in (source.url, source.original_url) if url}
    if urls:
        marks = ", ".join("?" for _ in urls)
        row = conn.execute(
            f"SELECT l.item_id FROM idea_sources l JOIN sources s ON s.id = l.source_id "
            f"JOIN items i ON i.id = l.item_id WHERE i.kind = 'idea' AND (s.url IN ({marks}) "
            f"OR s.original_url IN ({marks})) ORDER BY i.number LIMIT 1", (*urls, *urls),
        ).fetchone()
        if row is not None:
            return str(row["item_id"])
    for item, details in list_ideas(conn):
        if details.duplicate_of:
            continue
        if similarity(item.title, candidate.title) >= strategy.duplicate_threshold:
            return item.id
    return None


def _add_sources(conn: sqlite3.Connection, settings: Settings, item_id: str,
                 sources: list[SourceInput], command: str | None) -> None:
    for given in sources:
        source, created = add_source(
            conn, given.type, url=given.url, original_url=given.original_url,
            title=given.title, publisher=given.publisher, language=given.language,
            published_at=given.published_at,
            fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            purpose=given.purpose, trust=given.trust, text_path=given.text_path,
            command=command,
        )
        if created and given.text:
            path = settings.research_dir / "sources" / f"{source.id}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, given.text + "\n")
            set_text_path(conn, source.id, path.as_posix())
        link_source(conn, item_id, source.id, role=given.role, command=command)


def ingest(conn: sqlite3.Connection, settings: Settings, candidate: Candidate,
           strategy: Strategy, counts: RunCounts, *, actor: str = "system",
           command: str | None = None) -> str:
    """The candidate as an idea (or merged into the older one); returns the BG ID."""
    duplicate = find_duplicate(conn, candidate, strategy)
    if duplicate is not None:
        _add_sources(conn, settings, duplicate, candidate.sources, command)
        counts.duplicates += 1
        counts.lines.append(f"{duplicate}: duplicate of \"{candidate.title}\"; sources added")
        return duplicate
    item = create_idea(conn, candidate.title, topic=candidate.summary or candidate.title,
                       original_text=candidate.original_text,
                       assumptions=candidate.assumptions,
                       actor="user" if actor == "user" else "system", command=command)
    _add_sources(conn, settings, item.id, candidate.sources, command)
    pillar = pillar_guess(f"{candidate.title} {candidate.summary}", strategy)
    flags = [] if pillar else ["off_strategy"]
    update_details(conn, item.id, pillar=pillar, flags=flags, command=command)
    counts.ideas += 1
    counts.off_strategy += 0 if pillar else 1
    counts.lines.append(f"{item.id} idea: {item.title} ({pillar or 'off_strategy'})")
    return item.id


def run_sources(conn: sqlite3.Connection, settings: Settings, strategy: Strategy,
                counts: RunCounts, *, limit: int, command: str | None,
                progress: Callable[[str], None] | None = None) -> None:
    """The enabled scraper sources: this run's new articles (at most `limit`, spread over the
    sources) become ideas; `progress` gets one line per source as it finishes."""
    report, _ = collect(settings, limit=limit, progress=progress)
    configs = {source.name: source for source in load_sources(settings.sources_file)}
    counts.collected += report.new
    for article_id in report.new_articles[:limit]:
        article = find_article(settings.research_dir, article_id)
        if article is None:
            continue
        config = configs.get(article.source)
        paths = list(settings.research_dir.glob(f"articles/*/{article_id}.json"))
        ingest(conn, settings, Candidate(article.title, article.summary, [SourceInput(
            "article", url=article.url, title=article.title, publisher=article.source,
            language=config.language if config else None,
            published_at=article.published_at.isoformat(),
            trust=config.trust if config else "unknown",
            text_path=paths[0].as_posix() if paths else None, role="article")]),
            strategy, counts, command=command)


def newest_list(settings: Settings) -> Path | None:
    files = sorted((settings.research_dir / "newsletters").glob("*_content-list.json"))
    return files[-1] if files else None


def run_newsletters(conn: sqlite3.Connection, settings: Settings, strategy: Strategy,
                    newsletters: NewsletterConfig, list_file: Path, counts: RunCounts, *,
                    command: str | None) -> None:
    """A content list the research-ideas skill saved: each idea with its newsletter sources;
    links of senders that allow it are followed to the original article."""
    data = ResearchFile.model_validate_json(list_file.read_text(encoding="utf-8"))
    for idea in data.ideas:
        sources: list[SourceInput] = []
        for given in idea.sources:
            sender = newsletters.sender_for(given.url) if given.url else None
            sender = sender or next((s for s in newsletters.senders
                                     if s.name.lower() == (given.source or "").lower()), None)
            if sender is None and given.source and given.source not in counts.unknown_senders:
                counts.unknown_senders.append(given.source)
            source = SourceInput("newsletter", url=given.url, title=given.title,
                                 publisher=given.source, published_at=str(given.date),
                                 purpose=sender.purpose if sender else None,
                                 text=given.excerpt, role="newsletter")
            if given.url and (sender is None or sender.follow_links):
                fetched = fetch_article(given.url, newsletters.limits)
                if fetched.error is None:
                    source.original_url = fetched.original_url
                    source.text = fetched.text or given.excerpt
                    source.language = fetched.language
                else:
                    counts.failed_fetches += 1
                    counts.lines.append(f"failed fetch: {given.url}: {fetched.error}")
            sources.append(source)
        counts.collected += 1
        ingest(conn, settings, Candidate(idea.title, idea.summary, sources), strategy, counts,
               command=command)


def idea_sources_line(conn: sqlite3.Connection, item_id: str) -> str:
    details = get_details(conn, item_id)
    sources = item_sources(conn, item_id)
    return (f"{item_id}: pillar {details.pillar or '—'}, flags {', '.join(details.flags) or '—'}, "
            f"{len(sources)} source(s)")
