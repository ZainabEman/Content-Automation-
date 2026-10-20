"""The layout variant of a new package (config/design_directions.json; Phase D step 4, v5 R5).

The category follows the part: a Facebook post = fb_single, a Facebook ad = fb_ad, a LinkedIn post
= li_single, an Instagram carousel = carousel. requires_roman (the calendar's Roman row "roman",
or a founder variant named with "as <ID>") picks among the founder variants of that category
(ids with R, Higgsfield Soul 2.0); otherwise only the variants without Roman. Rotation (R5.3):
never the variant of the previous package with the same category and platform, a carousel also
skips the one before that while another is left, and never a background treatment that the last
two packages both used, so no platform gets three near-identical images in a row. History is
package.json `direction` (stamped with the Content ID, the registry item's alias), newest first.
"as <ID>" picks a variant by hand; a founder variant is never swapped for another provider.
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

PACKAGE_KEY = "direction"  # package.json: the chosen variant's ID
DIRECTION_ID = re.compile(r"^(FB|FA|LI|CS)-R?\d+$", re.IGNORECASE)
ROMAN = "roman"
_FORMATS = {("post", "facebook"): "fb_single", ("post", "linkedin"): "li_single",
            ("ad", "facebook"): "fb_ad", ("carousel", "instagram"): "carousel"}
_AVOID = {"carousel": 2}  # how many recent variants to skip; 1 for every other category
_SAME_TREATMENT = 2  # never a treatment the last two packages both used (no 3 in a row)


def is_direction_id(value: str | None) -> bool:
    return bool(value) and DIRECTION_ID.match(str(value).strip()) is not None


def direction_format(part: str, platform: str, roman: bool = False) -> str | None:
    """The variant category of a deliverable part, None when no variant applies. Roman stays
    inside the category (a founder variant); a carousel never shows him."""
    found = _FORMATS.get((part, platform))
    if roman and found == "carousel":
        return None
    return found


def recent_directions(packages_dir: Path, catalog: DirectionCatalog, format_name: str,
                      platform: str, *, exclude: Path | None = None,
                      limit: int = 2) -> list[str]:
    """The variants of the newest packages with this category and platform, newest first."""
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


def _treatments(catalog: DirectionCatalog, recent: list[str]) -> list[str]:
    return [found.treatment for value in recent if (found := catalog.find(value)) is not None]


def pick_direction(
    catalog: DirectionCatalog,
    format_name: str,
    platform: str,
    *,
    seed: str,
    recent: list[str],
    roman_ok: bool,
    override: str | None = None,
    roman: bool = False,
) -> tuple[Direction, str]:
    """The variant and why it was chosen (one short reason for the package and dry-run line)."""
    if override and is_direction_id(override):
        chosen = catalog.get(override.strip().upper())
        if chosen.format != format_name or platform not in chosen.platforms:
            raise DirectionError(f"{chosen.id} is a {chosen.category} variant for "
                                 f"{'/'.join(chosen.platforms)}, not {format_name} on {platform}")
        if chosen.roman and not roman_ok:
            raise DirectionError(f"{chosen.id} needs Roman's image route ({chosen.provider}), "
                                 "which is not enabled; it is never swapped for another "
                                 "provider")
        return chosen, "as asked"
    options = [item for item in catalog.directions
               if item.format == format_name and platform in item.platforms
               and item.roman == roman]
    if not options:
        kind = "founder (Roman) " if roman else ""
        raise DirectionError(f"config/design_directions.json has no {kind}{format_name} variant "
                             f"for {platform}")
    usable = [item for item in options if not item.roman or roman_ok]
    if not usable:
        raise DirectionError(f"every founder {format_name} variant needs Roman's image route "
                             "(Higgsfield Soul 2.0), which is not enabled; it is never swapped "
                             "for another provider")
    avoid = recent[:_AVOID.get(format_name, 1)]
    treatments = _treatments(catalog, recent[:_SAME_TREATMENT])
    tired = treatments[0] if len(treatments) == _SAME_TREATMENT and len(set(treatments)) == 1 \
        else None
    pool = [item for item in usable if item.id not in avoid and item.treatment != tired]
    while not pool and avoid:  # too few left: relax from the oldest; never the previous one
        avoid = avoid[:-1]
        pool = [item for item in usable if item.id not in avoid and item.treatment != tired]
    if not pool:
        pool = [item for item in usable if not recent or item.id != recent[0]] or usable
    rng = random.Random(f"{format_name}|{platform}|{seed}")
    chosen = rng.choices(pool, weights=[item.weight for item in pool])[0]
    if avoid:
        reason = f"not the last {len(avoid)} on {platform}: {', '.join(avoid)}"
    elif recent and chosen.id == recent[0]:
        reason = "the only usable variant"
    else:
        reason = "first of its category" if not recent else f"rotated on {platform}"
    if tired:
        reason += f"; not a third {tired} in a row"
    if len(usable) < len(options):
        reason += "; founder variants left out (Roman's route not available)"
    return chosen, reason


__all__ = ["PACKAGE_KEY", "ROMAN", "direction_format", "is_direction_id", "pick_direction",
           "recent_directions"]
