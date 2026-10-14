"""Phase 7: review list/show and regeneration (offline, nothing made)."""

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from content_automation.cli import app
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve
from content_automation.registry.items import create_item
from content_automation.registry.progress import part_done
from content_automation.registry.versions import revise

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def item(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("DELIVERABLES_FILE", str(REPO / "config" / "deliverables.json"))
    (isolated / "config").mkdir()
    shutil.copy(REPO / "config" / "jobs.json", isolated / "config" / "jobs.json")
    package = isolated / "packages" / "pkg"
    (package / "images").mkdir(parents=True)
    (package / "images" / "post-1.png").write_bytes(b"png")
    (package / "package.json").write_text(json.dumps({
        "packageId": "pkg", "topic": "Leads", "platform": "facebook", "formats": ["post"],
        "items": {"post": {"status": "done", "files": ["images/post-1.png"],
                           "estCostUsd": 0.04}}}), encoding="utf-8")
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    created = create_item(conn, kind="post", title="Leads", topic="Leads",
                          platforms=["facebook"], deliverable="facebook_post",
                          package_path=package.as_posix())
    approve(conn, created.id, gate="idea")
    part_done(conn, created.id)
    yield created.id
    conn.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def _conn() -> sqlite3.Connection:
    return open_registry(db_path(Path("state")), Path("config/registry.json"))


def test_review_list_and_show(item: str) -> None:
    listed = ca("review", "list")
    assert listed.exit_code == 0 and f"{item} v1 facebook_post" in listed.output
    shown = ca("review", "show", item)
    assert shown.exit_code == 0 and "images/post-1.png" in shown.output


def test_regenerate_makes_a_dry_run(item: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IMAGE_PROVIDER", "openrouter")
    conn = _conn()
    try:
        revise(conn, item, "Brighter background")
    finally:
        conn.close()
    result = ca("regenerate", item, "--only", "1")
    assert result.exit_code == 0, result.output
    assert "Dry run ID: DR-" in result.output and "--authorize" in result.output
