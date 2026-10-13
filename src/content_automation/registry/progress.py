"""Item generation and upload status from jobs and from the pipelines (§14 D-7, D-16).

Every move goes through items.set_status (statuses.py decides; actor system):
- the first generation job starting: generation -> queued -> running;
- the pipeline saying a part is done (package part "done", carousel rendered): -> generated;
- the pipeline saying a part failed, with no job still open: -> failed, or partial when some of
  the version's generation jobs succeeded; a part that never ran a job stays as it is;
- upload, from the item's files (D-16): uploading while any file is in progress, failed if any
  failed, uploaded when all succeeded; the provider is kept, so mock uploads show "(mock)".
"""

import sqlite3
from collections.abc import Mapping

from content_automation.registry.audit import Actor
from content_automation.registry.db import now, transaction
from content_automation.registry.items import Item, get_item, set_status
from content_automation.registry.statuses import Dimension

GENERATION_JOBS = ("image", "still", "clip", "video_scene", "avatar_scene")
REAL_UPLOAD = "drive"  # any other upload provider (mock) never counts as a real upload


def _walk(conn: sqlite3.Connection, item: Item, path: list[str], dimension: Dimension,
          actor: Actor, command: str | None) -> Item:
    current = item.status(dimension)
    for status in path:
        if status == current:
            continue
        item = set_status(conn, item.id, dimension, status, actor=actor, command=command)
        current = status
    return item


def job_started(conn: sqlite3.Connection, item_id: str, *, actor: Actor = "system",
                command: str | None = None) -> Item:
    """A generation job started: generation queued -> running (raises if the idea is not
    approved: B4-1)."""
    with transaction(conn):
        item = get_item(conn, item_id)
        state = item.generation_status
        if state in ("not_started", "failed", "partial"):
            return _walk(conn, item, ["queued", "running"], "generation", actor, command)
        if state == "queued":
            return _walk(conn, item, ["running"], "generation", actor, command)
        return item


def _open_jobs(conn: sqlite3.Connection, item: Item) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE item_id = ? AND version = ? AND status IN "
        f"('queued', 'running') AND job_type IN ({', '.join('?' for _ in GENERATION_JOBS)})",
        (item.id, item.current_version, *GENERATION_JOBS),
    ).fetchone()
    return int(row[0])


def _succeeded_jobs(conn: sqlite3.Connection, item: Item) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE item_id = ? AND version = ? AND status = 'succeeded' "
        f"AND job_type IN ({', '.join('?' for _ in GENERATION_JOBS)})",
        (item.id, item.current_version, *GENERATION_JOBS),
    ).fetchone()
    return int(row[0])


def part_done(conn: sqlite3.Connection, item_id: str, *, actor: Actor = "system",
              command: str | None = None) -> Item:
    """The pipeline finished the item's part: generation -> generated."""
    with transaction(conn):
        item = get_item(conn, item_id)
        state = item.generation_status
        if state == "generated":
            return item
        path = {"not_started": ["queued", "running", "generated"],
                "failed": ["queued", "running", "generated"],
                "partial": ["queued", "running", "generated"],
                "queued": ["running", "generated"],
                "running": ["generated"]}[state]
        return _walk(conn, item, path, "generation", actor, command)


def part_failed(conn: sqlite3.Connection, item_id: str, *, actor: Actor = "system",
                command: str | None = None) -> Item:
    """The pipeline gave up on the part: failed, or partial if some jobs succeeded. Only after a
    job ran (generation running) and none is still open."""
    with transaction(conn):
        item = get_item(conn, item_id)
        if item.generation_status not in ("queued", "running") or _open_jobs(conn, item):
            return item
        target = "partial" if _succeeded_jobs(conn, item) else "failed"
        return _walk(conn, item, ["running", target], "generation", actor, command)


def upload_target(records: Mapping[str, str], files: list[str]) -> str:
    """D-16 from the per-file states ("uploading", "uploaded", "failed", or missing)."""
    states = [records.get(name, "missing") for name in files]
    if not states:
        return "not_uploaded"
    if "uploading" in states:
        return "uploading"
    if "failed" in states:
        return "failed"
    if all(state == "uploaded" for state in states):
        return "uploaded"
    return "uploading" if "uploaded" in states else "not_uploaded"


def set_upload(conn: sqlite3.Connection, item_id: str, target: str, provider: str, *,
               actor: Actor = "system", command: str | None = None) -> Item:
    """Move the item's upload status to `target` (via uploading) and keep the provider."""
    with transaction(conn):
        item = get_item(conn, item_id)
        if target != "not_uploaded" and item.upload_status != target:
            path = {"uploading": ["uploading"], "failed": ["uploading", "failed"],
                    "uploaded": ["uploading", "uploaded"]}[target]
            if item.upload_status in ("uploaded",):
                path = []  # an uploaded item stays uploaded (new files: Phase 7)
            item = _walk(conn, item, path, "upload", actor, command)
        conn.execute("UPDATE items SET upload_provider = ?, updated_at = ? WHERE id = ?",
                     (provider, now(), item_id))
        return get_item(conn, item_id)


def upload_label(item: Item, provider: str | None) -> str:
    """"uploaded (mock)" for a mock upload: it never counts as a real one (D-16)."""
    if item.upload_status == "uploaded" and provider and provider != REAL_UPLOAD:
        return f"uploaded ({provider})"
    return item.upload_status
