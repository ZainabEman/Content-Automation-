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
    sections: list[dict[str, object]] = [
        {"key": key, "text": " ".join(["Firms"] * count)
         + (" In 2025 calls rose." if key == "ai_risk_or_mistake" else ""),
         "claimRefs": [verified] if key == "ai_risk_or_mistake" else []}
        for key, count in LENGTHS.items()]
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
             "purpose": "educational", "headline": "Leads wait for *nobody*",
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


def test_youtube_brief_validates_and_renders(conn: sqlite3.Connection, tmp_path: Path) -> None:
    video, _ = _sourced_video(conn)
    skeleton = json.loads(ca("brief", "template", video, "--json").output)["skeleton"]
    skeleton["bRoll"][0]["description"] = "Screen recording of a fake CEO call"
    skeleton["captions"]["style"] = "burned-in, two lines"
    skeleton["thumbnail"] = {"concept": "Roman with a phone", "text": "Your CEO never called"}
    skeleton["chapters"] = [{"title": c["section"].replace("_", " "), "section": c["section"]}
                            for c in skeleton["chapters"]]
    skeleton["musicMood"] = "calm, tense"
    skeleton["presenter"]["setting"] = "Office, desk, evening light"
    draft = tmp_path / "brief.json"
    draft.write_text(json.dumps(skeleton), encoding="utf-8")
    saved = ca("brief", "save", video, str(draft))
    assert saved.exit_code == 0 and "warning: no saved script for v1" in saved.output
    assert "Thumbnail: Roman with a phone" in ca("brief", "show", video).output
    skeleton["thumbnail"]["text"] = "Your CEO never called you today"
    draft.write_text(json.dumps(skeleton), encoding="utf-8")
    refused = ca("brief", "save", video, str(draft))
    assert refused.exit_code == 1 and "thumbnail.text: 6 words (at most 5)" in refused.output


def test_podcast_brief_validates_segments(conn: sqlite3.Connection, tmp_path: Path) -> None:
    episode = create_item(conn, kind="podcast", title="Voice clones", topic="t",
                          platforms=["podcast"], deliverable="podcast_episode")
    skeleton = json.loads(ca("brief", "template", episode.id, "--json").output)["skeleton"]
    for segment in skeleton["segments"]:
        segment.update({"title": segment["section"], "minutes": 3})
    skeleton.update({"showNotes": "Links and sources", "episodeTitle": "Voice clones",
                     "episodeDescription": "Why finance teams get fake calls"})
    draft = tmp_path / "brief.json"
    draft.write_text(json.dumps(skeleton), encoding="utf-8")
    saved = ca("brief", "save", episode.id, str(draft))
    assert saved.exit_code == 0, saved.output
    assert "## Segments" in ca("brief", "show", episode.id).output
    assert ca("brief", "check", episode.id).exit_code == 0


SOCIAL = {"central_message": "Answer every lead", "audience": "Clinic owners",
          "purpose": "educational", "headline": "Leads wait for *nobody*",
          "visual_direction": "Roman at a reception desk with a phone", "cta": "Book a call"}


def _post_draft(path: Path, item: str, copy: str) -> Path:
    path.write_text(json.dumps({
        "item": item, "version": 1, "formula": "social_graphic", "language": "en",
        "sections": [{"key": k, "text": v} for k, v in {**SOCIAL, "copy": copy}.items()],
        "hashtags": ["#BrandedGenius", "#AI", "#Leads"]}), encoding="utf-8")
    return path


def test_post_copy_fills_its_brief_fields_only(conn: sqlite3.Connection, tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    brief = {"topic": "Leads", "post": {"format": "statement", "headline": "Old"},
             "captions": {"facebook_post": {"hook": "keep", "takeaways": ["a", "b", "c"],
                                            "question": "keep?"}}, "cta": "Old cta"}
    (package / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
    post = create_item(conn, kind="post", title="Leads", topic="t", platforms=["linkedin"],
                       deliverable="linkedin_post", package_path=package.as_posix())
    lines = ["Leads wait for nobody.", *[" ".join(["Answer"] * 40) for _ in range(3)],
             "How fast do you answer?"]
    result = ca("script", "save", post.id, str(_post_draft(tmp_path / "p.json", post.id,
                                                            "\n".join(lines))))
    assert result.exit_code == 0, result.output
    assert "brief.json updated: post.headline, captions.linkedin_post" in result.output
    data = json.loads((package / "brief.json").read_text("utf-8"))
    assert data["post"] == {"format": "statement", "headline": "Leads wait for nobody",
                            "highlight": ["nobody"]}
    assert data["captions"]["linkedin_post"]["question"] == "How fast do you answer?"
    assert data["captions"]["facebook_post"]["hook"] == "keep" and data["cta"] == "Old cta"
    assert (package / "scripts" / post.id / "v1" / "script.md").is_file()


def test_copy_without_brief_json_stays_in_the_script(conn: sqlite3.Connection,
                                                     tmp_path: Path) -> None:
    package = tmp_path / "pkg"
    package.mkdir()
    post = create_item(conn, kind="post", title="Leads", topic="t", platforms=["linkedin"],
                       deliverable="linkedin_post", package_path=package.as_posix())
    copy = "Leads wait for nobody.\n" + " ".join(["Answer"] * 130)
    result = ca("script", "save", post.id, str(_post_draft(tmp_path / "p.json", post.id, copy)))
    assert result.exit_code == 0 and "not written yet" in result.output
    assert not (package / "brief.json").exists()
