"""PRD v6 R2/R6: the topic pool, and the memory that keeps rejected, deleted and already
generated topics from coming back.

The pool (config/topic_pool.json): the German-society AI themes, the verified services and the
newsletters, mixed by sourceMix; `theme_of` names a topic's theme and `spread` orders topics so
the same theme is never planned back to back. No topic has to map to a service. Its `topics` are
the candidates `ca topics refill` and `ca topics search` saved (content/topic_refill.py), each
with its checked sources (URL, publisher, date, quote) so later copy and research steps can trace
it back; the calendar fills slots with them when the newsletters and articles run out.

The memory is read fresh from what is stored (so it holds across restarts and new runs): the
registry (idea rejected or deleted, generation generated), the weekly calendars (Rejected,
Deleted, Generated rows) and the packages' package.json topics (a rejected package keeps its
topic, R8). `TopicMemory.check(topic)` names why a new topic is blocked: the same normalised
text, or a near-duplicate (similarity at or above the threshold with enough shared content
words), so a reworded repeat is blocked and a different angle on the same broad theme is not.
Every suggestion source (the weekly calendar, the monthly plan, the backlog import) asks it.
"""

from __future__ import annotations

import csv
import difflib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from content_automation.core.files import atomic_write_text

CONFIG_FILE = Path("config/topic_pool.json")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_WORD = re.compile(r"[a-zäöüß0-9]+")
STOP_WORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "of", "to", "in", "on", "with", "how", "why", "what",
    "is", "are", "your", "you", "der", "die", "das", "den", "dem", "des", "ein", "eine", "einen",
    "einem", "und", "oder", "für", "mit", "von", "im", "am", "auf", "bei", "zu", "zum",
    "zur", "ist", "sind", "wie", "was", "warum", "wenn", "nicht", "ihr", "ihre", "sie", "du",
    "dein", "deine", "wir", "es", "als", "aus", "vor", "nach", "über"})
BLOCKING = ("rejected", "deleted", "generated")
SOURCES = ("society", "services", "newsletters", "search")


class TopicPoolError(ValueError):
    """config/topic_pool.json is missing or invalid."""


@dataclass(frozen=True)
class Theme:
    id: str
    label: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class TopicSource:
    """A checked source of a pool topic (content/topic_sources.py)."""

    url: str
    publisher: str
    date: str  # YYYY-MM-DD, as found on the page
    title: str
    quote: str
    tier: int

    def as_json(self) -> dict[str, str | int]:
        return {"url": self.url, "publisher": self.publisher, "date": self.date,
                "title": self.title, "quote": self.quote, "tier": self.tier}


@dataclass(frozen=True)
class PoolTopic:
    """A topic candidate saved by `ca topics refill|search` (Codex wrote it, ca checked it)."""

    topic: str
    source: str  # society | services | newsletters | search
    reader_angle: str  # what it means for a German business reader
    theme: str | None = None
    service: str | None = None
    ref: str | None = None  # newsletter:<YYYY-MM-DD>#<n> for a newsletter topic
    added: str = ""
    sources: tuple[TopicSource, ...] = ()
    search_theme: str | None = None  # the theme `ca topics search` was given
    week: str | None = None  # YYYY-Www: planned first in that week (search --week)
    evergreen: bool = False  # a timeless theme: the source may be older than maxAgeDays

    def as_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "topic": self.topic, "source": self.source, "theme": self.theme,
            "searchTheme": self.search_theme, "service": self.service,
            "readerAngle": self.reader_angle, "ref": self.ref, "week": self.week,
            "evergreen": self.evergreen,
            "sources": [source.as_json() for source in self.sources], "added": self.added}
        return {key: value for key, value in data.items() if value}


@dataclass(frozen=True)
class TopicPool:
    themes: tuple[Theme, ...]
    source_mix: dict[str, float]
    threshold: float
    min_shared: int
    topics: tuple[PoolTopic, ...] = ()

    def label(self, theme_id: str | None) -> str:
        return next((theme.label for theme in self.themes if theme.id == theme_id), "")


def _pool_file(path: Path) -> Path:
    return path if path.is_file() or path.is_absolute() else _PROJECT_ROOT / path


def _text(value: object) -> str | None:
    return str(value) if value else None


