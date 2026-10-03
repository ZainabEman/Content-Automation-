"""`ca content start` and `ca content build`: one content package per topic.

start: collect news, rank articles for the topic, then create PACKAGES_DIR/YYYY-MM-DD_<slug>/
with research.md, brief.template.json and package.json. Codex then writes brief.json.
build: check brief.json, then make the post images (2 options, or one image per carousel
slide), the ad images (3 variants) and the reel (first frame = post-1) into images/, video/,
post.md and package.json. Each part is saved as soon as it is done; a failed or pending part
never blocks the others, and running build again redoes only what is missing.

Variety: the template suggests a post format the newest packages did not use, and scene,
wardrobe, props, decor and style images avoid what the newest packages used; the picks are
saved per part in package.json.

Person check: every image that shows the person is made as its own job, and the build stops
right after it (part status "review") until Codex has compared it with his photos and
recorded `ca job review`. A passed image lets the build go on; a failed one is made again on
the next build (after the user agreed to the cost) and is never used as slide 1 for later
slides.
"""

import json
import re
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from content_automation.ai.avatar import AvatarError
from content_automation.ai.image import ImageError, estimate_cost_usd
from content_automation.ai.video import VideoError
from content_automation.content.brief import (
    ASPECT_BY_PLATFORM,
    MAX_HASHTAGS,
    MIN_HASHTAGS,
    STORY_ASPECT,
    BriefError,
    ContentBrief,
    ImageSlot,
    brand_hashtag,
    load_brief,
    slot_kind,
)
from content_automation.content.deliverables import (
    DeliverableCatalog,
    DeliverableError,
    load_deliverables,
)
from content_automation.content.quality import carousel_problems, proof_problems
from content_automation.content.research_input import ResearchIdea, save_sources
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.core.jobs import DETAILS_FILE, Job, slugify
from content_automation.core.limits import DailyLimitError
from content_automation.references import (
    BrandProfile,
    BrandProfileError,
    CompanyProfile,
    ReferenceLibraryError,
    load_brand,
    load_company,
    load_set,
)
from content_automation.research.collectors import CollectorError
from content_automation.research.models import SourceArticle, SourcesError
from content_automation.research.run import collect, topic_digest, topic_note
from content_automation.research.store import find_article, known_article_ids, load_articles
from content_automation.workflows.design_system import (
    STEP_SEPARATOR,
    DesignSystem,
    FormatId,
    FormatSpec,
    load_design_system,
)
from content_automation.workflows.image_workflows import (
    AD_VARIANTS,
    PreparedWorkflow,
    WorkflowInputs,
    prepare_workflow,
    run_workflow,
)
from content_automation.workflows.registry import WorkflowError
from content_automation.workflows.variety import (
    DesignPicks,
    flatten,
    recent_packages,
    suggest_format,
)
from content_automation.workflows.video_job import (
    AvatarSetupError,
    agent_checklist,
    missing_avatar_ids,
    missing_providers,
    pending_lines,
    prepare_video,
    resume_video_job,
    scene_lines,
    start_video_job,
)
from content_automation.workflows.video_plan import PlanError, parse_plan

PACKAGE_FILE = "package.json"
BRIEF_FILE = "brief.json"
TEMPLATE_FILE = "brief.template.json"
RESEARCH_FILE = "research.md"
POST_FILE = "post.md"
IMAGES_DIR = "images"
VIDEO_DIR = "video"
TOPIC_DAYS = 14
TOPIC_LIMIT = 10
# Made in this order; a later part avoids the earlier ones' picks.
IMAGE_SLOTS = ("post", "carousel", "ad")
# Image options per job for briefs without deliverables (deliverables.json sets its own).
IMAGE_COUNTS = {"post": 2, "carousel": 1, "ad": AD_VARIANTS}
LABELS = {"post": "post images", "carousel": "carousel slides", "ad": "ad images", "reel": "video"}
CONTENT_FILE = "content.md"  # stage 1: angle, key message, key points, draft caption
PROOF_FILE = "proof.md"  # next to the company file: the only results content may cite
MIN_RELEVANT = 3  # fewer matching articles: Codex adds sources with web search
_IMAGE_ERRORS = (
    WorkflowError,
    ReferenceLibraryError,
    BrandProfileError,
    DailyLimitError,
    ImageError,
)

# waiting = video steps are with Codex; review = an image waits for the person check
ItemStatus = Literal["pending", "done", "waiting", "failed", "review"]
IDENTITY_PHOTOS_TO_COMPARE = 2  # primary photos shown beside an image at the person check


class PackageItem(CamelModel):
    """One part of the package (post, ad or reel)."""

    status: ItemStatus = "pending"
    job_id: str | None = None  # the newest job of this part
    job_folder: str | None = None
    job_ids: list[str] = Field(default_factory=list)  # a carousel has one job per slide
    picks: DesignPicks | None = None  # format, scene, wardrobe, props, style images used
    files: list[str] = Field(default_factory=list)  # relative to the package folder
    image_refs: list[str] = Field(default_factory=list)  # "<jobId>/<file>" per image
    cost_usd: float | None = None
    error: str | None = None
    updated_at: datetime | None = None


class ContentPackage(CamelModel):
    """PACKAGES_DIR/<folder>/package.json"""

    package_id: str
    topic: str
    deliverables: list[str] = Field(default_factory=list)  # exactly what the user named
    platform: str
    formats: list[str]
    status: str = "brief needed"
    items: dict[str, PackageItem] = Field(default_factory=dict)
    source_article_ids: list[str] = Field(default_factory=list)
    total_cost_usd: float | None = None
    reviewer: str | None = None
    note: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PackageResult:
    folder: Path
    lines: list[str] = field(default_factory=list)
    package: ContentPackage | None = None


# ----------------------------------------------------------------------------- start


