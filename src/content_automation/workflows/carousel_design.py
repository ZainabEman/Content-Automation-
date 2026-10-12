"""Animated Instagram carousel design (Phase 3): config/carousel_design.json.

The design comes from the sample carousels: 8 slides, 1:1 at 1080x1080, 5 s each at 24 fps,
silent, no transitions. Every slide is a dark navy background with a blue particle wave, the
text in the left half (static) and a text-free illustration in the right half (the only part
that moves). No people on any slide. The last slide adds a Like/Share/Save row and the logo.

Slide types: cover, point, stat, list and final. Each has text zones for the Phase 2 text
overlay (workflows/text_overlay.py), writer limits checked in the free dry run, and a default
subject for its still. The writer marks highlight words as **word**; the overlay renders them
in the highlight blue.
"""

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.core.files import CamelModel
from content_automation.workflows.design_system import Box, OverlayFonts, TextZone, ZoneField
from content_automation.workflows.registry import WorkflowError

SlideType = Literal["cover", "point", "stat", "list", "final"]
StillsProvider = Literal["higgsfield", "comfyui"]
StillSource = Literal["plugin", "local"]  # local: the app-drawn background, no request
ClipSource = Literal["higgsfield", "local"]  # local: the app's own animation, no request
ReferenceSupport = Literal["unknown", "yes", "no"]
MARK = "**"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ICONS = 3  # like, share, save
_PROMPT_FIELDS = {
    "topic": "", "illustration": "", "area": "", "background": "", "navy": "", "glow": "",
    "crest": "",
}


class CarouselDesignError(WorkflowError):
    """config/carousel_design.json is missing or invalid."""


class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


class Canvas(_Model):
    width: int = Field(ge=100)
    height: int = Field(ge=100)


class Timing(_Model):
    seconds_per_slide: float = Field(gt=0)
    fps: int = Field(ge=1)
    audio: bool = False
    transitions: bool = False


class Palette(_Model):
    background: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")  # the edges
    navy: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")  # the lifted centre
    glow: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")  # wave dots, outlines, icons
    crest: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")  # the brightest wave dots
    highlight: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")  # **highlight** words, big numbers
    text: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    sampled: str = ""  # where the colours were measured


class WriterLimits(_Model):
    """What the writer may put on one slide type; checked in the free dry run."""

    headline_words: int = Field(ge=1)
    body_words: int = Field(default=0, ge=0)  # 0 = no body line
    body_required: bool = False
    stat_chars: int = Field(default=0, ge=0)  # 0 = no big number; otherwise one is required
    items: tuple[int, int] = (0, 0)  # list items, fewest and most; (0, 0) = none
    item_words: int = Field(default=0, ge=0)
    highlight_words: tuple[int, int] = (1, 4)  # **marked** words on the whole slide
    question: bool = False  # the headline is one question ending with ?


class SlideTypeSpec(_Model):
    use: str = Field(min_length=1)  # what the slide does, for the writer
    zones: list[TextZone] = Field(min_length=1)
    limits: WriterLimits
    numbered: bool = False  # list items as 1. 2. 3.
    illustration: str = Field(min_length=1)  # the still's subject when the writer gives none
    still_note: str = ""  # added to this type's still prompt
    still: StillSource = "plugin"
    clip: ClipSource = "higgsfield"
    motion: str = Field(min_length=1)  # what moves in this type's clip


class IconLabel(_Model):
    label: str = Field(min_length=1)
    note: str = ""


class IconRow(_Model):
    """The Like/Share/Save row on the last slide: heart, paper plane, bookmark."""

    box: Box
    labels: dict[str, list[IconLabel]]  # language -> like, share, save


class LogoRule(_Model):
    slide_types: list[SlideType] = Field(min_length=1)
    position: Literal["top right"] = "top right"  # where workflows/logo.py pastes it


class BackgroundSpec(_Model):
    """The app-drawn background: navy, a dot-grid mark at the top left and a particle wave
    along the bottom that loops once per slide."""

    wave_top: float = Field(gt=0, lt=1)  # share of the height where the far crest runs
    rows: int = Field(ge=2)
    columns: int = Field(ge=2)
    amplitude: float = Field(ge=0, lt=0.2)  # share of the height
    dot_size: tuple[float, float]  # radius in px at the canvas width: far, near
    glow_radius: float = Field(ge=0)
    dot_grid: tuple[int, int] = (0, 0)  # columns, rows; (0, 0) = no mark


