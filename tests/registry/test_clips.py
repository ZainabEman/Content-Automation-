"""Phase 9 Step 1: Opus Pro clips as a manual provider (offline, a tiny FFmpeg fixture)."""

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from content_automation.cli import app
from content_automation.core.media import run_ffmpeg
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve
from content_automation.registry.artifacts import add_artifact
from content_automation.registry.items import create_item, get_item, set_status
from content_automation.registry.progress import part_done

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def video(isolated: Path) -> Iterator[tuple[sqlite3.Connection, str]]:
    (isolated / "config").mkdir()
    shutil.copy(REPO / "config" / "clips.json", isolated / "config" / "clips.json")
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    item = create_item(conn, kind="youtube", title="Deepfake calls", topic="t",
                       platforms=["youtube"], deliverable="youtube_longform")
    approve(conn, item.id, gate="idea")
    for status in ("awaiting_recording", "recorded", "editing", "edited", "final"):
        set_status(conn, item.id, "production", status)
    part_done(conn, item.id)
    approve(conn, item.id, gate="review")
    (isolated / "final.mp4").write_bytes(b"video")
    add_artifact(conn, item.id, 1, "final", (isolated / "final.mp4").as_posix(), {"ok": True})
    yield conn, item.id
    conn.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def test_clips_handoff_import_select(video: tuple[sqlite3.Connection, str],
                                     tmp_path: Path) -> None:
    conn, item = video
    handoff = ca("clips", "handoff", item)
    assert handoff.exit_code == 0 and "10-12 candidates, 9:16" in handoff.output
    folder = tmp_path / "opus"
    folder.mkdir()
    run_ffmpeg(["-y", "-f", "lavfi", "-i", "testsrc=size=180x320:rate=10:duration=16",
                "-pix_fmt", "yuv420p", str(folder / "c1.mp4")])
    for n in range(2, 6):
        shutil.copy(folder / "c1.mp4", folder / f"c{n}.mp4")
    imported = ca("clips", "import", item, str(folder))
    assert imported.exit_code == 0 and "Candidate 5" in imported.output, imported.output
    selected = ca("clips", "select", item, "1", "2", "3", "4")
    assert selected.exit_code == 0 and "rejected (not selected)" in selected.output
    assert get_item(conn, "BG-002").idea_status == "approved"
    assert get_item(conn, "BG-006").idea_status == "rejected"
