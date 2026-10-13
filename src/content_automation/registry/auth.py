"""Authorizations (PRD D8, §14 D-4): the spend an "ok" approved, never unlimited.

`--authorize <dryrun_id>` creates one authorization per paid provider/unit of the dry run
(grouped by its dryrun_id): the items and job types in scope, the max with retries, what was
spent and a status (open, closed, exceeded). A paid job starts only if spent + its estimate fits
under the max. Free providers (mock, local, Drive) need none. An old carousel approved before the
registry gets a "legacy" authorization with the max its carousel.json recorded.
"""

import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, cast

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.dryruns import DryRun

AuthStatus = Literal["open", "closed", "exceeded"]


@dataclass(frozen=True)
class Authorization:
    id: int
    dryrun_id: str | None
    item_ids: tuple[str, ...]
    job_types: tuple[str, ...]
    provider: str
    unit: str
    max_amount: float
    spent: float
    status: AuthStatus
    actor: str
    command: str | None
    created_at: str
    updated_at: str
    closed_at: str | None
    note: str | None

    @property
    def remaining(self) -> float:
        return round(self.max_amount - self.spent, 6)

    def line(self) -> str:
        scope = ", ".join(self.item_ids) or "direct run"
        return (f"#{self.id} {self.provider} {self.unit}: spent {self.spent:g} of max "
                f"{self.max_amount:g} ({self.status}); {scope}; dry run {self.dryrun_id or '—'}")