def start_package(
    topic: str,
    deliverables: list[str],
    catalog: DeliverableCatalog,
    settings: Settings,
    *,
    idea: ResearchIdea | None = None,
) -> PackageResult:
    """Make the package folder with research.md (stage 1, free).

    idea: research from a file (a newsletter idea) instead of the scraper. With no
    deliverables yet, nothing can be built until `ca content set` names them.
    """
    lines: list[str] = []
    if idea is not None:
        articles = save_sources(idea, settings.research_dir, topic)
        note = None
        lines.append(
            f"Research: {len(articles)} source(s) from idea {idea.number} "
            f'("{idea.title}"); the scraper was not used.'
        )
    else:
        try:
            report, _ = collect(settings)
            lines.append(
                f"Collected news: {report.new} new articles ({report.duplicates} already saved)."
            )
        except (SourcesError, CollectorError) as error:
            lines.append(f"Collecting news failed ({error}); using the articles already saved.")
        ranked = topic_digest(settings, topic, TOPIC_DAYS, TOPIC_LIMIT)
        note = topic_note(ranked)
        if note:
            lines.append(note[0].upper() + note[1:])
        articles = [item.article for item in ranked.articles]
        if ranked.strong_matches < MIN_RELEVANT:
            lines.append(
                f"Only {ranked.strong_matches} relevant article(s): add up to 5 reputable "
                f"sources with web search, with links and dates, to {RESEARCH_FILE}."
            )

    folder = _new_folder(settings.packages_dir, f"{date.today():%Y-%m-%d}_{slugify(topic)}")
    atomic_write_text(folder / RESEARCH_FILE, _research_markdown(topic, articles, note))
    package = ContentPackage(
        package_id=folder.name,
        topic=topic,
        platform=catalog.platform_for([]),
        formats=[],
        source_article_ids=[article.article_id for article in articles[:3]],
    )
    _save(folder, package)
    lines.append(f"Package folder: {folder}")
    if deliverables:
        lines += _apply_deliverables(folder, package, deliverables, catalog, settings, articles)
    else:
        lines.append(
            f"Next (Codex): write {CONTENT_FILE} (angle, key message, 3-5 key points, draft "
            'caption, source link), then ask "What should I make?". Nothing is built until '
            f'the user names deliverables: uv run ca content set "{folder}" --deliverables '
            '"<names>"'
        )
    return PackageResult(folder, lines, package)


def set_deliverables(
    folder: Path, deliverables: list[str], catalog: DeliverableCatalog, settings: Settings
) -> PackageResult:
    """Name the deliverables of an existing package and write its brief template."""
    path = folder / PACKAGE_FILE
    if not path.is_file():
        raise DeliverableError(f"No {PACKAGE_FILE} in {folder}: start the package first.")
    package = ContentPackage.model_validate_json(path.read_text(encoding="utf-8"))
    articles = [
        found
        for article_id in package.source_article_ids
        if (found := find_article(settings.research_dir, article_id)) is not None
    ]
    lines = _apply_deliverables(folder, package, deliverables, catalog, settings, articles)
    if (folder / BRIEF_FILE).is_file():
        lines.append(f"{BRIEF_FILE} already exists: make it match the new {TEMPLATE_FILE}.")
    return PackageResult(folder, lines, package)


def _apply_deliverables(
    folder: Path,
    package: ContentPackage,
    deliverables: list[str],
    catalog: DeliverableCatalog,
    settings: Settings,
    articles: list[SourceArticle],
) -> list[str]:
    items = [catalog.deliverables[key] for key in deliverables]
    lines = [
        "Deliverables: "
        + "; ".join(f"{key} ({item.label})" for key, item in zip(deliverables, items, strict=True))
    ]
    brand = _brand(settings)
    company = load_company(settings.company_file)
    try:
        system: DesignSystem | None = load_design_system(settings.design_system_file)
    except WorkflowError as error:
        system = None
        lines.append(f"Design help left out of the template: {error}")
    post = next((item for item in items if item.part == "post"), None)
    suggested: FormatId | None = post.format if post is not None else None
    if system is not None and post is not None and suggested is None:
        # The next format in the rotation that the newest packages did not use.
        suggested = suggest_format(
            system, recent_packages(settings.packages_dir, exclude=folder), allowed=post.formats
        )
        lines.append(f"Suggested post format: {suggested} (different from the last packages).")
    template = _brief_template(
        package.topic,
        deliverables,
        catalog,
        articles,
        brand,
        company,
        system,
        settings.default_identity_set,
        suggested,
    )
    atomic_write_text(
        folder / TEMPLATE_FILE, json.dumps(template, indent=2, ensure_ascii=False) + "\n"
    )
    package.deliverables = deliverables
    package.platform = catalog.platform_for(deliverables)
    package.formats = [item.brief_format for item in items]
    if post is not None and suggested is not None and "post" not in package.items:
        # Saved now, so the next package already rotates to another format.
        package.items["post"] = PackageItem(picks=DesignPicks(format=suggested))
    _save(folder, package)
    lines += [
        f"Next (Codex): write {BRIEF_FILE} for only these deliverables: start from "
        f"{TEMPLATE_FILE} (and {CONTENT_FILE} if it exists) and replace every <...> (English; "
        "use docs/company/services.md and the brand and design rules in _help; no invented "
        "results, statistics, prices or client names; one caption per deliverable).",
        f'Then run: uv run ca content build "{folder}" --dry-run',
    ]
    return lines


