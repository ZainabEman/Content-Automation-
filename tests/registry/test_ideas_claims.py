"""Phase 5 Step 4: claim rules, manual topics, scoring, merge and the review queue."""

import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.registry import db_path, open_registry
from content_automation.registry.claims import add_claim, check_claims
from content_automation.registry.db import RegistryError
from content_automation.registry.ideas import (
    create_idea,
    get_details,
    list_ideas,
    merge_ideas,
    review_queue,
    score_idea,
)
from content_automation.registry.items import get_item
from content_automation.registry.sources import add_source, item_sources, link_source

REPO = Path(__file__).resolve().parents[2]
TODAY = datetime.now(UTC).date()
PILLARS = ["ai_risks", "ai_misuse"]


def _source(conn: sqlite3.Connection, n: int, publisher: str, days_ago: int = 3,
            trust: str = "secondary") -> str:
    source, _ = add_source(conn, "article", url=f"https://news.example/{n}", publisher=publisher,
                           published_at=(TODAY - timedelta(days=days_ago)).isoformat(),
                           trust=trust)  # type: ignore[arg-type]
    return source.id


def test_claim_status_follows_the_rules(registry: sqlite3.Connection) -> None:
    idea = create_idea(registry, "Deepfake CEO calls")
    heise, golem = _source(registry, 1, "heise"), _source(registry, 2, "golem")
    old = _source(registry, 3, "taz", days_ago=400)
    assert add_claim(registry, idea.id, "Calls rose", "fact", [heise]).status == "unverified"
    assert add_claim(registry, idea.id, "Calls rose", "fact", [heise, golem]).status == "verified"
    assert add_claim(registry, idea.id, "Calls rose", "fact", [old]).status == "outdated"
    assert add_claim(registry, idea.id, "Calls rose", "fact", [heise],
                     counter_ids=[golem]).status == "disputed"
    manual, _ = add_source(registry, "manual", title="a note")
    with pytest.raises(RegistryError, match="opinion needs"):
        add_claim(registry, idea.id, "It is bad", "opinion", [manual.id])
    with pytest.raises(RegistryError, match="URL and a published date"):
        add_claim(registry, idea.id, "Calls rose", "fact", [manual.id])
    later = check_claims(registry, idea.id, today=TODAY + timedelta(days=200))
    assert {claim.status for claim in later} == {"outdated"}


def test_score_merge_and_review_queue(registry: sqlite3.Connection) -> None:
    first = create_idea(registry, "Voice clones target SMEs")
    second = create_idea(registry, "Voice clone fraud at small firms")
    link_source(registry, second.id, _source(registry, 9, "BSI", trust="primary"))
    scored = score_idea(registry, first.id, pillar="ai_misuse", relevance=5, german="yes",
                        reason="fraud with AI", pillars=PILLARS)
    assert scored.score is not None and scored.score_parts["pillar"]["by"] == "assistant"
    off = score_idea(registry, second.id, pillar=None, relevance=0, german="no",
                     reason="no pillar", pillars=PILLARS)
    assert "off_strategy" in off.flags
    assert [item.id for item, _ in review_queue(registry)] == [first.id, second.id]
    merged = merge_ideas(registry, second.id, first.id)
    assert merged.duplicate_of == first.id
    assert get_item(registry, second.id).idea_status == "rejected"
    assert [s.publisher for s in item_sources(registry, first.id)] == ["BSI"]
    assert [item.id for item, _ in review_queue(registry)] == [first.id]


@pytest.fixture
def workspace(isolated: Path) -> Path:
    (isolated / "config").mkdir(exist_ok=True)
    shutil.copy(REPO / "config" / "strategy.json", isolated / "config" / "strategy.json")
    return isolated


def test_manual_topic_is_kept_verbatim_and_deduped(workspace: Path) -> None:
    runner = CliRunner()
    text = "why do German clinics trust AI triage?? (my notes)"
    added = runner.invoke(app, ["ideas", "add", text, "--assume", "audience: clinic owners"])
    assert added.exit_code == 0, added.output
    again = runner.invoke(app, ["ideas", "add", text])
    assert again.exit_code == 0 and "duplicate" in again.output
    conn = open_registry(db_path(workspace / "state"))
    try:
        ((item, details),) = list_ideas(conn)
        assert details.original_text == text
        assert details.assumptions == ("audience: clinic owners",)
        # the repeat is merged: its words are kept as a second manual note on the older idea
        assert item.kind == "idea" and len(item_sources(conn, item.id)) == 2
    finally:
        conn.close()
    listed = runner.invoke(app, ["ideas", "list"])
    assert "1 idea(s)." in listed.output


def test_claims_cli_has_no_status_option(workspace: Path) -> None:
    runner = CliRunner()
    runner.invoke(app, ["ideas", "add", "Deepfake calls"])
    refused = runner.invoke(app, ["claims", "add", "BG-001", "--text", "x", "--label", "fact",
                                  "--source", "SRC-0001", "--status", "verified"])
    assert refused.exit_code == 2
    conn = open_registry(db_path(workspace / "state"))
    try:
        assert get_details(conn, "BG-001").item_id == "BG-001"
    finally:
        conn.close()
    shown = runner.invoke(app, ["claims", "list", "BG-001"])
    assert shown.exit_code == 0 and "0 claim(s)" in shown.output
