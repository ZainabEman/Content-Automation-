"""Decisions (PRD §5): every approve, reject or revise with its text; rows are never changed.

Each decision is also a "decision" event in the audit log.
"""

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import now, transaction
from content_automation.registry.ids import resolve

Gate = Literal["idea", "review"]
Action = Literal["approve", "reject", "revise"]


@dataclass(frozen=True)
class Decision:
    id: int
    item_id: str
    version: int
    gate: Gate
    action: Action
    text: str | None
    actor: Actor
    created_at: str


def record_decision(
    conn: sqlite3.Connection,
    item_id: str,
    version: int,
    gate: Gate,
    action: Action,
    text: str | None,
    *,
    actor: Actor = "user",
    command: str | None = None,
    details: Mapping[str, Any] | None = None,
) -> Decision:
    """Store one decision on `version` of the item and log it."""
    stamp = now()
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO decisions (item_id, version, gate, action, text, actor, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item_id, version, gate, action, text, actor, stamp),
        )
        append_event(conn, "decision", actor=actor, command=command, item_id=item_id,
                     version=version,
                     details={"gate": gate, "action": action, "text": text, **(details or {})})
    return Decision(int(cursor.lastrowid or 0), item_id, version, gate, action, text, actor,
                    stamp)


def list_decisions(conn: sqlite3.Connection, ref: str) -> list[Decision]:
    """The item's decisions, oldest first."""
    item_id = resolve(conn, ref)
    rows = conn.execute("SELECT * FROM decisions WHERE item_id = ? ORDER BY id", (item_id,))
    return [
        Decision(
            id=int(row["id"]), item_id=str(row["item_id"]), version=int(row["version"]),
            gate=cast(Gate, str(row["gate"])), action=cast(Action, str(row["action"])),
            text=None if row["text"] is None else str(row["text"]),
            actor=cast(Actor, str(row["actor"])), created_at=str(row["created_at"]),
        )
        for row in rows
    ]
