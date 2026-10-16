"""Post formats (config/post_formats.json): one per post or carousel, picked for variety.

pick_format: never the format of the last 2 posts on that platform ("format" in their
package.json), Roman formats at most 1 in 3, needsNumber formats only when the research has a
sourced number, no Roman formats when the image provider cannot show him, seeded by the
Content ID; an "as <format>" override wins. The writer fills only the chosen format's fields
(brief.template.json), workflows/text_overlay.py renders its zones and the dry run names it.
"""

import json
import random
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.ai.image import ImageError, get_provider
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel

ZoneKind = Literal["big_number", "headline", "subline", "list", "two_column", "question", "quote"]
SlideKind = Literal["cover", "body", "final"]
LIST_KINDS = ("list", "two_column")
PACKAGE_KEY = "format"  # package.json: the chosen format's ID
HISTORY = 2  # never the format of the last 2 posts on the platform
ROMAN_WINDOW = 3  # Roman formats at most 1 in 3 posts
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
# A sourced number: a percentage, a multiple, money or a figure with a unit (not a year).
_STAT = re.compile(
    r"\d+(?:[.,]\d+)*\s*(?:%|percent|per cent|x\b|times|million|billion|thousand)"
    r"|[$€£]\s*\d+(?:[.,]\d+)*|\b\d+(?:[.,]\d+)*\s*(?:hours|minutes|days|weeks|customers|"
    r"businesses|companies|people|users|leads|calls)\b",
    re.IGNORECASE,
)
_PLACEHOLDER = re.compile(r"<[^<>]{2,}>")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class FormatError(ValueError):
    """config/post_formats.json is invalid, or a format cannot be used here."""


class _FormatModel(CamelModel):
    model_config = ConfigDict(extra="forbid")


class FormatZone(_FormatModel):
    """One text zone: a box (shares of the canvas) and how its text fits."""

    kind: ZoneKind
    field: str | None = None  # the copy field it shows (two_column: fields)
    fields: list[str] = Field(default_factory=list)  # two_column: left, right
    labels: list[str] = Field(default_factory=list)  # two_column: the column headers
    items: tuple[int, int] | None = None  # list and two_column: fewest and most items
    numbered: bool = False  # list: 1. 2. 3. instead of bullets
    box: tuple[float, float, float, float]
    size: tuple[int, int]  # smallest and largest font size, px at 1080 px width
    weight: str = Field(min_length=1)  # a key of textOverlay.fonts.weights
    max_lines: int = Field(default=1, ge=1)
    color: Literal["background", "accent", "highlight", "text"] = "text"
    align: Literal["left", "center", "right"] = "left"
    valign: Literal["top", "middle", "bottom"] = "top"
    scrim: Literal["auto", "always", "never"] = "auto"

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.kind == "two_column":
            if len(self.fields) != 2 or len(self.labels) != 2:
                raise ValueError("a two_column zone needs 2 fields and 2 labels")
        elif not self.field:
            raise ValueError(f"a {self.kind} zone needs a field")
        left, top, right, bottom = self.box
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError(f"box {list(self.box)}: needs 0 <= left < right <= 1, top < bottom")
        return self

    def copy_fields(self) -> list[str]:
        return list(self.fields) if self.kind == "two_column" else [str(self.field)]


class SlideLayout(_FormatModel):
    fields: dict[str, str]  # copy field -> what the writer puts in it
    zones: list[FormatZone]


class PostFormat(_FormatModel):
    id: str = Field(min_length=1)
    platform: Literal["linkedin", "facebook", "instagram"]
    size: tuple[int, int]  # the final PNG, width x height
    person: Literal["none", "roman"]
    weight: float = Field(gt=0)
    needs_number: bool = False
    classic: bool = False  # the current design-system layout (its own fields and zones)
    fields: dict[str, str] = Field(default_factory=dict)
    zones: list[FormatZone] = Field(default_factory=list)
    slides: tuple[int, int] | None = None  # a carousel: fewest and most slides
    slide_types: dict[SlideKind, SlideLayout] = Field(default_factory=dict)
    image_prompt: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.slides is not None and set(self.slide_types) != {"cover", "body", "final"}:
            raise ValueError(f"{self.id}: a carousel format needs cover, body and final slides")
        for fields, zones in self.layouts():
            missing = {name for zone in zones for name in zone.copy_fields()} - set(fields)
            if missing:
                raise ValueError(f"{self.id}: zones show fields it does not list: {missing}")
        return self

    @property
    def aspect(self) -> str:
        width, height = self.size
        return "1:1" if width == height else "4:5" if height > width else "16:9"

    @property
    def roman(self) -> bool:
        return self.person == "roman"

    def layouts(self) -> list[tuple[dict[str, str], list[FormatZone]]]:
        if self.slide_types:
            return [(layout.fields, layout.zones) for layout in self.slide_types.values()]
        return [(self.fields, self.zones)]

    def layout(self, slide_type: str | None = None) -> tuple[dict[str, str], list[FormatZone]]:
        """The fields and zones of the post, or of one carousel slide type."""
        if self.slide_types:
            found = self.slide_types.get(slide_type)  # type: ignore[call-overload]
            if found is None:
                raise FormatError(f"{self.id}: slide type must be cover, body or final")
            return found.fields, found.zones
        return self.fields, self.zones

    def label(self) -> str:
        person = "Roman" if self.roman else "no person"
        extra = ", needs a sourced number" if self.needs_number else ""
        layout = ", the current layout" if self.classic else ""
        width, height = self.size
        return f"{self.id} ({self.platform}, {width}x{height}, {person}{extra}{layout})"


