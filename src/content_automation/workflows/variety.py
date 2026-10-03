"""Variety for designed graphics.

Scene, wardrobe, props, decor, hologram style and pose come from the design system's pools.
What is not given is picked from the pool, avoiding what the newest content packages used.
The same inputs and history always give the same picks, so a dry run shows what the real
run will use.
"""

import json
import random
import zlib
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, ValidationError

from content_automation.core.files import CamelModel
from content_automation.workflows.design_system import (
    DesignChoice,
    DesignSystem,
    DesignSystemError,
    FormatId,
    PoolEntry,
)
from content_automation.workflows.registry import WorkflowError

RECENT_PACKAGES = 5  # the picks of this many newest packages are avoided
RECENT_FORMATS = 3  # a suggested format differs from those of this many newest packages
PACKAGE_FILE = "package.json"
CUSTOM = "custom"  # given in the user's own words instead of a pool ID
PICK_NAMES = ("format", "scene", "wardrobe", "props", "decor", "holograms", "pose")


class DesignPicks(CamelModel):
    """What one design used from the pools; saved in details.json and package.json."""

    format: str | None = None
    scene: str | None = None
    wardrobe: str | None = None
    props: str | None = None
    decor: str | None = None
    holograms: str | None = None
    pose: str | None = None
    style_refs: list[str] = Field(default_factory=list)  # asset IDs of the style images

    @classmethod
    def from_recorded(
        cls, inputs: Mapping[str, str | bool], style_asset_ids: list[str]
    ) -> "DesignPicks":
        """Read the picks back from a job's ``inputs`` and ``styleAssetIds``."""
        values = {name: str(inputs[name]) for name in PICK_NAMES if inputs.get(name)}
        return cls(style_refs=list(style_asset_ids), **values)


@dataclass(frozen=True)
class Pick:
    id: str  # pool ID, or "custom"
    text: str  # what the prompt says


@dataclass(frozen=True)
class DesignLook:
    """The variable parts of one design; None = this design does not show that part."""

    scene: Pick | None = None
    wardrobe: Pick | None = None
    props: Pick | None = None
    decor: Pick | None = None
    holograms: Pick | None = None
    pose: Pick | None = None

    def ids(self) -> dict[str, str]:
        parts = {
            "scene": self.scene,
            "wardrobe": self.wardrobe,
            "props": self.props,
            "decor": self.decor,
            "holograms": self.holograms,
            "pose": self.pose,
        }
        return {name: pick.id for name, pick in parts.items() if pick is not None}


def recent_packages(
    packages_dir: Path, limit: int = RECENT_PACKAGES, *, exclude: Path | None = None
) -> list[list[DesignPicks]]:
    """The picks saved in the newest packages' package.json: newest first, one list each.

    exclude: a package folder to leave out (the one being built).
    """
    found: list[tuple[str, list[DesignPicks]]] = []
    skip = exclude.resolve() if exclude is not None else None
    for path in packages_dir.glob(f"*/{PACKAGE_FILE}"):
        if skip is not None and path.parent.resolve() == skip:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = data.get("items") if isinstance(data, dict) else None
        if not isinstance(items, dict):
            continue
        picks = []
        for item in items.values():
            raw = item.get("picks") if isinstance(item, dict) else None
            if isinstance(raw, dict):
                try:
                    picks.append(DesignPicks.model_validate(raw))
                except ValidationError:
                    continue
        found.append((str(data.get("createdAt", "")), picks))
    found.sort(key=lambda entry: entry[0], reverse=True)
    return [picks for _, picks in found[:limit]]


def flatten(packages: list[list[DesignPicks]]) -> list[DesignPicks]:
    return [picks for package in packages for picks in package]


