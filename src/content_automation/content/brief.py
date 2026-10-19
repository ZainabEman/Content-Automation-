"""brief.json: what Codex decides for one content package (designs, reel, caption).

Keys starting with "_" (like the "_help" block in brief.template.json) are ignored.
"""

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.content.relevance import INSIGHT_ONLY
from content_automation.core.files import CamelModel
from content_automation.workflows.design_system import (
    DEFAULT_FORMAT,
    CtaIconId,
    FormatId,
    Kind,
    LayoutId,
    SlideRole,
)
from content_automation.workflows.video_plan import VideoWorkflow
from content_automation.workflows.video_workflows import VIDEO_WORKFLOWS

Platform = Literal["instagram", "facebook", "linkedin"]
Format = Literal["post", "carousel", "ad", "reel"]
ImageRef = Literal[
    "post-1", "post-2", "post-3", "post-4", "post-5", "post-6", "post-7",
    "carousel-1", "carousel-2", "carousel-3", "carousel-4", "carousel-5", "carousel-6",
    "carousel-7", "carousel-8", "ad-1", "ad-2", "ad-3",
]
# The carousel story, in order: hook -> problem -> steps or insights -> example or result -> cta.
StoryRole = Literal["hook", "problem", "step", "insight", "example", "result", "cta"]
PLATFORMS: tuple[Platform, ...] = ("instagram", "facebook", "linkedin")
FORMATS: tuple[Format, ...] = ("post", "carousel", "ad", "reel")
ASPECT_BY_PLATFORM = {"instagram": "4:5", "facebook": "4:5", "linkedin": "1:1"}
STORY_ASPECT = "9:16"
# The design kind of each image slot: the default first, then the others it may use.
SLOT_KINDS: dict[str, tuple[Kind, ...]] = {
    "post": ("organic", "story", "carousel_slide"),
    "carousel": ("carousel_slide",),
    "ad": ("ad",),
}
MIN_SLIDES, MAX_SLIDES = 6, 8  # a carousel story (v1 or a post format's static slides)
CopyValue = str | list[str]
SlideKind = Literal["cover", "body", "final"]
_HEADLINE_FIELDS = ("headline", "question", "quote", "main", "keyword", "lead_in")  # main line
MAX_REEL_SEC = 90
MIN_HASHTAGS, MAX_HASHTAGS = 3, 5
MIN_TAKEAWAYS, MAX_TAKEAWAYS = 3, 5
MIN_INSIGHTS = 6
_PLACEHOLDER = re.compile(r"<[^<>]{2,}>")


class BriefError(ValueError):
    """brief.json is missing or invalid; ``problems`` lists every issue."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        lines = "\n".join(f"- {problem}" for problem in problems)
        super().__init__(f"brief.json has {len(problems)} problem(s):\n{lines}")


class _BriefModel(CamelModel):
    model_config = ConfigDict(extra="forbid")


class ChatBubble(_BriefModel):
    """One bubble of a tip slide's chat example; the text is rendered exactly."""

    speaker: Literal["customer", "bot"] = Field(alias="from")
    text: str = Field(min_length=1)


class BeforeAfter(_BriefModel):
    before: str = Field(min_length=1)
    after: str = Field(min_length=1)


