"""The branded person-post card (live fix): templates "insight" (default) and "stat".

config/design_system.json personTemplates sets the look. Over the photo scene the app draws, all
locally and with Pillow: a smooth navy gradient on the left (#010208 to transparent) with a subtle
procedural brand pattern (thin network lines, soft particles), a tag pill, the headline with one
highlight word in the accent blue (at most 3 lines), a short accent line and the German subtitle,
3 bullets with an icon in an accent circle (Tabler Icons webfont, MIT, assets/icons/), the CTA
pill with the short German CTA, a bottom brand bar (website left, small logo right) and the white
logo top right with a soft drop shadow (no box). "stat" puts a stat badge in place of bullet 1.
The photo is cropped so his face and shoulders stay clear of the text column.
"""

import json
import random
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from content_automation.core.faces import face_boxes
from content_automation.workflows.logo import LogoOverlay, load_logo, white_version
from content_automation.workflows.registry import WorkflowError

Template = Literal["insight", "stat"]
TEMPLATES: tuple[Template, ...] = ("insight", "stat")
RGB = tuple[int, int, int]
PixelBox = tuple[int, int, int, int]
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MARK = re.compile(r"\*([^*]+)\*")
DEFAULT_SPEC: dict[str, Any] = {
    "default": "insight",
    "canvas": {"linkedin": [1080, 1350], "instagram": [1080, 1350], "facebook": [1080, 1080]},
    "colors": {"navy": "#010208", "accent": "#0970EB", "subtitle": "#9CC8FF", "text": "#FFFFFF",
               "bar": "#020B1F"},
    "textWidth": 0.45, "margin": 64, "faceClear": 0.05,
    "gradient": {"opacity": 0.94, "solidTo": 0.30, "fadeTo": 0.66},
    "pattern": {"points": 34, "particles": 90, "opacity": 0.2, "seed": 11},
    "tag": {"size": 22, "padX": 18, "padY": 10},
    "headline": {"sizes": [80, 68], "maxLines": 3, "lineHeight": 1.04, "gap": 30},
    "subtitle": {"size": 28, "rule": [56, 4], "gap": 22},
    "bullets": {"circle": 44, "icon": 24, "size": 26, "spacing": 20, "gap": 40},
    "cta": {"size": 24, "deSize": 21, "height": 54, "gap": 40},
    "bar": {"height": 72, "opacity": 0.9, "logoHeight": 30, "size": 22},
    "logo": {"width": 0.19, "margin": 0.045, "shadow": 0.6},
    "stat": {"numberSize": 72, "labelSize": 22, "pad": 20},
    "icons": {"font": "assets/icons/tabler-icons.ttf",
              "codepoints": "assets/icons/tabler-codepoints.json", "allowed": []},
}


class CardError(WorkflowError):
    """The card cannot be drawn (the copy does not fit, the face would sit under the text)."""


@dataclass(frozen=True)
class Copy:
    """What the app writes onto a person post. Card fields (live fix): tag, German subtitle
    (subline), 3 bullets with an icon each, the CTA in English and German, an optional stat."""

    headline: str  # may mark the highlight word like *word*
    subline: str = ""  # the German subtitle (card) or the sub-line (cutout, photo-crop)
    website: str = ""
    bullets: tuple[str, ...] = ()
    tag: str = ""
    icons: tuple[str, ...] = ()
    cta_en: str = ""
    cta_de: str = ""
    stat: str = ""
    stat_label: str = ""
    highlight: tuple[str, ...] = ()  # highlight words when the headline has no *marks*

    def headline_words(self) -> tuple[list[str], set[str]]:
        """(the words without marks, the highlight words casefolded)."""
        marked = {_key(word) for mark in _MARK.findall(self.headline) for word in mark.split()}
        marked |= {_key(word) for phrase in self.highlight for word in phrase.split()}
        return self.headline.replace("*", "").split(), marked


def _key(word: str) -> str:
    return word.casefold().strip(".,:;!?\"'()")


def _rgb(value: str) -> RGB:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def card_spec(raw: dict[str, Any] | None) -> dict[str, Any]:
    """design_system.json personTemplates over the defaults (one level deep)."""
    spec = {key: (dict(value) if isinstance(value, dict) else value)
            for key, value in DEFAULT_SPEC.items()}
    for key, value in (raw or {}).items():
        if isinstance(value, dict) and isinstance(spec.get(key), dict):
            spec[key].update(value)
        elif not key.startswith("_"):
            spec[key] = value
    return spec


