"""Design system for designed graphics (social_creative): config/design_system.json.

The file describes the look, layouts, poses and text rules. It names colours only by role
(background, accent, highlight, text); the prompt builder maps each role to a brand.json
colour. Fonts and the logo come from brand.json too.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.ai.image import AspectRatio
from content_automation.core.files import CamelModel
from content_automation.workflows.registry import WorkflowError

Kind = Literal["organic", "ad", "story", "carousel_slide"]
LayoutId = Literal["A", "B", "C", "D"]
CtaIconId = Literal["arrow", "calendar", "play"]
SlideRole = Literal["hook", "tip", "cta"]
ColorRole = Literal["background", "accent", "highlight", "text"]
KINDS: tuple[Kind, ...] = ("organic", "ad", "story", "carousel_slide")
LAYOUTS: tuple[LayoutId, ...] = ("A", "B", "C", "D")
CTA_ICONS: tuple[CtaIconId, ...] = ("arrow", "calendar", "play")
SLIDE_ROLES: tuple[SlideRole, ...] = ("hook", "tip", "cta")
COLOR_ROLES: tuple[ColorRole, ...] = ("background", "accent", "highlight", "text")
MAX_HIGHLIGHT_WORDS = 2
ICON_LABELS_MIN, ICON_LABELS_MAX = 3, 4
MAX_ICON_LABEL_WORDS = 2
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SLIDE = re.compile(r"(\d{1,2})\s*/\s*(\d{1,2})")


class DesignSystemError(WorkflowError):
    """design_system.json is missing or invalid."""


class _DesignModel(CamelModel):
    model_config = ConfigDict(extra="forbid")


class ColorRoleSpec(_DesignModel):
    usage: list[str] = Field(min_length=1)  # words looked for in a brand colour's "usage"
    use: str = Field(min_length=1)  # what the design uses that colour for


class Typography(_DesignModel):
    headline: str = Field(min_length=1)
    subheadline: str = Field(min_length=1)


class CtaIcon(_DesignModel):
    icon: str = Field(min_length=1)
    actions: list[str] = Field(default_factory=list)  # CTA words that pick this icon


class CtaButton(_DesignModel):
    description: str = Field(min_length=1)
    pointer: str = ""
    icons: dict[CtaIconId, CtaIcon]


class LayoutSpec(_DesignModel):
    use: str = Field(min_length=1)
    description: str = Field(min_length=1)
    person: bool
    default_pose: str | None = None
    split_poses: list[str] = Field(default_factory=list)  # before/after: left pose, right pose


class FormatSpec(_DesignModel):
    description: str = Field(min_length=1)
    aspects: list[AspectRatio] = Field(min_length=1)  # the first one is the default
    safe_zone: str = ""


class CarouselSpec(_DesignModel):
    slides: dict[SlideRole, str]
    navigation: str = Field(min_length=1)


class PersonSpec(_DesignModel):
    wardrobe: str = Field(min_length=1)


class DesignRules(_DesignModel):
    organic: list[str] = Field(min_length=1)
    ad: list[str] = Field(min_length=1)


class DesignSystem(_DesignModel):
    style: str = Field(min_length=1)
    color_roles: dict[ColorRole, ColorRoleSpec]
    text_panel: str = Field(min_length=1)
    typography: Typography
    cta_button: CtaButton
    holograms: str = Field(min_length=1)
    icon_row: str = Field(min_length=1)
    decor: str = Field(min_length=1)
    props: str = Field(min_length=1)
    logo: str = Field(min_length=1)
    layouts: dict[LayoutId, LayoutSpec]
    poses: dict[str, str] = Field(min_length=1)
    headline_formulas: dict[str, str] = Field(default_factory=dict)  # name -> example
    formats: dict[Kind, FormatSpec]
    carousel: CarouselSpec
    person: PersonSpec
    rules: DesignRules

    @model_validator(mode="after")
    def _check_complete(self) -> Self:
        missing = (
            [f"layouts.{key}" for key in LAYOUTS if key not in self.layouts]
            + [f"formats.{key}" for key in KINDS if key not in self.formats]
            + [f"ctaButton.icons.{key}" for key in CTA_ICONS if key not in self.cta_button.icons]
            + [f"colorRoles.{key}" for key in COLOR_ROLES if key not in self.color_roles]
            + [f"carousel.slides.{key}" for key in SLIDE_ROLES if key not in self.carousel.slides]
        )
        for layout_id, layout in self.layouts.items():
            if len(layout.split_poses) not in (0, 2):
                missing.append(f"layouts.{layout_id}.splitPoses (a left and a right pose)")
            for pose in (layout.default_pose, *layout.split_poses):
                if pose is not None and pose not in self.poses:
                    missing.append(f"poses.{pose} (used by layout {layout_id})")
        if missing:
            raise ValueError("missing " + ", ".join(missing))
        return self

    def cta_icon_for(self, label: str) -> CtaIconId:
        """The button icon for the first action word in the CTA label (default: arrow)."""
        for word in re.findall(r"[a-z]+", label.lower()):
            for icon_id, icon in self.cta_button.icons.items():
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
    slide: str | None
    slide_role: str | None


@dataclass(frozen=True)
class DesignChoice:
    """What one designed graphic shows, checked against the design system."""

    kind: Kind
    layout: LayoutId | None = None  # None: carousel tip and cta slides
    person: bool = False  # the man is shown, so identity photos are required
    pose: str | None = None  # key in DesignSystem.poses
    headline: str | None = None
    highlight: tuple[str, ...] = ()
    subheadline: str | None = None
    sub_highlight: str | None = None
    cta: str | None = None
    cta_icon: CtaIconId | None = None
    icons: tuple[str, ...] = ()
    visual: str | None = None
    slide: tuple[int, int] | None = None  # (number, total)
    slide_role: SlideRole | None = None

    @property
    def label(self) -> str:
        """How error messages name this design."""
        if self.slide_role is not None:
            return f"A carousel {self.slide_role} slide"
        return f"Layout {self.layout}"


def _choice[T: str](value: str, options: tuple[T, ...], flag: str) -> T:
    for option in options:
        if option == value.strip():
            return option
    raise WorkflowError(f"{flag} must be one of: {', '.join(options)}.")


def _clean(value: str | None) -> str | None:
    return (value or "").strip() or None


def split_list(value: str | None) -> tuple[str, ...]:
    """Comma-separated words or labels, as given to --highlight and --icons."""
    return tuple(part.strip() for part in (value or "").split(",") if part.strip())


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


def resolve_design(fields: DesignFields, system: DesignSystem, *, kind: str) -> DesignChoice:
    """Check the design options and fill the defaults; WorkflowError names the flag to fix."""
    kind_id = _choice(kind, KINDS, "--kind")
    slide = _parse_slide(fields.slide)
    role: SlideRole | None = None
    layout: LayoutId | None = None
    if kind_id == "carousel_slide":
        if fields.slide_role:
            role = _choice(fields.slide_role, SLIDE_ROLES, "--slide-role")
        elif slide is None or slide[0] == 1:
            role = "hook"
        else:
            role = "cta" if slide[0] == slide[1] else "tip"
        if role == "hook":
            layout = _choice(fields.layout, LAYOUTS, "--layout") if fields.layout else "B"
            if not system.layouts[layout].person or system.layouts[layout].split_poses:
                raise WorkflowError("A carousel hook slide shows the person: use --layout B or C.")
        elif fields.layout:
            raise WorkflowError(f"A carousel {role} slide has no layout letter; remove --layout.")
    elif slide is not None or fields.slide_role:
        raise WorkflowError("--slide and --slide-role are for --kind carousel_slide.")
    elif fields.layout:
        layout = _choice(fields.layout, LAYOUTS, "--layout")
    else:
        layout = "B" if fields.identity_set else "A"
    spec = system.layouts[layout] if layout is not None else None
    person = spec is not None and spec.person
    posed = person and spec is not None and not spec.split_poses

    pose = _clean(fields.pose)
    if pose is not None:
        if not posed:
            raise WorkflowError("--pose is for layouts B and C and carousel hook slides.")
        if pose not in system.poses:
            raise WorkflowError(f"--pose must be one of: {', '.join(system.poses)}.")
    elif posed and spec is not None:
        pose = spec.default_pose

    visual = _clean(fields.visual)
    if visual is not None and person:
        raise WorkflowError(
            "--visual is the system visual of layout A (or the icon of a carousel tip slide); "
            "designs that show the person do not use it."
        )

    headline = _clean(fields.headline)
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
    subheadline = _clean(fields.subheadline)
    sub_highlight = _clean(fields.sub_highlight)
    if sub_highlight is not None and (
        subheadline is None or not _contains(subheadline, sub_highlight)
    ):
        raise WorkflowError("--sub-highlight must be a word from --subheadline.")

    cta = _clean(fields.cta)
    cta_icon: CtaIconId | None = None
    if fields.cta_icon:
        if cta is None:
            raise WorkflowError("--cta-icon needs --cta (the button label).")
        cta_icon = _choice(fields.cta_icon, CTA_ICONS, "--cta-icon")
    elif cta is not None:
        cta_icon = system.cta_icon_for(cta)

    icons = split_list(fields.icons)
    if icons and (
        not ICON_LABELS_MIN <= len(icons) <= ICON_LABELS_MAX
        or any(len(label.split()) > MAX_ICON_LABEL_WORDS for label in icons)
    ):
        raise WorkflowError(
            f"--icons takes {ICON_LABELS_MIN}-{ICON_LABELS_MAX} labels of 1-"
            f'{MAX_ICON_LABEL_WORDS} words each, e.g. "Chatbots,CRM,Email".'
        )

    return DesignChoice(
        kind=kind_id,
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
        slide=slide,
        slide_role=role,
    )