class SlideSlot(_BriefModel):
    """One slide of a carousel story: the first (hook) and the last (cta) show the man; the
    slides between are information visuals without people."""

    role: StoryRole | None = None  # where the slide is in the story
    headline: str = Field(min_length=1)
    highlight: list[str] = Field(default_factory=list, max_length=2)  # headline words
    subheadline: str | None = None  # middle slides: the concrete fact or action
    sub_highlight: str | None = None
    visual: str | None = None  # not on middle slides: they use one of the four visuals below
    chat: list[ChatBubble] = Field(default_factory=list, max_length=3)  # middle slides
    diagram: list[str] = Field(default_factory=list, max_length=4)  # middle slides: workflow
    checklist: list[str] = Field(default_factory=list, max_length=3)  # middle: 3-row checklist
    before_after: BeforeAfter | None = None  # middle slides: before / after
    cta: str | None = None  # last slide only: the button label
    cta_icon: CtaIconId | None = None
    # A post format's static slide (carousel.postFormat, config/post_formats.json): cover,
    # body or final; its text in "copy" (only that format's fields), the picture without text
    # in "illustration", and the alt text for Instagram.
    type: SlideKind | None = None
    # Phase D: a design direction's slide (carousel.direction): its slide role (cover, what,
    # how, ..., cta; config/design_directions.json slideRoles) and that layout's fields in copy.
    direction_role: str | None = None
    copy_text: dict[str, CopyValue] = Field(default_factory=dict, alias="copy")
    illustration: str | None = None
    alt_text: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _headline_from_copy(cls, data: Any) -> Any:
        """A format slide's main line (headline, question or quote) is also its headline."""
        if isinstance(data, dict) and not data.get("headline") and isinstance(
                data.get("copy"), dict):
            for name in _HEADLINE_FIELDS:
                value = data["copy"].get(name)
                if isinstance(value, str) and value.strip():
                    return {**data, "headline": value}
            if data.get("directionRole"):  # a direction slide without a main line (cards)
                return {**data, "headline": str(data["directionRole"])}
        return data


class CardCopy(_BriefModel):
    """Live fix: the branded person-post card (insight/stat template): tag, German subtitle,
    an icon per bullet, the CTA in English and German, an optional verified stat."""

    tag: str | None = None  # "AI RISK · HR"
    subtitle: str | None = None  # German
    icons: list[str] = Field(default_factory=list, max_length=3)
    cta_en: str | None = None
    cta_de: str | None = None
    stat: str | None = None  # only with a verified fact claim (the copy check)
    stat_label: str | None = None


class ImageSlot(_BriefModel):
    """A post or ad image: a designed graphic (social_creative) from the design system.

    The fields match the `ca image` flags. Which texts are required depends on ``format``
    (see "formats" in config/design_system.json); a brief without a format is an "ad".
    """

    format: FormatId = DEFAULT_FORMAT
    kind: Kind | None = None  # default: post -> organic (carousel: carousel_slide), ad -> ad
    layout: LayoutId | None = None  # A, B, C or D; left out, it rotates between packages
    pose: str | None = None  # a pose from the pools; picked when left out
    audience_line: str | None = None  # "FOR DENTAL PRACTICES" (statement, stat, checklist, hook)
    headline: str | None = None
    highlight: list[str] = Field(default_factory=list, max_length=2)  # headline words
    subheadline: str | None = None
    sub_highlight: str | None = None  # one subheadline word
    cta: str | None = None  # the button label (format ad only)
    primary_text: str | None = None  # format ad: the text above the ad (Phase 7, from copy)
    cta_icon: CtaIconId | None = None  # default: chosen from the cta label
    icons: list[str] = Field(default_factory=list, max_length=4)  # icon row labels
    visual: str | None = None  # layout A: the system visual
    stat: str | None = None  # format stat: the one big number
    source: str | None = None  # format stat (required) and news: the research article ID
    source_name: str | None = None  # format stat: "Source: <this>" (default: the article's)
    points: list[str] = Field(default_factory=list, max_length=3)  # post: 3 key points
    steps: list[str] = Field(default_factory=list, max_length=5)  # old briefs only
    slides: list[SlideSlot] = Field(default_factory=list, max_length=MAX_SLIDES)  # carousel
    slide: str | None = None  # a single carousel slide instead of "slides": "N/TOTAL"
    slide_role: SlideRole | None = None
    # LinkedIn post only: false leaves the man out when the topic fits ("no person" in the
    # dry run); left out, he is shown as in every other post.
    person: bool | None = None
    # A pool ID from the design system or own words; picked for variety when left out.
    scene: str | None = None
    wardrobe: str | None = None
    props: str | None = None
    card: CardCopy | None = None  # live fix: the branded person-post card (from saved copy)
    # The post format (config/post_formats.json, chosen at stage 1 and saved in package.json):
    # its fields go into "copy" (a carousel: per slide), its zones are rendered by the app.
    post_format: str | None = None
    # Phase D: the design direction (config/design_directions.json, chosen at stage 1); its
    # layout's fields go into "copy" (a carousel: per slide); the app draws the design.
    direction: str | None = None
    copy_text: dict[str, CopyValue] = Field(default_factory=dict, alias="copy")

    @property
    def templated(self) -> bool:
        """A post format or a design direction: the app renders the text, not the old design."""
        return bool(self.post_format or self.direction)


