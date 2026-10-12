"""What the app draws for the animated carousel (free, local): the background layer, the
Like/Share/Save row, the slide text (the Phase 2 text overlay), the logo on the last slide, the
style frames from the sample carousels and `ca carousel preview`.

Order on every slide: background (navy + particle wave), the illustration (later the
Higgsfield clip; in the preview the right half of a sample frame), the icon row (last slide),
the text, then the logo (last slide).
"""

import io
import json
import math
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from content_automation.core.media import run_ffmpeg
from content_automation.workflows.carousel_design import (
    CarouselDesign,
    SlideText,
    SlideType,
    project_path,
    slide_problems,
    split_marked,
    still_prompt,
)
from content_automation.workflows.design_system import (
    ColorRole,
    DesignSystem,
    OverlayPanel,
    ZoneField,
)
from content_automation.workflows.logo import LogoError, LogoOverlay, logo_zone, paste_logo
from content_automation.workflows.text_overlay import (
    TextOverlay,
    TextOverlayError,
    ZoneText,
    place_texts,
    resolve_fonts,
    text_layer,
)

RGB = tuple[int, int, int]
PREVIEW_DIR = Path("outputs/carousel-preview")
_PANEL_LABEL = "the left half of the frame"
# Preview: the sample frame fades in from just right of the text panel over this width.
_FADE_GAP, _FEATHER = 0.015, 0.06
_PREPARE_SLACK = 0.98  # like the Phase 2 check before generation
_ICONS = ("heart", "plane", "bookmark")
# The Phase 2 overlay's names for the carousel's texts.
_NAMES = {"The subheadline": "The body line", "The key points": "The list items"}


def _color(hex_value: str) -> RGB:
    value = hex_value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _mix(color: RGB, other: RGB, share: float) -> RGB:
    red, green, blue = (round(a + (b - a) * share) for a, b in zip(color, other, strict=True))
    return red, green, blue


def _scaled(color: RGB, light: float) -> RGB:
    red, green, blue = (round(value * light) for value in color)
    return red, green, blue


@lru_cache(maxsize=32)
def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size)


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


# --- Background layer ------------------------------------------------------------------------


