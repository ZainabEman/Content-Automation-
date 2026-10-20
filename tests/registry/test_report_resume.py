"""Phase 10 Step 1: `ca report month` and `ca jobs resume --all` (offline)."""

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from content_automation.cli import app
from content_automation.content.distribution import mark_published
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve
from content_automation.registry.auth import legacy_authorization
from content_automation.registry.items import Item, create_item, set_status
from content_automation.registry.jobs import fail_job, load_job_config, open_job
from content_automation.registry.progress import part_done, set_upload


@pytest.fixture
def conn(isolated: Path) -> Iterator[sqlite3.Connection]:
    (isolated / "config").mkdir()
    opened = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield opened
    opened.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def _approved(conn: sqlite3.Connection, **fields: object) -> Item:
    item = create_item(conn, **{"title": "Leads", "topic": "Leads", **fields})  # type: ignore[arg-type]
    approve(conn, item.id, gate="idea")
    if item.kind in ("youtube", "podcast"):
        for status in ("awaiting_recording", "recorded", "editing", "edited", "final"):
            set_status(conn, item.id, "production", status)
    part_done(conn, item.id)
    if item.kind != "podcast":
        approve(conn, item.id, gate="review")
    return item


def test_report_month_counts_recorded_finals(conn: sqlite3.Connection, isolated: Path) -> None:
    month = datetime.now(UTC).strftime("%Y-%m")
    video = _approved(conn, kind="youtube", platforms=["youtube"])
    clip = _approved(conn, kind="short", platforms=["tiktok"], parent_id=video.id)
    post = _approved(conn, kind="post", platforms=["linkedin"])
    mock = _approved(conn, kind="post", platforms=["linkedin"])
    set_upload(conn, mock.id, "uploaded", "mock")
    set_status(conn, post.id, "publication", "ready", platform="linkedin")
    mark_published(conn, post.id, "linkedin", "https://ln/p/1")

    result = ca("report", "month", month)
    assert result.exit_code == 0, result.output
    out = result.output
    assert "YouTube finals (review approved): 1 of 8" in out
    assert "Clips selected and approved: 1 of 32–40" in out
    assert "Graphics approved (posts, carousels, ads): 1 of 30–60" in out
    assert "Podcast" not in out  # v5: podcasts removed (PRD R8)
    assert f"Published on linkedin: 1 ({post.id} https://ln/p/1)" in out
    assert "Published with an approved review: 1 of 1 (100%), target 100%" in out
    assert f"Mock (not counted): 1 ({mock.id} post: mock upload)" in out
    assert (isolated / "outputs" / "_system" / "reports" / f"{month}.md").is_file()
    data = json.loads(ca("report", "month", month, "--json").output)
    assert [row["count"] for row in data["rows"]] == [1, 1, 1] and clip.id in str(data)
    assert ca("report", "month", "2026-13").exit_code == 1


def test_resume_all(conn: sqlite3.Connection, isolated: Path) -> None:
    config = load_job_config(Path("config/jobs.json"))
    post = create_item(conn, kind="post", title="Leads", topic="Leads",
                       platforms=["linkedin"], package_path="packages/pkg")
    auth = legacy_authorization(conn, post.id, "openrouter", "usd", 1.0, "test")
    image = open_job(conn, item_id=post.id, job_type="image", provider="openrouter",
                     inputs={"prompt": "p"}, config=config, estimate=0.1).job
    failed = open_job(conn, item_id=post.id, job_type="upload", provider="drive",
                      inputs={"file": "a.png", "folder": "linkedin/BG-1/v1/"}, config=config).job
    fail_job(conn, failed.id, "network")
    queued = open_job(conn, item_id=post.id, job_type="upload", provider="drive",
                      inputs={"file": "b.png", "folder": "linkedin/BG-1/v1/"}, config=config).job
    odd = open_job(conn, item_id=post.id, job_type="caption", provider="local",
                   inputs={}, config=config).job

    result = ca("jobs", "resume", "--all")
    assert result.exit_code == 0, result.output
    out = result.output
    assert f"#{image.id} {post.id} image" in out and f"authorization #{auth.id} open" in out
    assert 'uv run ca content build "packages/pkg"' in out
    assert f"#{failed.id} {post.id} upload failed: re-queued as Upload request #" in out
    assert f"#{queued.id} {post.id} upload via drive: queued: plugin request" in out
    assert f"#{odd.id} {post.id} caption via local: queued: needs manual action" in out
    assert len(list((isolated / "state" / "uploads").glob("*.json"))) == 1
    assert ca("jobs", "resume", post.id, "--all").exit_code == 2
