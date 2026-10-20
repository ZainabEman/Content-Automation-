"""v6 (PRD R3.5): variety without drift. A layout variant is drawn in one of several variations,
all within the approved look (R3.2):

- side: L = the text on the left (as in the references), R = mirrored (text right, visual left);
  carousels and Roman's founder variants keep their side (the carousel text is always left;
  Roman's side comes from his combination);
- panel: "panel" = the dark-navy rounded panel behind the text, "open" = the text directly on the
  dark base (only where a scrim still backs the text);
- deco: one decoration set of config/design_directions.json `decorations` (diagonal bars, a dot
  grid, a chevron row, a particle-wave mesh, thin frame lines); a decoration that would touch a
  text, the logo or the icons is left out;
- cta: "arrow" = a circle-arrow on the right, "calendar" / "play" = the icon on the left.

The variation is picked at stage 1 by rotation and stored in package.json `variation` (e.g.
"R/open/chevrons/calendar"): never one that shares more than two of its four parts with the
previous image on the platform, and never the same key twice in the last three. The layout
variant and treatment rotation (content/direction_pick.py) stays as it is.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from itertools import product
from pathlib import Path

from content_automation.content.directions import (
    Direction,
    DirectionCatalog,
    DirectionError,
    Layout,
    Zone,
    boxes_overlap,
)

PACKAGE_KEY = "variation"
SIDES = ("L", "R")
PANELS = ("panel", "open")
CTAS: dict[str, tuple[str, str]] = {"arrow": ("arrow-right", "right"),
                                    "calendar": ("calendar", "left"),
                                    "play": ("play", "left")}  # play: drawn by the app
_SWAP = {"left": "right", "right": "left"}


@dataclass(frozen=True)
class Variation:
    side: str = "L"
    panel: str = "panel"
    deco: str = "none"
    cta: str = "arrow"

    @property
    def key(self) -> str:
        return f"{self.side}/{self.panel}/{self.deco}/{self.cta}"

    @classmethod
    def parse(cls, value: str | None) -> Variation:
        parts = str(value or "").split("/")
        if len(parts) != 4 or parts[0] not in SIDES or parts[1] not in PANELS or (
                parts[3] not in CTAS):
            raise DirectionError(f'variation "{value}": side/panel/deco/cta, e.g. '
                                 '"L/panel/dots/arrow"')
        return cls(*parts)

    def shared(self, other: Variation) -> int:
        return sum(a == b for a, b in zip(self.key.split("/"), other.key.split("/"),
                                          strict=True))


def _mirror_zone(zone: Zone) -> Zone:
    left, top, right, bottom = zone.box
    update: dict[str, object] = {"box": (round(1 - right, 4), top, round(1 - left, 4), bottom)}
    if zone.align in _SWAP:
        update["align"] = _SWAP[zone.align]
    if zone.gradient is not None and zone.gradient.toward in _SWAP:
        update["gradient"] = zone.gradient.model_copy(
            update={"toward": _SWAP[zone.gradient.toward]})
    return zone.model_copy(update=update)


def can_mirror(direction: Direction) -> bool:
    return direction.format != "carousel" and not direction.roman


def apply(direction: Direction, layout: Layout, variation: Variation,
          catalog: DirectionCatalog) -> Layout:
    """The layout drawn in this variation (DirectionError when the result breaks a layout
    rule; `variations` only offers ones that pass)."""
    zones = dict(layout.zones)
    if variation.panel == "open":
        zones = {name: zone for name, zone in zones.items()
                 if not (zone.kind == "shape" and zone.shape in ("panel", "glass")
                         and not any(other.kind in ("icons", "items")
                                     and boxes_overlap(other.box, zone.box)
                                     for other in zones.values()))}
    cta = zones.get("cta")
    if cta is not None and cta.kind == "text":
        icon, side = CTAS[variation.cta]
        zones["cta"] = cta.model_copy(update={"icon": icon, "icon_side": side})
    reserved = [zone.box for zone in zones.values() if zone.reserved]
    extras = [zone for zone in catalog.decorations.get(variation.deco, [])
              if zone.shape == "frame" or not any(boxes_overlap(zone.box, box)
                                                  for box in reserved)]
    if extras:  # drawn over the picture and scrims, under the panel and every text
        first = next((index for index, zone in enumerate(zones.values())
                      if zone.kind not in ("visual",) and not (
                          zone.kind == "shape" and zone.shape in ("scrim", "glow"))),
                     len(zones))
        items = list(zones.items())
        zones = dict(items[:first] + [(f"deco{n}", zone) for n, zone in enumerate(extras)]
                     + items[first:])
    if variation.side == "R" and can_mirror(direction):
        zones = {name: _mirror_zone(zone) for name, zone in zones.items()}
        glows = [(role, round(1 - x, 4), y, r, o) for role, x, y, r, o in layout.background.glows]
        background = layout.background.model_copy(update={"glows": glows})
    else:
        background = layout.background
    varied = layout.model_copy(update={"zones": zones, "background": background})
    name = next((key for key, value in direction.layouts.items() if value is layout),
                "variation")
    catalog.check_layout(direction, name, varied)
    return varied


def variations(direction: Direction, layout: Layout, catalog: DirectionCatalog) -> list[Variation]:
    """Every valid variation of a layout."""
    sides = SIDES if can_mirror(direction) else ("L",)
    panels = PANELS if any(zone.kind == "shape" and zone.shape in ("panel", "glass")
                           for zone in layout.zones.values()) else ("panel",)
    decos = tuple(catalog.decorations) or ("none",)
    ctas = tuple(CTAS) if "cta" in layout.zones else ("arrow",)
    found: list[Variation] = []
    for side, panel, deco, cta in product(sides, panels, decos, ctas):
        variation = Variation(side, panel, deco, cta)
        try:
            apply(direction, layout, variation, catalog)
        except (DirectionError, ValueError):
            continue
        found.append(variation)
    return found or [Variation()]


def pick_variation(direction: Direction, layout: Layout, catalog: DirectionCatalog, *,
                   seed: str, recent: list[str], override: str | None = None
                   ) -> tuple[Variation, str]:
    """The variation and why (R3.5): differs from the previous one on the platform in at least
    two of its four parts and is not one of the last three."""
    if override:
        return Variation.parse(override), "as asked"
    options = variations(direction, layout, catalog)
    previous = [Variation.parse(key) for key in recent if _valid(key)]
    rng = random.Random(f"{direction.id}|{seed}")
    rng.shuffle(options)
    for option in options:
        if previous and option.shared(previous[0]) > 2:
            continue
        if option.key in {item.key for item in previous[:3]}:
            continue
        return option, (f"differs from {previous[0].key}" if previous else "first on the "
                        "platform")
    return options[0], "the only variation left"


def _valid(key: str) -> bool:
    try:
        Variation.parse(key)
    except DirectionError:
        return False
    return True


def recent_variations(packages_dir: Path, platform: str, *, exclude: Path | None = None,
                      limit: int = 3) -> list[str]:
    """package.json `variation` of the newest packages on the platform, newest first."""
    found: list[tuple[str, str]] = []
    for path in packages_dir.glob("*/package.json"):
        if exclude is not None and path.parent.resolve() == exclude.resolve():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("platform") == platform and data.get(
                PACKAGE_KEY):
            found.append((str(data.get("createdAt") or ""), str(data[PACKAGE_KEY])))
    return [value for _, value in sorted(found, reverse=True)[:limit]]


__all__ = ["CTAS", "PACKAGE_KEY", "Variation", "apply", "can_mirror", "pick_variation",
           "recent_variations", "variations"]