class StillCheckSpec(_Model):
    """`ca carousel stills-check`: thresholds for the text panel (and a blank image)."""

    max_edge_share: float = Field(gt=0, lt=1)  # share of edge pixels: letters, busy detail
    max_std_dev: float = Field(gt=0)  # brightness spread (0-255): contrast
    max_brightness: float = Field(gt=0, le=1)  # 95th percentile (0-1): white text stays legible
    min_std_dev: float = Field(ge=0)  # the illustration area below this = blank
    max_aspect_change: float = Field(ge=0, lt=1)  # wider or taller than this is not cropped
    calibrated: str = ""


class StillsSpec(_Model):
    provider: StillsProvider = "higgsfield"  # comfyui: a stub until RunPod has credit
    model: str = ""  # "" = the plugin tool's default image model (PHASE3-DECISION section 10)
    # Style frames go with the request; Codex attaches them only when the image tool accepts
    # reference images ("unknown" until the plugin listing, section 10).
    reference_images: ReferenceSupport = "unknown"
    style_references: int = Field(default=2, ge=0, le=3)
    estimated_credits: float = Field(ge=0)  # per still: an estimate until the first paid run
    usd_per_credit: float | None = Field(default=None, ge=0)  # shown beside credits
    attempts: int = Field(default=2, ge=1, le=3)  # per still, the first one included
    estimate_note: str = ""
    negative_prompt: str = Field(min_length=1)
    check: StillCheckSpec
    prompt: str = Field(min_length=1)  # {topic} {illustration} {area} and the palette colours


class ClipCheckSpec(_Model):
    """`ca carousel clips-check`, measured on grey frames at 4 per second (0-255)."""

    min_seconds: float = Field(gt=0)
    min_motion: float = Field(ge=0)  # mean change in the illustration area: not frozen
    max_text_motion: float = Field(gt=0)  # mean change in the text panel: calm
    max_text_brightness_change: float = Field(gt=0)
    max_aspect_change: float = Field(ge=0, lt=1)
    calibrated: str = ""


class ClipsSpec(_Model):
    model: str = ""  # "" = the plugin tool's default video model (section 10)
    seconds: float = Field(gt=0)
    estimated_credits: float = Field(ge=0)  # per clip: an estimate until the first paid run
    attempts: int = Field(default=2, ge=1, le=3)
    estimate_note: str = ""
    prompt: str = Field(min_length=1)  # {seconds} {motion}
    negative_prompt: str = Field(min_length=1)
    check: ClipCheckSpec


class LocalMotion(_Model):
    """The app's own animation for local slides and fallbacks."""

    zoom: float = Field(ge=0, lt=0.2)  # slow zoom on the still over the slide
    glow_pulse: float = Field(ge=0, le=1)
    wave_opacity: float = Field(ge=0, le=1)  # the animated wave over a plugin still
    icon_pulse: float = Field(ge=0, le=1)  # the final slide's icon row glow


class RenderSpec(_Model):
    crf: int = Field(default=18, ge=0, le=51)
    preset: str = "medium"


class SetCheckSpec(_Model):
    max_brightness_diff: float = Field(gt=0)  # against slide 1 (mean, 0-1)
    max_brightness: float = Field(gt=0, le=1)  # the dark navy style
    max_off_palette: float = Field(ge=0, le=1)  # share of saturated colour outside blue
    calibrated: str = ""


class StyleFrames(_Model):
    folder: str = Field(min_length=1)  # where the extracted frames go
    samples: str = Field(min_length=1)  # the sample carousels (MP4s)
    second: float = Field(default=2.5, ge=0)  # where in each clip the frame is taken
    frames: dict[SlideType, list[str]]  # type -> sample clips, best first


class SlideText(_Model):
    """One slide as the writer gives it (brief.json) or as a preview sample."""

    type: SlideType
    headline: str = Field(min_length=1)
    body: str | None = None
    stat: str | None = None
    items: list[str] = Field(default_factory=list)
    illustration: str | None = None  # the still's subject (right half)


