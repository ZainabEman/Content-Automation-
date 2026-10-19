"""Phase 8 Step 2: the YouTube thumbnail (offline). The podcast parts were removed in v5."""

import json
import re
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner, Result

from content_automation.cli import app
from content_automation.content.production import start_if_ready
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve
from content_automation.registry.artifacts import add_artifact
from content_automation.registry.items import create_item

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def video(isolated: Path, monkeypatch: pytest.MonkeyPatch
          ) -> Iterator[tuple[sqlite3.Connection, str]]:
    monkeypatch.setenv("DESIGN_SYSTEM_FILE", str(REPO / "config" / "design_system.json"))
    (isolated / "config").mkdir()
    for name in ("production.json", "jobs.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    item = create_item(conn, kind="youtube", title="Stimmklone", topic="t",
                       platforms=["youtube"], deliverable="youtube_longform")
    approve(conn, item.id, gate="idea")
    folder = isolated / "briefs"
    folder.mkdir()
    (folder / "brief.json").write_text(json.dumps({
        "type": "youtube", "thumbnail": {"text": "Ihr Chef rief nie an"}}), encoding="utf-8")
    (folder / "script.json").write_text("{}", encoding="utf-8")
    add_artifact(conn, item.id, 1, "brief", (folder / "brief.json").as_posix(), {"ok": True})
    add_artifact(conn, item.id, 1, "script", (folder / "script.json").as_posix(), {"ok": True})
    start_if_ready(conn, item.id)
    yield conn, item.id
    conn.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def test_thumbnail_from_the_imported_background(video: tuple[sqlite3.Connection, str],
                                                tmp_path: Path) -> None:
    image = Image.new("RGB", (1600, 900), (20, 60, 160))
    ImageDraw.Draw(image).ellipse((200, 200, 700, 700), fill=(220, 220, 230))
    image.save(tmp_path / "bg.png")
    assert ca("import", video[1], str(tmp_path / "bg.png"), "--as", "thumbnail").exit_code == 0
    result = ca("thumbnail", video[1])
    assert result.exit_code == 0, result.output
    out = Path(re.findall(r"thumbnail (\S+thumbnail_1280x720\.png)", result.output)[0])
    with Image.open(out) as made:
        assert made.size == (1280, 720)


def test_podcast_commands_are_gone() -> None:
    """PRD R8: no podcast generation (HeyGen recording, audio export)."""
    result = ca("podcast", "--help")
    assert result.exit_code != 0
