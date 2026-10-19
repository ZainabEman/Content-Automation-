"""`ca design check` (Phase D step 7): free, deterministic checks of one rendered design.

Reads the render manifest (`<name>.json` beside `<name>.png`, written by workflows/
design_render.py) and checks: the direction and canvas size; brand compliance (every fill and
text colour is a brand.json token; the official logo by hash, its aspect kept, at least its
minimum width, no text inside its clear space); layout (texts inside the canvas, at or above
their minimum size, within their lines and characters, contrast 3:1 for large text and 4.5:1
otherwise); contact (only the website and the contact details cleared for graphics, D-4);
content (no unverified service claimed, no number without a source in the copy is a warning);
identity (Roman from the LoRA needs a recorded person check; a real photo is refused).
v5 (PRD R2.7, R4): fonts from the brand set only; texts inside the 64 px margin; a carousel
shows the logo and the website only on its last slide and never a slide number or counter
("01/07"); LinkedIn's logo sits at a side corner.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from content_automation.content.directions import DirectionCatalog, DirectionError
from content_automation.content.relevance import unverified_claims
from content_automation.references.brand import BrandProfile
from content_automation.references.services import ServiceCatalog

ASPECT_TOLERANCE = 0.01
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?\s*(?:%|x\b|€|eur\b|k\b)", re.IGNORECASE)
_COUNTER = re.compile(r"\b\d{1,2}\s*/\s*\d{1,2}\b|\b\d{1,2}\s+(?:von|of)\s+\d{1,2}\b",
                      re.IGNORECASE)
CORNER = 0.2
Box = tuple[float, float, float, float]


@dataclass
class Report:
    name: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # a Roman image via Higgsfield: each strict check's result (workflows/roman_check.py)
    checks: dict[str, str] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.errors

    def lines(self) -> list[str]:
        head = f"{'PASS' if self.passed else 'FAIL'} {self.name}"
        return ([head] + [f"  error: {item}" for item in self.errors]
                + [f"  warning: {item}" for item in self.warnings])


def _overlap(first: Box, second: Box) -> bool:
    return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and (
        second[1] < first[3])


def _official_hashes(brand: BrandProfile) -> set[str]:
    return {variant.sha256 for variant in brand.logo_variants if variant.file}


def _copy_texts(copy: Mapping[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for key, value in copy.items():
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, str) and key not in ("icons", "service_icons", "illustration"):
                found.append((f"copy.{key}", item))
    return found


def check_manifest(
    manifest: Mapping[str, Any],
    *,
    catalog: DirectionCatalog,
    brand: BrandProfile,
    services: ServiceCatalog,
    name: str = "design",
    image: Image.Image | None = None,
    person_check: str | None = None,
    official: set[str] | None = None,
) -> Report:
    """All checks of one manifest; person_check: "pass" once `ca job review --person` passed."""
    report = Report(name)
    errors, warnings = report.errors, report.warnings
    try:
        direction = catalog.get(str(manifest.get("direction")))
    except DirectionError as error:
        errors.append(str(error))
        return report
    size = tuple(manifest.get("size") or ())
    if size != catalog.size(direction):
        errors.append(f"canvas {size} is not {direction.id}'s {catalog.size(direction)}")
    if image is not None and image.size != size:
        errors.append(f"the PNG is {image.size}, the manifest says {size}")
    width, height = (int(size[0]), int(size[1])) if len(size) == 2 else (0, 0)

    tokens = set(brand.tokens.hexes()) if brand.tokens is not None else set()
    for zone, token in manifest.get("fills") or []:
        if token not in tokens:
            errors.append(f"{zone}: colour {token!r} is not a brand token")

    logo = manifest.get("logo")
    logo_zone: Box | None = None
    closing = direction.format != "carousel" or manifest.get("layout") == (
        direction.last_layout())
    if not closing and logo:
        errors.append("a carousel shows the logo only on its last slide (PRD R4)")
    if not closing and manifest.get("footer"):
        errors.append("a carousel shows the website only on its last slide (PRD R4)")
    if direction.format == "carousel":
        for text in manifest.get("texts") or []:
            if _COUNTER.search(str(text.get("text", ""))):
                errors.append(f'{text.get("zone")}: "{text.get("text")}" reads as a slide '
                              "number or counter; carousels have none (PRD R4)")
    families = brand.typography.families() if brand.typography else []
    for font in manifest.get("fonts") or []:
        if families and not any(str(font).lower().startswith(family.lower())
                                for family in families):
            errors.append(f"font {font} is not a brand font ({', '.join(families)})")
    if not logo and closing:
        errors.append("no logo: every design carries the official logo")
    elif logo:
        if logo.get("sha256") not in (official if official is not None else
                                      _official_hashes(brand)):
            errors.append(f"logo {logo.get('file')} is not the official file (brand.json "
                          "logoVariants sha256)")
        if float(logo.get("aspect_error", 1)) > ASPECT_TOLERANCE:
            errors.append(f"logo stretched: aspect off by {float(logo['aspect_error']):.1%}")
        if int(logo.get("width_px", 0)) < int(logo.get("min_width_px", 0)):
            errors.append(f"logo {logo.get('width_px')} px wide, under its minimum "
                          f"{logo.get('min_width_px')} px")
        box = [float(value) for value in logo.get("box", (0, 0, 0, 0))]
        clear = float(logo.get("clear_space_px", 0))
        ratio = brand.logo_spec.clear_space_ratio if brand.logo_spec else 0.25
        if clear + 1 < (box[3] - box[1]) * ratio:
            errors.append("logo clear space is under its ratio of the logo height")
        logo_zone = (box[0] - clear, box[1] - clear, box[2] + clear, box[3] + clear)
        if direction.format == "li_single" and width and height and not (
                (box[0] <= width * CORNER or box[2] >= width * (1 - CORNER))
                and (box[1] <= height * CORNER or box[3] >= height * (1 - CORNER))):
            errors.append("LinkedIn: the logo must sit at a side corner (PRD R3/R4)")

    for text in manifest.get("texts") or []:
        where = f"{text.get('zone')} \"{str(text.get('text', ''))[:40]}\""
        values = [float(value) for value in text.get("box") or ()]
        if len(values) != 4:
            values = [-2.0, -2.0, -2.0, -2.0]  # reported as outside the canvas
        area: Box = (values[0], values[1], values[2], values[3])
        layout = direction.layouts.get(str(manifest.get("layout")))
        zone = layout.zones.get(str(text.get("zone"))) if layout is not None else None
        bar = zone is not None and zone.kind == "footer" and zone.bleed and zone.fill is not None
        margin = catalog.margin_px * width / 1080 if width and not bar else 0
        if area[0] < -1 or area[1] < -1 or area[2] > width + 1 or area[3] > height + 1:
            errors.append(f"{where}: outside the canvas")
        elif margin and (area[0] < margin - 2 or area[2] > width - margin + 2
                         or area[1] < margin - 2 or area[3] > height - margin + 2):
            errors.append(f"{where}: inside the {catalog.margin_px} px margin")
        elif logo_zone is not None and _overlap(area, logo_zone):
            errors.append(f"{where}: inside the logo's clear space")
        for token in text.get("tokens") or []:
            if token not in tokens:
                errors.append(f"{where}: colour {token!r} is not a brand token")
        if float(text.get("contrast", 0)) < float(text.get("needed", 4.5)):
            errors.append(f"{where}: contrast {text.get('contrast')}:1, needs "
                          f"{text.get('needed')}:1")
        if int(text.get("font_px", 0)) < int(text.get("min_font_px", 0)):
            errors.append(f"{where}: {text.get('font_px')} px, under its minimum")
        if int(text.get("lines", 0)) > int(text.get("max_lines", 99)):
            errors.append(f"{where}: {text.get('lines')} lines, at most {text.get('max_lines')}")
        if len(str(text.get("text", ""))) > int(text.get("max_chars", 10_000)):
            warnings.append(f"{where}: longer than {text.get('max_chars')} characters")

    banned = [contact.value for contact in (brand.contact.email, brand.contact.phone)
              if contact is not None and not contact.on_graphics]
    texts = " ".join(str(text.get("text", "")) for text in manifest.get("texts") or [])
    for value in banned:
        if value and value in texts:
            errors.append(f"{value} is not cleared for graphics (brand.json contact, D-4)")

    copy = manifest.get("copy")
    if isinstance(copy, Mapping):
        pairs = _copy_texts(copy)
        errors.extend(unverified_claims(pairs, services))
        for where, value in pairs:
            if _NUMBER.search(value):
                warnings.append(f'{where} "{value[:40]}": a number needs its source '
                                "(research or brand/proof.md)")

    subject = direction.visual.subject
    if subject in ("roman_lora", "roman_higgsfield") and person_check != "pass":
        warnings.append("Roman (generated): the person check must pass before use (ca job "
                        "review --person pass|fail, with the identity sheet)")
    if direction.roman and manifest.get("photo"):
        errors.append(f"{Path(str(manifest['photo'])).name}: a real photo is never the final "
                      "image of Roman; he is generated (Higgsfield Soul 2.0, his saved character)")
    return report


def check_files(paths: list[Path], *, catalog: DirectionCatalog, brand: BrandProfile,
                services: ServiceCatalog, person_check: str | None = None) -> list[Report]:
    """Check every manifest given (a folder: each *.json manifest in it)."""
    manifests: list[Path] = []
    for path in paths:
        manifests += sorted(path.glob("*.json")) if path.is_dir() else [path]
    reports: list[Report] = []
    for path in manifests:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            reports.append(Report(path.name, errors=[f"unreadable manifest: {error}"]))
            continue
        if not isinstance(data, dict) or "direction" not in data:
            continue  # not a render manifest
        png = path.with_suffix(".png")
        image = None
        if png.is_file():
            with Image.open(png) as opened:
                image = opened.copy()
        report = check_manifest(data, catalog=catalog, brand=brand, services=services,
                                name=path.stem, image=image, person_check=person_check)
        if image is None:
            report.warnings.append(f"{png.name} is missing: only the manifest was checked")
        reports.append(report)
    return reports


__all__ = ["Report", "check_files", "check_manifest"]
