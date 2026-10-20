"""Post formats (config/post_formats.json): one per post or carousel, picked for variety.

Every format is a template: a solid theme panel with its text zones plus a separate image slot
(the picture is cropped into it; text never sits on the picture), checked at load: zones never
overlap each other or the slot. Each format's image provider is OpenRouter; it is never swapped.
pick_format: never the format or the theme of the previous post on that platform, needsNumber
formats only when the research has a sourced number, or an "as <format>" override. v6 (R5): the
Roman post formats of the removed LoRA route are archived (docs/history/README.md); Roman is a
founder layout variant made with Higgsfield Soul 2.0 (config/design_directions.json). The writer
fills only the chosen format's fields (brief.template.json), workflows/text_overlay.py renders
the template and the dry run names it.
"""

import json
import math
import random
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.ai.image import ImageError, get_provider
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel

ZoneKind = Literal[
    "big_number", "headline", "subline", "list", "two_column", "question", "quote", "icon"
]
SlideKind = Literal["cover", "body", "final"]
Platform = Literal["linkedin", "facebook", "instagram"]
FormatProvider = Literal["openrouter"]
Box = tuple[float, float, float, float]
LIST_KINDS = ("list", "two_column")
TITLE_KINDS = ("headline", "question")
PACKAGE_KEY = "format"  # package.json: the chosen format's ID
HISTORY = 2  # avoid the formats of the last 2 posts on the platform when there is a choice
ROMAN = "roman"  # the calendar's weekly Roman row: one of the Roman formats, picked at stage 1
TITLE_WORDS = 8  # a title (headline, question) has at most 8 words
LINE_WORDS = 18  # any other line (subline, quote, list item) at most 18 words
ICONS = ("check", "clock", "chat", "euro", "user", "target", "shield", "bolt", "calendar", "mail",
         "search", "arrow")
