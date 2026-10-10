"""App-rendered text for image providers that draw no text (ComfyUI).

Order on every image: the generated base image, then this text overlay, then the logo
(workflows/logo.py). design_system.json "textOverlay" holds the text zones per format: a box
inside the layout's text panel, alignment, max lines, a font size range, weight and colour
roles. Each text is wrapped, then shrunk within its size range; text that still does not fit is
an error, never cut. The contrast behind each zone is measured and the zone's scrim (a soft
panel in a dark shade of the background colour) is added when it is too low.

Fonts come from textOverlay.fonts by family priority, so brand files (Futura) dropped into
assets/fonts/ replace the Jost fallback without a code change.

TEXT_OVERLAY=auto uses the overlay only when the image provider cannot draw text
(ProviderCapabilities.draws_text); "always" and "never" override that. Nano Banana keeps its
model-drawn text.
"""

import io
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from content_automation.references import BrandProfile, CompanyProfile
from content_automation.workflows.design_system import (
    Box,
    ColorRole,
    CtaIconId,
    DesignChoice,
    DesignSystem,
    OverlayFonts,
    OverlayPanel,
    TextOverlaySpec,
    TextZone,
    ZoneField,
)
from content_automation.workflows.logo import logo_zone
from content_automation.workflows.prompt import footer_text, role_colors
from content_automation.workflows.registry import WorkflowError

RGB = tuple[int, int, int]
PixelBox = tuple[int, int, int, int]  # left, top, right, bottom

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_FONT_SUFFIXES = (".ttf", ".otf")
_TAG_LETTERS = 3  # a short tag may sit between family and style in a name: "Futura PT Bold"
_NOMINAL = {"1:1": (1080, 1080), "4:5": (1080, 1350), "9:16": (1080, 1920), "16:9": (1080, 608)}
_PREPARE_SLACK = 0.98  # the check before generation keeps 2% spare height for rounding
_MAX_SCRIM = 0.95
_FOOTER_AREA = "a strip at the bottom centre (the footer)"
_LIST_GAP = 0.45  # space between list items, in lines
_BULLET = 0.14  # bullet radius, share of the font size
_UNSUPPORTED = ("steps", "chat", "diagram", "mini_checklist", "before_after")
_LABELS: dict[ZoneField, str] = {
    "audience_line": "The audience line",
    "headline": "The headline",
    "subheadline": "The subheadline",
    "stat": "The big number",
    "source_line": "The source line",
    "points": "The key points",
    "cta": "The CTA label",
    "icons": "The icon labels",
    "footer": "The footer",
}

# Sample texts for `ca overlay preview`: the fields of each format's brief template
# (content/package.py _slot_template), written at the template's word limits.
SAMPLE_TEXTS: dict[str, dict[str, str]] = {
    "ad": {
        "headline": "Stop losing your leads after hours",
        "highlight": "leads",
        "subheadline": "An AI chatbot answers every enquiry in seconds, day and night.",
        "sub_highlight": "seconds",
        "cta": "Book a free demo",
    },
    "statement": {
        "audience_line": "For dental practices",
        "headline": "Most missed calls are patients you never hear from again",
        "highlight": "missed,calls",
        "subheadline": "An AI receptionist answers, books and confirms while your team treats.",
        "points": "Answer every call within three rings|Send booking links by text "
        "automatically|Confirm each appointment one day before",
    },
    "stat": {
        "audience_line": "For real estate agents",
        "headline": "Buyers pick the agent who answers first",
        "highlight": "answers,first",
        "stat": "73%",
        "source": "sample",
        "source_name": "Zillow",
        "subheadline": "of buyers work with the first agent who replies, so automate that reply.",
    },
    "news": {
        "headline": "Google now shows AI answers above ads for most local service searches",
        "subheadline": "Your website content decides whether those answers name your business.",
        "points": "Check which questions your customers ask|Answer each one on your own "
        "site|Add your opening hours and prices",
    },
    "checklist": {
        "audience_line": "For restaurants",
        "headline": "Take WhatsApp orders without extra staff",
        "highlight": "WhatsApp",
        "subheadline": "A chatbot takes the order, confirms it and sends it to your kitchen.",
        "points": "Connect your WhatsApp Business number|Upload your menu with "
        "prices|Send each order to the kitchen",
    },
    "person_photo": {"headline": "Your AI partner"},
}


