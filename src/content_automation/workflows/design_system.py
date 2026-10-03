"""Design system for designed graphics (social_creative): config/design_system.json.

The file has a fixed core (colour roles, font use, logo rule, identity rules, text-accuracy
rules), variable pools (scenes, wardrobe, props, decor, holograms, poses) and the post
formats. It names colours only by role (background, accent, highlight, text); the prompt
builder maps each role to a brand.json colour. Fonts and the logo come from brand.json too.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Self

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
TextField = Literal["headline", "subheadline", "cta", "icons", "visual", "stat", "steps"]
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
    "headline", "subheadline", "cta", "icons", "visual", "stat", "steps",
)
DEFAULT_FORMAT: FormatId = "ad"  # designs without a format keep the headline + CTA design
MAX_HIGHLIGHT_WORDS = 2
ICON_LABELS_MIN, ICON_LABELS_MAX = 3, 4
MAX_ICON_LABEL_WORDS = 2
STEPS_MIN, STEPS_MAX = 3, 5
MAX_STEP_WORDS = 8
MAX_STAT_CHARS = 12
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


class Core(_DesignModel):
    """Always on, whatever the format."""

    color_roles: dict[ColorRole, ColorRoleSpec]
    fonts: str = Field(min_length=1)
    logo: str = Field(min_length=1)
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
    scenes: list[str] = Field(default_factory=list)  # props and poses: scenes they fit; [] = all


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


class KindSpec(_DesignModel):
    description: str = Field(min_length=1)
    aspects: list[AspectRatio] = Field(min_length=1)  # the first one is the default
    safe_zone: str = ""


class CarouselSpec(_DesignModel):
    slides: dict[SlideRole, str]
    navigation: str = Field(min_length=1)
    demos: dict[str, str] = Field(default_factory=dict)  # where the examples are, their structure


class DesignRules(_DesignModel):
    organic: list[str] = Field(min_length=1)
    ad: list[str] = Field(min_length=1)


class DesignSystem(_DesignModel):
    core: Core
    typography: Typography
    elements: Elements
    pools: Pools
    layouts: dict[LayoutId, LayoutSpec]
    formats: dict[FormatId, FormatSpec]
    kinds: dict[Kind, KindSpec]
    carousel: CarouselSpec
    headline_formulas: dict[str, str] = Field(default_factory=dict)  # name -> example
    rules: DesignRules

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
    steps: str | None
    slide: str | None
    slide_role: str | None


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
    steps: tuple[str, ...] = ()
    slide: tuple[int, int] | None = None  # (number, total)
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
        if role != "hook":
            if given is not None:
                raise WorkflowError(
                    f"A carousel {role} slide has no layout letter; remove --layout."
                )
            return None, role
        layout = given or spec.default_layout
        if layout is None or layout not in spec.layouts:
            options = " or ".join(spec.layouts)
            raise WorkflowError(f"A carousel hook slide shows the person: use --layout {options}.")
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
    with_person = [key for key in spec.layouts if system.layouts[key].person]
    if fields.identity_set and with_person:
        return with_person[0], None
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
    layout_spec = system.layouts[layout] if layout is not None else None
    person = spec.person == "always" or (
        spec.person == "layout" and layout_spec is not None and layout_spec.person
    )
    posed = person and not (layout_spec is not None and layout_spec.split_poses)

    headline = _clean(fields.headline)
    subheadline = _clean(fields.subheadline)
    cta = _clean(fields.cta)
    icons = split_list(fields.icons)
    visual = _clean(fields.visual)
    stat = _clean(fields.stat)
    steps = split_list(fields.steps, STEP_SEPARATOR)
    given: dict[TextField, bool] = {
        "headline": headline is not None,
        "subheadline": subheadline is not None,
        "cta": cta is not None,
        "icons": bool(icons),
        "visual": visual is not None,
        "stat": stat is not None,
        "steps": bool(steps),
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
    if visual is not None and person:
        raise WorkflowError(
            "--visual is the system visual of layout A (or the icon of a carousel tip slide); "
            "designs that show the person do not use it."
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
        steps=steps,
        slide=slide,
        slide_role=role,
    )