@lru_cache(maxsize=4)
def load_pool(path: Path = CONFIG_FILE) -> TopicPool:
    try:
        data = json.loads(_pool_file(path).read_text(encoding="utf-8"))
        themes = tuple(Theme(str(item["id"]), str(item["label"]),
                             tuple(str(word).lower() for word in item["keywords"]))
                       for item in data["themes"])
        duplicates = data.get("duplicates", {})
        mix = {str(key): float(value) for key, value in data.get("sourceMix", {}).items()}
        topics = tuple(PoolTopic(str(item["topic"]), str(item["source"]),
                                 str(item.get("readerAngle", "")), _text(item.get("theme")),
                                 _text(item.get("service")), _text(item.get("ref")),
                                 str(item.get("added", "")),
                                 tuple(TopicSource(str(found["url"]),
                                                   str(found.get("publisher", "")),
                                                   str(found.get("date", "")),
                                                   str(found.get("title", "")),
                                                   str(found.get("quote", "")),
                                                   int(found.get("tier", 0)))
                                       for found in item.get("sources", [])),
                                 _text(item.get("searchTheme")), _text(item.get("week")),
                                 bool(item.get("evergreen", False)))
                       for item in data.get("topics", []))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise TopicPoolError(f"{path}: {error}") from None
    if not themes or abs(sum(mix.values()) - 1.0) > 0.01:
        raise TopicPoolError(f"{path}: needs themes and a sourceMix that adds up to 1")
    return TopicPool(themes, mix, float(duplicates.get("threshold", 0.6)),
                     int(duplicates.get("minSharedWords", 3)), topics)


def render_pool(data: dict[str, Any]) -> str:
    """The pool file as it is written by hand: two-space indent, one theme or topic per line,
    short objects on one line."""
    parts: list[str] = []
    for key, value in data.items():
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            text = "[\n" + ",\n".join(f"    {json.dumps(item, ensure_ascii=False)}"
                                      for item in value) + "\n  ]"
        else:
            text = json.dumps(value, ensure_ascii=False)
            if len(text) > 100:
                text = json.dumps(value, ensure_ascii=False, indent=2).replace("\n", "\n  ")
        parts.append(f"  {json.dumps(key)}: {text}")
    return "{\n" + ",\n".join(parts) + "\n}\n"


