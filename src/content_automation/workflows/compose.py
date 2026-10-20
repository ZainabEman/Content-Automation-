"""Person images composed in the app (live fixes).

config/compose.json `mode` picks the look (and holds the rules):
- scene (default): the model makes a photo scene of Roman (personScene); the app draws the
  branded card over it (workflows/card.py, templates insight and stat from design_system.json
  personTemplates). Copy: tag 2-3 words, headline 3-7 words with one highlight, German subtitle
  <= 8 words, exactly 3 bullets <= 6 words with an icon each, CTA <= 5 words + German <= 3.
- cutout / photo-crop (off): a clean studio photo (personPhoto) cut out onto the brand background
  (rembg u2net_human_seg, CPU, model in .cache/rembg) or cropped with a navy fade; headline <= 8
  words and one sub-line <= 14.
raw_checks (free, local) run on the raw image first: OCR (rapidocr-onnxruntime) finds no text,
exactly one face, at least minFaceHeight of the image height (10% in a scene). A fail is the one
automatic redo within the dry run's max.
"""

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from content_automation.core.config import Settings
from content_automation.core.faces import face_boxes
from content_automation.references import BrandProfileError, load_brand
from content_automation.workflows.card import (
    CardError,
    Copy,
    Template,
    card_aspect,
    card_fonts,
    card_spec,
    render_card,
)
from content_automation.workflows.design_system import load_design_system
from content_automation.workflows.logo import LogoOverlay, logo_zone, paste_logo
from content_automation.workflows.registry import WorkflowError
from content_automation.workflows.text_overlay import TextOverlay, overlay_colors, resolve_fonts

Mode = Literal["scene", "cutout", "photo-crop"]
RGB = tuple[int, int, int]
PixelBox = tuple[int, int, int, int]
MODES: tuple[Mode, ...] = ("scene", "cutout", "photo-crop")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = _PROJECT_ROOT / ".cache" / "rembg"  # git-ignored
DEFAULTS: dict[str, Any] = {
    "outputSizes": {"1:1": [1080, 1080], "4:5": [1080, 1350], "9:16": [1080, 1920],
                    "16:9": [1920, 1080]},
    "rawChecks": {"minFaceHeight": {"scene": 0.10, "cutout": 0.18, "photo-crop": 0.18},
                  "minTextScore": 0.6},
    "cutout": {"model": "u2net_human_seg", "minCover": 0.15, "maxCover": 0.70,
               "minMainShare": 0.9, "maxEdgeNoise": 0.04, "headTop": 0.18, "bodyHeight": 0.85,
               "centerX": 0.70},
    "photoCrop": {"faceX": 0.78, "faceY": 0.30, "fadeTo": 0.62},
    "look": {"glowCenter": [0.70, 0.42], "glowRadius": 0.55, "glowOpacity": 0.38,
             "blueGrade": 0.08, "shadowOpacity": 0.38, "rimOpacity": 0.45,
             "sceneGlowOpacity": 0.22},
    "overlay": {"panelOpacity": 0.88, "margin": 0.06, "textRight": 0.50, "textTop": 0.18,
                "headlineMaxWords": 8, "sublineMaxWords": 14},
    "insight": {"tagWords": [2, 3], "headlineWords": [3, 7], "subtitleMaxWords": 8,
                "bullets": 3, "bulletMaxWords": 6, "ctaEnMaxWords": 5, "ctaDeMaxWords": 3},
}


class ComposeError(WorkflowError):
    """The post cannot be composed (e.g. the text does not fit)."""


@dataclass
class Composed:
    image: Image.Image
    mode: Mode
    notes: list[str] = field(default_factory=list)
    boxes: dict[str, PixelBox] = field(default_factory=dict)  # panel, pill, logo