class Caption(_BriefModel):
    """The post text, in this order; the cta with the offer, the link and the hashtags follow.

    Hook, takeaways, question and cta together are 120-200 words, 120-250 for LinkedIn
    (checked by the dry run).
    """

    hook: str = Field(min_length=1)  # line 1
    takeaways: list[str] = Field(min_length=MIN_TAKEAWAYS, max_length=MAX_TAKEAWAYS)
    question: str = Field(min_length=1)  # one question that invites comments
    closing_de: str | None = None  # live fix: the one German line after the question


class Insight(_BriefModel):
    """A specific, usable finding from the research, written before the content."""

    text: str = Field(min_length=1)  # an action, how-to step, example wording, timing, tool...
    source: str = Field(min_length=1)  # a research article ID or a link listed in research.md


class ReelScene(_BriefModel):
    type: Literal["video", "avatar"] = "video"  # avatar: the avatar says ``prompt``
    prompt: str = Field(min_length=1)  # video: the shot; avatar: the exact words
    duration_sec: float = Field(gt=0, le=15)
    on_screen_text: str | None = None
    image: ImageRef | None = None  # show this package image (slow zoom) instead of a clip


class ReelSlot(_BriefModel):
    """The package's video: reel_short (see deliverables.json; UGC and podcast removed in v5)."""

    workflow: VideoWorkflow = "reel_short"
    hook: str = Field(min_length=1)
    script: str = Field(min_length=1)
    first_frame: ImageRef | None = None  # start image of scene 1 (default: best post image)
    scenes: list[ReelScene] = Field(min_length=1, max_length=8)


class ContentBrief(_BriefModel):
    topic: str = Field(min_length=1)
    deliverables: list[str] = Field(default_factory=list)  # what the user named; sets formats
    platform: Platform
    formats: list[Format] = Field(min_length=1)
    service: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)
    identity_set: str | None = None  # default: DEFAULT_IDENTITY_SET
    source_article_ids: list[str] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)  # at least 6 (checked by the dry run)
    post: ImageSlot | None = None  # a single designed image (e.g. facebook_post)
    carousel: ImageSlot | None = None  # format carousel with its slides (instagram_carousel)
    ad: ImageSlot | None = None
    reel: ReelSlot | None = None
    caption: Caption | None = None  # briefs without deliverables: one caption
    captions: dict[str, Caption] = Field(default_factory=dict)  # one per deliverable
    hashtags: list[str] = Field(min_length=MIN_HASHTAGS, max_length=MAX_HASHTAGS)
    cta: str = Field(min_length=1)
    link: str = Field(pattern=r"^https?://\S+$")  # closes the caption, after the cta


def brand_hashtag(brand_name: str) -> str:
    """The hashtag every post carries, e.g. "Branded Genius" -> "#BrandedGenius"."""
    return "#" + re.sub(r"\W", "", brand_name)


def slot_kind(name: str, slot: ImageSlot) -> Kind:
    if slot.kind is not None:
        return slot.kind
    return "carousel_slide" if slot.format == "carousel" else SLOT_KINDS[name][0]


