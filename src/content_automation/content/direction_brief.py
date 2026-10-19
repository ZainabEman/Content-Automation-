"""Phase D step 8: a design direction in brief.json (template, checks) for the package build.

The template asks for exactly the chosen layout's fields (a carousel: one slide per role, in the
direction's order). The check is free and deterministic: the copy is drawn with a stand-in
picture (the same layout the build uses), so text that does not fit, a wrong item count or an
icon outside the allowed set is refused before any paid call.
"""

from __future__ import annotations

from typing import Any

from content_automation.content.brief import ContentBrief, ImageSlot
from content_automation.content.design_preview import stand_in_picture
from content_automation.content.directions import (
    Direction,
    DirectionCatalog,
    DirectionError,
    Layout,
)
from content_automation.core.config import Settings
from content_automation.references import load_brand
from content_automation.references.brand import BrandProfileError
from content_automation.workflows.design_render import (
    Assets,
    DesignRenderError,
    design_fonts,
    logo_file,
    render_layout,
    token_colors,
)
from content_automation.workflows.direction_job import direction_layout, has_picture

_LIST_ZONES = ("items", "icons")


def copy_template(layout: Layout) -> dict[str, Any]:
    """The layout's fields with the writer's hints; lists keep the fewest items asked for."""
    counts: dict[str, int] = {}
    for zone in layout.zones.values():
        if zone.kind in _LIST_ZONES:
            low = zone.count[0] if zone.count else 3
            for name in (zone.field, zone.icons_field):
                if name:
                    counts[name] = low
    template: dict[str, Any] = {}
    for name, hint in layout.fields.items():
        if name in counts:
            template[name] = [f"<{hint} ({number})>" for number in range(1, counts[name] + 1)]
        else:
            template[name] = f"<{hint}>"
    return template


def slide_roles(direction: Direction) -> list[str]:
    """The fewest slides that fill slideCount, each role within its repeat range, in order."""
    if direction.slide_count is None:
        return []
    repeats = {item.role: item.repeat[0] for item in direction.slide_roles}
    target = direction.slide_count[0]
    for item in direction.slide_roles:
        while sum(repeats.values()) < target and repeats[item.role] < item.repeat[1]:
            repeats[item.role] += 1
    return [item.role for item in direction.slide_roles for _ in range(repeats[item.role])]


def post_template(direction: Direction, *, platform: str | None, seed: str,
                  design: str) -> dict[str, Any]:
    _, layout = direction_layout(direction, platform=platform, seed=seed)
    return {"format": design, "direction": direction.id, "copy": copy_template(layout),
            "altText": "<German alt text: what the image shows and says, for screen readers>"}


def carousel_template(direction: Direction) -> dict[str, Any]:
    slides = []
    for role in slide_roles(direction):
        _, layout = direction.layout_for(role=role)
        slides.append({"directionRole": role, "copy": copy_template(layout),
                       "altText": "<what the slide shows and says, for screen readers>"})
    return {"format": "carousel", "direction": direction.id, "slides": slides}


def help_text(direction: Direction) -> dict[str, Any]:
    return {
        "direction": direction.label,
        "purpose": direction.purpose,
        "rules": ("Fill only the copy fields given, within the word limits in each hint: the "
                  "app draws them and refuses text that does not fit. *word* = accent colour, "
                  "**phrase** = bold, [[phrase]] = highlight. Icons: names from config/"
                  "design_directions.json icons. The illustration describes a place or objects "
                  "only (nothing written, no people), never the copy. Numbers only from the "
                  "cited research or brand/proof.md."),
    }