def _new_folder(parent: Path, name: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while True:
        candidate = parent / (name if suffix == 1 else f"{name}-{suffix}")
        try:
            candidate.mkdir()
        except FileExistsError:
            suffix += 1
            continue
        return candidate


def _brand(settings: Settings) -> BrandProfile | None:
    try:
        return load_brand(settings.references_dir)
    except BrandProfileError:
        return None


def service_names(brand: BrandProfile | None, company: CompanyProfile | None) -> list[str]:
    if brand is not None and brand.services:
        return list(brand.services)
    if company is None:
        return []
    names = []
    for line in company.services:
        name = line.split(":", 1)[0].replace("(core)", "").strip().rstrip(".")
        names.append(name.removesuffix(" for campaigns"))
    return names


def _research_markdown(topic: str, articles: list[SourceArticle], note: str | None) -> str:
    lines = [
        f"# Research: {topic}",
        "",
        f"Made {date.today():%Y-%m-%d} from articles of the last {TOPIC_DAYS} days, "
        "best match first.",
        "",
    ]
    if note:
        lines += [f"> {note}", ""]
    if not articles:
        lines.append("No articles found. Run `uv run ca research collect` and start again.")
    for number, article in enumerate(articles, start=1):
        summary = " ".join((article.summary or article.content).split())[:300]
        lines += [
            f"{number}. **{article.title}**: {article.source}, "
            f"{article.published_at.astimezone(UTC):%Y-%m-%d}",
            f"   - Link: {article.url}",
            f"   - ID: `{article.article_id}`",
            f"   - {summary}",
            "",
        ]
    return "\n".join(lines).rstrip() + "\n"


def _design_help(system: DesignSystem, suggested: FormatId | None) -> dict[str, Any]:
    """The design system's choices, for the "_help" block of the brief template."""

    def person(key: str, spec: FormatSpec) -> str:
        if spec.person != "layout":
            return "always the man" if spec.person == "always" else "no person"
        if key == "carousel":
            return "the man on slide 1 only"
        shown = [name for name in spec.layouts if system.layouts[name].person]
        others = [name for name in spec.layouts if name not in shown]
        rest = f"with layout {', '.join(others)}" if others else "without a layout"
        return f"the man with layout {', '.join(shown)}; no person {rest}"

    return {
        "choose": (
            "Format: keep the suggested post format (it differs from the last packages) unless "
            "it does not fit the research; then pick another from formats and fill its "
            "required fields. A stat needs a number that is written in a research article "
            "(its ID goes in source); never invent one. Layout: A for a product or feature; "
            "B or C for trust (alternate B and C between posts); D for pain vs gain. Headline "
            "(format ad): one formula from headlineFormulas. Never describe the man's face."
        ),
        "suggestedFormat": suggested,
        "formats": {
            key: {
                "use": spec.use,
                "required": [*spec.required, *(["source"] if key == "stat" else [])],
                "optional": spec.optional,
                "person": person(key, spec),
                "headlineMaxWords": spec.headline_max_words,
            }
            for key, spec in system.formats.items()
        },
        "layouts": {
            key: f"{layout.use}: {layout.description}" for key, layout in system.layouts.items()
        },
        "pools": {
            name: {key: entry.description for key, entry in pool.items()}
            for name, pool in (
                ("scene", system.pools.scenes),
                ("wardrobe", system.pools.wardrobe),
                ("props", system.pools.props),
                ("pose", system.pools.poses),
            )
        },
        "headlineFormulas": system.headline_formulas,
        "ctaIcons": {
            key: ", ".join(icon.actions)
            for key, icon in system.elements.cta_button.icons.items()
        },
        "rules": {"post": system.rules.organic, "ad": system.rules.ad},
        "optional": (
            'Per image you may add "scene", "wardrobe", "props" or "pose": an ID from pools or '
            "your own words. Left out, they are picked so that they differ from the last "
            'packages. Format ad also takes "ctaIcon" (arrow, calendar or play; default: '
            'chosen from the cta label) and "icons" (3-4 labels of 1-2 words). In post, '
            '"kind": "story" makes it 9:16.'
        ),
    }


def _carousel_slides(count: int, cta: str) -> list[dict[str, Any]]:
    """Slide 1 the hook (with the man), then tips, the last slide with the call to action."""
    how = "<the concrete how or an example, 1-2 short lines>"
    shows: list[dict[str, Any]] = [
        {"chat": [
            {"from": "customer", "text": "<a short customer question>"},
            {"from": "bot", "text": "<the automated answer>"},
        ]},
        {"diagram": ["<step 1>", "<step 2>", "<step 3>"]},
        {"visual": "<what its icon shows, or replace with chat/diagram>"},
    ]
    tips = [
        {"headline": f"<tip {number}: its own idea>", "subheadline": how,
         **shows[(number - 1) % len(shows)]}
        for number in range(1, count - 1)
    ]
    return [
        {"headline": "<the problem or the promise for this audience, at most 8 words>",
         "subheadline": "<one short line>"},
        *tips,
        {"headline": "<the call to action>", "cta": cta},
    ]


def _slot_template(
    name: str, format_id: FormatId, slides: int = 4, last_cta: str = "<button label>"
) -> dict[str, Any]:
    """The fields the format needs, as placeholders."""
    highlight = ["<1-2 words from the headline>"]
    audience = "<FOR WHOM, from the topic, e.g. FOR DENTAL PRACTICES>"
    cta = (
        "<button label naming the one offer (see _help.design.rules.ad)>"
        if name == "ad"
        else "<soft button label (see _help.design.rules.post)>"
    )
    fields: dict[FormatId, dict[str, Any]] = {
        "ad": {
            "layout": "<A, B, C or D (see _help.design.layouts)>",
            "headline": "<at most 6 words, built from a formula in _help.design.headlineFormulas>",
            "highlight": highlight,
            "subheadline": "<one short sentence>",
            "subHighlight": "<one word from the subheadline>",
            "cta": cta,
            "visual": "<layout A: the system visual on the right; otherwise delete this line>",
        },
        "statement": {
            "audienceLine": audience,
            "headline": "<one bold sentence, at most 12 words>",
            "highlight": highlight,
        },
        "stat": {
            "audienceLine": audience,
            "stat": "<the one big number, exactly as the article writes it, e.g. 73%>",
            "source": "<the ID of that article (research.md); list it in sourceArticleIds too>",
            "sourceName": "<the publisher, short, as the article names it, e.g. Zillow>",
            "subheadline": "<one context line: what the number measures>",
        },
        "news": {
            "headline": "<the news in one line, at most 14 words>",
            "subheadline": "<what it means for our audience, in one sentence>",
            "source": "<the ID of the article (research.md)>",
            "layout": "<B or C to show the man; otherwise delete this line>",
        },
        "carousel": {"audienceLine": audience, "slides": _carousel_slides(slides, last_cta)},
        "person_photo": {"headline": "<0-3 words, or delete this line>"},
        "checklist": {
            "audienceLine": audience,
            "headline": "<short title, at most 6 words>",
            "steps": ["<step 1>", "<step 2>", "<step 3>"],
        },
    }
    return {"format": format_id, **fields[format_id]}


def _platform_cta(
    system: DesignSystem | None, platform: str | None, company: CompanyProfile | None
) -> str:
    """The placeholder for a carousel's last CTA: what works on the platform, with the offer."""
    rule = system.cta_rules.get(platform or "") if system else None
    offer = company.offer if company else ""
    offer_text = f'the offer "{offer}"' if offer else "the offer (ask: services.md has none)"
    if rule is None:
        return f"<a short call to action with {offer_text}>"
    return f"<{rule.use.split('.')[0]}, with {offer_text}>"


def _first_frame(formats: Sequence[str]) -> str | None:
    """The package image a video starts from: the post, else the carousel hook, else the ad."""
    for kind in ("post", "carousel", "ad"):
        if kind in formats:
            return f"{kind}-1"
    return None


def _video_template(workflow: str, first_frame: str | None) -> dict[str, Any]:
    """reel_short and ugc_ad: generated clips; podcast_clip: the avatar speaks the script."""
    video: dict[str, Any] = {
        "workflow": workflow,
        "hook": "<the first sentence that stops the scroll>",
        "script": "<what the video tells, in 2-4 sentences>",
    }
    if workflow == "podcast_clip":
        video["scenes"] = [
            {
                "type": "avatar",
                "prompt": "<the exact words the avatar says, about 2.5 words per second>",
                "durationSec": 12,
                "onScreenText": "<at most 6 words>",
            },
            {"type": "video", "prompt": "<b-roll shot>", "durationSec": 5},
        ]
        return video
    if first_frame:
        video["firstFrame"] = first_frame
    video["scenes"] = [
        {
            "prompt": "<shot 1: continues from the first frame>" if first_frame else "<shot 1>",
            "durationSec": 5,
            "onScreenText": "<at most 6 words>",
        },
        {"prompt": "<shot 2>", "durationSec": 5, "onScreenText": "<short call to action>"},
    ]
    return video


def _brief_template(
    topic: str,
    deliverables: list[str],
    catalog: DeliverableCatalog,
    articles: list[SourceArticle],
    brand: BrandProfile | None,
    company: CompanyProfile | None,
    system: DesignSystem | None,
    identity_set: str,
    suggested: FormatId | None,
) -> dict[str, Any]:
    brand_tag = brand_hashtag(brand.brand_name) if brand else "<#BrandName>"
    chosen = {key: catalog.deliverables[key] for key in deliverables}
    by_part = {item.part: item for item in chosen.values()}
    formats = [item.brief_format for item in chosen.values()]
    template: dict[str, Any] = {
        "_help": {
            "howTo": (
                f"Save a copy as {BRIEF_FILE} in this folder and replace every <...>. English "
                "only. Use docs/company/services.md and the brand and design rules below. "
                "Never invent results, statistics, prices or client names. Keep deliverables "
                "and formats unchanged: build only what the user named. This _help block is "
                "ignored."
            ),
            "deliverables": {key: item.label for key, item in chosen.items()},
            "services": service_names(brand, company),
            "brandRules": {
                "tone": brand.tone if brand else "",
                "language": "English",
                "avoid": brand.dont if brand else [],
                "contentRules": company.content_rules if company else "",
            },
            "design": _design_help(system, suggested) if system else {},
            "formats": {
                "post": "one designed image in the post's format",
                "carousel": "one image per slide: hook (with the man), tips, call to action",
                "ad": f"{AD_VARIANTS} variants of one ad: one message, one offer, one CTA",
                "reel": (
                    "9:16 video (workflow from the deliverable); each scene at most 15 s; "
                    "reel_short and podcast_clip at most 90 s, ugc_ad at most 60 s; scene 1 "
                    'starts from firstFrame; a scene with "image": "post-1" shows that picture; '
                    'podcast_clip scenes are "avatar" (the exact words) or "video" (b-roll)'
                ),
            },
            "caption": (
                "hook = line 1; lines = 2-3 short lines, the problem then the solution; "
                "question = one question that invites comments; cta and link close the "
                f"caption; {MIN_HASHTAGS}-{MAX_HASHTAGS} English hashtags including {brand_tag}."
            ),
            "topArticles": [f"{a.article_id} | {a.source} | {a.title}" for a in articles],
        },
        "topic": topic,
        "deliverables": deliverables,
        "platform": catalog.platform_for(deliverables),
        "formats": formats,
        "service": "<one of the services in _help>",
        "audience": brand.audience if brand and brand.audience else "<who this is for>",
        "objective": "<what this content should achieve>",
        "keyPoints": ["<key point 1>", "<key point 2>", "<key point 3>"],
        "identitySet": identity_set,
        "sourceArticleIds": [a.article_id for a in articles[:3]],
    }
    post = by_part.get("post")
    if post is not None:
        template["post"] = _slot_template("post", suggested or post.format or "statement")
    carousel = by_part.get("carousel")
    if carousel is not None:
        template["carousel"] = _slot_template(
            "carousel",
            "carousel",
            slides=carousel.slides or 5,
            last_cta=_platform_cta(system, carousel.platform, company),
        )
    if "ad" in by_part:
        template["ad"] = _slot_template("ad", "ad")
    video = by_part.get("video")
    if video is not None and video.workflow is not None:
        first = _first_frame(formats)
        template["reel"] = _video_template(video.workflow, first)
    template["captions"] = {
        key: {
            "hook": f"<line 1: the hook for the {item.label.split(':')[0]}>",
            "lines": ["<short line: the problem>", "<short line: the solution>"],
            "question": "<one question that invites comments?>",
        }
        for key, item in chosen.items()
    }
    template["cta"] = "<one clear call to action>"
    website = company.website if company else ""
    template["link"] = website or (
        "<https://... the page to open; ask the user, never guess (to pre-fill it, add a "
        '"Website: https://..." line to docs/company/services.md)>'
    )
    template["hashtags"] = [brand_tag, "<#TopicTag>", "<#TopicTag>"]
    return template


# ----------------------------------------------------------------------------- build


def build_package(folder: Path, settings: Settings, *, dry_run: bool) -> PackageResult:
    """Raises BriefError when brief.json is missing or invalid (nothing is made)."""
    saved_package = folder / PACKAGE_FILE
    if saved_package.is_file() and not (folder / BRIEF_FILE).is_file():
        package = ContentPackage.model_validate_json(saved_package.read_text(encoding="utf-8"))
        if not package.deliverables and not package.formats:
            return PackageResult(folder, [
                "No deliverables on this package yet: nothing is built. Ask the user what to "
                f'make, then run: uv run ca content set "{folder}" --deliverables "<names>"'
            ], package)
    brand = _brand(settings)
    company = load_company(settings.company_file)
    known = known_article_ids(settings.research_dir)
    brief = load_brief(
        folder / BRIEF_FILE,
        services=service_names(brand, company),
        known_article_ids=known,
        brand_tag=brand_hashtag(brand.brand_name) if brand else None,
        checks=lambda checked: _deliverable_problems(checked, settings),
    )
    package = _load(folder, brief)
    plans = _plan_images(brief, package, folder, settings, _image_counts(brief, settings))
    problems = [
        f"{name}: {_in_brief_words(str(plan.error))}"
        for name, plan in plans.items()
        if isinstance(plan.error, WorkflowError)
    ]
    if problems:  # format rules, a stat without a research source, ...: nothing is made
        raise BriefError(problems)
    if dry_run:
        lines = _dry_run_lines(folder, brief, package, plans, settings)
        return PackageResult(folder, lines, package)

    lines = []
    check: list[str] = []
    for kind, plan in plans.items():
        package.items[kind], check = _make_images(
            kind, plan, folder, settings, package.items.get(kind)
        )
        lines.append(_item_line(kind, package.items[kind]))
        _save(folder, package)
        if check:  # an image with the person waits for the person check: build nothing more
            lines += check
            break
    if brief.reel is not None and not check:
        item = package.items.get("reel")
        if item is None or item.status != "done":
            package.items["reel"], extra = _make_reel(brief, package, folder, settings)
            lines.append(_item_line("reel", package.items["reel"]))
            lines += extra
    package.status = _status(brief, package)
    costs = [item.cost_usd for item in package.items.values() if item.cost_usd is not None]
    package.total_cost_usd = round(sum(costs), 6) if costs else None
    saved = load_articles(settings.research_dir, datetime.min.replace(tzinfo=UTC))
    articles = {article.article_id: article for article in saved}
    atomic_write_text(folder / POST_FILE, _post_markdown(brief, package, articles))
    _save(folder, package)
    return PackageResult(folder, lines, package)


def _image_counts(brief: ContentBrief, settings: Settings) -> dict[str, int]:
    """Image options per job and part: from the deliverables, else the old defaults."""
    counts = dict(IMAGE_COUNTS)
    if brief.deliverables:
        try:
            catalog = load_deliverables(settings.deliverables_file)
        except DeliverableError:
            return counts  # reported by the brief checks
        for part in counts:
            images = catalog.images_for(brief.deliverables, part)
            if images is not None:
                counts[part] = images
    return counts


def _deliverable_problems(brief: ContentBrief, settings: Settings) -> list[str]:
    problems = _quality_problems(brief, settings)
    if not brief.deliverables:
        return problems  # a brief from before deliverables: its formats decide
    try:
        return load_deliverables(settings.deliverables_file).problems(brief) + problems
    except DeliverableError as error:
        return [str(error), *problems]


def _quality_problems(brief: ContentBrief, settings: Settings) -> list[str]:
    """A real hook, distinct tips with a how, a platform CTA, and proof only from proof.md."""
    proof_file = settings.company_file.parent / PROOF_FILE
    proof = proof_file.read_text(encoding="utf-8") if proof_file.is_file() else ""
    research = [
        f"{found.title} {found.summary} {found.content}"
        for article_id in brief.source_article_ids
        if (found := find_article(settings.research_dir, article_id)) is not None
    ]
    problems = proof_problems(brief, proof, research)
    platforms: dict[str, str] = {}
    if brief.deliverables:
        try:
            catalog = load_deliverables(settings.deliverables_file)
            for key in brief.deliverables:
                item = catalog.deliverables.get(key)
                if item is not None and item.platform:
                    platforms[item.brief_format] = item.platform
        except DeliverableError:
            pass  # reported by the deliverable checks
    try:
        system = load_design_system(settings.design_system_file)
        problems = carousel_problems(brief, system, platforms) + problems
    except WorkflowError as error:
        problems.append(str(error))
    return problems


def _in_brief_words(message: str) -> str:
    """Name brief.json fields instead of command-line flags: --sub-highlight -> subHighlight."""

    def field_name(match: re.Match[str]) -> str:
        first, *rest = match.group(1).split("-")
        return first + "".join(part.capitalize() for part in rest)

    return re.sub(r"--([a-z]+(?:-[a-z]+)*)", field_name, message)


def _slot_inputs(
    name: str,
    slot: ImageSlot,
    brief: ContentBrief,
    folder: Path,
    history: list[DesignPicks],
    count: int,
) -> list[WorkflowInputs]:
    """One image job per part; a carousel has one job per slide, all with the same look."""
    design_kind = slot_kind(name, slot)
    aspect = STORY_ASPECT if design_kind == "story" else ASPECT_BY_PLATFORM[brief.platform]
    request = f"{brief.topic}: {name} for {brief.platform} (package {folder.name})"
    base = WorkflowInputs(
        # Used only by designs that show the person.
        fallback_identity_set=brief.identity_set,
        format=slot.format,
        kind=design_kind,
        layout=slot.layout,
        pose=slot.pose,
        headline=slot.headline,
        highlight=", ".join(slot.highlight) or None,
        subheadline=slot.subheadline,
        sub_highlight=slot.sub_highlight,
        cta=slot.cta,
        cta_icon=slot.cta_icon,
        icons=", ".join(slot.icons) or None,
        visual=slot.visual,
        stat=slot.stat,
        source=slot.source,
        source_name=slot.source_name,
        steps=STEP_SEPARATOR.join(slot.steps) or None,
        audience_line=slot.audience_line,
        slide=slot.slide,
        slide_role=slot.slide_role,
        scene=slot.scene,
        wardrobe=slot.wardrobe,
        props=slot.props,
        logo=True,
        aspect_ratio=aspect,
        count=count,
        request=request,
        history=history,
        context=" ".join([brief.topic, brief.audience, brief.objective, *brief.key_points]),
    )
    if not slot.slides:
        return [base]
    total = len(slot.slides)
    return [
        replace(
            base,
            # Only the hook slide (slide 1) shows the man.
            layout=slot.layout if number == 1 else None,
            audience_line=slot.audience_line if number == 1 else None,
            pose=slot.pose if number == 1 else None,
            wardrobe=slot.wardrobe if number == 1 else None,
            headline=slide.headline,
            highlight=", ".join(slide.highlight) or None,
            subheadline=slide.subheadline,
            sub_highlight=slide.sub_highlight,
            visual=slide.visual,
            chat="|".join(f"{bubble.speaker}: {bubble.text}" for bubble in slide.chat) or None,
            diagram=STEP_SEPARATOR.join(slide.diagram) or None,
            cta=slide.cta,
            cta_icon=slide.cta_icon,
            slide=f"{number}/{total}",
            slide_role=None,
            count=1,
            request=f"{request}, slide {number}/{total}",
        )
        for number, slide in enumerate(slot.slides, start=1)
    ]


@dataclass
class _ImagePlan:
    """The image jobs of one part that is still to be made, checked without making anything."""

    slot: ImageSlot
    jobs: list[WorkflowInputs]
    prepared: list[PreparedWorkflow] = field(default_factory=list)
    error: Exception | None = None


def _plan_images(
    brief: ContentBrief,
    package: ContentPackage,
    folder: Path,
    settings: Settings,
    counts: dict[str, int],
) -> dict[str, _ImagePlan]:
    """Check the image parts that are not done yet.

    Each part avoids the picks of the parts before it and of the newest other packages, so
    the dry run and the build choose the same scene, wardrobe, props and style images.
    """
    others = flatten(recent_packages(settings.packages_dir, exclude=folder))
    picks = {name: item.picks for name, item in package.items.items() if item.picks is not None}
    plans: dict[str, _ImagePlan] = {}
    for position, name in enumerate(IMAGE_SLOTS):
        slot: ImageSlot | None = getattr(brief, name)
        item = package.items.get(name)
        if slot is None or (item is not None and item.status == "done"):
            continue
        earlier = [picks[part] for part in IMAGE_SLOTS[:position] if part in picks]
        jobs = _slot_inputs(name, slot, brief, folder, earlier + others, counts[name])
        plan = _ImagePlan(slot, jobs)
        try:
            plan.prepared = [
                prepare_workflow("social_creative", inputs, settings) for inputs in plan.jobs
            ]
            if len(jobs) == 1 and jobs[0].count > 1 and plan.prepared[0].person_shown:
                # Each image with the person gets its own job, so each one is checked
                # before the next is made (same inputs, so the same look).
                plan.jobs = [replace(jobs[0], count=1) for _ in range(jobs[0].count)]
                one = prepare_workflow("social_creative", plan.jobs[0], settings)
                plan.prepared = [one] * len(plan.jobs)
        except _IMAGE_ERRORS as error:
            plan.error = error
        if plan.prepared and plan.prepared[0].picks is not None:
            picks[name] = plan.prepared[0].picks
        plans[name] = plan
    return plans


def _last_image(item: PackageItem) -> tuple[Job, str] | None:
    """The newest image of a part and its job (the one a person check is about)."""
    if not item.image_refs or not item.job_folder:
        return None
    job_id, _, name = item.image_refs[-1].partition("/")
    try:
        job = Job.load(Path(item.job_folder) / DETAILS_FILE)
    except (OSError, ValueError):
        return None
    return (job, name) if job.job_id == job_id else None


def _review_result(item: PackageItem) -> str | None:
    """"pass", "fail" or None (not checked yet) for a part waiting at the person check."""
    found = _last_image(item)
    if found is None:
        return None
    review = found[0].review(found[1])
    return review.result if review is not None else None


def _jobs_done(plan: _ImagePlan, previous: PackageItem | None) -> int:
    """Image jobs of a part that an earlier build already made (and that may be kept).

    A part stopped at the person check keeps its images; one that failed the check is
    made again. A part that failed half-way keeps the images it has.
    """
    if previous is None or previous.status not in ("failed", "review") or not plan.jobs:
        return 0
    per_job = plan.jobs[0].count
    done = len(previous.image_refs) // per_job
    if previous.status == "review" and _review_result(previous) == "fail":
        done -= 1
    return max(0, done)


def _identity_photos(job: Job, settings: Settings) -> list[Path]:
    set_id = str(job.inputs.get("identitySet") or settings.default_identity_set)
    try:
        ref_set = load_set(set_id, settings.references_dir)
    except ReferenceLibraryError:
        return []
    photos = ref_set.primary_assets or ref_set.ok_assets
    return [(ref_set.folder / a.file).resolve() for a in photos[:IDENTITY_PHOTOS_TO_COMPARE]]


def _check_lines(
    kind: str, item: PackageItem, folder: Path, settings: Settings, *, waiting: bool = False
) -> list[str]:
    """What Codex must do at the person check: compare, record, ask before regenerating."""
    found = _last_image(item)
    if found is None:
        return [f"{LABELS[kind]}: person check pending, but its job record is missing."]
    job, name = found
    image = (folder / item.files[-1]).resolve()
    cost = f"${job.est_cost_usd:.3f}" if job.est_cost_usd else "the price of 1 image"
    head = (
        f"PERSON CHECK (still not recorded) for {item.files[-1]}"
        if waiting
        else f"PERSON CHECK: stop here. {item.files[-1]} shows the person."
    )
    lines = [
        head,
        f"  View it: {image}",
        "  beside his primary photos: "
        + ", ".join(str(path) for path in _identity_photos(job, settings)),
        "  Same person (hair, build, facial hair, age)? Record the result:",
        f'    uv run ca job review "{job.folder}" --image {name} --pass',
        f'    uv run ca job review "{job.folder}" --image {name} --fail "<what differs>"',
        "  If it differs: stop, show the user the image and ask whether to make it again "
        f"(about {cost}, 1 image via {settings.image_provider}). Only after a yes:",
        f'    uv run ca content build "{folder}"   (makes this image again)',
        f'  If it passes: uv run ca content build "{folder}"   (continues)',
    ]
    return lines


def _make_images(
    kind: str, plan: _ImagePlan, folder: Path, settings: Settings, previous: PackageItem | None
) -> tuple[PackageItem, list[str]]:
    """Make the part's missing images; the lines are a person check that stops the build."""
    now = datetime.now(UTC)
    if previous is not None and previous.status == "review":
        result = _review_result(previous)
        if result is None:  # not checked yet: make nothing
            return previous, _check_lines(kind, previous, folder, settings, waiting=True)
    done = _jobs_done(plan, previous)
    if done and previous is not None:  # keep the finished images; make only the missing ones
        item = previous.model_copy(update={"error": None, "updated_at": now}, deep=True)
        per_job = plan.jobs[0].count
        for stale in item.files[done * per_job:]:  # an image that failed the person check
            (folder / stale).unlink(missing_ok=True)
        item.files = item.files[: done * per_job]
        item.image_refs = item.image_refs[: done * per_job]
    else:
        item = PackageItem(status="failed", updated_at=now)
    for number, inputs in enumerate(plan.jobs, start=1):
        if number <= done:
            continue
        if number > 1 and plan.slot.format == "carousel" and item.image_refs:
            # Later carousel slides attach slide 1's image (it passed the person check): one
            # scene, decor and palette.
            inputs = replace(inputs, first_slide=item.image_refs[0])
        try:
            job = run_workflow("social_creative", inputs, settings)
        except _IMAGE_ERRORS as error:
            item.status, item.error = "failed", str(error)
            return item, []
        item.job_id, item.job_folder = job.job_id, str(job.folder)
        item.job_ids.append(job.job_id)
        if job.status != "completed":
            item.status, item.error = "failed", job.error
            item.cost_usd = _add_cost(item.cost_usd, job.actual_cost_usd)
            return item, []
        (folder / IMAGES_DIR).mkdir(exist_ok=True)
        for index, name in enumerate(job.outputs, start=1):
            position = number if len(plan.jobs) > 1 else index  # one file per slide or variant
            target = folder / IMAGES_DIR / f"{kind}-{position}{Path(name).suffix}"
            shutil.copyfile(job.folder / name, target)
            item.files.append(f"{IMAGES_DIR}/{target.name}")
            item.image_refs.append(f"{job.job_id}/{name}")
        cost = job.actual_cost_usd if job.actual_cost_usd is not None else job.est_cost_usd
        item.cost_usd = _add_cost(item.cost_usd, cost)
        if item.picks is None:
            item.picks = DesignPicks.from_recorded(job.inputs, job.style_asset_ids)
        if job.inputs.get("personShown") is True:
            item.status = "review"
            item.error = f"person check pending: {item.files[-1]}"
            return item, _check_lines(kind, item, folder, settings)
    item.status, item.error = "done", None
    return item, []


def _add_cost(total: float | None, cost: float | None) -> float | None:
    if cost is None:
        return total
    return round((total or 0.0) + cost, 6)


def _make_reel(
    brief: ContentBrief, package: ContentPackage, folder: Path, settings: Settings
) -> tuple[PackageItem, list[str]]:
    now = datetime.now(UTC)
    previous = package.items.get("reel")
    job: Job | None = None
    if previous is not None and previous.status == "waiting" and previous.job_folder:
        try:
            job = resume_video_job(Job.load(Path(previous.job_folder) / DETAILS_FILE), settings)
        except (OSError, ValueError, VideoError, AvatarError) as error:
            failed = PackageItem(
                status="failed", error=f"cannot resume the video: {error}", updated_at=now
            )
            return failed, []
    if job is None:
        assert brief.reel is not None
        plan = _reel_plan(brief, package)
        if isinstance(plan, str):
            return PackageItem(status="pending", error=plan, updated_at=now), []
        plan_file = folder / VIDEO_DIR / "plan.json"
        plan_file.parent.mkdir(exist_ok=True)
        atomic_write_text(plan_file, json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
        try:
            # A package never takes placeholder clips: without a real provider the job is
            # created and waits ("draft — video pending").
            job = start_video_job(
                plan_file,
                settings,
                request=f"{brief.topic}: {brief.reel.workflow} (package {folder.name})",
                real_only=True,
            )
        except AvatarSetupError as error:  # no job was created, so nothing is failed
            pending = PackageItem(
                status="pending", error="HeyGen avatar or voice ID not set", updated_at=now
            )
            return pending, [
                "Video not started (no job created): set these first, then build again:",
                *(f"  - {line}" for line in error.problems),
            ]
        except (PlanError, VideoError, AvatarError) as error:
            return PackageItem(status="failed", error=str(error), updated_at=now), []
    return _reel_item(job, folder, settings)


def _reel_plan(
    brief: ContentBrief, package: ContentPackage, *, check: bool = False
) -> dict[str, Any] | str:
    """The video plan for `ca video`; a string explains what is still missing.

    check: for a dry run, before the package images exist: no start images, and scenes that
    show a package image count as video scenes.
    """
    assert brief.reel is not None
    reel = brief.reel

    def image_ref(name: str) -> str | None:
        kind, number = name.split("-")
        item = package.items.get(kind)
        if item is None or item.status != "done" or len(item.image_refs) < int(number):
            return None
        return item.image_refs[int(number) - 1]

    first = reel.first_frame or _first_frame(brief.formats)
    scenes: list[dict[str, Any]] = []
    for number, scene in enumerate(reel.scenes, start=1):
        entry: dict[str, Any] = {
            "n": number,
            "type": scene.type,
            "prompt": scene.prompt,
            "durationSec": scene.duration_sec,
        }
        if scene.on_screen_text:
            entry["onScreenText"] = scene.on_screen_text
        # Avatar scenes take no start image; the first frame starts the first video scene.
        wanted = scene.image or (first if number == 1 and scene.type == "video" else None)
        if wanted and not check:
            ref = image_ref(wanted)
            if ref is None:
                return f"waiting for {wanted} (its image is not made yet); run build again"
            entry["startImageAssetId"] = ref
            if scene.image:
                entry["type"] = "image"
        scenes.append(entry)
    return {
        "workflowId": reel.workflow,
        "platform": f"{brief.platform}_{reel.workflow}",
        "durationSec": sum(scene.duration_sec for scene in reel.scenes),
        "hook": reel.hook,
        "script": reel.script,
        "cta": brief.cta,
        "scenes": scenes,
    }


def _reel_item(job: Job, folder: Path, settings: Settings) -> tuple[PackageItem, list[str]]:
    now = datetime.now(UTC)
    if job.status == "completed":
        target_dir = folder / VIDEO_DIR
        target_dir.mkdir(exist_ok=True)
        files = []
        for name in job.outputs:  # final.mp4 (+ captions.srt)
            shutil.copyfile(job.folder / name, target_dir / name)
            files.append(f"{VIDEO_DIR}/{name}")
        credits = [step.credits_used for step in job.steps if step.credits_used is not None]
        item = PackageItem(
            status="done",
            job_id=job.job_id,
            job_folder=str(job.folder),
            files=files,
            updated_at=now,
        )
        return item, ([f"Video credits used: {sum(credits):g}"] if credits else [])
    if job.status in ("awaiting_agent", "processing"):
        held = pending_lines(job, settings)  # no real video provider yet
        item = PackageItem(
            status="waiting",
            job_id=job.job_id,
            job_folder=str(job.folder),
            error="waiting for a real video provider" if held else "video steps are with Codex",
            updated_at=now,
        )
        steps = held or agent_checklist(job)
        return item, steps + [f'  Then (for this package): uv run ca content build "{folder}"']
    item = PackageItem(
        status="failed",
        job_id=job.job_id,
        job_folder=str(job.folder),
        error=job.error or job.status,
        updated_at=now,
    )
    return item, []


def _status(brief: ContentBrief, package: ContentPackage) -> str:
    missing = []
    for kind in brief.formats:
        item = package.items.get(kind)
        state = item.status if item else "pending"
        if state in ("pending", "waiting"):
            missing.append(f"{LABELS[kind]} pending")
        elif state == "review":
            missing.append(f"{LABELS[kind]}: person check pending")
        elif state == "failed":
            missing.append(f"{LABELS[kind]} failed")
    return "draft" if not missing else "draft — " + ", ".join(missing)


def _item_line(kind: str, item: PackageItem) -> str:
    if item.status == "done":
        cost = f" (${item.cost_usd:.4f})" if item.cost_usd else ""
        return f"{LABELS[kind]}: done{cost}: {', '.join(item.files)}"
    return f"{LABELS[kind]}: {item.status}" + (f": {item.error}" if item.error else "")


def _dry_run_lines(
    folder: Path,
    brief: ContentBrief,
    package: ContentPackage,
    plans: dict[str, _ImagePlan],
    settings: Settings,
) -> list[str]:
    lines = [
        "DRY RUN: nothing is made and nothing is spent.",
        f"Package: {folder}",
        f"Topic: {brief.topic} | platform: {brief.platform} | "
        f"formats: {', '.join(brief.formats)}",
    ]
    total = 0.0
    names = _part_names(brief, settings)
    for kind in IMAGE_SLOTS:
        item = package.items.get(kind)
        plan = plans.get(kind)
        if plan is None:
            if item is not None and item.status == "done":
                lines.append(f"{names[kind]}: already done ({', '.join(item.files)}); skipped")
            continue
        if plan.error is not None or not plan.prepared:
            lines.append(f"{names[kind]}: cannot be made yet: {plan.error}")
            continue
        todo = plan.prepared[_jobs_done(plan, item):]
        cost = sum(estimate_cost_usd(prepared.request, settings) for prepared in todo)
        total += cost
        lead = plan.prepared[0]
        request = lead.request
        slot = plan.slot
        if len(plan.prepared) > 1:
            unit = "slides" if slot.format == "carousel" else "images"
            images = f"{len(todo)} of {len(plan.prepared)} {unit}"
        else:
            images = f"{request.count} image{'s' if request.count > 1 else ''}"
        layout = f", layout {slot.layout}" if slot.layout else ""
        title = slot.headline or slot.stat or (slot.slides[0].headline if slot.slides else "")
        picks: dict[str, str] = {}
        if lead.picks is not None:
            picks = lead.picks.model_dump(exclude={"format", "style_refs"}, exclude_none=True)
        look = ", ".join(f"{name} {value}" for name, value in picks.items()) or "-"
        person = "the man shown" if lead.inputs.get("personShown") else "no person"
        lines.append(
            f"{names[kind]}: {images} x {request.aspect_ratio} {request.image_size} "
            f'(format {slot.format}{layout}), "{title}"; picked: {look}; '
            f"{person}, {len(request.identity_refs)} identity + {len(request.style_refs)} style "
            f"images (people-free and logo-free when he is shown), logo pasted by the app, via "
            f"{settings.image_provider}: about ${cost:.3f}"
        )
        if slot.format == "carousel" and len(plan.prepared) > 1:
            lines.append(
                "  slides 2+ also attach slide 1's image (same scene, decor and colours); "
                f"slide 1 shows the man, slides 2-{len(plan.prepared)} no person"
            )
        checked = [n for n, prepared in enumerate(plan.prepared, start=1) if prepared.person_shown]
        if checked:
            which = "each image" if len(checked) == len(plan.prepared) else (
                "slide 1" if checked == [1] else f"images {', '.join(map(str, checked))}"
            )
            lines.append(
                f"  person check: the build stops after {which} so Codex can compare it with "
                "his photos before anything else is made"
            )
    if brief.reel is not None:
        item = package.items.get("reel")
        seconds = sum(scene.duration_sec for scene in brief.reel.scenes)
        if item is not None and item.status == "done":
            lines.append("video: already done; skipped")
        elif item is not None and item.status == "waiting":
            lines.append("video: waiting (video pending); build checks it again")
        else:
            lines += _video_dry_run(brief, seconds, settings)
    lines.append(
        f"Estimated image cost: ${total:.3f} ({settings.image_provider}). "
        "Run again without --dry-run to build."
    )
    return lines


def _part_names(brief: ContentBrief, settings: Settings) -> dict[str, str]:
    """How the dry run names each part: the deliverable's name when the brief has them."""
    names = dict(LABELS)
    if brief.deliverables:
        try:
            catalog = load_deliverables(settings.deliverables_file)
        except DeliverableError:
            return names
        for key in brief.deliverables:
            item = catalog.deliverables.get(key)
            if item is not None:
                names[item.brief_format] = key
    return names


def _video_dry_run(brief: ContentBrief, seconds: float, settings: Settings) -> list[str]:
    """What the video costs and whether it can be made now (nothing is made)."""
    assert brief.reel is not None
    reel = brief.reel
    empty = ContentPackage(package_id="", topic="", platform="", formats=[])
    plan = _reel_plan(brief, empty, check=True)
    head = f"{reel.workflow}: 1 video, {len(reel.scenes)} scenes, {seconds:g} s, 9:16"
    if isinstance(plan, str):  # not expected in check mode
        return [f"{head}: {plan}"]
    try:
        prepared = prepare_video(parse_plan(json.dumps(plan), check_scenes=False), settings)
    except (PlanError, VideoError, AvatarError) as error:
        return [f"{head}: cannot be made yet: {error}"]
    used = sorted({(item.scene.type, item.provider) for item in prepared.scenes})
    via = ", ".join(f"{kind} scenes via {provider}" for kind, provider in used)
    lines = [f"{head}; {via}; {_credits({provider for _, provider in used})}"]
    lines += [f"  {line}" for line in scene_lines(prepared, settings)]
    ids = missing_avatar_ids(prepared, settings)
    if ids:
        lines.append("  STOP: the video cannot start until these are set (no job is created):")
        lines += [f"  - {line}" for line in ids]
    missing = missing_providers(prepared)
    if missing:
        lines.append("  The video will be pending (draft - video pending) until this is fixed:")
        lines += [f"  - {line}" for line in missing]
    return lines


def _credits(providers: set[str]) -> str:
    if providers <= {"mock", "none", "library"}:
        return "cost: none now (no real clips are made; the video waits for a real provider)"
    return (
        "cost: Higgsfield/HeyGen credits charged in those apps (not estimated by this tool; "
        "check the plan or credit balance there)"
    )


def _post_markdown(
    brief: ContentBrief, package: ContentPackage, articles: dict[str, SourceArticle]
) -> str:
    lines = [
        f"# {brief.topic}",
        "",
        f"Platform: {brief.platform} | Formats: {', '.join(brief.formats)} | "
        f"Status: {package.status}",
        "",
    ]
    captions = dict(brief.captions) or ({"caption": brief.caption} if brief.caption else {})
    for name, caption in captions.items():
        lines += [
            "## Caption" if name == "caption" else f"## Caption: {name}",
            "",
            caption.hook.strip(),
            "",
            *(line.strip() for line in caption.lines),
            "",
            caption.question.strip(),
            "",
            f"{brief.cta.strip()} {brief.link}",
            "",
            " ".join(brief.hashtags),
            "",
        ]
    lines += ["## Files", ""]
    for kind in brief.formats:
        item = package.items.get(kind)
        if item is not None and item.files:
            lines += [f"- {name}" for name in item.files]
        else:
            state = item.status if item else "pending"
            lines.append(f"- {LABELS[kind]}: {state}")
    lines += ["", "## Sources", ""]
    for article_id in brief.source_article_ids:
        article = articles.get(article_id)
        if article is None:
            lines.append(f"- {article_id}")
            continue
        lines.append(
            f"- [{article.title}]({article.url}): {article.source}, "
            f"{article.published_at.astimezone(UTC):%Y-%m-%d}"
        )
    if not brief.source_article_ids:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _load(folder: Path, brief: ContentBrief) -> ContentPackage:
    path = folder / PACKAGE_FILE
    if path.is_file():
        package = ContentPackage.model_validate_json(path.read_text(encoding="utf-8"))
    else:
        package = ContentPackage(
            package_id=folder.name, topic=brief.topic, platform=brief.platform, formats=[]
        )
    package.topic = brief.topic
    package.platform = brief.platform
    package.formats = list(brief.formats)
    package.source_article_ids = list(brief.source_article_ids)
    return package


def _save(folder: Path, package: ContentPackage) -> None:
    package.updated_at = datetime.now(UTC)
    text = package.model_dump_json(by_alias=True, indent=2) + "\n"
    atomic_write_text(folder / PACKAGE_FILE, text)


__all__ = ["BriefError", "PackageResult", "build_package", "start_package"]
