"""Item versions (PRD D6, §14 D-19, D-20): v1 comes with the item; each revise adds v(n+1).

Version status: active = the version being worked on (v1 as created; a newer version once its
generation starts); pending = a newer version waiting (for idea approval, or for generation
after a review revise); approved = items.approved_version; superseded = an older version once
a newer one is approved. current_version is the newest version, approved_version the approved
one. No version is ever deleted; until Phase 7 a new version shares v1's package folder and
stores the feedback.

Revise (D-19):
- idea gate (idea proposed): idea -> revision_requested and v(n+1) pending. With a new title
  (the Codex skill rewrites the topic from the feedback) the idea goes back to proposed on the
  new version at once; without one it waits for resubmit(title).
- review gate (generation generated, review not_reviewed or approved): review ->
  changes_requested and v(n+1) pending. start_new_version() starts its generation: generation
  -> queued and review changes_requested -> not_reviewed. Review rejected is final.
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal, cast

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.decisions import Gate, record_decision
from content_automation.registry.items import Item, get_item, set_status, set_title

VersionStatus = Literal["pending", "active", "approved", "superseded"]
GATES: tuple[Gate, ...] = ("idea", "review")  # D5: the idea gate first
REVIEW_REVISABLE = ("not_reviewed", "approved")  # review statuses a revise may change
RESTART_FROM = ("generated", "failed", "partial")  # generation a newer version may restart


@dataclass(frozen=True)
class Version:
    item_id: str
    version: int
    created_at: str
    reason: str
    feedback: str | None
    package_path: str | None
    status: VersionStatus


@dataclass(frozen=True)
class Revision:
    gate: Gate
    item: Item  # after the revise
    version: Version  # the new version


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


def gate_open_for_revise(item: Item, gate: Gate) -> bool:
    if gate == "idea":
        return item.idea_status == "proposed"
    return item.generation_status == "generated" and item.review_status in REVIEW_REVISABLE


def revise_gate(item: Item) -> Gate | None:
    """The gate a revise acts on, or None if neither is open."""
    return next((gate for gate in GATES if gate_open_for_revise(item, gate)), None)


def _not_open(item: Item, gate: Gate | None) -> str:
    where = f"the {gate} gate is not open" if gate else "there is nothing to revise"
    state = (f"idea is {item.idea_status}, generation is {item.generation_status}, review is "
             f"{item.review_status}")
    if item.idea_status == "revision_requested":
        hint = f' It waits for: ca item resubmit {item.id} --title "<new topic>".'
    elif item.review_status == "rejected":
        hint = " Review rejected is final."
    elif item.review_status == "changes_requested":
        hint = (f" Changes are already requested; v{item.current_version} waits for "
                "generation.")
    elif item.generation_status in ("queued", "running"):
        hint = " Generation is in progress; wait for it to finish."
    else:
        hint = ""
    return f"{item.id}: {where} ({state}).{hint}"


def revise(
    conn: sqlite3.Connection,
    ref: str,
    feedback: str,
    *,
    title: str | None = None,
    gate: Gate | None = None,
    actor: Actor = "user",
    command: str | None = None,
) -> Revision:
    """Store the feedback as a revise decision and create v(n+1) (see the module text)."""
    text = feedback.strip()
    if not text:
        raise RegistryError("A revise needs feedback: what should change?")
    new_title = title.strip() if title is not None else None
    if new_title == "":
        raise RegistryError("The new title cannot be empty.")
    with transaction(conn):
        item = get_item(conn, ref)
        chosen = gate or revise_gate(item)
        if chosen is None or not gate_open_for_revise(item, chosen):
            raise RegistryError(_not_open(item, chosen))
        if chosen == "review" and new_title is not None:
            raise RegistryError(
                "A new title is for the idea gate; a review revise keeps the topic."
            )
        revised = item.current_version
        if chosen == "idea":
            set_status(conn, item.id, "idea", "revision_requested", actor=actor, command=command)
        else:
            set_status(conn, item.id, "review", "changes_requested", actor=actor, command=command)
        version = create_version(conn, item.id, reason=f"revise ({chosen} gate)", feedback=text,
                                 actor=actor, command=command)
        record_decision(conn, item.id, revised, chosen, "revise", text, actor=actor,
                        command=command,
                        details={"new_version": version.version, "title": new_title})
        if chosen == "idea" and new_title is not None:
            set_title(conn, item.id, new_title, actor=actor, command=command)
            set_status(conn, item.id, "idea", "proposed", actor=actor, command=command)
        return Revision(chosen, get_item(conn, item.id), version)


def resubmit(
    conn: sqlite3.Connection, ref: str, title: str, *, actor: Actor = "user",
    command: str | None = None,
) -> Item:
    """After a revise without a new title: set the new title and propose the idea again."""
    with transaction(conn):
        item = get_item(conn, ref)
        if item.idea_status != "revision_requested":
            raise RegistryError(
                f"{item.id}: idea is {item.idea_status}; resubmit follows a revise without a "
                "new title (idea revision_requested)."
            )
        set_title(conn, item.id, title, actor=actor, command=command)
        return set_status(conn, item.id, "idea", "proposed", actor=actor, command=command)


def start_new_version(
    conn: sqlite3.Connection, ref: str, *, actor: Actor = "system", command: str | None = None
) -> Item:
    """Start generating the pending newer version: generation -> queued, review
    changes_requested -> not_reviewed, the version becomes active (Phase 7 regeneration)."""
    with transaction(conn):
        item = get_item(conn, ref)
        current = get_version(conn, item.id, item.current_version)
        if item.current_version == 1 or current.status != "pending":
            raise RegistryError(
                f"{item.id} has no newer version waiting (v{current.version} is "
                f"{current.status}): revise it first."
            )
        if item.idea_status != "approved":
            raise RegistryError(f"{item.id}: idea is {item.idea_status}; approve it first.")
        if item.review_status == "rejected":
            raise RegistryError(f"{item.id}: review rejected is final.")
        if item.generation_status not in RESTART_FROM:
            raise RegistryError(
                f"{item.id}: generation is {item.generation_status}; a newer version restarts "
                "from generated, failed or partial."
            )
        set_status(conn, item.id, "generation", "queued", new_version=True, actor=actor,
                   command=command)
        if item.review_status == "changes_requested":
            set_status(conn, item.id, "review", "not_reviewed", new_version=True, actor=actor,
                       command=command)
        conn.execute(
            "UPDATE versions SET status = 'active' WHERE item_id = ? AND version = ?",
            (item.id, current.version),
        )
        return get_item(conn, item.id)
