import sqlite3
from pathlib import Path

import pytest

from content_automation.registry import open_registry
from content_automation.registry.db import (
    MIGRATIONS,
    Migration,
    RegistryError,
    connect,
    migrate,
    schema_version,
    transaction,
)

EXTRA = Migration(2, "test column", "ALTER TABLE items ADD COLUMN extra TEXT;")


def test_new_database_has_every_table(registry: sqlite3.Connection) -> None:
    tables = {row[0] for row in registry.execute("SELECT name FROM sqlite_master "
                                                 "WHERE type = 'table'")}
    assert {"schema_version", "id_counter", "items", "aliases", "versions", "decisions",
            "jobs", "authorizations", "publications", "events"} <= tables
    assert schema_version(registry) == len(MIGRATIONS)


def test_no_backup_for_a_new_database(db_path: Path, config_path: Path) -> None:
    open_registry(db_path, config_path).close()
    assert not (db_path.parent / "backups").exists()


def test_backup_before_a_migration(db_path: Path, config_path: Path) -> None:
    conn = open_registry(db_path, config_path)
    conn.execute("INSERT INTO id_counter (name, next_value) VALUES ('probe', 42)")
    result = migrate(conn, db_path, (*MIGRATIONS, EXTRA))
    assert [m.version for m in result.applied] == [2]
    assert result.backup is not None and result.backup.parent == db_path.parent / "backups"
    assert result.backup.name.startswith("registry-") and result.backup.suffix == ".db"
    with sqlite3.connect(result.backup) as copy:  # the copy is the database before migration 2
        assert copy.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == 1
        assert copy.execute("SELECT next_value FROM id_counter WHERE name = 'probe'"
                            ).fetchone()[0] == 42
    copy.close()
    assert schema_version(conn) == 2
    assert migrate(conn, db_path, (*MIGRATIONS, EXTRA)).applied == ()
    conn.close()


def test_failed_migration_rolls_back(db_path: Path, config_path: Path) -> None:
    conn = open_registry(db_path, config_path)
    broken = Migration(2, "broken", "ALTER TABLE items ADD COLUMN a TEXT; NOT SQL;")
    with pytest.raises(sqlite3.OperationalError):
        migrate(conn, db_path, (*MIGRATIONS, broken))
    assert schema_version(conn) == 1
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(items)")]
    assert "a" not in columns
    conn.close()


def test_newer_database_or_bad_numbering_is_refused(db_path: Path) -> None:
    conn = connect(db_path)
    migrate(conn, db_path, (*MIGRATIONS, EXTRA))
    with pytest.raises(RegistryError, match="newer than this code"):
        migrate(conn, db_path, MIGRATIONS)
    with pytest.raises(RegistryError, match="numbered"):
        migrate(conn, db_path, (EXTRA,))
    conn.close()


def test_transaction_rolls_back_and_nests(registry: sqlite3.Connection) -> None:
    with pytest.raises(RuntimeError), transaction(registry):
        registry.execute("INSERT INTO id_counter (name, next_value) VALUES ('a', 1)")
        raise RuntimeError("stop")
    with transaction(registry):
        registry.execute("INSERT INTO id_counter (name, next_value) VALUES ('b', 1)")
        with pytest.raises(RuntimeError), transaction(registry):
            registry.execute("INSERT INTO id_counter (name, next_value) VALUES ('c', 1)")
            raise RuntimeError("inner")
    names = {row["name"] for row in registry.execute("SELECT name FROM id_counter")}
    assert "a" not in names and "b" in names and "c" not in names
    assert not registry.in_transaction
