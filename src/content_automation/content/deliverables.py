"""Deliverables the user can ask for by name: config/deliverables.json (DELIVERABLES_FILE).

A request names deliverables in plain words ("insta post, reel"). Each name must match one
alias exactly; an unknown or ambiguous name is never guessed, so Codex asks the user. Only
the named deliverables are built.
"""

import re
from pathlib import Path
from typing import Literal, Self

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.content.brief import (
    MAX_SLIDES,
    MIN_SLIDES,
    ContentBrief,
    Format,
    Platform,
)
from content_automation.core.files import CamelModel
from content_automation.workflows.design_system import FormatId
from content_automation.workflows.video_plan import VideoWorkflow

Part = Literal["post", "carousel", "ad", "video"]
# The package part (brief.json "formats") that makes each kind of deliverable.
FORMAT_BY_PART: dict[Part, Format] = {
    "post": "post", "carousel": "carousel", "ad": "ad", "video": "reel",
}
PART_NAMES: dict[Part, str] = {
    "post": "single-image posts", "carousel": "carousels", "ad": "image ads", "video": "videos",
}
# The registry item kind of each deliverable (PRD Phase 4 §14 D-2); "kind" in deliverables.json.
ItemKind = Literal["post", "carousel", "graphic", "youtube", "short", "podcast", "ad"]
KIND_BY_PART: dict[Part, ItemKind] = {
    "post": "post", "carousel": "carousel", "ad": "ad", "video": "short",
}
DEFAULT_PLATFORM: Platform = "instagram"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SPLIT = re.compile(r",|;|\+|&|\band\b|\bplus\b")
_FILLER = re.compile(r"^(?:(?:a|an|one|the|only|just)\s+)+|(?:\s+only)+$")


class DeliverableError(ValueError):
    """An unknown or ambiguous deliverable name, or an invalid deliverables.json."""


class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


class Deliverable(_Model):
    label: str = Field(min_length=1)
    part: Part
    platform: Platform | None = None
    format: FormatId | None = None  # a fixed design format
    formats: list[FormatId] = Field(default_factory=list)  # or: formats to rotate between
    images: int = Field(default=1, ge=1, le=4)  # image options per job (carousel: per slide)
    # Carousels: the template's slide count; a brief may use 6-8 (chosen by content).
    slides: int | None = Field(default=None, ge=MIN_SLIDES, le=MAX_SLIDES)
    workflow: VideoWorkflow | None = None  # videos
    aliases: list[str] = Field(min_length=1)
    kind: ItemKind | None = None  # the registry kind (D-2); default from the part
    # Phase 7: the image provider of this deliverable (default IMAGE_PROVIDER) and a fallback
    # that the dry run offers on its own line (used only after the user's "ok", never silently).
    provider: Literal["mock", "openrouter"] | None = None
    fallback_provider: Literal["mock", "openrouter"] | None = None

    @property
    def brief_format(self) -> Format:
        return FORMAT_BY_PART[self.part]

    @property
    def item_kind(self) -> ItemKind:
        return self.kind or KIND_BY_PART[self.part]


def normalize(name: str) -> str:
    """"Insta-Reel only" -> "insta reel"."""
    text = re.sub(r"[\s_\-]+", " ", name.lower()).strip(" .!?\"'")
    return _FILLER.sub("", text).strip()


class MonthlyPlan(_Model):
    """v5 (PRD R7): `ca plan month` at about 2 graphics a day, 30-60 a month (a carousel is
    one); mix = deliverable -> share (the PRD default per 60); every romanEvery-th LinkedIn or
    Facebook post or ad is planned with requires_roman (a founder variant)."""

    note: str = Field(default="", alias="_note")
    graphics_per_day: int = Field(default=2, ge=1, le=4)
    min_per_month: int = Field(default=30, ge=1)
    max_per_month: int = Field(default=60, ge=1)
    mix: dict[str, int] = Field(min_length=1)
    roman_every: int = Field(default=8, ge=0)  # 0: never planned with Roman
    roman_deliverables: list[str] = Field(default_factory=lambda: [
        "linkedin_post", "facebook_post", "facebook_ad"])


