import sqlite3
from collections.abc import Callable

import pytest

from content_automation.registry.audit import list_events
from content_automation.registry.db import RegistryError
from content_automation.registry.items import Item, get_item, publications, set_status
from content_automation.registry.statuses import (
    GUARD_TEXT,
    STATUSES,
    TABLE,
    Dimension,
    Guard,
    IllegalTransition,
    Move,
    UnknownStatus,
    allowed_next,
    initial,
    transition,
)

ALLOWED = {(move.dimension, move.source, move.target) for move in TABLE}
ILLEGAL = [
    (dimension, source, target)
    for dimension, names in STATUSES.items()
    for source in names
    for target in names
    if (dimension, source, target) not in ALLOWED
]


def _context(move: Move) -> dict[str, str | bool | None]:
    """The other statuses under which a guarded move passes."""
    generation = ("not_started" if "idea_window" in move.guards
                  else "generated" if "generation_generated" in move.guards else None)
    return {"generation": generation,
            "idea": "approved" if "idea_approved" in move.guards else None,
            "new_version": "new_version" in move.guards}


def _breaking(move: Move, guard: Guard) -> dict[str, str | bool | None]:
    """The move's passing context with only `guard` failing."""
    context = _context(move)
    if guard == "idea_window":
        context["generation"] = "generated"
    elif guard == "generation_generated":
        context["generation"] = "queued"
    elif guard == "idea_approved":
        context["idea"] = "proposed"
    else:
        context["new_version"] = False
    return context


def test_table_matches_prd_d4_and_section_14() -> None:
    d4 = {
        ("idea", "proposed", "approved"), ("idea", "proposed", "rejected"),
        ("idea", "proposed", "revision_requested"), ("idea", "revision_requested", "proposed"),
        ("idea", "approved", "rejected"), ("idea", "rejected", "approved"),
        ("idea", "approved", "revision_requested"),
        ("generation", "not_started", "queued"), ("generation", "queued", "running"),
        ("generation", "running", "generated"), ("generation", "running", "partial"),
        ("generation", "running", "failed"), ("generation", "failed", "queued"),
        ("generation", "partial", "queued"), ("generation", "generated", "queued"),
        ("review", "not_reviewed", "approved"), ("review", "not_reviewed", "rejected"),
        ("review", "not_reviewed", "changes_requested"),
        ("review", "approved", "changes_requested"),
        ("review", "changes_requested", "not_reviewed"),
        ("upload", "not_uploaded", "uploading"), ("upload", "uploading", "uploaded"),
        ("upload", "uploading", "failed"), ("upload", "failed", "uploading"),
        ("publication", "not_ready", "ready"), ("publication", "ready", "published"),
        ("publication", "ready", "failed"),
    }
    assert d4 == ALLOWED
    assert [initial(d) for d in STATUSES] == [
        "proposed", "not_started", "not_reviewed", "not_uploaded", "not_ready"
    ]


@pytest.mark.parametrize("move", TABLE, ids=lambda m: f"{m.dimension}:{m.source}->{m.target}")
def test_every_allowed_move(move: Move) -> None:
    context = _context(move)
    assert transition(move.dimension, move.source, move.target,
                      **context) == move.target  # type: ignore[arg-type]
    assert move.target in allowed_next(move.dimension, move.source,
                                       **context)  # type: ignore[arg-type]


@pytest.mark.parametrize(("dimension", "source", "target"), ILLEGAL,
                         ids=lambda v: str(v))
def test_every_illegal_move(dimension: Dimension, source: str, target: str) -> None:
    with pytest.raises(IllegalTransition) as raised:
        transition(dimension, source, target, generation="not_started", idea="approved",
                   new_version=True)
    message = str(raised.value)
    assert f"is {source}" in message and f"cannot become {target}" in message
    expected = allowed_next(dimension, source, generation="not_started", idea="approved",
                            new_version=True)
    assert raised.value.allowed == expected
    assert f"Allowed next: {', '.join(expected) or 'none'}." in message


@pytest.mark.parametrize(("move", "guard"), [(m, g) for m in TABLE for g in m.guards],
                         ids=lambda v: v if isinstance(v, str) else f"{v.source}->{v.target}")
def test_guarded_moves_refused_without_their_condition(move: Move, guard: Guard) -> None:
    with pytest.raises(IllegalTransition, match=GUARD_TEXT[guard].split(";")[0]):
        transition(move.dimension, move.source, move.target,
                   **_breaking(move, guard))  # type: ignore[arg-type]


def test_unknown_status_names_the_valid_ones() -> None:
    with pytest.raises(UnknownStatus, match="proposed, approved"):
        transition("idea", "proposed", "done")


def test_set_status_writes_and_logs(new_item: Callable[..., Item],
                                    registry: sqlite3.Connection) -> None:
    item = new_item()
    changed = set_status(registry, item.id, "idea", "approved", actor="user",
                         command="approve BG-001")
    assert changed.idea_status == "approved"
    event = list_events(registry, item_id=item.id, types=["status_changed"])[-1]
    assert event.details == {"dimension": "idea", "from": "proposed", "to": "approved"}
    assert event.actor == "user" and event.command == "approve BG-001"


def test_illegal_set_status_writes_nothing(new_item: Callable[..., Item],
                                           registry: sqlite3.Connection) -> None:
    item = new_item()
    before = list_events(registry)
    with pytest.raises(IllegalTransition, match="Allowed next: none"):
        set_status(registry, item.id, "generation", "generated")
    with pytest.raises(IllegalTransition, match="the idea is approved; idea is proposed"):
        set_status(registry, item.id, "generation", "queued")
    with pytest.raises(IllegalTransition, match="only while generation is generated"):
        set_status(registry, item.id, "review", "approved")
    assert get_item(registry, item.id) == item
    assert list_events(registry) == before


def test_reject_after_generation_started_is_refused(new_item: Callable[..., Item],
                                                    registry: sqlite3.Connection) -> None:
    item = new_item()
    set_status(registry, item.id, "idea", "approved")
    set_status(registry, item.id, "generation", "queued")
    with pytest.raises(IllegalTransition, match="generation is queued"):
        set_status(registry, item.id, "idea", "rejected")
    assert get_item(registry, item.id).idea_status == "approved"


def test_generated_needs_a_new_version_to_queue_again(new_item: Callable[..., Item],
                                                      registry: sqlite3.Connection) -> None:
    item = new_item()
    set_status(registry, item.id, "idea", "approved")
    for status in ("queued", "running", "generated"):
        set_status(registry, item.id, "generation", status)
    with pytest.raises(IllegalTransition, match="only when a newer version starts generating"):
        set_status(registry, item.id, "generation", "queued")
    assert set_status(registry, item.id, "generation", "queued",
                      new_version=True).generation_status == "queued"


def test_publication_is_per_platform(new_item: Callable[..., Item],
                                     registry: sqlite3.Connection) -> None:
    item = new_item(platforms=["LinkedIn", "facebook"])
    set_status(registry, item.id, "publication", "ready", platform="linkedin")
    assert publications(registry, item.id) == {"facebook": "not_ready", "linkedin": "ready"}
    with pytest.raises(RegistryError, match="not planned for instagram"):
        set_status(registry, item.id, "publication", "ready", platform="instagram")
    with pytest.raises(RegistryError, match="needs the platform"):
        set_status(registry, item.id, "publication", "ready")