def card_size(spec: dict[str, Any], platform: str | None) -> tuple[int, int]:
    found = spec["canvas"].get(platform or "", spec["canvas"].get("linkedin", [1080, 1350]))
    return int(found[0]), int(found[1])


def card_aspect(spec: dict[str, Any], platform: str | None) -> str:
    width, height = card_size(spec, platform)
    return "1:1" if width == height else ("4:5" if height > width else "16:9")


def _path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() or path.exists() else _PROJECT_ROOT / path


@lru_cache(maxsize=4)
def _codepoints(path: str) -> dict[str, str]:
    data = json.loads(_path(path).read_text(encoding="utf-8"))
    return {str(name): chr(int(str(code), 16)) for name, code in data.items()}


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), max(8, size))


def _wrap(words: list[str], font: ImageFont.FreeTypeFont, width: float) -> list[list[str]]:
    lines: list[list[str]] = []
    for word in words:
        if lines and font.getlength(" ".join([*lines[-1], word])) <= width:
            lines[-1].append(word)
        else:
            lines.append([word])
    return lines


def _overlaps(first: PixelBox, second: PixelBox) -> bool:
    return not (first[2] <= second[0] or second[2] <= first[0] or first[3] <= second[1]
                or second[3] <= first[1])


# --- The photo ---------------------------------------------------------------------------------


def scene_crop(photo: Image.Image, size: tuple[int, int], clear_x: float
               ) -> tuple[Image.Image, PixelBox | None]:
    """The photo full-bleed with his face (and shoulders) right of clear_x (a share of the
    width): shifted, and zoomed in up to 1.8x when needed; (canvas, the face box on it)."""
    width, height = size
    base = max(width / photo.width, height / photo.height)
    faces = face_boxes(photo)
    if not faces:
        scaled = photo.resize((round(photo.width * base), round(photo.height * base)),
                              Image.Resampling.LANCZOS)
        left, top = (scaled.width - width) // 2, (scaled.height - height) // 2
        return scaled.crop((left, top, left + width, top + height)), None
    fx0, fy0, fx1, fy1 = faces[0]
    centre_x, centre_y, face_w = (fx0 + fx1) / 2, (fy0 + fy1) / 2, fx1 - fx0

    def target(scale: float) -> float:  # where the face centre must land on the canvas
        return max(0.70 * width, clear_x * width + 1.3 * face_w * photo.width * scale)

    scale = base
    if centre_x * photo.width * scale < target(scale):
        scale = min(max(scale, target(scale) / (centre_x * photo.width)), 1.8 * base)
    scaled = photo.resize((round(photo.width * scale), round(photo.height * scale)),
                          Image.Resampling.LANCZOS)
    left = min(max(round(centre_x * scaled.width - target(scale)), 0), scaled.width - width)
    top = min(max(round(centre_y * scaled.height - 0.30 * height), 0), scaled.height - height)
    canvas = scaled.crop((left, top, left + width, top + height))
    face = (round(fx0 * scaled.width - left), round(fy0 * scaled.height - top),
            round(fx1 * scaled.width - left), round(fy1 * scaled.height - top))
    return canvas, face


def _gradient(size: tuple[int, int], spec: dict[str, Any]) -> Image.Image:
    """The alpha of the navy gradient: solid on the far left, fading out to the right."""
    width, height = size
    rules = spec["gradient"]
    solid, fade = float(rules["solidTo"]) * width, float(rules["fadeTo"]) * width
    row = bytes(round(255 * float(rules["opacity"]) * min(1.0, max(0.0, (fade - x) /
                                                                   max(1.0, fade - solid))))
                for x in range(width))
    return Image.frombytes("L", (width, 1), row).resize(size)


def _pattern(size: tuple[int, int], spec: dict[str, Any], accent: RGB, mask: Image.Image
             ) -> Image.Image:
    """Thin network lines and soft particles on the dark side (low opacity, seeded)."""
    width, height = size
    unit = width / 1080
    rules = spec["pattern"]
    rng = random.Random(int(rules["seed"]))
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    points = [(rng.uniform(0, 0.55 * width), rng.uniform(0, height))
              for _ in range(int(rules["points"]))]
    reach = 0.2 * width
    for index, (x, y) in enumerate(points):
        near = sorted(points[index + 1:], key=lambda p: (p[0] - x) ** 2 + (p[1] - y) ** 2)[:2]
        for nx, ny in near:
            if (nx - x) ** 2 + (ny - y) ** 2 <= reach ** 2:
                draw.line((x, y, nx, ny), fill=(*accent, 150), width=max(1, round(1.2 * unit)))
        radius = 2.4 * unit
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=(*accent, 190))
    for _ in range(int(rules["particles"])):
        x, y, radius = rng.uniform(0, 0.6 * width), rng.uniform(0, height), rng.uniform(1, 3.2)
        draw.ellipse((x - radius * unit, y - radius * unit, x + radius * unit, y + radius * unit),
                     fill=(255, 255, 255, rng.randint(60, 200)))
    layer = layer.filter(ImageFilter.GaussianBlur(0.6 * unit))
    alpha = layer.getchannel("A").point(lambda value: round(value * float(rules["opacity"])))
    alpha = Image.composite(alpha, Image.new("L", size, 0), mask)
    layer.putalpha(alpha)
    return layer


