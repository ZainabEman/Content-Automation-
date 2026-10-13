"""The calendar as a view of the registry and the migration (PRD Phase 4 D10, §14 D-8, D-9,
D-11, D-12, D-18)."""

import csv
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from content_automation.cli import app
from content_automation.content.calendar import COLUMNS, OLD_COLUMNS, view_status
from content_automation.registry import db_path, open_registry
from content_automation.registry.audit import list_events
from content_automation.registry.decisions import list_decisions
from content_automation.registry.ids import resolve
from content_automation.registry.items import aliases, get_item, list_items

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "migration"
WEEK = "2026-W45"
TOPICS = ["Chatbots that answer at night", "Missed calls cost dentists patients",
          "AI receptionists for gyms", "Five WhatsApp flows for shops",
          "Lead scoring without spreadsheets"]


@pytest.fixture
def env(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("CALENDAR_FILE", str(REPO / "config" / "calendar.json"))
    monkeypatch.setenv("DELIVERABLES_FILE", str(REPO / "config" / "deliverables.json"))
    return isolated


@pytest.fixture
def conn(env: Path) -> Iterator[sqlite3.Connection]:
    connection = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield connection
    connection.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _new_week() -> Path:
    args = ["calendar", "new", "--week", WEEK]
    for topic in TOPICS:
        args += ["--topic", topic]
    result = ca(*args)
    assert result.exit_code == 0, result.output
    return Path("calendar") / f"{WEEK}.csv"


def test_status_mapping() -> None:
    assert [view_status(idea, "not_started") for idea in
            ("proposed", "revision_requested", "rejected", "approved")] == [
        "Proposed", "Revision requested", "Rejected", "Approved"]
    assert [view_status("approved", g) for g in
            ("queued", "running", "generated", "failed", "partial")] == [
        "In progress", "In progress", "Generated", "Failed", "Failed"]


def test_new_calendar_is_a_view_with_bg_ids(conn: sqlite3.Connection) -> None:
    path = _new_week()
    with path.open(encoding="utf-8") as handle:
        assert tuple(handle.readline().strip().split(",")) == COLUMNS
    rows = _rows(path)
    assert [row["BG ID"] for row in rows] == ["BG-001", "BG-002", "BG-003", "BG-004", "BG-005"]
    assert {row["Status"] for row in rows} == {"Proposed"}
    assert {row["Version"] for row in rows} == {"1"}
    assert aliases(conn, "BG-002") == [f"{WEEK}-02"]
    assert get_item(conn, "BG-005").planned_date is not None
    assert resolve(conn, f"{WEEK}-03") == "BG-003"
    assert "| 3 | BG-003 |" in ca("calendar", "show", "--week", WEEK).stdout


def test_approve_and_reject_go_through_the_registry(conn: sqlite3.Connection) -> None:
    path = _new_week()
    approved = ca("calendar", "approve", "1", "3", "--week", WEEK)
    assert approved.exit_code == 0, approved.output
    assert f"{WEEK}.csv: row 1 BG-001 idea: proposed → approved (v1)" in approved.stdout
    rejected = ca("calendar", "reject", "2", "--week", WEEK, "--reason", "off strategy")
    assert "row 2 BG-002 idea: proposed → rejected (v1)" in rejected.stdout
    assert list_decisions(conn, "BG-002")[-1].text == "off strategy"
    plain = ca("calendar", "reject", "4", "--week", WEEK)
    assert "(no reason given)" in list_decisions(conn, "BG-004")[-1].text  # type: ignore[operator]
    assert plain.exit_code == 0
    assert [row["Status"] for row in _rows(path)] == [
        "Approved", "Rejected", "Approved", "Rejected", "Proposed"]
    again = ca("calendar", "approve", "all", "--week", WEEK)
    assert "row 5 BG-005" in again.stdout
    by_id = ca("item", "approve", "2", "--week", WEEK)  # D-12: a row number with its week
    assert by_id.stdout.strip() == "BG-002 idea: rejected → approved (v1)"


def test_hand_edits_stop_and_sync(conn: sqlite3.Connection) -> None:
    path = _new_week()
    text = path.read_text(encoding="utf-8")
    edited = text.replace("AI receptionists for gyms", "AI receptionists for yoga studios")
    edited = edited.replace(f"{WEEK}-04", f"{WEEK}-04", 1)
    rows = _rows(path)
    edited = edited.replace(f",{rows[4]['Planned date']},Lead scoring", ",2026-11-08,Lead scoring")
    lines = edited.splitlines(keepends=True)
    lines[1] = lines[1].replace(",Proposed,", ",Approved,")  # a Status edit by hand
    path.write_text("".join(lines), encoding="utf-8")
    stopped = ca("calendar", "approve", "1", "--week", WEEK)
    assert stopped.exit_code == 2
    assert "edited by hand" in stopped.stderr and "+1,BG-001" in stopped.stderr
    assert "--discard-edits" in stopped.stderr and "--import-edits" in stopped.stderr
    assert get_item(conn, "BG-001").idea_status == "proposed"  # nothing changed
    assert ca("calendar", "show", "--week", WEEK).exit_code == 2
    synced = ca("calendar", "sync", "--week", WEEK, "--import-edits")
    assert synced.exit_code == 0, synced.output
    assert 'BG-003: topic imported: "AI receptionists for yoga studios"' in synced.stdout
    assert "BG-005: planned date imported: 2026-11-08" in synced.stdout
    assert 'BG-001: Status edit "Approved" not imported' in synced.stdout
    assert get_item(conn, "BG-003").title == "AI receptionists for yoga studios"
    assert _rows(path)[0]["Status"] == "Proposed"  # the registry wins for Status
    assert list_events(conn, item_id="BG-003", types=["item_updated"])
    path.write_text(path.read_text(encoding="utf-8").replace("yoga studios", "pilates"),
                    encoding="utf-8")
    discarded = ca("calendar", "sync", "--week", WEEK, "--discard-edits")
    assert "hand edits discarded" in discarded.stdout
    assert "yoga studios" in path.read_text(encoding="utf-8")
    assert ca("calendar", "show", "--week", WEEK).exit_code == 0


def test_replace_moves_the_content_id(conn: sqlite3.Connection) -> None:
    _new_week()
    args = ["calendar", "new", "--week", WEEK, "--replace"]
    for topic in reversed(TOPICS):
        args += ["--topic", topic]
    replaced = ca(*args)
    assert replaced.exit_code == 0, replaced.output
    old = get_item(conn, "BG-001")
    assert old.idea_status == "rejected" and list_decisions(conn, "BG-001")[-1].text == "replaced"
    assert resolve(conn, f"{WEEK}-01") == "BG-006"
    assert aliases(conn, "BG-001") == [] and len(list_items(conn)) == 10
    assert [e.type for e in list_events(conn, item_id="BG-001")][0] == "item_created"


def test_old_header_is_read_and_registered(conn: sqlite3.Connection) -> None:
    folder = Path("calendar")
    folder.mkdir()
    shutil.copy(FIXTURES / "calendar" / "2026-W42.csv", folder / "2026-W42.csv")
    with (folder / "2026-W42.csv").open(encoding="utf-8") as handle:
        assert tuple(handle.readline().strip().split(",")) == OLD_COLUMNS
    result = ca("calendar", "approve", "1", "--week", "2026-W42")
    assert result.exit_code == 0, result.output
    assert "row 1 BG-001 idea: proposed → approved" in result.stdout
    rows = _rows(folder / "2026-W42.csv")
    assert rows[0]["BG ID"] == "BG-001" and rows[1]["Status"] == "Approved"
    assert get_item(conn, "2026-W42-03").idea_status == "rejected"  # carried over, logged


# --- migration -------------------------------------------------------------------------------


@pytest.fixture
def legacy(env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for name in ("calendar", "outputs"):
        shutil.copytree(FIXTURES / name, env / name)
    monkeypatch.setenv("SECRETS_DIR", str(FIXTURES / "secrets-fake"))
    return env


def test_migration_dry_run_and_apply(legacy: Path) -> None:
    dry = ca("registry", "migrate", "--dry-run")
    assert dry.exit_code == 0, dry.output
    assert dry.stdout.splitlines()[0] == (
        "DRY RUN: 7 would be created, 0 skipped (already migrated), 1 unreadable.")
    assert "fake-folder-id" not in dry.stdout and "fake-root-id" not in dry.stdout
    assert "drive_state.json: 1 Drive content folder(s) known" in dry.stdout
    assert "2026-W40-01; not migrated" in dry.stdout
    assert "2026-10-02_broken/package.json" in dry.stdout
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    assert list_items(conn) == []  # a dry run creates nothing
    conn.close()
    applied = ca("registry", "migrate")
    assert applied.exit_code == 0, applied.output
    assert applied.stdout.startswith("7 created, 0 skipped")
    assert "Backup first: " in applied.stdout
    assert "calendar/2026-W42.csv: rewritten with the new header" in applied.stdout
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    by_alias = {alias: get_item(conn, alias) for alias in
                ("2026-W42-01", "2026-W42-02", "2026-W42-03", "2026-W42-04", "2026-W42-05")}
    assert [(i.idea_status, i.generation_status) for i in by_alias.values()] == [
        ("proposed", "not_started"), ("approved", "generated"), ("rejected", "not_started"),
        ("approved", "generated"), ("approved", "not_started")]
    two = by_alias["2026-W42-02"]
    assert (two.upload_status, two.upload_provider) == ("uploaded", "mock")
    assert two.package_path == "outputs/content/2026-10-14_topic-b"
    assert aliases(conn, two.id) == ["2026-W42-02", "2026-10-14_topic-b#facebook_post"]
    v1 = get_item(conn, "2026-10-01_v1-package#facebook_ad")
    assert (v1.kind, v1.idea_status, v1.generation_status) == ("ad", "approved", "generated")
    assert get_item(conn, "2026-10-01_v1-package#facebook_post").kind == "post"
    assert list_items(conn)[0].id == "BG-001"
    rows = _rows(Path("calendar") / "2026-W42.csv")
    assert [row["BG ID"] for row in rows] == [i.id for i in by_alias.values()]
    assert [row["Status"] for row in rows] == [
        "Proposed", "Generated", "Rejected", "Generated", "Approved"]
    [run] = [e for e in list_events(conn, types=["migration_run"]) if e.details["kind"] == "data"]
    assert run.details["created"] == 7
    note = list_decisions(conn, two.id)[0].text
    assert note is not None and "migrated from calendar 2026-W42 row 2" in note
    conn.close()
    again = ca("registry", "migrate")
    assert again.stdout.startswith("0 created, 7 skipped (already migrated), 1 unreadable.")
    assert "Backup first" not in again.stdout
