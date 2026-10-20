"""The graphic designer's prompt (PRD v6 R3.3/R3.4) for the OpenRouter image of a layout variant.

The designer's own prompt (brand/designer_prompt.md, verbatim) stays the core, adapted to the
category's platform and format (config/designer_prompts.json designerAdapt). Two modes:

- designer (the default for non-Roman feed posts, ads, LinkedIn and carousel slides): the model
  draws the whole ad, including the exact German headline, body, CTA and labels (quoted in the
  prompt, their places in words), with the R3.2 look in words and explicit negatives. Image
  inputs, in the adapter's numbering: object_refs = 1 the colour section of the style guide
  (cropped from the JPEG inside the guide PDF: never its logo or type specimen, which v5 images
  copied); style_refs = 2.. the variant's approved references with their logos masked (at most
  maxReferences). The logo file is never sent (2026-10-21: models drew wordmarks after seeing
  it), and the prompt names no logo, wordmark or brand outside its negatives
  (`check_brand_free`); the logo corner is described as plain empty dark space. The app places
  the real logo afterwards and reads the text back (workflows/text_reader.py).
- composite (the fallback after the designer attempts): the model draws only the scene, with the
  text side dark and empty, and gets no image inputs at all; the app draws everything else.

Zones are described in words (the left half, the top-right corner), never as coordinates: v5's
"x 6-34%, y 47-60%" reached the images. `check_clean` refuses any prompt that still carries one.
Nothing from the competitor archive is ever read. A missing input fails a paid designer job; on the
mock provider it is left out and named in the job record.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from PIL import Image

from content_automation.ai.image import ReferenceImage
from content_automation.content.directions import Direction, DirectionCatalog, Layout

CONFIG_FILE = Path("config/designer_prompts.json")
REFS_FILE = Path("config/brand_refs.json")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
GUIDE_LONG_SIDE = 1600  # the guide page sent to the model (the PDF's JPEG is 5475x7275)
_JPEG = re.compile(rb"/Filter\s*/DCTDecode.*?stream\r?\n", re.S)
# what must never reach an image-model prompt (outside the quoted copy): coordinates, shares
_COORDINATES = re.compile(r"\b[xy]\s*[:=]?\s*\d|\d+(?:[.,]\d+)?\s*%|\b\d+(?:\.\d+)?\s*[-–]\s*"
                          r"\d+(?:\.\d+)?\b(?!\s*(?:px|x\d))|\b(?:zone|box)\s*\d",
                          re.IGNORECASE)
Mode = Literal["designer", "composite"]
# what never reaches an image prompt outside its negatives: the logo, a wordmark, the brand's name
_BRAND = re.compile(r"\blogos?\b|wordmark|brand(?:ed|it)\s*genius|brandedgenius|\bgenius\b",
                    re.IGNORECASE)
TEXT_ZONE_ORDER = ("eyebrow", "number", "headline", "sub", "body", "tagline", "badge", "cta")


class DesignerPromptError(ValueError):
    """The designer prompt or one of its inputs cannot be prepared."""


@dataclass
class DesignerInputs:
    prompt: str
    object_refs: list[ReferenceImage] = field(default_factory=list)  # guide colours, logo
    style_refs: list[ReferenceImage] = field(default_factory=list)  # masked references
    missing: list[str] = field(default_factory=list)  # inputs not found (mock only)
    mode: Mode = "designer"
    texts: list[str] = field(default_factory=list)  # designer mode: the strings the model writes

    def record(self) -> dict[str, str]:
        """What the job record shows: the mode, the inputs sent and the ones missing."""
        sent = [ref.source for ref in [*self.object_refs, *self.style_refs]]
        found = {"designMode": self.mode, "designerInputs": "; ".join(sent) or "none"}
        if self.texts:
            found["designerTexts"] = json.dumps(self.texts, ensure_ascii=False)
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


def default_mode() -> Mode:
    return "composite" if load_templates().get("mode") == "composite" else "designer"


def designer_text(platform: str, canvas: str) -> str:
    """The designer's own prompt (brand/designer_prompt.md), adapted to platform and format."""
    templates = load_templates()
    source = _resolve(Path(str(templates.get("designerPromptFile", "brand/designer_prompt.md"))))
    if not source.is_file():
        raise DesignerPromptError(f"{source} is missing: the designer's prompt (PRD v6 R3.3)")
    text = " ".join(source.read_text(encoding="utf-8").split())
    for old, new in dict(templates.get("designerAdapt", {})).items():
        text = text.replace(old, str(new).format(platform=platform, format=canvas))
    return text


