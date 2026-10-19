"""Phase 9 Step 2: prepare, per-platform copy, publish (offline, mock storage)."""

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner, Result

from content_automation.cli import app
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve
from content_automation.registry.items import create_item, publications
from content_automation.registry.progress import part_done

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def post(isolated: Path, monkeypatch: pytest.MonkeyPatch
         ) -> Iterator[tuple[sqlite3.Connection, str]]:
    monkeypatch.setenv("DELIVERABLES_FILE", str(REPO / "config" / "deliverables.json"))
    (isolated / "config").mkdir()
    for name in ("platforms.json", "publishing.json", "formulas.json", "content.json",
                 "storage.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    package = isolated / "packages" / "pkg"
    (package / "images").mkdir(parents=True)
    image = Image.new("RGB", (1200, 1200), (20, 60, 160))
    ImageDraw.Draw(image).rectangle((100, 100, 600, 600), fill=(230, 230, 230))
    image.save(package / "images" / "post-1.png")
    (package / "package.json").write_text(json.dumps({
        "packageId": "pkg", "topic": "Leads", "platform": "linkedin", "formats": ["post"],
        "items": {"post": {"status": "done", "files": ["images/post-1.png"]}}}),
        encoding="utf-8")
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    item = create_item(conn, kind="post", title="Leads", topic="Leads",
                       platforms=["linkedin", "facebook"], deliverable="linkedin_post",
                       package_path=package.as_posix())
    approve(conn, item.id, gate="idea")
    part_done(conn, item.id)
    approve(conn, item.id, gate="review")
    yield conn, item.id
    conn.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def _copy(path: Path, item: str) -> Path:
    texts = {"central_message": "Answer every lead", "audience": "Clinic owners",
             "purpose": "educational", "headline": "Leads warten auf *niemanden*",
             "copy": "Leads wait for nobody.\n" + " ".join(["Answer"] * 130),
             "visual_direction": "Roman at a reception desk with a phone",
             "cta": "Kostenlose Analyse buchen"}
    path.write_text(json.dumps({
        "item": item, "version": 1, "formula": "social_graphic", "language": "de",
        "sections": [{"key": k, "text": v} for k, v in texts.items()],
        "hashtags": ["#BrandedGenius", "#AI", "#Leads"]}), encoding="utf-8")
    return path


def test_prepare_copy_publish(post: tuple[sqlite3.Connection, str], tmp_path: Path) -> None:
    conn, item = post
    prepared = ca("prepare", item)
    assert prepared.exit_code == 0 and "linkedin: 1 file(s)" in prepared.output, prepared.output
    template = ca("copy", "template", item, "--platform", "linkedin")
    assert template.exit_code == 0 and "Formula social_graphic" in template.output
    for platform in ("linkedin", "facebook"):
        saved = ca("copy", "save", item, str(_copy(tmp_path / "c.json", item)),
                   "--platform", platform)
        assert saved.exit_code == 0 and "ready to publish" in saved.output, saved.output
    assert f"{item} linkedin: ready" in ca("publish", "list", "--ready").output
    missing = ca("publish", "mark", item, "--platform", "linkedin", "--url", "soon")
    assert missing.exit_code == 1 and "URL" in missing.output
    live = ca("publish", "mark", item, "--platform", "linkedin", "--url", "https://ln/p/1")
    assert live.exit_code == 0 and "published https://ln/p/1" in live.output
    failed = ca("publish", "fail", item, "Account locked", "--platform", "facebook")
    assert failed.exit_code == 0
    assert publications(conn, item) == {"facebook": "failed", "linkedin": "published"}
