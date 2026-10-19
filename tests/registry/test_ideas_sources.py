"""Phase 5 Step 1: idea items, sources, configs (P5-D1..D4)."""

import sqlite3
from pathlib import Path

import pytest

from content_automation.registry.approvals import approve
from content_automation.registry.db import RegistryError
from content_automation.registry.gates import next_actions
from content_automation.registry.ideas import create_idea, get_details, update_details
from content_automation.registry.items import get_item
from content_automation.registry.sources import add_source, item_sources, link_source
from content_automation.registry.strategy import load_content, load_strategy

REPO = Path(__file__).resolve().parents[2]


def test_idea_items_use_only_the_idea_gate(registry: sqlite3.Connection) -> None:
    idea = create_idea(registry, "Deepfake calls hit German SMEs", original_text="deepfakes!!")
    assert idea.kind == "idea" and idea.shown("generation") == "—"
    assert get_details(registry, idea.id).original_text == "deepfakes!!"
    approve(registry, idea.id)
    assert [a.action for a in next_actions(get_item(registry, idea.id))] == [
        "reject", "revise", "plan"]
    details = update_details(registry, idea.id, pillar="ai_misuse", flags=["off_strategy"])
    assert details.pillar == "ai_misuse" and details.flags == ("off_strategy",)
    with pytest.raises(RegistryError, match="Unknown idea field"):
        update_details(registry, idea.id, colour="red")


def test_sources_are_unique_by_url_and_linked(registry: sqlite3.Connection) -> None:
    idea = create_idea(registry, "AI hallucinations in clinics")
    first, created = add_source(registry, "newsletter", url="https://t.co/x",
                                original_url="https://heise.de/a", publisher="heise")
    again, created_again = add_source(registry, "web", url="https://heise.de/a")
    assert first.id == "SRC-0001" and created and not created_again and again.id == first.id
    assert link_source(registry, idea.id, first.id, role="newsletter")
    assert not link_source(registry, idea.id, first.id)
    assert [s.id for s in item_sources(registry, idea.id)] == ["SRC-0001"]


def test_strategy_and_content_configs() -> None:
    strategy = load_strategy(REPO / "config" / "strategy.json")
    assert [p.key for p in strategy.pillars] == [
        "german_problems", "ai_risks", "ai_misuse", "ai_mistakes", "ai_solutions"]
    assert "mittelstand" in strategy.pillar("german_problems").keywords  # type: ignore[union-attr]
    assert abs(sum(p.target_share for p in strategy.pillars) - 1.0) < 1e-9
    content = load_content(REPO / "config" / "content.json")
    assert content.language == "de" and content.for_platform("linkedin") == "de"  # v5 R1.4