def check_clean(prompt: str, copy_texts: list[str] | None = None) -> None:
    """No coordinates or zone numbers in an image-model prompt (PRD v6 R3.1 pattern 1); the
    quoted copy may carry its own numbers."""
    rest = prompt
    for text in sorted(copy_texts or [], key=len, reverse=True):
        if text:
            rest = rest.replace(text, " ")
    rest = re.sub(r"#[0-9A-Fa-f]{6}", " ", rest)  # brand colours by hex are allowed
    rest = re.sub(r"\(\d+x\d+\)|\b\d+:\d+\b|\b35mm\b|f/\d(?:\.\d)?", " ", rest)  # format, lens
    found = _COORDINATES.search(rest)
    if found:
        raise DesignerPromptError(f'the image prompt carries a coordinate ("{found.group(0)}"): '
                                  "zones go to the model in words only (PRD v6 R3.1)")


def without_brand(text: str) -> str:
    """A description without its logo, wordmark or brand-name parts: the clauses (split at ";"
    and ",") that name one are left out; a bare brand name becomes "the brand"."""
    parts = [part.strip() for part in re.split(r"[;,]", text)]
    kept = [part for part in parts
            if part and not re.search(r"\blogos?\b|wordmark", part, re.IGNORECASE)]
    return re.sub(r"brand(?:ed|it)\s*genius(?:\.de)?|brandedgenius(?:\.de)?", "the brand",
                  ", ".join(kept), flags=re.IGNORECASE)


def check_brand_free(prompt: str, allowed: list[str]) -> None:
    """No logo, wordmark or brand name in an image prompt outside its negatives and the quoted
    copy (2026-10-21: the model drew what it was told about)."""
    rest = prompt
    for text in sorted(allowed, key=len, reverse=True):
        if text:
            rest = rest.replace(text, " ")
    found = _BRAND.search(rest)
    if found:
        raise DesignerPromptError(f'the image prompt names "{found.group(0)}": the logo, '
                                  "wordmarks and the brand name stay out of it (the app adds "
                                  "the real logo afterwards)")


def guide_image(pdf: Path, cache_dir: Path, crop: list[float] | None = None) -> Path:
    """The colour section of the style guide page as a JPEG for the model (the guide PDF is one
    embedded JPEG; `crop` in shares of the page: config/brand_refs.json guidelineCrop)."""
    target = cache_dir / ("brand_style_guide_colours.jpg" if crop else "brand_style_guide.jpg")
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
    if crop:
        width, height = image.size
        image = image.crop((round(crop[0] * width), round(crop[1] * height),
                            round(crop[2] * width), round(crop[3] * height)))
    image.thumbnail((GUIDE_LONG_SIDE, GUIDE_LONG_SIDE))
    cache_dir.mkdir(parents=True, exist_ok=True)
    image.save(target, format="JPEG", quality=90)
    return target


def masked_reference(path: Path, boxes: list[list[float]], cache_dir: Path) -> Path:
    """A reference with its boxes (carousel top corners with logo and old slide counters, and any
    third-party logo listed for that reference) painted in its own base colour, so the model never
    sees a logo or a counter to copy."""
    import hashlib

    key = hashlib.sha256(f"{path.as_posix()}|{boxes}".encode()).hexdigest()[:16]
    target = cache_dir / "masked_refs" / f"{key}.png"
    if target.is_file() and target.stat().st_mtime >= path.stat().st_mtime:
        return target
    from PIL import ImageDraw

    from content_automation.workflows.image_check import base_colour

    with Image.open(path) as opened:
        image = opened.convert("RGB")
    fill = base_colour(image)
    draw = ImageDraw.Draw(image)
    width, height = image.size
    for box in boxes:
        draw.rectangle((round(box[0] * width), round(box[1] * height),
                        round(box[2] * width), round(box[3] * height)), fill=fill)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="PNG")
    return target


# --- Zones in words -----------------------------------------------------------------------------


