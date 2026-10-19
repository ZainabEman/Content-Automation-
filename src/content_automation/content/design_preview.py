"""`ca design preview [IDS…] [--photo FILE]` (Phase D step 3): every layout of the chosen design
directions drawn with the sample copy in config/design_preview_copy.json, free and local.

Pictures are silver placeholders (a person outline for Roman's directions); --photo replaces
them in the directions without Roman only (Roman is always his LoRA, never a photo).
Writes `<ID>_<layout>.png` and `<ID>_<layout>.json` (the render manifest that `ca design check`
reads) to outputs/design/preview/. No provider is called.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from content_automation.content.directions import Direction, DirectionCatalog, load_directions
from content_automation.core.files import atomic_write_text
from content_automation.references import load_brand
from content_automation.workflows.design_render import (
    Assets,
    DesignRenderError,
    design_fonts,
    logo_file,
    placeholder,
    render_layout,
    token_colors,
)

SAMPLE_COPY = Path("config/design_preview_copy.json")
PREVIEW_DIR = Path("outputs/design/preview")


def sample_copy(path: Path = SAMPLE_COPY) -> dict[str, dict[str, object]]:
    if not path.is_file() and not path.is_absolute():  # run from another folder
        path = Path(__file__).resolve().parents[3] / path
    data = json.loads(path.read_text(encoding="utf-8"))
    return {key: value for key, value in data.items() if not key.startswith("_")}


def _silhouette(picture: Image.Image) -> Image.Image:
    """The placeholder as a person-shaped RGBA, the stand-in for a green-screen cut-out."""
    width, height = picture.size
    mask = Image.new("L", picture.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((width * 0.36, height * 0.04, width * 0.64, height * 0.36), fill=255)
    draw.rounded_rectangle((width * 0.14, height * 0.38, width * 0.86, height * 1.2),
                           radius=round(width * 0.22), fill=255)
    cut = picture.convert("RGBA")
    cut.putalpha(mask)
    return cut


def stand_in_picture(direction: Direction, layout_name: str, catalog: DirectionCatalog,
             colors: Mapping[str, tuple[int, int, int]], photo: Path | None) -> Image.Image | None:
    zones = [z for z in direction.layouts[layout_name].zones.values() if z.kind == "visual"]
    if not zones:
        return None
    zone = zones[0]
    cutout = zone.visual_shape == "cutout"
    if photo is not None and not direction.roman:  # Roman: only his LoRA, never a photo
        with Image.open(photo) as source:
            return source.convert("RGB")
    width, height = catalog.size(direction)
    left, top, right, bottom = zone.box
    size = (max(1, round((right - left) * width)), max(1, round((bottom - top) * height)))
    if zone.visual_shape == "full" and direction.layouts[layout_name].theme != "light":
        return dark_placeholder(size, direction.id, colors, person=direction.roman)
    stand_in = placeholder(size, direction.id, colors, person=direction.roman)
    return _silhouette(stand_in) if cutout else stand_in


def dark_placeholder(size: tuple[int, int], label: str,
                     colors: Mapping[str, tuple[int, int, int]], person: bool = False
                     ) -> Image.Image:
    """v5: a full-bleed stand-in like the approved references (near-black, a blue glow and the
    object on the right): a preview picture, never a design fill, so no token is needed."""
    width, height = size
    image = Image.new("RGB", size, (3, 6, 18))
    glow = Image.new("L", size, 0)
    ImageDraw.Draw(glow).ellipse((width * 0.55, height * 0.25, width * 1.05, height * 0.85),
                                 fill=150)
    glow = glow.filter(ImageFilter.GaussianBlur(max(4, width // 12)))
    image.paste(Image.new("RGB", size, colors["accent"]), (0, 0), glow)
    draw = ImageDraw.Draw(image)
    if person:
        draw.ellipse((width * 0.66, height * 0.16, width * 0.84, height * 0.36), fill=(40, 52, 80))
        draw.rounded_rectangle((width * 0.58, height * 0.38, width * 0.94, height * 1.05),
                               radius=round(width * 0.12), fill=(40, 52, 80))
    else:
        draw.rounded_rectangle((width * 0.66, height * 0.42, width * 0.88, height * 0.64),
                               radius=round(width * 0.03), outline=colors["accent"],
                               width=max(2, width // 220))
    return image


def preview(ids: Sequence[str] = (), photo: Path | None = None,
            references_dir: Path = Path("assets/reference"), out_dir: Path = PREVIEW_DIR,
            copy_file: Path = SAMPLE_COPY) -> list[str]:
    """Render the layouts; one line per file, failures named (the others still render)."""
    catalog = load_directions()
    brand = load_brand(references_dir)
    assets = Assets(brand=brand, logo_path=logo_file(brand, references_dir),
                    fonts=design_fonts(brand))
    colors = token_colors(brand)
    samples = sample_copy(copy_file)
    wanted = [catalog.get(value.upper()) for value in ids] or list(catalog.directions)
    if photo is not None and not photo.is_file():
        raise DesignRenderError(f"--photo {photo} is not a file")
    out_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    failed = 0
    for direction in wanted:
        for layout_name in direction.layouts:
            key = f"{direction.id}/{layout_name}"
            copy = samples.get(key)
            if copy is None:
                lines.append(f"{key}: no sample copy in {copy_file}")
                failed += 1
                continue
            try:
                picture = stand_in_picture(direction, layout_name, catalog, colors, photo)
                rendered = render_layout(catalog, direction, layout_name, copy, assets,
                                         picture=picture)
            except (DesignRenderError, OSError, ValueError) as error:
                lines.append(f"{key}: {error}")
                failed += 1
                continue
            target = out_dir / f"{direction.id}_{layout_name}.png"
            rendered.image.save(target, format="PNG", optimize=True)
            manifest = rendered.manifest() | {"copy": copy, "photo": str(photo) if photo else None}
            atomic_write_text(target.with_suffix(".json"),
                              json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
            low = min((t.contrast / t.needed for t in rendered.texts), default=1.0)
            lines.append(f"{key}: {target} ({len(rendered.texts)} texts"
                         f"{', contrast below the minimum' if low < 1 else ''})")
    rendered_count = len(lines) - failed
    lines.append(f"Preview: {rendered_count} rendered, {failed} failed, in {out_dir} "
                 "(free, no provider called).")
    return lines


__all__ = ["PREVIEW_DIR", "SAMPLE_COPY", "preview", "sample_copy", "stand_in_picture"]
