"""The free format preview (`ca overlay sheet`): every post format of config/post_formats.json,
and each Instagram carousel as cover, body and final slide, rendered with sample copy and a
gradient stand-in in the image slot, then the real logo, on one review sheet. No provider call.
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from content_automation.content.formats import ICONS, FormatCatalog, PostFormat, load_formats
from content_automation.core.config import Settings
from content_automation.references import ReferenceLibraryError, select_logo_ref
from content_automation.workflows.design_system import DesignSystem, load_design_system
from content_automation.workflows.logo import LogoError, LogoOverlay, apply_logo, check_logo
from content_automation.workflows.text_overlay import TextOverlay, compose_format, format_overlay

SHEET_FILE = Path("outputs/review/format_sheet.png")
TILE_WIDTH = 360
COLUMNS = 6
GAP = 24
LABEL = 34
SHEET_BACKGROUND = (226, 230, 236)

# Sample copy at the format limits (titles 8 words, lines 18 words): a concrete example each.
_SAMPLES: dict[str, object] = {
    "headline": "Answer every missed call within five minutes",
    "question": "Who answers your phone after 6 pm?",
    "quote": "A chatbot that books 12 tables a night beats hiring another waiter",
    "subline": "Forward missed calls to WhatsApp and send your booking link within 5 minutes.",
    "line": "Forward missed calls to WhatsApp and send the booking link within 5 minutes.",
    "big_number": "73%",
    "steps": ["Forward missed calls to WhatsApp", "Reply with a booking link in 5 minutes",
              "Send a reminder one day before", "Ask for a Google review after"],
    "mistakes": ["Calling back the next day", "Sending a generic email", "No booking link"],
    "fixes": ["Auto-reply by SMS in 5 minutes", "Send one booking link", "Add Calendly to Google"],
}
_ROMAN_SUBLINE = "Roman, Branded Genius"
_STAND_IN = ((91, 125, 177), (27, 43, 75))  # the gradient where the picture goes


def _copy(chosen: PostFormat, slide_type: str | None, number: int) -> dict[str, object]:
    fields, _ = chosen.layout(slide_type)
    copy: dict[str, object] = {}
    for name in fields:
        if name in ("illustration", "source"):
            continue
        if name == "icon":
            copy[name] = ICONS[number % len(ICONS)]
        elif name == "subline" and chosen.id == "roman_quote":
            copy[name] = _ROMAN_SUBLINE
        else:
            copy[name] = _SAMPLES.get(name, "Send the booking link within 5 minutes")
    return copy


def stand_in(size: tuple[int, int], person: bool) -> Image.Image:
    """A gradient where the picture goes (Roman: a soft head-and-shoulders shape)."""
    width, height = size
    top, bottom = _STAND_IN
    gradient = Image.linear_gradient("L").resize((width, height))
    image = Image.composite(Image.new("RGB", size, bottom), Image.new("RGB", size, top), gradient)
    if person:
        draw = ImageDraw.Draw(image)
        cx, side = width / 2, min(width, height)
        draw.ellipse((cx - side * 0.16, height * 0.18, cx + side * 0.16,
                      height * 0.18 + side * 0.36), fill=(150, 170, 205))
        draw.ellipse((cx - side * 0.42, height * 0.18 + side * 0.4, cx + side * 0.42,
                      height * 0.18 + side * 1.2), fill=(150, 170, 205))
    return image


def _logo(settings: Settings) -> LogoOverlay | None:
    try:
        ref = select_logo_ref(settings.references_dir)
        overlay = LogoOverlay(path=ref.path, source=ref.source, asset_id=ref.asset_id)
        check_logo(overlay)
    except (ReferenceLibraryError, LogoError):
        return None
    return overlay


def render_tile(chosen: PostFormat, catalog: FormatCatalog, system: DesignSystem,
                slide_type: str | None, number: int, logo: LogoOverlay | None) -> Image.Image:
    """One format (or slide) at its final size with a stand-in picture and the logo."""
    overlay: TextOverlay = format_overlay(
        chosen, _copy(chosen, slide_type, number), system,
        theme=catalog.themes[chosen.theme], slide_type=slide_type,
        step=number if slide_type == "body" else None,
    )
    image, _ = chosen.canvas(slide_type)
    picture = stand_in((540, 540), chosen.roman) if image is not None else None
    made = compose_format(picture, overlay)
    if logo is not None and slide_type in (None, "final"):
        buffer = io.BytesIO()
        made.save(buffer, format="PNG")
        data, _ = apply_logo(buffer.getvalue(), logo)
        with Image.open(io.BytesIO(data)) as source:
            made = source.convert("RGB")
    return made


def _tiles(settings: Settings) -> list[tuple[str, Image.Image]]:
    catalog = load_formats(settings.post_formats_file)
    system = load_design_system(settings.design_system_file)
    logo = _logo(settings)
    tiles: list[tuple[str, Image.Image]] = []
    for chosen in catalog.formats:
        if not chosen.slide_types:
            tiles.append((f"{chosen.id} ({chosen.theme})",
                          render_tile(chosen, catalog, system, None, 1, logo)))
            continue
        for slide_type, number in (("cover", 0), ("body", 1), ("body", 2), ("final", 0)):
            label = f"{chosen.id} {slide_type}{f' {number}' if slide_type == 'body' else ''}"
            tiles.append((label, render_tile(chosen, catalog, system, slide_type, number,
                                             logo)))
    return tiles


def format_sheet(settings: Settings, out: Path | None = None) -> tuple[Path, int]:
    """Render every format onto one PNG (default: outputs/review/format_sheet.png); returns
    the path and the number of tiles. Local and free; TextOverlayError when a text does not
    fit."""
    tiles = _tiles(settings)
    scaled = [(label, tile.resize((TILE_WIDTH, round(tile.height * TILE_WIDTH / tile.width)),
                                  Image.Resampling.LANCZOS)) for label, tile in tiles]
    rows = [scaled[n:n + COLUMNS] for n in range(0, len(scaled), COLUMNS)]
    heights = [max(tile.height for _, tile in row) + LABEL for row in rows]
    width = COLUMNS * TILE_WIDTH + (COLUMNS + 1) * GAP
    sheet = Image.new("RGB", (width, sum(heights) + (len(rows) + 1) * GAP), SHEET_BACKGROUND)
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=18)
    y = GAP
    for row, height in zip(rows, heights, strict=True):
        for column, (label, tile) in enumerate(row):
            x = GAP + column * (TILE_WIDTH + GAP)
            draw.text((x, y + 6), label, fill=(20, 28, 44), font=font)
            sheet.paste(tile, (x, y + LABEL))
        y += height + GAP
    path = out or SHEET_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path, format="PNG", optimize=True)
    return path, len(tiles)
