"""`ca item` and `ca audit` through the CLI (PRD §6, §14 D-5/D-10/D-12/D-19/D-22)."""

import json
import sqlite3
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from content_automation.cli import app
from content_automation.registry import db_path, open_registry
from content_automation.registry.audit import list_events
from content_automation.registry.db import RegistryError
from content_automation.registry.items import Item, add_alias, create_item, get_item, set_status
from content_automation.registry.statuses import IllegalTransition


@pytest.fixture
def conn(isolated: Path) -> Iterator[sqlite3.Connection]:
    connection = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield connection
    connection.close()


def _item(conn: sqlite3.Connection, title: str = "AI chatbots for dentists", **extra: object
          ) -> Item:
    fields: dict[str, object] = {"kind": "post", "title": title, "topic": title,
                                 "platforms": ["linkedin"], "deliverable": "linkedin_post"}
    fields.update(extra)
    return create_item(conn, **fields)  # type: ignore[arg-type]


def _generated(conn: sqlite3.Connection, item: Item) -> None:
    set_status(conn, item.id, "idea", "approved")
    for status in ("queued", "running", "generated"):
        set_status(conn, item.id, "generation", status)


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def _one_line_error(result: Result, code: int = 1) -> str:
    assert result.exit_code == code, result.output
    assert isinstance(result.exception, SystemExit)  # no traceback
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(lines) == 1, result.stderr
    return lines[0]


def test_list_filters_and_json(conn: sqlite3.Connection) -> None:
    first = _item(conn, planned_date=date(2026, 10, 19))
    _item(conn, "Second topic", kind="carousel", planned_date=date(2026, 10, 30))
    set_status(conn, first.id, "idea", "approved")
    result = ca("item", "list")
    assert result.exit_code == 0, result.output
    assert "BG-001" in result.stdout and "BG-002" in result.stdout and "2 item(s)" in result.stdout
    assert "BG-002" not in ca("item", "list", "--status", "idea=approved").stdout
    assert "BG-001" not in ca("item", "list", "--kind", "carousel").stdout
    assert "BG-002" not in ca("item", "list", "--week", "2026-W43").stdout
    rows = json.loads(ca("item", "list", "--json").stdout)
    assert [(r["id"], r["idea"], r["current_version"]) for r in rows] == [
        ("BG-001", "approved", 1), ("BG-002", "proposed", 1)]
    assert "dimension=value" in _one_line_error(ca("item", "list", "--status", "idea"), 2)
    assert ca("item", "list", "--status", "idea=done").exit_code == 1


def test_status_text_json_and_mismatches(conn: sqlite3.Connection, isolated: Path) -> None:
    package = isolated / "outputs" / "content" / "2026-10-03_dentists"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({
        "status": "draft", "items": {"post": {"status": "done", "files": ["images/post.png"]}},
        "uploads": {"images/post.png": {"provider": "mock", "status": "uploaded"}},
    }), encoding="utf-8")
    item = _item(conn, package_path=package.relative_to(isolated).as_posix())
    add_alias(conn, item.id, "2026-W42-03")
    result = ca("item", "status", "BG-1")
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "BG-001 post (linkedin_post): AI chatbots for dentists" in out
    assert "Aliases: 2026-W42-03" in out and "- v1 active (current)" in out
    assert "Drive: 1 uploaded (mock)" in out
    assert "package.json: post is done, registry generation is not_started" in out
    assert "- approve (idea gate): ca item approve BG-001" in out
    data = json.loads(ca("item", "status", "2026-W42-03", "--json").stdout)
    assert data["statuses"]["publication"] == {"linkedin": "not_ready"}
    assert {a["action"] for a in data["next_actions"]} == {"approve", "reject", "revise"}
    assert len(data["mismatches"]) == 2  # generation and upload


def test_gate_inference_both_ways_and_none_open(conn: sqlite3.Connection) -> None:
    idea, done = _item(conn), _item(conn, "Second")
    _generated(conn, done)
    assert ca("item", "approve", idea.id).stdout.strip() == "BG-001 idea: proposed → approved (v1)"
    assert ca("item", "approve", done.id).stdout.strip() == (
        "BG-002 review: not_reviewed → approved (v1)")
    assert get_item(conn, idea.id).approved_version == 1
    error = _one_line_error(ca("item", "approve", done.id))
    assert "nothing to approve" in error and "BG-002" in error
    rejected = ca("item", "reject", idea.id, "--gate", "review", "too", "late")
    assert "review gate is not open" in _one_line_error(rejected)


def test_reject_needs_a_reason_and_joins_words(conn: sqlite3.Connection) -> None:
    item = _item(conn)
    assert "needs a reason" in _one_line_error(ca("item", "reject", item.id), 2)
    result = ca("item", "reject", item.id, "too", "generic")
    assert result.stdout.strip() == 'BG-001 idea: proposed → rejected (v1) — reason: "too generic"'
    decision = list_events(conn, types=["decision"])[-1]
    assert decision.details["text"] == "too generic" and decision.actor == "user"
    back = ca("item", "approve", item.id)
    assert back.stdout.strip() == "BG-001 idea: rejected → approved (v1)"


