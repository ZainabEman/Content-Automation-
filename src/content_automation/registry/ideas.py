"""Ideas in the backlog (Phase 5 P5-D1, D9, D10, D11): items of kind `idea` plus their details.

An idea uses only the idea gate (approve, reject, revise via `ca item`). Its details: the pillar,
the score (0-100) and its parts, flags (e.g. off_strategy), the user's original words for a manual
topic and the assumptions Codex made, and `duplicate_of` once merged into an older idea.
"""

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.items import Item, create_item, get_item


@dataclass(frozen=True)
class IdeaDetails:
    item_id: str
    pillar: str | None = None
    score: int | None = None
    score_parts: dict[str, Any] = field(default_factory=dict)
    flags: tuple[str, ...] = ()
    original_text: str | None = None
    assumptions: tuple[str, ...] = ()
    duplicate_of: str | None = None


def create_idea(
    conn: sqlite3.Connection, title: str, *, topic: str | None = None,
    original_text: str | None = None, assumptions: Sequence[str] = (),
    platforms: Sequence[str] = (), notes: str | None = None, actor: Actor = "system",
    command: str | None = None,
) -> Item:
    """A new idea item (proposed) with its details row."""
    with transaction(conn):
        item = create_item(conn, kind="idea", title=title, topic=topic or title,
                           platforms=platforms, notes=notes, actor=actor, command=command)
        conn.execute(
            "INSERT INTO ideas (item_id, original_text, assumptions, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (item.id, original_text, json.dumps(list(assumptions), ensure_ascii=False), now()),
        )
        return item


def get_details(conn: sqlite3.Connection, ref: str) -> IdeaDetails:
    item = get_item(conn, ref)
    if not item.is_idea:
        raise RegistryError(f"{item.id} is a {item.kind}, not an idea.")
    row = conn.execute("SELECT * FROM ideas WHERE item_id = ?", (item.id,)).fetchone()
    if row is None:
        return IdeaDetails(item.id)
    return IdeaDetails(
        item_id=item.id, pillar=row["pillar"], score=row["score"],
        score_parts=dict(json.loads(row["score_parts"])),
        flags=tuple(json.loads(row["flags"])), original_text=row["original_text"],
        assumptions=tuple(json.loads(row["assumptions"])), duplicate_of=row["duplicate_of"],
    )


def update_details(
    conn: sqlite3.Connection, ref: str, *, actor: Actor = "system", command: str | None = None,
    **changes: Any,
) -> IdeaDetails:
    """Change pillar, score, score_parts, flags or duplicate_of (logged)."""
    allowed = {"pillar", "score", "score_parts", "flags", "duplicate_of"}
    unknown = set(changes) - allowed
    if unknown:
        raise RegistryError(f"Unknown idea field(s): {', '.join(sorted(unknown))}.")
    with transaction(conn):
        details = get_details(conn, ref)
        values: dict[str, Any] = {
            key: json.dumps(value, ensure_ascii=False) if key in ("score_parts", "flags")
            else value for key, value in changes.items()
        }
        conn.execute("INSERT OR IGNORE INTO ideas (item_id, updated_at) VALUES (?, ?)",
                     (details.item_id, now()))
        if values:
            sets = ", ".join(f"{key} = ?" for key in values)
            conn.execute(f"UPDATE ideas SET {sets}, updated_at = ? WHERE item_id = ?",
                         (*values.values(), now(), details.item_id))
        append_event(conn, "item_updated", actor=actor, command=command,
                     item_id=details.item_id, details={"idea": _plain(changes)})
        return get_details(conn, details.item_id)


def _plain(changes: Mapping[str, Any]) -> dict[str, Any]:
    return {key: list(value) if isinstance(value, tuple) else value
            for key, value in changes.items()}


def list_ideas(conn: sqlite3.Connection) -> list[tuple[Item, IdeaDetails]]:
    rows = conn.execute("SELECT id FROM items WHERE kind = 'idea' ORDER BY number")
    return [(get_item(conn, str(row["id"])), get_details(conn, str(row["id"]))) for row in rows]
