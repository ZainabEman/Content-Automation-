"""Design system for designed graphics (social_creative): config/design_system.json.

The file has a fixed core (colour roles, font use, logo rule, identity rules, text-accuracy
rules), variable pools (scenes, wardrobe, props, decor, holograms, poses) and the post
formats. It names colours only by role (background, accent, highlight, text); the prompt
builder maps each role to a brand.json colour. Fonts and the logo come from brand.json too.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.ai.image import AspectRatio
from content_automation.core.files import CamelModel
from content_automation.workflows.registry import INPUT_FLAGS, WorkflowError

Kind = Literal["organic", "ad", "story", "carousel_slide"]
FormatId = Literal["ad", "statement", "stat", "news", "carousel", "person_photo", "checklist"]
LayoutId = Literal["A", "B", "C", "D"]
CtaIconId = Literal["arrow", "calendar", "play"]
SlideRole = Literal["hook", "tip", "cta"]
ColorRole = Literal["background", "accent", "highlight", "text"]
ElementId = Literal["textPanel", "holograms", "decor", "props"]
TextField = Literal[
    "headline", "subheadline", "cta", "icons", "visual", "stat", "steps", "audience_line", "chat",
    "diagram", "points", "mini_checklist", "before_after",
]
PersonRule = Literal["never", "layout", "always"]
KINDS: tuple[Kind, ...] = ("organic", "ad", "story", "carousel_slide")
FORMATS: tuple[FormatId, ...] = (
    "ad", "statement", "stat", "news", "carousel", "person_photo", "checklist",
)
LAYOUTS: tuple[LayoutId, ...] = ("A", "B", "C", "D")
CTA_ICONS: tuple[CtaIconId, ...] = ("arrow", "calendar", "play")
SLIDE_ROLES: tuple[SlideRole, ...] = ("hook", "tip", "cta")
COLOR_ROLES: tuple[ColorRole, ...] = ("background", "accent", "highlight", "text")
TEXT_FIELDS: tuple[TextField, ...] = (
    "headline", "subheadline", "cta", "icons", "visual", "stat", "steps", "audience_line", "chat",
    "diagram", "points", "mini_checklist", "before_after",
)
# A middle carousel slide shows exactly one of these visuals.
SLIDE_VISUALS: tuple[TextField, ...] = ("chat", "diagram", "mini_checklist", "before_after")
DEFAULT_FORMAT: FormatId = "ad"  # designs without a format keep the headline + CTA design
MAX_HIGHLIGHT_WORDS = 2
ICON_LABELS_MIN, ICON_LABELS_MAX = 3, 4
MAX_ICON_LABEL_WORDS = 2
STEPS_MIN, STEPS_MAX = 3, 5
MAX_STEP_WORDS = 8
MAX_STAT_CHARS = 12
MAX_AUDIENCE_WORDS = 6
MAX_SOURCE_WORDS = 4
CHAT_MIN, CHAT_MAX, MAX_BUBBLE_WORDS = 2, 3, 14
DIAGRAM_MIN, DIAGRAM_MAX, MAX_DIAGRAM_WORDS = 3, 4, 4
POINTS, MAX_POINT_WORDS = 3, 8  # a post's key points
CHECKLIST_ROWS, MAX_CHECKLIST_WORDS = 3, 6  # a middle slide's mini checklist
MAX_BEFORE_AFTER_WORDS = 12
MIDDLE_HEADLINE_WORDS, MIDDLE_LINE_WORDS = 6, 18  # a middle slide's heading and supporting line
SPEAKERS = ("customer", "bot")
STEP_SEPARATOR = "|"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SLIDE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")


class DesignSystemError(WorkflowError):
    """design_system.json is missing or invalid."""


class _DesignModel(CamelModel):
    model_config = ConfigDict(extra="forbid")


class ColorRoleSpec(_DesignModel):
    usage: list[str] = Field(min_length=1)  # words looked for in a brand colour's "usage"
    use: str = Field(min_length=1)  # what the design uses that colour for


class IdentityRules(_DesignModel):
    rules: list[str] = Field(min_length=1)  # "{images}" names the identity reference images
    split: str = Field(min_length=1)  # added when one image shows the man twice


class TextRules(_DesignModel):
    only: str = Field(min_length=1)  # "{language}" is the brand.json language
    nothing_else: str = Field(min_length=1)
    none: str = Field(min_length=1)
    no_button: str = Field(min_length=1)
    lettering: str = Field(min_length=1)  # "{lettering}" lists what else may carry letters
    no_lettering: str = Field(min_length=1)  # when nothing else may carry letters


class BrandRules(_DesignModel):
    """The brand guide's rules, enforced on every format."""

    colours: str = Field(min_length=1)
    typography: str = Field(min_length=1)  # "{heading}" and "{body}" are the brand fonts
    spacing: str = Field(min_length=1)


