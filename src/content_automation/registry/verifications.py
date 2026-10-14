"""Integration verifications (Phase 10 Step 2): one row per check, never changed.

`ca verify run` records an offline result (actor system); `ca verify record --live` records the
user's manual live test (actor user). An integration is operational only when its newest live
result is a pass.
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import RegistryError, now, transaction

Mode = Literal["offline", "live"]
Result = Literal["pass", "fail"]


@dataclass(frozen=True)
class Verification:
    integration: str
    mode: str
    result: str
    note: str | None
    actor: str
    created_at: str

    def line(self) -> str:
        note = f" — {self.note}" if self.note else ""
        return f"{self.mode} {self.result} {self.created_at[:16].replace('T', ' ')}{note}"


def record_verification(conn: sqlite3.Connection, integration: str, mode: Mode, result: Result,
                        note: str | None, *, actor: Actor = "system",
                        command: str | None = None) -> Verification:
    if result not in ("pass", "fail"):
        raise RegistryError(f'A result is pass or fail, not "{result}".')
    with transaction(conn):
        stamp = now()
        conn.execute("INSERT INTO verifications (integration, mode, result, note, actor, "
                     "created_at) VALUES (?, ?, ?, ?, ?, ?)",
                     (integration, mode, result, note, actor, stamp))
        append_event(conn, "verification_recorded", actor=actor, command=command,
                     details={"integration": integration, "mode": mode, "result": result,
                              "note": note})
    return Verification(integration, mode, result, note, actor, stamp)


def latest(conn: sqlite3.Connection, integration: str, mode: Mode) -> Verification | None:
    row = conn.execute("SELECT * FROM verifications WHERE integration = ? AND mode = ? "
                       "ORDER BY id DESC LIMIT 1", (integration, mode)).fetchone()
    if row is None:
        return None
    return Verification(str(row["integration"]), str(row["mode"]), str(row["result"]),
                        None if row["note"] is None else str(row["note"]), str(row["actor"]),
                        str(row["created_at"]))