class TextOverlayError(WorkflowError):
    """The text overlay cannot be made: no zones, no fonts, or a text that does not fit."""


def use_text_overlay(mode: str, draws_text: bool) -> bool:
    """TEXT_OVERLAY: auto = only for providers that draw no text; always; never."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    return not draws_text


# --- Fonts -----------------------------------------------------------------------------------


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def _font_folder(folder: str) -> Path:
    path = Path(folder)
    if path.is_absolute() or path.is_dir():
        return path
    return _PROJECT_ROOT / path


def _font_keys(path: Path) -> list[str]:
    """What a font file answers to: its file name and its own family + style names."""
    keys = [_key(path.stem)]
    try:
        family, style = ImageFont.truetype(str(path), 12).getname()
    except OSError:
        return keys
    return [*keys, _key(f"{family or ''}{style or ''}")]


def _matches(key: str, family: str, style: str) -> bool:
    family_key, style_key = _key(family), _key(style)
    if len(key) < len(family_key) + len(style_key):
        return False
    if not (key.startswith(family_key) and key.endswith(style_key)):
        return False
    tag = key[len(family_key) : len(key) - len(style_key)]
    return tag == "" or (tag.isalpha() and len(tag) <= _TAG_LETTERS)


def resolve_fonts(fonts: OverlayFonts, weights: set[str]) -> dict[str, Path]:
    """The font file per weight: the first family (priority order) with a matching file."""
    folder = _font_folder(fonts.folder)
    files = sorted(
        path for path in (folder.iterdir() if folder.is_dir() else [])
        if path.suffix.lower() in _FONT_SUFFIXES
    )
    keys = {path: _font_keys(path) for path in files}
    found: dict[str, Path] = {}
    for weight in sorted(weights):
        styles = fonts.weights[weight]
        match = next(
            (
                path
                for family in fonts.families
                for style in styles
                for path in files
                if any(_matches(key, family, style) for key in keys[path])
            ),
            None,
        )
        if match is None:
            raise TextOverlayError(
                f'No font file for weight "{weight}" in {folder}: looked for '
                f"{' or '.join(fonts.families)} in style {' or '.join(styles)} (file names like "
                f'"{fonts.families[-1]}-{styles[0]}.ttf"). Add the files or fix '
                "textOverlay.fonts in design_system.json."
            )
        found[weight] = match
    return found


@lru_cache(maxsize=256)
def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


# --- Colours and contrast --------------------------------------------------------------------


def _rgb(hex_value: str) -> RGB:
    value = hex_value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _mix(color: RGB, other: RGB, share: float) -> RGB:
    """`share` of `other` mixed into `color`."""
    red, green, blue = (
        round(a * (1 - share) + b * share) for a, b in zip(color, other, strict=True)
    )
    return red, green, blue


def overlay_colors(
    brand: BrandProfile | None, system: DesignSystem, spec: TextOverlaySpec
) -> dict[ColorRole, RGB]:
    """The design's colour roles as RGB; the background is used as a dark shade."""
    found = role_colors(brand, system) if brand is not None and brand.colors else {}
    colors: dict[ColorRole, RGB] = {role: _rgb(color.hex) for role, color in found.items()}
    colors.setdefault("background", (0, 0, 0))
    colors.setdefault("text", (255, 255, 255))
    colors.setdefault("accent", colors["text"])
    colors.setdefault("highlight", colors["accent"])
    colors["background"] = _mix(colors["background"], (0, 0, 0), spec.background_shade)
    return colors


def _luminance(color: RGB) -> float:
    """WCAG relative luminance."""

    def channel(value: int) -> float:
        share = value / 255
        return share / 12.92 if share <= 0.04045 else ((share + 0.055) / 1.055) ** 2.4

    red, green, blue = color
    return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)


