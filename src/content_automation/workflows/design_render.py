"""Render one design direction layout (config/design_directions.json) with Pillow.

Order: background (a token fill, the guide's blue or silver gradient, soft token glows), then
the zones in their config order: the picture (cropped into its box, a round slot, a cut-out or
full bleed; greyscale with a Sky Blue glow for "mono"), panels and scrims, text, items, icons,
footer, swipe marks, and the official logo placed by code. Every colour is a brand.json token,
so the brand tokens are the only colours the app paints.

Text is fit-or-fail like workflows/text_overlay.py: wrapped, then shrunk from the zone's size
down to its textLimits minimum; text that still does not fit is an error, never cut. Copy marks:
*word* = accent colour, **phrase** = bold, [[phrase]] = highlight pill. Before each text is
drawn, the canvas under it is measured (10th/90th percentile) and the contrast recorded:
headlines and large text need 3:1, other text 4.5:1 (workflows/design_check.py reads the
manifest). Diagrams, cards and UI panels are drawn here from the copy, never by an image model.

Composite layout (2026-10-21): the sub or body sits STACK_GAP_PX under the text drawn above it
(the headline), not at its zone's fixed place; on a Roman picture every text is narrowed (rewrapped
or shrunk by the fit) until it clears his glowing holograms and icons by HOLOGRAM_GAP_PX (the
boxes go into the manifest for the overlap check); the CTA icon follows its meaning (cta_icon).
Designer mode (place_brand_marks) covers the logo zone with a soft-edged plate in the dark
colour around it before the official logo goes on it.
"""

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

from content_automation.content.directions import (
    Background,
    Direction,
    DirectionCatalog,
    Layout,
    TextLimit,
    Zone,
)
from content_automation.references.brand import BrandProfile, TokenRole
from content_automation.workflows.design_system import OverlayFonts
from content_automation.workflows.logo import load_logo, white_version
from content_automation.workflows.text_overlay import TextOverlayError, contrast, resolve_fonts

RGB = tuple[int, int, int]
PixelBox = tuple[int, int, int, int]
BASE_WIDTH = 1080
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
FONT_FOLDER = "assets/fonts"
ICON_FONT = Path("assets/icons/tabler-icons.ttf")
ICON_CODES = Path("assets/icons/tabler-codepoints.json")
WEIGHTS: dict[str, list[str]] = {
    "regular": ["Regular", "Book", "Medium"],
    "medium": ["Medium", "Book"],
    "semibold": ["SemiBold", "Demi", "Bold"],
    "bold": ["Bold", "Demi"],
    "extrabold": ["ExtraBold", "Heavy", "Bold"],
}
_BOLDER = {"regular": "bold", "medium": "bold", "semibold": "extrabold", "bold": "extrabold",
           "extrabold": "extrabold"}
_MARK = re.compile(r"\*\*(.+?)\*\*|\*(.+?)\*|\[\[(.+?)\]\]")
_DARK_BELOW = 0.55  # mean brightness under the logo below which the white version is used
_FADE = 0.16  # share of a faded picture's box that blends into the background
STACK_GAP_PX = 32  # the design kit: a sub or body this far under the headline (at 1080 px)
HOLOGRAM_GAP_PX = 48  # every text this far from Roman's holograms and icons (at 1080 px)
_STACKED = ("sub", "body")
# a booking or an appointment: the only CTAs with the calendar icon (else the circle arrow)
_BOOKING = re.compile(r"termin|buchen|buchung|vereinbar|kalender|erstgespräch|"
                      r"beratungsgespräch|gespräch sichern|call sichern", re.IGNORECASE)


class DesignRenderError(TextOverlayError):
    """A direction cannot be rendered: a text does not fit, a field is missing, a bad icon."""


# --- Small helpers -----------------------------------------------------------------------------


def rgb(hex_value: str) -> RGB:
    value = hex_value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _luminance(color: RGB) -> float:
    def channel(value: int) -> float:
        share = value / 255
        return share / 12.92 if share <= 0.04045 else ((share + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color[0]) + 0.7152 * channel(color[1]) + 0.0722 * channel(color[2])


def _path(value: Path | str) -> Path:
    path = Path(value)
    return path if path.is_absolute() or path.exists() else _PROJECT_ROOT / path


@lru_cache(maxsize=256)
def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), max(6, size))


@lru_cache(maxsize=2)
def _icon_codes(path: str) -> dict[str, str]:
    import json

    data = json.loads(_path(path).read_text(encoding="utf-8"))
    return {str(name): chr(int(str(code), 16)) for name, code in data.items()}


