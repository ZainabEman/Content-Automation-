"""Layout variants (config/design_directions.json): reusable layouts rendered by code.

v5 (PRD R4/R5): a variant ("direction" in the code) is one layout of one of the four social
categories, derived from the approved company references (config/brand_refs.json,
brand/reference-analysis.md): Instagram carousel (format carousel, 1:1), Facebook post
(fb_single, 4:5), Facebook ad (fb_ad, 4:5) and LinkedIn post (li_single, 3:4). Founder (Roman)
variants are variants inside a category (id with R, e.g. LI-R1), never a fifth category. Each
variant names its background treatment; rotation keys on variant + treatment. Layouts are zones
in shares of the canvas (logo, headline, body, items, visual, cta, footer, …), colours are
brand.json token names only and the fonts are the brand's. The loader checks the rules that
keep designs on brand before anything is rendered: tokens only, text inside the 64 px margin,
no two text zones on top of each other, text over a picture only on a panel or scrim, text
limits for every text zone, the canvas of each category, carousels of 5-6 slides without Roman
and with the logo (and an optional website) only on the last slide, LinkedIn's logo at a side
corner. Selection and rotation: content/direction_pick.py; rendering: workflows/design_render.py.
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.core.files import CamelModel
from content_automation.references.brand import TokenRole

DirectionFormat = Literal["fb_single", "fb_ad", "li_single", "carousel"]
Platform = Literal["linkedin", "facebook", "instagram"]
# roman_higgsfield (2026-10-20): Roman by Higgsfield Soul 2.0 from his saved character, prompt
# built from config/roman_image_guidelines.json; roman_lora: the disabled RunPod/ComfyUI route
Subject = Literal["roman_real", "roman_lora", "roman_higgsfield", "illustration", "none"]
Provider = Literal["template", "openrouter", "comfyui", "higgsfield_soul"]
ZoneKind = Literal["logo", "text", "items", "visual", "shape", "footer", "swipe", "icons",
                   "arrow"]
TextRole = Literal["eyebrow", "headline", "sub", "body", "cta", "tagline", "badge", "number"]
ItemsLayout = Literal["icon_list", "bullets", "pairs", "zigzag", "cycle", "orbit", "value_map",
                      "numbered_cards", "floating_cards"]
ShapeKind = Literal["panel", "glass", "rule", "bar", "glow", "scrim", "ring", "pill", "dots",
                    "chevrons", "bars", "wave", "arcs", "frame"]  # v6 decorations (R3.2)
VisualShape = Literal["rect", "circle", "cutout", "full"]
Weight = Literal["regular", "medium", "semibold", "bold", "extrabold"]
Box = tuple[float, float, float, float]
FORMATS: tuple[DirectionFormat, ...] = ("fb_single", "fb_ad", "li_single", "carousel")
# PRD R4: one category per format, each with its canvas (from the approved references)
CATEGORY: dict[str, str] = {"carousel": "instagram_carousel", "fb_single": "facebook_post",
                            "fb_ad": "facebook_ad", "li_single": "linkedin_post"}
CANVAS: dict[str, str] = {"carousel": "1:1", "fb_single": "4:5", "fb_ad": "4:5",
                          "li_single": "3:4"}
CAROUSEL_SLIDES = (5, 6)
CORNER = 0.2  # LinkedIn: the logo sits within this share of a side corner
ROMAN_SUBJECTS: tuple[Subject, ...] = ("roman_real", "roman_lora", "roman_higgsfield")
# a founder variant's two mirrored layouts: Roman right (text left) and Roman left (text right)
SIDE_LAYOUTS = {"S-R": "roman_right", "S-L": "roman_left"}
CONFIG_FILE = Path("config/design_directions.json")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class DirectionError(ValueError):
    """design_directions.json is invalid, or a direction cannot be used here."""


class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


def check_box(box: Box) -> None:
    left, top, right, bottom = box
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError(f"box {list(box)}: needs 0 <= left < right <= 1, top < bottom")


def boxes_overlap(first: Box, second: Box) -> bool:
    return (first[0] < second[2] and second[0] < first[2] and first[1] < second[3]
            and second[1] < first[3])


def covers(outer: Box, inner: Box, slack: float = 0.002) -> bool:
    return (outer[0] - slack <= inner[0] and outer[1] - slack <= inner[1]
            and inner[2] <= outer[2] + slack and inner[3] <= outer[3] + slack)


class Pill(_Model):
    """The whole text inside a rounded pill (a headline pill, a badge, a CTA button)."""

    fill: TokenRole | None = None
    outline: TokenRole | None = None
    alpha: float = Field(default=1.0, gt=0, le=1)


class Gradient(_Model):
    """A fade of one token from `start` to `end` opacity along `toward` (a scrim)."""

    color: TokenRole
    start: float = Field(ge=0, le=1)
    end: float = Field(ge=0, le=1)
    toward: Literal["down", "up", "right", "left"] = "down"


class Zone(_Model):
    """One element of a layout. Text-bearing kinds: text, items, footer, swipe, icons."""

    kind: ZoneKind
    box: Box
    bleed: bool = False  # shapes and visuals may reach the canvas edge
    field: str | None = None  # the copy field it shows
    role: TextRole | None = None  # text: decides the contrast rule (headline 3:1, else 4.5:1)
    optional: bool = False  # an empty field leaves the zone out
    # text style
    size: int | None = Field(default=None, gt=0)  # largest font size, px at 1080 px width
    weight: Weight = "medium"
    color: TokenRole | None = None  # default: the layout theme's text token
    accent: TokenRole = "accent"  # *word* in the copy
    highlight: TokenRole = "highlight"  # [[phrase]] in the copy: a pill behind it
    highlight_text: TokenRole = "primary"  # the phrase's colour inside that pill
    upper: bool = False
    align: Literal["left", "center", "right"] = "left"
    valign: Literal["top", "middle", "bottom"] = "top"
    line_height: float = Field(default=1.12, ge=0.8, le=2.0)
    tracking: float = Field(default=0.0, ge=0, le=0.5)  # letter spacing, share of the size
    pill: Pill | None = None
    underline: bool = False
    vertical: bool = False  # rotated 90°, read bottom to top
    icon: str | None = None  # a Tabler icon in the CTA button (v6: drawn clear of the text)
    icon_side: Literal["left", "right"] = "right"  # v6: circle-arrow right, calendar/play left
    cut: float = Field(default=0.0, ge=0, le=0.3)  # v6 panel: one angled cut corner (share)
    # items
    layout: ItemsLayout | None = None
    count: tuple[int, int] | None = None  # fewest and most items
    icons_field: str | None = None  # one icon name per item
    numbered: bool = False
    card: TokenRole | None = None  # card fill
    card_alpha: float = Field(default=1.0, gt=0, le=1)
    # shapes
    shape: ShapeKind | None = None
    fill: TokenRole | None = None
    alpha: float = Field(default=1.0, gt=0, le=1)
    radius: float = Field(default=0.0, ge=0, le=0.5)  # share of the canvas width
    outline: TokenRole | None = None
    gradient: Gradient | None = None
    # visual
    visual_shape: VisualShape | None = None
    fade: bool = False  # soft edges into the background
    mono: bool = False  # greyscale (CS-2), the accent glow added by code
    # footer
    elements: list[Literal["website", "email", "phone", "handles", "cta", "tagline"]] = Field(
        default_factory=list)
    divider: bool = False
    # swipe / icons / arrow
    style: Literal["pill", "arrow_circle", "chevrons", "hand_drawn", "engagement"] | None = None
    label: str | None = None
    names: list[str] = Field(default_factory=list)  # icons: fixed names
    labels: list[str] = Field(default_factory=list)  # icons: fixed labels (Liken, Teilen, …);
    # "LIKEN|wenn du zustimmst": a label and the small line under it (the engagement bar)

    @model_validator(mode="after")
    def _check(self) -> Self:
        check_box(self.box)
        if self.kind == "text" and (not self.field or self.role is None or self.size is None):
            raise ValueError("a text zone needs field, role and size")
        if self.kind == "items" and (not self.field or self.layout is None or self.size is None
                                     or self.count is None):
            raise ValueError("an items zone needs field, layout, size and count")
        if self.kind == "shape" and self.shape is None:
            raise ValueError("a shape zone needs shape")
        if self.kind == "shape" and self.shape != "scrim" and self.fill is None and (
                self.outline is None):
            raise ValueError("a shape zone needs fill or outline")
        if self.kind == "visual" and self.visual_shape is None:
            raise ValueError("a visual zone needs visualShape")
        if self.kind == "footer" and (not self.elements or self.size is None):
            raise ValueError("a footer zone needs elements and size")
        if self.kind in ("swipe", "arrow") and self.style is None:
            raise ValueError(f"a {self.kind} zone needs style")
        if self.count is not None and not 1 <= self.count[0] <= self.count[1] <= 6:
            raise ValueError("count: 1 <= fewest <= most <= 6")
        if self.bleed and self.kind not in ("shape", "visual", "footer"):
            raise ValueError("only shapes, visuals and footer bars may bleed to the edge")
        return self

    @property
    def bears_text(self) -> bool:
        """Copy-carrying zones: they need textLimits and may not overlap other text."""
        return self.kind in ("text", "items", "footer") or (
            self.kind == "icons" and (self.field is not None or bool(self.labels)))

    @property
    def reserved(self) -> bool:
        """Zones other text may not cover: text, the logo, swipe marks, icons, arrows."""
        return self.bears_text or self.kind in ("logo", "swipe", "icons", "arrow")


class TextLimit(_Model):
    max_chars: int = Field(gt=0)
    max_lines: int = Field(ge=1)
    min_font_px: int = Field(gt=0)  # px at 1080 px width; smaller does not fit: an error


class Background(_Model):
    fill: TokenRole
    gradient: Literal["blue", "silver"] | None = None  # brand.json gradients
    angle: int = Field(default=180, ge=0, lt=360)  # 180: top to bottom
    glows: list[tuple[TokenRole, float, float, float, float]] = Field(default_factory=list)
    # glow: token, centre x, centre y, radius (shares), opacity
    vignette: float = Field(default=0.0, ge=0, le=1)  # v6: darkened edges (R3.2 base)


class Layout(_Model):
    """One layout: the post, or one carousel slide role."""

    theme: Literal["dark", "light", "photo"]
    background: Background
    fields: dict[str, str]  # copy field -> what the writer puts in it
    zones: dict[str, Zone]  # drawn in this order
    text_limits: dict[str, TextLimit] = Field(default_factory=dict)  # per text zone name
    platforms: list[Platform] = Field(default_factory=list)  # variant only for these

    def text_color(self) -> TokenRole:
        return "text_on_light" if self.theme == "light" else "text_on_dark"


class Visual(_Model):
    subject: Subject
    placement: str = ""
    prompt: str = ""  # {illustration}: the writer's picture; Roman: built from the pools

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.subject == "roman_real":  # a real photo is never the final image of Roman
            raise ValueError("Roman is always generated by his LoRA on ComfyUI (subject "
                             "roman_lora); real photos are identity references only")
        if self.subject in ("illustration", "roman_lora") and not self.prompt:  # higgsfield:
            # the prompt comes from config/roman_image_guidelines.json
            raise ValueError(f"a {self.subject} visual needs a prompt template")
        if self.subject == "illustration" and "{illustration}" not in self.prompt:
            raise ValueError("an illustration prompt needs {illustration}")
        if self.prompt and "no text" not in self.prompt.lower():
            raise ValueError("the visual prompt must ask for no text in the image")
        return self


class SlideRole(_Model):
    role: str = Field(min_length=1)
    layout: str = Field(min_length=1)
    repeat: tuple[int, int] = (1, 1)  # fewest and most slides of this role
    visual: bool = True  # the slide has a generated picture (else: template only, free)


class Direction(_Model):
    id: str = Field(pattern=r"^(FB|FA|LI|CS)-R?\d+$")  # R: a founder (Roman) variant
    name: str = Field(min_length=1)
    format: DirectionFormat
    platforms: list[Platform] = Field(min_length=1)
    purpose: str = Field(min_length=1)
    content_types: list[str] = Field(min_length=1)
    topic_tags: list[str] = Field(default_factory=list)
    canvas: str = "4:5"
    treatment: str = Field(min_length=1)  # background treatment (R5.3 rotation key)
    provider: Provider
    visual: Visual
    layouts: dict[str, Layout] = Field(min_length=1)
    pick: Literal["single", "platform", "rotate", "side"] = "single"  # side: Roman's side
    slide_roles: list[SlideRole] = Field(default_factory=list)
    slide_count: tuple[int, int] | None = None
    consistent: list[str] = Field(default_factory=list)
    may_vary: list[str] = Field(default_factory=list)
    reference_ids: list[str] = Field(default_factory=list)
    weight: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.format == "carousel":
            if self.visual.subject in ROMAN_SUBJECTS:
                raise ValueError(f"{self.id}: carousels never show Roman")
            if not self.slide_roles or self.slide_count is None:
                raise ValueError(f"{self.id}: a carousel needs slideRoles and slideCount")
            roles = [role.role for role in self.slide_roles]
            if roles[0] != "cover" or roles[-1] != "cta":
                raise ValueError(f"{self.id}: slides start with cover and end with cta")
            unknown = [role.layout for role in self.slide_roles if role.layout not in self.layouts]
            if unknown:
                raise ValueError(f"{self.id}: slide roles name unknown layouts {unknown}")
            low = sum(role.repeat[0] for role in self.slide_roles)
            high = sum(role.repeat[1] for role in self.slide_roles)
            if not (low <= self.slide_count[0] <= self.slide_count[1] <= high):
                raise ValueError(f"{self.id}: slideCount must lie within the roles' {low}-{high}")
            if not (CAROUSEL_SLIDES[0] <= self.slide_count[0] <= self.slide_count[1]
                    <= CAROUSEL_SLIDES[1]):
                raise ValueError(f"{self.id}: a carousel has {CAROUSEL_SLIDES[0]}-"
                                 f"{CAROUSEL_SLIDES[1]} slides (PRD R4)")
        elif self.slide_roles:
            raise ValueError(f"{self.id}: only carousels have slide roles")
        if self.canvas != CANVAS[self.format]:
            raise ValueError(f"{self.id}: {CATEGORY[self.format]} is {CANVAS[self.format]}, "
                             f"not {self.canvas} (PRD R4)")
        if (self.visual.subject in ROMAN_SUBJECTS) != ("-R" in self.id):
            raise ValueError(f"{self.id}: founder (Roman) variants and only they have an id "
                             "with R (e.g. LI-R1)")
        if self.format in ("fb_single", "fb_ad") and self.platforms != ["facebook"]:
            raise ValueError(f"{self.id}: {self.format} is for facebook only")
        if self.format == "li_single" and self.platforms != ["linkedin"]:
            raise ValueError(f"{self.id}: li_single is for linkedin only")
        if self.format == "carousel" and "instagram" not in self.platforms:
            raise ValueError(f"{self.id}: carousels are for instagram")
        expected = {"none": "template", "illustration": "openrouter",
                    "roman_lora": "comfyui",
                    "roman_higgsfield": "higgsfield_soul"}[self.visual.subject]
        if self.provider != expected:
            raise ValueError(f"{self.id}: a {self.visual.subject} visual uses the "
                             f"{expected} provider")
        if self.pick == "single" and len(self.layouts) != 1 and self.format != "carousel":
            raise ValueError(f"{self.id}: several layouts need pick platform or rotate")
        if self.pick == "side" and set(self.layouts) != set(SIDE_LAYOUTS.values()):
            raise ValueError(f"{self.id}: pick side needs the layouts "
                             f"{', '.join(SIDE_LAYOUTS.values())}")
        if self.visual.subject == "roman_higgsfield" and self.pick != "side":
            raise ValueError(f"{self.id}: a Higgsfield founder variant mirrors with Roman's side "
                             "(pick side)")
        return self

    @property
    def label(self) -> str:
        return f"{self.id} {self.name}"

    @property
    def roman(self) -> bool:
        return self.visual.subject in ROMAN_SUBJECTS

    @property
    def category(self) -> str:
        return CATEGORY[self.format]

    def last_layout(self) -> str | None:
        """A carousel's closing slide layout (the only one with the logo and the website)."""
        return self.slide_roles[-1].layout if self.slide_roles else None

    def layout_for(self, platform: str | None = None, seed: str = "",
                   role: str | None = None, side: str | None = None) -> tuple[str, Layout]:
        """The layout to draw: a slide role's, Roman's side, the platform's variant, or one by
        rotation."""
        if self.pick == "side":
            name = SIDE_LAYOUTS.get(side or "S-R", SIDE_LAYOUTS["S-R"])
            return name, self.layouts[name]
        if role is not None:
            found = next((item for item in self.slide_roles if item.role == role), None)
            if found is None:
                raise DirectionError(f"{self.id}: no slide role {role!r} "
                                     f"({', '.join(r.role for r in self.slide_roles)})")
            return found.layout, self.layouts[found.layout]
        names = list(self.layouts)
        if self.pick == "platform" and platform:
            for name, layout in self.layouts.items():
                if platform in layout.platforms:
                    return name, layout
        if self.pick == "rotate" and len(names) > 1:
            from hashlib import sha256

            index = int(sha256(f"{self.id}|{seed}".encode()).hexdigest(), 16) % len(names)
            return names[index], self.layouts[names[index]]
        return names[0], self.layouts[names[0]]


