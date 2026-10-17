"""Phase D step 4: the design direction of a new package (config/design_directions.json).

The format follows the part: a Facebook post = fb_single, a LinkedIn post = li_single, an
Instagram carousel = carousel; the calendar's Roman row ("roman") = founder on LinkedIn or
Facebook. Rotation: never the direction of the previous package with the same format and
platform; a carousel also skips the one before that while another direction is left. History is
package.json `direction` (stamped with the Content ID, the registry item's alias), newest first.
"as <ID>" picks a direction by hand; founder directions that need Roman's LoRA are left out when
the comfyui provider is not set up, never swapped for another provider.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

from content_automation.content.directions import (
    Direction,
    DirectionCatalog,
    DirectionError,
)

PACKAGE_KEY = "direction"  # package.json: the chosen direction's ID
DIRECTION_ID = re.compile(r"^(FB|LI|CS|FD)-\d+$", re.IGNORECASE)
ROMAN = "roman"
_FORMATS = {("post", "facebook"): "fb_single", ("post", "linkedin"): "li_single",
            ("carousel", "instagram"): "carousel"}
_AVOID = {"carousel": 2}  # how many recent directions to skip; 1 for every other format


def is_direction_id(value: str | None) -> bool:
    return bool(value) and DIRECTION_ID.match(str(value).strip()) is not None


def direction_format(part: str, platform: str, roman: bool = False) -> str | None:
    """The direction format of a deliverable part, None when no direction applies."""
    if roman:
        return "founder" if part == "post" and platform in ("linkedin", "facebook") else None
    return _FORMATS.get((part, platform))


def recent_directions(packages_dir: Path, catalog: DirectionCatalog, format_name: str,
                      platform: str, *, exclude: Path | None = None,
                      limit: int = 2) -> list[str]:
    """The directions of the newest packages with this format and platform, newest first."""
    found: list[tuple[str, str]] = []
    for path in packages_dir.glob("*/package.json"):
        if exclude is not None and path.parent.resolve() == exclude.resolve():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or data.get("platform") != platform:
            continue
        chosen = catalog.find(str(data.get(PACKAGE_KEY) or ""))
        if chosen is not None and chosen.format == format_name:
            found.append((str(data.get("createdAt") or ""), chosen.id))
    return [value for _, value in sorted(found, reverse=True)[:limit]]


def pick_direction(
    catalog: DirectionCatalog,
    format_name: str,
    platform: str,
    *,
    seed: str,
    recent: list[str],
    lora_ok: bool,
    override: str | None = None,
) -> tuple[Direction, str]:
    """The direction and why it was chosen (one short reason for the package and dry-run line)."""
    if override and is_direction_id(override):
        chosen = catalog.get(override.strip().upper())
        if chosen.format != format_name or platform not in chosen.platforms:
            raise DirectionError(f"{chosen.id} is a {chosen.format} direction for "
                                 f"{'/'.join(chosen.platforms)}, not {format_name} on {platform}")
        if chosen.provider == "comfyui" and not lora_ok:
            raise DirectionError(f"{chosen.id} needs Roman's LoRA (comfyui), which is not set up; "
                                 "it is never swapped for another provider")
        return chosen, "as asked"
    options = [item for item in catalog.directions
               if item.format == format_name and platform in item.platforms]
    if not options:
        raise DirectionError(f"config/design_directions.json has no {format_name} direction "
                             f"for {platform}")
    usable = [item for item in options if item.provider != "comfyui" or lora_ok]
    if not usable:
        raise DirectionError(f"every {format_name} direction needs Roman's LoRA (comfyui), "
                             "which is not set up; it is never swapped for another provider")
    avoid = recent[:_AVOID.get(format_name, 1)]
    pool = [item for item in usable if item.id not in avoid]
    while not pool and avoid:  # too few left: relax from the oldest; never the previous one
        avoid = avoid[:-1]
        pool = [item for item in usable if item.id not in avoid]
    if not pool:
        pool = usable
    rng = random.Random(f"{format_name}|{platform}|{seed}")
    chosen = rng.choices(pool, weights=[item.weight for item in pool])[0]
    if avoid:
        reason = f"not the last {len(avoid)} on {platform}: {', '.join(avoid)}"
    elif recent and chosen.id == recent[0]:
        reason = "the only usable direction"
    else:
        reason = "first of its format" if not recent else f"rotated on {platform}"
    if len(usable) < len(options):
        reason += "; LoRA directions left out (comfyui not set up)"
    return chosen, reason


__all__ = ["PACKAGE_KEY", "ROMAN", "direction_format", "is_direction_id", "pick_direction",
           "recent_directions"]
