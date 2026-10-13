"""The audit log (PRD D9): append-only events, written and read here and nowhere else.

There is no function to change or delete an event, and database triggers refuse it too. The
command text and the details pass through redact.py before they are stored.
"""

import json
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.redact import redact_data, redact_text, secret_values

Actor = Literal["user", "system"]
ACTORS: tuple[Actor, ...] = ("user", "system")
EVENT_TYPES = frozenset({
    "command_run", "item_created", "item_updated", "alias_added", "status_changed", "decision",
    "version_created", "version_approved",
    "authorization_created", "authorization_exceeded", "authorization_closed",
    "job_queued", "job_started", "job_succeeded", "job_failed", "job_reused", "job_cancelled",
    "job_rejected",
    "upload_succeeded", "upload_failed", "tracker_synced", "conflict_found", "migration_run",
})


@dataclass(frozen=True)
class Event:
    id: int
    created_at: str
    actor: Actor
    command: str | None
    item_id: str | None
    version: int | None
    type: str
    details: dict[str, Any]


def append_event(
    conn: sqlite3.Connection,
    event_type: str,
    *,
    actor: Actor = "system",
    command: str | None = None,
    item_id: str | None = None,
    version: int | None = None,
    details: Mapping[str, Any] | None = None,
) -> Event:
    """Add one event (redacted) and return it as stored."""
    if event_type not in EVENT_TYPES:
        raise RegistryError(f'Unknown event type "{event_type}".')
    if actor not in ACTORS:
        raise RegistryError(f'The actor must be user or system, not "{actor}".')
    secrets = secret_values()
    clean = cast(dict[str, Any], redact_data(dict(details or {}), secrets))
    text = redact_text(command, secrets) if command is not None else None
    created = now()
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO events (created_at, actor, command, item_id, version, type, details) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (created, actor, text, item_id, version, event_type,
             json.dumps(clean, ensure_ascii=False, sort_keys=True)),
        )
    return Event(int(cursor.lastrowid or 0), created, actor, text, item_id, version, event_type,
                 clean)


def _when(value: str | datetime) -> str:
    if isinstance(value, str):
        return value
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _event(row: sqlite3.Row) -> Event:
    version = row["version"]
    return Event(
        id=int(row["id"]),
        created_at=str(row["created_at"]),
        actor=cast(Actor, str(row["actor"])),
        command=None if row["command"] is None else str(row["command"]),
        item_id=None if row["item_id"] is None else str(row["item_id"]),
        version=None if version is None else int(version),
        type=str(row["type"]),
        details=cast(dict[str, Any], json.loads(row["details"])),
    )


def list_events(
    conn: sqlite3.Connection,
    *,
    item_id: str | None = None,
    types: Iterable[str] = (),
    since: str | datetime | None = None,
    until: str | datetime | None = None,
    limit: int | None = None,
    last: int | None = None,
) -> list[Event]:
    """Events oldest first; `since`/`until` take a datetime or ISO text (a date is a day start);
    `limit` keeps the oldest matches, `last` the newest ones."""
    clauses: list[str] = []
    params: list[Any] = []
    if item_id is not None:
        clauses.append("item_id = ?")
        params.append(item_id)
    wanted = list(types)
    if wanted:
        clauses.append(f"type IN ({', '.join('?' for _ in wanted)})")
        params += wanted
    if since is not None:
        clauses.append("created_at >= ?")
        params.append(_when(since))
    if until is not None:
        clauses.append("created_at < ?")
        params.append(_when(until))
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "DESC" if last is not None else ""
    sql = f"SELECT * FROM events{where} ORDER BY id {order}"
    if limit is not None or last is not None:
        sql += " LIMIT ?"
        params.append(last if last is not None else limit)
    events = [_event(row) for row in conn.execute(sql, params)]
    return events[::-1] if last is not None else events