class RomanRules(_Model):
    """The LoRA prompt pools and rules (known LoRA issues: docs/lora-training-results.md).
    Since 2026-10-20 the LoRA route is disabled; these rules stay for its code and for the
    identity sheet's approved photos."""

    note: str = Field(default="", alias="_note")
    prefix: str = Field(min_length=1)
    outfits: list[str] = Field(min_length=1)
    angles: list[str] = Field(min_length=1)
    expressions: list[str] = Field(min_length=1)
    settings: dict[Literal["business", "quiet_luxury"], list[str]]
    alone: str = Field(min_length=1)
    no_text_surfaces: str = Field(min_length=1)
    blocked_props: list[str] = Field(default_factory=list)
    lora_strength: tuple[float, float] = (0.8, 1.0)
    approved_photos: list[str] = Field(min_length=1)  # real photos in the identity set (FD-1)
    portrait_photos: list[str] = Field(default_factory=list)  # real, suitable for FD-2
    photo_notes: str = ""


class DirectionCatalog(_Model):
    note: str = Field(default="", alias="_note")
    canvas_presets: dict[str, tuple[int, int]]
    margin_px: int = Field(gt=0)  # at 1080 px width
    max_headline_words: int = Field(gt=0)
    max_list_items: int = Field(gt=0)
    content_types: dict[str, str]
    consistent: list[str] = Field(default_factory=list)
    icons: list[str] = Field(min_length=1)  # Tabler names the writer may use
    no_text: str = Field(min_length=1)
    blocked_visual_words: list[str] = Field(default_factory=list)
    roman: RomanRules
    directions: list[Direction] = Field(min_length=1)
    # v6 (R3.5): decoration sets a variation adds (content/design_variation.py), boxes for the
    # text-left layout; mirrored with it
    decorations: dict[str, list[Zone]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [item.id for item in self.directions]
        if len(ids) != len(set(ids)):
            raise ValueError("direction ids must be unique")
        for direction in self.directions:
            if direction.canvas not in self.canvas_presets:
                raise ValueError(f"{direction.id}: canvas {direction.canvas} is not in "
                                 "canvasPresets")
            unknown = sorted(set(direction.content_types) - set(self.content_types))
            if unknown:
                raise ValueError(f"{direction.id}: unknown content types {unknown}")
            for name, layout in direction.layouts.items():
                self._check_layout(direction, name, layout)
        return self

    def _check_layout(self, direction: Direction, name: str, layout: Layout) -> None:
        where = f"{direction.id} {name}"
        width, height = self.canvas_presets[direction.canvas]
        mx, my = self.margin_px / width, self.margin_px / height
        zones = layout.zones
        shown = {zone.field for zone in zones.values() if zone.field}
        shown |= {zone.icons_field for zone in zones.values() if zone.icons_field}
        if shown - set(layout.fields):
            raise ValueError(f"{where}: zones show fields it does not list: "
                             f"{sorted(shown - set(layout.fields))}")
        if set(layout.fields) - shown - {"illustration"}:
            raise ValueError(f"{where}: fields no zone shows: "
                             f"{sorted(set(layout.fields) - shown - {'illustration'})}")
        kinds = [zone.kind for zone in zones.values()]
        closing = direction.format != "carousel" or name == direction.last_layout()
        if direction.roman and ("logo" in kinds or "footer" in kinds):
            raise ValueError(f"{where}: a Roman creative carries no logo and no website (PRD "
                             "v6 R4.6)")
        if closing and "logo" not in kinds and not direction.roman:
            raise ValueError(f"{where}: this layout places the official logo")
        if not closing and ("logo" in kinds or "footer" in kinds):
            raise ValueError(f"{where}: a carousel shows the logo and the website only on its "
                             "last slide (PRD R4)")
        if direction.format == "carousel" and any(
                role.layout == name for role in direction.slide_roles[:-1]) and closing:
            raise ValueError(f"{where}: the last slide's layout is used by another slide too")
        if direction.format == "li_single" and not direction.roman:
            logo = next(zone for zone in zones.values() if zone.kind == "logo")
            left, top, right, bottom = logo.box
            if not ((left <= CORNER or right >= 1 - CORNER)
                    and (top <= CORNER or bottom >= 1 - CORNER)):
                raise ValueError(f"{where}: LinkedIn's logo sits at a side corner (PRD R3/R4)")
        if any(zone.field and "counter" in zone.field.lower() for zone in zones.values()):
            raise ValueError(f"{where}: no slide numbers or counters (PRD R4)")
        for zone_name, zone in zones.items():
            left, top, right, bottom = zone.box
            inside = left >= mx - 1e-3 and right <= 1 - mx + 1e-3 and top >= my - 1e-3 and (
                bottom <= 1 - my + 1e-3)
            if not zone.bleed and not inside:
                raise ValueError(f"{where}: {zone_name} reaches into the {self.margin_px} px "
                                 "margin")
            if zone.bears_text and zone_name not in layout.text_limits:
                raise ValueError(f"{where}: {zone_name} has no textLimits")
            for icon in zone.names:
                if icon not in self.icons:
                    raise ValueError(f"{where}: {zone_name} icon {icon!r} is not in icons")
            if zone.icon and zone.icon not in self.icons:
                raise ValueError(f"{where}: {zone_name} icon {zone.icon!r} is not in icons")
            if zone.visual_shape == "circle" and abs(
                    (right - left) * width - (bottom - top) * height) > 2:
                raise ValueError(f"{where}: a round visual must be square in pixels")
        unknown = sorted(set(layout.text_limits) - set(zones))
        if unknown:
            raise ValueError(f"{where}: textLimits for unknown zones {unknown}")
        texts = [(n, z) for n, z in zones.items() if z.reserved]
        for number, (first_name, first) in enumerate(texts):
            for second_name, second in texts[number + 1:]:
                if boxes_overlap(first.box, second.box):
                    raise ValueError(f"{where}: {first_name} and {second_name} overlap")
        backings = [z.box for z in zones.values() if z.kind == "shape" and z.shape in (
            "panel", "glass", "bar", "scrim", "pill") or z.kind == "footer" and z.fill]
        for zone_name, zone in texts:
            if not zone.bears_text:
                continue
            for visual in (z for z in zones.values() if z.kind == "visual"):
                if boxes_overlap(zone.box, visual.box) and not any(
                        covers(backing, zone.box) for backing in backings) and not (
                        zone.card and zone.card_alpha >= 0.9) and not (
                        zone.pill and zone.pill.fill):
                    raise ValueError(f"{where}: {zone_name} sits on the picture without a "
                                     "panel or scrim behind it")

    def check_layout(self, direction: Direction, name: str, layout: Layout) -> None:
        """The layout rules for a derived layout (a v6 variation): DirectionError if broken."""
        try:
            self._check_layout(direction, name, layout)
        except ValueError as error:
            raise DirectionError(str(error)) from None

    def get(self, direction_id: str) -> Direction:
        wanted = direction_id.strip().upper()
        for item in self.directions:
            if item.id == wanted:
                return item
        raise DirectionError(f'unknown design direction "{direction_id}" (config/'
                             f"design_directions.json: {', '.join(i.id for i in self.directions)})")

    def find(self, direction_id: str) -> Direction | None:
        return next((item for item in self.directions if item.id == direction_id.upper()), None)

    def for_format(self, format_name: str, platform: str | None = None) -> list[Direction]:
        return [item for item in self.directions if item.format == format_name and (
            platform is None or platform in item.platforms)]

    def size(self, direction: Direction) -> tuple[int, int]:
        return self.canvas_presets[direction.canvas]


def _resolve(path: Path) -> Path:
    if not path.is_absolute() and not path.exists() and (_PROJECT_ROOT / path).exists():
        return _PROJECT_ROOT / path
    return path


@lru_cache(maxsize=8)
def _load(path: Path, stamp: float) -> DirectionCatalog:
    try:
        return DirectionCatalog.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except ValidationError as error:
        problems = sorted({
            ".".join(str(part) for part in issue["loc"]) + f": {issue['msg']}"
            for issue in error.errors(include_url=False)
        })
        raise DirectionError(f"{path.name} is invalid: {'; '.join(problems[:6])}") from None
    except ValueError as error:
        raise DirectionError(f"{path.name} is not valid JSON: {error}") from None


def load_directions(path: Path = CONFIG_FILE) -> DirectionCatalog:
    """Read and check design_directions.json; a relative path is also tried in the project."""
    found = _resolve(path)
    if not found.is_file():
        raise DirectionError(f"{path} not found: restore config/design_directions.json")
    return _load(found, found.stat().st_mtime)