class CarouselDesign(_Model):
    about: str = ""  # what the file is, for people reading it
    canvas: Canvas
    slides: int = Field(ge=2)
    timing: Timing
    palette: Palette
    fonts: OverlayFonts
    text_panel: Box
    illustration_area: Box
    min_contrast: float = Field(default=4.0, ge=1, le=21)
    structure: list[SlideType]
    slide_types: dict[SlideType, SlideTypeSpec]
    icon_row: IconRow
    logo: LogoRule
    background: BackgroundSpec
    languages: dict[str, str] = Field(min_length=1)  # code -> name for the writer
    stills: StillsSpec
    clips: ClipsSpec
    local_motion: LocalMotion
    render: RenderSpec = Field(default_factory=RenderSpec)
    set_check: SetCheckSpec
    style_frames: StyleFrames
    samples: list[SlideText]  # `ca carousel preview` text, one per slide; {topic} = the topic

    @model_validator(mode="after")
    def _check(self) -> Self:
        problems = []
        if len(self.structure) != self.slides:
            problems.append(f"structure has {len(self.structure)} slides, not {self.slides}")
        if self.structure and (self.structure[0] != "cover" or self.structure[-1] != "final"):
            problems.append("structure starts with cover and ends with final")
        for name in sorted(set(self.structure) | set(self.style_frames.frames)):
            if name not in self.slide_types:
                problems.append(f"slideTypes.{name} is missing")
        for name, spec in self.slide_types.items():
            have = {zone.field for zone in spec.zones}
            for zone_field in sorted(_needed(spec.limits) - have):
                problems.append(f"slideTypes.{name}.zones: no {zone_field} zone")
            for zone in spec.zones:
                if zone.weight not in self.fonts.weights:
                    problems.append(f"slideTypes.{name}.zones.{zone.field}.weight {zone.weight}")
            if len(self.style_frames.frames.get(name, [])) < self.stills.style_references:
                problems.append(f"styleFrames.frames.{name}: fewer than styleReferences")
        for language, labels in self.icon_row.labels.items():
            if len(labels) != _ICONS:
                problems.append(f"iconRow.labels.{language}: like, share and save")
        if set(self.icon_row.labels) != set(self.languages):
            problems.append("iconRow.labels and languages name the same languages")
        if [sample.type for sample in self.samples] != self.structure:
            problems.append("samples follow structure, one per slide")
        try:
            self.stills.prompt.format(**_PROMPT_FIELDS)
        except (KeyError, IndexError, ValueError):
            problems.append(f"stills.prompt uses only {{{'}, {'.join(_PROMPT_FIELDS)}}}")
        try:
            self.clips.prompt.format(seconds="", motion="")
        except (KeyError, IndexError, ValueError):
            problems.append("clips.prompt uses only {seconds} and {motion}")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def language_name(self, language: str) -> str:
        name = self.languages.get(language)
        if name is None:
            raise CarouselDesignError(
                f'carousel.language "{language}" (brand.json) is not in config/'
                f"carousel_design.json languages ({', '.join(self.languages)}); add it with its "
                "iconRow labels."
            )
        return name


def _needed(limits: WriterLimits) -> set[ZoneField]:
    needed: set[ZoneField] = {"headline"}
    if limits.body_words:
        needed.add("subheadline")
    if limits.stat_chars:
        needed.add("stat")
    if limits.items[1]:
        needed.add("points")
    return needed


def load_carousel_design(path: Path) -> CarouselDesign:
    """Read and check carousel_design.json; a relative path is also tried in the project."""
    candidates = [path] if path.is_absolute() else [path, _PROJECT_ROOT / path]
    file = next((candidate for candidate in candidates if candidate.is_file()), None)
    if file is None:
        raise CarouselDesignError(
            f"Carousel design not found at {path}. Restore config/carousel_design.json or set "
            "CAROUSEL_DESIGN_FILE in .env."
        )
    try:
        return CarouselDesign.model_validate_json(file.read_text(encoding="utf-8"))
    except ValidationError as error:
        problems = sorted({
            ".".join(str(part) for part in issue["loc"]) or str(issue["msg"])
            for issue in error.errors(include_url=False)
        })
        raise CarouselDesignError(
            f"{file.name} is invalid; check: {'; '.join(problems)}."
        ) from None


def project_path(value: str) -> Path:
    """A config path: absolute, or relative to the project folder."""
    path = Path(value)
    return path if path.is_absolute() else _PROJECT_ROOT / path