class FormatCatalog(_FormatModel):
    note: str = Field(default="", alias="_note")
    image_rules: str = Field(min_length=1)
    formats: list[PostFormat] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [item.id for item in self.formats]
        if len(ids) != len(set(ids)):
            raise ValueError("format IDs must be unique")
        return self

    def get(self, format_id: str) -> PostFormat:
        for item in self.formats:
            if item.id == format_id:
                return item
        raise FormatError(f'unknown format "{format_id}" (config/post_formats.json: '
                          f"{', '.join(item.id for item in self.formats)})")

    def for_platform(self, platform: str) -> list[PostFormat]:
        return [item for item in self.formats if item.platform == platform]


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


def recent_formats(packages_dir: Path, platform: str, *, exclude: Path | None = None,
                   limit: int = ROMAN_WINDOW) -> list[str]:
    """The formats of the newest packages on this platform, newest first."""
    found: list[tuple[str, str]] = []
    for path in packages_dir.glob("*/package.json"):
        if exclude is not None and path.parent.resolve() == exclude.resolve():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("platform") == platform and data.get(PACKAGE_KEY):
            found.append((str(data.get("createdAt") or ""), str(data[PACKAGE_KEY])))
    return [value for _, value in sorted(found, reverse=True)[:limit]]


def research_has_number(texts: Iterable[str]) -> bool:
    """A sourced number: a statistic written in one of the research articles."""
    return any(_STAT.search(text) for text in texts)


def provider_shows_person(settings: Settings) -> bool:
    """The image provider can make images of Roman (identity photos or a trained LoRA)."""
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
) -> PostFormat:
    """The post format for a new package; recent = the platform's formats, newest first."""
    options = catalog.for_platform(platform)
    if not options:
        raise FormatError(f"config/post_formats.json has no formats for {platform}")
    if override:
        chosen = catalog.get(override.strip())
        if chosen.platform != platform:
            raise FormatError(f"{chosen.id} is a {chosen.platform} format, not {platform}")
        if chosen.roman and not person_ok:
            raise FormatError(f"{chosen.id} shows Roman, but the image provider cannot make "
                              "images of him; choose a format without a person")
        return chosen
    eligible = [item for item in options
                if (has_number or not item.needs_number) and (person_ok or not item.roman)]
    known = {item.id: item for item in catalog.formats}
    if any(known[name].roman for name in recent[:ROMAN_WINDOW - 1] if name in known):
        eligible = [item for item in eligible if not item.roman] or eligible
    for window in (HISTORY, 1, 0):  # the last 2; only if nothing is left, fewer
        pool = [item for item in eligible if item.id not in recent[:window]]
        if pool:
            break
    else:
        raise FormatError(f"no {platform} format fits (no sourced number and no person "
                          "images): use 'as <format>'")
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


def copy_problems(
    chosen: PostFormat,
    copy: Mapping[str, Any],
    where: str,
    *,
    slide_type: str | None = None,
    research: Iterable[str] = (),
) -> list[str]:
    """Every field of the format filled (and only those), list sizes, the sourced number."""
    if chosen.classic:
        return []
    fields, zones = chosen.layout(slide_type)
    problems = [f'{where}.copy.{name}: not a field of {chosen.id} (only: {", ".join(fields)})'
                for name in copy if name not in fields]
    lists = {name: zone for zone in zones if zone.kind in LIST_KINDS
             for name in zone.copy_fields()}
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
    for zone in zones:
        if zone.kind == "two_column":
            left, right = (copy.get(name) for name in zone.fields)
            if isinstance(left, list) and isinstance(right, list) and len(left) != len(right):
                problems.append(f"{where}.copy: {zone.fields[0]} and {zone.fields[1]} need the "
                                "same number of items")
    if chosen.needs_number:
        allowed = {number for text in research for number in _NUMBER.findall(text)}
        figure = str(copy.get("big_number") or "")
        if not _NUMBER.findall(figure) or any(n not in allowed for n in _NUMBER.findall(figure)):
            problems.append(f'{where}.copy.big_number "{figure}": the number must be written in '
                            "a research article listed in sourceArticleIds; never invent one")
    return problems


def text_areas(zones: Iterable[FormatZone]) -> str:
    """The areas the prompt keeps empty for the text."""
    return "; ".join(
        f"{zone.kind.replace('_', ' ')} ({left:.0%}-{right:.0%} of the width, "
        f"{top:.0%}-{bottom:.0%} of the height)"
        for zone in zones
        for left, top, right, bottom in [zone.box]
    )


def image_prompt(
    chosen: PostFormat,
    catalog: FormatCatalog,
    *,
    topic: str,
    illustration: str | None,
    areas: str,
    identity_text: str | None = None,
    identity_photos: int = 0,
) -> str:
    """The picture without any text: the format's prompt, the person rule, the empty areas."""
    subject = (illustration or "").strip() or f"a clean visual about {topic}"
    lines = [chosen.image_prompt.replace("{topic}", topic).replace("{illustration}", subject)]
    if chosen.roman and identity_text:
        lines.append(f"The man is {identity_text}. He is the only person in the picture.")
    elif chosen.roman:
        lines.append(
            f"The man is the person in reference images 1-{max(identity_photos, 1)}: the same "
            "face, hair, build and age as in those photos (never change or describe his face). "
            "He is the only person in the picture."
        )
    else:
        lines.append("No people, no faces, no hands.")
    lines.append(catalog.image_rules.replace("{areas}", areas))
    return "\n\n".join(lines)
