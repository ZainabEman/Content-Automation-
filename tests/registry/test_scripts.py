"""Phase 6: formulas, artifacts and script templates (offline)."""

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
from content_automation.registry.artifacts import add_artifact, list_artifacts
from content_automation.registry.claims import add_claim
from content_automation.registry.ideas import create_idea
from content_automation.registry.items import create_item
from content_automation.registry.sources import add_source
from content_automation.registry.versions import revise

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def conn(isolated: Path) -> Iterator[sqlite3.Connection]:
    (isolated / "config").mkdir()
    for name in ("formulas.json", "content.json", "strategy.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    connection = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield connection
    connection.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def _video(conn: sqlite3.Connection) -> str:
    idea = create_idea(conn, "Deepfake CEO calls")
    source, _ = add_source(conn, "article", url="https://heise.de/a", publisher="heise",
                           published_at="2026-10-10")
    add_claim(conn, idea.id, "Deepfake calls hit firms", "fact", [source.id])
    approve(conn, idea.id, gate="idea")
    video = create_item(conn, kind="youtube", title="Deepfake CEO calls", topic="t",
                        platforms=["youtube"], parent_id=idea.id,
                        deliverable="youtube_longform")
    approve(conn, video.id, gate="idea")
    return video.id


def test_template_has_sections_claims_and_feedback(conn: sqlite3.Connection) -> None:
    video = _video(conn)
    revise(conn, video, "Shorter hook, more on the Mittelstand")
    result = ca("script", "template", video, "--json")
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["formula"] == "youtube_longform" and data["version"] == 2
    assert [s["key"] for s in data["skeleton"]["sections"]][:2] == ["hook", "german_problem"]
    assert data["totalWords"] == [1200, 1800] and data["claims"][0]["status"] == "unverified"
    assert data["feedback"] == "Shorter hook, more on the Mittelstand"
    assert data["storesIn"].endswith(f"items/{video}/scripts/v2")


def test_every_formula_has_a_template(conn: sqlite3.Connection) -> None:
    for kind, deliverable, platform in (("podcast", "podcast_episode", "podcast"),
                                        ("post", "linkedin_post", "linkedin"),
                                        ("carousel", "instagram_carousel", "instagram"),
                                        ("ad", "facebook_ad", "facebook")):
        item = create_item(conn, kind=kind, title=f"A {kind}", topic="t", platforms=[platform],
                           deliverable=deliverable)
        result = ca("script", "template", item.id)
        assert result.exit_code == 0 and "Claims: none" in result.output, result.output


def test_shorts_have_no_formula_and_artifacts_are_logged(conn: sqlite3.Connection) -> None:
    short = create_item(conn, kind="short", title="A short", topic="t",
                        deliverable="youtube_short")
    result = ca("script", "template", short.id)
    assert result.exit_code == 2 and "Phase 9" in result.output
    saved = add_artifact(conn, short.id, 1, "script", "x/script.json", {"ok": True})
    assert list_artifacts(conn, short.id) == [saved]