# --- The card ----------------------------------------------------------------------------------


def _logo_white(logo: LogoOverlay, width: int | None = None, height: int | None = None
                ) -> Image.Image:
    white = load_logo(logo.path)
    if not logo.keep_colours:  # brand.json logoSpec.keepColours: the favicon's own colours
        white = white_version(white)
    scale = (width / white.width) if width else ((height or white.height) / white.height)
    return white.resize((max(1, round(white.width * scale)), max(1, round(white.height * scale))),
                        Image.Resampling.LANCZOS)


def render_card(photo: Image.Image, copy: Copy, spec: dict[str, Any], fonts: dict[str, Path],
                logo: LogoOverlay | None, template: Template, platform: str | None,
                strict: bool = True) -> tuple[Image.Image, dict[str, PixelBox], list[str]]:
    """The finished card; the boxes of every element (none overlaps another or the face).
    strict=False (a free preview) reports text over his face as a note instead of refusing."""
    size = card_size(spec, platform)
    width, height = size
    unit = width / 1080
    colors = {name: _rgb(str(value)) for name, value in spec["colors"].items()}
    margin = round(float(spec["margin"]) * unit)
    column = round(float(spec["textWidth"]) * width)
    canvas, face = scene_crop(photo, size, float(spec["textWidth"]) + float(spec["faceClear"]))
    card = canvas.convert("RGBA")
    shade = _gradient(size, spec)
    navy = Image.new("RGBA", size, (*colors["navy"], 255))
    navy.putalpha(shade)
    card = Image.alpha_composite(card, navy)
    card = Image.alpha_composite(card, _pattern(size, spec, colors["accent"], shade))
    draw = ImageDraw.Draw(card)
    boxes: dict[str, PixelBox] = {}
    inner = column - margin

    bar_h = round(float(spec["bar"]["height"]) * unit)
    bar_top = height - bar_h
    rule = spec["headline"]
    head_words, marked = copy.headline_words()
    for head_size in range(round(int(rule["sizes"][0]) * unit),
                           round(int(rule["sizes"][1]) * unit) - 1, -2):
        head_font = _font(fonts["bold"], head_size)
        head_lines = _wrap(head_words, head_font, inner)
        if len(head_lines) <= int(rule["maxLines"]):
            break
    else:
        raise CardError(f"the headline needs more than {rule['maxLines']} lines at "
                        f"{rule['sizes'][1]} px: shorten it")
    tag_font = _font(fonts["semibold"], round(spec["tag"]["size"] * unit))
    sub_font = _font(fonts["regular"], round(spec["subtitle"]["size"] * unit))
    text_font = _font(fonts["medium"], round(spec["bullets"]["size"] * unit))
    icon_font = _font(_path(spec["icons"]["font"]), round(spec["bullets"]["icon"] * unit))
    glyphs = _codepoints(str(spec["icons"]["codepoints"]))

    y = margin
    if copy.tag:  # the tag pill
        pad_x, pad_y = round(spec["tag"]["padX"] * unit), round(spec["tag"]["padY"] * unit)
        tag = copy.tag.upper()
        box = (margin, y, margin + round(tag_font.getlength(tag)) + 2 * pad_x,
               y + tag_font.size + 2 * pad_y)
        draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=(*colors["accent"], 255))
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), tag, font=tag_font, anchor="mm",
                  fill=(*colors["text"], 255))
        boxes["tag"] = box
        y = box[3] + round(rule["gap"] * unit)
    step = round(head_font.size * float(rule["lineHeight"]))
    top, right = y, margin
    for line in head_lines:  # the headline, the highlight word in the accent blue
        x = margin
        for word in line:
            color = colors["accent"] if _key(word) in marked else colors["text"]
            draw.text((x, y), word, font=head_font, fill=(*color, 255))
            x += round(head_font.getlength(word + " "))
        right = max(right, x - round(head_font.getlength(" ")))
        y += step
    boxes["headline"] = (margin, top, right, y)
    if copy.subline:  # the accent line, then the German subtitle
        sub = spec["subtitle"]
        y += round(sub["gap"] * unit)
        line_w, line_h = (round(int(v) * unit) for v in sub["rule"])
        draw.rectangle((margin, y, margin + line_w, y + line_h), fill=(*colors["accent"], 255))
        boxes["rule"] = (margin, y, margin + line_w, y + line_h)
        y += line_h + round(16 * unit)
        top, right = y, margin
        for line in _wrap(copy.subline.split(), sub_font, inner):
            draw.text((margin, y), " ".join(line), font=sub_font,
                      fill=(*colors["subtitle"], 255))
            right = max(right, margin + round(sub_font.getlength(" ".join(line))))
            y += round(sub_font.size * 1.3)
        boxes["subtitle"] = (margin, top, right, y)
    bullets = spec["bullets"]
    circle = round(bullets["circle"] * unit)
    y += round(bullets["gap"] * unit)
    items = list(zip(copy.bullets, [*copy.icons, *[""] * 3], strict=False))
    if template == "stat" and copy.stat:  # the stat badge in place of bullet 1
        stat = spec["stat"]
        number_font = _font(fonts["bold"], round(stat["numberSize"] * unit))
        label_font = _font(fonts["medium"], round(stat["labelSize"] * unit))
        pad = round(stat["pad"] * unit)
        box = (margin, y, column, y + 2 * pad + number_font.size + round(10 * unit)
               + label_font.size)
        draw.rounded_rectangle(box, radius=round(18 * unit), fill=(*colors["navy"], 200),
                               outline=(*colors["accent"], 255), width=max(2, round(2 * unit)))
        draw.text((margin + pad, y + pad), copy.stat, font=number_font,
                  fill=(*colors["accent"], 255))
        draw.text((margin + pad, y + pad + number_font.size + round(10 * unit)),
                  copy.stat_label, font=label_font, fill=(*colors["text"], 255))
        boxes["stat"] = box
        y = box[3] + round(bullets["spacing"] * unit)
        items = items[1:]
    for number, (bullet, icon) in enumerate(items, 1):  # icon in a circle, then the text
        lines = _wrap(bullet.split(), text_font, inner - circle - round(16 * unit))
        line_h = round(text_font.size * 1.25)
        block = max(circle, len(lines) * line_h)
        draw.ellipse((margin, y + (block - circle) // 2, margin + circle,
                      y + (block - circle) // 2 + circle), fill=(*colors["accent"], 255))
        if icon in glyphs:
            draw.text((margin + circle / 2, y + block / 2), glyphs[icon], font=icon_font,
                      anchor="mm", fill=(*colors["text"], 255))
        text_y = y + (block - len(lines) * line_h) // 2
        text_x = margin + circle + round(16 * unit)
        for line in lines:
            draw.text((text_x, text_y), " ".join(line), font=text_font,
                      fill=(*colors["text"], 255))
            text_y += line_h
        right = text_x + max(round(text_font.getlength(" ".join(line))) for line in lines)
        boxes[f"bullet{number}"] = (margin, y, right, y + block)
        y += block + round(bullets["spacing"] * unit)
    if copy.cta_en:  # the CTA pill, the short German CTA beside it or below
        cta = spec["cta"]
        cta_font = _font(fonts["medium"], round(cta["size"] * unit))
        de_font = _font(fonts["regular"], round(cta["deSize"] * unit))
        pill_h = round(cta["height"] * unit)
        pill_w = round(cta_font.getlength(copy.cta_en)) + round(44 * unit)
        label = copy.cta_de
        below = bool(label) and margin + pill_w + round(18 * unit) + de_font.getlength(
            label) > column
        # anchored just above the brand bar, so the card has no empty lower half
        low = bar_top - round(40 * unit) - pill_h - (
            round(14 * unit) + de_font.size if below else 0)
        bottom = y - round(bullets["spacing"] * unit) + round(cta["gap"] * unit)
        y = max(low, bottom)
        box = (margin, y, margin + pill_w, y + pill_h)
        draw.rounded_rectangle(box, radius=pill_h // 2, outline=(*colors["text"], 255),
                               width=max(2, round(2 * unit)), fill=(*colors["navy"], 90))
        draw.text(((box[0] + box[2]) / 2, (box[1] + box[3]) / 2), copy.cta_en, font=cta_font,
                  anchor="mm", fill=(*colors["text"], 255))
        boxes["cta"] = box
        y = box[3]
        if label:
            beside = box[2] + round(18 * unit)
            if not below:
                spot, anchor = (beside, (box[1] + box[3]) / 2), "lm"
            else:
                spot, anchor = (margin, y + round(14 * unit)), "la"
                y += round(14 * unit) + de_font.size
            draw.text(spot, label, font=de_font, anchor=anchor, fill=(*colors["subtitle"], 255))
            left_x = round(spot[0])
            boxes["cta_de"] = (left_x, round(spot[1]) - de_font.size // 2 if anchor == "lm"
                               else round(spot[1]), left_x + round(de_font.getlength(label)),
                               round(spot[1]) + de_font.size)
    if y > bar_top - round(28 * unit):
        raise CardError("the copy does not fit above the brand bar: shorten the headline, "
                        "subtitle or bullets")
    bar = spec["bar"]  # the brand bar: website left, small logo right
    strip = Image.new("RGBA", (width, bar_h), (*colors["bar"], round(255 * float(bar["opacity"]))))
    card.alpha_composite(strip, (0, bar_top))
    site = copy.website.removeprefix("https://").removeprefix("http://").rstrip("/")
    if site:
        draw.text((margin, bar_top + bar_h / 2), site, anchor="lm",
                  font=_font(fonts["medium"], round(bar["size"] * unit)),
                  fill=(*colors["text"], 255))
    boxes["bar"] = (0, bar_top, width, height)
    if logo is not None:
        small = _logo_white(logo, height=round(bar["logoHeight"] * unit))
        card.alpha_composite(small, (width - margin - small.width,
                                     bar_top + (bar_h - small.height) // 2))
        mark = _logo_white(logo, width=round(float(spec["logo"]["width"]) * width))
        edge = round(float(spec["logo"]["margin"]) * width)
        spot = (width - edge - mark.width, edge)
        shadow = Image.new("RGBA", mark.size, (0, 0, 0, 0))
        shadow.putalpha(mark.getchannel("A").point(
            lambda value: round(value * float(spec["logo"]["shadow"]))))
        padded = Image.new("RGBA", (mark.width + 40, mark.height + 40), (0, 0, 0, 0))
        padded.alpha_composite(shadow, (20, 20))
        padded = padded.filter(ImageFilter.GaussianBlur(round(6 * unit)))
        card.alpha_composite(padded, (spot[0] - 20, spot[1] - 20 + round(3 * unit)))
        card.alpha_composite(mark, spot)
        boxes["logo"] = (spot[0], spot[1], spot[0] + mark.width, spot[1] + mark.height)
    named = [(name, box) for name, box in boxes.items() if name != "bar"]
    for index, (name, box) in enumerate(named):
        if box[3] > bar_top and name != "logo":
            raise CardError(f"the {name} would overlap the brand bar")
        for other, second in named[index + 1:]:
            if _overlaps(box, second):
                raise CardError(f"the {name} would overlap the {other}")
    notes = [f"card: template {template}, {width}x{height}"]
    if face is not None:  # his face, and below the chin his widening shoulders, stay clear
        face_w = face[2] - face[0]

        def shoulder_left(y: int) -> float:  # the shoulders widen over one face height
            return face[0] - 0.6 * face_w * min(1.0, max(0.0, (y - face[3]) / max(1, face_w)))

        covered = [name for name, box in named if name != "logo" and (
            _overlaps(box, face) or (box[3] > face[3] and box[2] > shoulder_left(box[3])))]
        message = (f"the {', '.join(covered)} would cover his face or shoulders: a new image is "
                   "needed (him on the right)")
        if covered and strict:
            raise CardError(message)
        notes.append(f"WARNING (preview only): {message}" if covered
                     else "face and shoulders clear of the text")
    else:
        notes.append("no face found on the canvas: the text column was not checked against it")
    return card.convert("RGB"), boxes, notes


def card_fonts(fonts: Any) -> dict[str, Path]:
    """bold, semibold, medium and regular from design_system.json textOverlay.fonts."""
    from content_automation.workflows.text_overlay import resolve_fonts

    extended = fonts.model_copy(update={"weights": {
        **fonts.weights, "semibold": ["SemiBold", "Demi", "Bold"],
        "regular": ["Regular", "Book", "Medium"]}})
    return resolve_fonts(extended, {"bold", "semibold", "medium", "regular"})
