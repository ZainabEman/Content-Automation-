"""Phase 8 Step 1: production status, import, handoff (offline; a tiny FFmpeg fixture)."""

import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from content_automation.cli import app
from content_automation.content.production import start_if_ready
from content_automation.core.media import run_ffmpeg
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve
from content_automation.registry.artifacts import add_artifact
from content_automation.registry.items import create_item, get_item

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def video(isolated: Path) -> Iterator[tuple[sqlite3.Connection, str]]:
    (isolated / "config").mkdir()
    shutil.copy(REPO / "config" / "production.json", isolated / "config" / "production.json")
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    item = create_item(conn, kind="youtube", title="Deepfake calls", topic="t",
                       platforms=["youtube"], deliverable="youtube_longform")
    approve(conn, item.id, gate="idea")
    folder = isolated / "outputs" / "items" / item.id / "scripts" / "v1"
    folder.mkdir(parents=True)
    for name in ("script", "brief"):
        (folder / f"{name}.json").write_text("{}", encoding="utf-8")
        (folder / f"{name}.md").write_text(f"# {name}\n", encoding="utf-8")
        add_artifact(conn, item.id, 1, name, (folder / f"{name}.json").as_posix(), {"ok": True})
    assert start_if_ready(conn, item.id) is not None
    yield conn, item.id
    conn.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def _clip(path: Path, size: str = "1920x1080") -> Path:
    run_ffmpeg(["-y", "-f", "lavfi", "-i", f"testsrc=size={size}:rate=24:duration=1",
                "-pix_fmt", "yuv420p", str(path)])
    return path


def test_import_handoff_and_set(video: tuple[sqlite3.Connection, str], tmp_path: Path) -> None:
    conn, item = video
    clip = _clip(tmp_path / "take1.mp4")
    imported = ca("import", item, str(clip), "--as", "recording")
    assert imported.exit_code == 0 and "awaiting_recording → recorded" in imported.output
    assert clip.is_file()
    handed = ca("handoff", item, "--to", "Mia")
    assert handed.exit_code == 0 and "recorded → editing" in handed.output, handed.output
    assert (Path("outputs/items") / item / "versions/v1/handoff/README.md").is_file()
    assert ca("production", "set", item, "edited").exit_code == 0
    small = ca("import", item, str(_clip(tmp_path / "small.mp4", "640x360")), "--as", "final")
    assert small.exit_code == 1 and "1080p" in small.output
    final = ca("import", item, str(_clip(tmp_path / "final.mp4")), "--as", "final")
    assert final.exit_code == 0 and "review gate is open" in final.output
    assert get_item(conn, item).generation_status == "generated"


def test_production_list_counts_finals(video: tuple[sqlite3.Connection, str]) -> None:
    listed = ca("production", "list")
    assert listed.exit_code == 0 and "youtube: 0 final of 8" in listed.output
    refused = ca("production", "set", video[1], "final")
    assert refused.exit_code == 1 and "cannot become final" in refused.output