class Core(_DesignModel):
    """Always on, whatever the format."""

    color_roles: dict[ColorRole, ColorRoleSpec]
    fonts: str = Field(min_length=1)
    heading_font: str = Field(min_length=1)  # "{font}" is the brand heading font
    body_font: str = Field(min_length=1)  # "{font}" is the brand body (sub-heading) font
    brand_rules: BrandRules
    layout: str = Field(min_length=1)  # fill the canvas, phone-readable text
    footer: str = Field(min_length=1)  # where the handle or website goes
    audience_line: str = Field(min_length=1)  # how the "FOR ..." line looks
    logo: str = Field(min_length=1)  # the corner kept clear: the app pastes the real logo there
    scene_text: str = Field(min_length=1)  # no readable text on screens, devices or signs
    source_line: str = Field(min_length=1)  # how a stat's "Source: ..." line looks
    identity: IdentityRules
    no_person: str = Field(min_length=1)  # said by every design that does not show him
    text: TextRules


class Typography(_DesignModel):
    headline: str = Field(min_length=1)
    headline_highlight: str = Field(min_length=1)  # added only when highlight words are given
    subheadline: str = Field(min_length=1)
    subheadline_highlight: str = Field(min_length=1)  # added only with a sub-highlight word
    stat: str = Field(min_length=1)
    steps: str = Field(min_length=1)
    points: str = Field(min_length=1)


class CtaIcon(_DesignModel):
    icon: str = Field(min_length=1)
    actions: list[str] = Field(default_factory=list)  # CTA words that pick this icon


class CtaButton(_DesignModel):
    description: str = Field(min_length=1)
    pointer: str = ""
    icons: dict[CtaIconId, CtaIcon]


class Elements(_DesignModel):
    text_panel: str = Field(min_length=1)
    cta_button: CtaButton
    icon_row: str = Field(min_length=1)
    holograms_person: str = ""


class PoolEntry(_DesignModel):
    description: str = Field(min_length=1)
    auto: bool = True  # may be picked when nothing is given
    photo: bool = True  # scenes: a real place, where the man and props can be shown
    general: bool = True  # scenes: false = picked only when the topic matches its tags
    scenes: list[str] = Field(default_factory=list)  # props and poses: scenes they fit; [] = all
    tags: list[str] = Field(default_factory=list)  # scenes: topics and audiences it suits


class Pools(_DesignModel):
    """What varies from post to post."""

    scenes: dict[str, PoolEntry] = Field(min_length=8)
    wardrobe: dict[str, PoolEntry] = Field(min_length=4)
    props: dict[str, PoolEntry] = Field(min_length=1)
    decor: dict[str, PoolEntry] = Field(min_length=1)
    holograms: dict[str, PoolEntry] = Field(min_length=1)
    poses: dict[str, PoolEntry] = Field(min_length=1)


class LayoutSpec(_DesignModel):
    use: str = Field(min_length=1)
    description: str = Field(min_length=1)
    person: bool
    split_poses: list[str] = Field(default_factory=list)  # before/after: left pose, right pose


class FormatSpec(_DesignModel):
    use: str = Field(min_length=1)  # when to choose it
    composition: str = Field(min_length=1)
    required: list[TextField] = Field(default_factory=list)
    optional: list[TextField] = Field(default_factory=list)  # other texts are refused
    layouts: list[LayoutId] = Field(default_factory=list)  # [] = no layout letter
    default_layout: LayoutId | None = None
    person: PersonRule  # "layout": only with a layout that shows him
    elements: list[ElementId] = Field(default_factory=list)  # optional parts this format shows
    headline_max_words: int = Field(default=6, ge=1)
    headline_caps: bool = True
    labels: dict[TextField, str] = Field(default_factory=dict)  # names in the text block
    fixed_texts: dict[str, str] = Field(default_factory=dict)  # what it is -> exact text
    typography: dict[TextField, str] = Field(default_factory=dict)  # replaces the default
    style_sets: list[str] = Field(default_factory=list)  # creative sets (or folders) that fit
    style_by_role: bool = False  # carousels: hook, tip or cta examples by slide position
    style_refs: int = Field(default=3, ge=0, le=3)  # 0 = no style images
    family: Literal["post"] | None = None  # "post": a content type of the premium post family
    numbered_points: bool = False  # the key points are numbered steps


class KindSpec(_DesignModel):
    description: str = Field(min_length=1)
    aspects: list[AspectRatio] = Field(min_length=1)  # the first one is the default
    safe_zone: str = ""