def _auth(row: sqlite3.Row) -> Authorization:
    return Authorization(
        id=int(row["id"]),
        dryrun_id=None if row["dryrun_id"] is None else str(row["dryrun_id"]),
        item_ids=tuple(str(i) for i in json.loads(row["item_ids"])),
        job_types=tuple(str(t) for t in json.loads(row["job_types"])),
        provider=str(row["provider"]),
        unit=str(row["unit"]),
        max_amount=float(row["max_amount"]),
        spent=float(row["spent"]),
        status=cast(AuthStatus, str(row["status"])),
        actor=str(row["actor"]),
        command=None if row["command"] is None else str(row["command"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        closed_at=None if row["closed_at"] is None else str(row["closed_at"]),
        note=None if row["note"] is None else str(row["note"]),
    )


def get_authorization(conn: sqlite3.Connection, auth_id: int) -> Authorization:
    row = conn.execute("SELECT * FROM authorizations WHERE id = ?", (auth_id,)).fetchone()
    if row is None:
        raise RegistryError(f"Authorization #{auth_id} does not exist.")
    return _auth(row)


def list_authorizations(conn: sqlite3.Connection, *, open_only: bool = False
                        ) -> list[Authorization]:
    where = " WHERE status = 'open'" if open_only else ""
    return [_auth(row) for row in conn.execute(f"SELECT * FROM authorizations{where} ORDER BY id")]


def _insert(conn: sqlite3.Connection, *, dryrun_id: str | None, items: Sequence[str],
            job_types: Sequence[str], provider: str, unit: str, max_amount: float, actor: Actor,
            command: str | None, note: str | None) -> Authorization:
    if max_amount < 0:
        raise RegistryError("An authorization max cannot be negative.")
    stamp = now()
    cursor = conn.execute(
        "INSERT INTO authorizations (item_ids, job_types, provider, unit, max_amount, spent, "
        "status, actor, command, created_at, updated_at, dryrun_id, note) "
        "VALUES (?, ?, ?, ?, ?, 0, 'open', ?, ?, ?, ?, ?, ?)",
        (json.dumps(sorted(set(items))), json.dumps(sorted(set(job_types))), provider, unit,
         max_amount, actor, command, stamp, stamp, dryrun_id, note),
    )
    auth = get_authorization(conn, int(cursor.lastrowid or 0))
    append_event(conn, "authorization_created", actor=actor, command=command,
                 details={"authorization_id": auth.id, "dryrun": dryrun_id, "provider": provider,
                          "unit": unit, "max": max_amount, "items": list(auth.item_ids),
                          "job_types": list(auth.job_types), "note": note})
    return auth


def create_from_dry_run(
    conn: sqlite3.Connection, dry_run: DryRun, *, free: Iterable[str], actor: Actor = "user",
    command: str | None = None,
) -> list[Authorization]:
    """One authorization per paid provider/unit of the dry run (after the user's "ok")."""
    skip = set(free)
    groups: dict[tuple[str, str], list[int]] = {}
    for index, line in enumerate(dry_run.lines):
        if line.provider not in skip:
            groups.setdefault((line.provider, line.unit), []).append(index)
    created: list[Authorization] = []
    with transaction(conn):
        for (provider, unit), indexes in sorted(groups.items()):
            lines = [dry_run.lines[i] for i in indexes]
            created.append(_insert(
                conn, dryrun_id=dry_run.id,
                items=[line.item for line in lines if line.item],
                job_types=[line.job_type for line in lines], provider=provider, unit=unit,
                max_amount=round(sum(line.max for line in lines), 6), actor=actor,
                command=command, note=None,
            ))
    return created


def legacy_authorization(
    conn: sqlite3.Connection, item_id: str, provider: str, unit: str, max_amount: float,
    note: str, *, command: str | None = None,
) -> Authorization:
    """The max an older approval recorded (e.g. carousel.json), so its work can resume."""
    with transaction(conn):
        return _insert(conn, dryrun_id=None, items=[item_id], job_types=["still", "clip"],
                       provider=provider, unit=unit, max_amount=max_amount, actor="system",
                       command=command, note=note)


def find_authorization(
    conn: sqlite3.Connection, *, item_id: str | None, provider: str, unit: str,
    explicit: Sequence[int] = (), estimate: float = 0.0,
) -> Authorization | None:
    """An open authorization for this provider/unit: one named by the command first, then one
    whose scope holds the item; the one with room for `estimate` if there are several."""
    candidates = [get_authorization(conn, auth_id) for auth_id in explicit]
    if item_id is not None:
        candidates += [auth for auth in list_authorizations(conn, open_only=True)
                       if item_id in auth.item_ids]
    usable = [auth for auth in candidates
              if auth.status == "open" and (auth.provider, auth.unit) == (provider, unit)]
    roomy = [auth for auth in usable if auth.remaining >= estimate]
    best = roomy or usable
    return best[0] if best else None


def charge(conn: sqlite3.Connection, auth_id: int, amount: float, *, job_id: int,
           command: str | None = None) -> Authorization:
    """Add `amount` to spent; past the max the authorization becomes exceeded (logged)."""
    with transaction(conn):
        auth = get_authorization(conn, auth_id)
        spent = round(auth.spent + amount, 6)
        status: AuthStatus = auth.status
        if spent > auth.max_amount + 1e-9 and status == "open":
            status = "exceeded"
        conn.execute("UPDATE authorizations SET spent = ?, status = ?, updated_at = ? "
                     "WHERE id = ?", (spent, status, now(), auth_id))
        if status == "exceeded" and auth.status != "exceeded":
            append_event(conn, "authorization_exceeded", command=command,
                         details={"authorization_id": auth_id, "job": job_id, "spent": spent,
                                  "max": auth.max_amount, "unit": auth.unit})
        return get_authorization(conn, auth_id)


def close_authorization(conn: sqlite3.Connection, auth_id: int, reason: str, *,
                        actor: Actor = "system", command: str | None = None) -> Authorization:
    with transaction(conn):
        auth = get_authorization(conn, auth_id)
        if auth.status == "closed":
            return auth
        stamp = now()
        conn.execute("UPDATE authorizations SET status = 'closed', closed_at = ?, updated_at = ? "
                     "WHERE id = ?", (stamp, stamp, auth_id))
        append_event(conn, "authorization_closed", actor=actor, command=command,
                     details={"authorization_id": auth_id, "reason": reason, "spent": auth.spent,
                              "max": auth.max_amount, "unit": auth.unit})
        return get_authorization(conn, auth_id)