class WeeklySet(_Model):
    """PRD v6 weekly (2026-10-22): the fixed set of "make weekly calendar"; a month is the
    same set x monthMultiplier (it replaces the 30-60 mix). imagePosts = romanMin Roman posts
    (romanDeliverables, taking turns) + the fixed posts (2 carousels) + the rest split fairly
    across `split` (10: 4/3/3; the one with the extra post rotates week by week, so a month
    of 4 weeks is 14/13/13)."""

    note: str = Field(default="", alias="_note")
    image_posts: int = Field(default=14, ge=1)
    roman_min: int = Field(default=2, ge=0)
    roman_deliverables: list[str] = Field(default_factory=lambda: [
        "linkedin_post", "facebook_post"])
    fixed: dict[str, int] = Field(default_factory=lambda: {"instagram_carousel": 2})
    split: list[str] = Field(default_factory=lambda: [
        "linkedin_post", "facebook_post", "facebook_ad"])  # []: config/calendar.json slots
    youtube: dict[str, int] = Field(default_factory=lambda: {
        "youtube_longform": 2, "youtube_shortform": 4})
    month_multiplier: int = Field(default=4, ge=1)

    def per_month(self, value: int) -> int:
        return value * self.month_multiplier

    def split_counts(self, week: int) -> dict[str, int]:
        """The rest split fairly across `split`; week (e.g. the ISO week number) rotates
        which deliverables get the extra posts."""
        rest = self.image_posts - self.roman_min - sum(self.fixed.values())
        if not self.split:
            return {}
        base, extra = divmod(max(0, rest), len(self.split))
        start = week % len(self.split)
        lucky = {self.split[(start + n) % len(self.split)] for n in range(extra)}
        return {key: base + (key in lucky) for key in self.split}

    def week_counts(self, week: int) -> dict[str, int]:
        """Deliverables of one week: fixed + split + the Roman posts (they are LinkedIn or
        Facebook posts, one per platform in turn; Format "roman" marks them in the calendar)."""
        counts = dict(self.fixed)
        for key, value in self.split_counts(week).items():
            counts[key] = counts.get(key, 0) + value
        for n in range(self.roman_min):
            key = self.roman_deliverables[(week + n) % len(self.roman_deliverables)]
            counts[key] = counts.get(key, 0) + 1
        return counts

    def month_counts(self, first_week: int) -> dict[str, int]:
        """monthMultiplier weeks from first_week (14/13/13 split, 8 Roman, 8 carousels)."""
        total: dict[str, int] = {}
        for week in range(first_week, first_week + self.month_multiplier):
            for key, value in self.week_counts(week).items():
                total[key] = total.get(key, 0) + value
        return total


