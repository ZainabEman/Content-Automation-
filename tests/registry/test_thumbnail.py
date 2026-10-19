"""Phase 8 Step 2: thumbnail, HeyGen podcast request, podcast audio (offline)."""

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
from content_automation.core.media import run_ffmpeg
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve
from content_automation.registry.artifacts import add_artifact
from content_automation.registry.items import create_item

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def podcast(isolated: Path, monkeypatch: pytest.MonkeyPatch
            ) -> Iterator[tuple[sqlite3.Connection, str]]:
    monkeypatch.setenv("DESIGN_SYSTEM_FILE", str(REPO / "config" / "design_system.json"))
    (isolated / "config").mkdir()
    for name in ("production.json", "jobs.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    item = create_item(conn, kind="podcast", title="Voice clones", topic="t",
                       platforms=["podcast"], deliverable="podcast_episode")
    approve(conn, item.id, gate="idea")
    folder = isolated / "briefs"
    folder.mkdir()
    (folder / "brief.json").write_text(json.dumps({
        "type": "podcast", "recordingSource": "heygen", "segments": [{"minutes": 3}] * 2,
        "thumbnail": {"text": "Your CEO never called"}}), encoding="utf-8")
    (folder / "script.json").write_text("{}", encoding="utf-8")
    add_artifact(conn, item.id, 1, "brief", (folder / "brief.json").as_posix(), {"ok": True})
    add_artifact(conn, item.id, 1, "script", (folder / "script.json").as_posix(), {"ok": True})
    start_if_ready(conn, item.id)
    yield conn, item.id
    conn.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def test_thumbnail_from_the_imported_background(podcast: tuple[sqlite3.Connection, str],
                                                tmp_path: Path) -> None:
    image = Image.new("RGB", (1600, 900), (20, 60, 160))
    ImageDraw.Draw(image).ellipse((200, 200, 700, 700), fill=(220, 220, 230))
    image.save(tmp_path / "bg.png")
    assert ca("import", podcast[1], str(tmp_path / "bg.png"), "--as", "thumbnail").exit_code == 0
    result = ca("thumbnail", podcast[1])
    assert result.exit_code == 0, result.output
    out = Path(re.findall(r"thumbnail (\S+thumbnail_1280x720\.png)", result.output)[0])
    with Image.open(out) as made:
        assert made.size == (1280, 720)


def test_heygen_request_and_record(podcast: tuple[sqlite3.Connection, str],
                                   monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    item = podcast[1]
    assert "HeyGen voice ID not configured (client)" in ca("podcast", "heygen", item).output
    monkeypatch.setenv("HEYGEN_VOICE_ID", "voice-1")
    dry = ca("podcast", "heygen", item)
    assert "about 10 credits" in dry.output, dry.output
    dryrun = re.findall(r"DR-[\w-]+", dry.output)[0]
    asked = ca("podcast", "heygen", item, "--authorize", dryrun)
    assert asked.exit_code == 0 and "HeyGen request #1" in asked.output, asked.output
    run_ffmpeg(["-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=24:duration=1",
                "-pix_fmt", "yuv420p", str(tmp_path / "heygen.mp4")])
    recorded = ca("podcast", "record", "1", str(tmp_path / "heygen.mp4"), "--credits", "9")
    assert recorded.exit_code == 0 and "recording imported" in recorded.output


def test_podcast_audio_mp3(podcast: tuple[sqlite3.Connection, str], tmp_path: Path) -> None:
    wav = tmp_path / "a.wav"
    run_ffmpeg(["-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", str(wav)])
    conn, item = podcast
    add_artifact(conn, item, 1, "recording", (tmp_path / "a.wav").as_posix(), {"ok": True})
    result = ca("podcast", "audio", item)
    assert result.exit_code == 0 and "loudnorm -16 LUFS" in result.output, result.output
