"""The registry inside a pipeline run (§14 D-5, D-6, D-7, D-16).

A `ca` command that builds, records or uploads opens one Scope (activate); the pipelines find
it with current() and report through the functions below: open, start and close jobs, say a
part is done or failed, and set the upload status. Without a scope (library use, older tests)
every function here does nothing and returns None, so the pipelines run as before; a paid image
call is then refused by the image job itself.

The item a job belongs to is the scope's current item (for_item), or an explicit one. Items are
found by their package folder and the package part of their deliverable (part_of, from
config/deliverables.json, given by the command).
"""

import secrets
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content_automation.registry.audit import Actor
from content_automation.registry.auth import find_authorization, legacy_authorization
from content_automation.registry.items import Item, get_item
from content_automation.registry.jobs import (
    JobConfig,
    JobRecord,
    Opened,
    fail_job,
    get_job,
    open_job,
    reject_job,
    start_job,
    succeed_job,
)
from content_automation.registry.progress import part_done, part_failed, set_upload


@dataclass
class Scope:
    conn: sqlite3.Connection
    config: JobConfig
    command: str | None = None
    actor: Actor = "user"
    part_of: dict[str, str] = field(default_factory=dict)  # deliverable -> package part key
    authorizations: list[int] = field(default_factory=list)  # created by this command
    run_id: str = field(default_factory=lambda: secrets.token_hex(4))
    item: str | None = None  # the item whose jobs are being made now (for_item)
    tracker_columns: dict[str, str] = field(default_factory=dict)  # key -> tracker column


_SCOPE: ContextVar[Scope | None] = ContextVar("registry_scope", default=None)


@contextmanager
def activate(scope: Scope) -> Iterator[Scope]:
    token = _SCOPE.set(scope)
    try:
        yield scope
    finally:
        _SCOPE.reset(token)


def current() -> Scope | None:
    return _SCOPE.get()


@contextmanager
def for_item(item_id: str | None) -> Iterator[None]:
    """Jobs opened inside belong to `item_id` (no-op without a scope)."""
    scope = current()
    if scope is None:
        yield
        return
    previous, scope.item = scope.item, item_id
    try:
        yield
    finally:
        scope.item = previous


def _same(path: str | None, folder: Path) -> bool:
    return path is not None and Path(path).resolve() == folder.resolve()


def package_items(folder: Path) -> dict[str, str]:
    """part key (post, ad, carousel, reel) -> BG ID of the registered items of a package."""
    scope = current()
    if scope is None:
        return {}
    found: dict[str, str] = {}
    for row in scope.conn.execute(
        "SELECT id, package_path, deliverable FROM items WHERE package_path IS NOT NULL "
        "ORDER BY number"
    ):
        part = scope.part_of.get(str(row["deliverable"] or ""))
        if part and part not in found and _same(str(row["package_path"]), folder):
            found[part] = str(row["id"])
    return found


def item_for(folder: Path, part: str) -> str | None:
    return package_items(folder).get(part)


def job(job_id: int) -> JobRecord | None:
    scope = current()
    return get_job(scope.conn, job_id) if scope is not None else None


def get(item_id: str) -> Item | None:
    scope = current()
    return get_item(scope.conn, item_id) if scope is not None else None


def open_scoped_job(
    job_type: str, provider: str, inputs: Mapping[str, Any], *, estimate: float | None = None,
    unit: str | None = None, item_id: str | None = None, direct: bool = False,
) -> Opened | None:
    """Open (or reuse) a job for `item_id` or the current item. direct: a job of a direct run
    (`ca image`, `ca video`), keyed by this command's run so a new "ok" makes new output."""
    scope = current()
    if scope is None:
        return None
    item = item_id if item_id is not None else scope.item
    if item is None and not direct:
        return None
    keyed = dict(inputs) | ({"run": scope.run_id} if item is None else {})
    return open_job(scope.conn, item_id=item, job_type=job_type, provider=provider,
                    inputs=keyed, config=scope.config, estimate=estimate, unit=unit,
                    explicit_auths=scope.authorizations, command=scope.command)


def start(job_id: int) -> JobRecord | None:
    scope = current()
    if scope is None:
        return None
    return start_job(scope.conn, job_id, config=scope.config,
                     explicit_auths=scope.authorizations, command=scope.command)


def succeed(job_id: int, *, actual: float | None = None, result_path: str | None = None
            ) -> JobRecord | None:
    scope = current()
    if scope is None:
        return None
    return succeed_job(scope.conn, job_id, actual=actual, result_path=result_path,
                       command=scope.command)


def fail(job_id: int, error: str, *, actual: float | None = None) -> JobRecord | None:
    scope = current()
    if scope is None:
        return None
    return fail_job(scope.conn, job_id, error, actual=actual, command=scope.command)


def reject(job_id: int, reason: str) -> JobRecord | None:
    scope = current()
    if scope is None:
        return None
    return reject_job(scope.conn, job_id, reason, command=scope.command)


def report_part(item_id: str | None, state: str) -> None:
    """The pipeline's part status: "done" -> generated, "failed" -> failed/partial."""
    scope = current()
    if scope is None or item_id is None:
        return
    if state == "done":
        part_done(scope.conn, item_id, command=scope.command)
    elif state == "failed":
        part_failed(scope.conn, item_id, command=scope.command)


def report_upload(item_id: str | None, target: str, provider: str) -> None:
    scope = current()
    if scope is None or item_id is None:
        return
    set_upload(scope.conn, item_id, target, provider, command=scope.command)


def authorized_max(item_id: str | None, provider: str, unit: str) -> float | None:
    """The max of the open authorization for the item (the carousel's max, D-4)."""
    scope = current()
    if scope is None or item_id is None:
        return None
    auth = find_authorization(scope.conn, item_id=item_id, provider=provider, unit=unit,
                              explicit=scope.authorizations)
    return auth.max_amount if auth is not None else None


def ensure_legacy(item_id: str | None, provider: str, unit: str, max_amount: float,
                  note: str) -> None:
    """An approval from before the registry (carousel.json max) becomes its authorization."""
    scope = current()
    if scope is None or item_id is None:
        return
    if find_authorization(scope.conn, item_id=item_id, provider=provider, unit=unit) is None:
        legacy_authorization(scope.conn, item_id, provider, unit, max_amount, note,
                             command=scope.command)