def test_multi_id_approve_reports_each_failure(conn: sqlite3.Connection) -> None:
    first = _item(conn)
    result = ca("item", "approve", first.id, "BG-099")
    assert result.exit_code == 1
    assert "BG-001 idea: proposed → approved (v1)" in result.stdout
    assert "BG-099: BG-099 does not exist." in result.stderr
    assert "1 of 2 not approved" in result.stderr
    assert get_item(conn, first.id).idea_status == "approved"


def test_alias_and_row_number_lookup(conn: sqlite3.Connection) -> None:
    item = _item(conn)
    add_alias(conn, item.id, "2026-W42-03")
    add_alias(conn, item.id, "2026-10-03_ai-chatbots-for-dentists")
    assert "BG-001" in ca("item", "status", "2026-10-03_ai-chatbots-for-dentists").stdout
    assert "needs its week" in _one_line_error(ca("item", "approve", "3"))
    result = ca("item", "approve", "3", "--week", "2026-W42")
    assert result.stdout.strip() == "BG-001 idea: proposed → approved (v1)"
    assert "no registered row 4" in _one_line_error(ca("item", "status", "4", "--week", "2026-W42"))
    assert "No item has the ID or alias" in _one_line_error(ca("item", "status", "nope"))


def test_revise_with_and_without_title(conn: sqlite3.Connection) -> None:
    first, second = _item(conn), _item(conn, "Second")
    result = ca("item", "revise", first.id, "focus", "on", "Mittelstand", "--title",
                "AI chatbots for the Mittelstand")
    assert result.exit_code == 0, result.output
    assert "BG-001 idea: revise → proposed; v2 created" in result.stdout
    assert get_item(conn, first.id).title == "AI chatbots for the Mittelstand"
    plain = ca("item", "revise", second.id, "too", "generic")
    assert "revision_requested" in plain.stdout and "ca item resubmit BG-002" in plain.stdout
    assert "needs feedback" in _one_line_error(ca("item", "revise", second.id), 2)
    again = ca("item", "resubmit", second.id, "--title", "Chatbots that book appointments")
    assert again.stdout.strip() == ('BG-002 idea: revision_requested → proposed (v2); '
                                    'title "Chatbots that book appointments".')


def test_d22_revise_an_approved_idea(conn: sqlite3.Connection) -> None:
    item = _item(conn)
    set_status(conn, item.id, "idea", "approved")
    result = ca("item", "revise", item.id, "make", "it", "local")
    assert "BG-001 idea: revise → revision_requested; v2 created" in result.stdout
    with pytest.raises(IllegalTransition, match="only while the idea is approved"):
        set_status(conn, item.id, "generation", "queued")  # no generation until approved again
    assert "resubmit" in _one_line_error(ca("item", "revise", item.id, "more"))
    ca("item", "resubmit", item.id, "--title", "AI chatbots for local dentists")
    assert ca("item", "approve", item.id).stdout.strip() == "BG-001 idea: proposed → approved (v2)"
    assert get_item(conn, item.id).approved_version == 2


@pytest.mark.parametrize(("end", "allowed"), [("queued", False), ("failed", True),
                                              ("partial", True)])
def test_d22_window(conn: sqlite3.Connection, end: str, allowed: bool) -> None:
    item = _item(conn)
    set_status(conn, item.id, "idea", "approved")
    path = {"queued": ["queued"], "failed": ["queued", "running", "failed"],
            "partial": ["queued", "running", "partial"]}[end]
    for status in path:
        set_status(conn, item.id, "generation", status)
    result = ca("item", "revise", item.id, "change", "it")
    assert (result.exit_code == 0) is allowed, result.output


def test_history_and_audit_show(conn: sqlite3.Connection) -> None:
    item = _item(conn)
    ca("item", "reject", item.id, "off", "brand")
    history = ca("item", "history", item.id)
    assert history.exit_code == 0
    assert "item_created" in history.stdout and 'idea reject "off brand"' in history.stdout
    shown = json.loads(ca("audit", "show", "--type", "decision", "--json").stdout)
    assert [e["details"]["text"] for e in shown] == ["off brand"]
    commands = [e for e in list_events(conn, types=["command_run"])]
    assert all(e.actor == "user" for e in commands)
    assert any(e.command == 'ca item reject BG-001 "off brand"' for e in commands)
    assert len(json.loads(ca("audit", "show", "--limit", "2", "--json").stdout)) == 2
    assert "Unknown event type" in _one_line_error(ca("audit", "show", "--type", "nope"), 2)
    assert "BG-001" in ca("audit", "show", "--item", "BG-1").stdout


def test_registry_error_type_is_registry_error() -> None:
    assert issubclass(IllegalTransition, RegistryError)
