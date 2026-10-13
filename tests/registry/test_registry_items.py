import sqlite3
from collections.abc import Callable
from datetime import date

import pytest

from content_automation.registry.audit import list_events
from content_automation.registry.db import RegistryError
from content_automation.registry.items import Item, create_item, get_item
from content_automation.registry.versions import (
    create_version,
    get_version,
    list_versions,
    set_approved_version,
)


def test_create_item_makes_v1_and_logs(registry: sqlite3.Connection) -> None:
    item = create_item(
        registry, kind="carousel", title="WhatsApp orders for restaurants",
        topic="WhatsApp order automation", platforms=["instagram"],
        planned_date=date(2026, 10, 16), source_refs=["newsletter:2026-10-05#2"],
        package_path="outputs/content/2026-10-05_whatsapp", actor="user", command="make calendar",
    )
    assert item.id == "BG-001" and item.kind == "carousel"
    assert (item.idea_status, item.generation_status, item.review_status,
            item.upload_status) == ("proposed", "not_started", "not_reviewed", "not_uploaded")
    assert (item.current_version, item.approved_version) == (1, None)
    assert item.planned_date == date(2026, 10, 16)
    assert item.source_refs == ("newsletter:2026-10-05#2",)
    [v1] = list_versions(registry, item.id)
    assert (v1.version, v1.status, v1.reason) == (1, "active", "created")
    assert v1.package_path == "outputs/content/2026-10-05_whatsapp"
    [event] = list_events(registry, item_id=item.id)
    assert (event.type, event.version, event.actor) == ("item_created", 1, "user")
    assert event.details["kind"] == "carousel"


def test_create_item_checks_its_input(registry: sqlite3.Connection,
                                      new_item: Callable[..., Item]) -> None:
    with pytest.raises(RegistryError, match="Unknown kind"):
        new_item(kind="blog")
    with pytest.raises(RegistryError, match="needs a title"):
        new_item(title="  ")
    with pytest.raises(RegistryError, match="does not exist"):
        new_item(parent_id="BG-050")
    assert list_events(registry, types=["item_created"]) == []


def test_parent_by_alias(registry: sqlite3.Connection, new_item: Callable[..., Item]) -> None:
    parent = new_item(kind="youtube", platforms=["youtube"])
    child = new_item(kind="short", platforms=["youtube"], parent_id="bg-1")
    assert child.parent_id == parent.id


def test_create_version_keeps_v1(registry: sqlite3.Connection,
                                 new_item: Callable[..., Item]) -> None:
    item = new_item()
    v2 = create_version(registry, item.id, reason="revise", feedback="focus on Mittelstand",
                        actor="user", command="revise BG-001")
    assert (v2.version, v2.status, v2.feedback) == (2, "pending", "focus on Mittelstand")
    assert v2.package_path == item.package_path
    assert get_item(registry, item.id).current_version == 2
    assert [v.status for v in list_versions(registry, item.id)] == ["active", "pending"]
    event = list_events(registry, item_id=item.id, types=["version_created"])[0]
    assert event.version == 2 and event.details["feedback"] == "focus on Mittelstand"
    with pytest.raises(RegistryError, match="needs a reason"):
        create_version(registry, item.id, reason=" ")


def test_approved_version_is_separate(registry: sqlite3.Connection,
                                      new_item: Callable[..., Item]) -> None:
    item = new_item()
    set_approved_version(registry, item.id, 1)
    create_version(registry, item.id, reason="revise")
    after = get_item(registry, item.id)
    assert (after.current_version, after.approved_version) == (2, 1)
    set_approved_version(registry, item.id, 2)
    assert [v.status for v in list_versions(registry, item.id)] == ["superseded", "approved"]
    assert get_item(registry, item.id).approved_version == 2
    with pytest.raises(RegistryError, match="older"):
        set_approved_version(registry, item.id, 1)
    with pytest.raises(RegistryError, match="no v3"):
        get_version(registry, item.id, 3)