def load_brief(
    path: Path,
    *,
    services: list[str],
    known_article_ids: set[str],
    brand_tag: str | None = None,
    checks: Callable[[ContentBrief], list[str]] | None = None,
) -> ContentBrief:
    """Read and check brief.json; raise BriefError listing every problem.

    checks: more rules (e.g. the deliverables catalog) reported together with these.
    """
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
    if checks is not None:
        problems += checks(brief)
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
        if slot_kind(name, image) not in kinds:
            problems.append(f"{name}.kind must be one of: {', '.join(kinds)}")
        if name == "ad" and image.format != "ad":
            problems.append('ad.format must be "ad" (headline, subheadline and CTA button)')
        if name == "carousel" and image.format != "carousel":
            problems.append('carousel.format must be "carousel"')
        if image.format == "carousel":
            if image.slide is None and not MIN_SLIDES <= len(image.slides) <= MAX_SLIDES:
                problems.append(
                    f"{name}.slides: a carousel has {MIN_SLIDES}-{MAX_SLIDES} slides (hook, "
                    "problem, steps or insights, example or result, call to action)"
                )
        elif image.slides:
            problems.append(f'{name}.slides is only for "format": "carousel"')
        if image.person is False and (name != "post" or brief.platform != "linkedin"):
            problems.append(
                f'{name}.person: only a LinkedIn post may leave the person out; remove "person"'
            )
        if image.stat is not None and image.source not in brief.source_article_ids:
            problems.append(
                f"{name}.source: a stat needs the ID of the research article its number comes "
                "from, and that ID must also be listed in sourceArticleIds"
            )
    if services and brief.service not in services and brief.service != INSIGHT_ONLY:
        problems.append(f"service must be one of: {'; '.join(services)} (or {INSIGHT_ONLY}: "
                        "no service named, a question as the cta)")
    for tag in brief.hashtags:
        if not re.fullmatch(r"#\w+", tag):
            problems.append(f'hashtag "{tag}" must look like #OneWord')
    if brand_tag and brand_tag.lower() not in {tag.lower() for tag in brief.hashtags}:
        problems.append(f"hashtags must include {brand_tag}")
    if brief.deliverables:
        if sorted(brief.captions) != sorted(brief.deliverables) or brief.caption is not None:
            problems.append(
                "captions: write one caption per deliverable, keyed by its name "
                f"({', '.join(brief.deliverables)}), and no single \"caption\""
            )
    elif brief.caption is None or brief.captions:
        problems.append('caption: a brief without deliverables has one "caption"')
    captions = {"caption": brief.caption} if brief.caption else {}
    captions |= {f"captions.{key}": value for key, value in brief.captions.items()}
    for where, caption in captions.items():
        if caption is not None and not caption.question.rstrip().endswith("?"):
            problems.append(f"{where}.question must be one question ending with ?")
    unknown = [aid for aid in brief.source_article_ids if aid not in known_article_ids]
    if unknown:
        problems.append(f"unknown sourceArticleIds (see research.md): {', '.join(unknown)}")
    if brief.reel is not None:
        video = VIDEO_WORKFLOWS[brief.reel.workflow]
        limit = min(MAX_REEL_SEC, video.max_duration_sec)
        total = sum(scene.duration_sec for scene in brief.reel.scenes)
        if total > limit:
            problems.append(
                f"the reel scenes add up to {total:g} s (max {limit} s for {video.workflow_id})"
            )
        types = [scene.type for scene in brief.reel.scenes if scene.image is None]
        if any(kind not in video.scene_types for kind in types):
            problems.append(
                f"{video.workflow_id} scenes are {' or '.join(video.scene_types)}, not "
                f"{', '.join(sorted(set(types) - set(video.scene_types)))}"
            )
        if video.required_scene_type not in types:
            problems.append(
                f"{video.workflow_id} needs at least one {video.required_scene_type} scene"
            )
        if any(scene.type == "avatar" and scene.image for scene in brief.reel.scenes):
            problems.append("an avatar scene cannot show a package image")
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
