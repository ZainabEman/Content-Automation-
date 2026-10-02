"""brief.json: what Codex decides for one content package (designs, reel, caption).

Keys starting with "_" (like the "_help" block in brief.template.json) are ignored.
"""

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError

from content_automation.core.files import CamelModel
from content_automation.workflows.design_system import CtaIconId, Kind, LayoutId, SlideRole

Platform = Literal["instagram", "facebook", "linkedin"]
Format = Literal["post", "ad", "reel"]
ImageRef = Literal["post-1", "post-2", "ad-1", "ad-2", "ad-3"]
PLATFORMS: tuple[Platform, ...] = ("instagram", "facebook", "linkedin")
FORMATS: tuple[Format, ...] = ("post", "ad", "reel")
ASPECT_BY_PLATFORM = {"instagram": "4:5", "facebook": "4:5", "linkedin": "1:1"}
STORY_ASPECT = "9:16"
# The design kind of each image slot: the default first, then the others it may use.
SLOT_KINDS: dict[str, tuple[Kind, ...]] = {
    "post": ("organic", "story", "carousel_slide"),
    "ad": ("ad",),
}
MAX_HEADLINE_WORDS = 6
MAX_REEL_SEC = 90
MIN_HASHTAGS, MAX_HASHTAGS = 3, 5
_PLACEHOLDER = re.compile(r"<[^<>]{2,}>")