class CarouselSpec(_DesignModel):
    slides: dict[SlideRole, str]
    chat: str = Field(min_length=1)  # how a middle slide shows a chat example
    diagram: str = Field(min_length=1)  # how a middle slide shows a workflow diagram
    checklist: str = Field(min_length=1)  # a 3-row mini checklist
    before_after: str = Field(min_length=1)  # a before/after comparison
    navigation: str = Field(min_length=1)  # the swipe cue; no slide numbers
    series: str = Field(min_length=1)  # every slide shares one design
    story: dict[str, str] = Field(default_factory=dict)  # story role -> what that slide says
    demos: dict[str, str] = Field(default_factory=dict)  # where the examples are, their structure


class PostFamily(_DesignModel):
    """The premium layout every Facebook post uses; the formats are its content types."""

    use: str = Field(min_length=1)
    composition: str = Field(min_length=1)
    composition_no_person: str = Field(min_length=1)  # a LinkedIn post without the man
    points: str = Field(min_length=1)  # the content block: 3 key points with icons
    stat: str = Field(min_length=1)  # the content block: the big number and its source


class CtaRule(_DesignModel):
    """What a carousel's last-slide CTA must (and must not) ask for on one platform."""

    use: str = Field(min_length=1)
    require: list[str] = Field(min_length=1)  # one of these words or phrases
    avoid: list[str] = Field(default_factory=list)


class DesignRules(_DesignModel):
    organic: list[str] = Field(min_length=1)
    ad: list[str] = Field(min_length=1)


# The texts the app renders itself (workflows/text_overlay.py) for providers that draw no text.
ZoneField = Literal[
    "audience_line", "headline", "subheadline", "stat", "source_line", "points", "cta", "icons",
    "footer",
    # post formats (config/post_formats.json): question, quote and the two columns
    "question", "quote", "column_left_label", "column_left", "column_right_label", "column_right",
]
Box = tuple[float, float, float, float]  # left, top, right, bottom as shares (0-1)
ScrimMode = Literal["auto", "always", "never"]


def _box_problem(box: Box) -> str | None:
    left, top, right, bottom = box
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        return f"{list(box)} (needs 0 <= left < right <= 1 and 0 <= top < bottom <= 1)"
    return None


class OverlayFonts(_DesignModel):
    """Font files in `folder`, by family in priority order: the first family with a file for
    a weight wins, so brand files (Futura) dropped in later replace the fallback (Jost)."""

    folder: str = Field(min_length=1)
    families: list[str] = Field(min_length=1)
    weights: dict[str, list[str]] = Field(min_length=1)  # weight -> style names, best first


class Scrim(_DesignModel):
    """The soft panel drawn behind a zone whose background is too busy or too light."""

    color: ColorRole = "background"
    opacity: float = Field(default=0.72, gt=0, le=1)
    padding: int = Field(default=24, ge=0)  # px at baseWidth
    radius: int = Field(default=22, ge=0)


class ButtonStyle(_DesignModel):
    fill: ColorRole = "background"
    outline: ColorRole = "accent"
    outline_width: int = Field(default=3, ge=0)
    pad_x: int = Field(default=28, ge=0)
    pad_y: int = Field(default=16, ge=0)
    radius: int = Field(default=18, ge=0)


class TextZone(_DesignModel):
    """One text: its box (shares of the panel; the footer: of the canvas) and how it fits."""

    field: ZoneField
    box: Box
    align: Literal["left", "center", "right"] = "left"
    valign: Literal["top", "middle", "bottom"] = "top"
    max_lines: int = Field(default=1, ge=1)
    size: tuple[int, int]  # smallest and largest font size, px at baseWidth
    weight: str = Field(min_length=1)  # a key of fonts.weights
    color: ColorRole = "text"
    highlight: ColorRole = "highlight"  # highlight words
    marker: ColorRole = "accent"  # list bullets and numbers
    line_height: float = Field(default=1.2, gt=0.8, le=2)
    scrim: ScrimMode = "auto"
    min_contrast: float | None = Field(default=None, ge=1, le=21)  # default: minContrast


class OverlayPanel(_DesignModel):
    box: Box  # shares of the canvas
    label: str = Field(min_length=1)  # how the prompt names this area


class OverlayFormat(_DesignModel):
    zones: list[TextZone] = Field(min_length=1)
    panel: str | None = None  # a fixed panel; None: the layout's panel (layoutPanels)


class OverlayPrompt(_DesignModel):
    """What the prompt says instead of the text, typography and text-panel lines."""

    no_text: str = Field(min_length=1)
    space: str = Field(min_length=1)  # "{areas}" names the areas kept clear
    canvas: str = Field(min_length=1)
    post: str = Field(min_length=1)  # the post family composition, without its text
    post_no_person: str = Field(min_length=1)
    compositions: dict[FormatId, str] = Field(default_factory=dict)  # replaces the format's
    layouts: dict[LayoutId, str] = Field(default_factory=dict)  # replaces the layout's


