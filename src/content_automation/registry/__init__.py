"""The content-item registry (Phase 4): one record per piece of content in state/registry.db.

All registry logic lives in this package (PRD D11); the CLI and skills call only this package,
and no SQL is written anywhere else. open_registry() is the way in: it creates or upgrades the
database (with a backup first) and applies config/registry.json.
"""

import sqlite3
from pathlib import Path

from content_automation.registry.audit import append_event
from content_automation.registry.db import DEFAULT_DB_PATH, connect, migrate
from content_automation.registry.ids import DEFAULT_CONFIG_PATH, apply_config, load_config

DB_FILE = "registry.db"


def db_path(state_dir: Path) -> Path:
    """The registry database inside STATE_DIR."""
    return state_dir / DB_FILE


def open_registry(
    db_path: Path = DEFAULT_DB_PATH, config_path: Path = DEFAULT_CONFIG_PATH
) -> sqlite3.Connection:
    """Open the registry, run pending schema migrations (logged as migration_run) and raise
    the ID counter to config/registry.json "next_id" if it is lower."""
    config = load_config(config_path)
    conn = connect(db_path)
    try:
        result = migrate(conn, db_path)
        for migration in result.applied:
            append_event(
                conn, "migration_run", command="schema migration",
                details={"kind": "schema", "version": migration.version, "name": migration.name,
                         "backup": result.backup.as_posix() if result.backup else None},
            )
        apply_config(conn, config)
    except BaseException:
        conn.close()
        raise
    return conn