class Background:
    """The app-drawn background, made once and animated per frame: navy lifted behind the
    illustration and a dot-grid mark at the top left (static), and the particle wave along the
    bottom, which loops once per slide (t = 0 and t = the slide length give the same frame).
    Only the wave band is drawn again for each frame."""

    def __init__(self, design: CarouselDesign) -> None:
        self.design = design
        width, height = self.size = (design.canvas.width, design.canvas.height)
        palette, spec = design.palette, design.background
        self.glow, self.crest = _color(palette.glow), _color(palette.crest)
        # Radial lift centred behind the illustration: 0 there, 255 towards the edges.
        lift = Image.radial_gradient("L").resize(
            (2 * width, 2 * height), Image.Resampling.BILINEAR
        )
        centre_x, centre_y = round(width * 0.62), round(height * 0.5)
        lift = lift.crop((width - centre_x, height - centre_y, 2 * width - centre_x,
                          2 * height - centre_y)).point(lambda value: min(255, value * 3 // 2))
        base = Image.composite(
            Image.new("RGB", self.size, _color(palette.background)),
            Image.new("RGB", self.size, _color(palette.navy)),
            lift,
        )
        marks = Image.new("RGB", self.size, (0, 0, 0))
        draw = ImageDraw.Draw(marks)
        columns, rows = spec.dot_grid
        step, dot = width * 0.016, max(1.0, width / 540)
        for column in range(columns):
            for row in range(rows):
                x, y = width * 0.045 + column * step, height * 0.045 + row * step
                draw.ellipse(
                    (x - dot, y - dot, x + dot, y + dot), fill=_mix(self.glow, self.crest, 0.6)
                )
        self.base = self._glowing(base, marks)
        reach = height * spec.amplitude + spec.dot_size[1] + 3 * spec.glow_radius
        self.top = max(0, int(height * spec.wave_top - reach))

    def _glowing(self, image: Image.Image, dots: Image.Image) -> Image.Image:
        radius = self.design.background.glow_radius
        if radius:
            halo = dots.filter(ImageFilter.GaussianBlur(radius))
            image = ImageChops.screen(ImageChops.screen(image, halo), halo)
        return ImageChops.screen(image, dots)

    def wave(self, t: float) -> Image.Image:
        """The wave band at second t: glowing dots on black (from self.top down)."""
        design, spec = self.design, self.design.background
        width, height = self.size
        dots = Image.new("RGB", (width, height - self.top), (0, 0, 0))
        draw = ImageDraw.Draw(dots)
        phase = 2 * math.pi * t / design.timing.seconds_per_slide
        far, near = spec.dot_size
        for row in range(spec.rows):
            depth = row / (spec.rows - 1)  # 0 = the far crest, 1 = the bottom edge
            base = height * (spec.wave_top + (1.02 - spec.wave_top) * depth**1.5) - self.top
            amplitude = height * spec.amplitude * (1 - 0.45 * depth)
            radius = far + (near - far) * depth
            color = _mix(self.glow, self.crest, (1 - depth) ** 4)
            light = 0.25 + 0.75 * (1 - depth) ** 2.2
            spread = 1.05 + 0.6 * depth  # nearer rows reach past the edges
            for column in range(spec.columns):
                across = column / (spec.columns - 1)
                x = width * (0.5 + (across - 0.5) * spread)
                wave = (math.sin(2 * math.pi * 1.1 * across + phase + depth * 2.4)
                        + 0.5 * math.sin(2 * math.pi * 0.45 * across - phase + depth * 1.3)) / 1.5
                y = base + amplitude * wave
                fill = _scaled(color, light * (0.75 + 0.25 * wave))
                draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
        return self._glowing(Image.new("RGB", dots.size, (0, 0, 0)), dots)

    def frame(self, t: float = 0.0) -> Image.Image:
        image = self.base.copy()
        band = image.crop((0, self.top, *self.size))
        image.paste(ImageChops.screen(band, self.wave(t)), (0, self.top))
        return image


def background(design: CarouselDesign, t: float = 0.0) -> Image.Image:
    """The background at second t (see Background)."""
    return Background(design).frame(t)


# --- Like / Share / Save row -----------------------------------------------------------------


def _icon(draw: ImageDraw.ImageDraw, icon: str, centre: tuple[float, float], half: float,
          color: tuple[int, int, int, int], line: int) -> None:
    cx, cy = centre
    if icon == "heart":
        points = []
        for step in range(64):
            angle = 2 * math.pi * step / 64
            x = 16 * math.sin(angle) ** 3
            y = -(13 * math.cos(angle) - 5 * math.cos(2 * angle) - 2 * math.cos(3 * angle)
                  - math.cos(4 * angle))
            points.append((cx + x * half / 17, cy + (y + 2) * half / 17))
        draw.line([*points, points[0]], fill=color, width=line, joint="curve")
        return
    shape = (
        [(-0.9, 0.05), (0.9, -0.75), (0.15, 0.85), (-0.05, 0.2)]
        if icon == "plane"
        else [(-0.55, -0.85), (0.55, -0.85), (0.55, 0.85), (0.0, 0.4), (-0.55, 0.85)]
    )
    points = [(cx + x * half, cy + y * half) for x, y in shape]
    draw.line([*points, points[0]], fill=color, width=line, joint="curve")
    if icon == "plane":
        draw.line([points[3], points[1]], fill=color, width=line)


def icon_row(design: CarouselDesign, language: str) -> Image.Image:
    """The last slide's Like/Share/Save row as a transparent layer of the canvas size."""
    design.language_name(language)
    width, height = design.canvas.width, design.canvas.height
    palette = design.palette
    left, top, right, bottom = (
        round(share * side)
        for share, side in zip(design.icon_row.box, (width, height, width, height), strict=True)
    )
    bar = bottom - top
    layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    glow, crest, text = _color(palette.glow), _color(palette.crest), _color(palette.text)
    line = max(2, round(width / 540))
    draw.rounded_rectangle(
        (left, top, right, bottom), radius=round(bar * 0.28),
        fill=(*_color(palette.navy), 235), outline=(*glow, 220), width=line,
    )
    fonts = resolve_fonts(design.fonts, {"bold", "medium"})
    label_font = _font(fonts["bold"], round(bar * 0.17))
    note_font = _font(fonts["medium"], round(bar * 0.12))
    section = (right - left) / len(_ICONS)
    for number, (icon, item) in enumerate(
        zip(_ICONS, design.icon_row.labels[language], strict=True)
    ):
        cx = left + section * (number + 0.5)
        if number:
            x = left + section * number
            draw.line((x, top + bar * 0.18, x, bottom - bar * 0.18), fill=(*glow, 110), width=1)
        radius, cy = bar * 0.19, top + bar * 0.3
        draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                     outline=(*glow, 255), width=line)
        _icon(draw, icon, (cx, cy), radius * 0.55, (*crest, 255), line)
        draw.text((cx, top + bar * 0.66), item.label, font=label_font, fill=(*text, 255),
                  anchor="mm")
        if item.note:
            draw.text((cx, top + bar * 0.84), item.note, font=note_font,
                      fill=(*_mix(text, glow, 0.35), 255), anchor="mm")
    return layer


# --- Slide text (Phase 2 overlay) ------------------------------------------------------------


def slide_colors(design: CarouselDesign) -> dict[ColorRole, RGB]:
    palette = design.palette
    return {
        "background": _color(palette.background),
        "accent": _color(palette.glow),
        "highlight": _color(palette.highlight),
        "text": _color(palette.text),
    }


def _marked(paragraphs: Sequence[str], numbered: bool = False) -> ZoneText:
    """**word** marks -> the plain text and the marked word positions across paragraphs."""
    plain: list[str] = []
    lit: set[int] = set()
    for paragraph in paragraphs:
        text, marked = split_marked(paragraph)
        offset = sum(len(done.split()) for done in plain)
        lit |= {offset + position for position in marked}
        plain.append(text)
    return ZoneText(tuple(plain), highlight_at=frozenset(lit), numbered=numbered)


def slide_overlay(slide: SlideText, design: CarouselDesign, system: DesignSystem) -> TextOverlay:
    """The Phase 2 overlay for one slide: the type's zones in the left text panel."""
    if system.text_overlay is None:
        raise TextOverlayError(
            "design_system.json has no textOverlay section; the carousel text needs it."
        )
    spec = design.slide_types[slide.type]
    texts: dict[ZoneField, ZoneText] = {"headline": _marked([slide.headline])}
    if slide.body:
        texts["subheadline"] = _marked([slide.body])
    if slide.stat:
        texts["stat"] = ZoneText((slide.stat.strip(),))
    if slide.items:
        texts["points"] = _marked(slide.items, numbered=spec.numbered)
    zones = tuple(spec.zones)
    missing = sorted(set(texts) - {zone.field for zone in zones})
    if missing:
        raise TextOverlayError(
            f"Slide type {slide.type} has no zone for {', '.join(missing)} "
            "(config/carousel_design.json slideTypes); the text would be lost."
        )
    used = {zone.weight for zone in zones if zone.field in texts}
    return TextOverlay(
        format=f"carousel {slide.type}",
        panel=OverlayPanel(box=design.text_panel, label=_PANEL_LABEL),
        zones=zones,
        texts=texts,
        spec=system.text_overlay.model_copy(update={
            "fonts": design.fonts,
            "base_width": design.canvas.width,
            "min_contrast": design.min_contrast,
        }),
        colors=slide_colors(design),
        fonts=resolve_fonts(design.fonts, used),
    )


def slide_layer(
    slide: SlideText,
    design: CarouselDesign,
    system: DesignSystem,
    backdrop: Image.Image,
    language: str,
    logo: LogoOverlay | None,
) -> tuple[Image.Image, list[str]]:
    """The static layer of one slide, on a transparent canvas: the Like/Share/Save row (last
    slide), the text and the logo (last slide). It goes over the slide's still or its moving
    clip unchanged; scrims and the logo version are measured on the backdrop (the still).
    TextOverlayError if the text does not fit; a logo problem becomes a note."""
    size = (design.canvas.width, design.canvas.height)
    backdrop = backdrop.convert("RGBA").resize(size)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    if slide.type == design.structure[-1]:
        layer.alpha_composite(icon_row(design, language))
    text, notes = text_layer(
        slide_overlay(slide, design, system), Image.alpha_composite(backdrop, layer)
    )
    layer = Image.alpha_composite(layer, text)
    if logo is not None and slide.type in design.logo.slide_types:
        try:
            notes.append(f"logo {paste_logo(layer, backdrop, logo)}")
        except LogoError as error:
            notes.append(f"logo not pasted: {error}")
    return layer, notes


def _overlay_message(error: TextOverlayError, slide: SlideText) -> str:
    message = str(error).split(" Shorten it")[0]
    for old, new in _NAMES.items():
        message = message.replace(old, new)
    if "does not fit" in message:
        message += (
            f" Shorten it, or widen slideTypes.{slide.type}.zones in config/carousel_design.json."
        )
    return message


def fit_problems(
    slides: Sequence[SlideText], design: CarouselDesign, system: DesignSystem,
    where: str = "carousel",
) -> list[str]:
    """Every slide's text fits its zones (with the fonts found); free, before any cost."""
    size = (design.canvas.width, design.canvas.height)
    problems = []
    for number, slide in enumerate(slides, start=1):
        try:
            place_texts(slide_overlay(slide, design, system), size, slack=_PREPARE_SLACK)
        except TextOverlayError as error:
            problems.append(f"{where}.slides[{number}]: {_overlay_message(error, slide)}")
    return problems


# --- Style frames from the samples -----------------------------------------------------------


def style_frames(design: CarouselDesign, slide_type: SlideType) -> list[Path]:
    """The type's reference frames (best first), extracted from the sample MP4s with FFmpeg
    on first use; a sample that is missing is left out."""
    spec = design.style_frames
    folder = project_path(spec.folder)
    found = []
    for number, clip in enumerate(spec.frames.get(slide_type, []), start=1):
        target = folder / f"{slide_type}_{number}.png"
        source = project_path(spec.samples) / clip
        if not target.is_file() and source.is_file():
            folder.mkdir(parents=True, exist_ok=True)
            run_ffmpeg([
                "-y", "-ss", f"{spec.second:g}", "-i", str(source), "-frames:v", "1",
                "-vf", f"scale={design.canvas.width}:{design.canvas.height}:flags=lanczos",
                str(target),
            ])
        if target.is_file():
            found.append(target)
    return found


def extract_style(design: CarouselDesign) -> list[str]:
    """`ca carousel style`: every type's frames plus palette.json in the style folder."""
    folder = project_path(design.style_frames.folder)
    lines = []
    for slide_type, clips in design.style_frames.frames.items():
        frames = style_frames(design, slide_type)
        names = ", ".join(path.name for path in frames) or "none"
        missing = len(clips) - len(frames)
        lines.append(
            f"{slide_type}: {names}" + (f" ({missing} sample clip(s) not found)" if missing else "")
        )
    folder.mkdir(parents=True, exist_ok=True)
    palette = design.palette.model_dump(by_alias=True)
    (folder / "palette.json").write_text(json.dumps(palette, indent=2) + "\n", encoding="utf-8")
    lines.append(f"Palette: {folder / 'palette.json'}")
    return lines


# --- Preview ---------------------------------------------------------------------------------


def _ramp(length: int, start: float, end: float) -> bytes:
    """0 before `start`, 255 after `end` (shares of the length), linear between."""
    return bytes(
        round(255 * min(1.0, max(0.0, (position / length - start) / (end - start))))
        for position in range(length)
    )


def _preview_base(design: CarouselDesign, frame: Path | None, final: bool) -> Image.Image:
    """The background with the right half of a sample frame (its own text masked out)."""
    image = background(design)
    if frame is None:
        return image
    width, height = image.size
    with Image.open(frame) as source:
        picture = source.convert("RGB").resize(image.size, Image.Resampling.LANCZOS)
    start = design.text_panel[2] + _FADE_GAP
    mask = Image.frombytes("L", (width, 1), _ramp(width, start, start + _FEATHER))
    mask = mask.resize(image.size)
    if final:  # the sample's own icon row and logo stay hidden under ours
        top = design.icon_row.box[1]
        fade = Image.frombytes("L", (1, height), _ramp(height, top, top - 0.06))
        mask = ImageChops.multiply(mask, fade.resize(image.size))
        corner = Image.new("L", image.size, 255)
        left, _, _, bottom = logo_zone(image.size)
        ImageDraw.Draw(corner).rectangle(
            (left - width * 0.03, 0, width, bottom + height * 0.06), fill=0
        )
        corner = corner.filter(ImageFilter.GaussianBlur(width * 0.02))
        mask = ImageChops.multiply(mask, corner)
    return Image.composite(picture, image, mask)


def sample_slides(design: CarouselDesign, topic: str) -> list[SlideText]:
    return [
        sample.model_copy(update={
            "headline": sample.headline.replace("{topic}", topic),
            "body": sample.body.replace("{topic}", topic) if sample.body else None,
        })
        for sample in design.samples
    ]


def preview(
    design: CarouselDesign,
    system: DesignSystem,
    topic: str,
    language: str,
    logo: LogoOverlay | None,
    out: Path,
) -> list[str]:
    """Render every slide as a still with the sample text (free): background, the right half
    of a sample frame of the slide's type, icon row and logo on the last slide, the text.
    Also writes still-prompts.md (what each paid still would ask for) and sheet.png."""
    slides = sample_slides(design, topic)
    lines = [
        f"Limits: {problem}" for problem in slide_problems(slides, design, where="sample")
    ]
    out.mkdir(parents=True, exist_ok=True)
    seen: dict[str, int] = {}
    prompts = [
        f"# Still prompts: {topic}",
        "",
        f"Provider: {design.stills.provider} (stills.provider). Style references: the first "
        f"{design.stills.style_references} frames of the slide's type, attached only if the "
        "image model accepts reference images.",
    ]
    stills: list[Image.Image] = []
    for number, slide in enumerate(slides, start=1):
        frames = style_frames(design, slide.type)
        frame = frames[seen.get(slide.type, 0) % len(frames)] if frames else None
        seen[slide.type] = seen.get(slide.type, 0) + 1
        final = slide.type == design.structure[-1]
        image = _preview_base(design, frame, final).convert("RGBA")
        try:
            layer, notes = slide_layer(slide, design, system, image, language, logo)
            image.alpha_composite(layer)
        except TextOverlayError as error:
            notes = [f"text not rendered: {_overlay_message(error, slide)}"]
        data = _png(image)
        target = out / f"slide_{number:02d}.png"
        target.write_bytes(data)
        with Image.open(io.BytesIO(data)) as done:
            stills.append(done.convert("RGB"))
        source = f"frame {frame.name}" if frame else "no sample frame"
        lines.append(
            f"Slide {number} ({slide.type}, {source}): {target.name}"
            + (f"; {'; '.join(notes)}" if notes else "")
        )
        references = ", ".join(path.name for path in frames[: design.stills.style_references])
        prompts += [
            "",
            f"## Slide {number} ({slide.type})",
            "",
            f"Style references: {references or 'none found'}",
            "",
            still_prompt(design, slide, topic),
        ]
    (out / "still-prompts.md").write_text("\n".join(prompts) + "\n", encoding="utf-8")
    side = design.canvas.width // 4
    sheet = Image.new("RGB", (side * 4, side * ((len(stills) + 3) // 4)))
    for number, still in enumerate(stills):
        sheet.paste(still.resize((side, side)), ((number % 4) * side, (number // 4) * side))
    sheet.save(out / "sheet.png", optimize=True)
    lines += [f"Still prompts: {out / 'still-prompts.md'}", f"Contact sheet: {out / 'sheet.png'}"]
    return lines