class TextOverlaySpec(_DesignModel):
    fonts: OverlayFonts
    base_width: int = Field(default=1080, ge=100)  # the canvas width that sizes refer to
    min_contrast: float = Field(default=4.5, ge=1, le=21)
    # Share of black mixed into the background colour: core.colorRoles.background is used
    # "as a deep, dark shade of it" (scrims and button fills).
    background_shade: float = Field(default=0.45, ge=0, lt=1)
    scrim: Scrim = Field(default_factory=Scrim)
    button: ButtonStyle = Field(default_factory=ButtonStyle)
    panels: dict[str, OverlayPanel] = Field(min_length=1)
    layout_panels: dict[str, str]  # layout letter, or "none" (no layout) -> panel
    footer: TextZone
    prompt: OverlayPrompt
    formats: dict[FormatId, OverlayFormat] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Self:
        problems = []
        for name, panel in self.panels.items():
            if (box := _box_problem(panel.box)) is not None:
                problems.append(f"panels.{name}.box {box}")
        for key, panel_name in self.layout_panels.items():
            if panel_name not in self.panels:
                problems.append(f"layoutPanels.{key}: no panel {panel_name}")
        zones = [("footer", self.footer)] + [
            (f"formats.{format_id}.zones.{zone.field}", zone)
            for format_id, spec in self.formats.items()
            for zone in spec.zones
        ]
        for where, zone in zones:
            if (box := _box_problem(zone.box)) is not None:
                problems.append(f"{where}.box {box}")
            if not 0 < zone.size[0] <= zone.size[1]:
                problems.append(f"{where}.size (needs 0 < smallest <= largest)")
            if zone.weight not in self.fonts.weights:
                problems.append(f"{where}.weight: {zone.weight} is not in fonts.weights")
        for format_id, spec in self.formats.items():
            if spec.panel is not None and spec.panel not in self.panels:
                problems.append(f"formats.{format_id}.panel: no panel {spec.panel}")
        if "{areas}" not in self.prompt.space:
            problems.append("{areas} in prompt.space")
        if problems:
            raise ValueError("textOverlay: " + "; ".join(problems))
        return self


class DesignSystem(_DesignModel):
    core: Core
    typography: Typography
    elements: Elements
    pools: Pools
    layouts: dict[LayoutId, LayoutSpec]
    formats: dict[FormatId, FormatSpec]
    kinds: dict[Kind, KindSpec]
    carousel: CarouselSpec
    post_family: PostFamily
    cta_rules: dict[str, CtaRule] = Field(default_factory=dict)  # platform -> rule
    headline_formulas: dict[str, str] = Field(default_factory=dict)  # name -> example
    rules: DesignRules
    text_overlay: TextOverlaySpec | None = None  # for image providers that draw no text
    # Live fix: the branded person-post card (workflows/card.py; insight, stat).
    person_templates: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_complete(self) -> Self:
        roles = self.core.color_roles
        missing = (
            [f"layouts.{key}" for key in LAYOUTS if key not in self.layouts]
            + [f"formats.{key}" for key in FORMATS if key not in self.formats]
            + [f"kinds.{key}" for key in KINDS if key not in self.kinds]
            + [f"core.colorRoles.{key}" for key in COLOR_ROLES if key not in roles]
            + [f"carousel.slides.{key}" for key in SLIDE_ROLES if key not in self.carousel.slides]
        )
        icons = self.elements.cta_button.icons
        missing += [f"elements.ctaButton.icons.{key}" for key in CTA_ICONS if key not in icons]
        for layout_id, layout in self.layouts.items():
            if len(layout.split_poses) not in (0, 2):
                missing.append(f"layouts.{layout_id}.splitPoses (a left and a right pose)")
            for pose in layout.split_poses:
                if pose not in self.pools.poses:
                    missing.append(f"pools.poses.{pose} (used by layout {layout_id})")
        for name, pool in (("props", self.pools.props), ("poses", self.pools.poses)):
            for key, entry in pool.items():
                for scene in entry.scenes:
                    if scene not in self.pools.scenes:
                        missing.append(f"pools.scenes.{scene} (used by pools.{name}.{key})")
        for text, placeholder, where in (
            (" ".join(self.core.identity.rules), "{images}", "core.identity.rules"),
            (self.core.text.only, "{language}", "core.text.only"),
            (self.core.text.lettering, "{lettering}", "core.text.lettering"),
            (self.core.heading_font, "{font}", "core.headingFont"),
            (self.core.body_font, "{font}", "core.bodyFont"),
            (self.core.brand_rules.typography, "{heading}", "core.brandRules.typography"),
            (self.core.brand_rules.typography, "{body}", "core.brandRules.typography"),
        ):
            if placeholder not in text:
                missing.append(f"{placeholder} in {where}")
        if missing:
            raise ValueError("missing " + ", ".join(missing))
        return self

    def cta_icon_for(self, label: str) -> CtaIconId:
        """The button icon for the first action word in the CTA label (default: arrow)."""
        for word in re.findall(r"[a-z]+", label.lower()):
            for icon_id, icon in self.elements.cta_button.icons.items():
                if word in icon.actions:
                    return icon_id
        return "arrow"


