"""Phase 6: formulas, artifacts and script templates (offline)."""

import json
import shutil
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
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


TODAY = datetime.now(UTC).date()
LENGTHS = {"hook": 80, "german_problem": 300, "ai_risk_or_mistake": 350, "why_it_happens": 300,
           "correct_ai_solution": 400, "cta_outro": 70}


def _sourced_video(conn: sqlite3.Connection) -> tuple[str, dict[str, str]]:
    """A video whose idea has a verified fact, an outdated fact and an opinion."""
    idea = create_idea(conn, "Deepfake CEO calls")
    day, old = (TODAY - timedelta(days=5)).isoformat(), (TODAY - timedelta(days=400)).isoformat()
    ids = [add_source(conn, "article", url=f"https://news.example/{n}", publisher=publisher,
                      published_at=when)[0].id
           for n, publisher, when in ((1, "heise", day), (2, "golem", day), (3, "taz", old))]
    claims = {
        "verified": add_claim(conn, idea.id, "Calls rose in 2025", "fact", ids[:2]).id,
        "outdated": add_claim(conn, idea.id, "Calls were rare", "fact", [ids[2]]).id,
        "opinion": add_claim(conn, idea.id, "It will get worse", "opinion", [ids[0]]).id,
    }
    approve(conn, idea.id, gate="idea")
    video = create_item(conn, kind="youtube", title="Deepfake CEO calls", topic="t",
                        platforms=["youtube"], parent_id=idea.id, deliverable="youtube_longform")
    return video.id, claims


def _draft(path: Path, item: str, version: int, verified: str, **changes: object) -> Path:
    sections = [{"key": key, "text": " ".join(["Firms"] * count), "claimRefs": []}
                for key, count in LENGTHS.items()]
    sections[2]["text"] += " In 2025 calls rose."
    sections[2]["claimRefs"] = [verified]
    data: dict[str, object] = {"item": item, "version": version, "formula": "youtube_longform",
                               "language": "en", "sections": sections,
                               "titleOptions": ["Deepfake calls"]}
    data.update(changes)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_valid_youtube_script_saves_v1_with_md(conn: sqlite3.Connection, tmp_path: Path) -> None:
    video, claims = _sourced_video(conn)
    result = ca("script", "save", video, str(_draft(tmp_path / "s.json", video, 1,
                                                    claims["verified"])))
    assert result.exit_code == 0, result.output
    assert "Saved v1" in result.output and "about 10 min" in result.output
    folder = Path("outputs") / "items" / video / "scripts" / "v1"
    assert json.loads((folder / "script.json").read_text("utf-8"))["durationMinutes"] == 10.0
    assert "## hook" in (folder / "script.md").read_text("utf-8")
    assert ca("script", "check", video).exit_code == 0
    assert "## cta_outro" in ca("script", "show", video).output


def test_check_refuses_with_clear_messages(conn: sqlite3.Connection, tmp_path: Path) -> None:
    video, claims = _sourced_video(conn)
    draft = _draft(tmp_path / "s.json", video, 1, claims["verified"])
    data = json.loads(draft.read_text("utf-8"))
    data["sections"] = data["sections"][:-1]  # no cta_outro
    data["sections"][0]["text"] += " 40 percent"  # a number without a verified claim
    data["sections"][1]["claimRefs"] = [claims["outdated"]]
    data["sections"][3]["claimRefs"] = [claims["opinion"]]
    draft.write_text(json.dumps(data), encoding="utf-8")
    result = ca("script", "save", video, str(draft))
    assert result.exit_code == 1 and "Not saved" in result.output
    for message in ("cta_outro: missing or empty", "hook: number without verified source",
                    f"german_problem: {claims['outdated']} is outdated",
                    f"why_it_happens: {claims['opinion']} is opinion and unverified"):
        assert message in result.output
    assert not (Path("outputs") / "items" / video / "scripts" / "v1").exists()


def test_revise_then_save_makes_v2_and_keeps_v1(conn: sqlite3.Connection,
                                                tmp_path: Path) -> None:
    video, claims = _sourced_video(conn)
    approve(conn, video, gate="idea")
    assert ca("script", "save", video,
              str(_draft(tmp_path / "a.json", video, 1, claims["verified"]))).exit_code == 0
    v1 = Path("outputs") / "items" / video / "scripts" / "v1" / "script.json"
    before = v1.read_bytes()
    revise(conn, video, "More on the Mittelstand")
    stale = ca("script", "save", video,
               str(_draft(tmp_path / "b.json", video, 1, claims["verified"])))
    assert stale.exit_code == 1 and "current version is v2" in stale.output
    again = ca("script", "save", video, str(_draft(tmp_path / "c.json", video, 2,
                                                   claims["verified"], cta="Book a call")))
    assert again.exit_code == 0 and "Saved v2" in again.output
    assert v1.read_bytes() == before and "Book a call" in ca("script", "show", video).output


def test_linkedin_copy_outside_range_fails(conn: sqlite3.Connection, tmp_path: Path) -> None:
    post = create_item(conn, kind="post", title="A post", topic="t", platforms=["linkedin"],
                       deliverable="linkedin_post")
    texts = {"central_message": "Answer every lead", "audience": "Clinic owners",
             "purpose": "educational", "headline": "Leads wait for nobody",
             "copy": "Leads wait for nobody.\n" + " ".join(["word"] * 95),
             "visual_direction": "Roman at a reception desk with a phone",
             "cta": "Book a free analysis"}
    draft = tmp_path / "post.json"
    draft.write_text(json.dumps({
        "item": post.id, "version": 1, "formula": "social_graphic", "language": "en",
        "sections": [{"key": k, "text": v} for k, v in texts.items()],
        "hashtags": ["#BrandedGenius", "#AI", "#Leads"]}), encoding="utf-8")
    result = ca("script", "save", post.id, str(draft))
    assert result.exit_code == 1 and "copy: 99 words (allowed 120-250)" in result.output
