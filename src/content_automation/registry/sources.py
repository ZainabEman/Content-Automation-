"""Research sources (Phase 5 P5-D4): SRC-#### records linked to ideas.

A source is a newsletter item, an article, a fetched web page or a manual note: its URL and the
original URL behind a tracking link, title, publisher, language, dates, purpose, trust (primary,
secondary, unknown) and where its text is kept. The same URL (or original URL) is one source.
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal, cast

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.ids import allocate_counter, resolve

SourceType = Literal["newsletter", "article", "web", "manual"]
Trust = Literal["primary", "secondary", "unknown"]
SOURCE_TYPES: tuple[SourceType, ...] = ("newsletter", "article", "web", "manual")
TRUST_LEVELS: tuple[Trust, ...] = ("primary", "secondary", "unknown")


@dataclass(frozen=True)
class Source:
    id: str
    type: SourceType
    url: str | None
    original_url: str | None
    title: str | None
    publisher: str | None
    language: str | None
    published_at: str | None
    fetched_at: str | None
    purpose: str | None
    trust: Trust
    text_path: str | None
    created_at: str


def format_source_id(number: int) -> str:
    return f"SRC-{number:04d}"


def _source(row: sqlite3.Row) -> Source:
    def text(name: str) -> str | None:
        return None if row[name] is None else str(row[name])

    return Source(
        id=str(row["id"]), type=cast(SourceType, str(row["type"])), url=text("url"),
        original_url=text("original_url"), title=text("title"), publisher=text("publisher"),
        language=text("language"), published_at=text("published_at"),
        fetched_at=text("fetched_at"), purpose=text("purpose"),
        trust=cast(Trust, str(row["trust"])), text_path=text("text_path"),
        created_at=str(row["created_at"]),
    )


def get_source(conn: sqlite3.Connection, source_id: str) -> Source:
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id.strip().upper(),)
                       ).fetchone()
    if row is None:
        raise RegistryError(f"Source {source_id} does not exist.")
    return _source(row)


def find_by_url(conn: sqlite3.Connection, *urls: str | None) -> Source | None:
    """The source whose URL or original URL is one of `urls`."""
    for url in urls:
        if not url:
            continue
        row = conn.execute("SELECT * FROM sources WHERE url = ? OR original_url = ? ORDER BY "
                           "number LIMIT 1", (url, url)).fetchone()
        if row is not None:
            return _source(row)
    return None


def add_source(
    conn: sqlite3.Connection, source_type: SourceType, *, url: str | None = None,
    original_url: str | None = None, title: str | None = None, publisher: str | None = None,
    language: str | None = None, published_at: str | None = None,
    fetched_at: str | None = None, purpose: str | None = None, trust: Trust = "unknown",
    text_path: str | None = None, actor: Actor = "system", command: str | None = None,
) -> tuple[Source, bool]:
    """(the source, created): an existing source with the same URL is returned as it is."""
    if source_type not in SOURCE_TYPES:
        raise RegistryError(f'Unknown source type "{source_type}" ({", ".join(SOURCE_TYPES)}).')
    if trust not in TRUST_LEVELS:
        raise RegistryError(f'Unknown trust "{trust}" ({", ".join(TRUST_LEVELS)}).')
    with transaction(conn):
        existing = find_by_url(conn, url, original_url)
        if existing is not None:
            return existing, False
        source_id = format_source_id(allocate_counter(conn, "source"))
        number = int(source_id.split("-")[1])
        conn.execute(
            "INSERT INTO sources (id, number, type, url, original_url, title, publisher, "
            "language, published_at, fetched_at, purpose, trust, text_path, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (source_id, number, source_type, url, original_url, title, publisher, language,
             published_at, fetched_at, purpose, trust, text_path, now()),
        )
        append_event(conn, "item_updated", actor=actor, command=command,
                     details={"source_added": source_id, "type": source_type, "url": url,
                              "original_url": original_url})
        return get_source(conn, source_id), True


def link_source(conn: sqlite3.Connection, ref: str, source_id: str, *, role: str | None = None,
                actor: Actor = "system", command: str | None = None) -> bool:
    """Link a source to an idea (or any item); False if it was linked already."""
    with transaction(conn):
        item_id = resolve(conn, ref)
        source = get_source(conn, source_id)
        if conn.execute("SELECT 1 FROM idea_sources WHERE item_id = ? AND source_id = ?",
                        (item_id, source.id)).fetchone():
            return False
        conn.execute("INSERT INTO idea_sources (item_id, source_id, role, created_at) "
                     "VALUES (?, ?, ?, ?)", (item_id, source.id, role, now()))
        append_event(conn, "item_updated", actor=actor, command=command, item_id=item_id,
                     details={"source_linked": source.id, "role": role})
        return True


def item_sources(conn: sqlite3.Connection, ref: str) -> list[Source]:
    item_id = resolve(conn, ref)
    rows = conn.execute("SELECT s.* FROM sources s JOIN idea_sources l ON l.source_id = s.id "
                        "WHERE l.item_id = ? ORDER BY s.number", (item_id,))
    return [_source(row) for row in rows]
