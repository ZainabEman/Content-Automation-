"""What the app last wrote to a view file (PRD D10): the calendar CSVs.

Every write of a view stores its SHA-256 and text. A file whose content differs from the last
write was edited by hand: edited_diff returns the unified diff (last written -> now) so the
command can stop and ask instead of overwriting silently.
"""

import difflib
import hashlib
import sqlite3
from pathlib import Path

from content_automation.registry.db import now, transaction


def _key(path: Path) -> str:
    return path.resolve().as_posix()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_written(conn: sqlite3.Connection, path: Path, text: str) -> None:
    with transaction(conn):
        conn.execute(
            "INSERT INTO written_files (path, sha256, content, written_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT (path) DO UPDATE SET sha256 = excluded.sha256, "
            "content = excluded.content, written_at = excluded.written_at",
            (_key(path), sha256_text(text), text, now()),
        )


def last_written(conn: sqlite3.Connection, path: Path) -> str | None:
    """The text the app last wrote to `path` (None: never written since the registry)."""
    row = conn.execute("SELECT content FROM written_files WHERE path = ?",
                       (_key(path),)).fetchone()
    return None if row is None else str(row["content"])


def _read(path: Path) -> str | None:
    try:
        return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    except OSError:
        return None


def edited_diff(conn: sqlite3.Connection, path: Path) -> str | None:
    """The unified diff of hand edits since the last write, or None (unchanged, never written
    since the registry, or deleted: the next write recreates it)."""
    before = last_written(conn, path)
    current = _read(path)
    if before is None or current is None or sha256_text(current) == sha256_text(before):
        return None
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), current.splitlines(keepends=True),
        fromfile=f"{path.name} (last written by ca)", tofile=f"{path.name} (now)",
    ))
