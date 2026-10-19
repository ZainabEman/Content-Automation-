"""The graphic designer's prompt (PRD v5 R3) for the OpenRouter image of a layout variant.

The designer's own prompt stays the core (config/designer_prompts.json): an expert-designer role
and quality bar, the brand style guide and the official logo as input images, the motive and aim
of Branded Genius, creative latitude and the explicit format. Added per job: the category, the
topic, the German headline as context, the variant's picture description and its free zones (the
app draws the exact German text and pastes the real logo there afterwards, R3.5), and the
approved company graphics the variant was derived from (config/brand_refs.json).

Image inputs (R3.3), in the adapter's numbering: object_refs = 1 the style guide page (the JPEG
inside the guide PDF, cached as a smaller copy), 2 the official logo; style_refs = 3.. the
variant's approved references (at most maxReferences). Nothing from the competitor archive is
ever read. A missing input fails a paid job (it never runs without the guide, the logo or its
references); on the mock provider it is left out and named in the job record.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from PIL import Image

from content_automation.ai.image import ReferenceImage
from content_automation.content.directions import Direction, DirectionCatalog, Layout

CONFIG_FILE = Path("config/designer_prompts.json")
REFS_FILE = Path("config/brand_refs.json")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
GUIDE_LONG_SIDE = 1600  # the guide page sent to the model (the PDF's JPEG is 5475x7275)
_JPEG = re.compile(rb"/Filter\s*/DCTDecode.*?stream\r?\n", re.S)


class DesignerPromptError(ValueError):
    """The designer prompt or one of its inputs cannot be prepared."""


@dataclass
class DesignerInputs:
    prompt: str
    object_refs: list[ReferenceImage] = field(default_factory=list)  # guide, logo
    style_refs: list[ReferenceImage] = field(default_factory=list)  # approved references
    missing: list[str] = field(default_factory=list)  # inputs not found (mock only)

    def record(self) -> dict[str, str]:
        """What the job record shows: the inputs sent and the ones missing."""
        sent = [ref.source for ref in [*self.object_refs, *self.style_refs]]
        found = {"designerInputs": "; ".join(sent) or "none"}
        if self.missing:
            found["designerMissing"] = "; ".join(self.missing)
        return found


def _resolve(path: Path) -> Path:
    if not path.is_absolute() and not path.exists() and (_PROJECT_ROOT / path).exists():
        return _PROJECT_ROOT / path
    return path


@lru_cache(maxsize=4)
def _json(path: Path) -> dict[str, Any]:
    data = json.loads(_resolve(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DesignerPromptError(f"{path} must be a JSON object")
    return data


def load_templates(path: Path = CONFIG_FILE) -> dict[str, Any]:
    return _json(path)


def load_refs(path: Path = REFS_FILE) -> dict[str, Any]:
    return _json(path)


def guide_image(pdf: Path, cache_dir: Path) -> Path:
    """The style guide page as a JPEG for the model: the guide PDF is one embedded JPEG."""
    target = cache_dir / "brand_style_guide.jpg"
    if target.is_file() and target.stat().st_mtime >= pdf.stat().st_mtime:
        return target
    data = pdf.read_bytes()
    match = _JPEG.search(data)
    if match is None:
        raise DesignerPromptError(f"{pdf.name}: no embedded JPEG page found; export the guide "
                                  "as an image")
    end = data.find(b"\xff\xd9", match.end())
    if end < 0:
        raise DesignerPromptError(f"{pdf.name}: the embedded page is cut off")
    with Image.open(io.BytesIO(data[match.end():end + 2])) as page:
        image = page.convert("RGB")
    image.thumbnail((GUIDE_LONG_SIDE, GUIDE_LONG_SIDE))
    cache_dir.mkdir(parents=True, exist_ok=True)
    image.save(target, format="JPEG", quality=90)
    return target


def _where(box: tuple[float, float, float, float]) -> str:
    left, top, right, bottom = (round(value * 100) for value in box)
    return f"x {left}-{right}%, y {top}-{bottom}%"


def free_zones(layout: Layout) -> tuple[str, str]:
    """The areas the app draws on (text, icons, the logo), in shares of the image."""
    text = [f"{name} ({_where(zone.box)})" for name, zone in layout.zones.items()
            if zone.bears_text or zone.kind == "icons"]
    logo = [_where(zone.box) for zone in layout.zones.values() if zone.kind == "logo"]
    return "; ".join(text) or "none", (logo[0] if logo else "no logo on this slide")


def _ref_files(direction: Direction, references_dir: Path, limit: int,
               role: str | None) -> list[tuple[str, Path, str]]:
    refs = load_refs().get("refs", {})
    found: list[tuple[str, Path, str]] = []
    for ref_id in direction.reference_ids[:limit]:
        entry = refs.get(ref_id)
        if not isinstance(entry, dict):
            raise DesignerPromptError(f"{direction.id}: reference {ref_id} is not in "
                                      f"{REFS_FILE} (approved company references only)")
        name = str(entry.get("last") if role == "cta" and entry.get("last") else entry["file"])
        found.append((ref_id, references_dir / name, str(entry.get("use", ""))))
    return found


def designer_inputs(direction: Direction, layout: Layout, catalog: DirectionCatalog, *,
                    picture: str, topic: str, headline: str, references_dir: Path,
                    logo_path: Path | None, cache_dir: Path, mock: bool,
                    role: str | None = None) -> DesignerInputs:
    """The full prompt and its image inputs for one picture of a layout variant."""
    templates = load_templates()
    category = templates["categories"][direction.category]
    width, height = catalog.size(direction)
    zones, logo_zone = free_zones(layout)
    limit = int(templates.get("maxReferences", 3))
    refs = _ref_files(direction, references_dir, limit, role)
    missing: list[str] = []
    objects: list[ReferenceImage] = []
    guide_pdf = references_dir / str(load_refs().get("guideline", ""))
    try:
        guide = guide_image(guide_pdf, cache_dir) if guide_pdf.is_file() else None
    except (DesignerPromptError, OSError) as error:
        raise DesignerPromptError(str(error)) from None
    if guide is None:
        missing.append(f"style guide {guide_pdf}")
    else:
        objects.append(ReferenceImage(asset_id="brand-style-guide", path=guide,
                                      source=guide_pdf.name, people=False, logo=True))
    if logo_path is not None and logo_path.is_file():
        objects.append(ReferenceImage(asset_id="brand-logo", path=logo_path,
                                      source=f"official logo {logo_path.name}", people=False,
                                      logo=True))
    else:
        missing.append(f"official logo {logo_path}")
    styles = [ReferenceImage(asset_id=f"ref-{ref_id}", path=path,
                             source=f"{ref_id} {path.name}", people=None, logo=True)
              for ref_id, path, _ in refs if path.is_file()]
    missing += [f"reference {ref_id} {path}" for ref_id, path, _ in refs if not path.is_file()]
    if missing and not mock:
        raise DesignerPromptError(f"{direction.id}: the designer prompt needs its inputs; "
                                  f"missing: {'; '.join(missing)} (copy assets/reference onto "
                                  "this machine)")
    first = len(objects) + 1
    numbers = (f"images {first}-{first + len(styles) - 1}" if len(styles) > 1
               else f"image {first}" if styles else "none attached")
    uses = "; ".join(f"{ref_id}: {use}" for ref_id, path, use in refs if path.is_file()) or (
        "the dark Branded Genius look described above")
    tone = "light" if layout.theme == "light" else "dark"
    values = {
        "category": category["category"], "platform": category["platform"],
        "purpose": category["purpose"], "mission": templates["mission"],
        "logoZone": logo_zone, "references": uses, "referenceImages": numbers,
        "topic": topic.strip() or "(no topic)", "headline": headline.strip() or "(none)",
        "variant": f"{direction.id} {direction.name}", "picture": picture,
        "zones": zones, "format": direction.canvas, "size": f"{width}x{height}",
    }
    rules = str(templates["rules"]).replace("calm, dark and empty", f"calm, {tone} and empty")
    parts = [str(templates["core"]), str(templates["brief"]), rules, str(templates["format"])]
    prompt = " ".join(part.format(**values) for part in parts)
    return DesignerInputs(prompt=prompt, object_refs=objects, style_refs=styles,
                          missing=missing)


__all__ = ["CONFIG_FILE", "DesignerInputs", "DesignerPromptError", "REFS_FILE",
           "designer_inputs", "free_zones", "guide_image", "load_refs", "load_templates"]
