"""Registering what the pipelines make as items (§14 D-1, D-2, D-3; PRD §9 status mapping).

- A package: one item per deliverable (D-1), kind from config/deliverables.json (D-2), the
  package folder shared, aliases "<folder>#<deliverable>", the folder name when the package has
  one deliverable, and its Content ID. `ca content start` / `ca content set` register them when
  the deliverables are named (D-3); the user's own make-content request approves the idea, with
  that request stored on the decision (B4-10).
- A calendar row: one item with the row's Content ID as alias; its CSV status is carried over
  (Proposed -> proposed; Approved -> approved; Rejected -> rejected; Generated -> approved and
  generated), each as a logged decision that says it came from the calendar.
The callers pass kinds and platforms (the registry does not read content configs).
"""

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from content_automation.registry.approvals import approve, reject
from content_automation.registry.audit import Actor
from content_automation.registry.db import RegistryError, transaction
from content_automation.registry.ids import parse_id
from content_automation.registry.items import (
    Item,
    add_alias,
    create_item,
    get_item,
    move_alias,
    set_package_path,
)
from content_automation.registry.progress import part_done

ALIAS_SEPARATOR = "#"


def _alias_free(conn: sqlite3.Connection, alias: str) -> bool:
    return conn.execute("SELECT 1 FROM aliases WHERE alias = ?", (alias,)).fetchone() is None


def _try_alias(conn: sqlite3.Connection, item_id: str, alias: str, actor: Actor,
               command: str | None) -> None:
    if alias and parse_id(alias) is None and _alias_free(conn, alias):
        add_alias(conn, item_id, alias, actor=actor, command=command)


def by_alias(conn: sqlite3.Connection, alias: str) -> Item | None:
    row = conn.execute("SELECT item_id FROM aliases WHERE alias = ?", (alias,)).fetchone()
    return get_item(conn, str(row["item_id"])) if row else None


def package_item(conn: sqlite3.Connection, folder: Path, deliverable: str) -> Item | None:
    """The registered item of this package and deliverable, if any."""
    target = folder.resolve()
    for row in conn.execute("SELECT id, package_path FROM items WHERE deliverable = ? AND "
                            "package_path IS NOT NULL ORDER BY number", (deliverable,)):
        if Path(str(row["package_path"])).resolve() == target:
            return get_item(conn, str(row["id"]))
    return None


def register_package(
    conn: sqlite3.Connection,
    folder: Path,
    *,
    topic: str,
    deliverables: Sequence[str],
    kinds: Mapping[str, str],
    platforms: Mapping[str, str | None],
    content_id: str | None = None,
    source_refs: Sequence[str] = (),
    request: str | None = None,
    actor: Actor = "user",
    command: str | None = None,
) -> list[tuple[Item, bool]]:
    """The package's items, created where missing (item, created). With `request` (the user's
    own make-content words) a new item's idea is approved by that request."""
    results: list[tuple[Item, bool]] = []
    path = folder.as_posix()
    with transaction(conn):
        for deliverable in deliverables:
            existing = package_item(conn, folder, deliverable)
            if existing is not None:
                results.append((existing, False))
                continue
            if deliverable not in kinds:
                raise RegistryError(f'No kind for deliverable "{deliverable}" in '
                                    "config/deliverables.json.")
            platform = platforms.get(deliverable)
            item = create_item(conn, kind=kinds[deliverable], title=topic, topic=topic,
                               platforms=[platform] if platform else [], source_refs=source_refs,
                               package_path=path, deliverable=deliverable, actor=actor,
                               command=command)
            _try_alias(conn, item.id, f"{folder.name}{ALIAS_SEPARATOR}{deliverable}", actor,
                       command)
            if len(deliverables) == 1:
                _try_alias(conn, item.id, folder.name, actor, command)
            if content_id:
                _try_alias(conn, item.id, content_id, actor, command)
            if request:
                approve(conn, item.id, gate="idea", actor=actor, command=command,
                        note=f"make-content request: {request}")
            results.append((get_item(conn, item.id), True))
    return results


def register_row(
    conn: sqlite3.Connection,
    row: Mapping[str, str],
    label: str,
    *,
    kind: str,
    platform: str | None,
    command: str | None = None,
    replace: bool = False,
) -> tuple[Item, bool]:
    """The item of a calendar row (created from the row if missing), linked to its package.
    replace (calendar new --replace, D-11): an item that already has this Content ID is
    rejected ("replaced"), a new item is made and the Content ID moves to it; the old item
    keeps its history."""
    content_id = row.get("Content ID") or f"{label}-{int(row['Row']):02d}"
    with transaction(conn):
        found = by_alias(conn, content_id)
        if found is not None and replace:
            if found.idea_status in ("proposed", "approved"):
                reject(conn, found.id, "replaced", gate="idea", actor="user", command=command)
            found = None
        created = found is None
        if found is None:
            planned = row.get("Planned date") or ""
            source = row.get("Research source") or ""
            found = create_item(
                conn, kind=kind, title=row["Topic"], topic=row["Topic"],
                platforms=[platform] if platform else [],
                planned_date=date.fromisoformat(planned) if planned else None,
                source_refs=[source] if source else [], package_path=row.get("Package") or None,
                deliverable=row.get("Content type") or None, command=command,
            )
            move_alias(conn, content_id, found.id, command=command)
            _carry_status(conn, found, row.get("Status", "Proposed"), label, command)
        package = row.get("Package") or ""
        if package and found.package_path != package:
            set_package_path(conn, found.id, package, command=command)
        if package and row.get("Content type"):
            _try_alias(conn, found.id,
                       f"{Path(package).name}{ALIAS_SEPARATOR}{row['Content type']}", "system",
                       command)
        return get_item(conn, found.id), created


def _carry_status(conn: sqlite3.Connection, item: Item, status: str, label: str,
                  command: str | None) -> None:
    note = f"calendar {label}: row was {status} before the registry"
    if status in ("Approved", "Generated", "In progress", "Failed"):
        approve(conn, item.id, gate="idea", actor="migration", command=command, note=note)
    elif status == "Rejected":
        reject(conn, item.id, note, gate="idea", actor="migration", command=command)
    if status == "Generated":
        part_done(conn, item.id, command=command)


def plan_item(
    conn: sqlite3.Connection, row: Mapping[str, str], label: str, *, kind: str,
    platform: str | None, parent_id: str, idea_id: str, command: str | None = None,
) -> Item:
    """A calendar row planned from an approved idea (Phase 5 P5-D12): a child of `parent_id`
    (the idea, or the video of a short) whose idea gate starts approved, inherited and logged
    with the idea's ID. Refused when the idea is not approved."""
    with transaction(conn):
        idea = get_item(conn, idea_id)
        if idea.kind != "idea" or idea.idea_status != "approved":
            raise RegistryError(f"{idea.id} is not an approved idea: approve it first.")
        content_id = row.get("Content ID") or f"{label}-{int(row['Row']):02d}"
        planned = row.get("Planned date") or ""
        item = create_item(
            conn, kind=kind, title=row["Topic"], topic=row["Topic"],
            platforms=[platform] if platform else [], parent_id=parent_id,
            planned_date=date.fromisoformat(planned) if planned else None,
            source_refs=[f"idea:{idea.id}"], deliverable=row.get("Content type") or None,
            command=command,
        )
        move_alias(conn, content_id, item.id, command=command)
        approve(conn, item.id, gate="idea", actor="system", command=command,
                note=f"inherited from approved idea {idea.id} (parent {parent_id})")
        return get_item(conn, item.id)