# --- Highlight marks -------------------------------------------------------------------------


def strip_marks(text: str) -> str:
    return text.replace(MARK, "")


def count_words(text: str) -> int:
    return len(strip_marks(text).split())


def split_marked(text: str) -> tuple[str, frozenset[int]]:
    """The text without marks, and the positions of the words inside **...** (a word counts
    when any of its letters is marked: "**leads**." is a marked word)."""
    words: list[str] = []
    marked: set[int] = set()
    inside = False
    for token in text.split():
        parts = token.split(MARK)
        plain = "".join(parts)
        lit = any(
            part.strip(".,:;!?\"'()") and inside != (number % 2 == 1)
            for number, part in enumerate(parts)
        )
        inside = inside != ((len(parts) - 1) % 2 == 1)
        if plain:
            if lit:
                marked.add(len(words))
            words.append(plain)
    return " ".join(words), frozenset(marked)


# --- Writer limits ---------------------------------------------------------------------------


def _limit_problems(where: str, slide: SlideText, limits: WriterLimits) -> list[str]:
    kind = slide.type
    texts = {"headline": slide.headline, "body": slide.body or ""}
    texts |= {f"items[{number}]": item for number, item in enumerate(slide.items, start=1)}
    problems = [
        f'{where}.{name}: unbalanced ** in "{text}" (mark each highlight as **word**)'
        for name, text in texts.items()
        if text.count(MARK) % 2
    ]
    words = count_words(slide.headline)
    if words > limits.headline_words:
        problems.append(f"{where}.headline: {words} words, at most {limits.headline_words}")
    body = count_words(slide.body or "")
    if body and not limits.body_words:
        problems.append(f"{where}.body: a {kind} slide has no body line; remove it")
    elif body > limits.body_words:
        problems.append(f"{where}.body: {body} words, at most {limits.body_words}")
    elif limits.body_required and not body:
        problems.append(f"{where}.body: missing (one line, at most {limits.body_words} words)")
    stat = (slide.stat or "").strip()
    if stat and not limits.stat_chars:
        problems.append(f"{where}.stat: a {kind} slide has no big number; remove it")
    elif limits.stat_chars and not stat:
        problems.append(f"{where}.stat: missing (the one big number from a cited article)")
    elif len(stat) > limits.stat_chars:
        problems.append(f'{where}.stat "{stat}": at most {limits.stat_chars} characters')
    fewest, most = limits.items
    if slide.items and not most:
        problems.append(f"{where}.items: a {kind} slide has no list; remove them")
    elif most and not fewest <= len(slide.items) <= most:
        problems.append(f"{where}.items: {fewest}-{most} items, found {len(slide.items)}")
    for number, item in enumerate(slide.items, start=1):
        if most and count_words(item) > limits.item_words:
            problems.append(
                f"{where}.items[{number}]: {count_words(item)} words, at most {limits.item_words}"
            )
    lit = sum(len(split_marked(text)[1]) for text in texts.values())
    low, high = limits.highlight_words
    if not low <= lit <= high:
        problems.append(
            f"{where}: {lit} highlight words; mark {low}-{high} key words as **word**"
        )
    if limits.question and not strip_marks(slide.headline).rstrip().endswith("?"):
        problems.append(f"{where}.headline: one question that invites comments, ending with ?")
    return problems


def slide_problems(
    slides: Sequence[SlideText], design: CarouselDesign, where: str = "carousel"
) -> list[str]:
    """Structure (cover first, final last, point/stat/list between) and the writer limits."""
    problems = []
    if len(slides) != design.slides:
        problems.append(
            f"{where}.slides: an animated carousel has {design.slides} slides "
            f"({' -> '.join(design.structure)})"
        )
    first, last = design.structure[0], design.structure[-1]
    middle = sorted(set(design.structure[1:-1]))
    for number, slide in enumerate(slides, start=1):
        at = f"{where}.slides[{number}]"
        wanted = first if number == 1 else last if number == len(slides) else None
        if wanted is not None and slide.type != wanted:
            problems.append(f'{at}.type is "{slide.type}"; slide {number} is the {wanted} slide')
        elif wanted is None and slide.type not in middle:
            problems.append(f'{at}.type: a middle slide is {" or ".join(middle)}')
        problems += _limit_problems(at, slide, design.slide_types[slide.type].limits)
    return problems