def copy_from_overlay(overlay: TextOverlay, card: dict[str, Any] | None = None) -> Copy:
    """Headline (with its highlight words), the subtitle or sub-line, the website, the points
    and the card fields (tag, icons, CTA in English and German, stat) from the brief."""
    def joined(field: str) -> str:
        found = overlay.texts.get(field)  # type: ignore[call-overload]
        return " ".join(found.paragraphs) if found is not None else ""

    card = card or {}
    points = overlay.texts.get("points")
    head = overlay.texts.get("headline")
    return Copy(
        str(card.get("headline") or joined("headline")),
        str(card.get("subtitle") or joined("subheadline") or joined("audience_line")),
        joined("footer"), tuple(points.paragraphs) if points is not None else (),
        tag=str(card.get("tag") or ""), icons=tuple(card.get("icons") or ()),
        cta_en=str(card.get("ctaEn") or ""), cta_de=str(card.get("ctaDe") or ""),
        stat=str(card.get("stat") or ""), stat_label=str(card.get("statLabel") or ""),
        highlight=tuple(sorted(head.highlight)) if head is not None else ())


def person_card(settings: Settings) -> dict[str, Any]:
    """design_system.json personTemplates over the card defaults."""
    return card_spec(load_design_system(settings.design_system_file).person_templates)


def card_aspect_for(settings: Settings, platform: str | None) -> str:
    """The canvas aspect of a person post on this platform (4:5 LinkedIn and Instagram, 1:1
    Facebook): the scene is generated at it."""
    return card_aspect(person_card(settings), platform)


