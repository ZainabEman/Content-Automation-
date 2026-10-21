"""`ca design overlay` (Phase 3 of GERMAN_CONTENT_AND_IMAGE_WORKFLOW_PRD.md, P3-R8): a founder
overlay re-rendered on an existing picture of Roman, free and local (no image is generated, no
provider is called), and a contact sheet of every founder variant with short, medium and
maximum copy.

The picture is the one a build used: the job folder's raw/image-N.png beside image-N.design.json
(the render manifest with its direction, layout and copy; details.json has the variation). A
target is that manifest, its job folder, a package folder or the package's BG id (its first
image). --copy FILE replaces the copy (a JSON object with the layout's fields), so shortened copy
can be tried before a rebuild. The same checks as the build run on the result (design check and
Roman's strict checks); the exact text is a string comparison of the drawn text with the copy.
Writes PNG + manifest to outputs/_system/previews/overlay/; the package is never touched.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageOps

from content_automation.content.design_preview import SAMPLE_COPY, stand_in_picture
from content_automation.content.design_variation import Variation
from content_automation.content.design_variation import apply as apply_variation
from content_automation.content.directions import (
    SIDE_LAYOUTS,
    Direction,
    DirectionCatalog,
    load_directions,
)
from content_automation.core.files import atomic_write_text
from content_automation.core.output_tree import iter_package_files
from content_automation.references import load_brand
from content_automation.references.brand import BrandProfile
from content_automation.references.services import ServiceCatalog
from content_automation.workflows.design_check import Report, check_manifest
from content_automation.workflows.design_render import (
    Assets,
    DesignRenderError,
    Rendered,
    design_fonts,
    emblem_file,
    logo_file,
    plain,
    render_layout,
    token_colors,
)
from content_automation.workflows.roman_check import run_checks

OVERLAY_DIR = Path("outputs/_system/previews/overlay")
SHEET_NAME = "founder_contact_sheet.png"
LENGTHS = ("short", "medium", "max")
_TILE = 360


class OverlayPreviewError(ValueError):
    """The target names no founder image, or its picture is missing."""


def find_manifest(target: str, outputs: Path = Path("outputs")) -> Path:
    """image-N.design.json of a founder image: the file itself, a job folder, a package folder
    or a BG id (the package's first image folder)."""
    path = Path(target)
    if path.is_file():
        return path
    if path.is_dir() and (path / "package.json").is_file():
        return _from_package(path / "package.json")
    if path.is_dir():
        found = sorted(path.glob("image-*.design.json"))
        if found:
            return found[0]
        raise OverlayPreviewError(f"{path} has no image-N.design.json (not a job folder)")
    marker = f"_{target.upper()}_"
    for package in iter_package_files(outputs):
        if marker in f"{package.parent.name}_":
            return _from_package(package)
    raise OverlayPreviewError(f"{target}: no package, job folder or render manifest found")


def _from_package(package: Path) -> Path:
    data = json.loads(package.read_text(encoding="utf-8"))
    for item in (data.get("items") or {}).values():
        for folder in item.get("imageFolders") or []:
            found = sorted(Path(str(folder).replace("\\", "/")).glob("image-*.design.json"))
            if found:
                return found[0]
    raise OverlayPreviewError(f"{package.parent.name}: no built image (package.json "
                              "imageFolders)")


def _assets(references_dir: Path) -> tuple[Assets, BrandProfile]:
    brand = load_brand(references_dir)
    return Assets(brand=brand, logo_path=logo_file(brand, references_dir),
                  fonts=design_fonts(brand),
                  emblem_path=emblem_file(brand, references_dir)), brand


def expected_texts(direction: Direction, layout_name: str,
                   copy: Mapping[str, object]) -> list[str]:
    """The strings the layout must show, as the reader sees them (marks removed)."""
    found: list[str] = []
    for zone in direction.layouts[layout_name].zones.values():
        value = copy.get(str(zone.field)) if zone.field else None
        items = value if isinstance(value, list) else [value]
        lines = [str(item).strip() for item in items if isinstance(item, str) and item.strip()]
        if zone.kind == "text" and lines:
            found.append(plain(" ".join(lines)))
        elif zone.kind == "icons":
            found += [plain(line) for line in lines]
    return found


def _check(rendered: Rendered, direction: Direction, layout_name: str, copy: Mapping[str, Any],
           picture: Image.Image | None, catalog: DirectionCatalog, brand: BrandProfile,
           services: ServiceCatalog, name: str) -> tuple[Report, dict[str, Any]]:
    manifest = json.loads(json.dumps(rendered.manifest(), default=str)) | {"copy": dict(copy)}
    report = check_manifest(manifest, catalog=catalog, brand=brand, services=services, name=name,
                            image=rendered.image, person_check=None)
    side = "S-L" if layout_name == SIDE_LAYOUTS["S-L"] else "S-R"
    roman, _ = run_checks(manifest, side, picture)
    report.errors += roman.errors
    report.checks = roman.results
    drawn = sorted(text.text for text in rendered.texts)
    wanted = sorted(expected_texts(direction, layout_name, copy))
    report.checks["exactText"] = ("passed" if drawn == wanted else
                                  f"failed: drawn {drawn}, approved {wanted}")
    if drawn != wanted:
        report.errors.append("exactText: the drawn text differs from the approved copy")
    return report, manifest


def summary(rendered: Rendered) -> str:
    """One line per text: size, lines as drawn, contrast and the calm numbers."""
    parts = []
    for text in rendered.texts:
        calm = (f", spread {text.backdrop_std:g}/detail {text.backdrop_detail:g}"
                if text.backdrop_std is not None else "")
        parts.append(f"{text.zone} {text.font_px}px {' | '.join(text.drawn)} (contrast "
                     f"{text.contrast:g}:1, needs {text.needed:g}{calm})")
    return "; ".join(parts)


def overlay_preview(target: str, references_dir: Path, services: ServiceCatalog, *,
                    copy_file: Path | None = None, out_dir: Path = OVERLAY_DIR) -> list[str]:
    """Re-render one founder image's overlay on its own picture; lines for the operator."""
    source = find_manifest(target)
    manifest = json.loads(source.read_text(encoding="utf-8"))
    catalog = load_directions()
    direction = catalog.get(str(manifest["direction"]))
    if not direction.roman:
        raise OverlayPreviewError(f"{direction.id} is not a founder variant (Roman's overlays "
                                  "only; Branch B images are drawn by the model)")
    layout_name = str(manifest["layout"])
    stem = source.name.split(".")[0]
    picture_file = source.parent / "raw" / f"{stem}.png"
    if not picture_file.is_file():
        raise OverlayPreviewError(f"{picture_file} is missing: the picture the build used")
    copy: dict[str, Any] = (json.loads(copy_file.read_text(encoding="utf-8")) if copy_file
                            else dict(manifest.get("copy") or {}))
    details = source.parent / "details.json"
    variation = (json.loads(details.read_text(encoding="utf-8")).get("inputs") or {}).get(
        "variation") if details.is_file() else None
    layout = direction.layouts[layout_name]
    if variation:
        layout = apply_variation(direction, layout, Variation.parse(str(variation)), catalog)
    assets, brand = _assets(references_dir)
    with Image.open(picture_file) as opened:
        picture = opened.convert("RGB")
    rendered = render_layout(catalog, direction, layout_name, copy, assets, picture=picture,
                             layout=layout)
    report, checked = _check(rendered, direction, layout_name, copy, picture, catalog, brand,
                             services, f"{direction.id} {layout_name}")
    out_dir.mkdir(parents=True, exist_ok=True)
    label = source.parent.name.split("_", 1)[-1][:40]
    target_png = out_dir / f"{direction.id}_{layout_name}_{label}.png"
    rendered.image.save(target_png, format="PNG", optimize=True)
    atomic_write_text(target_png.with_suffix(".json"), json.dumps(
        checked | {"source": source.as_posix(), "picture": picture_file.as_posix(),
                   "variation": variation, "check": {"errors": report.errors,
                                                     "warnings": report.warnings,
                                                     "romanChecks": report.checks}},
        indent=2, ensure_ascii=False))
    return [f"{direction.id} {layout_name} on {picture_file.as_posix()} "
            f"(variation {variation or 'none'}): {target_png.as_posix()}",
            f"  {summary(rendered)}", *report.lines()[0:1],
            *[f"  {name}: {value}" for name, value in report.checks.items()],
            *report.lines()[1:],
            "Free: nothing generated, the package untouched. To use it: shorten the copy in the "
            "brief if needed, then rebuild (an accepted Higgsfield image costs nothing again)."]


def roman_pictures(jobs: Path = Path("outputs/_system/jobs")) -> dict[str, Path]:
    """The newest built founder picture per side (S-R, S-L): a completed Higgsfield job's
    raw/image-1.png."""
    found: dict[str, tuple[str, Path]] = {}
    for details in jobs.glob("*/*/details.json"):
        data = json.loads(details.read_text(encoding="utf-8"))
        inputs = data.get("inputs") or {}
        picture = details.parent / "raw" / "image-1.png"
        if (data.get("provider") != "higgsfield_soul" or data.get("status") != "completed"
                or not picture.is_file()):
            continue
        side = str(inputs.get("romanCombination") or "").split("/")[0]
        stamp = str(data.get("updatedAt") or "")
        if side in ("S-R", "S-L") and stamp > found.get(side, ("", picture))[0]:
            found[side] = (stamp, picture)
    return {side: picture for side, (_, picture) in found.items()}


def sample_lengths(path: Path = SAMPLE_COPY) -> dict[str, dict[str, object]]:
    if not path.is_file() and not path.is_absolute():
        path = Path(__file__).resolve().parents[3] / path
    data = json.loads(path.read_text(encoding="utf-8"))
    lengths = data.get("_romanLengths") or {}
    return {key: dict(lengths[key]) for key in LENGTHS}


def overlay_sheet(references_dir: Path, services: ServiceCatalog, *,
                  out_dir: Path = OVERLAY_DIR) -> list[str]:
    """Every founder variant on both sides with short, medium and maximum copy (config/
    design_preview_copy.json _romanLengths) on the newest built picture of that side (else the
    stand-in); one PNG, failures named on their tile."""
    catalog = load_directions()
    assets, brand = _assets(references_dir)
    colors = token_colors(brand)
    pictures = roman_pictures()
    lengths = sample_lengths()
    rows: list[tuple[str, list[Image.Image]]] = []
    lines: list[str] = []
    failed = 0
    for direction in (item for item in catalog.directions if item.roman):
        for layout_name in direction.layouts:
            side = "S-L" if layout_name == SIDE_LAYOUTS["S-L"] else "S-R"
            source = pictures.get(side)
            if source is not None:
                with Image.open(source) as opened:
                    picture: Image.Image | None = opened.convert("RGB")
            else:
                picture = stand_in_picture(direction, layout_name, catalog, colors, None)
            tiles = []
            for length in LENGTHS:
                key = f"{direction.id} {layout_name} {length}"
                try:
                    rendered = render_layout(catalog, direction, layout_name, lengths[length],
                                             assets, picture=picture)
                    report, _ = _check(rendered, direction, layout_name, lengths[length],
                                       picture if source is not None else None, catalog, brand,
                                       services, key)
                    tile = rendered.image
                    note = "PASS" if report.passed else "FAIL: " + "; ".join(report.errors)[:90]
                    lines.append(f"{key}: {note} | {summary(rendered)}")
                except DesignRenderError as error:
                    tile = Image.new("RGB", catalog.size(direction), (40, 0, 0))
                    note = f"FAIL: {error}"[:90]
                    lines.append(f"{key}: {note}")
                failed += not note.startswith("PASS")
                tiles.append(_label(tile, f"{key}: {note[:44]}"))
            rows.append((f"{direction.id} {layout_name} on "
                         f"{source.parent.parent.name[:30] if source else 'the stand-in'}",
                         tiles))
    sheet = _sheet(rows)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / SHEET_NAME
    sheet.save(target, format="PNG", optimize=True)
    used = ", ".join(f"{side} {path.parent.parent.name}" for side, path in pictures.items())
    return [*lines, f"Contact sheet: {target.as_posix()} ({len(rows) * len(LENGTHS)} tiles, "
            f"{failed} failed; pictures: {used or 'stand-ins'}; free, nothing generated)."]


def _label(image: Image.Image, text: str) -> Image.Image:
    tile = ImageOps.contain(image, (_TILE, round(_TILE * 1.4)), Image.Resampling.LANCZOS)
    framed = Image.new("RGB", (_TILE, tile.height + 22), (20, 22, 28))
    framed.paste(tile, (0, 22))
    ImageDraw.Draw(framed).text((4, 4), text, fill=(230, 230, 230))
    return framed


def _sheet(rows: list[tuple[str, list[Image.Image]]]) -> Image.Image:
    gap = 12
    width = gap + len(LENGTHS) * (_TILE + gap)
    heights = [22 + max(tile.height for tile in tiles) + gap for _, tiles in rows]
    sheet = Image.new("RGB", (width, gap + sum(heights)), (12, 13, 18))
    draw = ImageDraw.Draw(sheet)
    y = gap
    for (title, tiles), height in zip(rows, heights, strict=True):
        draw.text((gap, y + 4), title, fill=(255, 255, 255))
        for index, tile in enumerate(tiles):
            sheet.paste(tile, (gap + index * (_TILE + gap), y + 22))
        y += height
    return sheet


__all__ = ["LENGTHS", "OVERLAY_DIR", "OverlayPreviewError", "expected_texts", "find_manifest",
           "overlay_preview", "overlay_sheet", "roman_pictures", "sample_lengths"]
