"""The Content Tracker with the registry (PRD Phase 4 §8, §14 D-13..D-16), mock storage only."""

import csv
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.content.package import ContentPackage, PackageItem, save_package
from content_automation.content.tracking import (
    COLUMNS,
    DEFAULT_REGISTRY_COLUMNS,
    Cell,
    find_conflicts,
    plan_upsert,
)
from content_automation.registry import db_path, open_registry
from content_automation.registry.audit import list_events
from content_automation.registry.items import create_item, set_status
from content_automation.registry.jobs import JobConfig
from content_automation.registry.progress import set_upload
from content_automation.registry.runtime import Scope, activate
from content_automation.registry.tracker import CellRecord, last_cells
from content_automation.storage import registry_cells, sync_package, update_tracker
from content_automation.storage.providers.drive_api import DriveState, DriveStorage
from content_automation.storage.providers.mock import MockStorage

EXTRA = tuple(DEFAULT_REGISTRY_COLUMNS.values())
BG = EXTRA[0]
OLD_ROW = ["2026-W42-01", "Topic", "topic:Topic", "LinkedIn", "linkedin_post", "Caption",
           "#BrandedGenius", "mock://x", "Approved", "Posted", "2026-10-20"]


def _entry(content_id: str = "2026-W42-01", **cells: str) -> dict[str, str]:
    entry = dict(zip(COLUMNS[:8], OLD_ROW[:8], strict=True))
    entry["Content ID"] = content_id
    entry.update({BG: "BG-001", EXTRA[1]: "v1", EXTRA[2]: "approved", EXTRA[3]: "generated",
                  EXTRA[4]: "not_reviewed", EXTRA[5]: "uploaded (mock)",
                  EXTRA[6]: "2026-10-13 10:00 UTC"})
    entry.update(cells)
    return entry


# --- the merge rules --------------------------------------------------------------------------


def test_registry_columns_are_appended_and_the_bg_id_filled() -> None:
    table = [list(COLUMNS), list(OLD_ROW)]
    plan = plan_upsert(table, [_entry()], {}, EXTRA)
    header = [cell for cell in plan.cells if cell.row == 0]
    assert [cell.value for cell in header] == list(EXTRA)
    assert header[0].column == len(COLUMNS)
    written = {cell.column: cell.value for cell in plan.cells if cell.row == 1}
    assert written[len(COLUMNS)] == "BG-001"  # matched by Content ID, BG ID filled in
    assert all(column >= len(COLUMNS) or column < 8 for column in written)  # no manager cell
    assert plan.updated == ["2026-W42-01"]
    assert plan.records["2026-W42-01"][BG] == CellRecord("BG-001", "BG-001")


def test_rows_match_by_bg_id_first() -> None:
    header = [*COLUMNS, *EXTRA]
    row = [*OLD_ROW, "BG-001", "v1", "approved", "generated", "not_reviewed", "uploaded (mock)",
           "x"]
    row[0] = "old-content-id"
    plan = plan_upsert([header, row], [_entry()], {}, EXTRA)
    assert plan.added == [] and plan.updated == ["2026-W42-01"]
    assert Cell(1, 0, "2026-W42-01") in plan.cells


def test_hand_edit_is_a_conflict_and_the_row_is_not_written() -> None:
    header = [*COLUMNS, *EXTRA]
    row = [*OLD_ROW, "BG-001", "v1", "approved", "generated", "not_reviewed", "uploaded (mock)",
           "2026-10-13 10:00 UTC"]
    row[1] = "Topic edited by the manager"
    last = {"2026-W42-01": {"Topic": CellRecord("Topic", "Topic")}}
    plan = plan_upsert([header, row], [_entry(**{EXTRA[4]: "approved"})], last, EXTRA)
    assert plan.cells == [] and plan.updated == []
    [conflict] = plan.conflicts
    assert conflict.kind == "hand edit" and "Topic edited by the manager" in conflict.detail


def test_kept_sheet_value_stays_until_the_registry_changes() -> None:
    header = [*COLUMNS, *EXTRA]
    row = [*OLD_ROW, "BG-001", "v1", "approved", "generated", "not_reviewed", "uploaded (mock)",
           "2026-10-13 10:00 UTC"]
    row[1] = "Manager's topic"
    last = {"2026-W42-01": {"Topic": CellRecord("Manager's topic", "Topic")}}  # --keep-sheet
    assert plan_upsert([header, row], [_entry()], last, EXTRA).cells == []
    changed = plan_upsert([header, row], [_entry(Topic="New registry topic")], last, EXTRA)
    assert Cell(1, 1, "New registry topic") in changed.cells


