import inspect
import sqlite3
from pathlib import Path

import pytest

from content_automation.registry import audit, open_registry
from content_automation.registry.audit import append_event, list_events
from content_automation.registry.db import RegistryError

FAKE_KEY = "sk-or-v1-fakefakefake0123456789"


def test_append_and_filter(registry: sqlite3.Connection) -> None:
    first = append_event(registry, "command_run", actor="user", command="ca item list")
    append_event(registry, "decision", actor="user", item_id="BG-001", version=1,
                 details={"gate": "idea", "action": "reject", "text": "too generic"})
    assert first.created_at.endswith("Z") and "T" in first.created_at
    assert [e.type for e in list_events(registry, item_id="BG-001")] == ["decision"]
    assert [e.type for e in list_events(registry, types=["command_run"])] == ["command_run"]
    assert list_events(registry, since="2999-01-01") == []
    assert len(list_events(registry, since=first.created_at)) >= 2
    assert len(list_events(registry, limit=1)) == 1
    assert list_events(registry, types=["decision"])[0].details["text"] == "too generic"


def test_unknown_type_or_actor_is_refused(registry: sqlite3.Connection) -> None:
    with pytest.raises(RegistryError, match="Unknown event type"):
        append_event(registry, "something_else")
    with pytest.raises(RegistryError, match="user or system"):
        append_event(registry, "command_run", actor="admin")  # type: ignore[arg-type]


def test_audit_log_is_append_only(registry: sqlite3.Connection) -> None:
    public = [name for name, function in inspect.getmembers(audit, inspect.isfunction)
              if not name.startswith("_") and inspect.getmodule(function) is audit]
    assert sorted(public) == ["append_event", "list_events"]
    event = append_event(registry, "command_run", command="ca audit show")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        registry.execute("UPDATE events SET command = 'changed' WHERE id = ?", (event.id,))
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        registry.execute("DELETE FROM events WHERE id = ?", (event.id,))
    assert list_events(registry, types=["command_run"])[-1] == event


def test_events_are_redacted(registry: sqlite3.Connection,
                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    event = append_event(
        registry, "job_failed", command=f"ca image --key {FAKE_KEY}",
        details={"error": f"401 for key {FAKE_KEY}", "token": "abc12345xyz",
                 "nested": [{"refresh_token": "1//0abcdefghijklmnopqrstuvwxyz"}]},
    )
    stored = registry.execute("SELECT command, details FROM events WHERE id = ?",
                              (event.id,)).fetchone()
    assert FAKE_KEY not in stored["command"] and FAKE_KEY not in stored["details"]
    assert "abc12345xyz" not in stored["details"] and "1//0abc" not in stored["details"]
    assert event.details["error"] == "401 for key [redacted]"


def test_schema_migration_is_logged(db_path: Path, config_path: Path) -> None:
    conn = open_registry(db_path, config_path)
    [event] = list_events(conn, types=["migration_run"])
    assert event.details == {"backup": None, "kind": "schema", "name": "registry core",
                             "version": 1}
    conn.close()
    conn = open_registry(db_path, config_path)  # nothing pending: nothing logged
    assert len(list_events(conn, types=["migration_run"])) == 1
    conn.close()
