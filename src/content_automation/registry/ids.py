"""BG IDs (PRD D2): "BG-" + the item number with at least 3 digits (BG-007, later BG-1000).

Numbers are sequential and never reused, even after a reject or a delete: the counter lives in
the database and only goes up. config/registry.json "next_id" sets the first number when the
database is created; raising it later skips ahead, lowering it changes nothing. A reference is
a BG ID (any case, padding optional: bg-7 = BG-007) or an alias (a legacy Content ID such as
2026-W42-03 or a package folder name). Calendar row numbers are resolved by the calendar step.
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from content_automation.registry.db import RegistryError, transaction

DEFAULT_CONFIG_PATH = Path("config/registry.json")
PREFIX = "BG-"
COUNTER = "item"
_ID = re.compile(r"BG-?(\d+)", re.IGNORECASE)


class UnknownItem(RegistryError):
    """No item has this BG ID or alias."""


@dataclass(frozen=True)
class RegistryConfig:
    next_id: int = 1


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> RegistryConfig:
    """config/registry.json; a missing file means next_id 1."""
    if not path.is_file():
        return RegistryConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise RegistryError(f"{path} is not valid JSON: {error}") from error
    value = data.get("next_id", 1) if isinstance(data, dict) else None
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RegistryError(f'{path}: "next_id" must be a whole number of at least 1.')
    return RegistryConfig(next_id=value)


def format_id(number: int) -> str:
    if number < 1:
        raise ValueError(f"A BG number starts at 1, got {number}.")
    return f"{PREFIX}{number:03d}"


def parse_id(text: str) -> int | None:
    """The number of a BG ID ("BG-024", "bg-24", "BG24" -> 24); None for anything else."""
    match = _ID.fullmatch(text.strip())
    number = int(match.group(1)) if match else 0
    return number or None


def apply_config(conn: sqlite3.Connection, config: RegistryConfig) -> int:
    """Raise the counter to config.next_id if it is lower; return the next number."""
    with transaction(conn):
        row = conn.execute(
            "SELECT next_value FROM id_counter WHERE name = ?", (COUNTER,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO id_counter (name, next_value) VALUES (?, ?)",
                (COUNTER, config.next_id),
            )
            return config.next_id
        current = int(row["next_value"])
        if config.next_id > current:
            conn.execute(
                "UPDATE id_counter SET next_value = ? WHERE name = ?", (config.next_id, COUNTER)
            )
            return config.next_id
        return current


def peek_next_id(conn: sqlite3.Connection) -> str:
    """The ID the next item will get (for dry runs); nothing is allocated."""
    row = conn.execute("SELECT next_value FROM id_counter WHERE name = ?", (COUNTER,)).fetchone()
    return format_id(int(row["next_value"]) if row else 1)


def allocate_number(conn: sqlite3.Connection) -> int:
    """Take the next number; it is never handed out again (inside the caller's transaction)."""
    with transaction(conn):
        row = conn.execute(
            "SELECT next_value FROM id_counter WHERE name = ?", (COUNTER,)
        ).fetchone()
        number = int(row["next_value"]) if row else 1
        conn.execute(
            "INSERT INTO id_counter (name, next_value) VALUES (?, ?) "
            "ON CONFLICT (name) DO UPDATE SET next_value = excluded.next_value",
            (COUNTER, number + 1),
        )
    return number


def allocate_id(conn: sqlite3.Connection) -> str:
    """Take the next BG ID (BG-007)."""
    return format_id(allocate_number(conn))


def resolve(conn: sqlite3.Connection, ref: str) -> str:
    """The BG ID of the item a BG ID or alias names; UnknownItem if there is none."""
    text = ref.strip()
    number = parse_id(text)
    if number is not None:
        row = conn.execute("SELECT id FROM items WHERE number = ?", (number,)).fetchone()
        if row is None:
            raise UnknownItem(f"{format_id(number)} does not exist.")
        return str(row["id"])
    row = conn.execute("SELECT item_id FROM aliases WHERE alias = ?", (text,)).fetchone()
    if row is None:
        raise UnknownItem(
            f'No item has the ID or alias "{text}" (use a BG ID, a Content ID or a package '
            "folder name)."
        )
    return str(row["item_id"])