def _lines(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    return [str(item).strip() for item in items if isinstance(item, str) and item.strip()]


def _split_item(text: str) -> tuple[str, str]:
    """'Title: description' -> (title, description); no colon: (text, "")."""
    head, sep, tail = text.partition(":")
    if sep and head.strip() and len(head.split()) <= 6:
        return head.strip(), tail.strip()
    return text.strip(), ""


def plain(text: str) -> str:
    """The copy without its marks, as a reader sees it."""
    return _MARK.sub(lambda m: next(g for g in m.groups() if g is not None), text)


# --- What a render records -------------------------------------------------------------------


@dataclass
class TextRecord:
    """One drawn text: where, which tokens, the measured contrast and the fit."""

    zone: str
    text: str
    box: PixelBox
    font_px: int
    min_font_px: int
    lines: int
    max_lines: int
    max_chars: int
    tokens: list[str]
    backdrop: tuple[RGB, RGB]
    contrast: float
    needed: float
    large: bool
    drawn: list[str] = field(default_factory=list)  # v5: the lines as drawn (hyphens shown)


@dataclass
class LogoRecord:
    file: str
    sha256: str
    box: PixelBox
    version: Literal["white", "full colour"]
    aspect_error: float
    width_px: int
    min_width_px: int
    clear_space_px: int


@dataclass
class Rendered:
    image: Image.Image
    direction: str
    layout: str
    size: tuple[int, int]
    texts: list[TextRecord] = field(default_factory=list)
    fills: list[tuple[str, str]] = field(default_factory=list)  # (zone, token)
    visual_boxes: list[PixelBox] = field(default_factory=list)
    logo: LogoRecord | None = None
    footer: list[str] = field(default_factory=list)  # the footer texts drawn
    notes: list[str] = field(default_factory=list)
    fonts: list[str] = field(default_factory=list)  # v5: the font files used (brand check)
    # v6 (R3.2/R3.6): each CTA button's text box, icon box and the gap between them
    ctas: list[dict[str, Any]] = field(default_factory=list)
    emblem: str | None = None  # v6: the "bg" emblem file on a carousel's last slide
    holograms: list[PixelBox] = field(default_factory=list)  # Roman's glowing holograms/icons

    def manifest(self) -> dict[str, Any]:
        return {
            "direction": self.direction, "layout": self.layout, "size": list(self.size),
            "texts": [vars(item) for item in self.texts],
            "fills": [list(item) for item in self.fills],
            "visualBoxes": [list(box) for box in self.visual_boxes],
            "logo": vars(self.logo) if self.logo else None,
            "footer": self.footer, "notes": self.notes, "fonts": self.fonts,
            "ctas": self.ctas, "emblem": self.emblem,
            "holograms": [list(box) for box in self.holograms],
        }


# --- Assets ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Assets:
    brand: BrandProfile
    logo_path: Path  # the official logo file (brand.json logoVariants full colour)
    fonts: dict[str, Path]  # weight -> font file
    emblem_path: Path | None = None  # v6: the "bg" emblem (brand.json logoVariants emblem)

    def token(self, role: str) -> RGB:
        if self.brand.tokens is None:
            raise DesignRenderError("brand.json has no tokens (Phase D)")
        return rgb(self.brand.tokens.get(role).hex)


def design_fonts(brand: BrandProfile) -> dict[str, Path]:
    """The brand family per weight (Futura when its files are in assets/fonts, else Jost)."""
    if brand.typography is None:
        raise DesignRenderError("brand.json has no typography (Phase D)")
    spec = OverlayFonts(folder=FONT_FOLDER, families=brand.typography.families(),
                        weights=WEIGHTS)
    return resolve_fonts(spec, set(WEIGHTS))


def emblem_file(brand: BrandProfile, references_dir: Path) -> Path | None:
    """v6: the official "bg" emblem (brand.json logoVariants id emblem), hash-checked; None when
    the brand file names none or it is not on this machine (the wordmark alone is placed)."""
    variant = next((v for v in brand.logo_variants if v.id == "emblem" and v.file), None)
    if variant is None or not (references_dir / variant.file).is_file():
        return None
    path = references_dir / variant.file
    if hashlib.sha256(path.read_bytes()).hexdigest() != variant.sha256:
        raise DesignRenderError(f"{path.name} is not the official emblem (brand.json sha256)")
    return path


def logo_file(brand: BrandProfile, references_dir: Path) -> Path:
    """The official logo: brand.json logoVariants (full colour), hash-checked."""
    variant = next((v for v in brand.logo_variants if v.file), None)
    if variant is None:
        raise DesignRenderError("brand.json logoVariants names no logo file")
    path = references_dir / variant.file
    if not path.is_file():
        raise DesignRenderError(f"The official logo {path} is missing (assets/reference is not "
                                "in git: copy the brand folder onto this machine).")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != variant.sha256:
        raise DesignRenderError(f"{path.name} is not the official logo (sha256 {digest[:12]}…, "
                                f"brand.json expects {variant.sha256[:12]}…)")
    return path


# --- Rich text ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Word:
    text: str
    style: Literal["plain", "accent", "bold", "pill"]
    group: int = -1  # pill words of one [[phrase]] share a group
    # v5 (PRD R1.5): long German words break only at their own hyphens or at a soft hyphen
    # (U+00AD) the writer set. glue: this fragment continues the word before it (no space);
    # soft: a soft hyphen follows, shown as "-" only when the line breaks there.
    glue: bool = False
    soft: bool = False


SOFT_HYPHEN = "\u00ad"
_BREAK = re.compile(r"(?<=[^\s\-\u00ad])(-|\u00ad)(?=[^\s\-\u00ad])")


def fragments(word: Word) -> list[Word]:
    """A word split at its break points: "KI-gestützte" -> "KI-" + "gestützte" (glued)."""
    parts: list[tuple[str, bool]] = []
    start = 0
    for match in _BREAK.finditer(word.text):
        if match.group(1) == "-":
            parts.append((word.text[start:match.end()], False))
        else:
            parts.append((word.text[start:match.start()], True))
        start = match.end()
    parts.append((word.text[start:].replace(SOFT_HYPHEN, ""), False))
    if len(parts) == 1:
        return [word if SOFT_HYPHEN not in word.text else Word(parts[0][0], word.style,
                                                                word.group)]
    return [Word(text, word.style, word.group, glue=index > 0, soft=soft)
            for index, (text, soft) in enumerate(parts)]


def parse(text: str, upper: bool = False) -> list[Word]:
    """Words with their mark; text touching a mark ("*word*?") joins that marked word."""
    words: list[Word] = []
    position = 0
    group = 0
    glue = False  # the next marked word continues the last plain word (no space between)

    def plain_words(part: str) -> None:
        nonlocal glue
        tokens = part.split()
        if tokens and words and part[:1].strip() and words[-1].style in ("accent", "bold"):
            last = words[-1]
            words[-1] = Word(last.text + tokens.pop(0), last.style, last.group)
        words.extend(Word(w, "plain") for w in tokens)
        glue = bool(part) and bool(part[-1:].strip()) and bool(tokens)

    for match in _MARK.finditer(text):
        plain_words(text[position:match.start()])
        bold, accent, pill = match.groups()
        style: Literal["bold", "accent", "pill"] = (
            "bold" if bold is not None else "accent" if accent is not None else "pill")
        marked = [Word(w, style, group if style == "pill" else -1)
                  for w in str(bold or accent or pill).split()]
        if glue and marked and style != "pill":
            marked[0] = Word(words.pop().text + marked[0].text, style)
        words += marked
        if style == "pill":
            group += 1
        position = match.end()
    plain_words(text[position:])
    if upper:
        words = [Word(w.text.upper(), w.style, w.group) for w in words]
    return [part for word in words for part in fragments(word)]


def _unglued(word: Word) -> Word:
    return Word(word.text, word.style, word.group, False, word.soft) if word.glue else word


def _joined(words: Sequence[Word]) -> str:
    return "".join(("" if index == 0 or w.glue else " ") + w.text
                   for index, w in enumerate(words))


@dataclass
class _Fitted:
    size: int
    lines: list[list[Word]]
    height: float
    width: float
    line_px: float


class Painter:
    """One canvas being drawn, with its tokens, fonts and the render record."""

    def __init__(self, size: tuple[int, int], assets: Assets, record: Rendered) -> None:
        self.size = size
        self.scale = size[0] / BASE_WIDTH
        self.assets = assets
        self.record = record
        self.image = Image.new("RGBA", size, (0, 0, 0, 255))

    # --- geometry
    def px(self, box: tuple[float, float, float, float]) -> PixelBox:
        width, height = self.size
        return (round(box[0] * width), round(box[1] * height), round(box[2] * width),
                round(box[3] * height))

    def s(self, value: float) -> int:
        return max(1, round(value * self.scale))

    def color(self, role: str) -> RGB:
        return self.assets.token(role)

    def fill(self, zone: str, role: str) -> RGB:
        self.record.fills.append((zone, role))
        return self.color(role)

    # --- compositing
    def paste(self, layer: Image.Image, at: tuple[int, int] = (0, 0)) -> None:
        self.image.alpha_composite(layer, at)

    def shape(self, draw: Any, zone: str, role: str, alpha: float = 1.0) -> None:
        """Draw with `draw(d, rgba)` on a transparent layer, then composite it."""
        layer = Image.new("RGBA", self.size, (0, 0, 0, 0))
        color = self.fill(zone, role)
        draw(ImageDraw.Draw(layer), (*color, round(255 * alpha)))
        self.paste(layer)

    def backdrop(self, box: PixelBox) -> tuple[RGB, RGB]:
        left, top, right, bottom = box
        left, top = max(0, left), max(0, top)
        right, bottom = min(self.size[0], right), min(self.size[1], bottom)
        if right <= left or bottom <= top:
            right, bottom = left + 1, top + 1
        region = self.image.crop((left, top, right, bottom)).convert("RGB")
        region.thumbnail((48, 48))
        pixels: list[RGB] = sorted(region.getdata(), key=_luminance)
        return pixels[len(pixels) // 10], pixels[len(pixels) * 9 // 10]

    # --- fonts and text
    def font(self, weight: str, size: int) -> ImageFont.FreeTypeFont:
        return _font(self.assets.fonts[weight], size)

    def word_width(self, word: Word, weight: str, size: int, tracking: float) -> float:
        font = self.font(_BOLDER[weight] if word.style == "bold" else weight, size)
        extra = tracking * size * max(0, len(word.text) - 1)
        return font.getlength(word.text) + extra

    def fit(self, words: list[Word], box: PixelBox, zone: Zone, limit: TextLimit) -> _Fitted:
        """The largest size at which the words wrap into the box within the limits."""
        width = box[2] - box[0]
        height = box[3] - box[1]
        largest = self.s(zone.size or limit.min_font_px)
        smallest = self.s(limit.min_font_px)
        pad = self._pill_pad(zone, largest)
        for size in range(max(largest, smallest), smallest - 1, -1):
            pad = self._pill_pad(zone, size)
            space = self.font(zone.weight, size).getlength(" ") + zone.tracking * size
            lines: list[list[Word]] = []
            current: list[Word] = []
            current_w = 0.0
            fits = True
            for word in words:
                w = self.word_width(word, zone.weight, size, zone.tracking)
                hyphen = self.word_width(Word("-", word.style), zone.weight, size,
                                         zone.tracking) if word.soft else 0.0
                if w + hyphen > width - 2 * pad[0]:
                    fits = False
                    break
                extra = w + (space if current and not word.glue else 0)
                if current and current_w + extra > width - 2 * pad[0]:
                    if word.glue and not current[-1].soft and not current[-1].text.endswith("-"):
                        fits = False  # never split a word where it has no break point
                        break
                    if current[-1].soft:  # the soft hyphen shows at the line end
                        last = current[-1]
                        current[-1] = Word(last.text + "-", last.style, last.group, last.glue)
                    lines.append(current)
                    current, current_w = [_unglued(word)], w
                else:
                    current.append(word)
                    current_w += extra
            if current:
                lines.append(current)
            if not fits or len(lines) > limit.max_lines:
                continue
            line_px = size * zone.line_height
            ascent, descent = self.font(zone.weight, size).getmetrics()
            total = ascent + descent + (len(lines) - 1) * line_px + 2 * pad[1]
            if total > height:
                continue
            widest = max(self._line_width(line, zone, size) for line in lines) + 2 * pad[0]
            return _Fitted(size, lines, total, widest, line_px)
        raise DesignRenderError(
            f"{self.record.direction} {zone.field or zone.kind}: "
            + '"' + _joined(words) + '"'
            + f" does not fit its zone at {limit.min_font_px} px or more in {limit.max_lines} "
            "line(s). Shorten it.")

    def _pill_pad(self, zone: Zone, size: int) -> tuple[float, float]:
        return (size * 0.7, size * 0.38) if zone.pill is not None else (0.0, 0.0)

    def _line_width(self, line: list[Word], zone: Zone, size: int) -> float:
        space = self.font(zone.weight, size).getlength(" ") + zone.tracking * size
        gaps = sum(1 for index, w in enumerate(line) if index and not w.glue)
        return sum(self.word_width(w, zone.weight, size, zone.tracking) for w in line) + (
            space * gaps)

    def text(self, name: str, zone: Zone, raw: str, layout: Layout,
             limit: TextLimit, box: PixelBox | None = None, color: str | None = None,
             weight: str | None = None, role_large: bool | None = None) -> PixelBox:
        """Fit, measure the backdrop, then draw one text; returns where it went."""
        words = parse(raw, zone.upper)
        if weight is not None:
            zone = zone.model_copy(update={"weight": weight})
        area = box or self.px(zone.box)
        if zone.vertical:
            return self._vertical(name, zone, raw, layout, limit, area)
        fitted = self.fit(words, area, zone, limit)
        pad_x, pad_y = self._pill_pad(zone, fitted.size)
        base = color or zone.color or layout.text_color()
        left, top, right, bottom = area
        width = fitted.width
        x0 = {"left": left, "center": left + (right - left - width) / 2,
              "right": right - width}[zone.align]
        y0 = {"top": top, "middle": top + (bottom - top - fitted.height) / 2,
              "bottom": bottom - fitted.height}[zone.valign]
        bounds = (round(x0), round(y0), round(x0 + width), round(y0 + fitted.height))
        if zone.pill is not None:
            pill = zone.pill
            radius = round((bounds[3] - bounds[1]) / 2)
            if pill.fill is not None:
                fill_role = pill.fill
                self.shape(lambda d, c: d.rounded_rectangle(bounds, radius=radius, fill=c),
                           name, fill_role, pill.alpha)
            if pill.outline is not None:
                outline_role = pill.outline
                self.shape(lambda d, c: d.rounded_rectangle(
                    bounds, radius=radius, outline=c, width=self.s(3)), name, outline_role)
        behind = self.backdrop(bounds)
        size = fitted.size
        large = role_large if role_large is not None else (
            zone.role in ("headline", "badge", "number") or size >= self.s(24) or (
                zone.weight in ("bold", "extrabold", "semibold") and size >= self.s(19)))
        needed = 3.0 if large else 4.5
        tokens: set[str] = {base}
        ascent, _ = self.font(zone.weight, size).getmetrics()
        layer = Image.new("RGBA", self.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        y = y0 + pad_y + ascent
        space = self.font(zone.weight, size).getlength(" ") + zone.tracking * size
        worst = 99.0
        for line in fitted.lines:
            line_w = self._line_width(line, zone, size)
            inner_left, inner_right = x0 + pad_x, x0 + width - pad_x
            x = {"left": inner_left, "center": inner_left + (inner_right - inner_left - line_w)
                 / 2, "right": inner_right - line_w}[zone.align]
            groups: dict[int, list[float]] = {}
            positions: list[tuple[float, Word]] = []
            for index, word in enumerate(line):
                if index and not word.glue:
                    x += space
                positions.append((x, word))
                w = self.word_width(word, zone.weight, size, zone.tracking)
                if word.style == "pill":
                    span = groups.setdefault(word.group, [x, x + w])
                    span[1] = x + w
                x += w
            for start, end in groups.values():  # [[phrase]]: a highlight pill behind it
                padding = size * 0.22
                # centred on the glyphs (caps to descenders); never taller than one line, so
                # the pill of one line does not cover the line above or below it
                half = size * 0.5 + padding * 0.5
                if len(fitted.lines) > 1:
                    half = min(half, fitted.line_px / 2 - self.s(1))
                middle = y - size * 0.24
                rect = (round(start - padding), round(middle - half), round(end + padding),
                        round(middle + half))
                draw.rounded_rectangle(rect, radius=round((rect[3] - rect[1]) / 2),
                                       fill=(*self.fill(name, zone.highlight), 255))
                tokens.add(zone.highlight)
            for x_word, word in positions:
                if word.style == "pill":
                    role: str = zone.highlight_text
                    against = (self.color(zone.highlight), self.color(zone.highlight))
                elif word.style == "accent":
                    role = zone.accent
                    against = behind
                else:
                    role = base
                    against = behind
                tokens.add(role)
                value = self.color(role)
                worst = min(worst, *(contrast(value, b) for b in against))
                weight_used = _BOLDER[zone.weight] if word.style == "bold" else zone.weight
                self._word(draw, x_word, y, word.text, self.font(weight_used, size), value,
                           zone.tracking * size)
            if zone.underline:
                start = positions[0][0] if positions else x0
                draw.line((start, y + size * 0.16, start + line_w, y + size * 0.16),
                          fill=(*self.color(base), 255), width=self.s(2))
            y += fitted.line_px
        self.paste(layer)
        self.record.texts.append(TextRecord(
            zone=name, text=plain(raw), box=bounds, font_px=round(size / self.scale),
            min_font_px=limit.min_font_px, lines=len(fitted.lines), max_lines=limit.max_lines,
            max_chars=limit.max_chars, tokens=sorted(tokens), backdrop=behind,
            contrast=round(worst, 2), needed=needed, large=large,
            drawn=[_joined(line) for line in fitted.lines]))
        if len(plain(raw)) > limit.max_chars:
            raise DesignRenderError(f"{self.record.direction} {name}: {len(plain(raw))} "
                                    f"characters, at most {limit.max_chars}: shorten it")
        return bounds

    def _word(self, draw: ImageDraw.ImageDraw, x: float, baseline: float, text: str,
              font: ImageFont.FreeTypeFont, color: RGB, tracking: float) -> None:
        if tracking <= 0:
            draw.text((x, baseline), text, font=font, fill=(*color, 255), anchor="ls")
            return
        for char in text:
            draw.text((x, baseline), char, font=font, fill=(*color, 255), anchor="ls")
            x += font.getlength(char) + tracking

    def _vertical(self, name: str, zone: Zone, raw: str, layout: Layout, limit: TextLimit,
                  area: PixelBox) -> PixelBox:
        """Rotated text (read bottom to top): drawn on a turned canvas, then turned back."""
        left, top, right, bottom = area
        turned = Painter((bottom - top, right - left), self.assets, self.record)
        turned.scale = self.scale
        turned.image = self.image.crop(area).rotate(-90, expand=True)
        straight = zone.model_copy(update={"vertical": False, "box": (0.0, 0.0, 1.0, 1.0)})
        turned.text(name, straight, raw, layout, limit, box=(0, 0, bottom - top, right - left))
        back = turned.image.rotate(90, expand=True)
        self.image.paste(back, (left, top))
        record = self.record.texts[-1]
        record.box = area
        return area

    # --- icons
    def icon(self, name: str, box: PixelBox, color: RGB) -> None:
        codes = _icon_codes(str(ICON_CODES))
        glyph = codes.get(name)
        if glyph is None:
            raise DesignRenderError(f"unknown icon {name!r} (assets/icons/tabler-codepoints.json)")
        side = min(box[2] - box[0], box[3] - box[1])
        font = _font(_path(ICON_FONT), max(8, round(side * 0.9)))
        layer = Image.new("RGBA", self.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), glyph,
                                   font=font, fill=(*color, 255), anchor="mm")
        self.paste(layer)


# --- Background and pictures -------------------------------------------------------------------


def _gradient(size: tuple[int, int], start: RGB, end: RGB, angle: int) -> Image.Image:
    """A linear gradient: angle 180 runs from the top (start) to the bottom (end), 0 the other
    way, 90 from left to right."""
    import numpy as np

    width, height = size
    radians = math.radians(angle)
    dx, dy = math.sin(radians), -math.cos(radians)
    xs = np.linspace(-0.5, 0.5, width)[None, :]
    ys = np.linspace(-0.5, 0.5, height)[:, None]
    t = xs * dx + ys * dy
    t = (t - t.min()) / max(1e-6, float(t.max() - t.min()))
    a, b = np.array(start, dtype=np.float32), np.array(end, dtype=np.float32)
    pixels = a[None, None, :] * (1 - t[..., None]) + b[None, None, :] * t[..., None]
    alpha = np.full((height, width, 1), 255, dtype=np.uint8)
    data = np.concatenate([pixels.round().astype(np.uint8), alpha], axis=2)
    return Image.fromarray(data, "RGBA")


def _glow(size: tuple[int, int], center: tuple[float, float], radius: float, color: RGB,
          opacity: float) -> Image.Image:
    width, height = size
    small = (max(8, width // 8), max(8, height // 8))
    mask = Image.new("L", small, 0)
    draw = ImageDraw.Draw(mask)
    cx, cy, r = center[0] * small[0], center[1] * small[1], radius * small[0]
    steps = 24
    for n in range(steps, 0, -1):
        share = n / steps
        value = round(255 * opacity * (1 - share) ** 1.6)
        draw.ellipse((cx - r * share, cy - r * share, cx + r * share, cy + r * share), fill=value)
    mask = mask.filter(ImageFilter.GaussianBlur(2)).resize(size, Image.Resampling.BICUBIC)
    layer = Image.new("RGBA", size, (*color, 0))
    layer.putalpha(mask)
    return layer


def paint_background(painter: Painter, background: Background) -> None:
    painter.record.fills.append(("background", background.fill))
    base = painter.color(background.fill)
    if background.gradient is not None:
        gradients = painter.assets.brand.gradients
        spec = gradients.get(background.gradient)
        if spec is None:
            raise DesignRenderError(f"brand.json has no {background.gradient} gradient")
        painter.record.fills += [("background", spec.from_), ("background", spec.to)]
        painter.image = _gradient(painter.size, painter.color(spec.from_),
                                  painter.color(spec.to), background.angle)
    else:
        painter.image = Image.new("RGBA", painter.size, (*base, 255))
    for role, x, y, radius, opacity in background.glows:
        painter.record.fills.append(("background", role))
        painter.paste(_glow(painter.size, (x, y), radius, painter.color(role), opacity))
    if background.vignette:
        painter.paste(_vignette(painter.size, background.vignette))


def _vignette(size: tuple[int, int], strength: float) -> Image.Image:
    """v6 (R3.2): the references' darkened edges, as a black layer stronger toward the corners."""
    import numpy as np

    width, height = size
    xs = np.linspace(-1, 1, width)[None, :]
    ys = np.linspace(-1, 1, height)[:, None]
    distance = np.clip(np.sqrt(xs ** 2 + ys ** 2) / math.sqrt(2), 0, 1)
    alpha = (np.clip((distance - 0.35) / 0.65, 0, 1) ** 1.6 * 255 * strength).astype(np.uint8)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    layer.putalpha(Image.fromarray(alpha, "L"))
    return layer


def _glow_line(painter: "Painter", mask: Image.Image, zone: str, role: str,
               alpha: float = 1.0) -> None:
    """A thin line (`mask`) with a soft glow around it, in one token colour (R3.2 outlines)."""
    color = painter.fill(zone, role)
    glow = mask.filter(ImageFilter.GaussianBlur(painter.s(7)))
    halo = Image.new("RGBA", painter.size, (*color, 0))
    halo.putalpha(glow.point(lambda value: round(min(255, value * 1.6) * 0.75 * alpha)))
    painter.paste(halo)
    line = Image.new("RGBA", painter.size, (*color, 0))
    line.putalpha(mask.point(lambda value: round(value * alpha)))
    painter.paste(line)


def _panel_mask(size: tuple[int, int], box: PixelBox, radius: int, cut: int,
                cut_left: bool) -> Image.Image:
    """A rounded panel with one angled cut corner at the top (toward the canvas centre)."""
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle(box, radius=radius, fill=255)
    if cut:
        left, top, right, _ = box
        corner = ([(left - 1, top - 1), (left + cut, top - 1), (left - 1, top + cut)] if cut_left
                  else [(right + 1, top - 1), (right - cut, top - 1), (right + 1, top + cut)])
        draw.polygon(corner, fill=0)
    return mask


def _fade_mask(size: tuple[int, int], edges: Sequence[str], share: float) -> Image.Image:
    width, height = size
    mask = Image.new("L", size, 255)
    pixels = mask.load()
    assert pixels is not None
    fx, fy = max(1, round(width * share)), max(1, round(height * share))
    columns = [1.0] * width
    rows = [1.0] * height
    for x in range(width):
        if "left" in edges and x < fx:
            columns[x] = min(columns[x], x / fx)
        if "right" in edges and x >= width - fx:
            columns[x] = min(columns[x], (width - 1 - x) / fx)
    for y in range(height):
        if "top" in edges and y < fy:
            rows[y] = min(rows[y], y / fy)
        if "bottom" in edges and y >= height - fy:
            rows[y] = min(rows[y], (height - 1 - y) / fy)
    column_img = Image.new("L", (width, 1))
    column_img.putdata([round(255 * value) for value in columns])
    row_img = Image.new("L", (1, height))
    row_img.putdata([round(255 * value) for value in rows])
    from PIL import ImageChops

    return ImageChops.multiply(column_img.resize(size), row_img.resize(size))


def _inner_edges(box: tuple[float, float, float, float]) -> list[str]:
    edges = []
    if box[0] > 0.001:
        edges.append("left")
    if box[1] > 0.001:
        edges.append("top")
    if box[2] < 0.999:
        edges.append("right")
    if box[3] < 0.999:
        edges.append("bottom")
    return edges


def place_picture(painter: Painter, name: str, zone: Zone, picture: Image.Image | None,
                  person: bool = False) -> None:
    """The picture in its zone: cover-cropped rect, round slot, cut-out or full bleed."""
    box = painter.px(zone.box)
    painter.record.visual_boxes.append(box)
    if picture is None:
        return
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    if zone.visual_shape == "cutout":
        cut = picture.convert("RGBA")
        ratio = min(width / cut.width, height / cut.height)
        target = (max(1, round(cut.width * ratio)), max(1, round(cut.height * ratio)))
        cut = cut.resize(target, Image.Resampling.LANCZOS)
        if zone.fade:  # the waist is cut by the frame: fade the bottom into the background
            alpha = cut.getchannel("A")
            fade = _fade_mask(cut.size, ["bottom"], 0.14)
            cut.putalpha(ImageChops.multiply(alpha, fade))
        x = left + (width - cut.width) // 2
        painter.paste(cut, (x, bottom - cut.height))
        return
    centering = (0.5, 0.32 if person else 0.5)
    fitted = ImageOps.fit(picture.convert("RGB"), (width, height), Image.Resampling.LANCZOS,
                          centering=centering)
    if zone.mono:
        fitted = ImageOps.grayscale(fitted).convert("RGB")
    layer = fitted.convert("RGBA")
    if zone.visual_shape == "circle":
        big = Image.new("L", (width * 4, height * 4), 0)
        ImageDraw.Draw(big).ellipse((0, 0, big.width - 1, big.height - 1), fill=255)
        layer.putalpha(big.resize((width, height), Image.Resampling.LANCZOS))
    elif zone.fade:
        layer.putalpha(_fade_mask((width, height), _inner_edges(zone.box), _FADE))
    painter.paste(layer, (left, top))
    if zone.mono:  # one Sky Blue glow on the greyscale picture
        painter.paste(_glow(painter.size, ((left + right) / 2 / painter.size[0],
                                           (top + bottom) / 2 / painter.size[1]),
                            0.42, painter.fill(name, "accent"), 0.42))
    if zone.visual_shape == "circle":
        ring = painter.s(4)
        painter.shape(lambda d, c: d.ellipse(box, outline=c, width=ring), name, "accent")


def placeholder(size: tuple[int, int], label: str, painter_colors: Mapping[str, RGB],
                person: bool = False, side: str = "right") -> Image.Image:
    """A free stand-in picture for previews (v6): a dark navy scene with a glowing network of
    rounded-square icon nodes on the visual side, like the approved references, and no text
    (the v5 "PLACEHOLDER" label ended up in a rejected image). `label` only seeds the layout."""
    import random

    width, height = size
    image = Image.new("RGB", size, (0, 5, 20))
    glow = Image.new("L", size, 0)
    cx = width * (0.7 if side == "right" else 0.3)
    ImageDraw.Draw(glow).ellipse((cx - width * 0.32, height * 0.2, cx + width * 0.32,
                                  height * 0.85), fill=120)
    glow = glow.filter(ImageFilter.GaussianBlur(max(4, width // 10)))
    image.paste(Image.new("RGB", size, painter_colors["primary"]), (0, 0), glow)
    rng = random.Random(label)
    lines = Image.new("L", size, 0)
    draw = ImageDraw.Draw(lines)
    hub = (cx, height * 0.52)
    node = max(12, round(min(width, height) * 0.075))
    nodes = []
    for n in range(6):
        angle = n / 6 * 2 * math.pi + rng.uniform(-0.25, 0.25)
        nodes.append((hub[0] + math.cos(angle) * width * 0.2,
                      hub[1] + math.sin(angle) * height * 0.2))
    for x, y in nodes:
        draw.line((hub[0], hub[1], x, y), fill=255, width=max(1, width // 400))
    for x, y in [hub, *nodes]:
        r = node * (1.4 if (x, y) == hub else 1)
        draw.rounded_rectangle((x - r, y - r, x + r, y + r), radius=round(r * 0.35), outline=255,
                               width=max(2, width // 300))
    halo = lines.filter(ImageFilter.GaussianBlur(max(2, width // 120)))
    image.paste(Image.new("RGB", size, painter_colors["primary"]), (0, 0), halo)
    image.paste(Image.new("RGB", size, painter_colors["accent"]), (0, 0), lines)
    if person:  # an anonymous figure in a navy suit (previews only; Roman is never drawn here)
        figure = ImageDraw.Draw(image)
        px = width * (0.86 if side == "right" else 0.14)
        figure.ellipse((px - width * 0.07, height * 0.18, px + width * 0.07, height * 0.36),
                       fill=(40, 52, 80))
        figure.rounded_rectangle((px - width * 0.16, height * 0.38, px + width * 0.16,
                                  height * 1.05), radius=round(width * 0.08), fill=(22, 30, 56))
    return image


# --- Zones -------------------------------------------------------------------------------------


def _shape(painter: Painter, name: str, zone: Zone) -> None:
    box = painter.px(zone.box)
    radius = round(zone.radius * painter.size[0])
    if zone.shape == "scrim" and zone.gradient is not None:
        spec = zone.gradient
        left, top, right, bottom = box
        width, height = right - left, bottom - top
        along = height if spec.toward in ("down", "up") else width
        ramp = [round(255 * (spec.start + (spec.end - spec.start) * n / max(1, along - 1)))
                for n in range(along)]
        if spec.toward in ("up", "left"):
            ramp.reverse()
        line = Image.new("L", (1, along) if spec.toward in ("down", "up") else (along, 1))
        line.putdata(ramp)
        mask = line.resize((width, height))
        across = [edge for edge in _inner_edges(zone.box)
                  if (edge in ("left", "right")) == (spec.toward in ("down", "up"))]
        if across:  # no hard edge where the scrim ends inside the canvas
            mask = ImageChops.multiply(mask, _fade_mask((width, height), across, 0.12))
        color = painter.fill(name, spec.color)
        layer = Image.new("RGBA", (width, height), (*color, 0))
        layer.putalpha(mask)
        painter.paste(layer, (left, top))
        return
    fill_role = zone.fill
    if zone.shape in ("panel", "glass") and zone.outline is not None:
        # v6 (R3.2): a dark-navy rounded panel, a thin glowing outline, one angled cut corner
        cut = round(zone.cut * (box[2] - box[0]))
        mask = _panel_mask(painter.size, box, radius, cut,
                           cut_left=(zone.box[0] + zone.box[2]) / 2 > 0.5)
        if fill_role is not None:
            panel_color = painter.fill(name, fill_role)
            layer = Image.new("RGBA", painter.size, (*panel_color, 0))
            layer.putalpha(mask.point(lambda value: round(value * zone.alpha)))
            painter.paste(layer)
        edge = ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(
            2 * painter.s(1.5) + 1)))
        _glow_line(painter, edge, name, zone.outline, 0.35 if zone.shape == "glass" else 1.0)
        return
    if zone.shape in ("chevrons", "bars", "wave", "arcs", "frame"):
        _decoration(painter, name, zone, box)
        return
    if zone.shape in ("panel", "glass", "bar", "pill") and fill_role is not None:
        role: str = fill_role
        painter.shape(lambda d, c: d.rounded_rectangle(box, radius=radius, fill=c), name, role,
                      zone.alpha)
        if zone.outline is not None:
            outline: str = zone.outline
            painter.shape(lambda d, c: d.rounded_rectangle(box, radius=radius, outline=c,
                                                           width=painter.s(2)),
                          name, outline, 0.35 if zone.shape == "glass" else 1.0)
    elif zone.shape in ("panel", "glass", "pill") and zone.outline is not None:
        line_role: str = zone.outline  # an outline-only panel (the references' glass frame)
        painter.shape(lambda d, c: d.rounded_rectangle(box, radius=radius, outline=c,
                                                       width=painter.s(3)), name, line_role,
                      zone.alpha)
    elif zone.shape == "dots" and fill_role is not None:
        dot_role: str = fill_role  # the references' dot grid (v5)
        step, dot = painter.s(26), painter.s(3)
        left, top, right, bottom = box

        def grid(d: Any, c: Any) -> None:
            for y in range(top + dot, bottom - dot + 1, step):
                for x in range(left + dot, right - dot + 1, step):
                    d.ellipse((x - dot, y - dot, x + dot, y + dot), fill=c)

        painter.shape(grid, name, dot_role, zone.alpha)
    elif zone.shape == "rule" and fill_role is not None:
        rule_role: str = fill_role
        painter.shape(lambda d, c: d.rectangle(box, fill=c), name, rule_role, zone.alpha)
    elif zone.shape == "ring":
        ring_role: str = zone.outline or fill_role or "accent"
        painter.shape(lambda d, c: d.ellipse(box, outline=c, width=painter.s(3)), name,
                      ring_role, zone.alpha)
    elif zone.shape == "glow" and fill_role is not None:
        z_left, z_top, z_right, z_bottom = zone.box
        painter.paste(_glow(painter.size, ((z_left + z_right) / 2, (z_top + z_bottom) / 2),
                            (z_right - z_left) / 2, painter.fill(name, fill_role), zone.alpha))


def _decoration(painter: Painter, name: str, zone: Zone, box: PixelBox) -> None:
    """v6 (R3.2) decorations from the references: a chevron row, diagonal blue bars, a
    particle-wave mesh, thin circle arcs touching the frame edges, thin frame corner lines."""
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    role: str = zone.fill or zone.outline or "primary"
    if zone.shape == "chevrons":
        arm = height * 0.42
        step = max(painter.s(14), round(height * 0.62))
        mid = (top + bottom) / 2
        painter.shape(lambda d, c: [d.line((x - arm * 0.6, mid - arm, x, mid, x - arm * 0.6,
                                            mid + arm), fill=c, width=painter.s(4))
                                    for x in range(round(left + arm), right, step)],
                      name, role, zone.alpha)
    elif zone.shape == "bars":
        slant = height
        thick = max(painter.s(10), round(width * 0.09))

        def bars(d: Any, c: Any) -> None:
            for n in range(3):
                x = left + n * thick * 2.1 - slant * 0.4
                d.polygon([(x, bottom), (x + thick, bottom), (x + thick + slant, top),
                           (x + slant, top)], fill=c)

        painter.shape(bars, name, role, zone.alpha)
    elif zone.shape == "wave":  # dots on stacked sine curves, brightest in the middle rows
        layer = Image.new("RGBA", painter.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        color = painter.fill(name, role)
        rows, columns = 14, max(24, width // painter.s(9))
        for row in range(rows):
            share = row / (rows - 1)
            for column in range(columns):
                t = column / (columns - 1)
                x = left + t * width
                y = top + height * (0.55 + 0.32 * math.sin(t * 5.2 + share * 2.4) * (
                    0.4 + share * 0.6) - 0.35 * share + 0.25)
                strength = (1 - abs(share - 0.5) * 1.4) * (0.35 + 0.65 * math.sin(t * math.pi))
                dot = painter.s(1.4 + 1.2 * strength)
                draw.ellipse((x - dot, y - dot, x + dot, y + dot),
                             fill=(*color, round(255 * zone.alpha * max(0.15, strength))))
        painter.paste(layer)
    elif zone.shape == "arcs":  # big thin circles centred off the canvas, touching its edges
        mask = Image.new("L", painter.size, 0)
        draw = ImageDraw.Draw(mask)
        w, h = painter.size
        for cx, cy, r in ((w * 1.02, h * -0.02, w * 0.3), (w * -0.06, h * 1.04, w * 0.24),
                          (w * 1.08, h * 0.98, w * 0.18)):
            draw.ellipse((cx - r, cy - r, cx + r, cy + r), outline=255, width=painter.s(3))
        _glow_line(painter, mask, name, role, zone.alpha)
    elif zone.shape == "frame":  # corner brackets of thin lines
        mask = Image.new("L", painter.size, 0)
        draw = ImageDraw.Draw(mask)
        arm_x, arm_y = round(width * 0.12), round(height * 0.09)
        line = painter.s(2)
        for x, y, dx, dy in ((left, top, 1, 1), (right, top, -1, 1), (left, bottom, 1, -1),
                             (right, bottom, -1, -1)):
            draw.line((x, y, x + dx * arm_x, y), fill=255, width=line)
            draw.line((x, y, x, y + dy * arm_y), fill=255, width=line)
        _glow_line(painter, mask, name, role, zone.alpha)


def cta_icon(text: str) -> tuple[str, str]:
    """The CTA's icon and its side by meaning (2026-10-21): the calendar (left) only for a
    booking or an appointment ("Termin buchen"), else the circle arrow (right)."""
    return ("calendar", "left") if _BOOKING.search(plain(text)) else ("arrow-right", "right")


def _cta(painter: Painter, name: str, zone: Zone, raw: str, layout: Layout,
         limit: TextLimit, area: PixelBox | None = None) -> None:
    """v6 (R3.2): the CTA as a wide rounded button: dark fill, glowing blue outline, white text
    and its icon (a circle-arrow on the right, or the calendar on the left for a booking) with a
    fixed gap, so the text never touches the icon. The geometry is recorded for the check."""
    icon_name, icon_side = cta_icon(raw)
    zone = zone.model_copy(update={"icon": icon_name, "icon_side": icon_side})
    box = area or painter.px(zone.box)
    left, top, right, bottom = box
    height = bottom - top
    radius = round(height * 0.32)
    pill = zone.pill
    if pill is not None and pill.fill is not None:
        fill_role: str = pill.fill
        painter.shape(lambda d, c: d.rounded_rectangle(box, radius=radius, fill=c), name,
                      fill_role, pill.alpha)
    mask = Image.new("L", painter.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=radius, outline=255, width=painter.s(2.5))
    _glow_line(painter, mask, name, pill.outline if pill and pill.outline else "accent")
    pad = round(height * 0.2)
    side = round(height * 0.6)
    gap = max(painter.s(16), round(height * 0.22))
    middle = (top + bottom) // 2
    if zone.icon_side == "left":
        icon = (left + pad, middle - side // 2, left + pad + side, middle + side // 2)
        text_box = (icon[2] + gap, top, right - pad - painter.s(8), bottom)
    else:
        icon = (right - pad - side, middle - side // 2, right - pad, middle + side // 2)
        text_box = (left + pad + painter.s(8), top, icon[0] - gap, bottom)
    color = painter.color("text_on_dark")
    if zone.icon in ("arrow-right", "play"):
        painter.shape(lambda d, c: d.ellipse(icon, outline=c, width=painter.s(2.5)), name,
                      "text_on_dark")
        cx, cy, arm = (icon[0] + icon[2]) / 2, (icon[1] + icon[3]) / 2, side * 0.22
        if zone.icon == "play":
            painter.shape(lambda d, c: d.polygon([(cx - arm * 0.6, cy - arm), (cx + arm, cy),
                                                  (cx - arm * 0.6, cy + arm)], fill=c), name,
                          "text_on_dark")
        else:
            painter.shape(lambda d, c: (d.line((cx - arm, cy, cx + arm, cy), fill=c,
                                               width=painter.s(2.5)),
                                        d.line((cx + arm * 0.15, cy - arm * 0.8, cx + arm, cy,
                                                cx + arm * 0.15, cy + arm * 0.8), fill=c,
                                               width=painter.s(2.5))), name, "text_on_dark")
    elif zone.icon:
        painter.icon(zone.icon, icon, color)
    style = zone.model_copy(update={"pill": None, "align": "center", "valign": "middle"})
    placed = painter.text(name, style, raw, layout, limit, box=text_box, color="text_on_dark")
    room = icon[0] - placed[2] if zone.icon_side != "left" else placed[0] - icon[2]
    painter.record.ctas.append({"zone": name, "text": list(placed), "icon": list(icon),
                                "gapPx": round(room / painter.scale)})


def _engagement(painter: Painter, name: str, zone: Zone, layout: Layout) -> None:
    """v6 (R3.2): the carousel's last-slide bar: three columns (LIKEN / TEILEN / SPEICHERN),
    each an outline icon, a bold label and a small line under it, divided by thin lines."""
    left, top, right, bottom = painter.px(zone.box)
    count = max(1, len(zone.labels))
    cell = (right - left) / count
    height = bottom - top
    limit = layout.text_limits.get(name, TextLimit(max_chars=24, max_lines=1, min_font_px=14))
    head = zone.model_copy(update={"kind": "text", "role": "body", "align": "center",
                                   "valign": "middle", "pill": None, "weight": "bold",
                                   "size": zone.size or 22})
    small = head.model_copy(update={"weight": "regular", "size": max(14, (zone.size or 22) - 7)})
    for index, label in enumerate(zone.labels):
        x0, x1 = round(left + cell * index), round(left + cell * (index + 1))
        side = round(height * 0.36)
        center = (x0 + x1) // 2
        icon = (center - side // 2, top, center + side // 2, top + side)
        if index < len(zone.names):
            painter.icon(zone.names[index], icon, painter.color("text_on_dark"))
        title, _, line = label.partition("|")
        painter.text(name, head, title.strip(), layout, limit,
                     box=(x0 + painter.s(6), top + side + painter.s(4), x1 - painter.s(6),
                          top + side + round(height * 0.32)), color="text_on_dark")
        if line.strip():
            painter.text(name, small, line.strip(), layout, limit,
                         box=(x0 + painter.s(6), top + side + round(height * 0.33),
                              x1 - painter.s(6), bottom), color="text_on_dark")
        if index:
            painter.shape(lambda d, c, x=x0: d.line((x, top + painter.s(6), x,
                                                     bottom - painter.s(6)), fill=c,
                                                    width=painter.s(1.5)), name, "primary")


def _footer_texts(brand: BrandProfile, zone: Zone, copy: Mapping[str, object]) -> list[str]:
    found: list[str] = []
    for element in zone.elements:
        if element == "website" and brand.website is not None:
            found.append(brand.website.display)
        elif element == "email" and brand.contact.email and brand.contact.email.on_graphics:
            found.append(brand.contact.email.value)
        elif element == "phone" and brand.contact.phone and brand.contact.phone.on_graphics:
            found.append(brand.contact.phone.value)
        elif element == "handles":
            found += [f"@{value.lstrip('@')}" for value in brand.social_handles().values()]
        elif element in ("cta", "tagline") and zone.field:
            found += _lines(copy.get(zone.field))[:1]
    return found


_FOOTER_ICONS = {"website": "world", "email": "mail", "phone": "phone"}


def _footer(painter: Painter, name: str, zone: Zone, layout: Layout,
            copy: Mapping[str, object]) -> None:
    brand = painter.assets.brand
    texts = _footer_texts(brand, zone, copy)
    painter.record.footer += texts
    if not texts:
        painter.record.notes.append(f"{name}: no footer element available ({zone.elements})")
        return
    box = painter.px(zone.box)
    if zone.fill is not None:
        bar_role: str = zone.fill
        painter.shape(lambda d, c: d.rectangle(box, fill=c), name, bar_role, zone.alpha)
    margin = painter.s(64)
    left, top, right, bottom = box
    if zone.bleed:
        left, right = max(left, margin), min(right, painter.size[0] - margin)
        top, bottom = top + painter.s(14), bottom - painter.s(14)
    limit = layout.text_limits[name]
    color = zone.color or ("text_on_light" if layout.theme == "light" and zone.fill is None
                           else "text_on_dark")
    labels = [e for e in zone.elements if e in _FOOTER_ICONS or e in ("cta", "tagline")]
    with_icons = zone.fill is not None or zone.icon is not None
    parts = len(texts)
    gap = painter.s(36)
    widths = [(right - left - gap * (parts - 1)) // parts] * parts
    x = left
    style = zone.model_copy(update={"valign": "middle", "pill": None})
    for index, text in enumerate(texts):
        element = labels[index] if index < len(labels) else "website"
        cell = (x, top, x + widths[index], bottom)
        icon_name = zone.icon if zone.icon and parts == 1 else _FOOTER_ICONS.get(element)
        icon_side = painter.s((zone.size or 24) * 1.05) if with_icons and icon_name else 0
        align = zone.align if parts == 1 else ("left" if index == 0 else "right")
        text_cell = cell
        if icon_side:
            if align == "right":
                text_cell = (cell[0], cell[1], cell[2] - icon_side - painter.s(12), cell[3])
            else:
                text_cell = (cell[0] + icon_side + painter.s(12), cell[1], cell[2], cell[3])
        placed = painter.text(name, style.model_copy(update={"align": align}), text, layout,
                              limit, box=text_cell, color=color)
        if icon_side and icon_name:
            middle = (placed[1] + placed[3]) // 2
            icon_x = placed[2] + painter.s(12) if align == "right" else placed[0] - icon_side - (
                painter.s(12))
            if parts == 1 and align == "center":
                icon_x = placed[0] - icon_side - painter.s(12)
            painter.icon(icon_name, (icon_x, middle - icon_side // 2, icon_x + icon_side,
                                     middle + icon_side // 2), painter.color(color))
        x += widths[index] + gap
    if zone.divider and parts == 2:
        middle_x = left + widths[0] + gap // 2
        line = (middle_x, top + painter.s(10), middle_x, bottom - painter.s(10))
        painter.shape(lambda d, c: d.line(line, fill=c, width=painter.s(2)), name, color, 0.6)


def _swipe(painter: Painter, name: str, zone: Zone, layout: Layout) -> None:
    box = painter.px(zone.box)
    color = layout.text_color()
    left, top, right, bottom = box
    height = bottom - top
    if zone.style == "arrow_circle":
        side = min(right - left, height)
        circle = (right - side, top + (height - side) // 2, right, top + (height + side) // 2)
        painter.shape(lambda d, c: d.ellipse(circle, outline=c, width=painter.s(3)), name, color)
        cx, cy = (circle[0] + circle[2]) / 2, (circle[1] + circle[3]) / 2
        arm = side * 0.2
        painter.shape(lambda d, c: (d.line((cx - arm, cy, cx + arm, cy), fill=c,
                                           width=painter.s(3)),
                                    d.line((cx + arm * 0.2, cy - arm * 0.8, cx + arm, cy, cx + arm
                                            * 0.2, cy + arm * 0.8), fill=c, width=painter.s(3))),
                      name, color)
        return
    label = (zone.label or "Swipe").strip()
    filled = zone.fill is not None
    text_role = "primary" if filled else color
    limit = TextLimit(max_chars=12, max_lines=1, min_font_px=16)
    style = zone.model_copy(update={"kind": "text", "role": "cta", "size": 26,
                                    "weight": "bold", "align": "center", "valign": "middle",
                                    "pill": None})
    radius = height // 2
    if filled:
        fill_role: str = zone.fill or "accent"
        painter.shape(lambda d, c: d.rounded_rectangle(box, radius=radius, fill=c), name,
                      fill_role)
    else:
        painter.shape(lambda d, c: d.rounded_rectangle(box, radius=radius, outline=c,
                                                       width=painter.s(2)), name, color)
    text_box = (left + painter.s(14), top, right - height // 2 - painter.s(10), bottom)
    placed = painter.text(name, style, label, layout, limit, box=text_box, color=text_role)
    cx = placed[2] + painter.s(18)
    cy = (top + bottom) / 2
    arm = height * 0.16
    for offset in (0.0, arm * 1.1):
        painter.shape(lambda d, c, o=offset: d.line(
            (cx + o - arm * 0.6, cy - arm, cx + o, cy, cx + o - arm * 0.6, cy + arm), fill=c,
            width=painter.s(3)), name, text_role)


def _arrow(painter: Painter, name: str, zone: Zone) -> None:
    left, top, right, bottom = painter.px(zone.box)
    points = []
    for n in range(41):
        t = n / 40
        x = left + (right - left) * (0.1 + 0.75 * t) + math.sin(t * 9) * painter.s(3)
        y = top + (bottom - top) * (0.05 + 0.8 * t ** 1.6)
        points.append((x, y))
    tip = points[-1]
    back = points[-6]
    angle = math.atan2(tip[1] - back[1], tip[0] - back[0])
    head = painter.s(26)
    wing = [(tip[0] - head * math.cos(angle - 0.5), tip[1] - head * math.sin(angle - 0.5)),
            tip, (tip[0] - head * math.cos(angle + 0.5), tip[1] - head * math.sin(angle + 0.5))]
    painter.shape(lambda d, c: (d.line(points, fill=c, width=painter.s(5), joint="curve"),
                                d.line(wing, fill=c, width=painter.s(5), joint="curve")),
                  name, "accent")


def _icons(painter: Painter, name: str, zone: Zone, layout: Layout,
           copy: Mapping[str, object], catalog: DirectionCatalog) -> None:
    if zone.style == "engagement":
        _engagement(painter, name, zone, layout)
        return
    labels = _lines(copy.get(zone.field)) if zone.field else list(zone.labels)
    names = _lines(copy.get(zone.icons_field)) if zone.icons_field else list(zone.names)
    count = max(len(labels), len(names))
    if count == 0:
        return
    for icon in names:
        if icon not in catalog.icons:
            raise DesignRenderError(f"{name}: icon {icon!r} is not allowed (config/"
                                    "design_directions.json icons)")
    left, top, right, bottom = painter.px(zone.box)
    cell = (right - left) / count
    side = min(bottom - top, painter.s(48))
    color = layout.text_color()
    limit = layout.text_limits.get(name, TextLimit(max_chars=24, max_lines=1, min_font_px=16))
    style = zone.model_copy(update={"kind": "text", "role": "body", "align": "left",
                                    "valign": "middle", "pill": None,
                                    "size": zone.size or 22})
    for index in range(count):
        x0 = round(left + cell * index)
        circle = (x0, top + (bottom - top - side) // 2, x0 + side, top + (bottom - top + side) // 2)
        painter.shape(lambda d, c, b=circle: d.ellipse(b, outline=c, width=painter.s(2.5)),
                      name, "accent")  # v6 (R3.2): circular outline icons
        if index < len(names):
            inset = round(side * 0.24)
            painter.icon(names[index], (circle[0] + inset, circle[1] + inset, circle[2] - inset,
                                        circle[3] - inset), painter.color("text_on_dark"))
        if index < len(labels):
            painter.text(name, style, labels[index], layout, limit,
                         box=(x0 + side + painter.s(12), top, round(x0 + cell) - painter.s(10),
                              bottom), color=color)


# --- Items (lists, cards, diagrams) ------------------------------------------------------------


def _item_style(zone: Zone, **update: Any) -> Zone:
    base: dict[str, Any] = {"kind": "text", "role": "body", "pill": None, "align": "left",
                            "valign": "top", "line_height": 1.12}
    base.update(update)
    return zone.model_copy(update=base)


def _card(painter: Painter, name: str, box: PixelBox, zone: Zone, radius: int) -> None:
    role: str = zone.card or "bg_light"
    shadow = (box[0] + painter.s(4), box[1] + painter.s(6), box[2] + painter.s(4),
              box[3] + painter.s(6))
    painter.shape(lambda d, c: d.rounded_rectangle(shadow, radius=radius, fill=c), name,
                  "bg_dark", 0.18)
    painter.shape(lambda d, c: d.rounded_rectangle(box, radius=radius, fill=c), name, role,
                  zone.card_alpha)


def _badge(painter: Painter, name: str, center: tuple[float, float], radius: float, label: str,
           fill: str, text_role: str, layout: Layout) -> None:
    cx, cy = center
    circle = (round(cx - radius), round(cy - radius), round(cx + radius), round(cy + radius))
    painter.shape(lambda d, c: d.ellipse(circle, fill=c), name, fill)
    zone = Zone(kind="text", box=(0.0, 0.0, 1.0, 1.0), field="n", role="number",
                size=max(8, round(radius * 1.05 / painter.scale)), weight="bold",
                align="center", valign="middle")
    painter.text(name, zone, label, layout, TextLimit(max_chars=4, max_lines=1, min_font_px=8),
                 box=circle, color=text_role, role_large=True)


def _items(painter: Painter, name: str, zone: Zone, layout: Layout, copy: Mapping[str, object],
           catalog: DirectionCatalog, step: int, visual_box: PixelBox | None) -> None:
    items = _lines(copy.get(str(zone.field)))
    icons = _lines(copy.get(zone.icons_field)) if zone.icons_field else []
    low, high = zone.count or (1, 6)
    if not low <= len(items) <= high:
        raise DesignRenderError(f"{painter.record.direction} {name}: {low}-{high} items, found "
                                f"{len(items)}")
    if icons and len(icons) != len(items):
        raise DesignRenderError(f"{painter.record.direction} {name}: one icon per item "
                                f"({len(items)} items, {len(icons)} icons)")
    for icon in icons:
        if icon not in catalog.icons:
            raise DesignRenderError(f"{name}: icon {icon!r} is not allowed (config/"
                                    "design_directions.json icons)")
    limit = layout.text_limits[name]
    box = painter.px(zone.box)
    text_role = layout.text_color()
    layout_kind = zone.layout
    if layout_kind in ("icon_list", "bullets", "pairs"):
        _stacked(painter, name, zone, layout, items, icons, box, limit, text_role)
    elif layout_kind in ("numbered_cards", "floating_cards"):
        _cards(painter, name, zone, layout, items, icons, box, limit, step)
    elif layout_kind == "zigzag":
        _zigzag(painter, name, zone, layout, items, icons, box, limit)
    elif layout_kind == "cycle":
        _cycle(painter, name, zone, layout, items, icons, box, limit)
    elif layout_kind == "orbit":
        _orbit(painter, name, zone, layout, items, icons, box, limit, visual_box)
    elif layout_kind == "value_map":
        _value_map(painter, name, zone, layout, items, icons, box, limit, visual_box)


def _stacked(painter: Painter, name: str, zone: Zone, layout: Layout, items: list[str],
             icons: list[str], box: PixelBox, limit: TextLimit, text_role: str) -> None:
    left, top, right, bottom = box
    count = len(items)
    row = (bottom - top) / count
    size = zone.size or 28
    for index, item in enumerate(items):
        y0 = round(top + row * index)
        y1 = round(top + row * (index + 1) - painter.s(10))
        if zone.layout == "icon_list":
            side = min(painter.s(size * 2.2), y1 - y0)
            circle = (left, y0, left + side, y0 + side)
            painter.shape(lambda d, c, b=circle: d.ellipse(b, fill=c), name, "accent")
            if index < len(icons):
                inset = round(side * 0.24)
                painter.icon(icons[index], (circle[0] + inset, circle[1] + inset,
                                            circle[2] - inset, circle[3] - inset),
                             painter.color("primary"))
            painter.text(name, _item_style(zone, valign="top"), item, layout, limit,
                         box=(left + side + painter.s(22), y0 + painter.s(2), right, y1),
                         color=text_role)
        elif zone.layout == "bullets":
            dot = painter.s(size * 0.32)
            cy = y0 + painter.s(size * 0.62)
            bullet = (left, cy - dot // 2, left + dot, cy + dot // 2)
            painter.shape(lambda d, c, b=bullet: d.ellipse(b, fill=c), name, "accent")
            painter.text(name, _item_style(zone), item, layout, limit,
                         box=(left + dot + painter.s(22), y0, right, y1), color=text_role)
        else:  # pairs: a bold label in the accent colour, then the description
            title, text = _split_item(item)
            label_h = round(painter.s(size) * 1.35)
            painter.text(name, _item_style(zone, weight="bold", role="headline"), title, layout,
                         limit, box=(left, y0, right, y0 + label_h), color="accent")
            if text:
                painter.text(name, _item_style(zone, weight="medium",
                                               size=max(limit.min_font_px, round(size * 0.82))),
                             text, layout, limit, box=(left, y0 + label_h, right, y1),
                             color=text_role)


def _card_texts(painter: Painter, name: str, zone: Zone, layout: Layout, item: str,
                inner: PixelBox, limit: TextLimit, title_scale: float = 1.0,
                text_scale: float = 0.78) -> None:
    """Title and line of one card, measured first and centred in the card as one block."""
    title, text = _split_item(item)
    size = zone.size or 24
    left, top, right, bottom = inner
    title_h = round(painter.s(size * title_scale) * 1.3 * (2 if len(title) > 26 else 1))
    title_h = min(title_h, bottom - top)
    gap = painter.s(4)
    title_style = _item_style(zone, weight="bold", role="headline",
                              size=max(limit.min_font_px, round(size * title_scale)))
    text_style = _item_style(zone, weight="medium",
                             size=max(limit.min_font_px, round(size * text_scale)))
    used_title = math.ceil(painter.fit(parse(title, zone.upper), (left, top, right, top + title_h),
                                       title_style, limit).height)
    used_text = 0
    has_text = bool(text) and bottom - top - title_h > painter.s(limit.min_font_px)
    if has_text:
        used_text = math.ceil(painter.fit(parse(text, zone.upper),
                                          (left, top + title_h + gap, right, bottom),
                                          text_style, limit).height)
    block = used_title + (gap + used_text if has_text else 0)
    y = top + max(0, (bottom - top - block) // 2)
    painter.text(name, title_style, title, layout, limit,
                 box=(left, y, right, y + used_title + 1), color="text_on_light")
    if has_text:
        y += used_title + gap
        painter.text(name, text_style, text, layout, limit,
                     box=(left, y, right, y + used_text + 1), color="text_on_light")


def _cards(painter: Painter, name: str, zone: Zone, layout: Layout, items: list[str],
           icons: list[str], box: PixelBox, limit: TextLimit, step: int) -> None:
    left, top, right, bottom = box
    count = len(items)
    gap = painter.s(28 if zone.layout == "numbered_cards" else 18)
    height = (bottom - top - gap * (count - 1)) / count
    radius = painter.s(30 if zone.layout == "numbered_cards" else 22)
    for index, item in enumerate(items):
        y0 = round(top + (height + gap) * index)
        y1 = round(y0 + height)
        if zone.layout == "floating_cards":  # small cards, slightly staggered
            shift = painter.s(36) if index % 2 else 0
            card = (left + shift, y0, right - painter.s(36) + shift, y1)
        else:
            card = (left, y0 + painter.s(22), right, y1)
        _card(painter, name, card, zone, radius)
        pad = painter.s(26)
        inner_left = card[0] + pad
        if zone.layout == "numbered_cards":
            badge_r = painter.s(44)
            _badge(painter, name, (card[0] + badge_r + pad * 0.5, card[1]), badge_r,
                   f"{step + index + 1:02d}", "accent", "primary", layout)
            inner = (inner_left, card[1] + badge_r + painter.s(6), card[2] - pad, card[3] - pad)
            _card_texts(painter, name, zone, layout, item, inner, limit, 1.0, 0.8)
        else:
            side = min(painter.s(56), card[3] - card[1] - 2 * pad)
            circle = (inner_left, card[1] + (card[3] - card[1] - side) // 2, inner_left + side,
                      card[1] + (card[3] - card[1] + side) // 2)
            painter.shape(lambda d, c, b=circle: d.ellipse(b, fill=c), name, "accent")
            if index < len(icons):
                inset = round(side * 0.22)
                painter.icon(icons[index], (circle[0] + inset, circle[1] + inset,
                                            circle[2] - inset, circle[3] - inset),
                             painter.color("primary"))
            inner = (circle[2] + painter.s(16), card[1] + painter.s(14), card[2] - pad,
                     card[3] - painter.s(14))
            _card_texts(painter, name, zone, layout, item, inner, limit, 1.0, 0.82)


def _zigzag(painter: Painter, name: str, zone: Zone, layout: Layout, items: list[str],
            icons: list[str], box: PixelBox, limit: TextLimit) -> None:
    left, top, right, bottom = box
    count = len(items)
    row = (bottom - top) / count
    card_w = round((right - left) * 0.7)
    radius = painter.s(60)
    cards: list[PixelBox] = []
    for index in range(count):
        x0 = left if index % 2 == 0 else right - card_w
        cards.append((x0, round(top + row * index + painter.s(8)), x0 + card_w,
                      round(top + row * (index + 1) - painter.s(8))))
    centers = [((card[0] + card[2]) / 2, (card[1] + card[3]) / 2) for card in cards]
    for (ax, ay), (bx, by) in zip(centers, centers[1:], strict=False):  # under the cards
        dots = 9
        for n in range(1, dots):
            t = n / dots
            cx, cy = ax + (bx - ax) * t, ay + (by - ay) * t
            r = painter.s(3)
            painter.shape(lambda d, c, cx=cx, cy=cy, r=r: d.ellipse(
                (cx - r, cy - r, cx + r, cy + r), fill=c), name, "muted")
    # Sky Blue is under 3:1 on white: the step number is marked only on dark designs
    step_label = "STEP {:02d}" if layout.theme == "light" else "STEP *{:02d}*"
    for index, (item, card) in enumerate(zip(items, cards, strict=True)):
        on_left = index % 2 == 0
        painter.shape(lambda d, c, b=card: d.rounded_rectangle(b, radius=radius, outline=c,
                                                               width=painter.s(3)),
                      name, "accent")
        _card(painter, name, (card[0] + painter.s(3), card[1] + painter.s(3),
                              card[2] - painter.s(3), card[3] - painter.s(3)),
              zone, radius)
        side = min(card[3] - card[1] - painter.s(24), painter.s(84))
        circle = (card[0] + painter.s(14), card[1] + (card[3] - card[1] - side) // 2,
                  card[0] + painter.s(14) + side, card[1] + (card[3] - card[1] + side) // 2)
        painter.shape(lambda d, c, b=circle: d.ellipse(b, fill=c), name, "primary")
        if index < len(icons):
            inset = round(side * 0.24)
            painter.icon(icons[index], (circle[0] + inset, circle[1] + inset, circle[2] - inset,
                                        circle[3] - inset), painter.color("bg_light"))
        inner = (circle[2] + painter.s(18), card[1] + painter.s(16), card[2] - painter.s(36),
                 card[3] - painter.s(12))
        _card_texts(painter, name, zone, layout, item, inner, limit, 1.0, 0.8)
        label_box = (card[2] + painter.s(20), card[1], right, card[3]) if on_left else (
            left, card[1], card[0] - painter.s(20), card[3])
        number = Zone(kind="text", box=(0.0, 0.0, 1.0, 1.0), field="n", role="number",
                      size=56, weight="extrabold", align="center", valign="middle",
                      line_height=1.0)
        painter.text(name, number, step_label.format(index + 1), layout,
                     TextLimit(max_chars=8, max_lines=2, min_font_px=20), box=label_box,
                     color="primary", role_large=True)


def _cycle(painter: Painter, name: str, zone: Zone, layout: Layout, items: list[str],
           icons: list[str], box: PixelBox, limit: TextLimit) -> None:
    left, top, right, bottom = box
    cx, cy = (left + right) / 2, (top + bottom) / 2
    radius = min(right - left, bottom - top) * 0.33
    ring = (round(cx - radius), round(cy - radius), round(cx + radius), round(cy + radius))
    painter.shape(lambda d, c: d.ellipse(ring, outline=c, width=painter.s(4)), name, "accent")
    hub = painter.s(70)
    painter.shape(lambda d, c: d.ellipse((cx - hub, cy - hub, cx + hub, cy + hub), fill=c), name,
                  "primary")
    painter.icon("refresh", (round(cx - hub * 0.6), round(cy - hub * 0.6), round(cx + hub * 0.6),
                             round(cy + hub * 0.6)), painter.color("bg_light"))
    count = len(items)
    node = painter.s(52)
    card_w, card_h = painter.s(300), painter.s(150)
    for index, item in enumerate(items):
        angle = -math.pi / 2 + 2 * math.pi * index / count
        nx, ny = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
        painter.shape(lambda d, c, nx=nx, ny=ny: d.ellipse((nx - node, ny - node, nx + node,
                                                            ny + node), fill=c), name, "primary")
        if index < len(icons):
            inset = round(node * 0.55)
            painter.icon(icons[index], (round(nx - node + inset), round(ny - node + inset),
                                        round(nx + node - inset), round(ny + node - inset)),
                         painter.color("bg_light"))
        _badge(painter, name, (nx + node * 0.8, ny - node * 0.8), painter.s(20),
               f"{index + 1}", "accent", "primary", layout)
        outward_x, outward_y = math.cos(angle), math.sin(angle)
        bx = nx + outward_x * (node + card_w * 0.55) - card_w / 2
        by = ny + outward_y * (node + card_h * 0.6) - card_h / 2
        bx = min(max(bx, left), right - card_w)
        by = min(max(by, top), bottom - card_h)
        card = (round(bx), round(by), round(bx + card_w), round(by + card_h))
        _card(painter, name, card, zone, painter.s(18))
        inner = (card[0] + painter.s(16), card[1] + painter.s(12), card[2] - painter.s(14),
                 card[3] - painter.s(10))
        _card_texts(painter, name, zone, layout, item, inner, limit, 0.9, 0.72)


def _orbit(painter: Painter, name: str, zone: Zone, layout: Layout, items: list[str],
           icons: list[str], box: PixelBox, limit: TextLimit,
           visual_box: PixelBox | None) -> None:
    left, top, right, bottom = box
    count = len(items)
    per_row = 3 if count > 3 else count
    rows = math.ceil(count / per_row)
    gap = painter.s(18)
    card_w = (right - left - gap * (per_row - 1)) / per_row
    card_h = (bottom - top - painter.s(30) - gap * (rows - 1)) / rows
    arc_y = top + painter.s(12)
    painter.shape(lambda d, c: d.arc((left - painter.s(80), arc_y - painter.s(40),
                                      right + painter.s(80), arc_y + painter.s(260)),
                                     start=190, end=350, fill=c, width=painter.s(2)),
                  name, "muted")
    for index, item in enumerate(items):
        row, column = divmod(index, per_row)
        x0 = round(left + column * (card_w + gap))
        y0 = round(top + painter.s(30) + row * (card_h + gap))
        card = (x0, y0, round(x0 + card_w), round(y0 + card_h))
        _card(painter, name, card, zone, painter.s(18))
        painter.shape(lambda d, c, b=card: d.rounded_rectangle(b, radius=painter.s(18),
                                                               outline=c, width=painter.s(2)),
                      name, "accent")
        dot = painter.s(7)
        mx = (card[0] + card[2]) / 2
        pin = (round(mx - dot), card[1] - dot, round(mx + dot), card[1] + dot)
        painter.shape(lambda d, c, b=pin: d.ellipse(b, fill=c), name, "accent")
        pad = painter.s(16)
        number_box = (card[0] + pad, card[1] + pad, card[0] + pad + painter.s(48),
                      card[1] + pad + painter.s(30))
        number = Zone(kind="text", box=(0.0, 0.0, 1.0, 1.0), field="n", role="number", size=24,
                      weight="extrabold", line_height=1.0)
        painter.text(name, number, f"{index + 1:02d}", layout,
                     TextLimit(max_chars=3, max_lines=1, min_font_px=14), box=number_box,
                     color="primary", role_large=True)
        if index < len(icons):
            side = painter.s(30)
            painter.icon(icons[index], (card[2] - pad - side, card[1] + pad, card[2] - pad,
                                        card[1] + pad + side), painter.color("primary"))
        inner = (card[0] + pad, number_box[3] + painter.s(6), card[2] - pad, card[3] - pad)
        _card_texts(painter, name, zone, layout, item, inner, limit, 1.0, 0.8)
    del visual_box


def _value_map(painter: Painter, name: str, zone: Zone, layout: Layout, items: list[str],
               icons: list[str], box: PixelBox, limit: TextLimit,
               visual_box: PixelBox | None) -> None:
    left, top, right, bottom = box
    if visual_box is None:
        visual_box = (round(left + (right - left) * 0.3), round(top + (bottom - top) * 0.2),
                      round(left + (right - left) * 0.7), round(top + (bottom - top) * 0.75))
    vcx, vcy = (visual_box[0] + visual_box[2]) / 2, (visual_box[1] + visual_box[3]) / 2
    vr = (visual_box[2] - visual_box[0]) / 2
    card_w = round((visual_box[0] - left) * 1.02)
    card_h = painter.s(118)
    spots = [(left, top + painter.s(10)), (right - card_w, top + painter.s(10)),
             (left, visual_box[3] - card_h - painter.s(20)),
             (right - card_w, visual_box[3] - card_h - painter.s(20)),
             (round(vcx - card_w / 2), bottom - card_h)]
    if len(items) == 4:
        spots = spots[:4]
    for index, item in enumerate(items):
        x0, y0 = spots[index]
        card = (round(x0), round(y0), round(x0 + card_w), round(y0 + card_h))
        ccx, ccy = (card[0] + card[2]) / 2, (card[1] + card[3]) / 2
        angle = math.atan2(ccy - vcy, ccx - vcx)
        start = (vcx + vr * math.cos(angle), vcy + vr * math.sin(angle))
        end = (min(max(start[0], card[0]), card[2]), min(max(start[1], card[1]), card[3]))
        painter.shape(lambda d, c, s=start, e=end: d.line((s, e), fill=c, width=painter.s(2)),
                      name, "muted")
        _card(painter, name, card, zone, card_h // 2)
        painter.shape(lambda d, c, b=card: d.rounded_rectangle(b, radius=card_h // 2,
                                                               outline=c, width=painter.s(2)),
                      name, "primary")
        side = painter.s(52)
        circle = (card[0] + painter.s(14), card[1] + (card_h - side) // 2,
                  card[0] + painter.s(14) + side, card[1] + (card_h + side) // 2)
        painter.shape(lambda d, c, b=circle: d.ellipse(b, fill=c), name, "accent")
        if index < len(icons):
            inset = round(side * 0.22)
            painter.icon(icons[index], (circle[0] + inset, circle[1] + inset, circle[2] - inset,
                                        circle[3] - inset), painter.color("primary"))
        painter.text(name, _item_style(zone, valign="middle"), item, layout, limit,
                     box=(circle[2] + painter.s(12), card[1] + painter.s(8),
                          card[2] - painter.s(18), card[3] - painter.s(8)),
                     color="text_on_light")


# --- The logo ----------------------------------------------------------------------------------


def place_logo(painter: Painter, zone: Zone, layout: Layout, emblem: bool = False) -> None:
    """The official file: aspect kept, clear space inside its zone, white on dark or photo.
    emblem (v6, the carousel's last slide): the "bg" emblem above the wordmark."""
    brand = painter.assets.brand
    spec = brand.logo_spec
    ratio = spec.clear_space_ratio if spec else 0.25
    minimum = painter.s(spec.min_width_px if spec else 160)
    logo = load_logo(painter.assets.logo_path)
    aspect = logo.width / logo.height
    left, top, right, bottom = painter.px(zone.box)
    if emblem and painter.assets.emblem_path is not None:
        mark = load_logo(painter.assets.emblem_path)
        mark_h = round((bottom - top) * 0.3)
        mark_w = round(mark_h * mark.width / mark.height)
        x_mark = right - mark_w - round((right - left) * 0.18)
        painter.paste(mark.resize((mark_w, mark_h), Image.Resampling.LANCZOS), (x_mark, top))
        painter.record.emblem = painter.assets.emblem_path.name
        top += mark_h + painter.s(4)
    width, height = right - left, bottom - top
    logo_h = min(height / (1 + 2 * ratio), width / (aspect + 2 * ratio))
    logo_w = logo_h * aspect
    if logo_w + 0.5 < minimum:
        raise DesignRenderError(f"{painter.record.direction}: the logo zone gives the logo "
                                f"{logo_w:.0f} px, less than its minimum {minimum} px (brand.json "
                                "logoSpec): widen the zone")
    clear = round(logo_h * ratio)
    center = (left + right) / 2 / painter.size[0]
    if 0.4 < center < 0.6:
        x = left + (width - logo_w) / 2
    elif zone.box[0] >= 0.5:
        x = right - clear - logo_w
    else:
        x = left + clear
    y = top + (height - logo_h) / 2
    # whole pixels from the height, so rounding never stretches the logo (v5)
    whole_h = max(1, round(logo_h))
    whole_w = max(1, round(whole_h * aspect))
    target = (round(x), round(y), round(x) + whole_w, round(y) + whole_h)
    region = painter.image.crop(target).convert("L")
    brightness = sum(region.getdata()) / max(1, region.width * region.height) / 255
    version: Literal["white", "full colour"] = (
        "white" if layout.theme == "photo" or brightness < _DARK_BELOW else "full colour")
    chosen = white_version(logo) if version == "white" else logo
    sized = chosen.resize((target[2] - target[0], target[3] - target[1]),
                          Image.Resampling.LANCZOS)
    painter.paste(sized, (target[0], target[1]))
    digest = hashlib.sha256(painter.assets.logo_path.read_bytes()).hexdigest()
    painter.record.logo = LogoRecord(
        file=painter.assets.logo_path.name, sha256=digest, box=target, version=version,
        aspect_error=round(abs((target[2] - target[0]) / (target[3] - target[1]) - aspect)
                           / aspect, 4),
        width_px=round((target[2] - target[0]) / painter.scale),
        min_width_px=spec.min_width_px if spec else 160, clear_space_px=clear)


def _logo_plate(painter: Painter, zone: Zone) -> None:
    """Designer mode (2026-10-21): a small plate over the logo zone in the dark colour sampled
    around it (the darker half of the ring; the base token when that is not dark), with a soft
    edge, so a decoration the model drew in the corner never shows behind the real logo. A
    wordmark or text that reaches out of the plate is still read back and fails the image."""
    import numpy as np

    left, top, right, bottom = painter.px(zone.box)
    soft = painter.s(18)
    width, height = painter.size
    ring = (max(0, left - 3 * soft), max(0, top - 3 * soft), min(width, right + 3 * soft),
            min(height, bottom + 3 * soft))
    pixels = np.asarray(painter.image.convert("RGB").crop(ring), dtype=np.float64)
    inside = np.zeros(pixels.shape[:2], dtype=bool)
    inside[max(0, top - ring[1]):bottom - ring[1], max(0, left - ring[0]):right - ring[0]] = True
    around = pixels[~inside] if (~inside).any() else pixels.reshape(-1, 3)
    light = around.sum(axis=1)
    median = np.median(around[light <= np.median(light)], axis=0)
    colour: RGB = (int(median[0]), int(median[1]), int(median[2]))
    base = painter.color("bg_dark")
    if max(colour) > max(base) + 40:  # not a dark navy there: the base token instead
        colour = base
    mask = Image.new("L", painter.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((left - soft, top - soft, right + soft, bottom + soft),
                                           radius=soft, fill=255)
    plate = Image.new("RGBA", painter.size, (*colour, 255))
    painter.image = Image.composite(plate, painter.image,
                                    mask.filter(ImageFilter.GaussianBlur(soft / 2)))
    painter.record.notes.append(f"logo plate rgb{colour} over the logo zone")


def hologram_boxes(image: Image.Image, person_right: bool) -> list[PixelBox]:
    """Roman's glowing holograms and icons (bright blue or cyan regions reaching into his half
    of the canvas, 2026-10-21): every text keeps HOLOGRAM_GAP_PX from them, not only from his
    third. A region wider than 60% of the canvas is a background wash, not an icon."""
    import cv2
    import numpy as np

    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    hue, sat, val = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    raw = ((hue >= 85) & (hue <= 130) & (sat >= 80) & (val >= 140)).astype(np.uint8)
    opened = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    glow = cv2.dilate(opened, np.ones((9, 9), np.uint8))  # one box per icon, not per line
    count, _, stats, _ = cv2.connectedComponentsWithStats(glow, connectivity=8)
    min_area = max(30, round(width * height * 0.0004))
    boxes: list[PixelBox] = []
    for index in range(1, count):
        x, y, w, h, area = (int(value) for value in stats[index])
        if area < min_area or w > width * 0.6:
            continue
        if (x + w > width // 2) if person_right else (x < width // 2):
            boxes.append((x, y, x + w, y + h))
    return boxes


def _clear_of(box: PixelBox, holograms: Sequence[PixelBox], gap: int,
              person_right: bool) -> PixelBox:
    """The box narrowed on Roman's side until it is `gap` px clear of every hologram beside it
    (one above or below it by more than the gap is left alone)."""
    left, top, right, bottom = box
    for hologram in holograms:
        if hologram[1] - gap >= bottom or hologram[3] + gap <= top:
            continue
        if person_right:
            right = min(right, hologram[0] - gap)
        else:
            left = max(left, hologram[2] + gap)
    return (left, top, right, bottom)


# --- One layout --------------------------------------------------------------------------------


def render_layout(
    catalog: DirectionCatalog,
    direction: Direction,
    layout_name: str,
    copy: Mapping[str, object],
    assets: Assets,
    *,
    picture: Image.Image | None = None,
    step: int = 0,
    size: tuple[int, int] | None = None,
    layout: Layout | None = None,
) -> Rendered:
    """Draw one layout of a direction; DesignRenderError when a text does not fit. layout: a
    v6 variation of it (content/design_variation.py), drawn instead of the stored one."""
    layout = layout or direction.layouts[layout_name]
    canvas = size or catalog.size(direction)
    record = Rendered(image=Image.new("RGB", canvas), direction=direction.id,
                      layout=layout_name, size=canvas)
    painter = Painter(canvas, assets, record)
    record.fonts = sorted({path.name for path in assets.fonts.values()})
    paint_background(painter, layout.background)
    visual_box: PixelBox | None = None
    texts = [zone.box for zone in layout.zones.values() if zone.kind == "text"]
    person_right = bool(texts) and sum(box[0] + box[2] for box in texts) / len(texts) < 1.0
    stacked: PixelBox | None = None  # the last headline/sub drawn: the next sub goes under it
    for name, zone in layout.zones.items():
        if zone.kind == "visual":
            visual_box = painter.px(zone.box)
            place_picture(painter, name, zone, picture, person=direction.roman)
            if direction.roman and picture is not None:
                record.holograms = hologram_boxes(painter.image, person_right)
        elif zone.kind == "shape":
            _shape(painter, name, zone)
        elif zone.kind == "logo":
            place_logo(painter, zone, layout, emblem=direction.format == "carousel")
        elif zone.kind == "text":
            value = " ".join(_lines(copy.get(str(zone.field))))
            if not value:
                if zone.optional:
                    continue
                raise DesignRenderError(f"{direction.id} {name}: fill copy.{zone.field}")
            area = painter.px(zone.box)
            if (zone.role in _STACKED and stacked is not None and area[1] > stacked[1]
                    and area[0] < stacked[2] and stacked[0] < area[2]):
                area = (area[0], stacked[3] + painter.s(STACK_GAP_PX), area[2], area[3])
                zone = zone.model_copy(update={"valign": "top"})
            if record.holograms:
                area = _clear_of(area, record.holograms, painter.s(HOLOGRAM_GAP_PX),
                                 person_right)
            if zone.role == "cta" and zone.icon:
                _cta(painter, name, zone, value, layout, layout.text_limits[name], area)
            else:
                placed = painter.text(name, zone, value, layout, layout.text_limits[name],
                                      box=area)
                if zone.role == "headline" or zone.role in _STACKED:
                    stacked = placed
        elif zone.kind == "items":
            _items(painter, name, zone, layout, copy, catalog, step, visual_box)
        elif zone.kind == "footer":
            if zone.optional and zone.field and not _lines(copy.get(zone.field)):
                continue  # v5: the carousel's website is optional (last slide only)
            _footer(painter, name, zone, layout, copy)
        elif zone.kind == "swipe":
            _swipe(painter, name, zone, layout)
        elif zone.kind == "arrow":
            _arrow(painter, name, zone)
        elif zone.kind == "icons":
            if direction.roman:  # his chips follow the body, clear of his holograms
                zone = _roman_row(painter, zone, stacked, record.holograms, person_right)
            _icons(painter, name, zone, layout, copy, catalog)
    record.image = painter.image.convert("RGB")
    return record


def _roman_row(painter: Painter, zone: Zone, stacked: PixelBox | None,
               holograms: Sequence[PixelBox], person_right: bool) -> Zone:
    """Roman's benefit chips (2026-10-21): right under the body, not at the zone's fixed place,
    and narrowed until they clear his holograms like every text."""
    area = painter.px(zone.box)
    if stacked is not None and area[1] > stacked[1]:
        top = stacked[3] + painter.s(STACK_GAP_PX * 1.5)
        area = (area[0], top, area[2], top + area[3] - area[1])
    if holograms:
        area = _clear_of(area, holograms, painter.s(HOLOGRAM_GAP_PX), person_right)
    width, height = painter.size
    return zone.model_copy(update={"box": (area[0] / width, area[1] / height, area[2] / width,
                                           area[3] / height)})


def place_brand_marks(image: Image.Image, direction: Direction, layout_name: str, layout: Layout,
                      assets: Assets, copy: Mapping[str, object] | None = None) -> Rendered:
    """v6 designer mode (R3.4): the model drew the ad; the app adds only the official logo (with
    the emblem on a carousel's last slide) and the website, in the layout's zones."""
    record = Rendered(image=image, direction=direction.id, layout=layout_name, size=image.size)
    painter = Painter(image.size, assets, record)
    painter.image = image.convert("RGBA")
    record.fonts = sorted({path.name for path in assets.fonts.values()})
    for name, zone in layout.zones.items():
        if zone.kind == "logo":
            _logo_plate(painter, zone)
            place_logo(painter, zone, layout, emblem=direction.format == "carousel")
        elif zone.kind == "footer":
            if zone.optional and zone.field and not _lines((copy or {}).get(zone.field)):
                continue
            _footer(painter, name, zone, layout, copy or {})
    record.image = painter.image.convert("RGB")
    return record


def token_colors(brand: BrandProfile) -> dict[str, RGB]:
    if brand.tokens is None:
        raise DesignRenderError("brand.json has no tokens (Phase D)")
    return {role: rgb(value) for role, value in brand.tokens.hexes().items()}


__all__ = [
    "Assets", "DesignRenderError", "Rendered", "TextRecord", "TokenRole", "cta_icon",
    "design_fonts", "emblem_file", "hologram_boxes", "logo_file", "parse", "place_brand_marks",
    "placeholder", "plain", "render_layout", "rgb", "token_colors",
]
