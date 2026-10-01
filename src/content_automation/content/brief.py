"""brief.json: what Codex decides for one content package (headlines, scenes, reel, caption).

Keys starting with "_" (like the "_help" block in brief.template.json) are ignored.
"""

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError

from content_automation.core.files import CamelModel

Platform = Literal["instagram", "facebook", "linkedin"]
Format = Literal["post", "ad", "reel"]
ImageRef = Literal["post-1", "post-2", "ad-1"]
PLATFORMS: tuple[Platform, ...] = ("instagram", "facebook", "linkedin")
FORMATS: tuple[Format, ...] = ("post", "ad", "reel")
ASPECT_BY_PLATFORM = {"instagram": "4:5", "facebook": "4:5", "linkedin": "1:1"}
MAX_HEADLINE_WORDS = 6
MAX_REEL_SEC = 90
MAX_HASHTAGS = 10
DEFAULT_IDENTITY_SET = "identity/person_01"
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
    """A post or ad image: social_creative with the headline, logo and brand style."""

    headline: str = Field(min_length=1)
    scene: str = Field(min_length=1)  # action, setting, light, camera, mood
    with_person: bool = True


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
    identity_set: str = DEFAULT_IDENTITY_SET
    source_article_ids: list[str] = Field(default_factory=list)
    post: ImageSlot | None = None
    ad: ImageSlot | None = None
    reel: ReelSlot | None = None
    caption: str = Field(min_length=1)
    hashtags: list[str] = Field(default_factory=list)
    cta: str = Field(min_length=1)


def load_brief(
    path: Path, *, services: list[str], known_article_ids: set[str]
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
    problems = brief_problems(brief, services=services, known_article_ids=known_article_ids)
    placeholders = sorted(set(_PLACEHOLDER.findall(json.dumps(data, ensure_ascii=False))))
    if placeholders:
        problems.append(f"replace the template placeholders: {', '.join(placeholders[:5])}")
    if problems:
        raise BriefError(problems)
    return brief


def brief_problems(
    brief: ContentBrief, *, services: list[str], known_article_ids: set[str]
) -> list[str]:
    problems: list[str] = []
    for kind in FORMATS:
        slot = getattr(brief, kind)
        if kind in brief.formats and slot is None:
            problems.append(f'"{kind}" is in formats, so fill in "{kind}"')
        if kind not in brief.formats and slot is not None:
            problems.append(f'"{kind}" is filled in but not in formats; remove it or add it')
    for kind in ("post", "ad"):
        slot = getattr(brief, kind)
        if slot is not None and len(slot.headline.split()) > MAX_HEADLINE_WORDS:
            problems.append(f"{kind}.headline has more than {MAX_HEADLINE_WORDS} words")
    if services and brief.service not in services:
        problems.append(f"service must be one of: {'; '.join(services)}")
    for tag in brief.hashtags:
        if not re.fullmatch(r"#\w+", tag):
            problems.append(f'hashtag "{tag}" must look like #OneWord')
    if len(brief.hashtags) > MAX_HASHTAGS:
        problems.append(f"at most {MAX_HASHTAGS} hashtags")
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