def test_duplicates_and_new_rows() -> None:
    table = [list(COLUMNS), list(OLD_ROW), list(OLD_ROW)]
    plan = plan_upsert(table, [_entry(), _entry("2026-W42-02", **{BG: "BG-002"})], {}, EXTRA)
    assert [c.kind for c in plan.conflicts] == ["duplicate"]
    assert plan.added == ["2026-W42-02"]
    new = plan.rows[0]
    assert new[COLUMNS.index("Approval status")] == "Pending"  # only on a new row
    assert new[len(COLUMNS)] == "BG-002"


def test_conflict_report() -> None:
    header = [*COLUMNS, *EXTRA]
    edited = [*OLD_ROW, "BG-001", "v1", "approved", "generated", "not_reviewed", "uploaded",
              "x"]
    stray = [*OLD_ROW, "BG-009", "", "", "", "", "", ""]
    stray[0] = "2026-W40-01"
    copied = [*OLD_ROW, "BG-001", "", "", "", "", "", ""]
    copied[0] = "2026-W42-07"
    last = {"2026-W42-01": {EXTRA[5]: CellRecord("uploaded (mock)", "uploaded (mock)")}}
    conflicts = find_conflicts([header, edited, stray, copied], last,
                               expected={"2026-W42-01": {"BG-001"}, "2026-W42-03": {"BG-003"}},
                               known_ids={"BG-001", "BG-003", "2026-W42-01", "2026-W42-03"},
                               extra=EXTRA)
    kinds = sorted((c.kind, c.key) for c in conflicts)
    assert kinds == [("duplicate", "BG-001"), ("hand edit", "2026-W42-01"),
                     ("missing in the Sheet", "2026-W42-03"),
                     ("missing in the registry", "2026-W40-01")]


# --- mock storage with the registry -----------------------------------------------------------


@pytest.fixture
def conn(isolated: Path) -> Iterator[sqlite3.Connection]:
    connection = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield connection
    connection.close()


def _package(conn: sqlite3.Connection) -> tuple[Path, str]:
    folder = Path("outputs/content/2026-10-13_post")
    (folder / "images").mkdir(parents=True)
    (folder / "images" / "post-1.png").write_bytes(b"png")
    save_package(folder, ContentPackage(
        package_id=folder.name, topic="Chatbots", platform="linkedin", formats=["post"],
        deliverables=["linkedin_post"],
        items={"post": PackageItem(status="done", files=["images/post-1.png"])},
    ))
    item = create_item(conn, kind="post", title="Chatbots", topic="Chatbots",
                       platforms=["linkedin"], deliverable="linkedin_post",
                       package_path=folder.as_posix())
    set_status(conn, item.id, "idea", "approved")
    return folder, item.id


def _scope(conn: sqlite3.Connection) -> Scope:
    return Scope(conn, JobConfig(), command="test", part_of={"linkedin_post": "post"},
                 tracker_columns=dict(DEFAULT_REGISTRY_COLUMNS))


