"""The five independent statuses of an item (PRD D4, BR-11) and every allowed move, in one table.

transition() is the only judge of a status change: an illegal move raises IllegalTransition,
naming the current status and the allowed next ones, before anything is written. Some moves
have guards on the item's other statuses (PRD §14 D-10, D-19, D-22):
- idea approved -> rejected | revision_requested and rejected -> approved only while generation
  is not_started, failed or partial; once generated, decisions move to the review gate;
- generation starts (-> queued) only while the idea is approved;
- review moves only while generation is generated; a revise turns not_reviewed or approved
  into changes_requested; rejected is final;
- generation generated -> queued and review changes_requested -> not_reviewed only when a newer
  version starts generating (versions.start_new_version).
Publication is stored per platform and used from Phase 9.
"""

from dataclasses import dataclass
from typing import Literal

from content_automation.registry.db import RegistryError

Dimension = Literal["idea", "generation", "review", "upload", "publication", "production"]
Guard = Literal["idea_window", "idea_approved", "generation_generated", "new_version"]

DIMENSIONS: tuple[Dimension, ...] = ("idea", "generation", "review", "upload", "publication")
STATUSES: dict[Dimension, tuple[str, ...]] = {  # the first one is a new item's status
    "idea": ("proposed", "approved", "rejected", "revision_requested"),
    "generation": ("not_started", "queued", "running", "generated", "partial", "failed"),
    "review": ("not_reviewed", "approved", "rejected", "changes_requested"),
    "upload": ("not_uploaded", "uploading", "uploaded", "failed"),
    "publication": ("not_ready", "ready", "published", "failed"),
    # Phase 8: youtube and podcast items only (recording and editing outside the app).
    "production": ("not_started", "awaiting_recording", "recorded", "editing", "edited", "final"),
}
IDEA_WINDOW = ("not_started", "failed", "partial")  # generation statuses with an open idea gate
GUARD_TEXT: dict[Guard, str] = {
    "idea_window": "only while generation is not_started, failed or partial; once generated, "
                   "use the review gate",
    "idea_approved": "only while the idea is approved",
    "generation_generated": "only while generation is generated",
    "new_version": "only when a newer version starts generating",
}


@dataclass(frozen=True)
class Move:
    dimension: Dimension
    source: str
    target: str
    guards: tuple[Guard, ...] = ()


@dataclass(frozen=True)
class Context:
    """The item's other statuses that guards look at."""

    generation: str | None = None
    idea: str | None = None
    new_version: bool = False


def _move(dimension: Dimension, source: str, target: str, *guards: Guard) -> Move:
    return Move(dimension, source, target, guards)


TABLE: tuple[Move, ...] = (
    _move("idea", "proposed", "approved"),
    _move("idea", "proposed", "rejected"),
    _move("idea", "proposed", "revision_requested"),
    _move("idea", "revision_requested", "proposed"),
    _move("idea", "approved", "rejected", "idea_window"),
    _move("idea", "approved", "revision_requested", "idea_window"),
    _move("idea", "rejected", "approved", "idea_window"),
    _move("generation", "not_started", "queued", "idea_approved"),
    _move("generation", "queued", "running"),
    _move("generation", "running", "generated"),
    _move("generation", "running", "partial"),
    _move("generation", "running", "failed"),
    _move("generation", "failed", "queued", "idea_approved"),
    _move("generation", "partial", "queued", "idea_approved"),
    _move("generation", "generated", "queued", "idea_approved", "new_version"),
    _move("review", "not_reviewed", "approved", "generation_generated"),
    _move("review", "not_reviewed", "rejected", "generation_generated"),
    _move("review", "not_reviewed", "changes_requested", "generation_generated"),
    _move("review", "approved", "changes_requested", "generation_generated"),
    _move("review", "changes_requested", "not_reviewed", "new_version"),
    _move("upload", "not_uploaded", "uploading"),
    _move("upload", "uploading", "uploaded"),
    _move("upload", "uploading", "failed"),
    _move("upload", "failed", "uploading"),
    _move("publication", "not_ready", "ready"),
    _move("publication", "ready", "published"),
    _move("publication", "ready", "failed"),
    _move("production", "not_started", "awaiting_recording"),
    _move("production", "awaiting_recording", "recorded"),
    _move("production", "recorded", "editing"),
    _move("production", "editing", "edited"),
    _move("production", "edited", "final"),
    _move("production", "edited", "editing", "new_version"),  # back only after a revise
    _move("production", "final", "editing", "new_version"),
)


class UnknownStatus(RegistryError):
    """A status name that does not exist for its dimension."""


class IllegalTransition(RegistryError):
    """A move the table does not allow (nothing was written)."""

    def __init__(
        self, dimension: Dimension, current: str, target: str, allowed: list[str],
        why: str | None = None,
    ) -> None:
        self.dimension = dimension
        self.current = current
        self.target = target
        self.allowed = allowed
        reason = f" ({why})" if why else ""
        super().__init__(
            f"{dimension} status is {current}: it cannot become {target}{reason}. "
            f"Allowed next: {', '.join(allowed) or 'none'}."
        )


def initial(dimension: Dimension) -> str:
    return STATUSES[dimension][0]


def check_status(dimension: Dimension, status: str) -> None:
    if dimension not in STATUSES:
        raise UnknownStatus(f'Unknown status dimension "{dimension}" ({", ".join(DIMENSIONS)}).')
    if status not in STATUSES[dimension]:
        raise UnknownStatus(
            f'"{status}" is not a {dimension} status ({", ".join(STATUSES[dimension])}).'
        )


def _passes(guard: Guard, context: Context) -> bool:
    if guard == "idea_window":
        return context.generation in IDEA_WINDOW
    if guard == "idea_approved":
        return context.idea == "approved"
    if guard == "generation_generated":
        return context.generation == "generated"
    return context.new_version


def _failing(move: Move, context: Context) -> Guard | None:
    return next((guard for guard in move.guards if not _passes(guard, context)), None)


def _why(guard: Guard, context: Context) -> str:
    if guard == "idea_approved":
        state = f"; idea is {context.idea or 'unknown'}"
    elif guard == "new_version":
        state = ""
    else:
        state = f"; generation is {context.generation or 'unknown'}"
    return f"{GUARD_TEXT[guard]}{state}"


def allowed_next(
    dimension: Dimension, current: str, *, generation: str | None = None,
    idea: str | None = None, new_version: bool = False,
) -> list[str]:
    """The statuses `current` may move to now (given the item's other statuses)."""
    check_status(dimension, current)
    context = Context(generation, idea, new_version)
    return [
        move.target for move in TABLE
        if move.dimension == dimension and move.source == current
        and _failing(move, context) is None
    ]


def transition(
    dimension: Dimension, current: str, target: str, *, generation: str | None = None,
    idea: str | None = None, new_version: bool = False,
) -> str:
    """Return `target` if the move is allowed; otherwise raise IllegalTransition."""
    check_status(dimension, current)
    check_status(dimension, target)
    context = Context(generation, idea, new_version)
    allowed = allowed_next(dimension, current, generation=generation, idea=idea,
                           new_version=new_version)
    move = next(
        (move for move in TABLE
         if (move.dimension, move.source, move.target) == (dimension, current, target)),
        None,
    )
    if move is None:
        raise IllegalTransition(dimension, current, target, allowed)
    failing = _failing(move, context)
    if failing is not None:
        raise IllegalTransition(dimension, current, target, allowed, _why(failing, context))
    return target