def load_design_system(path: Path) -> DesignSystem:
    """Read and check design_system.json; a relative path is also tried in the project folder."""
    candidates = [path] if path.is_absolute() else [path, _PROJECT_ROOT / path]
    file = next((candidate for candidate in candidates if candidate.is_file()), None)
    if file is None:
        raise DesignSystemError(
            f"Design system not found at {path}. Restore config/design_system.json or set "
            "DESIGN_SYSTEM_FILE in .env."
        )
    try:
        return DesignSystem.model_validate_json(file.read_text(encoding="utf-8"))
    except ValidationError as error:
        problems = sorted({
            ".".join(str(part) for part in issue["loc"]) or str(issue["msg"])
            for issue in error.errors(include_url=False)
        })
        raise DesignSystemError(f"{file.name} is invalid; check: {'; '.join(problems)}.") from None


class DesignFields(Protocol):
    """The design options as given on the command line or in a brief (see WorkflowInputs)."""

    identity_set: str | None
    format: str | None
    layout: str | None
    pose: str | None
    headline: str | None
    highlight: str | None
    subheadline: str | None
    sub_highlight: str | None
    cta: str | None
    cta_icon: str | None
    icons: str | None
    visual: str | None
    stat: str | None
    source: str | None
    source_name: str | None
    steps: str | None
    audience_line: str | None
    chat: str | None
    diagram: str | None
    points: str | None
    mini_checklist: str | None
    before_after: str | None
    slide: str | None
    slide_role: str | None
    no_person: bool  # post formats only: leave the man out (a LinkedIn post)


@dataclass(frozen=True)
class DesignChoice:
    """What one designed graphic shows, checked against the design system."""

    kind: Kind
    format: FormatId = DEFAULT_FORMAT
    layout: LayoutId | None = None  # None: formats and slides without a layout letter
    person: bool = False  # the man is shown, so identity photos are required
    pose: str | None = None  # key in the poses pool, when one was given
    headline: str | None = None
    highlight: tuple[str, ...] = ()
    subheadline: str | None = None
    sub_highlight: str | None = None
    cta: str | None = None
    cta_icon: CtaIconId | None = None
    icons: tuple[str, ...] = ()
    visual: str | None = None
    stat: str | None = None
    source: str | None = None  # research article ID behind a stat or a news line
    source_name: str | None = None  # stat: the publisher shown as "Source: <name>"
    steps: tuple[str, ...] = ()
    audience_line: str | None = None  # "FOR DENTAL PRACTICES"
    chat: tuple[tuple[str, str], ...] = ()  # (speaker, text): a tip slide's chat example
    diagram: tuple[str, ...] = ()  # a tip slide's workflow steps
    points: tuple[str, ...] = ()  # a post's 3 key points
    mini_checklist: tuple[str, ...] = ()  # a middle slide's 3 checklist rows
    before_after: tuple[str, ...] = ()  # a middle slide's (before, after)
    slide: tuple[int, int] | None = None  # (number, total); never shown on the image
    slide_role: SlideRole | None = None

    @property
    def label(self) -> str:
        """How error messages name this design."""
        if self.slide_role is not None:
            return f"A carousel {self.slide_role} slide"
        if self.layout is not None:
            return f"Layout {self.layout}"
        return f"Format {self.format}"


def _choice[T: str](value: str, options: tuple[T, ...], flag: str) -> T:
    for option in options:
        if option == value.strip():
            return option
    raise WorkflowError(f"{flag} must be one of: {', '.join(options)}.")


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def split_list(value: str | None, separator: str = ",") -> tuple[str, ...]:
    """Separated words or labels, as given to --highlight, --icons and --steps."""
    return tuple(part.strip() for part in (value or "").split(separator) if part.strip())


def _parse_slide(value: str | None) -> tuple[int, int] | None:
    if not _clean(value):
        return None
    match = _SLIDE.fullmatch((value or "").strip())
    number, total = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
    if total < 2 or not 1 <= number <= total:
        raise WorkflowError("--slide must look like N/TOTAL, e.g. 2/5.")
    return number, total