def _sheet(isolated: Path) -> list[dict[str, str]]:
    path = isolated / "outputs" / "drive" / "Content Automation" / "tracking.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_sync_conflict_and_resolve(isolated: Path, conn: sqlite3.Connection,
                                   monkeypatch: pytest.MonkeyPatch) -> None:
    folder, item_id = _package(conn)
    storage = MockStorage(isolated / "outputs" / "drive" / "Content Automation")
    with activate(_scope(conn)):
        result = sync_package(folder, storage, _catalog())
        assert "BG-001" in result.lines[0]  # D-13: no Content ID -> the BG ID folder
        set_upload(conn, item_id, "uploaded", "mock")
        cells = registry_cells(folder)
        entry = {"Content ID": folder.name, "Topic": "Chatbots", "Research source": "topic:x",
                 "Platform": "LinkedIn", "Content type": "linkedin_post", "Caption": "c",
                 "Hashtags": "#BrandedGenius", "Image/video link": "mock://x", **cells}
        assert cells[EXTRA[5]] == "uploaded (mock)"
        line = update_tracker(storage, [entry])
    assert "1 added" in line
    [row] = _sheet(isolated)
    assert row[BG] == item_id and row["Approval status"] == "Pending"
    assert last_cells(conn)[folder.name]["Topic"].written == "Chatbots"
    path = isolated / "outputs" / "drive" / "Content Automation" / "tracking.csv"
    path.write_text(path.read_text(encoding="utf-8").replace("Chatbots", "Bots by hand", 1),
                    encoding="utf-8")
    with activate(_scope(conn)):
        line = update_tracker(storage, [entry | {"Caption": "new caption"}])
    assert "1 not written" in line and _sheet(isolated)[0]["Caption"] == "c"
    [found] = list_events(conn, types=["conflict_found"])
    assert found.item_id == item_id and found.details["kind"] == "hand edit"
    runner = CliRunner()
    report = runner.invoke(app, ["tracking", "conflicts"])
    assert report.exit_code == 0, report.output
    assert "hand edit" in report.stdout and "Bots by hand" in report.stdout
    kept = runner.invoke(app, ["tracking", "resolve", item_id, "--keep-sheet"])
    assert kept.exit_code == 0, kept.output
    assert "kept the Sheet's values for Topic" in kept.stdout
    with activate(_scope(conn)):
        line = update_tracker(storage, [entry | {"Caption": "new caption"}])
    assert "1 updated" in line
    sheet = _sheet(isolated)[0]
    assert sheet["Topic"] == "Bots by hand" and sheet["Caption"] == "new caption"
    monkeypatch.setattr("content_automation.storage.tracker_entry",
                        lambda *_: {key: value for key, value in entry.items()
                                    if key not in EXTRA} | {"Topic": "Chatbots"})
    used = runner.invoke(app, ["tracking", "resolve", item_id, "--use-registry"])
    assert used.exit_code == 0, used.output
    assert _sheet(isolated)[0]["Topic"] == "Chatbots"
    assert runner.invoke(app, ["tracking", "conflicts"]).stdout.strip().endswith("no conflicts.")


def _catalog() -> Any:
    from content_automation.content.deliverables import load_deliverables

    return load_deliverables(Path(__file__).resolve().parents[2] / "config" / "deliverables.json")


# --- the Drive adapter with a fake Sheets client ------------------------------------------------


class _Request:
    def __init__(self, log: list[tuple[str, Any]], name: str, kwargs: dict[str, Any],
                 result: dict[str, Any]) -> None:
        self._log, self._name, self._kwargs, self._result = log, name, kwargs, result

    def execute(self) -> dict[str, Any]:
        self._log.append((self._name, self._kwargs))
        return self._result


class _FakeSheets:
    """spreadsheets().get / batchUpdate and spreadsheets().values().get / batchUpdate."""

    def __init__(self, table: list[list[str]], columns: int) -> None:
        self.log: list[tuple[str, Any]] = []
        self.table, self.columns = table, columns

    def spreadsheets(self) -> "_FakeSheets":
        return self

    def values(self) -> "_FakeSheets":
        return self

    def get(self, **kwargs: Any) -> _Request:
        if "range" in kwargs:
            return _Request(self.log, "values.get", kwargs, {"values": self.table})
        props = {"sheetId": 0, "title": "Tracker",
                 "gridProperties": {"rowCount": 100, "columnCount": self.columns}}
        return _Request(self.log, "get", kwargs, {"sheets": [{"properties": props}]})

    def batchUpdate(self, **kwargs: Any) -> _Request:  # noqa: N802 (Google's name)
        name = "values.batchUpdate" if "valueInputOption" in kwargs["body"] else "batchUpdate"
        return _Request(self.log, name, kwargs, {})


def test_drive_adapter_widens_the_sheet_for_registry_columns() -> None:
    fake = _FakeSheets([list(COLUMNS), list(OLD_ROW)], columns=len(COLUMNS))
    drive = object.__new__(DriveStorage)
    drive._state = DriveState(tracker_id="sheet-1", tracker_sheet_id=0)
    drive._sheets_service = fake
    drive._tab_cache = None
    drive._rows_read = None
    plan = plan_upsert(drive.read_tracker(), [_entry()], {}, EXTRA)
    drive.write_tracker(plan.cells, plan.rows)
    names = [name for name, _ in fake.log]
    assert names == ["get", "values.get", "batchUpdate", "values.batchUpdate"]
    widen = fake.log[2][1]["body"]["requests"][0]["appendDimension"]
    assert widen == {"sheetId": 0, "dimension": "COLUMNS", "length": len(EXTRA)}
    data = fake.log[3][1]["body"]["data"]
    assert {"range": "'Tracker'!L1", "values": [["BG ID"]]} in data
