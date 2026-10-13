"""PRD §14 D-10 (idea reject/approve window) and D-19 (revise, resubmit, review reset)."""

import sqlite3
from collections.abc import Callable

import pytest

from content_automation.registry.audit import list_events
from content_automation.registry.db import RegistryError
from content_automation.registry.decisions import list_decisions
from content_automation.registry.items import Item, get_item, set_status
from content_automation.registry.statuses import IllegalTransition
from content_automation.registry.versions import (
    list_versions,
    resubmit,
    revise,
    start_new_version,
)


def _generate(registry: sqlite3.Connection, item: Item, end: str = "generated") -> None:
    set_status(registry, item.id, "idea", "approved")
    for status in ("queued", "running", end):
        set_status(registry, item.id, "generation", status)


@pytest.mark.parametrize("end", ["failed", "partial"])
def test_reject_and_approve_back_after_failed_or_partial_generation(
    registry: sqlite3.Connection, new_item: Callable[..., Item], end: str
) -> None:
    item = new_item()
    _generate(registry, item, end)
    assert set_status(registry, item.id, "idea", "rejected").idea_status == "rejected"
    assert set_status(registry, item.id, "idea", "approved").idea_status == "approved"


def test_no_idea_reject_once_generated(registry: sqlite3.Connection,
                                       new_item: Callable[..., Item]) -> None:
    item = new_item()
    _generate(registry, item)
    with pytest.raises(IllegalTransition, match="use the review gate"):
        set_status(registry, item.id, "idea", "rejected")
    assert get_item(registry, item.id).idea_status == "approved"


def test_revise_with_title_is_proposed_again_on_the_new_version(
    registry: sqlite3.Connection, new_item: Callable[..., Item]
) -> None:
    item = new_item(title="AI chatbots", topic="AI chatbots")
    result = revise(registry, item.id, "focus on Mittelstand",
                    title="AI chatbots for the Mittelstand", command="revise BG-001")
    after = result.item
    assert result.gate == "idea" and result.version.version == 2
    assert (after.idea_status, after.current_version) == ("proposed", 2)
    assert after.title == after.topic == "AI chatbots for the Mittelstand"
    assert [(v.version, v.status, v.feedback) for v in list_versions(registry, item.id)] == [
        (1, "active", None), (2, "pending", "focus on Mittelstand")
    ]
    [decision] = list_decisions(registry, item.id)
    assert (decision.gate, decision.action, decision.version, decision.text) == (
        "idea", "revise", 1, "focus on Mittelstand"
    )
    changes = [(e.details["from"], e.details["to"], e.version)
               for e in list_events(registry, item_id=item.id, types=["status_changed"])]
    assert changes == [("proposed", "revision_requested", 1), ("revision_requested", "proposed", 2)]


def test_revise_without_title_waits_for_resubmit(registry: sqlite3.Connection,
                                                 new_item: Callable[..., Item]) -> None:
    item = new_item()
    result = revise(registry, "BG-001", "too generic")
    assert result.item.idea_status == "revision_requested" and result.item.title == item.title
    with pytest.raises(RegistryError, match="ca item resubmit BG-001"):
        revise(registry, item.id, "and shorter")
    with pytest.raises(IllegalTransition):
        set_status(registry, item.id, "idea", "approved")
    after = resubmit(registry, item.id, "Chatbots that book dental appointments")
    assert (after.idea_status, after.current_version) == ("proposed", 2)
    assert after.title == "Chatbots that book dental appointments"
    with pytest.raises(RegistryError, match="resubmit follows a revise"):
        resubmit(registry, item.id, "Again")


def test_revise_needs_feedback_and_an_open_gate(registry: sqlite3.Connection,
                                                new_item: Callable[..., Item]) -> None:
    item = new_item()
    with pytest.raises(RegistryError, match="needs feedback"):
        revise(registry, item.id, "  ")
    with pytest.raises(RegistryError, match="review gate is not open"):
        revise(registry, item.id, "x", gate="review")
    set_status(registry, item.id, "idea", "approved")
    set_status(registry, item.id, "generation", "queued")
    with pytest.raises(RegistryError, match="nothing to revise.*in progress"):
        revise(registry, item.id, "x")
    assert len(list_versions(registry, item.id)) == 1 and list_decisions(registry, item.id) == []


def test_review_revise_from_approved(registry: sqlite3.Connection,
                                     new_item: Callable[..., Item]) -> None:
    item = new_item()
    _generate(registry, item)
    set_status(registry, item.id, "review", "approved")
    with pytest.raises(RegistryError, match="idea gate"):
        revise(registry, item.id, "x", title="New", gate="review")
    result = revise(registry, item.id, "brighter background")
    assert result.gate == "review" and result.version.status == "pending"
    after = result.item
    assert (after.review_status, after.generation_status, after.current_version) == (
        "changes_requested", "generated", 2
    )


def test_changes_requested_resets_only_when_a_newer_version_starts(
    registry: sqlite3.Connection, new_item: Callable[..., Item]
) -> None:
    item = new_item()
    _generate(registry, item)
    revise(registry, item.id, "brighter background")
    with pytest.raises(IllegalTransition, match="newer version starts generating"):
        set_status(registry, item.id, "review", "not_reviewed")
    with pytest.raises(IllegalTransition, match="newer version starts generating"):
        set_status(registry, item.id, "generation", "queued")
    after = start_new_version(registry, item.id)
    assert (after.generation_status, after.review_status) == ("queued", "not_reviewed")
    assert [v.status for v in list_versions(registry, item.id)] == ["active", "active"]
    with pytest.raises(RegistryError, match="no newer version waiting"):
        start_new_version(registry, item.id)


def test_review_rejected_is_final(registry: sqlite3.Connection,
                                  new_item: Callable[..., Item]) -> None:
    item = new_item()
    _generate(registry, item)
    set_status(registry, item.id, "review", "rejected")
    with pytest.raises(RegistryError, match="Review rejected is final"):
        revise(registry, item.id, "try again")
    for target in ("not_reviewed", "approved", "changes_requested"):
        with pytest.raises(IllegalTransition, match="Allowed next: none"):
            set_status(registry, item.id, "review", target)
    with pytest.raises(RegistryError, match="no newer version waiting"):
        start_new_version(registry, item.id)
