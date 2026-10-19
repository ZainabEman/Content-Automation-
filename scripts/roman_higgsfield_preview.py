"""The Roman-via-Higgsfield layout preview (free, offline, no provider called).

9 combinations cover every background, pose and hologram style (5 of them S-L), each drawn at
3:4 (LinkedIn), 1:1 (square) and 4:5 (Facebook: made at 3:4, then the person-safe crop), with
the founder variants' sample German copy, on the drawn stand-in for Roman. Every tile also runs
the strict checks (overlap, calm text zones, German). Writes
outputs/previews/design/roman_higgsfield_layouts.png.

    uv run python scripts/roman_higgsfield_preview.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from content_automation.content.design_preview import sample_copy
from content_automation.content.directions import SIDE_LAYOUTS, load_directions
from content_automation.content.roman_prompt import parse_combination
from content_automation.content.roman_standin import stand_in
from content_automation.core.person_zone import detect, safe_crop
from content_automation.references.brand import load_brand
from content_automation.workflows.design_render import (
    Assets,
    design_fonts,
    logo_file,
    render_layout,
)
from content_automation.workflows.roman_check import run_checks

OUT = Path("outputs/previews/design/roman_higgsfield_layouts.png")
COMBINATIONS = ["S-R/BG-1/P-1/H-1", "S-L/BG-1/P-2/H-2", "S-R/BG-1/P-3/H-3",
                "S-L/BG-2/P-1/H-2", "S-R/BG-2/P-2/H-3", "S-L/BG-2/P-3/H-1",
                "S-L/BG-3/P-1/H-3", "S-R/BG-3/P-2/H-1", "S-L/BG-3/P-3/H-2"]
COPY_FROM = ["LI-R1", "FB-R1", "FA-R1"]
TILE_W = 240
GAP = 16


def main() -> int:
    catalog = load_directions()
    references = Path("assets/reference")
    brand = load_brand(references)
    assets = Assets(brand=brand, logo_path=logo_file(brand, references),
                    fonts=design_fonts(brand))
    samples = sample_copy()
    font = ImageFont.truetype(str(assets.fonts.get("bold") or next(iter(assets.fonts.values()))),
                              18)
    blocks: list[Image.Image] = []
    failures: list[str] = []
    for number, value in enumerate(COMBINATIONS):
        combination = parse_combination(value)
        layout = SIDE_LAYOUTS[combination.side]
        copy = samples[f"{COPY_FROM[number % 3]}/{layout}"]
        tall = stand_in((1080, 1440), combination.side, combination.pose)
        square = stand_in((1080, 1080), combination.side, combination.pose)
        cropped, _ = safe_crop(tall, (4, 5), detect(tall))
        tiles = []
        for label, direction_id, picture, size in (
                ("3:4", "LI-R1", tall, (1080, 1440)),
                ("1:1", "FB-R1", square, (1080, 1080)),
                ("4:5 (3:4 cropped)", "FB-R1", cropped, (1080, 1350))):
            direction = catalog.get(direction_id)
            rendered = render_layout(catalog, direction, layout, copy, assets, picture=picture,
                                     size=size)
            checks, _ = run_checks(rendered.manifest(), combination.side, picture)
            if checks.errors:
                failures.append(f"{value} {label}: {'; '.join(checks.errors)}")
            thumb = rendered.image.convert("RGB")
            thumb = thumb.resize((TILE_W, round(TILE_W * size[1] / size[0])),
                                 Image.Resampling.LANCZOS)
            tiles.append((f"{label} {'ok' if not checks.errors else 'FAIL'}", thumb))
        height = max(tile.size[1] for _, tile in tiles) + 64
        block = Image.new("RGB", (3 * TILE_W + 2 * GAP, height), (245, 246, 248))
        draw = ImageDraw.Draw(block)
        draw.text((0, 4), f"{number + 1}. {value}", fill=(10, 20, 40), font=font)
        for index, (label, tile) in enumerate(tiles):
            x = index * (TILE_W + GAP)
            block.paste(tile, (x, 32))
            draw.text((x, 36 + tile.size[1]), label, fill=(60, 70, 90), font=font)
        blocks.append(block)
    width = 3 * blocks[0].size[0] + 4 * GAP * 2
    rows = [blocks[i:i + 3] for i in range(0, len(blocks), 3)]
    height = sum(max(b.size[1] for b in row) + GAP * 2 for row in rows) + GAP * 2
    sheet = Image.new("RGB", (width, height), (245, 246, 248))
    y = GAP * 2
    for row in rows:
        for column, block in enumerate(row):
            sheet.paste(block, (GAP * 2 + column * (block.size[0] + GAP * 2), y))
        y += max(b.size[1] for b in row) + GAP * 2
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT, format="PNG", optimize=True)
    print(f"{OUT}: {len(COMBINATIONS)} combinations x 3 aspects "
          f"({sum(1 for v in COMBINATIONS if v.startswith('S-L'))} S-L); "
          f"{len(failures)} check failure(s)")
    for line in failures:
        print(f"  {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