def contrast(first: RGB, second: RGB) -> float:
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _backdrop(image: Image.Image, box: PixelBox) -> tuple[RGB, RGB]:
    """The darker and the lighter end of what lies behind a box (10th and 90th percentile),
    so fine detail does not count but a light half of the box does."""
    region = image.crop(box).convert("RGB")
    region.thumbnail((48, 48))
    pixels: list[RGB] = sorted(region.getdata(), key=_luminance)
    return pixels[len(pixels) // 10], pixels[len(pixels) * 9 // 10]


def _worst(backdrop: tuple[RGB, RGB], colors: tuple[RGB, ...]) -> float:
    return min(contrast(color, behind) for color in colors for behind in backdrop)


# --- What each zone shows --------------------------------------------------------------------


@dataclass(frozen=True)
class ZoneText:
    paragraphs: tuple[str, ...]  # one for plain text; one per item for a list
    highlight: frozenset[str] = frozenset()  # words in the highlight colour (casefolded)
    numbered: bool = False  # a list with 1. 2. 3. instead of bullets
    icon: CtaIconId | None = None  # the CTA button's icon


def _word(text: str) -> str:
    return text.casefold().strip(".,:;!?\"'“”‘’()")


def _highlight(phrases: tuple[str, ...]) -> frozenset[str]:
    return frozenset(_word(word) for phrase in phrases for word in phrase.split())


def zone_texts(
    design: DesignChoice, system: DesignSystem, footer: str | None
) -> dict[ZoneField, ZoneText]:
    """The texts of one design by zone field, as the model would have drawn them."""
    spec = system.formats[design.format]
    texts: dict[ZoneField, ZoneText] = {}
    if design.audience_line:
        texts["audience_line"] = ZoneText((design.audience_line.upper(),))
    if design.headline:
        headline = design.headline.upper() if spec.headline_caps else design.headline
        texts["headline"] = ZoneText((headline,), _highlight(design.highlight))
    if design.stat:
        texts["stat"] = ZoneText((design.stat,))
    if design.source_name:
        texts["source_line"] = ZoneText((f"Source: {design.source_name}",))
    if design.subheadline:
        sub = (design.sub_highlight,) if design.sub_highlight else ()
        texts["subheadline"] = ZoneText((design.subheadline,), _highlight(sub))
    if design.points:
        texts["points"] = ZoneText(design.points, numbered=spec.numbered_points)
    if design.icons:
        texts["icons"] = ZoneText(("  ·  ".join(design.icons),))
    if design.cta:
        texts["cta"] = ZoneText((design.cta,), icon=design.cta_icon)
    if footer:
        texts["footer"] = ZoneText((footer,))
    return texts


# --- The overlay of one design ---------------------------------------------------------------


@dataclass(frozen=True)
class TextOverlay:
    """What the app writes onto one design; built and checked before any paid call."""

    format: str
    panel: OverlayPanel
    zones: tuple[TextZone, ...]  # the format's zones, then the footer
    texts: dict[ZoneField, ZoneText]
    spec: TextOverlaySpec
    colors: dict[ColorRole, RGB]
    fonts: dict[str, Path]  # weight -> font file

    def describe(self) -> str:
        fields = ", ".join(
            _LABELS[zone.field].removeprefix("The ") for zone in self.zones
            if zone.field in self.texts
        )
        fonts = ", ".join(sorted({path.stem for path in self.fonts.values()}))
        return (
            f"{fields} rendered by the app in {self.panel.label} ({fonts}); a scrim is added "
            "where the contrast is too low; the image model draws no text"
        )

    def areas(self) -> str:
        """The areas the prompt keeps clear for the text."""
        found = [(self.panel.label, self.panel.box)]
        if "footer" in self.texts:
            found.append((_FOOTER_AREA, self.spec.footer.box))
        return "; ".join(
            f"{label} ({left:.0%}-{right:.0%} of the width, {top:.0%}-{bottom:.0%} of the "
            "height)"
            for label, (left, top, right, bottom) in found
        )

    def min_contrast(self, zone: TextZone) -> float:
        return zone.min_contrast or self.spec.min_contrast


def prepare_text_overlay(
    design: DesignChoice,
    system: DesignSystem,
    brand: BrandProfile | None,
    company: CompanyProfile | None,
    *,
    aspect_ratio: str | None = None,
) -> TextOverlay:
    """Check the overlay before generation: zones, fonts, colours, the logo corner and, with
    an aspect ratio, that every text fits. TextOverlayError says what to fix."""
    spec = system.text_overlay
    if spec is None:
        raise TextOverlayError(
            "design_system.json has no textOverlay section, so the app cannot render the text. "
            "Restore it, or set TEXT_OVERLAY=never to let the image model draw the text."
        )
    fitting = spec.formats.get(design.format)
    if fitting is None:
        raise TextOverlayError(
            f"The text overlay has no zones for format {design.format} (design_system.json "
            "textOverlay.formats; carousel slides follow in Phase 3). Use a provider that draws "
            "text (IMAGE_PROVIDER=openrouter) for it."
        )
    unsupported = [name for name in _UNSUPPORTED if getattr(design, name)]
    if unsupported:
        raise TextOverlayError(
            f"The text overlay cannot render {', '.join(unsupported)} yet (Phase 3)."
        )
    panel_name = fitting.panel or spec.layout_panels.get(design.layout or "none")
    if panel_name is None:
        raise TextOverlayError(
            f"textOverlay.layoutPanels names no panel for layout {design.layout or 'none'}."
        )
    zones = (*fitting.zones, spec.footer)
    texts = zone_texts(design, system, footer_text(company))
    covered = {zone.field for zone in zones}
    missing = [name for name in texts if name not in covered]
    if missing:
        raise TextOverlayError(
            f"Format {design.format} has no text zone for {', '.join(missing)} "
            "(design_system.json textOverlay.formats); the text would be lost."
        )
    used = [zone for zone in zones if zone.field in texts]
    colors = overlay_colors(brand, system, spec)
    overlay = TextOverlay(
        format=design.format,
        panel=spec.panels[panel_name],
        zones=zones,
        texts=texts,
        spec=spec,
        colors=colors,
        fonts=resolve_fonts(spec.fonts, {zone.weight for zone in used}),
    )
    scrim = colors[spec.scrim.color]
    for zone in used:
        if zone.field == "cta":
            behind, where = colors[spec.button.fill], "the CTA button fill"
        elif zone.scrim != "never":
            behind, where = scrim, "the scrim"
        else:
            continue
        for color in _zone_colors(zone, texts[zone.field], colors):
            if contrast(color, behind) < overlay.min_contrast(zone):
                raise TextOverlayError(
                    f"{_LABELS[zone.field]} colour has too little contrast with {where} "
                    f"({contrast(color, behind):.1f}:1, needs {overlay.min_contrast(zone):g}:1); "
                    "check the colour roles in design_system.json textOverlay."
                )
    if aspect_ratio is not None:
        size = _NOMINAL.get(aspect_ratio)
        if size is not None:
            place_texts(overlay, size, slack=_PREPARE_SLACK)
    return overlay


# --- Layout ----------------------------------------------------------------------------------


@dataclass
class _Placed:
    zone: TextZone
    font: ImageFont.FreeTypeFont
    bounds: PixelBox  # where the text (or the button) is
    colors: tuple[RGB, ...]  # what its text uses, for the contrast check
    runs: list[tuple[float, float, str, RGB]] = field(default_factory=list)  # x, baseline
    bullets: list[tuple[float, float, float, RGB]] = field(default_factory=list)  # cx, cy, r
    button: PixelBox | None = None
    icon: tuple[CtaIconId, PixelBox] | None = None


def _to_pixels(box: Box, area: PixelBox) -> PixelBox:
    left, top, right, bottom = area
    width, height = right - left, bottom - top
    return (
        left + round(box[0] * width),
        top + round(box[1] * height),
        left + round(box[2] * width),
        top + round(box[3] * height),
    )


def _overlaps(first: PixelBox, second: PixelBox) -> bool:
    return first[0] < second[2] and second[0] < first[2] and first[1] < second[3] and (
        second[1] < first[3]
    )


def _zone_colors(zone: TextZone, text: ZoneText, colors: dict[ColorRole, RGB]) -> tuple[RGB, ...]:
    found = [colors[zone.color]]
    if text.highlight:
        found.append(colors[zone.highlight])
    if zone.field == "points" and text.numbered:
        found.append(colors[zone.marker])
    return tuple(found)


def _width(words: list[str], font: ImageFont.FreeTypeFont) -> float:
    return sum(font.getlength(word) for word in words) + font.getlength(" ") * (len(words) - 1)


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[list[str]] | None:
    """Greedy word wrap; None when one word alone is wider than the box (never cut)."""
    lines: list[list[str]] = []
    current: list[str] = []
    for word in text.split():
        if _width([*current, word], font) <= width:
            current.append(word)
            continue
        if not current or font.getlength(word) > width:
            return None
        lines.append(current)
        current = [word]
    if current:
        lines.append(current)
    return lines


def _sizes(zone: TextZone, scale: float) -> range:
    smallest = max(1, round(zone.size[0] * scale))
    return range(max(smallest, round(zone.size[1] * scale)), smallest - 1, -1)


def _x(align: str, left: float, right: float, width: float) -> float:
    if align == "center":
        return left + (right - left - width) / 2
    if align == "right":
        return right - width
    return left


def _y(valign: str, top: float, bottom: float, height: float) -> float:
    if valign == "middle":
        return top + (bottom - top - height) / 2
    if valign == "bottom":
        return bottom - height
    return top


def _fit_text(
    zone: TextZone,
    text: ZoneText,
    box: PixelBox,
    font_path: Path,
    scale: float,
    slack: float,
    colors: dict[ColorRole, RGB],
) -> _Placed | None:
    """Plain text or a list: the largest size at which every line fits the box."""
    left, top, right, bottom = box
    is_list = zone.field == "points"
    for size in _sizes(zone, scale):
        font = _font(font_path, size)
        ascent, descent = font.getmetrics()
        line_px = size * zone.line_height
        gap = line_px * _LIST_GAP if is_list else 0.0
        if is_list and text.numbered:
            marks = [f"{number}." for number in range(1, len(text.paragraphs) + 1)]
            indent = max(font.getlength(mark) for mark in marks) + size * 0.4
        else:
            marks = []
            indent = size * (2 * _BULLET + 0.5) if is_list else 0.0
        wrapped = [_wrap(paragraph, font, right - left - indent) for paragraph in text.paragraphs]
        if any(lines is None for lines in wrapped):
            continue
        paragraphs = [lines for lines in wrapped if lines is not None]
        count = sum(len(lines) for lines in paragraphs)
        height = ascent + descent + (count - 1) * line_px + (len(paragraphs) - 1) * gap
        if count > zone.max_lines or height > (bottom - top) * slack:
            continue
        placed = _Placed(
            zone=zone,
            font=font,
            bounds=box,
            colors=_zone_colors(zone, text, colors),
        )
        y0 = _y(zone.valign, top, bottom, height)
        baseline = y0 + ascent
        edges: list[float] = []
        for number, lines in enumerate(paragraphs):
            if marks:
                placed.runs.append((left, baseline, marks[number], colors[zone.marker]))
            elif is_list:
                radius = size * _BULLET
                placed.bullets.append(
                    (left + radius, baseline - size * 0.33, radius, colors[zone.marker])
                )
            for words in lines:
                x = _x(zone.align, left + indent, right, _width(words, font))
                edges += [x - indent, x + _width(words, font)]
                for word in words:
                    color = zone.highlight if _word(word) in text.highlight else zone.color
                    placed.runs.append((x, baseline, word, colors[color]))
                    x += font.getlength(word) + font.getlength(" ")
                baseline += line_px
            baseline += gap
        placed.bounds = (
            round(min(edges)), round(y0), round(max(edges)), round(y0 + height)
        )
        return placed
    return None


def _fit_button(
    zone: TextZone,
    text: ZoneText,
    box: PixelBox,
    font_path: Path,
    scale: float,
    slack: float,
    overlay: TextOverlay,
) -> _Placed | None:
    """The CTA button: its label on one line, with the icon, inside the box."""
    left, top, right, bottom = box
    style = overlay.spec.button
    pad_x, pad_y = style.pad_x * scale, style.pad_y * scale
    label = text.paragraphs[0]
    for size in _sizes(zone, scale):
        font = _font(font_path, size)
        ascent, descent = font.getmetrics()
        icon = round(size * 0.95) if text.icon else 0
        gap = size * 0.5 if icon else 0.0
        label_width = font.getlength(label)
        width = 2 * pad_x + label_width + gap + icon
        height = 2 * pad_y + max(ascent + descent, icon)
        if width > right - left or height > (bottom - top) * slack:
            continue
        x0 = _x(zone.align, left, right, width)
        y0 = _y(zone.valign, top, bottom, height)
        button = (round(x0), round(y0), round(x0 + width), round(y0 + height))
        placed = _Placed(
            zone=zone,
            font=font,
            bounds=button,
            colors=(overlay.colors[zone.color],),
            button=button,
        )
        baseline = y0 + (height - ascent - descent) / 2 + ascent
        placed.runs.append((x0 + pad_x, baseline, label, overlay.colors[zone.color]))
        if text.icon:
            icon_left = round(x0 + pad_x + label_width + gap)
            icon_top = round(y0 + (height - icon) / 2)
            placed.icon = (text.icon, (icon_left, icon_top, icon_left + icon, icon_top + icon))
        return placed
    return None


def place_texts(
    overlay: TextOverlay, size: tuple[int, int], *, slack: float = 1.0
) -> list[_Placed]:
    """Lay out every text on an image of `size`; TextOverlayError if one does not fit or a
    zone reaches into the logo corner."""
    width, height = size
    scale = width / overlay.spec.base_width
    canvas = (0, 0, width, height)
    panel = _to_pixels(overlay.panel.box, canvas)
    logo = logo_zone(size)
    placed: list[_Placed] = []
    for zone in overlay.zones:
        box = _to_pixels(zone.box, canvas if zone.field == "footer" else panel)
        if _overlaps(box, logo):
            raise TextOverlayError(
                f"The {zone.field} zone of format {overlay.format} reaches into the logo corner "
                "(design_system.json textOverlay); move it."
            )
        text = overlay.texts.get(zone.field)
        if text is None:
            continue
        font_path = overlay.fonts[zone.weight]
        if zone.field == "cta":
            fitted = _fit_button(zone, text, box, font_path, scale, slack, overlay)
        else:
            fitted = _fit_text(zone, text, box, font_path, scale, slack, overlay.colors)
        if fitted is None:
            shown = " | ".join(text.paragraphs)
            raise TextOverlayError(
                f'{_LABELS[zone.field]} does not fit its zone even at the smallest size '
                f"({zone.size[0]} px at {overlay.spec.base_width} px width, at most "
                f'{zone.max_lines} lines): "{shown}". Shorten it, or widen textOverlay.formats.'
                f"{overlay.format}.zones ({zone.field}) in design_system.json."
            )
        placed.append(fitted)
    return placed


# --- Drawing ---------------------------------------------------------------------------------


def _scrim_alpha(
    backdrop: tuple[RGB, RGB], colors: tuple[RGB, ...], needed: float, overlay: TextOverlay
) -> float:
    """The lowest scrim opacity (from the configured one up) that reaches the contrast."""
    scrim = overlay.colors[overlay.spec.scrim.color]
    alpha = overlay.spec.scrim.opacity
    while alpha < _MAX_SCRIM:
        blended = (_mix(backdrop[0], scrim, alpha), _mix(backdrop[1], scrim, alpha))
        if _worst(blended, colors) >= needed:
            return alpha
        alpha = min(_MAX_SCRIM, alpha + 0.08)
    return _MAX_SCRIM


def _draw_icon(
    draw: ImageDraw.ImageDraw, icon: CtaIconId, box: PixelBox, color: RGB, line: int
) -> None:
    left, top, right, bottom = box
    side = right - left
    middle = (top + bottom) / 2
    if icon == "play":
        draw.polygon(
            [(left + side * 0.22, top + side * 0.12), (left + side * 0.22, bottom - side * 0.12),
             (right - side * 0.1, middle)],
            fill=color,
        )
    elif icon == "calendar":
        draw.rounded_rectangle(
            (left + side * 0.08, top + side * 0.18, right - side * 0.08, bottom - side * 0.06),
            radius=max(1, round(side * 0.1)), outline=color, width=line,
        )
        draw.line(
            (left + side * 0.08, top + side * 0.4, right - side * 0.08, top + side * 0.4),
            fill=color, width=line,
        )
        for x in (left + side * 0.32, right - side * 0.32):
            draw.line((x, top + side * 0.05, x, top + side * 0.3), fill=color, width=line)
    else:  # arrow: an arrow inside a circle
        draw.ellipse(box, outline=color, width=line)
        tip, tail = right - side * 0.27, left + side * 0.27
        draw.line((tail, middle, tip, middle), fill=color, width=line)
        for dy in (-side * 0.17, side * 0.17):
            draw.line((tip - side * 0.17, middle + dy, tip, middle), fill=color, width=line)


def apply_text(data: bytes, overlay: TextOverlay) -> tuple[bytes, list[str]]:
    """Render the texts onto one generated image (before the logo); returns PNG bytes and
    notes on the scrims that were added."""
    with Image.open(io.BytesIO(data)) as source:
        image = source.convert("RGB")
    placed = place_texts(overlay, image.size)
    scale = image.width / overlay.spec.base_width
    style = overlay.spec.scrim
    pad = round(style.padding * scale)
    mask = Image.new("L", image.size, 0)
    shade = ImageDraw.Draw(mask)
    notes: list[str] = []
    for item in placed:
        zone = item.zone
        if zone.scrim == "never" or zone.field == "cta":
            continue
        backdrop = _backdrop(image, item.bounds)
        needed = overlay.min_contrast(zone)
        worst = _worst(backdrop, item.colors)
        if zone.scrim == "auto" and worst >= needed:
            continue
        alpha = _scrim_alpha(backdrop, item.colors, needed, overlay)
        left, top, right, bottom = item.bounds
        shade.rounded_rectangle(
            (max(0, left - pad), max(0, top - pad), min(image.width, right + pad),
             min(image.height, bottom + pad)),
            radius=round(style.radius * scale),
            fill=round(255 * alpha),
        )
        notes.append(
            f"scrim behind the {zone.field.replace('_', ' ')} (contrast {worst:.1f}:1, "
            f"needs {needed:g}:1)"
        )
    if mask.getbbox() is not None:
        layer = Image.new("RGB", image.size, overlay.colors[style.color])
        image = Image.composite(layer, image, mask)
    draw = ImageDraw.Draw(image)
    button = overlay.spec.button
    for item in placed:
        if item.button is not None:
            draw.rounded_rectangle(
                item.button,
                radius=round(button.radius * scale),
                fill=overlay.colors[button.fill],
                outline=overlay.colors[button.outline],
                width=round(button.outline_width * scale),
            )
        for x, baseline, text, color in item.runs:
            draw.text((x, baseline), text, font=item.font, fill=color, anchor="ls")
        for cx, cy, radius, color in item.bullets:
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=color)
        if item.icon is not None:
            icon, box = item.icon
            line = max(2, round((box[2] - box[0]) / 11))
            _draw_icon(draw, icon, box, overlay.colors[item.zone.color], line)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue(), notes