def suggest_format(
    system: DesignSystem,
    packages: list[list[DesignPicks]],
    *,
    skip: Collection[str] = (),
    allowed: Collection[str] = (),
) -> FormatId:
    """The next format in the design system's order that the newest packages did not use.

    allowed: only these formats (e.g. a deliverable's rotation); empty = all.
    """
    recent = [picks.format for picks in flatten(packages[:RECENT_FORMATS]) if picks.format]
    order = [name for name in system.formats if not allowed or name in allowed]
    names: list[str] = list(order)
    start = names.index(recent[0]) + 1 if recent and recent[0] in names else 0
    rotated = order[start:] + order[:start]
    choices = [name for name in rotated if name not in skip] or rotated
    return next((name for name in choices if name not in recent), choices[0])


def _rng(seed: str) -> random.Random:
    return random.Random(zlib.crc32(seed.encode("utf-8")))


def _pick(
    pool: dict[str, PoolEntry],
    given: str | None,
    *,
    used: list[str],
    seed: str,
    fits: Callable[[PoolEntry], bool] = lambda entry: True,
) -> Pick | None:
    """The given pool entry (or the user's own words); else a fitting entry that ``used``
    (newest first) does not hold, else the fitting entry that was used longest ago."""
    wanted = (given or "").strip()
    if wanted:
        entry = pool.get(wanted)
        return Pick(wanted, entry.description) if entry else Pick(CUSTOM, wanted)
    options = [key for key, entry in pool.items() if entry.auto and fits(entry)]
    if not options:
        return None
    fresh = [key for key in options if key not in used]
    key = _rng(seed).choice(fresh) if fresh else max(options, key=used.index)
    return Pick(key, pool[key].description)


def choose_look(
    design: DesignChoice,
    system: DesignSystem,
    *,
    scene: str | None = None,
    wardrobe: str | None = None,
    props: str | None = None,
    decor: str | None = None,
    holograms: str | None = None,
    history: list[DesignPicks],
    seed: str,
) -> DesignLook:
    """Pick the variable parts this design shows; what is given is used as it is."""
    spec = system.formats[design.format]
    pools = system.pools
    layout = system.layouts[design.layout] if design.layout is not None else None
    split = layout is not None and bool(layout.split_poses)
    if wardrobe and not design.person:
        raise WorkflowError(f"{design.label} shows no person: remove --wardrobe.")
    if props and "props" not in spec.elements:
        raise WorkflowError(f"--format {design.format} shows no props: remove --props.")

    def used(name: str) -> list[str]:
        return [value for picks in history if (value := getattr(picks, name))]

    # A carousel keeps one scene for all slides, and its hook slide shows the man.
    needs_place = design.person or design.format == "carousel"
    scene_pick: Pick | None = None
    if scene or not split:  # the before/after layout describes its own two scenes
        scene_pick = _pick(
            pools.scenes, scene, used=used("scene"), seed=f"{seed}|scene",
            fits=lambda entry: entry.photo or not needs_place,
        )
        if scene_pick is None:
            raise DesignSystemError("design_system.json has no scene that can be picked.")
    place = pools.scenes.get(scene_pick.id) if scene_pick is not None else None
    photo = place.photo if place is not None else True

    def fits_scene(entry: PoolEntry) -> bool:
        return not entry.scenes or place is None or scene_pick is None or (
            scene_pick.id in entry.scenes
        )

    posed = design.person and not split
    return DesignLook(
        scene=scene_pick,
        wardrobe=(
            _pick(pools.wardrobe, wardrobe, used=used("wardrobe"), seed=f"{seed}|wardrobe")
            if design.person
            else None
        ),
        props=(
            _pick(pools.props, props, used=used("props"), seed=f"{seed}|props", fits=fits_scene)
            if "props" in spec.elements and (photo or bool(props))
            else None
        ),
        decor=(
            _pick(pools.decor, decor, used=used("decor"), seed=f"{seed}|decor")
            if "decor" in spec.elements
            else None
        ),
        holograms=(
            _pick(pools.holograms, holograms, used=used("holograms"), seed=f"{seed}|holograms")
            if "holograms" in spec.elements
            else None
        ),
        pose=(
            _pick(pools.poses, design.pose, used=used("pose"), seed=f"{seed}|pose", fits=fits_scene)
            if posed
            else None
        ),
    )