def add_topics(topics: Sequence[PoolTopic], path: Path = CONFIG_FILE) -> int:
    """Append refilled topics to the pool file (everything else is kept); the pool's size."""
    found = _pool_file(path)
    try:
        data = json.loads(found.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TopicPoolError(f"{path}: {error}") from None
    data["topics"] = [*data.get("topics", []), *(topic.as_json() for topic in topics)]
    atomic_write_text(found, render_pool(data))
    load_pool.cache_clear()
    return len(data["topics"])


def normalise_topic(text: str) -> str:
    """Case, accents of form (NFC), punctuation and spacing do not make a topic new."""
    folded = unicodedata.normalize("NFC", text).casefold()
    return " ".join(_WORD.findall(folded))


def content_words(text: str) -> set[str]:
    return {word for word in _WORD.findall(normalise_topic(text)) if word not in STOP_WORDS}


def similarity(first: str, second: str) -> float:
    """0-1: the higher of the word overlap (Jaccard over content words) and the character
    ratio of the normalised texts."""
    a, b = content_words(first), content_words(second)
    overlap = len(a & b) / len(a | b) if a | b else 0.0
    ratio = difflib.SequenceMatcher(None, normalise_topic(first), normalise_topic(second)).ratio()
    return max(overlap, ratio)


def theme_of(text: str, pool: TopicPool | None = None) -> str | None:
    """The theme with the most keyword hits (whole words or word starts), None: no theme."""
    pool = pool or load_pool()
    lowered = normalise_topic(text)
    words = lowered.split()
    best: tuple[int, str | None] = (0, None)
    for theme in pool.themes:
        hits = sum(1 for keyword in theme.keywords
                   if (" " in keyword and keyword in lowered)
                   or any(word.startswith(keyword) for word in words))
        if hits > best[0]:
            best = (hits, theme.id)
    return best[1]


def spread[T](items: Sequence[T], text: Callable[[T], str], pool: TopicPool | None = None
              ) -> list[T]:
    """The items in their order, except that the same theme never follows itself while another
    theme is waiting (R2: themes spread over the plan)."""
    pool = pool or load_pool()
    waiting = list(items)
    ordered: list[T] = []
    last: str | None = None
    while waiting:
        index = next((n for n, item in enumerate(waiting)
                      if last is None or theme_of(text(item), pool) != last), 0)
        chosen = waiting.pop(index)
        theme = theme_of(text(chosen), pool)
        last = theme if theme is not None else None
        ordered.append(chosen)
    return ordered


@dataclass(frozen=True)
class Known:
    topic: str
    status: str  # rejected | deleted | generated
    where: str  # BG-7, calendar 2026-W43 row 3, package <folder>


@dataclass
class TopicMemory:
    known: list[Known] = field(default_factory=list)
    pool: TopicPool | None = None

    def check(self, topic: str) -> str | None:
        """Why a new topic is blocked (None: it is new enough)."""
        pool = self.pool or load_pool()
        key = normalise_topic(topic)
        if not key:
            return None
        words = content_words(topic)
        for entry in self.known:
            if normalise_topic(entry.topic) == key:
                return f'{entry.status} before ({entry.where}): "{entry.topic}"'
        for entry in self.known:
            shared = len(words & content_words(entry.topic))
            if shared >= pool.min_shared and similarity(topic, entry.topic) >= pool.threshold:
                return f'too close to a topic {entry.status} before ({entry.where}): ' \
                       f'"{entry.topic}"'
        return None

    def allowed[T](self, topics: Sequence[T], text: Callable[[T], str]
                   ) -> tuple[list[T], list[str]]:
        """(the topics that may be suggested, one line per blocked one)."""
        kept: list[T] = []
        lines: list[str] = []
        for item in topics:
            reason = self.check(text(item))
            if reason is None:
                kept.append(item)
            else:
                lines.append(f'Skipped "{text(item)}": {reason}')
        return kept, lines


def _registry_known(conn: sqlite3.Connection) -> list[Known]:
    found: list[Known] = []
    rows = conn.execute("SELECT id, title, topic, idea_status, generation_status FROM items "
                        "WHERE kind NOT IN ('youtube_style') ORDER BY number")
    for row in rows:
        status = (str(row["idea_status"]) if row["idea_status"] in ("rejected", "deleted")
                  else "generated" if row["generation_status"] in ("generated", "partial")
                  else None)
        if status is not None:
            found.append(Known(str(row["title"] or row["topic"]), status, str(row["id"])))
    return found


def _calendar_known(calendar_dir: Path) -> list[Known]:
    found: list[Known] = []
    for path in sorted(calendar_dir.glob("*.csv")) if calendar_dir.is_dir() else []:
        try:
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
        except (OSError, csv.Error, UnicodeDecodeError):
            continue
        for row in rows:
            status = str(row.get("Status") or "").strip().lower()
            topic = str(row.get("Topic") or "").strip()
            if topic and status in BLOCKING:
                found.append(Known(topic, status, f"calendar {path.stem} row {row.get('Row')}"))
    return found


def _package_known(packages_dir: Path) -> list[Known]:
    found: list[Known] = []
    for path in packages_dir.rglob("package.json") if packages_dir.is_dir() else []:
        try:
            data: Any = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("topic") and data.get("items"):
            found.append(Known(str(data["topic"]), "generated", f"package {path.parent.name}"))
    return found


def topic_memory(*, conn: sqlite3.Connection | None, calendar_dir: Path | None = None,
                 packages_dir: Path | None = None) -> TopicMemory:
    """Everything generated, rejected or deleted so far, read fresh from what is stored."""
    known: list[Known] = []
    if conn is not None:
        known += _registry_known(conn)
    if calendar_dir is not None:
        known += _calendar_known(calendar_dir)
    if packages_dir is not None:
        known += _package_known(packages_dir)
    return TopicMemory(known)


__all__ = ["BLOCKING", "CONFIG_FILE", "SOURCES", "Known", "PoolTopic", "Theme", "TopicMemory",
           "TopicPool", "TopicPoolError", "TopicSource", "add_topics", "content_words",
           "load_pool", "normalise_topic", "render_pool", "similarity", "spread", "theme_of",
           "topic_memory"]