class BriefError(ValueError):
    """brief.json is missing or invalid; ``problems`` lists every issue."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        lines = "\n".join(f"- {problem}" for problem in problems)
        super().__init__(f"brief.json has {len(problems)} problem(s):\n{lines}")


class _BriefModel(CamelModel):
    model_config = ConfigDict(extra="forbid")


class ImageSlot(_BriefModel):
    """A post or ad image: a designed graphic (social_creative) from the design system.

    The fields match the `ca image` flags; subheadline and cta are required so that no
    design is left empty.
    """

    kind: Kind | None = None  # default: post -> organic, ad -> ad
    layout: LayoutId | None = None  # required, except for carousel slides
    pose: str | None = None  # layouts B and C: a pose key of the design system
    headline: str = Field(min_length=1)
    highlight: list[str] = Field(default_factory=list, max_length=2)  # headline words
    subheadline: str = Field(min_length=1)
    sub_highlight: str | None = None  # one subheadline word
    cta: str = Field(min_length=1)  # the button label
    cta_icon: CtaIconId | None = None  # default: chosen from the cta label
    icons: list[str] = Field(default_factory=list, max_length=4)  # icon row labels
    visual: str | None = None  # layout A: the system visual
    slide: str | None = None  # carousel slides: "N/TOTAL"
    slide_role: SlideRole | None = None
    scene: str = Field(min_length=1)  # scene details: setting, light, camera, mood


class Caption(_BriefModel):
    """The post text, in this order; the cta with the link and the hashtags follow it."""

    hook: str = Field(min_length=1)  # line 1
    lines: list[str] = Field(min_length=2, max_length=3)  # short: problem -> solution
    question: str = Field(min_length=1)  # one question that invites comments


class ReelScene(_BriefModel):
    prompt: str = Field(min_length=1)  # the shot, for the video provider
    duration_sec: float = Field(gt=0, le=15)
    on_screen_text: str | None = None
    image: ImageRef | None = None  # show this package image (slow zoom) instead of a clip


class ReelSlot(_BriefModel):
    hook: str = Field(min_length=1)
    script: str = Field(min_length=1)
    first_frame: ImageRef | None = None  # start image of scene 1 (default: best post image)
    scenes: list[ReelScene] = Field(min_length=1, max_length=8)


class ContentBrief(_BriefModel):
    topic: str = Field(min_length=1)
    platform: Platform
    formats: list[Format] = Field(min_length=1)
    service: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)
    identity_set: str | None = None  # default: DEFAULT_IDENTITY_SET
    source_article_ids: list[str] = Field(default_factory=list)
    post: ImageSlot | None = None
    ad: ImageSlot | None = None
    reel: ReelSlot | None = None
    caption: Caption
    hashtags: list[str] = Field(min_length=MIN_HASHTAGS, max_length=MAX_HASHTAGS)
    cta: str = Field(min_length=1)
    link: str = Field(pattern=r"^https?://\S+$")  # closes the caption, after the cta


def brand_hashtag(brand_name: str) -> str:
    """The hashtag every post carries, e.g. "Branded Genius" -> "#BrandedGenius"."""
    return "#" + re.sub(r"\W", "", brand_name)


def slot_kind(name: str, slot: ImageSlot) -> Kind:
    return slot.kind or SLOT_KINDS[name][0]


def load_brief(
    path: Path, *, services: list[str], known_article_ids: set[str], brand_tag: str | None = None
) -> ContentBrief:
    """Read and check brief.json; raise BriefError listing every problem."""
    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        missing = f"{path.name} not found: write it first (see brief.template.json)"
        raise BriefError([missing]) from None
    except json.JSONDecodeError as error:
        raise BriefError([f"not valid JSON: {error}"]) from None
    if not isinstance(raw, dict):
        raise BriefError(["the file must contain one JSON object"])
    data = {key: value for key, value in raw.items() if not str(key).startswith("_")}
    try:
        brief = ContentBrief.model_validate(data)
    except ValidationError as error:
        raise BriefError([_describe(issue) for issue in error.errors(include_url=False)]) from None
    problems = brief_problems(
        brief, services=services, known_article_ids=known_article_ids, brand_tag=brand_tag
    )
    placeholders = sorted(set(_PLACEHOLDER.findall(json.dumps(data, ensure_ascii=False))))
    if placeholders:
        problems.append(f"replace the template placeholders: {', '.join(placeholders[:5])}")
    if problems:
        raise BriefError(problems)
    return brief


def brief_problems(
    brief: ContentBrief,
    *,
    services: list[str],
    known_article_ids: set[str],
    brand_tag: str | None = None,
) -> list[str]:
    problems: list[str] = []
    for kind in FORMATS:
        slot = getattr(brief, kind)
        if kind in brief.formats and slot is None:
            problems.append(f'"{kind}" is in formats, so fill in "{kind}"')
        if kind not in brief.formats and slot is not None:
            problems.append(f'"{kind}" is filled in but not in formats; remove it or add it')
    for name, kinds in SLOT_KINDS.items():
        image: ImageSlot | None = getattr(brief, name)
        if image is None:
            continue
        if len(image.headline.split()) > MAX_HEADLINE_WORDS:
            problems.append(f"{name}.headline has more than {MAX_HEADLINE_WORDS} words")
        if slot_kind(name, image) not in kinds:
            problems.append(f"{name}.kind must be one of: {', '.join(kinds)}")
        elif image.layout is None and slot_kind(name, image) != "carousel_slide":
            problems.append(f"{name}.layout: choose A, B, C or D")
    if services and brief.service not in services:
        problems.append(f"service must be one of: {'; '.join(services)}")
    for tag in brief.hashtags:
        if not re.fullmatch(r"#\w+", tag):
            problems.append(f'hashtag "{tag}" must look like #OneWord')
    if brand_tag and brand_tag.lower() not in {tag.lower() for tag in brief.hashtags}:
        problems.append(f"hashtags must include {brand_tag}")
    if not brief.caption.question.rstrip().endswith("?"):
        problems.append("caption.question must be one question ending with ?")
    unknown = [aid for aid in brief.source_article_ids if aid not in known_article_ids]
    if unknown:
        problems.append(f"unknown sourceArticleIds (see research.md): {', '.join(unknown)}")
    if brief.reel is not None:
        total = sum(scene.duration_sec for scene in brief.reel.scenes)
        if total > MAX_REEL_SEC:
            problems.append(f"the reel scenes add up to {total:g} s (max {MAX_REEL_SEC} s)")
        refs = [brief.reel.first_frame] + [scene.image for scene in brief.reel.scenes]
        for ref in refs:
            if ref is not None and ref.split("-")[0] not in brief.formats:
                problems.append(f'reel uses "{ref}" but "{ref.split("-")[0]}" is not in formats')
    return problems


def _describe(issue: Any) -> str:
    location = ".".join(
        f"[{part + 1}]" if isinstance(part, int) else str(part) for part in issue["loc"]
    ).replace(".[", "[")
    if issue["type"] == "missing":
        return f"{location}: missing"
    if issue["type"] == "extra_forbidden":
        return f"{location}: unknown field (check spelling; fields are camelCase)"
    return f"{location}: {issue['msg']}" if location else str(issue["msg"])