def place_words(box: tuple[float, float, float, float]) -> str:
    """Where a box sits, in words: "the top-right corner", "the left half", "the lower third"."""
    left, top, right, bottom = box
    cx, cy = (left + right) / 2, (top + bottom) / 2
    wide, tall = right - left, bottom - top
    across = "left" if cx < 0.4 else "right" if cx > 0.6 else "centre"
    down = "top" if cy < 0.33 else "bottom" if cy > 0.67 else "middle"
    if wide <= 0.45 and tall <= 0.25 and down != "middle" and across != "centre":
        return f"the {down}-{across} corner"
    if tall >= 0.6 and wide <= 0.7 and across != "centre":
        return f"the {across} half"
    if wide >= 0.6 and tall <= 0.45 and down != "middle":
        return f"the {'upper' if down == 'top' else 'lower'} part"
    if across == "centre":
        return f"the {down} centre" if down != "middle" else "the centre"
    return f"the {down} {across}" if down != "middle" else f"the {across} side"


def _union(boxes: list[tuple[float, float, float, float]]) -> tuple[float, float, float, float]:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
            max(b[3] for b in boxes))


@dataclass
class LayoutWords:
    text_side: str  # "the left half"
    logo_corner: str  # "top-right corner" or "" (no logo on this slide)
    description: str  # the layout for the model, in words


def layout_words(layout: Layout) -> LayoutWords:
    """The layout for the image model, in words only."""
    zones = layout.zones
    texts = [zone.box for zone in zones.values() if zone.kind == "items" or (
        zone.kind == "text" and zone.role in ("eyebrow", "headline", "sub", "body", "number"))]
    text_side = place_words(_union(texts)) if texts else "the text side"
    logo = next((zone for zone in zones.values() if zone.kind == "logo"), None)
    logo_corner = place_words(logo.box).removeprefix("the ") if logo is not None else ""
    parts = [f"the text sits in {text_side}"]
    for role, label in (("headline", "the headline"), ("sub", "the subline"),
                        ("body", "the body text")):
        zone = next((z for z in zones.values() if z.kind == "text" and z.role == role), None)
        if zone is not None:
            parts.append(f"{label} in {place_words(zone.box)}")
    if any(zone.kind == "shape" and zone.shape in ("panel", "glass") and zone.outline
           and not any(z.kind == "icons" and boxes_inside(z.box, zone.box)
                       for z in zones.values()) for zone in zones.values()):
        parts.append("on a large dark-navy rounded panel with a thin glowing blue outline and one "
                     "angled cut corner")
    else:
        parts.append("directly on the dark base")
    visual = next((zone for zone in zones.values() if zone.kind == "visual"), None)
    if visual is not None:
        other = "right" if "left" in text_side else "left" if "right" in text_side else ""
        parts.append(f"the visual fills the {other} side" if other else
                     f"the visual fills {place_words(visual.box)}")
    if any(zone.kind == "icons" and not zone.labels for zone in zones.values()):
        parts.append("a row of three to four circular outline icons with their short labels")
    if any(zone.kind == "icons" and zone.style == "engagement" for zone in zones.values()):
        parts.append("a bottom engagement bar: a rounded rectangle with three columns, each with "
                     "an outline icon (heart, paper plane, bookmark), a bold label and a small "
                     "line under it")
    cta = zones.get("cta")
    if cta is not None and cta.kind == "text":
        side = "on the left" if cta.icon_side == "left" else "on the right"
        parts.append(f"the call-to-action button in {place_words(cta.box)} with its "
                     f"{(cta.icon or 'arrow-right').replace('-', ' ')} icon {side}, never "
                     "touching the text")
    if logo_corner:
        parts.append(f"the {logo_corner} stays plain empty dark space with nothing in it")
    if any(zone.kind == "footer" for zone in zones.values()):
        footer = next(zone for zone in zones.values() if zone.kind == "footer")
        parts.append(f"{place_words(footer.box)} keeps a small empty strip for the website")
    return LayoutWords(text_side, logo_corner, "; ".join(parts))


def boxes_inside(inner: tuple[float, float, float, float],
                 outer: tuple[float, float, float, float]) -> bool:
    return (outer[0] <= inner[0] and outer[1] <= inner[1] and inner[2] <= outer[2]
            and inner[3] <= outer[3])