def parse_chat(value: str | None) -> tuple[tuple[str, str], ...]:
    """Chat bubbles: "Customer: Can I book Friday?|Bot: Yes, at 10?" -> (speaker, text) pairs."""
    bubbles = []
    for part in split_list(value, STEP_SEPARATOR):
        speaker, colon, text = part.partition(":")
        if not colon or speaker.strip().lower() not in SPEAKERS or not text.strip():
            raise WorkflowError(
                '--chat takes 2-3 bubbles like "Customer: Can I book for Friday?|Bot: Yes, at 10 '
                'or 14 h. Which suits you?" (speakers: customer, bot).'
            )
        bubbles.append((speaker.strip().lower(), text.strip()))
    return tuple(bubbles)


def _contains(text: str, part: str) -> bool:
    return part.casefold() in text.casefold()


def _flags(fields: list[TextField]) -> str:
    return ", ".join(INPUT_FLAGS[name] for name in fields)


def _layout(
    fields: DesignFields,
    system: DesignSystem,
    format_id: FormatId,
    slide: tuple[int, int] | None,
) -> tuple[LayoutId | None, SlideRole | None]:
    """The layout letter (None: picked later for variety, or none for a middle slide) and the
    carousel slide role."""
    spec = system.formats[format_id]
    given = _choice(fields.layout, LAYOUTS, "--layout") if fields.layout else None
    if format_id == "carousel":
        role: SlideRole
        if fields.slide_role:
            role = _choice(fields.slide_role, SLIDE_ROLES, "--slide-role")
        elif slide is None or slide[0] == 1:
            role = "hook"
        else:
            role = "cta" if slide[0] == slide[1] else "tip"
        if role == "tip":
            if given is not None:
                raise WorkflowError(
                    "A middle carousel slide shows no person and has no layout letter; remove "
                    "--layout."
                )
            return None, role
        layout = given or spec.default_layout
        if layout is None or layout not in spec.layouts:
            options = " or ".join(spec.layouts)
            raise WorkflowError(
                f"The first and last carousel slides show the person: use --layout {options}."
            )
        return layout, role
    if slide is not None or fields.slide_role:
        raise WorkflowError("--slide and --slide-role are for --format carousel.")
    if given is not None:
        if given not in spec.layouts:
            options = " or ".join(spec.layouts)
            raise WorkflowError(
                f"--format {format_id} uses --layout {options}."
                if spec.layouts
                else f"--format {format_id} has no layout letter; remove --layout."
            )
        return given, None
    return spec.default_layout, None