class DeliverableCatalog(_Model):
    deliverables: dict[str, Deliverable] = Field(min_length=1)
    monthly_plan: MonthlyPlan | None = None
    weekly_set: WeeklySet = Field(default_factory=WeeklySet)

    @model_validator(mode="after")
    def _check(self) -> Self:
        problems = []
        seen: dict[str, str] = {}
        for key, item in self.deliverables.items():
            if item.part == "video" and item.workflow is None:
                problems.append(f"{key}: a video needs a workflow")
            if item.part != "video" and (item.format is None) == (not item.formats):
                problems.append(f"{key}: an image part needs a format or a list of formats")
            if item.part == "ad" and item.format != "ad":
                problems.append(f'{key}: an ad uses format "ad"')
            if (item.part == "carousel") != (item.format == "carousel"):
                problems.append(f'{key}: the carousel part, and only it, uses format "carousel"')
            if (item.format == "carousel") != (item.slides is not None):
                problems.append(f"{key}: slides are set for carousels, and only for them")
            if "carousel" in item.formats or "ad" in item.formats:
                problems.append(f"{key}: formats to rotate are single-image, non-ad formats")
            for name in [key, *item.aliases]:
                alias = normalize(name)
                if seen.setdefault(alias, key) != key:
                    problems.append(f'"{alias}" names both {seen[alias]} and {key}')
        if self.monthly_plan is not None:
            unknown = sorted(set(self.monthly_plan.mix) - set(self.deliverables))
            if unknown:
                problems.append(f"monthlyPlan.mix: unknown deliverables {unknown}")
            if self.monthly_plan.min_per_month > self.monthly_plan.max_per_month:
                problems.append("monthlyPlan: minPerMonth is above maxPerMonth")
        unknown_fixed = sorted((set(self.weekly_set.fixed) | set(self.weekly_set.split)
                                | set(self.weekly_set.roman_deliverables))
                               - set(self.deliverables))
        if unknown_fixed:
            problems.append(f"weeklySet.fixed: unknown deliverables {unknown_fixed}")
        if sum(self.weekly_set.fixed.values()) + self.weekly_set.roman_min > (
                self.weekly_set.image_posts):
            problems.append("weeklySet: the fixed posts are more than imagePosts")
        if problems:
            raise ValueError("; ".join(problems))
        return self

    def names(self) -> dict[str, str]:
        """Every accepted name (aliases and IDs, normalized) -> deliverable ID."""
        found = {}
        for key, item in self.deliverables.items():
            for name in [key, *item.aliases]:
                found[normalize(name)] = key
        return found

    def resolve(self, text: str) -> list[str]:
        """The deliverable IDs named in ``text`` (comma-separated), in order.

        Raises DeliverableError for an unknown or ambiguous name, and when two named
        deliverables need the same part of a package.
        """
        names = self.names()
        chosen: list[str] = []
        problems: list[str] = []
        for raw in _SPLIT.split(text):
            name = normalize(raw)
            if not name:
                continue
            key = names.get(name)
            if key is None:
                problems.append(self._unknown(name))
            elif key not in chosen:
                chosen.append(key)
        if not chosen and not problems:
            problems.append("no deliverable was named")
        for part in FORMAT_BY_PART:
            same = [key for key in chosen if self.deliverables[key].part == part]
            if len(same) > 1:
                problems.append(
                    f"{' and '.join(same)} are both {PART_NAMES[part]}; one package makes one "
                    "of each. Ask which one, or make a second package for the other"
                )
        if problems:
            known = "; ".join(f"{key}: {', '.join(item.aliases)}" for key, item in
                              self.deliverables.items())
            raise DeliverableError(
                "Ask the user, never guess: " + ". ".join(problems) + f". Known names: {known}."
            )
        return chosen

    def _unknown(self, name: str) -> str:
        words = set(name.split())
        close = [  # every word of the name is in one of its aliases ("ad" -> "facebook ad")
            f"{item.aliases[0]} ({key})"
            for key, item in self.deliverables.items()
            if any(words <= set(normalize(alias).split()) for alias in item.aliases)
        ]
        if len(close) > 1:
            return f'"{name}" is ambiguous: it could be {" or ".join(close)}'
        if close:
            return f'"{name}" is not a known name (did the user mean {close[0]}?)'
        return f'"{name}" is not a deliverable we make'

    def images_for(self, keys: list[str], part: str) -> int | None:
        """Image options per job for a part, from the named deliverables (None: not named)."""
        return next(
            (self.deliverables[key].images for key in keys if self.deliverables[key].part == part),
            None,
        )

    def platform_for(self, keys: list[str]) -> Platform:
        """The package platform: the first named deliverable that has one."""
        platforms = [self.deliverables[key].platform for key in keys]
        return next((platform for platform in platforms if platform), DEFAULT_PLATFORM)

    def problems(self, brief: ContentBrief) -> list[str]:
        """brief.json must build exactly its deliverables, as the catalog defines them."""
        unknown = [key for key in brief.deliverables if key not in self.deliverables]
        if unknown:
            return [f"unknown deliverables: {', '.join(unknown)}"]
        if not brief.deliverables:
            return []
        items = [self.deliverables[key] for key in brief.deliverables]
        problems = []
        wanted = [item.brief_format for item in items]
        if sorted(brief.formats) != sorted(wanted):
            problems.append(
                f"formats must be exactly {wanted} for the deliverables {brief.deliverables}; "
                "build only what the user named"
            )
        for key, item in zip(brief.deliverables, items, strict=True):
            if item.part == "video":
                if brief.reel is not None and brief.reel.workflow != item.workflow:
                    problems.append(f'reel.workflow must be "{item.workflow}" ({item.label})')
                continue
            slot = {"post": brief.post, "carousel": brief.carousel, "ad": brief.ad}[item.part]
            if slot is None:
                continue
            allowed = item.formats or ([item.format] if item.format else [])
            if slot.format not in allowed:
                problems.append(
                    f"{item.part}.format must be {' or '.join(allowed)} ({item.label})"
                )
            elif item.slides is not None and not slot.direction and not (
                    MIN_SLIDES <= len(slot.slides) <= MAX_SLIDES):
                problems.append(
                    f"{item.part}.slides: {key} has {MIN_SLIDES}-{MAX_SLIDES} slides, chosen by "
                    f"the content (default {item.slides}); found {len(slot.slides)}"
                )
        return problems


def load_deliverables(path: Path) -> DeliverableCatalog:
    """Read and check deliverables.json; a relative path is also tried in the project folder."""
    candidates = [path] if path.is_absolute() else [path, _PROJECT_ROOT / path]
    file = next((candidate for candidate in candidates if candidate.is_file()), None)
    if file is None:
        raise DeliverableError(
            f"Deliverables file not found at {path}. Restore config/deliverables.json or set "
            "DELIVERABLES_FILE in .env."
        )
    try:
        return DeliverableCatalog.model_validate_json(file.read_text(encoding="utf-8"))
    except ValidationError as error:
        problems = sorted({
            ".".join(str(part) for part in issue["loc"]) or str(issue["msg"])
            for issue in error.errors(include_url=False)
        })
        raise DeliverableError(f"{file.name} is invalid; check: {'; '.join(problems)}.") from None
