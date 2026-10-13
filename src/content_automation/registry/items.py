"""Content items (PRD §5): create, read, aliases and status changes.

create_item allocates the BG ID and writes the item, its v1, one publication row per platform
and an item_created event in one transaction. Statuses change only through set_status, which
asks statuses.transition() first: an illegal move writes nothing.
"""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.ids import allocate_number, format_id, parse_id, resolve
from content_automation.registry.statuses import Dimension, initial, transition

KINDS = ("post", "carousel", "graphic", "youtube", "short", "podcast", "ad")  # PRD D3
STATUS_COLUMNS: dict[Dimension, str] = {
    "idea": "idea_status",
    "generation": "generation_status",
    "review": "review_status",
    "upload": "upload_status",
}


class AliasTaken(RegistryError):
    """The alias already names another item."""


@dataclass(frozen=True)
class Item:
    id: str
    number: int
    kind: str
    title: str
    topic: str
    platforms: tuple[str, ...]
    parent_id: str | None
    planned_date: date | None
    source_refs: tuple[str, ...]
    package_path: str | None
    current_version: int
    approved_version: int | None
    idea_status: str
    generation_status: str
    review_status: str
    upload_status: str
    created_at: str
    updated_at: str
    notes: str | None

    def status(self, dimension: Dimension) -> str:
        """The item-level status of idea, generation, review or upload."""
        if dimension not in STATUS_COLUMNS:
            raise RegistryError("Publication is per platform: use publications().")
        return str(getattr(self, STATUS_COLUMNS[dimension]))


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _item(row: sqlite3.Row) -> Item:
    planned = row["planned_date"]
    approved = row["approved_version"]
    return Item(
        id=str(row["id"]),
        number=int(row["number"]),
        kind=str(row["kind"]),
        title=str(row["title"]),
        topic=str(row["topic"]),
        platforms=tuple(str(p) for p in json.loads(row["platforms"])),
        parent_id=_text(row["parent_id"]),
        planned_date=date.fromisoformat(planned) if planned else None,
        source_refs=tuple(str(s) for s in json.loads(row["source_refs"])),
        package_path=_text(row["package_path"]),
        current_version=int(row["current_version"]),
        approved_version=None if approved is None else int(approved),
        idea_status=str(row["idea_status"]),
        generation_status=str(row["generation_status"]),
        review_status=str(row["review_status"]),
        upload_status=str(row["upload_status"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        notes=_text(row["notes"]),
    )


def _platforms(values: Sequence[str]) -> list[str]:
    names: list[str] = []
    for value in values:
        name = value.strip().lower()
        if not name:
            raise RegistryError("A platform name cannot be empty.")
        if name not in names:
            names.append(name)
    return names


def create_item(
    conn: sqlite3.Connection,
    *,
    kind: str,
    title: str,
    topic: str,
    platforms: Sequence[str] = (),
    parent_id: str | None = None,
    planned_date: date | None = None,
    source_refs: Sequence[str] = (),
    package_path: str | None = None,
    notes: str | None = None,
    actor: Actor = "system",
    command: str | None = None,
) -> Item:
    """A new item with the next BG ID, every status at its start and v1."""
    if kind not in KINDS:
        raise RegistryError(f'Unknown kind "{kind}" ({", ".join(KINDS)}).')
    if not title.strip():
        raise RegistryError("An item needs a title.")
    names = _platforms(platforms)
    with transaction(conn):
        parent = resolve(conn, parent_id) if parent_id is not None else None
        number = allocate_number(conn)
        item_id = format_id(number)
        stamp = now()
        conn.execute(
            "INSERT INTO items (id, number, kind, title, topic, platforms, parent_id, "
            "planned_date, source_refs, package_path, current_version, approved_version, "
            "idea_status, generation_status, review_status, upload_status, created_at, "
            "updated_at, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, number, kind, title.strip(), topic.strip(), json.dumps(names), parent,
             planned_date.isoformat() if planned_date else None,
             json.dumps(list(source_refs), ensure_ascii=False), package_path,
             initial("idea"), initial("generation"), initial("review"), initial("upload"),
             stamp, stamp, notes),
        )
        conn.execute(
            "INSERT INTO versions (item_id, version, created_at, reason, feedback, "
            "package_path, status) VALUES (?, 1, ?, 'created', NULL, ?, 'active')",
            (item_id, stamp, package_path),
        )
        conn.executemany(
            "INSERT INTO publications (item_id, platform, status, updated_at) "
            "VALUES (?, ?, ?, ?)",
            [(item_id, name, initial("publication"), stamp) for name in names],
        )
        append_event(
            conn, "item_created", actor=actor, command=command, item_id=item_id, version=1,
            details={"kind": kind, "title": title.strip(), "platforms": names,
                     "parent_id": parent, "package_path": package_path,
                     "planned_date": planned_date.isoformat() if planned_date else None},
        )
        return get_item(conn, item_id)


def get_item(conn: sqlite3.Connection, ref: str) -> Item:
    """The item a BG ID or alias names (UnknownItem if none)."""
    item_id = resolve(conn, ref)
    row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return _item(row)


def publications(conn: sqlite3.Connection, ref: str) -> dict[str, str]:
    """Publication status per platform."""
    item_id = resolve(conn, ref)
    rows = conn.execute(
        "SELECT platform, status FROM publications WHERE item_id = ? ORDER BY platform",
        (item_id,),
    )
    return {str(row["platform"]): str(row["status"]) for row in rows}


def aliases(conn: sqlite3.Connection, ref: str) -> list[str]:
    item_id = resolve(conn, ref)
    rows = conn.execute(
        "SELECT alias FROM aliases WHERE item_id = ? ORDER BY rowid", (item_id,)
    )
    return [str(row["alias"]) for row in rows]


def add_alias(
    conn: sqlite3.Connection, ref: str, alias: str, *, actor: Actor = "system",
    command: str | None = None,
) -> None:
    """Let `alias` (a Content ID or package folder name) name the item; no-op if it already does."""
    name = alias.strip()
    if not name:
        raise RegistryError("An alias cannot be empty.")
    if parse_id(name) is not None:
        raise RegistryError(f'"{name}" looks like a BG ID, so it cannot be an alias.')
    with transaction(conn):
        item_id = resolve(conn, ref)
        row = conn.execute("SELECT item_id FROM aliases WHERE alias = ?", (name,)).fetchone()
        if row is not None:
            if str(row["item_id"]) == item_id:
                return
            raise AliasTaken(f'"{name}" already names {row["item_id"]}.')
        conn.execute(
            "INSERT INTO aliases (alias, item_id, created_at) VALUES (?, ?, ?)",
            (name, item_id, now()),
        )
        append_event(conn, "alias_added", actor=actor, command=command, item_id=item_id,
                     details={"alias": name})


def set_status(
    conn: sqlite3.Connection,
    ref: str,
    dimension: Dimension,
    target: str,
    *,
    platform: str | None = None,
    new_version: bool = False,
    actor: Actor = "system",
    command: str | None = None,
) -> Item:
    """Move one status (publication: per `platform`) if statuses.py allows it, and log it."""
    with transaction(conn):
        item = get_item(conn, ref)
        if dimension == "publication":
            if platform is None:
                raise RegistryError("A publication status needs the platform.")
            name = platform.strip().lower()
            current = publications(conn, item.id).get(name)
            if current is None:
                raise RegistryError(
                    f"{item.id} is not planned for {name} "
                    f"({', '.join(item.platforms) or 'no platforms'})."
                )
        else:
            if platform is not None:
                raise RegistryError(f"Only publication is per platform, not {dimension}.")
            name = None
            current = item.status(dimension)
        transition(dimension, current, target, generation=item.generation_status,
                   new_version=new_version)
        stamp = now()
        if name is not None:
            conn.execute(
                "UPDATE publications SET status = ?, updated_at = ? "
                "WHERE item_id = ? AND platform = ?",
                (target, stamp, item.id, name),
            )
            conn.execute("UPDATE items SET updated_at = ? WHERE id = ?", (stamp, item.id))
        else:
            conn.execute(
                f"UPDATE items SET {STATUS_COLUMNS[dimension]} = ?, updated_at = ? WHERE id = ?",
                (target, stamp, item.id),
            )
        details: dict[str, Any] = {"dimension": dimension, "from": current, "to": target}
        if name is not None:
            details["platform"] = name
        append_event(conn, "status_changed", actor=actor, command=command, item_id=item.id,
                     version=item.current_version, details=details)
        return get_item(conn, item.id)
