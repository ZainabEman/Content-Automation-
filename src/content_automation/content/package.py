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
"""

import json
import re
import shutil
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
)
from content_automation.research.collectors import CollectorError
from content_automation.research.models import SourceArticle, SourcesError
from content_automation.research.run import collect, topic_digest, topic_note
from content_automation.research.store import known_article_ids, load_articles
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
    agent_checklist,
    resume_video_job,
    start_video_job,
)
from content_automation.workflows.video_plan import PlanError

PACKAGE_FILE = "package.json"
BRIEF_FILE = "brief.json"
TEMPLATE_FILE = "brief.template.json"
RESEARCH_FILE = "research.md"
POST_FILE = "post.md"
IMAGES_DIR = "images"
VIDEO_DIR = "video"
TOPIC_DAYS = 14
TOPIC_LIMIT = 10
IMAGE_SLOTS = ("post", "ad")  # made in this order; a later part avoids the earlier one's picks
IMAGE_COUNTS = {"post": 2, "ad": AD_VARIANTS}
LABELS = {"post": "post images", "ad": "ad images", "reel": "video"}
_IMAGE_ERRORS = (
    WorkflowError,
    ReferenceLibraryError,
    BrandProfileError,
    DailyLimitError,
    ImageError,
)

ItemStatus = Literal["pending", "done", "waiting", "failed"]


class PackageItem(CamelModel):
    """One part of the package (post, ad or reel)."""

    status: ItemStatus = "pending"  # waiting = video steps are with Codex
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
    topic: str, platform: str, formats: list[str], settings: Settings
) -> PackageResult:
    lines: list[str] = []
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

    folder = _new_folder(settings.packages_dir, f"{date.today():%Y-%m-%d}_{slugify(topic)}")
    brand = _brand(settings)
    company = load_company(settings.company_file)
    try:
        system: DesignSystem | None = load_design_system(settings.design_system_file)
    except WorkflowError as error:
        system = None
        lines.append(f"Design help left out of the template: {error}")
    suggested: FormatId | None = None
    if system is not None and "post" in formats:
        # A format the newest packages did not use; the ad part already is an "ad".
        suggested = suggest_format(
            system, recent_packages(settings.packages_dir), skip=("ad",) if "ad" in formats else ()
        )
        lines.append(f"Suggested post format: {suggested} (different from the last packages).")
    atomic_write_text(folder / RESEARCH_FILE, _research_markdown(topic, articles, note))
    template = _brief_template(
        topic,
        platform,
        formats,
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
    package = ContentPackage(
        package_id=folder.name,
        topic=topic,
        platform=platform,
        formats=formats,
        source_article_ids=template["sourceArticleIds"],
    )
    _save(folder, package)
    lines += [
        f"Package folder: {folder}",
        f"Next (Codex): read {RESEARCH_FILE}, then write {BRIEF_FILE} in this folder: start "
        f"from {TEMPLATE_FILE} and replace every <...> (English; use docs/company/services.md "
        "and the brand and design rules in _help; no invented results, statistics, prices or "
        "client names; keep the suggested post format unless it does not fit the research, "
        "and fill the fields that format needs).",
        f'Then run: uv run ca content build "{folder}" --dry-run',
    ]
    return PackageResult(folder, lines, package)


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


def _slot_template(name: str, format_id: FormatId) -> dict[str, Any]:
    """The fields the format needs, as placeholders."""
    highlight = ["<1-2 words from the headline>"]
    line = "<one short line>"
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
            "headline": "<one bold sentence, at most 12 words>",
            "highlight": highlight,
        },
        "stat": {
            "stat": "<the one big number, exactly as the article writes it, e.g. 73%>",
            "source": "<the ID of that article (research.md); list it in sourceArticleIds too>",
            "subheadline": "<one context line: what the number measures>",
        },
        "news": {
            "headline": "<the news in one line, at most 14 words>",
            "subheadline": "<what it means for our audience, in one sentence>",
            "source": "<the ID of the article (research.md)>",
            "layout": "<B or C to show the man; otherwise delete this line>",
        },
        "carousel": {
            "slides": [
                {"headline": "<the hook, at most 8 words>", "subheadline": line},
                {"headline": "<tip 1>", "subheadline": line, "visual": "<what its icon shows>"},
                {"headline": "<tip 2>", "subheadline": line, "visual": "<what its icon shows>"},
                {"headline": "<the call to action>", "cta": "<button label>"},
            ],
        },
        "person_photo": {"headline": "<0-3 words, or delete this line>"},
        "checklist": {
            "headline": "<short title, at most 6 words>",
            "steps": ["<step 1>", "<step 2>", "<step 3>"],
        },
    }
    return {"format": format_id, **fields[format_id]}


def _brief_template(
    topic: str,
    platform: str,
    formats: list[str],
    articles: list[SourceArticle],
    brand: BrandProfile | None,
    company: CompanyProfile | None,
    system: DesignSystem | None,
    identity_set: str,
    suggested: FormatId | None,
) -> dict[str, Any]:
    brand_tag = brand_hashtag(brand.brand_name) if brand else "<#BrandName>"
    template: dict[str, Any] = {
        "_help": {
            "howTo": (
                f"Save a copy as {BRIEF_FILE} in this folder and replace every <...>. English "
                "only. Use docs/company/services.md and the brand and design rules below. "
                "Never invent results, statistics, prices or client names. This _help block "
                "is ignored."
            ),
            "services": service_names(brand, company),
            "brandRules": {
                "tone": brand.tone if brand else "",
                "language": "English",
                "avoid": brand.dont if brand else [],
                "contentRules": company.content_rules if company else "",
            },
            "design": _design_help(system, suggested) if system else {},
            "formats": {
                "post": "2 image options in the post's format (a carousel: one image per slide)",
                "ad": f"{AD_VARIANTS} variants of one ad: one message, one offer, one CTA",
                "reel": (
                    "9:16 video; each scene at most 15 s, all scenes at most 90 s; scene 1 "
                    'starts from firstFrame; a scene with "image": "post-1" shows that picture'
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
        "platform": platform,
        "formats": formats,
        "service": "<one of the services in _help>",
        "audience": brand.audience if brand and brand.audience else "<who this is for>",
        "objective": "<what this content should achieve>",
        "keyPoints": ["<key point 1>", "<key point 2>", "<key point 3>"],
        "identitySet": identity_set,
        "sourceArticleIds": [a.article_id for a in articles[:3]],
    }
    if "post" in formats:
        template["post"] = _slot_template("post", suggested or "ad")
    if "ad" in formats:
        template["ad"] = _slot_template("ad", "ad")
    if "reel" in formats:
        reel: dict[str, Any] = {
            "hook": "<the first sentence that stops the scroll>",
            "script": "<what the reel tells, in 2-4 sentences>",
        }
        first = "post-1" if "post" in formats else ("ad-1" if "ad" in formats else None)
        if first:
            reel["firstFrame"] = first
        reel["scenes"] = [
            {
                "prompt": "<shot 1: continues from the first frame>",
                "durationSec": 5,
                "onScreenText": "<at most 6 words>",
            },
            {"prompt": "<shot 2>", "durationSec": 5, "onScreenText": "<short call to action>"},
        ]
        template["reel"] = reel
    template["caption"] = {
        "hook": "<line 1: the hook>",
        "lines": ["<short line: the problem>", "<short line: the solution>"],
        "question": "<one question that invites comments?>",
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
    brand = _brand(settings)
    company = load_company(settings.company_file)
    known = known_article_ids(settings.research_dir)
    brief = load_brief(
        folder / BRIEF_FILE,
        services=service_names(brand, company),
        known_article_ids=known,
        brand_tag=brand_hashtag(brand.brand_name) if brand else None,
    )
    package = _load(folder, brief)
    plans = _plan_images(brief, package, folder, settings)
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
    for kind, plan in plans.items():
        package.items[kind] = _make_images(kind, plan, folder, settings, package.items.get(kind))
        lines.append(_item_line(kind, package.items[kind]))
        _save(folder, package)
    if brief.reel is not None:
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


def _in_brief_words(message: str) -> str:
    """Name brief.json fields instead of command-line flags: --sub-highlight -> subHighlight."""

    def field_name(match: re.Match[str]) -> str:
        first, *rest = match.group(1).split("-")
        return first + "".join(part.capitalize() for part in rest)

    return re.sub(r"--([a-z]+(?:-[a-z]+)*)", field_name, message)


def _slot_inputs(
    name: str, slot: ImageSlot, brief: ContentBrief, folder: Path, history: list[DesignPicks]
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
        steps=STEP_SEPARATOR.join(slot.steps) or None,
        slide=slot.slide,
        slide_role=slot.slide_role,
        scene=slot.scene,
        wardrobe=slot.wardrobe,
        props=slot.props,
        logo=True,
        aspect_ratio=aspect,
        count=IMAGE_COUNTS[name],
        request=request,
        history=history,
    )
    if not slot.slides:
        return [base]
    total = len(slot.slides)
    return [
        replace(
            base,
            # Only the hook slide (slide 1) shows the man.
            layout=slot.layout if number == 1 else None,
            pose=slot.pose if number == 1 else None,
            wardrobe=slot.wardrobe if number == 1 else None,
            headline=slide.headline,
            highlight=", ".join(slide.highlight) or None,
            subheadline=slide.subheadline,
            sub_highlight=slide.sub_highlight,
            visual=slide.visual,
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
    brief: ContentBrief, package: ContentPackage, folder: Path, settings: Settings
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
        plan = _ImagePlan(slot, _slot_inputs(name, slot, brief, folder, earlier + others))
        try:
            plan.prepared = [
                prepare_workflow("social_creative", inputs, settings) for inputs in plan.jobs
            ]
        except _IMAGE_ERRORS as error:
            plan.error = error
        if plan.prepared and plan.prepared[0].picks is not None:
            picks[name] = plan.prepared[0].picks
        plans[name] = plan
    return plans


def _slides_done(plan: _ImagePlan, previous: PackageItem | None) -> int:
    """Slides of a carousel that an earlier, interrupted build already made."""
    if len(plan.jobs) < 2 or previous is None or previous.status != "failed":
        return 0
    return len(previous.files) if len(previous.files) < len(plan.jobs) else 0


def _make_images(
    kind: str, plan: _ImagePlan, folder: Path, settings: Settings, previous: PackageItem | None
) -> PackageItem:
    now = datetime.now(UTC)
    done = _slides_done(plan, previous)
    if done and previous is not None:  # keep the finished slides; make only the missing ones
        item = previous.model_copy(update={"error": None, "updated_at": now}, deep=True)
    else:
        item = PackageItem(status="failed", updated_at=now)
    for number, inputs in enumerate(plan.jobs, start=1):
        if number <= done:
            continue
        try:
            job = run_workflow("social_creative", inputs, settings)
        except _IMAGE_ERRORS as error:
            item.error = str(error)
            return item
        item.job_id, item.job_folder = job.job_id, str(job.folder)
        item.job_ids.append(job.job_id)
        if job.status != "completed":
            item.error = job.error
            item.cost_usd = _add_cost(item.cost_usd, job.actual_cost_usd)
            return item
        (folder / IMAGES_DIR).mkdir(exist_ok=True)
        for index, name in enumerate(job.outputs, start=1):
            position = number if len(plan.jobs) > 1 else index  # carousel: one file per slide
            target = folder / IMAGES_DIR / f"{kind}-{position}{Path(name).suffix}"
            shutil.copyfile(job.folder / name, target)
            item.files.append(f"{IMAGES_DIR}/{target.name}")
            item.image_refs.append(f"{job.job_id}/{name}")
        cost = job.actual_cost_usd if job.actual_cost_usd is not None else job.est_cost_usd
        item.cost_usd = _add_cost(item.cost_usd, cost)
        if item.picks is None:
            item.picks = DesignPicks.from_recorded(job.inputs, job.style_asset_ids)
    item.status = "done"
    return item


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
        plan = _reel_plan(brief, package)
        if isinstance(plan, str):
            return PackageItem(status="pending", error=plan, updated_at=now), []
        plan_file = folder / VIDEO_DIR / "plan.json"
        plan_file.parent.mkdir(exist_ok=True)
        atomic_write_text(plan_file, json.dumps(plan, indent=2, ensure_ascii=False) + "\n")
        try:
            job = start_video_job(
                plan_file, settings, request=f"{brief.topic}: reel (package {folder.name})"
            )
        except (PlanError, VideoError, AvatarError) as error:
            return PackageItem(status="failed", error=str(error), updated_at=now), []
    return _reel_item(job, folder)


def _reel_plan(brief: ContentBrief, package: ContentPackage) -> dict[str, Any] | str:
    """The video plan for `ca video`; a string explains what is still missing."""
    assert brief.reel is not None
    reel = brief.reel

    def image_ref(name: str) -> str | None:
        kind, number = name.split("-")
        item = package.items.get(kind)
        if item is None or item.status != "done" or len(item.image_refs) < int(number):
            return None
        return item.image_refs[int(number) - 1]

    first = reel.first_frame or (
        "post-1" if "post" in brief.formats else ("ad-1" if "ad" in brief.formats else None)
    )
    scenes: list[dict[str, Any]] = []
    for number, scene in enumerate(reel.scenes, start=1):
        entry: dict[str, Any] = {
            "n": number,
            "type": "video",
            "prompt": scene.prompt,
            "durationSec": scene.duration_sec,
        }
        if scene.on_screen_text:
            entry["onScreenText"] = scene.on_screen_text
        wanted = scene.image or (first if number == 1 else None)
        if wanted:
            ref = image_ref(wanted)
            if ref is None:
                return f"waiting for {wanted} (its image is not made yet); run build again"
            entry["startImageAssetId"] = ref
            if scene.image:
                entry["type"] = "image"
        scenes.append(entry)
    return {
        "workflowId": "reel_short",
        "platform": f"{brief.platform}_reel",
        "durationSec": sum(scene.duration_sec for scene in reel.scenes),
        "hook": reel.hook,
        "script": reel.script,
        "cta": brief.cta,
        "scenes": scenes,
    }


def _reel_item(job: Job, folder: Path) -> tuple[PackageItem, list[str]]:
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
        item = PackageItem(
            status="waiting",
            job_id=job.job_id,
            job_folder=str(job.folder),
            error="video steps are with Codex",
            updated_at=now,
        )
        checklist = agent_checklist(job) + [
            f'  Then (for this package): uv run ca content build "{folder}"'
        ]
        return item, checklist
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
    for kind in IMAGE_SLOTS:
        item = package.items.get(kind)
        plan = plans.get(kind)
        if plan is None:
            if item is not None and item.status == "done":
                lines.append(f"{LABELS[kind]}: already done ({', '.join(item.files)}); skipped")
            continue
        if plan.error is not None or not plan.prepared:
            lines.append(f"{LABELS[kind]}: cannot be made yet: {plan.error}")
            continue
        todo = plan.prepared[_slides_done(plan, item):]
        cost = sum(estimate_cost_usd(prepared.request, settings) for prepared in todo)
        total += cost
        lead = plan.prepared[0]
        request = lead.request
        slot = plan.slot
        if len(plan.prepared) > 1:
            images = f"{len(todo)} of {len(plan.prepared)} slides"
        else:
            images = f"{request.count}"
        layout = f", layout {slot.layout}" if slot.layout else ""
        title = slot.headline or slot.stat or (slot.slides[0].headline if slot.slides else "")
        picks: dict[str, str] = {}
        if lead.picks is not None:
            picks = lead.picks.model_dump(exclude={"format", "style_refs"}, exclude_none=True)
        look = ", ".join(f"{name} {value}" for name, value in picks.items()) or "-"
        lines.append(
            f"{LABELS[kind]}: {images} x {request.aspect_ratio} {request.image_size} "
            f'(format {slot.format}{layout}), "{title}"; picked: {look}; '
            f"{len(request.identity_refs)} identity + {len(request.style_refs)} style photos, "
            f"via {settings.image_provider}: about ${cost:.3f}"
        )
    if brief.reel is not None:
        item = package.items.get("reel")
        seconds = sum(scene.duration_sec for scene in brief.reel.scenes)
        if item is not None and item.status == "done":
            lines.append("video: already done; skipped")
        elif item is not None and item.status == "waiting":
            lines.append("video: waiting for Codex (agent steps); build checks it again")
        else:
            provider = settings.video_provider
            credits = "0 (mock)" if provider == "mock" else "TBD until the MCP is connected"
            first = brief.reel.first_frame or ("post-1" if "post" in brief.formats else "none")
            lines.append(
                f"video: reel_short, {len(brief.reel.scenes)} scenes, {seconds:g} s, 9:16 via "
                f"{provider}, first frame {first}; credits: {credits}"
            )
    lines.append(
        f"Estimated image cost: ${total:.3f} ({settings.image_provider}). "
        "Run again without --dry-run to build."
    )
    return lines


def _post_markdown(
    brief: ContentBrief, package: ContentPackage, articles: dict[str, SourceArticle]
) -> str:
    lines = [
        f"# {brief.topic}",
        "",
        f"Platform: {brief.platform} | Formats: {', '.join(brief.formats)} | "
        f"Status: {package.status}",
        "",
        "## Caption",
        "",
        brief.caption.hook.strip(),
        "",
        *(line.strip() for line in brief.caption.lines),
        "",
        brief.caption.question.strip(),
        "",
        f"{brief.cta.strip()} {brief.link}",
        "",
        " ".join(brief.hashtags),
        "",
        "## Files",
        "",
    ]
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
