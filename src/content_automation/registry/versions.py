"""Item versions (PRD D6): v1 comes with the item; each revise adds v(n+1); none is ever deleted.

Version status: active = v1 as created (the only version); pending = a newer version waiting
for approval; approved = items.approved_version; superseded = an older version once a newer
one is approved. current_version is the newest version, approved_version the approved one.
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal, cast

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.items import get_item

VersionStatus = Literal["pending", "active", "approved", "superseded"]


@dataclass(frozen=True)
class Version:
    item_id: str
    version: int
    created_at: str
    reason: str
    feedback: str | None
    package_path: str | None
    status: VersionStatus


def _version(row: sqlite3.Row) -> Version:
    return Version(
        item_id=str(row["item_id"]),
        version=int(row["version"]),
        created_at=str(row["created_at"]),
        reason=str(row["reason"]),
        feedback=None if row["feedback"] is None else str(row["feedback"]),
        package_path=None if row["package_path"] is None else str(row["package_path"]),
        status=cast(VersionStatus, str(row["status"])),
    )


def list_versions(conn: sqlite3.Connection, ref: str) -> list[Version]:
    item = get_item(conn, ref)
    rows = conn.execute(
        "SELECT * FROM versions WHERE item_id = ? ORDER BY version", (item.id,)
    )
    return [_version(row) for row in rows]


def get_version(conn: sqlite3.Connection, ref: str, version: int) -> Version:
    item = get_item(conn, ref)
    row = conn.execute(
        "SELECT * FROM versions WHERE item_id = ? AND version = ?", (item.id, version)
    ).fetchone()
    if row is None:
        raise RegistryError(f"{item.id} has no v{version} (newest: v{item.current_version}).")
    return _version(row)


def create_version(
    conn: sqlite3.Connection,
    ref: str,
    *,
    reason: str,
    feedback: str | None = None,
    package_path: str | None = None,
    actor: Actor = "system",
    command: str | None = None,
) -> Version:
    """v(n+1) as pending (same package as the item unless given); it becomes current_version."""
    if not reason.strip():
        raise RegistryError("A new version needs a reason.")
    with transaction(conn):
        item = get_item(conn, ref)
        number = item.current_version + 1
        path = package_path if package_path is not None else item.package_path
        stamp = now()
        conn.execute(
            "INSERT INTO versions (item_id, version, created_at, reason, feedback, "
            "package_path, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
            (item.id, number, stamp, reason.strip(), feedback, path),
        )
        conn.execute(
            "UPDATE items SET current_version = ?, updated_at = ? WHERE id = ?",
            (number, stamp, item.id),
        )
        append_event(conn, "version_created", actor=actor, command=command, item_id=item.id,
                     version=number,
                     details={"reason": reason.strip(), "feedback": feedback,
                              "package_path": path})
        return get_version(conn, item.id, number)


def set_approved_version(
    conn: sqlite3.Connection,
    ref: str,
    version: int,
    *,
    actor: Actor = "system",
    command: str | None = None,
) -> Version:
    """Mark `version` approved; older active/approved versions become superseded."""
    with transaction(conn):
        item = get_item(conn, ref)
        target = get_version(conn, item.id, version)
        if item.approved_version is not None and version < item.approved_version:
            raise RegistryError(
                f"{item.id} v{item.approved_version} is already approved; v{version} is older."
            )
        if target.status == "superseded":
            raise RegistryError(f"{item.id} v{version} is superseded.")
        conn.execute(
            "UPDATE versions SET status = 'superseded' WHERE item_id = ? AND version < ? "
            "AND status IN ('active', 'approved')",
            (item.id, version),
        )
        conn.execute(
            "UPDATE versions SET status = 'approved' WHERE item_id = ? AND version = ?",
            (item.id, version),
        )
        conn.execute(
            "UPDATE items SET approved_version = ?, updated_at = ? WHERE id = ?",
            (version, now(), item.id),
        )
        append_event(conn, "version_approved", actor=actor, command=command, item_id=item.id,
                     version=version, details={"previous": item.approved_version})
        return get_version(conn, item.id, version)