# Banned in every text a reader sees (content/quality.py too).
BANNED = re.compile(r"\bsme marketers?\b|\bleverag\w*|\bunlock\w*|\bpractical sequences?\b",
                    re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# A sourced number: a percentage, a multiple, money or a figure with a unit (not a year).
_STAT = re.compile(
    r"\d+(?:[.,]\d+)*\s*(?:%|percent|per cent|x\b|times|million|billion|thousand)"
    r"|[$€£]\s*\d+(?:[.,]\d+)*|\b\d+(?:[.,]\d+)*\s*(?:hours|minutes|days|weeks|customers|"
    r"businesses|companies|people|users|leads|calls)\b",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(r"<[^<>]{2,}>")
_WORDS = re.compile(r"[a-z0-9äöüß']+")
_COPIED_WORDS = 3  # an illustration that repeats 3 words in a row of the copy is refused
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SIZE_SLACK = 2  # px: a round slot may be off by rounding


class FormatError(ValueError):
    """config/post_formats.json is invalid, or a format cannot be used here."""


class _FormatModel(CamelModel):
    model_config = ConfigDict(extra="forbid")


def _check_box(box: Box) -> None:
    left, top, right, bottom = box
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError(f"box {list(box)}: needs 0 <= left < right <= 1, top < bottom")


def boxes_overlap(first: Box, second: Box) -> bool:
    return (first[0] < second[2] and second[0] < first[2] and first[1] < second[3]
            and second[1] < first[3])


class FormatZone(_FormatModel):
    """One zone of the text panel: a box (shares of the canvas) and how its text fits."""

    kind: ZoneKind
    field: str | None = None  # the copy field it shows (two_column: fields)
    fields: list[str] = Field(default_factory=list)  # two_column: left, right
    labels: list[str] = Field(default_factory=list)  # two_column: the column headers
    auto: Literal["step", "arrow"] | None = None  # filled by the app: the step number, an icon
    items: tuple[int, int] | None = None  # list and two_column: fewest and most items
    numbered: bool = False  # list: 1. 2. 3. instead of bullets
    box: Box
    size: tuple[int, int] = (1, 1)  # smallest and largest font size, px at 1080 px width
    weight: str = "medium"  # a key of textOverlay.fonts.weights
    max_lines: int = Field(default=1, ge=1)
    color: Literal["accent", "highlight", "text", "muted"] = "text"
    align: Literal["left", "center", "right"] = "left"
    valign: Literal["top", "middle", "bottom"] = "top"

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.kind == "two_column":
            if len(self.fields) != 2 or len(self.labels) != 2:
                raise ValueError("a two_column zone needs 2 fields and 2 labels")
        elif not self.field and self.auto is None:
            raise ValueError(f"a {self.kind} zone needs a field (or auto)")
        _check_box(self.box)
        return self

    def copy_fields(self) -> list[str]:
        if self.kind == "two_column":
            return list(self.fields)
        return [str(self.field)] if self.field else []


class ImageSlot(_FormatModel):
    """Where the picture goes (shares of the canvas); it is cropped to fill it."""

    box: Box
    shape: Literal["rect", "circle"] = "rect"

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_box(self.box)
        return self


class Bar(_FormatModel):
    """A solid decorative bar (an accent line, a colour band) in a theme colour."""

    box: Box
    color: Literal["background", "text", "highlight", "muted"] = "highlight"

    @model_validator(mode="after")
    def _check(self) -> Self:
        _check_box(self.box)
        return self


class SlideLayout(_FormatModel):
    fields: dict[str, str]  # copy field -> what the writer puts in it
    zones: list[FormatZone]
    image: ImageSlot | None = None
    bars: list[Bar] = Field(default_factory=list)


class PostFormat(_FormatModel):
    id: str = Field(min_length=1)
    platform: Platform | list[Platform]
    size: tuple[int, int]  # the final PNG, width x height
    person: Literal["none", "roman"]
    provider: FormatProvider | None = None  # None: IMAGE_PROVIDER
    theme: str = Field(min_length=1)
    weight: float = Field(gt=0)
    needs_number: bool = False
    fields: dict[str, str] = Field(default_factory=dict)
    zones: list[FormatZone] = Field(default_factory=list)
    image: ImageSlot | None = None
    bars: list[Bar] = Field(default_factory=list)
    slides: tuple[int, int] | None = None  # a carousel: fewest and most slides
    slide_types: dict[SlideKind, SlideLayout] = Field(default_factory=dict)
    settings: list[str] = Field(default_factory=list)  # Roman: where he is (one per post)
    image_prompt: str = ""

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.slides is not None:
            if set(self.slide_types) != {"cover", "body", "final"}:
                raise ValueError(f"{self.id}: a carousel format needs cover, body and final slides")
            if any(layout.image for kind, layout in self.slide_types.items() if kind != "cover"):
                raise ValueError(f"{self.id}: only the cover slide has an image slot")
        for kind in self.layout_kinds():
            fields, zones = self.layout(kind)
            missing = {name for zone in zones for name in zone.copy_fields()} - set(fields)
            if missing:
                raise ValueError(f"{self.id}: zones show fields it does not list: {missing}")
            image, bars = self.canvas(kind)
            self._check_overlaps(zones, image, bars, kind)
        if self.has_image and "{illustration}" not in self.image_prompt and not self.roman:
            raise ValueError(f"{self.id}: an image slot needs an imagePrompt with {{illustration}}")
        if self.roman:
            raise ValueError(f"{self.id}: Roman post formats were removed (PRD v6 R5); Roman is "
                             "a founder layout variant made with Higgsfield Soul 2.0")
        if self.roman and (self.image is None or not self.settings or not self.image_prompt):
            raise ValueError(f"{self.id}: a Roman format needs an image slot, settings and an "
                             "imagePrompt")
        return self

    def _check_overlaps(self, zones: list[FormatZone], image: ImageSlot | None,
                        bars: list[Bar], kind: str | None) -> None:
        where = f"{self.id}{f' {kind}' if kind else ''}"
        for number, zone in enumerate(zones):
            for other in zones[number + 1:]:
                if boxes_overlap(zone.box, other.box):
                    raise ValueError(f"{where}: the {zone.kind} and {other.kind} zones overlap")
            if image is not None and boxes_overlap(zone.box, image.box):
                raise ValueError(f"{where}: the {zone.kind} zone overlaps the image slot (text "
                                 "never goes on the picture)")
            for bar in bars:
                if boxes_overlap(zone.box, bar.box):
                    raise ValueError(f"{where}: the {zone.kind} zone overlaps a bar")
        if image is not None and image.shape == "circle":
            width, height = self.size
            left, top, right, bottom = image.box
            if abs((right - left) * width - (bottom - top) * height) > _SIZE_SLACK:
                raise ValueError(f"{where}: a round image slot must be square in pixels")

    @property
    def platforms(self) -> list[Platform]:
        return list(self.platform) if isinstance(self.platform, list) else [self.platform]

    @property
    def aspect(self) -> str:
        width, height = self.size
        return "1:1" if width == height else "4:5" if height > width else "16:9"

    @property
    def roman(self) -> bool:
        return self.person == "roman"

    @property
    def has_image(self) -> bool:
        return any(self.canvas(kind)[0] is not None for kind in self.layout_kinds())

    def layout_kinds(self) -> list[str | None]:
        return list(self.slide_types) if self.slide_types else [None]

    def layouts(self) -> list[tuple[dict[str, str], list[FormatZone]]]:
        return [self.layout(kind) for kind in self.layout_kinds()]

    def layout(self, slide_type: str | None = None) -> tuple[dict[str, str], list[FormatZone]]:
        """The fields and zones of the post, or of one carousel slide type."""
        if self.slide_types:
            found = self.slide_types.get(slide_type)  # type: ignore[call-overload]
            if found is None:
                raise FormatError(f"{self.id}: slide type must be cover, body or final")
            return found.fields, found.zones
        return self.fields, self.zones

    def canvas(self, slide_type: str | None = None) -> tuple[ImageSlot | None, list[Bar]]:
        """The image slot (None: no picture, the app renders it alone) and the bars."""
        if self.slide_types:
            found = self.slide_types.get(slide_type)  # type: ignore[call-overload]
            if found is None:
                raise FormatError(f"{self.id}: slide type must be cover, body or final")
            return found.image, found.bars
        return self.image, self.bars

    def slot_aspect(self, slide_type: str | None = None) -> str:
        """The generation aspect closest to the image slot's shape (it is cropped to fill)."""
        image, _ = self.canvas(slide_type)
        if image is None:
            return self.aspect
        width, height = self.size
        left, top, right, bottom = image.box
        shape = (right - left) * width / ((bottom - top) * height)
        ratios = {"1:1": 1.0, "4:5": 0.8, "9:16": 9 / 16, "16:9": 16 / 9}
        return min(ratios, key=lambda name: round(abs(math.log(ratios[name] / shape)), 6))

    def label(self) -> str:
        person = "Roman" if self.roman else "no person"
        extra = ", needs a sourced number" if self.needs_number else ""
        width, height = self.size
        image = "image slot" if self.has_image else "no image"
        return (f"{self.id} ({'/'.join(self.platforms)}, {width}x{height}, theme {self.theme}, "
                f"{image}, {person}{extra})")


class FormatCatalog(_FormatModel):
    note: str = Field(default="", alias="_note")
    themes: dict[str, dict[str, str]]  # background, text, highlight, muted (hex)
    no_text: str = Field(min_length=1)
    blocked_visual_words: list[str] = Field(default_factory=list)
    formats: list[PostFormat] = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [item.id for item in self.formats]
        if len(ids) != len(set(ids)):
            raise ValueError("format IDs must be unique")
        for name, colors in self.themes.items():
            if set(colors) != {"background", "text", "highlight", "muted"}:
                raise ValueError(f"theme {name}: needs background, text, highlight and muted")
        unknown = sorted({item.theme for item in self.formats} - set(self.themes))
        if unknown:
            raise ValueError(f"unknown themes: {', '.join(unknown)}")
        return self

    def get(self, format_id: str) -> PostFormat:
        for item in self.formats:
            if item.id == format_id:
                return item
        raise FormatError(f'unknown format "{format_id}" (config/post_formats.json: '
                          f"{', '.join(item.id for item in self.formats)})")

    def find(self, format_id: str) -> PostFormat | None:
        return next((item for item in self.formats if item.id == format_id), None)

    def for_platform(self, platform: str) -> list[PostFormat]:
        return [item for item in self.formats if platform in item.platforms]


def load_formats(path: Path = Path("config/post_formats.json")) -> FormatCatalog:
    """Read and check post_formats.json; a relative path is also tried in the project folder."""
    candidates = [path] if path.is_absolute() else [path, _PROJECT_ROOT / path]
    file = next((candidate for candidate in candidates if candidate.is_file()), None)
    if file is None:
        raise FormatError(f"{path} not found: restore config/post_formats.json")
    try:
        return FormatCatalog.model_validate_json(file.read_text(encoding="utf-8"))
    except ValidationError as error:
        problems = sorted({
            ".".join(str(part) for part in issue["loc"]) + f": {issue['msg']}"
            for issue in error.errors(include_url=False)
        })
        raise FormatError(f"{file.name} is invalid: {'; '.join(problems)}") from None


def recent_formats(packages_dir: Path, platform: str | None, *, exclude: Path | None = None,
                   limit: int = HISTORY) -> list[str]:
    """The formats of the newest packages on this platform (None: any), newest first."""
    found: list[tuple[str, str]] = []
    for path in packages_dir.glob("*/package.json"):
        if exclude is not None and path.parent.resolve() == exclude.resolve():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get(PACKAGE_KEY) and (
                platform is None or data.get("platform") == platform):
            found.append((str(data.get("createdAt") or ""), str(data[PACKAGE_KEY])))
    return [value for _, value in sorted(found, reverse=True)[:limit]]


def research_has_number(texts: Iterable[str]) -> bool:
    """A sourced number: a statistic written in one of the research articles."""
    return any(_STAT.search(text) for text in texts)


def provider_shows_person(settings: Settings) -> bool:
    """The image provider can make images of Roman (identity photos or a saved identity)."""
    try:
        capabilities = get_provider(settings.image_provider, settings).capabilities
    except ImageError:
        return False
    return capabilities.max_identity_refs > 0 or capabilities.identity_prompt is not None


def pick_format(
    platform: str,
    catalog: FormatCatalog,
    *,
    seed: str,
    recent: list[str],
    has_number: bool,
    person_ok: bool,
    override: str | None = None,
    last_roman: str | None = None,
) -> PostFormat:
    """The post format for a new package; recent = the platform's formats, newest first;
    override "roman" = the calendar's Roman row; last_roman = the newest Roman format used."""
    options = catalog.for_platform(platform)
    if not options:
        raise FormatError(f"config/post_formats.json has no formats for {platform}")
    wanted = (override or "").strip()
    if wanted and wanted.lower() != ROMAN:
        chosen = catalog.get(wanted)
        if platform not in chosen.platforms:
            raise FormatError(f"{chosen.id} is a {'/'.join(chosen.platforms)} format, not "
                              f"{platform}")
        if chosen.roman and not person_ok:
            raise FormatError(f"{chosen.id} shows Roman, but its provider ({chosen.provider}) "
                              "cannot make images of him")
        return chosen
    roman = bool(wanted)
    if roman:
        raise FormatError("Roman has no post format (PRD v6 R5): he is planned as a founder "
                          "layout variant, made with Higgsfield Soul 2.0")
    del person_ok
    eligible = [item for item in options
                if item.roman == roman and (has_number or not item.needs_number)]
    previous = catalog.find(recent[0]) if recent else None
    if previous is not None:  # never the format or the theme of the previous post
        eligible = [item for item in eligible
                    if item.id != previous.id and item.theme != previous.theme]
    if roman and last_roman:  # the Roman formats rotate: never the same twice in a row
        eligible = [item for item in eligible if item.id != last_roman]
    if not eligible:
        raise FormatError(f"no {platform} format fits (not the previous format or theme"
                          f"{', no sourced number' if not has_number else ''}): use "
                          "'as <format>'")
    pool = [item for item in eligible if item.id not in recent[:HISTORY]] or eligible
    rng = random.Random(f"{platform}|{seed}")
    return rng.choices(pool, weights=[item.weight for item in pool])[0]


def copy_template(chosen: PostFormat, slide_type: str | None = None) -> dict[str, Any]:
    """The format's fields as placeholders: only these go into brief.json."""
    fields, zones = chosen.layout(slide_type)
    sizes = {name: zone.items for zone in zones if zone.kind in LIST_KINDS
             for name in zone.copy_fields()}
    template: dict[str, Any] = {}
    for name, hint in fields.items():
        if name in sizes:
            count = (sizes[name] or (3, 3))[0]
            template[name] = [f"<{hint}>"] + [f"<item {n}>" for n in range(2, count + 1)]
        else:
            template[name] = f"<{hint}>"
    return template


def _word_limit(zone: FormatZone) -> int:
    return TITLE_WORDS if zone.kind in TITLE_KINDS else LINE_WORDS


def copy_problems(
    chosen: PostFormat,
    copy: Mapping[str, Any],
    where: str,
    *,
    slide_type: str | None = None,
    research: Iterable[str] = (),
) -> list[str]:
    """Every field of the format filled (and only those), list sizes, word limits, banned
    words, a valid icon and the sourced number."""
    fields, zones = chosen.layout(slide_type)
    problems = [f'{where}.copy.{name}: not a field of {chosen.id} (only: {", ".join(fields)})'
                for name in copy if name not in fields]
    lists = {name: zone for zone in zones if zone.kind in LIST_KINDS
             for name in zone.copy_fields()}
    shown = {name: zone for zone in zones for name in zone.copy_fields()}
    for name in fields:
        value = copy.get(name)
        values = value if isinstance(value, list) else [value]
        if value in (None, "", []) or any(not isinstance(item, str) or not item.strip()
                                          for item in values):
            problems.append(f"{where}.copy.{name}: fill it ({fields[name]})")
            continue
        if any(_PLACEHOLDER.search(str(item)) for item in values):
            problems.append(f"{where}.copy.{name}: replace the <...> placeholder")
        zone = lists.get(name)
        if zone is not None and not isinstance(value, list):
            problems.append(f"{where}.copy.{name}: a list of short lines")
        elif zone is None and isinstance(value, list):
            problems.append(f"{where}.copy.{name}: one line, not a list")
        elif zone is not None and zone.items is not None and isinstance(value, list):
            low, high = zone.items
            if not low <= len(value) <= high:
                problems.append(f"{where}.copy.{name}: {low}-{high} items, found {len(value)}")
        for item in values:
            text = str(item)
            problems += [f'{where}.copy.{name}: "{found.group(0)}" is banned; say it plainly'
                         for found in BANNED.finditer(text)]
            shown_zone = shown.get(name)
            if shown_zone is None or shown_zone.kind in ("big_number", "icon"):
                continue
            limit = _word_limit(shown_zone)
            if len(text.split()) > limit:
                problems.append(f"{where}.copy.{name}: at most {limit} words, found "
                                f"{len(text.split())}")
        icon = shown.get(name)
        if icon is not None and icon.kind == "icon" and str(value).strip().lower() not in ICONS:
            problems.append(f"{where}.copy.{name}: one of {', '.join(ICONS)}")
    for zone in zones:
        if zone.kind == "two_column":
            left, right = (copy.get(name) for name in zone.fields)
            if isinstance(left, list) and isinstance(right, list) and len(left) != len(right):
                problems.append(f"{where}.copy: {zone.fields[0]} and {zone.fields[1]} need the "
                                "same number of items")
    if chosen.needs_number and "big_number" in fields:
        allowed = {number for text in research for number in _NUMBER.findall(text)}
        figure = str(copy.get("big_number") or "")
        if not _NUMBER.findall(figure) or any(n not in allowed for n in _NUMBER.findall(figure)):
            problems.append(f'{where}.copy.big_number "{figure}": the number must be written in '
                            "a research article listed in sourceArticleIds; never invent one")
    return problems


def _key_words(text: str) -> list[str]:
    return _WORDS.findall(text.lower())


def illustration_problem(illustration: str, catalog: FormatCatalog,
                         copy_texts: Iterable[str] = ()) -> str | None:
    """Why an illustration cannot go into an image prompt (None: fine): it names text, a screen
    or a logo, or repeats words of the copy (the picture describes the visual only)."""
    words = _key_words(illustration)
    blocked = sorted({word for word in words if word in set(catalog.blocked_visual_words)})
    if blocked:
        return (f"the illustration mentions {', '.join(blocked)}: describe a place or objects "
                "only, nothing written and no screens")
    if '"' in illustration or "“" in illustration:
        return "the illustration quotes text: describe the visual only"
    runs = {" ".join(words[n:n + _COPIED_WORDS]) for n in range(len(words) - _COPIED_WORDS + 1)}
    for text in copy_texts:
        copied = _key_words(text)
        for n in range(len(copied) - _COPIED_WORDS + 1):
            if " ".join(copied[n:n + _COPIED_WORDS]) in runs:
                return ("the illustration repeats the copy: describe the visual only, never the "
                        "headline or topic")
    return None


def image_prompt(
    chosen: PostFormat,
    catalog: FormatCatalog,
    *,
    illustration: str | None,
    seed: str = "",
    copy_texts: Iterable[str] = (),
) -> str:
    """The picture only: never the topic, headline or copy; the illustration, no people. Every
    prompt ends with the no-text rule. FormatError for an illustration that names text, screens
    or a logo, or repeats the copy."""
    del seed
    subject = (illustration or "").strip()
    if not subject:
        raise FormatError(f"{chosen.id}: describe the picture in illustration (a place or "
                          "objects, nothing written)")
    problem = illustration_problem(subject, catalog, copy_texts)
    if problem is not None:
        raise FormatError(f"{chosen.id}: {problem}")
    prompt = (f"{chosen.image_prompt.replace('{illustration}', subject.rstrip('.'))} "
              "No people, no faces, no hands")
    prompt = f"{prompt.rstrip('. ')}. {catalog.no_text}."
    if "logo" in prompt.lower().replace(catalog.no_text.lower(), ""):
        raise FormatError(f"{chosen.id}: the image prompt must not mention a logo")
    return prompt
