"""The last value the app wrote to each workflow cell of the Content Tracker (§14 D-15).

Per row (its Content ID) and column: what was written and the registry value it came from. A
Sheet cell that differs from what was written was edited by hand: a conflict, and the row is
not written until the user decides (`ca tracking resolve`). "Keep the Sheet" makes the Sheet's
value the written one, so it stays until the registry value changes again.
"""

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass

from content_automation.registry.db import now, transaction


@dataclass(frozen=True)
class CellRecord:
    written: str  # what the Sheet should show if nobody edited it
    source: str  # the registry value behind it


def last_cells(conn: sqlite3.Connection) -> dict[str, dict[str, CellRecord]]:
    records: dict[str, dict[str, CellRecord]] = {}
    for row in conn.execute("SELECT row_key, column_name, written, source FROM tracker_cells"):
        records.setdefault(str(row["row_key"]), {})[str(row["column_name"])] = CellRecord(
            str(row["written"]), str(row["source"]))
    return records


def record_cells(conn: sqlite3.Connection,
                 records: Mapping[str, Mapping[str, CellRecord]]) -> None:
    stamp = now()
    with transaction(conn):
        for key, cells in records.items():
            for column, record in cells.items():
                conn.execute(
                    "INSERT INTO tracker_cells (row_key, column_name, written, source, "
                    "updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT (row_key, column_name) DO "
                    "UPDATE SET written = excluded.written, source = excluded.source, "
                    "updated_at = excluded.updated_at",
                    (key, column, record.written, record.source, stamp),
                )