def _slot_problems(name: str, slot: ImageSlot, catalog: DirectionCatalog, platform: str,
                   seed: str, assets: Assets | None) -> list[str]:
    try:
        direction = catalog.get(str(slot.direction))
    except DirectionError as error:
        return [f"{name}.direction: {error}"]
    wanted = "carousel" if name == "carousel" else "post"
    if (direction.format == "carousel") != (wanted == "carousel"):
        return [f"{name}.direction: {direction.id} is a {direction.format} direction"]
    problems: list[str] = []
    pages: list[tuple[str, dict[str, Any], str | None]] = []
    if wanted == "post":
        if slot.slides:
            problems.append(f"{name}.slides: {direction.id} is one image; remove the slides")
        pages.append((f"{name}.copy", dict(slot.copy_text), None))
    else:
        roles = [item.role for item in direction.slide_roles]
        low, high = direction.slide_count or (1, 10)
        if not low <= len(slot.slides) <= high:
            problems.append(f"{name}.slides: {direction.id} has {low}-{high} slides, found "
                            f"{len(slot.slides)}")
        found = [slide.direction_role for slide in slot.slides]
        if found and (found[0] != roles[0] or found[-1] != roles[-1]):
            problems.append(f"{name}.slides: start with {roles[0]} and end with {roles[-1]}")
        for item in direction.slide_roles:
            used = found.count(item.role)
            if used and not item.repeat[0] <= used <= item.repeat[1]:
                problems.append(f"{name}.slides: {item.repeat[0]}-{item.repeat[1]} "
                                f"{item.role} slide(s), found {used}")
        for number, slide in enumerate(slot.slides, start=1):
            where = f"{name}.slides[{number}]"
            if slide.direction_role not in roles:
                problems.append(f"{where}.directionRole must be one of: {', '.join(roles)}")
                continue
            if not (slide.alt_text or "").strip():
                problems.append(f"{where}.altText: what the slide shows and says, for screen "
                                "readers")
            copy = dict(slide.copy_text)
            if slide.illustration and "illustration" not in copy:
                copy["illustration"] = slide.illustration
            pages.append((f"{where}.copy", copy, slide.direction_role))
    for where, copy, role in pages:
        layout_name, layout = direction_layout(direction, platform=platform, seed=seed,
                                               role=role)
        picture = has_picture(direction, layout, role)
        if (picture and direction.visual.subject == "illustration"
                and not str(copy.get("illustration") or "").strip()):
            problems.append(f"{where}.illustration: what the picture shows (a place or objects, "
                            "nothing written, no people)")
        unknown = sorted(set(copy) - set(layout.fields))
        if unknown:
            problems.append(f"{where}: {', '.join(unknown)} not in {direction.id} "
                            f"{layout_name} (fields: {', '.join(layout.fields)})")
        placeholders = [key for key, value in copy.items()
                        if "<" in str(value) and ">" in str(value)]
        if placeholders:
            problems.append(f"{where}: replace the <...> in {', '.join(placeholders)}")
            continue
        if assets is None:
            continue
        stand_in = stand_in_picture(direction, layout_name, catalog, token_colors(assets.brand),
                                    None) if picture else None
        try:
            render_layout(catalog, direction, layout_name, copy, assets, picture=stand_in)
        except DesignRenderError as error:
            problems.append(f"{where}: {error}")
    return problems


def direction_problems(brief: ContentBrief, catalog: DirectionCatalog,
                       settings: Settings) -> list[str]:
    """Every direction slot of the brief, drawn with a stand-in picture (free)."""
    slots = [(name, slot) for name in ("post", "carousel")
             if (slot := getattr(brief, name)) is not None and slot.direction]
    if not slots:
        return []
    problems: list[str] = []
    assets: Assets | None = None
    try:
        brand = load_brand(settings.references_dir)
        assets = Assets(brand=brand, logo_path=logo_file(brand, settings.references_dir),
                        fonts=design_fonts(brand))
    except (DesignRenderError, BrandProfileError, OSError) as error:
        problems.append(f"design check skipped: {error}")
    for name, slot in slots:
        problems += _slot_problems(name, slot, catalog, brief.platform, brief.topic, assets)
    return problems


__all__ = ["carousel_template", "copy_template", "direction_problems", "help_text",
           "post_template", "slide_roles"]