# --- Stills and the writer's template --------------------------------------------------------


def still_prompt(design: CarouselDesign, slide: SlideText, topic: str) -> str:
    """The text-free, no-people still for one slide: the illustration on the right half."""
    spec = design.slide_types[slide.type]
    left, _, right, _ = design.illustration_area
    palette = design.palette
    prompt = design.stills.prompt.format(
        topic=topic,
        illustration=(slide.illustration or spec.illustration).rstrip("."),
        area=f"{left:.0%}-{right:.0%} of the width",
        background=palette.background,
        navy=palette.navy,
        glow=palette.glow,
        crest=palette.crest,
    )
    return f"{prompt} {spec.still_note}".strip()


def clip_prompt(design: CarouselDesign, slide_type: SlideType) -> str:
    """The image-to-video prompt: only the right-half illustration moves, subtly."""
    clips = design.clips
    motion = design.slide_types[slide_type].motion.rstrip(".")
    return clips.prompt.format(seconds=f"{clips.seconds:g}", motion=motion)


def _limits_text(limits: WriterLimits) -> str:
    parts = [f"headline at most {limits.headline_words} words"]
    if limits.question:
        parts[0] += ", one question ending with ?"
    if limits.stat_chars:
        parts.append(f"stat at most {limits.stat_chars} characters")
    if limits.body_words:
        need = "required" if limits.body_required else "optional"
        parts.append(f"body at most {limits.body_words} words ({need})")
    if limits.items[1]:
        parts.append(
            f"{limits.items[0]}-{limits.items[1]} items of at most {limits.item_words} words"
        )
    low, high = limits.highlight_words
    parts.append(f"{low}-{high} **highlight** words")
    return "; ".join(parts)


def writer_help(design: CarouselDesign, language: str) -> dict[str, Any]:
    """The carousel block of the brief template's _help."""
    return {
        "language": (
            f"Write every slide text in {design.language_name(language)} "
            "(brand.json carousel.language)."
        ),
        "structure": (
            f"{design.slides} slides: {' -> '.join(design.structure)}. Slide 1 is the cover, the "
            "last slide the final question. Middle slides are point, stat or list; a stat needs "
            "a number written in a cited research article (otherwise use point)."
        ),
        "highlight": (
            "Mark the key words as **word**; the app renders them in highlight blue. Never use "
            "other markup."
        ),
        "types": {
            name: f"{spec.use} {_limits_text(spec.limits)}."
            for name, spec in design.slide_types.items()
        },
        "illustration": (
            "Per slide, what the right half shows (a white 3D robot, neon icons or a holographic "
            "chart that fits the slide). No people, no text, no numbers: the app adds the text."
        ),
        "look": (
            f"1:1, {design.timing.seconds_per_slide:g} s per slide; dark navy with a blue "
            "particle wave; the text stays still on the left, only the illustration moves; the "
            "logo and a Like/Share/Save row on the last slide."
        ),
    }


def _slide_template(name: SlideType, spec: SlideTypeSpec) -> dict[str, Any]:
    limits = spec.limits
    headline = f"<at most {limits.headline_words} words, key words as **word**>"
    if limits.question:
        headline = (
            f"<one question that invites comments, at most {limits.headline_words} words, "
            "ending with ?>"
        )
    elif name == "cover":
        headline = (
            f"<the problem or the promise, at most {limits.headline_words} words, key words as "
            "**word**>"
        )
    slide: dict[str, Any] = {"type": name}
    if limits.stat_chars:
        slide["stat"] = (
            f"<the number exactly as a cited article writes it, at most {limits.stat_chars} "
            "characters, e.g. 73%>"
        )
    slide["headline"] = headline
    if limits.body_words:
        need = "" if limits.body_required else "optional, "
        slide["body"] = f"<{need}one line, at most {limits.body_words} words>"
    if limits.items[1]:
        slide["items"] = [f"<item, at most {limits.item_words} words>"] * limits.items[0]
    slide["illustration"] = f"<right half, no people or text: e.g. {spec.illustration}>"
    return slide


def slides_template(design: CarouselDesign) -> list[dict[str, Any]]:
    """The slides of the brief template, in the design's structure."""
    return [_slide_template(name, design.slide_types[name]) for name in design.structure]