def compose_config(settings: Settings) -> dict[str, Any]:
    path = Path(settings.compose_file)
    path = path if path.is_absolute() or path.exists() else _PROJECT_ROOT / path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    merged = {key: (dict(value) if isinstance(value, dict) else value)
              for key, value in DEFAULTS.items()}
    for key, value in (data if isinstance(data, dict) else {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        elif not key.startswith("_"):
            merged[key] = value
    if merged.get("mode") not in MODES:
        merged["mode"] = "scene"
    return merged


def _words(text: str) -> int:
    return sum(any(char.isalnum() for char in token) for token in text.replace("*", "").split())


def copy_problems(copy: Copy, config: dict[str, Any], mode: Mode | None = None,
                  icons: tuple[str, ...] = ()) -> list[str]:
    """Copy that breaks the person post's limits (the free dry run refuses it)."""
    rules = config["overlay"]
    problems = []
    head, sub = _words(copy.headline), _words(copy.subline)
    if not head:
        problems.append("headline: missing")
    if (mode or config["mode"]) != "scene":
        if head > rules["headlineMaxWords"]:
            problems.append(f"headline: {head} words; a person post allows "
                            f"{rules['headlineMaxWords']} (shorten it)")
        if sub > rules["sublineMaxWords"]:
            problems.append(f"sub-line: {sub} words; a person post allows "
                            f"{rules['sublineMaxWords']} (the rest goes in the caption)")
        return problems
    card = config["insight"]
    low, high = card["headlineWords"]
    if head and not low <= head <= high:
        problems.append(f"headline: {head} words (allowed {low}-{high})")
    marks = len({word for word in copy.headline_words()[1]})
    if marks != 1:
        problems.append(f"headline: mark exactly 1 highlight word (found {marks})")
    tag_low, tag_high = card["tagWords"]
    if not copy.tag:
        problems.append("tag: missing (e.g. AI RISK · HR)")
    elif not tag_low <= _words(copy.tag) <= tag_high or copy.tag != copy.tag.upper():
        problems.append(f"tag: {tag_low}-{tag_high} words in capitals")
    if not sub:
        problems.append("subtitle: missing (German, the core message)")
    elif sub > card["subtitleMaxWords"]:
        problems.append(f"subtitle: {sub} words; at most {card['subtitleMaxWords']}")
    if len(copy.bullets) != card["bullets"]:
        problems.append(f"bullets: {len(copy.bullets)}; exactly {card['bullets']}")
    problems += [f"bullet {number}: {_words(text)} words; at most {card['bulletMaxWords']}"
                 for number, text in enumerate(copy.bullets, 1)
                 if _words(text) > card["bulletMaxWords"]]
    if len(copy.icons) != card["bullets"] or (icons and not set(copy.icons) <= set(icons)):
        problems.append(f"icons: one allowed icon per bullet ({', '.join(icons) or 'see config'})")
    if not copy.cta_en or _words(copy.cta_en) > card["ctaEnMaxWords"]:
        problems.append(f"cta_en: 1-{card['ctaEnMaxWords']} words")
    if not copy.cta_de or _words(copy.cta_de) > card["ctaDeMaxWords"]:
        problems.append(f"cta_de: 1-{card['ctaDeMaxWords']} German words")
    return problems


def _load(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return ImageOps.exif_transpose(source).convert("RGB")


# --- 1. Raw checks ----------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _ocr_engine() -> Any:
    from rapidocr_onnxruntime import RapidOCR

    return RapidOCR()


def _ocr_texts(image: Image.Image, min_score: float) -> list[str]:
    """Text the OCR reads in the image (local, rapidocr-onnxruntime)."""
    result, _ = _ocr_engine()(np.asarray(image))
    return [str(text).strip() for _, text, score in (result or [])
            if float(score) >= min_score and len(str(text).strip()) >= 2]


def raw_checks(image: Path, settings: Settings) -> list[str]:
    """What is wrong with the raw photo (empty: passed): text, not one face, a small face."""
    config = compose_config(settings)
    rules = config["rawChecks"]
    minimum = rules["minFaceHeight"]
    min_face = float(minimum.get(config["mode"], 0.18) if isinstance(minimum, dict) else minimum)
    photo = _load(image)
    problems = []
    texts = _ocr_texts(photo, float(rules["minTextScore"]))
    if texts:
        problems.append("text in the photo: " + ", ".join(f'"{text}"' for text in texts[:3]))
    faces = face_boxes(photo)
    if len(faces) != 1:
        problems.append(f"{len(faces)} faces found (exactly 1 needed)")
    elif faces[0][3] - faces[0][1] < min_face:
        problems.append(f"face height {faces[0][3] - faces[0][1]:.0%} of the image (at least "
                        f"{min_face:.0%})")
    return problems


# --- 2. Cutout --------------------------------------------------------------------------------


@lru_cache(maxsize=2)
def _session(model: str) -> Any:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("U2NET_HOME", str(CACHE_DIR))
    from rembg import new_session

    return new_session(model, providers=["CPUExecutionProvider"])


def _human_mask(image: Image.Image, model: str) -> Image.Image:
    """The person mask (rembg on the CPU; the model is downloaded once into .cache/rembg)."""
    from rembg import remove

    mask = remove(image, session=_session(model), only_mask=True)
    return cast(Image.Image, mask).convert("L")


def mask_problems(mask: Image.Image, rules: dict[str, Any]) -> list[str]:
    binary = np.asarray(mask.convert("L")) > 127
    cover = float(binary.mean())
    problems = []
    if not float(rules["minCover"]) <= cover <= float(rules["maxCover"]):
        problems.append(f"the mask covers {cover:.0%} (allowed {float(rules['minCover']):.0%}-"
                        f"{float(rules['maxCover']):.0%})")
    if not binary.any():
        return problems
    _, _, stats, _ = cv2.connectedComponentsWithStats(binary.astype(np.uint8), connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]
    main = float(areas.max() / areas.sum())
    if main < float(rules["minMainShare"]):
        problems.append(f"the mask is in pieces (the main part is {main:.0%})")
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    smooth = cv2.morphologyEx(cv2.morphologyEx(binary.astype(np.uint8), cv2.MORPH_OPEN, kernel),
                              cv2.MORPH_CLOSE, kernel).astype(bool)
    noise = float(np.logical_xor(binary, smooth).sum() / binary.sum())
    if noise > float(rules["maxEdgeNoise"]):
        problems.append(f"ragged edge ({noise:.1%} of the mask)")
    return problems


# --- 3. Background and person -----------------------------------------------------------------


def _mix(color: RGB, other: RGB, share: float) -> RGB:
    return cast(RGB, tuple(round(a * (1 - share) + b * share) for a, b in zip(color, other,
                                                                               strict=True)))


def _solid(size: tuple[int, int], color: RGB) -> Image.Image:
    return Image.new("RGB", size, color)


def _scaled(mask: Image.Image, opacity: float) -> Image.Image:
    return mask.point(lambda value: round(value * opacity))


def _background(size: tuple[int, int], colors: dict[str, RGB], look: dict[str, Any]
                ) -> Image.Image:
    """The brand background: a navy gradient with a soft blue glow (local, no model)."""
    width, height = size
    top, bottom = np.array(colors["background"]), np.array(_mix(colors["background"],
                                                                (0, 0, 0), 0.35))
    ramp = np.linspace(0.0, 1.0, height)[:, None, None]
    pixels = (top * (1 - ramp) + bottom * ramp).repeat(width, axis=1)
    canvas = Image.fromarray(pixels.astype(np.uint8), "RGB")
    glow = Image.new("L", size, 0)
    cx, cy = (float(v) for v in look["glowCenter"])
    radius = float(look["glowRadius"]) * width
    ImageDraw.Draw(glow).ellipse((cx * width - radius, cy * height - radius,
                                 cx * width + radius, cy * height + radius), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(radius * 0.45))
    canvas.paste(_solid(size, colors["accent"]), (0, 0), _scaled(glow, float(look["glowOpacity"])))
    return canvas


def _place_person(canvas: Image.Image, photo: Image.Image, mask: Image.Image,
                  colors: dict[str, RGB], rules: dict[str, Any], look: dict[str, Any],
                  text_right: float) -> None:
    """Roman on the right: head top at headTop, body bodyHeight of the canvas height (at most
    0.75 of its width); his face always clears the text column (left of text_right)."""
    width, height = canvas.size
    box = mask.point(lambda value: 255 if value > 127 else 0).getbbox()
    if box is None:
        raise ComposeError("the cutout mask is empty")
    person, alpha = photo.crop(box), mask.crop(box)
    scale = min(float(rules["bodyHeight"]) * height / person.height, 0.75 * width / person.width)
    size = (max(1, round(person.width * scale)), max(1, round(person.height * scale)))
    person, alpha = person.resize(size, Image.Resampling.LANCZOS), alpha.resize(
        size, Image.Resampling.LANCZOS)
    person = Image.blend(person, _solid(size, colors["accent"]), float(look["blueGrade"]))
    x = min(round(float(rules["centerX"]) * width - size[0] / 2), width - round(size[0] * 0.9))
    faces = face_boxes(photo)
    if faces:  # shift right until the face is clear of the text column
        face_left = x + (faces[0][0] * photo.width - box[0]) * scale
        x += max(0, round((text_right + 0.03) * width - face_left))
    y = round(float(rules["headTop"]) * height)
    pad = max(4, round(width * 0.03))
    padded = Image.new("L", (size[0] + 2 * pad, size[1] + 2 * pad), 0)
    padded.paste(alpha, (pad, pad))
    shadow = _scaled(padded.filter(ImageFilter.GaussianBlur(pad * 0.6)),
                     float(look["shadowOpacity"]))
    rim = _scaled(padded.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(pad / 2)),
                  float(look["rimOpacity"]))
    offset = (round(-0.012 * width), round(0.015 * height))
    canvas.paste(_solid(padded.size, (0, 0, 0)), (x - pad + offset[0], y - pad + offset[1]),
                 shadow)
    canvas.paste(_solid(padded.size, colors["accent"]), (x - pad, y - pad), rim)
    canvas.paste(person, (x, y), alpha)


def _photo_crop(photo: Image.Image, size: tuple[int, int], rules: dict[str, Any],
                colors: dict[str, RGB]) -> Image.Image:
    """The raw photo cropped so his face is in the right third, a navy fade on the left."""
    width, height = size
    faces = face_boxes(photo)
    fx, fy = ((faces[0][0] + faces[0][2]) / 2, (faces[0][1] + faces[0][3]) / 2) if faces else (
        0.5, 0.3)
    face_x, face_y = float(rules["faceX"]), float(rules["faceY"])
    scale = max(width / photo.width, height / photo.height)
    if fx > 0:  # zoom in (at most 2x) until the face can sit at faceX
        scale = min(max(scale, face_x * width / (fx * photo.width)), 2 * scale)
    scaled = photo.resize((round(photo.width * scale), round(photo.height * scale)),
                          Image.Resampling.LANCZOS)
    left = min(max(round(fx * scaled.width - face_x * width), 0), scaled.width - width)
    top = min(max(round(fy * scaled.height - face_y * height), 0), scaled.height - height)
    canvas = scaled.crop((left, top, left + width, top + height))
    fade_to = max(2, round(float(rules["fadeTo"]) * width))
    hold = round(fade_to * 0.5)  # solid behind the text column, then a soft fade to the face
    ramp = np.clip(1 - (np.arange(width) - hold) / (fade_to - hold), 0, 1) * 0.96 * 255
    fade = Image.fromarray(np.tile(ramp.astype(np.uint8), (height, 1)), "L")
    canvas.paste(_solid(size, colors["background"]), (0, 0), fade)
    return canvas


# --- 4. Overlay -------------------------------------------------------------------------------


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        trial = f"{lines[-1]} {word}" if lines else word
        if lines and font.getlength(trial) <= width:
            lines[-1] = trial
        else:
            lines.append(word)
    return lines


def _overlaps(first: PixelBox, second: PixelBox) -> bool:
    return not (first[2] <= second[0] or second[2] <= first[0] or first[3] <= second[1]
                or second[3] <= first[1])


def _overlay(canvas: Image.Image, copy: Copy, colors: dict[str, RGB], fonts: dict[str, Path],
             rules: dict[str, Any], logo: LogoOverlay | None) -> dict[str, PixelBox]:
    """Top-down: the logo zone, the text panel, the pill area; nothing overlaps."""
    width, height = canvas.size
    margin = round(float(rules["margin"]) * width)
    pad = round(width * 0.03)
    pill_font = ImageFont.truetype(str(fonts["medium"]), max(14, round(width * 0.024)))
    site = copy.website.removeprefix("https://").removeprefix("http://").rstrip("/")
    pill_h = round(pill_font.size * 2.2)
    pill_top = height - margin - pill_h
    left, right = margin, round(float(rules["textRight"]) * width)
    top = max(round(float(rules["textTop"]) * height), logo_zone(canvas.size)[3]
              if right > logo_zone(canvas.size)[0] else 0)
    room = pill_top - round(height * 0.03) - top
    inner = right - left - 2 * pad
    for size in range(round(width * 0.085), round(width * 0.04) - 1, -2):
        head_font = ImageFont.truetype(str(fonts["bold"]), size)
        sub_font = ImageFont.truetype(str(fonts["medium"]), max(14, round(size * 0.42)))
        head = _wrap(copy.headline, head_font, inner)
        sub = _wrap(copy.subline, sub_font, inner) if copy.subline else []
        head_h, sub_h = round(size * 1.08), round(sub_font.size * 1.3)
        gap = round(size * 0.45) if sub else 0
        needed = 2 * pad + len(head) * head_h + gap + len(sub) * sub_h
        if len(head) <= 4 and len(sub) <= 4 and needed <= room:
            break
    else:
        raise ComposeError(f"the headline and sub-line do not fit beside the person in "
                           f"{width}x{height}; shorten them")
    panel = (left, top, right, top + needed)
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    alpha = round(float(rules["panelOpacity"]) * 255)
    draw.rounded_rectangle(panel, radius=round(width * 0.02), fill=(*colors["background"], alpha))
    y = top + pad
    for line in head:
        draw.text((left + pad, y), line, font=head_font, fill=(*colors["text"], 255))
        y += head_h
    y += gap
    for line in sub:
        draw.text((left + pad, y), line, font=sub_font, fill=(*colors["accent"], 255))
        y += sub_h
    boxes: dict[str, PixelBox] = {"panel": panel}
    if site:
        pill = (margin, pill_top, margin + round(pill_font.getlength(site)) + 2 * pad,
                pill_top + pill_h)
        draw.rounded_rectangle(pill, radius=pill_h // 2, fill=(*colors["background"], alpha),
                               outline=(*colors["accent"], 255), width=max(2, width // 400))
        draw.text((pill[0] + pad, pill_top + pill_h / 2), site, font=pill_font, anchor="lm",
                  fill=(*colors["text"], 255))
        boxes["pill"] = pill
    if logo is not None:
        boxes["logo"] = logo_zone(canvas.size)
    named = list(boxes.items())
    for index, (name, box) in enumerate(named):
        for other, second in named[index + 1:]:
            if _overlaps(box, second):
                raise ComposeError(f"the {name} would overlap the {other}")
    composed = Image.alpha_composite(canvas.convert("RGBA"), layer)
    if logo is not None:
        paste_logo(composed, composed, logo)  # top right, no box behind it
    canvas.paste(composed.convert("RGB"))
    return boxes


# --- Together ---------------------------------------------------------------------------------


def brand_look(settings: Settings) -> tuple[dict[str, RGB], dict[str, Path]]:
    """The brand's colour roles (background as a dark navy) and the bold and medium fonts."""
    system = load_design_system(settings.design_system_file)
    spec = system.text_overlay
    if spec is None:
        raise ComposeError("design_system.json has no textOverlay (fonts and colours)")
    try:
        brand = load_brand(settings.references_dir)
    except BrandProfileError:
        brand = None
    colors = cast(dict[str, RGB], overlay_colors(brand, system, spec))
    return colors, resolve_fonts(spec.fonts, {"bold", "medium"})


def compose_post(photo: Image.Image, settings: Settings, aspect: str, copy: Copy,
                 logo: LogoOverlay | None, mode: Mode | None = None, *,
                 platform: str | None = None, template: Template | None = None,
                 strict: bool = True) -> Composed:
    """The finished person post from the raw photo (no model call)."""
    config = compose_config(settings)
    size = cast(tuple[int, int], tuple(config["outputSizes"].get(aspect, [1080, 1080])))
    chosen: Mode = mode or cast(Mode, config["mode"])
    if chosen == "scene":  # the branded card (insight, or stat when a verified stat exists)
        system = load_design_system(settings.design_system_file)
        if system.text_overlay is None:
            raise ComposeError("design_system.json has no textOverlay (fonts)")
        spec = card_spec(system.person_templates)
        picked: Template = template or ("stat" if copy.stat else cast(Template, spec["default"]))
        try:
            image, boxes, card_notes = render_card(photo, copy, spec,
                                              card_fonts(system.text_overlay.fonts), logo,
                                              picked, platform, strict)
        except CardError as error:
            raise ComposeError(str(error)) from None
        return Composed(image, chosen, [*card_notes, f"composed in the app: mode scene, "
                                                f"{image.width}x{image.height}"], boxes)
    colors, fonts = brand_look(settings)
    notes: list[str] = []
    canvas: Image.Image | None = None
    if chosen == "cutout":
        mask = _human_mask(photo, str(config["cutout"]["model"]))
        problems = mask_problems(mask, config["cutout"])
        if problems:
            notes.append("cutout not clean (" + "; ".join(problems) + "): photo-crop used")
            chosen = "photo-crop"
        else:
            canvas = _background(size, colors, config["look"])
            _place_person(canvas, photo, mask, colors, config["cutout"], config["look"],
                          float(config["overlay"]["textRight"]))
    if canvas is None:
        canvas = _photo_crop(photo, size, config["photoCrop"], colors)
    boxes = _overlay(canvas, copy, colors, fonts, config["overlay"], logo)
    notes.append(f"composed in the app: mode {chosen}, {size[0]}x{size[1]}")
    return Composed(canvas, chosen, notes, boxes)
