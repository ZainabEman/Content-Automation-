"""Phase 7 Step 2: upload after review, the Drive plugin route, retry and costs (offline)."""

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
from content_automation.registry.items import create_item, get_item
from content_automation.registry.jobs import fail_job, load_job_config, open_job, succeed_job
from content_automation.registry.progress import part_done

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def env(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[sqlite3.Connection,
                                                                             str]]:
    monkeypatch.setenv("DELIVERABLES_FILE", str(REPO / "config" / "deliverables.json"))
    (isolated / "config").mkdir()
    for name in ("jobs.json", "storage.json", "drive_folders.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    package = isolated / "packages" / "pkg"
    (package / "images").mkdir(parents=True)
    (package / "images" / "post-1.png").write_bytes(b"png")
    (package / "package.json").write_text(json.dumps({
        "packageId": "pkg", "contentId": "2026-W45-01", "topic": "Leads",
        "platform": "facebook", "formats": ["post"],
        "items": {"post": {"status": "done", "files": ["images/post-1.png"]}}}),
        encoding="utf-8")
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    item = create_item(conn, kind="post", title="Leads", topic="Leads", platforms=["facebook"],
                       deliverable="facebook_post", package_path=package.as_posix())
    approve(conn, item.id, gate="idea")
    part_done(conn, item.id)
    yield conn, item.id
    conn.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def test_review_approve_uploads_the_version(env: tuple[sqlite3.Connection, str]) -> None:
    conn, item = env
    result = ca("item", "approve", item)
    assert result.exit_code == 0, result.output
    assert "uploaded (mock) to Facebook/2026-W45-01/v1/" in result.output
    assert get_item(conn, item).upload_status == "uploaded"


def test_plugin_route_and_drive_record(env: tuple[sqlite3.Connection, str],
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    conn, item = env
    monkeypatch.setenv("STORAGE_PROVIDER", "plugin")
    approved = ca("item", "approve", item)
    assert "upload_manifest.json" in approved.output, approved.output
    manifest = json.loads(Path("packages/pkg/upload_manifest.json").read_text("utf-8"))
    results = [{"id": entry["id"], "folder_id": f"f{n}"} if entry["kind"] == "folder" else
               {"id": entry["id"], "file_id": f"x{n}", "link": f"https://drive/x{n}"}
               for n, entry in enumerate(manifest["entries"])
               if entry["kind"] in ("folder", "file")]
    assert any(entry["kind"] == "file" for entry in manifest["entries"])
    recorded = ca("drive", "record", "packages/pkg", "--results", json.dumps(results))
    assert recorded.exit_code == 0, recorded.output
    assert f"Recorded {len(results)}" in recorded.output
    assert "0 entries left (all done)" in recorded.output
    uploads = json.loads(Path("packages/pkg/package.json").read_text("utf-8"))["uploads"]
    assert uploads["v1/images/post-1.png"]["status"] == "uploaded"


def test_jobs_retry_makes_a_dry_run(env: tuple[sqlite3.Connection, str]) -> None:
    conn, item = env
    config = load_job_config(Path("config/jobs.json"))
    job = open_job(conn, item_id=item, job_type="image", provider="openrouter",
                   inputs={"prompt": "x"}, config=config, estimate=0.04).job
    fail_job(conn, job.id, "provider timeout")
    result = ca("jobs", "retry", item)
    assert result.exit_code == 0 and "Dry run ID: DR-" in result.output, result.output


def test_costs_report_and_calibrate(env: tuple[sqlite3.Connection, str]) -> None:
    conn, item = env
    config = load_job_config(Path("config/jobs.json"))
    job = open_job(conn, item_id=item, job_type="video_scene", provider="higgsfield-plugin",
                   inputs={"slide": 1}, config=config, estimate=5).job
    succeed_job(conn, job.id, actual=4)
    report = ca("costs", "report")
    assert ("video_scene via higgsfield-plugin: 1 job(s), estimate 5 credits, actual 4"
            in report.output)
    calibrated = ca("costs", "calibrate", "--provider", "higgsfield-plugin")
    assert calibrated.exit_code == 0 and "-> 4" in calibrated.output
    assert "Nothing written" in calibrated.output
