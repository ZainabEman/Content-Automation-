"""`ca outputs migrate [--apply]` (PRD v6 R8): the old local outputs out of the way.

Everything the system generated before v6 is rejected, so the old folders and files directly
under outputs/ move unchanged into outputs/_system/rejected_legacy/, keeping their relative
paths; nothing goes into the new platform tree. A dry run by default (it lists the moves); only
--apply moves. Nothing is deleted or overwritten (a target that exists is skipped and named),
and no tracker, registry or Drive record changes: rejected items keep their BG IDs and topics,
so the duplicate check still knows them.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from content_automation.core.output_tree import (
    CATEGORY_DIRS,
    REJECTED_LEGACY,
    SYSTEM,
    YOUTUBE_DIR,
)

# the new tree's top folders (never moved)
KEEP = {SYSTEM, YOUTUBE_DIR, *(path.split("/")[0] for path in CATEGORY_DIRS.values())}


@dataclass
class Move:
    source: Path
    target: Path
    files: int


@dataclass
class MigrationPlan:
    root: Path
    moves: list[Move] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # a target that already exists

    @property
    def files(self) -> int:
        return sum(move.files for move in self.moves)


def _count(path: Path) -> int:
    return 1 if path.is_file() else sum(1 for item in path.rglob("*") if item.is_file())


def plan_migration(root: Path) -> MigrationPlan:
    """What would move: every entry directly under outputs/ that is not part of the new tree."""
    plan = MigrationPlan(root)
    if not root.is_dir():
        return plan
    legacy = root / SYSTEM / REJECTED_LEGACY
    for entry in sorted(root.iterdir(), key=lambda path: path.name.lower()):
        if entry.name in KEEP:
            continue
        target = legacy / entry.name
        if target.exists():
            plan.skipped.append(f"{entry.as_posix()}: {target.as_posix()} exists (not "
                                "overwritten)")
            continue
        plan.moves.append(Move(entry, target, _count(entry)))
    return plan


def apply_migration(plan: MigrationPlan) -> list[str]:
    """Move every planned entry (never delete, never overwrite)."""
    done: list[str] = []
    for move in plan.moves:
        if move.target.exists():
            plan.skipped.append(f"{move.source.as_posix()}: {move.target.as_posix()} exists")
            continue
        move.target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(move.source), str(move.target))
        done.append(f"moved {move.source.as_posix()} -> {move.target.as_posix()}")
    return done


def plan_lines(plan: MigrationPlan, *, applied: bool) -> list[str]:
    head = "Moved" if applied else "DRY RUN (nothing moved; add --apply)"
    lines = [f"{head}: {len(plan.moves)} folder(s)/file(s), {plan.files} file(s) in all, from "
             f"{plan.root.as_posix()}/ to {(plan.root / SYSTEM / REJECTED_LEGACY).as_posix()}/ "
             "(relative paths kept; tracker, registry and Drive unchanged)."]
    lines += [f"  {move.source.name}/ -> {SYSTEM}/{REJECTED_LEGACY}/{move.source.name}"
              f"{'/' if move.source.is_dir() else ''} ({move.files} file(s))"
              for move in plan.moves]
    lines += [f"  skipped: {line}" for line in plan.skipped]
    return lines


__all__ = ["KEEP", "MigrationPlan", "Move", "apply_migration", "plan_lines", "plan_migration"]