def resolve_design(
    fields: DesignFields, system: DesignSystem, *, kind: str | None = None
) -> DesignChoice:
    """Check the design options against the format's rules and fill the defaults.

    WorkflowError names the flag to fix.
    """
    if fields.format:
        format_id = _choice(fields.format, FORMATS, "--format")
    else:
        format_id = "carousel" if kind == "carousel_slide" else DEFAULT_FORMAT
    if kind:
        kind_id = _choice(kind, KINDS, "--kind")
    else:
        kind_id = "carousel_slide" if format_id == "carousel" else "organic"
    if (kind_id == "carousel_slide") != (format_id == "carousel"):
        raise WorkflowError("--format carousel and --kind carousel_slide go together.")
    if kind_id == "ad" and format_id != "ad":
        raise WorkflowError(
            "--kind ad (a paid ad) needs --format ad: headline, subheadline and CTA button."
        )
    spec = system.formats[format_id]
    slide = _parse_slide(fields.slide)
    layout, role = _layout(fields, system, format_id, slide)
    if fields.no_person:
        if spec.family != "post":
            raise WorkflowError(f"--format {format_id} always shows the person.")
        if fields.layout:
            raise WorkflowError("A post without the person has no layout letter; remove --layout.")
        layout = None
    layout_spec = system.layouts[layout] if layout is not None else None
    person = not fields.no_person and (
        spec.person == "always"
        or (spec.person == "layout" and layout_spec is not None and layout_spec.person)
    )
    posed = person and not (layout_spec is not None and layout_spec.split_poses)

    headline = _clean(fields.headline)
    subheadline = _clean(fields.subheadline)
    cta = _clean(fields.cta)
    icons = split_list(fields.icons)
    visual = _clean(fields.visual)
    stat = _clean(fields.stat)
    steps = split_list(fields.steps, STEP_SEPARATOR)
    audience_line = _clean(fields.audience_line)
    chat = parse_chat(fields.chat)
    diagram = split_list(fields.diagram, STEP_SEPARATOR)
    points = split_list(fields.points, STEP_SEPARATOR)
    mini_checklist = split_list(fields.mini_checklist, STEP_SEPARATOR)
    before_after = split_list(fields.before_after, STEP_SEPARATOR)
    given: dict[TextField, bool] = {
        "headline": headline is not None,
        "subheadline": subheadline is not None,
        "cta": cta is not None,
        "icons": bool(icons),
        "visual": visual is not None,
        "stat": stat is not None,
        "steps": bool(steps),
        "audience_line": audience_line is not None,
        "chat": bool(chat),
        "diagram": bool(diagram),
        "points": bool(points),
        "mini_checklist": bool(mini_checklist),
        "before_after": bool(before_after),
    }
    allowed = {*spec.required, *spec.optional}
    unused = [name for name in TEXT_FIELDS if given[name] and name not in allowed]
    if unused:
        raise WorkflowError(f"--format {format_id} does not use {_flags(unused)}.")
    missing = [name for name in spec.required if not given[name]]
    if missing:
        raise WorkflowError(f"--format {format_id} needs {_flags(missing)}.")
    if role is not None and (cta is not None) != (role == "cta"):
        raise WorkflowError(
            "The last carousel slide needs --cta."
            if role == "cta"
            else "Only the last carousel slide has a CTA button; remove --cta."
        )
    if role is not None:
        if role == "hook" and audience_line is None:
            raise WorkflowError(
                "The hook slide names the audience: add --audience-line, e.g. "
                '"FOR DENTAL PRACTICES".'
            )
        if role != "hook" and audience_line is not None:
            raise WorkflowError("Only the hook slide has --audience-line.")
        visuals = [name for name in SLIDE_VISUALS if given[name]]
        if role != "tip" and (visuals or visual):
            raise WorkflowError(
                "--chat, --diagram, --mini-checklist and --before-after belong on the middle "
                "slides; the first and last slides carry no tip content."
            )
        if role == "tip":
            if visual is not None:
                raise WorkflowError(
                    "A middle slide shows information, not an icon: use --chat, --diagram, "
                    "--mini-checklist or --before-after instead of --visual."
                )
            if len(visuals) != 1:
                raise WorkflowError(
                    "A middle slide has exactly one visual that adds information: --chat, "
                    "--diagram, --mini-checklist (3 rows) or --before-after."
                )
            if subheadline is None:
                raise WorkflowError(
                    "A middle slide needs --subheadline: one line with the concrete fact or action."
                )
            if headline is not None and len(headline.split()) > MIDDLE_HEADLINE_WORDS:
                raise WorkflowError(
                    f"A middle slide's heading has at most {MIDDLE_HEADLINE_WORDS} words."
                )
            if len(subheadline.split()) > MIDDLE_LINE_WORDS:
                raise WorkflowError(
                    f"A middle slide's supporting line has at most {MIDDLE_LINE_WORDS} words."
                )
    if sum(bool(item) for item in (visual, chat, diagram, mini_checklist, before_after)) > 1:
        raise WorkflowError(
            "Give one visual: --chat, --diagram, --mini-checklist, --before-after or --visual."
        )
    if points and (
        len(points) != POINTS or any(len(point.split()) > MAX_POINT_WORDS for point in points)
    ):
        raise WorkflowError(
            f"--points takes exactly {POINTS} short key points (at most {MAX_POINT_WORDS} words "
            f'each) separated by "{STEP_SEPARATOR}".'
        )
    if mini_checklist and (
        len(mini_checklist) != CHECKLIST_ROWS
        or any(len(row.split()) > MAX_CHECKLIST_WORDS for row in mini_checklist)
    ):
        raise WorkflowError(
            f"--mini-checklist takes exactly {CHECKLIST_ROWS} rows of at most "
            f'{MAX_CHECKLIST_WORDS} words, separated by "{STEP_SEPARATOR}".'
        )
    if before_after and (
        len(before_after) != 2
        or any(len(part.split()) > MAX_BEFORE_AFTER_WORDS for part in before_after)
    ):
        raise WorkflowError(
            f'--before-after takes "<before>{STEP_SEPARATOR}<after>", each at most '
            f"{MAX_BEFORE_AFTER_WORDS} words."
        )
    if chat and not CHAT_MIN <= len(chat) <= CHAT_MAX:
        raise WorkflowError(f"--chat takes {CHAT_MIN}-{CHAT_MAX} bubbles.")
    if any(len(text.split()) > MAX_BUBBLE_WORDS for _, text in chat):
        raise WorkflowError(f"Each chat bubble has at most {MAX_BUBBLE_WORDS} words.")
    if diagram and (
        not DIAGRAM_MIN <= len(diagram) <= DIAGRAM_MAX
        or any(len(step.split()) > MAX_DIAGRAM_WORDS for step in diagram)
    ):
        raise WorkflowError(
            f"--diagram takes {DIAGRAM_MIN}-{DIAGRAM_MAX} steps of at most {MAX_DIAGRAM_WORDS} "
            'words, separated by "|", e.g. "Visitor asks|Chatbot answers|Lead in CRM".'
        )
    if audience_line is not None and len(audience_line.split()) > MAX_AUDIENCE_WORDS:
        raise WorkflowError(f"--audience-line has at most {MAX_AUDIENCE_WORDS} words.")
    if headline is not None and len(headline.split()) > spec.headline_max_words:
        raise WorkflowError(
            f"--headline has more than {spec.headline_max_words} words "
            f"(the limit of --format {format_id})."
        )

    pose = _clean(fields.pose)
    if pose is not None:
        if not posed:
            raise WorkflowError(
                "--pose is for designs that show the man (not the before/after layout D)."
            )
        if pose not in system.pools.poses:
            raise WorkflowError(f"--pose must be one of: {', '.join(system.pools.poses)}.")
    if visual is not None and role is None and layout not in ("A", None):
        raise WorkflowError(
            "--visual is the system visual of layout A; layouts B, C and D do not use it."
        )

    highlight = split_list(fields.highlight)
    if highlight and (
        headline is None
        or len(highlight) > MAX_HIGHLIGHT_WORDS
        or not all(_contains(headline, word) for word in highlight)
    ):
        raise WorkflowError(
            f"--highlight takes 1-{MAX_HIGHLIGHT_WORDS} words from --headline, "
            "separated by commas."
        )
    sub_highlight = _clean(fields.sub_highlight)
    if sub_highlight is not None and (
        subheadline is None or not _contains(subheadline, sub_highlight)
    ):
        raise WorkflowError("--sub-highlight must be a word from --subheadline.")

    cta_icon: CtaIconId | None = None
    if fields.cta_icon:
        if cta is None:
            raise WorkflowError("--cta-icon needs --cta (the button label).")
        cta_icon = _choice(fields.cta_icon, CTA_ICONS, "--cta-icon")
    elif cta is not None:
        cta_icon = system.cta_icon_for(cta)

    if icons and (
        not ICON_LABELS_MIN <= len(icons) <= ICON_LABELS_MAX
        or any(len(label.split()) > MAX_ICON_LABEL_WORDS for label in icons)
    ):
        raise WorkflowError(
            f"--icons takes {ICON_LABELS_MIN}-{ICON_LABELS_MAX} labels of 1-"
            f'{MAX_ICON_LABEL_WORDS} words each, e.g. "Chatbots,CRM,Email".'
        )
    if steps and (
        not STEPS_MIN <= len(steps) <= STEPS_MAX
        or any(len(step.split()) > MAX_STEP_WORDS for step in steps)
    ):
        raise WorkflowError(
            f"--steps takes {STEPS_MIN}-{STEPS_MAX} short steps (at most {MAX_STEP_WORDS} words "
            f'each) separated by "{STEP_SEPARATOR}".'
        )
    if stat is not None and (len(stat) > MAX_STAT_CHARS or not re.search(r"\d", stat)):
        raise WorkflowError(
            f'--stat is one big number, e.g. "73%" (at most {MAX_STAT_CHARS} characters).'
        )
    source = _clean(fields.source)
    if stat is not None and source is None:
        raise WorkflowError(
            "--stat needs --source: the ID of the research article the number comes from."
        )
    if source is not None and format_id not in ("stat", "news"):
        raise WorkflowError("--source is for --format stat or news.")
    source_name = _clean(fields.source_name)
    if source_name is not None and format_id != "stat":
        raise WorkflowError("--source-name is for --format stat (its small source line).")
    if source_name is not None and len(source_name.split()) > MAX_SOURCE_WORDS:
        raise WorkflowError(
            f'--source-name is the publisher in at most {MAX_SOURCE_WORDS} words, e.g. "Zillow".'
        )

    return DesignChoice(
        kind=kind_id,
        format=format_id,
        layout=layout,
        person=person,
        pose=pose,
        headline=headline,
        highlight=highlight,
        subheadline=subheadline,
        sub_highlight=sub_highlight,
        cta=cta,
        cta_icon=cta_icon,
        icons=icons,
        visual=visual,
        stat=stat,
        source=source,
        source_name=source_name,
        steps=steps,
        audience_line=audience_line,
        chat=chat,
        diagram=diagram,
        points=points,
        mini_checklist=mini_checklist,
        before_after=before_after,
        slide=slide,
        slide_role=role,
    )
