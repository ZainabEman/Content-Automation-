"""Approve and reject by ID (PRD D5, §14 D-10): the gate is inferred unless the user names it.

Each call is one transaction: the status change, the decision row (with the reason for a reject)
and, for an approve, approved_version = the current version. Revise and resubmit are in
versions.py.
"""

import sqlite3
from dataclasses import dataclass

from content_automation.registry.audit import Actor
from content_automation.registry.db import RegistryError, transaction
from content_automation.registry.decisions import Gate, record_decision
from content_automation.registry.gates import Action, closed_message, gate_open, open_gate
from content_automation.registry.items import get_item, set_status
from content_automation.registry.versions import set_approved_version


@dataclass(frozen=True)
class GateChange:
    item_id: str
    gate: Gate
    before: str
    after: str
    version: int

    def line(self) -> str:
        """BG-007 idea: proposed → approved (v2)"""
        return f"{self.item_id} {self.gate}: {self.before} → {self.after} (v{self.version})"


def _decide(
    conn: sqlite3.Connection, ref: str, action: Action, target: str, text: str | None,
    gate: Gate | None, actor: Actor, command: str | None,
) -> GateChange:
    with transaction(conn):
        item = get_item(conn, ref)
        chosen = gate or open_gate(item, action)
        if chosen is None or not gate_open(item, action, chosen):
            raise RegistryError(closed_message(item, action, chosen))
        before = item.status(chosen)
        set_status(conn, item.id, chosen, target, actor=actor, command=command)
        record_decision(conn, item.id, item.current_version, chosen,
                        "approve" if action == "approve" else "reject", text, actor=actor,
                        command=command)
        if action == "approve" and item.approved_version != item.current_version:
            set_approved_version(conn, item.id, item.current_version, actor=actor,
                                 command=command)
        return GateChange(item.id, chosen, before, target, item.current_version)


def approve(
    conn: sqlite3.Connection, ref: str, *, gate: Gate | None = None, actor: Actor = "user",
    command: str | None = None, note: str | None = None,
) -> GateChange:
    """Approve the open gate (idea first, then review) or the named one; `note` is stored with
    the decision (e.g. where the approval came from)."""
    return _decide(conn, ref, "approve", "approved", note, gate, actor, command)


def reject(
    conn: sqlite3.Connection, ref: str, reason: str, *, gate: Gate | None = None,
    actor: Actor = "user", command: str | None = None,
) -> GateChange:
    """Reject with a reason (required) on the open gate or the named one."""
    text = reason.strip()
    if not text:
        raise RegistryError("A reject needs a reason: why is it rejected?")
    return _decide(conn, ref, "reject", "rejected", text, gate, actor, command)