def _marked(raw: str) -> tuple[str, list[str]]:
    """The copy as the reader sees it, and its *marked* keywords."""
    from content_automation.workflows.design_render import plain

    keys = [match.group(1) or match.group(2) or match.group(3) for match in re.finditer(
        r"\*\*(.+?)\*\*|\*(.+?)\*|\[\[(.+?)\]\]", raw)]
    return plain(raw), [key for key in keys if key]


def _list(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in items if isinstance(item, str) and item.strip()]


def designer_texts(layout: Layout, copy: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(the exact strings the model writes, their descriptions for the prompt). The logo and the
    website are the app's; everything else readable is listed here."""
    exact: list[str] = []
    lines: list[str] = []
    ordered = sorted(layout.zones.items(), key=lambda item: (
        TEXT_ZONE_ORDER.index(item[1].role) if item[1].role in TEXT_ZONE_ORDER else 50))
    for name, zone in ordered:
        if zone.kind == "text" and zone.field:
            raw = " ".join(_list(copy.get(zone.field)))
            if not raw:
                continue
            text, keys = _marked(raw)
            if zone.upper:
                text, keys = text.upper(), [key.upper() for key in keys]
            exact.append(text)
            what = {"headline": "headline", "cta": "button text", "number": "number"}.get(
                str(zone.role), "line")
            accent = (f' (the words "{", ".join(keys)}" in light blue)' if keys else "")
            lines.append(f'{what} "{text}"{accent}')
        elif zone.kind == "items" and zone.field:
            items = [_marked(item)[0] for item in _list(copy.get(zone.field))]
            exact += items
            lines += [f'list item "{item}"' for item in items]
        elif zone.kind == "icons":
            labels = _list(copy.get(zone.field)) if zone.field else list(zone.labels)
            for label in labels:
                head, _, small = label.partition("|")
                exact.append(head.strip())
                lines.append(f'icon label "{head.strip()}"')
                if small.strip():
                    exact.append(small.strip())
                    lines.append(f'small line "{small.strip()}" under it')
        del name
    return exact, lines


def _ref_files(direction: Direction, references_dir: Path, limit: int,
               role: str | None) -> list[tuple[str, Path, str, str, list[list[float]]]]:
    """(id, file, use, kind, mask boxes) per reference; the boxes cover third-party logos and
    brand marks in that file ("mask" for the first frame, "lastMask" for the last one)."""
    refs = load_refs().get("refs", {})
    found: list[tuple[str, Path, str, str, list[list[float]]]] = []
    for ref_id in direction.reference_ids[:limit]:
        entry = refs.get(ref_id)
        if not isinstance(entry, dict):
            raise DesignerPromptError(f"{direction.id}: reference {ref_id} is not in "
                                      f"{REFS_FILE} (approved company references only)")
        last = role == "cta" and bool(entry.get("last"))
        name = str(entry["last"] if last else entry.get("masked") or entry["file"])
        boxes = [list(map(float, box)) for box in entry.get("lastMask" if last else "mask", [])]
        found.append((ref_id, references_dir / name, str(entry.get("use", "")),
                      str(entry.get("kind", "")), boxes))
    return found


def _look(direction: Direction) -> str:
    look = load_templates().get("look", {})
    return str(look.get("carousel" if direction.format == "carousel" else "feed", ""))


def mirror_words(text: str) -> str:
    """left <-> right in a picture description (a mirrored layout variant)."""
    swap = {"left": "right", "right": "left", "Left": "Right", "Right": "Left"}
    return re.sub(r"\b(left|right|Left|Right)\b", lambda m: swap[m.group(1)], text)


def designer_inputs(direction: Direction, layout: Layout, catalog: DirectionCatalog, *,
                    picture: str, topic: str, copy: dict[str, Any], references_dir: Path,
                    logo_path: Path | None, cache_dir: Path, mock: bool,
                    role: str | None = None, mode: Mode = "designer") -> DesignerInputs:
    """The full prompt and its image inputs for one picture of a layout variant."""
    templates = load_templates()
    category = templates["categories"][direction.category]
    width, height = catalog.size(direction)
    words = layout_words(layout)
    values = {
        "category": category["category"], "platform": category["platform"],
        "purpose": category["purpose"], "mission": templates["mission"],
        "topic": without_brand(topic.strip()) or "(no topic)",
        "variant": f"{direction.id} {direction.name}",
        "layout": words.description, "picture": picture, "look": _look(direction),
        "format": direction.canvas, "size": f"{width}x{height}",
        "logoCorner": words.logo_corner or "corner",
        "textSide": words.text_side[:1].upper() + words.text_side[1:],
    }
    if mode == "composite":
        composite = templates["composite"]
        prompt = " ".join([str(composite["core"]).format(**values),
                           str(composite["negatives"]), str(templates["format"]).format(**values)])
        check_clean(prompt, [picture])
        check_brand_free(prompt, [str(composite["negatives"])])
        return DesignerInputs(prompt=prompt, mode="composite")
    limit = int(templates.get("maxReferences", 3))
    refs = _ref_files(direction, references_dir, limit, role)
    missing: list[str] = []
    objects: list[ReferenceImage] = []
    refs_config = load_refs()
    guide_pdf = references_dir / str(refs_config.get("guideline", ""))
    try:
        guide = guide_image(guide_pdf, cache_dir, refs_config.get("guidelineCrop")) if (
            guide_pdf.is_file()) else None
    except (DesignerPromptError, OSError) as error:
        raise DesignerPromptError(str(error)) from None
    if guide is None:
        missing.append(f"style guide {guide_pdf}")
    else:
        objects.append(ReferenceImage(asset_id="brand-style-guide", path=guide,
                                      source=f"{guide_pdf.name} (colour section)", people=False,
                                      logo=False))
    del logo_path  # never sent: the app places the real logo afterwards (2026-10-21)
    styles: list[ReferenceImage] = []
    for ref_id, path, _, kind, own_boxes in refs:
        if not path.is_file():
            missing.append(f"reference {ref_id} {path}")
            continue
        boxes = list(refs_config.get("carouselMask", [])) if kind == "instagram_carousel" else []
        boxes += own_boxes  # third-party logos (e.g. a search bar) the model must never copy
        sent = masked_reference(path, boxes, cache_dir) if boxes else path
        styles.append(ReferenceImage(asset_id=f"ref-{ref_id}", path=sent,
                                     source=f"{ref_id} {path.name} (logo masked)", people=None,
                                     logo=False))
    if missing and not mock:
        raise DesignerPromptError(f"{direction.id}: the designer prompt needs its inputs; "
                                  f"missing: {'; '.join(missing)} (copy assets/reference onto "
                                  "this machine)")
    first = len(objects) + 1
    values["referenceImages"] = (
        f"Images {first} to {first + len(styles) - 1} are" if len(styles) > 1
        else f"Image {first} is" if styles else "No images are attached as")
    values["references"] = "; ".join(f"{ref_id}: {without_brand(use)}"
                                     for ref_id, path, use, _, _ in refs
                                     if path.is_file()) or "the dark look above"
    exact, described = designer_texts(layout, copy)
    values["texts"] = "; ".join(described) or "(no text on this image)"
    parts = [designer_text(category["platform"], direction.canvas),
             str(templates["inputs"]).format(**values), str(templates["brief"]).format(**values),
             _look(direction), str(templates["texts"]).format(**values),
             str(templates["negatives"]), str(templates["format"]).format(**values)]
    if words.logo_corner:
        parts.insert(-2, f"Leave the {words.logo_corner} as plain empty dark space: nothing "
                         "drawn there, no text and no symbol.")
    prompt = " ".join(part for part in parts if part)
    check_clean(prompt, [*exact, topic, picture])
    check_brand_free(prompt, [*exact, str(templates["negatives"])])
    return DesignerInputs(prompt=prompt, object_refs=objects, style_refs=styles,
                          missing=missing, mode="designer", texts=exact)


__all__ = ["CONFIG_FILE", "DesignerInputs", "DesignerPromptError", "LayoutWords", "Mode",
           "REFS_FILE", "check_brand_free", "check_clean", "default_mode", "designer_inputs",
           "designer_text",
           "designer_texts", "guide_image", "layout_words", "load_refs", "load_templates",
           "masked_reference", "mirror_words", "place_words", "without_brand"]
