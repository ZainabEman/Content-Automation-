"""The five independent statuses of an item (PRD D4, BR-11) and every allowed move, in one table.

transition() is the only judge of a status change: an illegal move raises IllegalTransition,
naming the current status and the allowed next ones, before anything is written. Some moves
depend on the generation status (idea approved <-> rejected only while generation has not
started; any review only while generation is generated) or need a new version (generation
generated -> queued). Publication is stored per platform and used from Phase 9.
"""

from dataclasses import dataclass
from typing import Literal

from content_automation.registry.db import RegistryError

Dimension = Literal["idea", "generation", "review", "upload", "publication"]
Guard = Literal["generation_not_started", "generation_generated", "new_version"]

DIMENSIONS: tuple[Dimension, ...] = ("idea", "generation", "review", "upload", "publication")
STATUSES: dict[Dimension, tuple[str, ...]] = {  # the first one is a new item's status
    "idea": ("proposed", "approved", "rejected", "revision_requested"),
    "generation": ("not_started", "queued", "running", "generated", "partial", "failed"),
    "review": ("not_reviewed", "approved", "rejected", "changes_requested"),
    "upload": ("not_uploaded", "uploading", "uploaded", "failed"),
    "publication": ("not_ready", "ready", "published", "failed"),
}
GUARD_TEXT: dict[Guard, str] = {
    "generation_not_started": "only while generation is not_started",
    "generation_generated": "only while generation is generated",
    "new_version": "only through a new version",
}


@dataclass(frozen=True)
class Move:
    dimension: Dimension
    source: str
    target: str
    guard: Guard | None = None


TABLE: tuple[Move, ...] = (
    Move("idea", "proposed", "approved"),
    Move("idea", "proposed", "rejected"),
    Move("idea", "proposed", "revision_requested"),
    Move("idea", "revision_requested", "proposed"),
    Move("idea", "approved", "rejected", "generation_not_started"),
    Move("idea", "rejected", "approved", "generation_not_started"),
    Move("generation", "not_started", "queued"),
    Move("generation", "queued", "running"),
    Move("generation", "running", "generated"),
    Move("generation", "running", "partial"),
    Move("generation", "running", "failed"),
    Move("generation", "failed", "queued"),
    Move("generation", "partial", "queued"),
    Move("generation", "generated", "queued", "new_version"),
    Move("review", "not_reviewed", "approved", "generation_generated"),
    Move("review", "not_reviewed", "rejected", "generation_generated"),
    Move("review", "not_reviewed", "changes_requested", "generation_generated"),
    Move("upload", "not_uploaded", "uploading"),
    Move("upload", "uploading", "uploaded"),
    Move("upload", "uploading", "failed"),
    Move("upload", "failed", "uploading"),
    Move("publication", "not_ready", "ready"),
    Move("publication", "ready", "published"),
    Move("publication", "ready", "failed"),
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


def _passes(guard: Guard | None, generation: str | None, new_version: bool) -> bool:
    if guard == "generation_not_started":
        return generation == "not_started"
    if guard == "generation_generated":
        return generation == "generated"
    if guard == "new_version":
        return new_version
    return True


def allowed_next(
    dimension: Dimension, current: str, *, generation: str | None = None,
    new_version: bool = False,
) -> list[str]:
    """The statuses `current` may move to now (given the item's generation status)."""
    check_status(dimension, current)
    return [
        move.target for move in TABLE
        if move.dimension == dimension and move.source == current
        and _passes(move.guard, generation, new_version)
    ]


def transition(
    dimension: Dimension, current: str, target: str, *, generation: str | None = None,
    new_version: bool = False,
) -> str:
    """Return `target` if the move is allowed; otherwise raise IllegalTransition."""
    check_status(dimension, current)
    check_status(dimension, target)
    allowed = allowed_next(dimension, current, generation=generation, new_version=new_version)
    move = next(
        (move for move in TABLE
         if (move.dimension, move.source, move.target) == (dimension, current, target)),
        None,
    )
    if move is None:
        raise IllegalTransition(dimension, current, target, allowed)
    if not _passes(move.guard, generation, new_version):
        assert move.guard is not None
        state = "" if move.guard == "new_version" else f"; generation is {generation or 'unknown'}"
        raise IllegalTransition(
            dimension, current, target, allowed, f"{GUARD_TEXT[move.guard]}{state}"
        )
    return target
