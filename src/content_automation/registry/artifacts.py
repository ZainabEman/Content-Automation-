"""Scripts, production briefs and copy saved for an item (Phase 6 P6-D3).

Each save is one row: item, version, type (script, brief, copy), the file's path and the check
result. A valid save is logged `artifact_saved`, a refused one `artifact_invalid` (its problems
in the event; no row, no file). Rows are never changed.
"""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.ids import resolve

ArtifactType = Literal["script", "brief", "copy"]
ARTIFACT_TYPES: tuple[ArtifactType, ...] = ("script", "brief", "copy")


@dataclass(frozen=True)
class Artifact:
    id: int
    item_id: str
    version: int
    type: ArtifactType
    path: str
    check: dict[str, Any]
    created_at: str


def _artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(id=int(row["id"]), item_id=str(row["item_id"]), version=int(row["version"]),
                    type=cast(ArtifactType, str(row["type"])), path=str(row["path"]),
                    check=json.loads(row["check_result"]), created_at=str(row["created_at"]))


def add_artifact(conn: sqlite3.Connection, ref: str, version: int, artifact_type: ArtifactType,
                 path: str, check: dict[str, Any], *, actor: Actor = "system",
                 command: str | None = None) -> Artifact:
    if artifact_type not in ARTIFACT_TYPES:
        raise RegistryError(f'Unknown artifact type "{artifact_type}".')
    with transaction(conn):
        item_id = resolve(conn, ref)
        cursor = conn.execute(
            "INSERT INTO artifacts (item_id, version, type, path, check_result, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (item_id, version, artifact_type, path, json.dumps(check, ensure_ascii=False), now()),
        )
        append_event(conn, "artifact_saved", actor=actor, command=command, item_id=item_id,
                     details={"type": artifact_type, "version": version, "path": path,
                              "warnings": check.get("warnings", [])})
        row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return _artifact(row)


def log_invalid(conn: sqlite3.Connection, ref: str, version: int, artifact_type: ArtifactType,
                problems: Sequence[str], *, actor: Actor = "system",
                command: str | None = None) -> None:
    """A refused save: logged with its problems; nothing stored."""
    with transaction(conn):
        item_id = resolve(conn, ref)
        append_event(conn, "artifact_invalid", actor=actor, command=command, item_id=item_id,
                     details={"type": artifact_type, "version": version,
                              "problems": list(problems)})


def list_artifacts(conn: sqlite3.Connection, ref: str,
                   artifact_type: ArtifactType | None = None) -> list[Artifact]:
    item_id = resolve(conn, ref)
    rows = conn.execute(
        "SELECT * FROM artifacts WHERE item_id = ? AND (? IS NULL OR type = ?) ORDER BY id",
        (item_id, artifact_type, artifact_type))
    return [_artifact(row) for row in rows]


def latest_artifact(conn: sqlite3.Connection, ref: str, artifact_type: ArtifactType,
                    version: int | None = None) -> Artifact | None:
    found = [a for a in list_artifacts(conn, ref, artifact_type)
             if version is None or a.version == version]
    return found[-1] if found else None
