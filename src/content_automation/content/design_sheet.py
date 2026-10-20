"""`ca design compare` (PRD v5 R3.6, v6 §5 check 2): every layout variant next to the approved
references, in v6 at outputs/_system/previews/design_fix_vs_references.png.

One row per variant, grouped by category: the approved company graphics the variant was derived
from (config/brand_refs.json; a carousel shows its cover and last slide), then the variant's
layouts drawn with the German sample copy and a dark stand-in picture (the same renders as
`ca design preview`), plus one other variation of each feed variant (v6 R3.5: side, panel,
decoration set, CTA style). The graphic designer's own outputs are added when files exist in
REFERENCES_DIR/creative/designer/ (none were found on 2026-10-19). Free and local: no provider
is called. Roman reviews this sheet before the first paid batch (acceptance criterion 3).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from content_automation.content.design_preview import sample_copy, stand_in_picture
from content_automation.content.design_variation import apply as apply_variation
from content_automation.content.design_variation import variations
from content_automation.content.designer_prompt import load_refs
from content_automation.content.directions import CATEGORY, load_directions
from content_automation.references import load_brand
from content_automation.workflows.design_render import (
    Assets,
    design_fonts,
    emblem_file,
    logo_file,
    render_layout,
    token_colors,
)

SHEET_FILE = Path("outputs/_system/previews/design_fix_vs_references.png")
DESIGNER_DIR = "creative/designer"  # the graphic designer's own outputs, if Roman adds them
TILE = 300
GAP = 16
LABEL = 34
_FONT = Path(__file__).resolve().parents[3] / "assets" / "fonts" / "Jost-Medium.ttf"
_BOLD = Path(__file__).resolve().parents[3] / "assets" / "fonts" / "Jost-Bold.ttf"


def _tile(image: Image.Image) -> Image.Image:
    return ImageOps.contain(image.convert("RGB"), (TILE, TILE))


def _missing(label: str) -> Image.Image:
    tile = Image.new("RGB", (TILE, TILE), (230, 230, 230))
    ImageDraw.Draw(tile).text((TILE // 2, TILE // 2), f"{label}\nnot on this machine",
                              fill=(120, 120, 120), anchor="mm", align="center",
                              font=ImageFont.truetype(str(_FONT), 18))
    return tile


def compare_sheet(references_dir: Path, out: Path = SHEET_FILE) -> list[str]:
    """Draw the sheet; one line per row and a summary line."""
    catalog = load_directions()
    brand = load_brand(references_dir)
    assets = Assets(brand=brand, logo_path=logo_file(brand, references_dir),
                    fonts=design_fonts(brand), emblem_path=emblem_file(brand, references_dir))
    colors = token_colors(brand)
    samples = sample_copy()
    refs = load_refs().get("refs", {})
    rows: list[tuple[str, list[tuple[str, Image.Image]], list[tuple[str, Image.Image]]]] = []
    lines: list[str] = []
    for format_name, category in CATEGORY.items():
        for direction in catalog.for_format(format_name):
            left: list[tuple[str, Image.Image]] = []
            for ref_id in direction.reference_ids[:2]:
                entry = refs.get(ref_id, {})
                names = [entry.get("file")] + ([entry.get("last")] if entry.get("last") else [])
                for name in names[:2]:
                    path = references_dir / str(name)
                    left.append((f"approved {ref_id}", _tile(Image.open(path)) if path.is_file()
                                 else _missing(ref_id)))
            right: list[tuple[str, Image.Image]] = []
            for layout_name in direction.layouts:
                picture = stand_in_picture(direction, layout_name, catalog, colors, None)
                rendered = render_layout(catalog, direction, layout_name,
                                         samples[f"{direction.id}/{layout_name}"], assets,
                                         picture=picture)
                right.append((f"{direction.id} {layout_name}", _tile(rendered.image)))
            if direction.format != "carousel":  # one other variation (v6 R3.5)
                name = next(iter(direction.layouts))
                options = [v for v in variations(direction, direction.layouts[name], catalog)
                           if v.side == ("R" if not direction.roman else "L")
                           and v.deco != "none"]
                if options:
                    varied = apply_variation(direction, direction.layouts[name], options[-1],
                                             catalog)
                    picture = stand_in_picture(direction, name, catalog, colors, None)
                    rendered = render_layout(catalog, direction, name,
                                             samples[f"{direction.id}/{name}"], assets,
                                             picture=picture, layout=varied)
                    right.append((f"{direction.id} {options[-1].key}", _tile(rendered.image)))
            rows.append((f"{category}: {direction.label} [{direction.treatment}]", left, right))
            lines.append(f"{direction.id}: {len(right)} layout(s) beside "
                         f"{', '.join(direction.reference_ids[:2])}")
    designer = sorted((references_dir / DESIGNER_DIR).glob("*.*")) if (
        references_dir / DESIGNER_DIR).is_dir() else []
    if designer:
        rows.append(("The graphic designer's own outputs", [],
                     [(path.name, _tile(Image.open(path))) for path in designer[:8]]))
    start = GAP + 4 * (TILE + GAP) + TILE // 3  # the column where the v5 renders start
    width = start + max(len(r) for _, _, r in rows) * (TILE + GAP)
    height = GAP + len(rows) * (TILE + LABEL * 2 + GAP) + LABEL
    sheet = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    head = ImageFont.truetype(str(_BOLD), 22)
    small = ImageFont.truetype(str(_FONT), 16)
    y = GAP
    for title, left, right in rows:
        draw.text((GAP, y), title, fill=(0, 75, 160), font=head)
        x = GAP
        for label, tile in left:
            sheet.paste(tile, (x, y + LABEL))
            draw.text((x, y + LABEL + TILE + 4), label, fill=(80, 80, 80), font=small)
            x += TILE + GAP
        x = start if left else x  # the v5 renders line up in one column
        draw.line((x - GAP, y + LABEL, x - GAP, y + LABEL + TILE), fill=(105, 191, 248),
                  width=3)
        for label, tile in right:
            sheet.paste(tile, (x, y + LABEL))
            draw.text((x, y + LABEL + TILE + 4), label, fill=(80, 80, 80), font=small)
            x += TILE + GAP
        y += TILE + LABEL * 2 + GAP
    note = ("Left: approved Branded Genius graphics (config/brand_refs.json). Right: v6 layout "
            "variants and one other variation each, with German sample copy and a text-free "
            "stand-in scene (free, no provider). "
            + ("" if designer else "No designer outputs found in creative/designer/."))
    draw.text((GAP, y), note, fill=(80, 80, 80), font=small)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, format="PNG", optimize=True)
    lines.append(f"Sheet: {out} ({len(rows)} rows; free, no provider called)")
    return lines


__all__ = ["SHEET_FILE", "compare_sheet"]
