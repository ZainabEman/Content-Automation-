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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from PIL import Image, ImageOps
from pydantic import Field

from content_automation.ai.avatar import AvatarError
from content_automation.ai.image import ImageError, estimate_cost_usd, get_provider
from content_automation.ai.video import VideoError
from content_automation.content.brief import (
    ASPECT_BY_PLATFORM,
    MAX_HASHTAGS,
    MAX_TAKEAWAYS,
    MIN_HASHTAGS,
    MIN_INSIGHTS,
    MIN_TAKEAWAYS,
    STORY_ASPECT,
    BriefError,
    ContentBrief,
    ImageSlot,
    brand_hashtag,
    load_brief,
    meta_cta_buttons,
    slot_kind,
)
from content_automation.content.deliverables import (
    Deliverable,
    DeliverableCatalog,
    DeliverableError,
    load_deliverables,
)
from content_automation.content.direction_brief import (
    carousel_template,
    direction_problems,
    help_text,
    post_template,
)
from content_automation.content.direction_pick import (
    ROMAN,
    direction_format,
    is_direction_id,
    pick_direction,
    recent_directions,
)
from content_automation.content.directions import Direction, DirectionError, load_directions
from content_automation.content.formats import (
    LINE_WORDS,
    TITLE_WORDS,
    FormatCatalog,
    FormatError,
    PostFormat,
    copy_template,
    load_formats,
    pick_format,
    provider_shows_person,
    recent_formats,
    research_has_number,
)
from content_automation.content.german import check_texts
from content_automation.content.quality import (
    CAPTION_MAX_WORDS,
    CAPTION_MAX_WORDS_BY_PLATFORM,
    CAPTION_MIN_WORDS,
    banned_problems,
    caption_problems,
    carousel_problems,
    format_problems,
    insight_problems,
    offer_label,
    post_problems,
    proof_problems,
    reader_texts,
    service_problems,
)
from content_automation.content.relevance import INSIGHT_ONLY, Fit, service_fit
from content_automation.content.research_input import ResearchIdea, save_sources
from content_automation.content.roman import RomanError, approved_photos, identity_sheet
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.core.jobs import DETAILS_FILE, Job, ReviewCheck, slugify
from content_automation.core.limits import DailyLimitError
from content_automation.references import (
    BrandProfile,
    BrandProfileError,
    CompanyProfile,
    ReferenceLibraryError,
    load_brand,
    load_company,
    load_services,
    load_set,
)
from content_automation.references.services import ServicesError
from content_automation.registry import runtime
from content_automation.registry.artifacts import latest_artifact
from content_automation.registry.db import RegistryError
from content_automation.registry.dryruns import CostLine
from content_automation.registry.jobs import JobConfig, find_by_result, load_job_config
from content_automation.registry.strategy import load_content
from content_automation.research.collectors import CollectorError
from content_automation.research.models import SourceArticle, SourcesError
from content_automation.research.run import collect, topic_digest, topic_note
from content_automation.research.store import find_article, known_article_ids, load_articles
from content_automation.workflows.card import Copy
from content_automation.workflows.compose import compose_config, copy_problems, person_card
from content_automation.workflows.design_system import (
    STEP_SEPARATOR,
    DesignSystem,
    FormatId,
    FormatSpec,
    load_design_system,
)
from content_automation.workflows.direction_job import direction_settings
from content_automation.workflows.image_checks import image_problems
from content_automation.workflows.image_job import raw_image
from content_automation.workflows.image_workflows import (
    AD_VARIANTS,
    PreparedWorkflow,
    WorkflowInputs,
    format_settings,
    prepare_workflow,
    run_workflow,
)
from content_automation.workflows.person_check import check_job_image
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
# v5 R6.7: shown with every image of Roman made by his LoRA (caption and tracker notes)
AI_DISCLOSURE = "KI-generiertes Bild (Roman, erstellt mit einem KI-Modell)"
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
    RegistryError,  # not authorized, or over the authorization: nothing was made
)
CAROUSEL_DIR = "carousel"  # the static carousel's caption.txt and alt_text.txt
FORMAT_PLATFORMS = ("linkedin", "facebook", "instagram")  # posts and carousels with a format

# waiting = video steps are with Codex; review = an image waits for the person check
ItemStatus = Literal["pending", "done", "waiting", "failed", "review"]
IDENTITY_PHOTOS_TO_COMPARE = 2  # primary photos shown beside an image at the person check
DONE_STATUS = "draft"  # package.json status once every part is made


class PackageItem(CamelModel):
    """One part of the package (post, ad or reel)."""

    status: ItemStatus = "pending"
    job_id: str | None = None  # the newest job of this part
    job_folder: str | None = None
    job_ids: list[str] = Field(default_factory=list)  # a carousel has one job per slide
    picks: DesignPicks | None = None  # format, scene, wardrobe, props, style images used
    redo: list[int] = Field(default_factory=list)  # positions a review regenerate makes again
    # Track L: automatic redos used per image (at most 1 per "ok") and the failed checks' reasons
    person_redos: dict[int, int] = Field(default_factory=dict)
    person_reasons: dict[int, list[str]] = Field(default_factory=dict)
    files: list[str] = Field(default_factory=list)  # relative to the package folder
    image_refs: list[str] = Field(default_factory=list)  # "<jobId>/<file>" per image
    image_folders: list[str] = Field(default_factory=list)  # the job folder of each image
    cost_usd: float | None = None  # actual (provider-reported) where known, else the estimate
    est_cost_usd: float | None = None  # the estimate for the same jobs: shown beside the actual
    subfolders: dict[str, str] = Field(default_factory=dict)  # file -> Drive subfolder
    notes: list[str] = Field(default_factory=list)  # for the tracker (fallbacks, set check)
    error: str | None = None
    updated_at: datetime | None = None


class UploadRecord(CamelModel):
    """One file copied to storage by `ca drive sync`: its ID and link, or upload_failed."""

    provider: str  # drive or mock: a mock upload never counts as a Drive one
    status: Literal["uploaded", "upload_failed"]
    file_id: str | None = None
    link: str | None = None
    error: str | None = None
    updated_at: datetime | None = None


class ContentPackage(CamelModel):
    """PACKAGES_DIR/<folder>/package.json"""

    package_id: str
    content_id: str | None = None  # the calendar row's Content ID (Drive folder name)
    research_source: str | None = None  # the calendar row's Research source (tracker)
    topic: str
    deliverables: list[str] = Field(default_factory=list)  # exactly what the user named
    platform: str
    formats: list[str]
    status: str = "brief needed"
    items: dict[str, PackageItem] = Field(default_factory=dict)
    uploads: dict[str, UploadRecord] = Field(default_factory=dict)  # by file in the package
    source_article_ids: list[str] = Field(default_factory=list)
    total_cost_usd: float | None = None
    reviewer: str | None = None
    note: str | None = None
    format: str | None = None  # the post format (config/post_formats.json), picked at stage 1
    direction: str | None = None  # Phase D: config/design_directions.json, picked at stage 1
    # v5: the layout variant's category and background treatment (R4, R5.3), the explicit
    # requires_roman flag (R6.3) and the content language (R1)
    category: str | None = None
    treatment: str | None = None
    requires_roman: bool = False
    language: str | None = None
    # v5 R6.7 (EU AI Act Art. 50): the label for images of Roman made by his LoRA; also on
    # Facebook ads (Q8 default yes). None: no generated person.
    ai_disclosure: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass
class PackageResult:
    folder: Path
    lines: list[str] = field(default_factory=list)
    package: ContentPackage | None = None
    estimated_usd: float | None = None  # dry run: the image cost still to spend
    cost_lines: list[CostLine] = field(default_factory=list)  # dry run: per item and provider


# ----------------------------------------------------------------------------- start


def start_package(
    topic: str,
    deliverables: list[str],
    catalog: DeliverableCatalog,
    settings: Settings,
    *,
    idea: ResearchIdea | None = None,
    content_id: str | None = None,
    format_override: str | None = None,
) -> PackageResult:
    """Make the package folder with research.md (stage 1, free).

    idea: research from a file (a newsletter idea) instead of the scraper. With no
    deliverables yet, nothing can be built until `ca content set` names them.
    content_id: the calendar row's Content ID (it seeds the post format); format_override:
    "as <format>".
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
        content_id=content_id,
        platform=catalog.platform_for([]),
        formats=[],
        source_article_ids=[article.article_id for article in articles[:3]],
    )
    _save(folder, package)
    lines.append(f"Package folder: {folder}")
    if deliverables:
        lines += _apply_deliverables(folder, package, deliverables, catalog, settings, articles,
                                     format_override)
    else:
        lines.append(
            f"Next (Codex): write {CONTENT_FILE} (angle, key message, 3-5 key points, draft "
            'caption, source link), then ask "What should I make?". Nothing is built until '
            f'the user names deliverables: uv run ca content set "{folder}" --deliverables '
            '"<names>"'
        )
    return PackageResult(folder, lines, package)


def set_deliverables(
    folder: Path, deliverables: list[str], catalog: DeliverableCatalog, settings: Settings,
    *, format_override: str | None = None,
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
    lines = _apply_deliverables(folder, package, deliverables, catalog, settings, articles,
                                format_override)
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
    format_override: str | None = None,
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
    # Phase D: a design direction by default; the older post formats only when one is named
    # ("as li_stat"), or for a part no direction takes.
    as_direction = is_direction_id(format_override)
    as_format = bool(format_override) and not as_direction and (
        str(format_override).strip().lower() != ROMAN)
    direction = None if as_format else _choose_direction(folder, package, items, settings,
                                                         format_override)
    if direction is not None:
        lines.append(f"Design direction: {direction[0].label} ({direction[1]})")
        lines.append(f"Layout variant: {direction[0].id}, {direction[0].category}, "
                     f"treatment {direction[0].treatment}; route: "
                     + ("comfyui (Roman's LoRA on RunPod; AI disclosure on)" if direction[0].roman
                        else "openrouter (designer prompt, no person)"))
    elif as_direction:
        raise DeliverableError(f'"as {format_override}": none of these deliverables takes a '
                               "layout variant (LinkedIn or Facebook post, Facebook ad, "
                               "Instagram carousel)")
    post_format = None if direction is not None else _choose_format(
        folder, package, items, settings, articles, format_override)
    if post_format is not None:
        lines.append(f"Post format: {post_format.label()}"
                     + (" (as asked)" if as_format else
                        " (not one of the last 2 on that platform)"))
    if post_format is None and direction is None and format_override and not as_direction:
        raise DeliverableError(f'"as {format_override}": none of these deliverables takes a '
                               "post format (LinkedIn or Facebook post, Instagram carousel)")
    post = next((item for item in items if item.part == "post"), None)
    suggested: FormatId | None = post.format if post is not None else None
    if system is not None and post is not None and suggested is None:
        # The next format in the rotation that the newest packages did not use.
        suggested = suggest_format(
            system, recent_packages(settings.packages_dir, exclude=folder), allowed=post.formats
        )
        if direction is None:
            lines.append(f"Suggested post format: {suggested} (different from the last "
                         "packages).")
    template = _brief_template(
        package.topic,
        deliverables,
        catalog,
        articles,
        brand,
        company,
        system,
        post_format,
        settings.default_identity_set,
        suggested,
        settings.services_file,
        direction[0] if direction is not None else None,
    )
    atomic_write_text(
        folder / TEMPLATE_FILE, json.dumps(template, indent=2, ensure_ascii=False) + "\n"
    )
    package.deliverables = deliverables
    package.platform = catalog.platform_for(deliverables)
    package.formats = [item.brief_format for item in items]
    package.format = post_format.id if post_format is not None else None
    package.direction = direction[0].id if direction is not None else None
    if direction is not None:  # v5: stored in package.json and the registry (R5.4, R6.3)
        package.category = direction[0].category
        package.treatment = direction[0].treatment
        package.requires_roman = direction[0].roman
        package.ai_disclosure = AI_DISCLOSURE if direction[0].roman else None
    package.language = load_content(settings.content_file).for_platform(package.platform)
    for item_id in runtime.package_items(folder).values():
        runtime.report_design(item_id, layout_variant=package.direction,
                              background_treatment=package.treatment,
                              requires_roman=package.requires_roman, language=package.language)
    if post is not None and suggested is not None and "post" not in package.items:
        # Saved now, so the next package already rotates to another format.
        package.items["post"] = PackageItem(picks=DesignPicks(format=suggested))
    _save(folder, package)
    lines += [
        f"Next (Codex): write {BRIEF_FILE} for only these deliverables: start from "
        f"{TEMPLATE_FILE} (and {CONTENT_FILE} if it exists) and replace every <...> (German "
        "for everything the audience sees, natural for readers in Germany, \"Sie\"; "
        "use brand/services.md and the brand and design rules in _help; no invented "
        "results, statistics, prices or client names; one caption per deliverable).",
        f'Then run: uv run ca content build "{folder}" --dry-run',
    ]
    return lines


def _choose_format(
    folder: Path,
    package: ContentPackage,
    items: list[Deliverable],
    settings: Settings,
    articles: list[SourceArticle],
    override: str | None,
) -> PostFormat | None:
    """The post format of the package's LinkedIn/Facebook post or Instagram carousel (one per
    package), picked by content/formats.py; "as <format>" wins. DeliverableError for a bad
    override (exit 2: Codex asks the user)."""
    part = next((item for item in items if item.part in ("post", "carousel")
                 and item.platform in FORMAT_PLATFORMS), None)
    if part is None or part.platform is None:
        return None
    try:
        catalog = load_formats(settings.post_formats_file)
        roman = next((item for item in catalog.formats if item.roman), None)
        # Roman formats use their own provider (comfyui, Roman's LoRA); mock stays mock.
        person_ok = roman is not None and provider_shows_person(
            format_settings(roman, settings))
        last_roman = next((name for name in recent_formats(
            settings.packages_dir, None, exclude=folder, limit=50)
            if (found := catalog.find(name)) is not None and found.roman), None)
        return pick_format(
            part.platform, catalog,
            seed=package.content_id or folder.name,
            recent=recent_formats(settings.packages_dir, part.platform, exclude=folder),
            has_number=research_has_number(f"{a.title} {a.summary} {a.content}"
                                           for a in articles),
            person_ok=person_ok,
            override=override,
            last_roman=last_roman,
        )
    except FormatError as error:
        raise DeliverableError(str(error)) from None


def _choose_direction(
    folder: Path,
    package: ContentPackage,
    items: list[Deliverable],
    settings: Settings,
    override: str | None,
) -> tuple[Direction, str] | None:
    """Phase D / v5: the layout variant of the package's post, ad or carousel (content/
    direction_pick.py); "as <ID>" wins, "roman" = a founder variant of that category.
    DeliverableError for a bad override or no usable variant (exit 2: Codex asks the user)."""
    roman = (override or "").strip().lower() == ROMAN  # requires_roman (v5 R6.3)
    for item in items:
        if item.platform is None:
            continue
        format_name = direction_format(item.part, item.platform, roman)
        if format_name is None:
            continue
        try:
            catalog = load_directions()
            lora = settings if settings.image_provider == "mock" else settings.model_copy(
                update={"image_provider": "comfyui"})
            return pick_direction(
                catalog, format_name, item.platform,
                seed=package.content_id or folder.name,
                recent=recent_directions(settings.packages_dir, catalog, format_name,
                                         item.platform, exclude=folder),
                lora_ok=provider_shows_person(lora),
                override=override if is_direction_id(override) else None,
                roman=roman,
            )
        except DirectionError as error:
            raise DeliverableError(str(error)) from None
    return None


def _service_fit(topic: str, articles: list[SourceArticle],
                 services_file: Path | None) -> Fit | None:
    """Phase D: the verified service the topic is about, or insight-only (None: no file)."""
    if services_file is None:
        return None
    try:
        catalog = load_services(services_file)
    except ServicesError:
        return None
    return service_fit([topic, *(article.title for article in articles[:3])], catalog)


def _formats(settings: Settings) -> FormatCatalog | None:
    try:
        return load_formats(settings.post_formats_file)
    except FormatError:
        return None  # reported by the brief checks


def _part_settings(chosen: PostFormat | None, slot: ImageSlot, settings: Settings) -> Settings:
    """A post format's part: the format's own provider, never swapped (a carousel: its cover's,
    OpenRouter with CAROUSEL_IMAGE_MODEL; no image slot: the app alone, free); IMAGE_PROVIDER=
    mock stays mock. A design direction: its provider (each slide's own in the prepared job).
    Every other part: as given."""
    if slot.direction:
        try:
            found = load_directions().find(slot.direction)
        except DirectionError:
            found = None  # reported by the brief checks
        if found is not None:
            return direction_settings(found, found.visual.subject != "none", settings)
        return settings
    if chosen is None or not slot.post_format:
        return settings
    return format_settings(chosen, settings, "cover" if chosen.slide_types else None)


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


def service_names(brand: BrandProfile | None, company: CompanyProfile | None,
                  services_file: Path | None = None) -> list[str]:
    """The verified services of config/services.json; older setups: brand.json, services.md."""
    if services_file is not None and services_file.is_file():
        return [service.name for service in load_services(services_file).verified()]
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

    def person(spec: FormatSpec) -> str:
        return "always the man" if spec.person != "never" else "no person"

    post_types = [key for key, spec in system.formats.items() if spec.family == "post"]
    return {
        "choose": (
            "Every Facebook post is the premium post layout with the man; statement, stat, "
            f"checklist and news are its content types ({', '.join(post_types)}). Keep the "
            "suggested content type (it differs from the last packages) unless it does not fit "
            "the research. A stat needs a number written in a research article (its ID goes in "
            "source); never invent one. Layout: leave it out to rotate A-D (A product or feature, "
            "B or C trust, D pain vs gain). Headline (format ad): one formula from "
            "headlineFormulas. Never describe the man's face."
        ),
        "suggestedFormat": suggested,
        "postFamily": system.post_family.composition,
        "formats": {
            key: {
                "use": spec.use,
                "required": [*spec.required, *(["source"] if key == "stat" else [])],
                "optional": spec.optional,
                "person": person(spec),
                "headlineMaxWords": spec.headline_max_words,
            }
            for key, spec in system.formats.items()
            if key != "carousel"  # the carousel follows its post format (_help.postFormat)
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
            'Per image you may add "layout", "scene", "wardrobe", "props" or "pose": a letter, '
            "an ID from pools or your own words. Left out, they are picked so that they differ "
            'from the last packages. Format ad also takes "ctaIcon" (arrow, calendar or play; '
            'default: chosen from the cta label) and "icons" (3-4 labels of 1-2 words). In '
            'post, "kind": "story" makes it 9:16.'
        ),
    }


def _slot_template(name: str, format_id: FormatId) -> dict[str, Any]:
    """The fields the format needs, as placeholders."""
    highlight = ["<1-2 words from the headline>"]
    audience = "<FOR WHOM, from the topic, e.g. FOR DENTAL PRACTICES>"
    line = "<one specific supporting line: who does what, when, through which channel>"
    points = ["<key point 1, at most 8 words>", "<key point 2>", "<key point 3>"]
    cta = (
        "<button label naming the one offer (see _help.design.rules.ad)>"
        if name == "ad"
        else "<soft button label (see _help.design.rules.post)>"
    )
    fields: dict[FormatId, dict[str, Any]] = {
        "ad": {
            "headline": "<at most 6 words, built from a formula in _help.design.headlineFormulas>",
            "highlight": highlight,
            "subheadline": "<one short, specific sentence>",
            "subHighlight": "<one word from the subheadline>",
            "cta": cta,
        },
        "statement": {
            "audienceLine": audience,
            "headline": "<one bold claim or insight, at most 10 words>",
            "highlight": highlight,
            "subheadline": line,
            "points": points,
        },
        "stat": {
            "audienceLine": audience,
            "headline": "<what the number means, at most 10 words>",
            "stat": "<the one big number, exactly as the article writes it, e.g. 73%>",
            "source": "<the ID of that article (research.md); list it in sourceArticleIds too>",
            "sourceName": "<the publisher, short, as the article names it, e.g. Zillow>",
            "subheadline": "<one line: what the number measures and what to do about it>",
        },
        "news": {
            "headline": "<the news in one line, at most 14 words>",
            "subheadline": "<what it means for our audience, in one sentence>",
            "source": "<the ID of the article (research.md)>",
            "points": ["<what to do now 1>", "<what to do now 2>", "<what to do now 3>"],
        },
        "person_photo": {"headline": "<0-3 words, or delete this line>"},
        "checklist": {
            "audienceLine": audience,
            "headline": "<the task, at most 8 words>",
            "subheadline": line,
            "points": ["<step 1>", "<step 2>", "<step 3>"],
        },
    }
    return {"format": format_id, **fields[format_id]}


def _format_slide(post_format: PostFormat, kind: str) -> dict[str, Any]:
    """One static carousel slide of a post format: its fields, the picture (the cover only)
    and the alt text."""
    slide: dict[str, Any] = {"type": kind, "copy": copy_template(post_format, kind)}
    if post_format.canvas(kind)[0] is not None:
        slide["illustration"] = ("<what the picture shows: a place or objects only, never the "
                                 "headline or topic; nothing written, no screens, no people>")
    slide["altText"] = "<what the slide shows and says, for screen readers>"
    return slide


def _first_frame(formats: Sequence[str]) -> str | None:
    """The package image a video starts from: the post, else the carousel hook, else the ad."""
    for kind in ("post", "carousel", "ad"):
        if kind in formats:
            return f"{kind}-1"
    return None


def _video_template(workflow: str, first_frame: str | None) -> dict[str, Any]:
    """reel_short: generated clips (UGC ads and podcast clips were removed in v5)."""
    video: dict[str, Any] = {
        "workflow": workflow,
        "hook": "<the first sentence that stops the scroll>",
        "script": "<what the video tells, in 2-4 sentences>",
    }
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
    post_format: PostFormat | None,
    identity_set: str,
    suggested: FormatId | None,
    services_file: Path | None = None,
    direction: Direction | None = None,
) -> dict[str, Any]:
    brand_tag = brand_hashtag(brand.brand_name) if brand else "<#BrandName>"
    chosen = {key: catalog.deliverables[key] for key in deliverables}
    fit = _service_fit(topic, articles, services_file)
    by_part = {item.part: item for item in chosen.values()}
    formats = [item.brief_format for item in chosen.values()]
    template: dict[str, Any] = {
        "_help": {
            "howTo": (
                f"Save a copy as {BRIEF_FILE} in this folder and replace every <...>. Everything "
                "the audience sees is German (natural, for readers in Germany, \"Sie\"; no "
                "literal translations, no generic AI marketing language: config/"
                "german_quality.json). Use brand/services.md and config/services.json "
                "(verified services only) and the brand and design rules below. "
                "Never invent results, statistics, prices or client names. Keep deliverables "
                "and formats unchanged: build only what the user named. This _help block is "
                "ignored."
            ),
            "deliverables": {key: item.label for key, item in chosen.items()},
            "services": service_names(brand, company, services_file),
            "designDirection": help_text(direction) if direction is not None else {},
            "serviceFit": (
                f"{fit.label}: keep this service, pick another verified one the copy is "
                f'really about, or write "{INSIGHT_ONLY}" (no service named; the cta is a '
                "question, no sales ask). Never invent services, results or prices."
            ) if fit is not None else "",
            "brandRules": {
                "tone": brand.tone if brand else "",
                "language": "German (de), \"Sie\"",
                "avoid": brand.dont if brand else [],
                "contentRules": company.content_rules if company else "",
            },
            "design": _design_help(system, suggested) if system else {},
            "formats": {
                "post": "one premium post image with the man, in the post's content type",
                "carousel": (
                    "static PNG slides (1080x1350): cover, body slides, final; the text and the "
                    "logo (last slide only) are rendered by the app (see _help.postFormat)"
                ),
                "ad": f"{AD_VARIANTS} variants of one ad: one message, one offer, one CTA",
                "reel": (
                    "9:16 video (workflow from the deliverable); each scene at most 15 s; "
                    "reel_short at most 90 s; scene 1 starts from firstFrame; a scene with "
                    '"image": "post-1" shows that picture'
                ),
            },
            "caption": (
                f"hook = line 1; takeaways = {MIN_TAKEAWAYS}-{MAX_TAKEAWAYS} specific, usable "
                "points; question = one question that invites comments; the cta (with the "
                "offer) and link close the caption; hook, takeaways, question and cta together "
                f"{CAPTION_MIN_WORDS}-{CAPTION_MAX_WORDS} words; {MIN_HASHTAGS}-{MAX_HASHTAGS} "
                f"hashtags (German or brand tags) including {brand_tag}."
            ),
            "insights": (
                f"Before writing anything else, list at least {MIN_INSIGHTS} specific insights "
                "from the research (actions, how-to steps, example wording, timings, tools, "
                "sourced figures), each with its source: an article ID or a link in "
                "research.md. Build every slide and post on them; generic lines are refused."
            ),
            "topArticles": [f"{a.article_id} | {a.source} | {a.title}" for a in articles],
        },
        "topic": topic,
        "deliverables": deliverables,
        "platform": catalog.platform_for(deliverables),
        "formats": formats,
        "service": fit.name if fit is not None and fit.service_id else (
            INSIGHT_ONLY if fit is not None else "<one of the services in _help>"),
        "audience": brand.audience if brand and brand.audience else "<who this is for>",
        "objective": "<what this content should achieve>",
        "keyPoints": ["<key point 1>", "<key point 2>", "<key point 3>"],
        "identitySet": identity_set,
        "sourceArticleIds": [a.article_id for a in articles[:3]],
        "insights": [
            {"text": f"<insight {number}: specific and usable today>",
             "source": "<article ID or link from research.md>"}
            for number in range(1, MIN_INSIGHTS + 1)
        ],
    }
    linkedin = [key for key, item in chosen.items() if item.platform == "linkedin"]
    if linkedin:
        template["_help"]["linkedin"] = (
            f"{', '.join(linkedin)}: the premium post layout at 1:1. The man is shown by "
            'default; set "post.person": false only when the topic fits without him (the dry '
            'run then says "no person"). Caption: professional tone (clear and specific, no '
            "slang or emoji), the hook as one line on line 1, hook, takeaways, question and cta "
            f"together {CAPTION_MIN_WORDS}-{CAPTION_MAX_WORDS_BY_PLATFORM['linkedin']} words, "
            f"{MIN_HASHTAGS}-{MAX_HASHTAGS} hashtags including {brand_tag}."
        )
    post = by_part.get("post")
    if post_format is not None:
        template["_help"]["postFormat"] = {
            "format": post_format.label(),
            "rule": (
                'Fill only the fields under "copy" (they are this format\'s fields); the app '
                "renders them on a solid panel beside the picture, and the picture has no text "
                f"at all. Titles at most {TITLE_WORDS} words, every other line at most "
                f"{LINE_WORDS} words; no generic titles: one concrete example or sourced fact "
                "per post and per slide. Never use: SME marketers, leverage, unlock, practical "
                "sequence. The illustration describes the visual only (a place or objects), "
                "never the headline, topic or copy. Never describe the man's face."
                + (" A big number must be written in a research article listed in "
                   "sourceArticleIds." if post_format.needs_number else "")
            ),
            "fields": {name: hint for fields, _ in post_format.layouts()
                       for name, hint in fields.items()},
        }
    if post is not None:
        design = suggested or post.format or "statement"
        if direction is not None and direction.format not in ("carousel", "fb_ad"):
            template["post"] = post_template(direction, platform=post.platform, seed=topic,
                                             design=design)
        elif post_format is not None:
            template["post"] = {"format": design, "postFormat": post_format.id,
                                "copy": copy_template(post_format)}
        else:
            template["post"] = _slot_template("post", design)
            if post.platform == "linkedin":
                template["post"]["person"] = True
    if "carousel" in by_part:
        carousel = by_part["carousel"]
        if direction is not None and direction.format == "carousel":
            template["carousel"] = carousel_template(direction)
        elif post_format is not None and post_format.slides is not None:
            low, high = post_format.slides
            count = min(max(carousel.slides or high, low), high)
            kinds = ["cover", *(["body"] * (count - 2)), "final"]
            template["carousel"] = {"format": "carousel", "postFormat": post_format.id,
                                    "slides": [_format_slide(post_format, kind) for kind in kinds]}
        else:
            template["carousel"] = {"format": "carousel", "slides": []}
    if "ad" in by_part:
        if direction is not None and direction.format == "fb_ad":  # v5: a Facebook ad (R4)
            template["ad"] = {
                **post_template(direction, platform="facebook", seed=topic, design="ad"),
                "adFields": {
                    "primaryText": "<German primary text above the image: the problem, the "
                                   "offer and the next step, 1-3 short sentences>",
                    "headline": "<German headline below the image, at most 40 characters>",
                    "description": "<optional German line under the headline, at most 30 "
                                   "characters>",
                    "ctaButton": f"<one of Meta's buttons: {', '.join(meta_cta_buttons())}>",
                },
            }
        else:
            template["ad"] = _slot_template("ad", "ad")
    video = by_part.get("video")
    if video is not None and video.workflow is not None:
        first = _first_frame(formats)
        template["reel"] = _video_template(video.workflow, first)
    template["captions"] = {
        key: {
            "hook": f"<line 1: the hook for the {item.label.split(':')[0]}>",
            "takeaways": [f"<takeaway {n}: specific and usable today>" for n in range(1, 5)],
            "question": "<one question that invites comments?>",
        }
        for key, item in chosen.items()
    }
    offer = company.offer if company else ""
    template["cta"] = (
        "<one question that invites comments: insight-only, no sales ask>"
        if fit is not None and fit.service_id is None else
        f'<one clear call to action that names the offer "{offer_label(offer)}">'
        if offer else "<one clear call to action with the offer (ask: services.md has none)>"
    )
    website = company.website if company else ""
    template["link"] = website or (
        "<https://... the page to open; ask the user, never guess (to pre-fill it, add a "
        '"Website: https://..." line to brand/services.md)>'
    )
    template["hashtags"] = [brand_tag, "<#TopicTag>", "<#TopicTag>"]
    return template


# ----------------------------------------------------------------------------- build


def ad_provider_problem(specs: Mapping[str, Deliverable], provider: str | None,
                        image_provider: str) -> str | None:
    """Facebook ads (strict, Track L): never a fallback provider. A --provider other than the
    ad's own (mock aside, for local tests) is refused for a build with an ad."""
    ads = [name for name, spec in specs.items() if spec.part == "ad"]
    own = {specs[name].provider or image_provider for name in ads}
    if not ads or provider is None or provider == "mock" or provider in own:
        return None
    return (f"{', '.join(ads)}: never a fallback provider for an ad (--provider {provider}); "
            f"build it with {', '.join(sorted(own))}, or leave the ad out of this build")


def _format_provider_problem(folder: Path, provider: str | None,
                             settings: Settings) -> str | None:
    """A post format's provider is fixed (config/post_formats.json "provider"): a --provider
    other than it (mock aside, for local tests) is refused, never a silent switch."""
    if provider is None or provider == "mock" or not (folder / PACKAGE_FILE).is_file():
        return None
    try:
        saved = json.loads((folder / PACKAGE_FILE).read_text(encoding="utf-8"))
        chosen = load_formats(settings.post_formats_file).find(str(saved.get("format") or ""))
    except (OSError, ValueError, FormatError):
        return None
    named = str(saved.get("direction") or "")
    try:
        direction = load_directions().find(named) if named else None
    except DirectionError:
        direction = None
    if direction is not None:
        if direction.provider in ("template", provider):
            return None
        return (f"{direction.id}: its image provider is {direction.provider} (config/"
                f"design_directions.json); --provider {provider} is refused (never swapped)")
    if chosen is None or chosen.provider in (None, provider) or not chosen.has_image:
        return None
    return (f"{chosen.id}: its image provider is {chosen.provider} (config/post_formats.json); "
            f"--provider {provider} is refused (never swapped)")


def build_package(folder: Path, settings: Settings, *, dry_run: bool,
                  provider: str | None = None) -> PackageResult:
    """Raises BriefError when brief.json is missing or invalid (nothing is made). provider:
    the user's --provider override (else the deliverable's provider, else IMAGE_PROVIDER)."""
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
        services=service_names(brand, company, settings.services_file),
        known_article_ids=known,
        brand_tag=brand_hashtag(brand.brand_name) if brand else None,
        checks=lambda checked: _deliverable_problems(checked, settings, folder),
    )
    catalog = load_deliverables(settings.deliverables_file)
    specs = {name: catalog.deliverables[name] for name in brief.deliverables
             if name in catalog.deliverables}
    configured = {spec.provider for spec in specs.values()} - {None}
    # --provider first; IMAGE_PROVIDER=mock (local test mode) stays mock; then the
    # deliverable's provider; then IMAGE_PROVIDER.
    chosen = provider or (None if settings.image_provider == "mock" else
                          configured.pop() if len(configured) == 1 else None)
    refused = ad_provider_problem(specs, provider, settings.image_provider)
    if refused is None:
        refused = _format_provider_problem(folder, provider, settings)
    if refused is not None:
        raise BriefError([refused])
    if chosen and chosen != settings.image_provider:
        settings = settings.model_copy(update={"image_provider": chosen})
    package = _load(folder, brief)
    plans = _plan_images(brief, package, folder, settings, _image_counts(brief, settings))
    problems = [
        f"{name}: {_in_brief_words(str(plan.error))}"
        for name, plan in plans.items()
        if isinstance(plan.error, WorkflowError)
    ]
    problems += _ad_claim_problems(brief, folder)
    problems += _person_copy_problems(plans, settings)
    if problems:  # format rules, a stat without a research source, ...: nothing is made
        raise BriefError(problems)
    if dry_run:
        lines, total, image_costs, redo_costs = _dry_run_lines(folder, brief, package, plans,
                                                               settings)
        fallbacks = sorted({str(spec.fallback_provider) for spec in specs.values()
                            if spec.fallback_provider and spec.part != "ad"}  # never for ads
                           - {chosen or settings.image_provider})
        lines += [f"Fallback provider {name}: not used unless the user says ok to it; its own "
                  f'dry run: uv run ca content build "{folder}" --provider {name} --dry-run'
                  for name in fallbacks]
        result = PackageResult(folder, lines, package, estimated_usd=total)
        providers: dict[str, str] = {kind: (plan.settings or settings).image_provider
                     for kind, plan in plans.items()}
        result.cost_lines = _cost_lines(folder, brief, package, image_costs, settings,
                                        redo_costs, providers)
        return result

    lines = []
    check: list[str] = []
    waiting: list[str] = []  # a warm batch: the checks of every part, after all are made
    batch = _batch(settings)
    for kind, plan in plans.items():  # the picks are saved before any provider call
        stored = package.items.get(kind)
        if plan.prepared and plan.prepared[0].picks is not None and (
                stored is None or stored.picks is None):
            package.items[kind] = (stored or PackageItem()).model_copy(
                update={"picks": plan.prepared[0].picks})
    _save(folder, package)
    registered = runtime.package_items(folder)  # part -> BG ID (inside a `ca` command)
    if package.direction:  # v5: the registry shows the variant (R5.4) and requires_roman
        for item_id in registered.values():
            runtime.report_design(item_id, layout_variant=package.direction,
                                  background_treatment=package.treatment,
                                  requires_roman=package.requires_roman,
                                  language=package.language)
    for kind, plan in plans.items():
        with runtime.for_item(registered.get(kind)):
            package.items[kind], check = _make_images(
                kind, plan, folder, plan.settings or settings, package.items.get(kind), batch
            )
            done = package.items[kind].status == "done"
            if kind == "carousel" and plan.slot.templated and done:
                _carousel_texts(brief, folder, package.items[kind])
        _report(registered.get(kind), package.items[kind])
        lines.append(_item_line(kind, package.items[kind]))
        _save(folder, package)
        if check and not batch.warm:  # the person check stops the build: build nothing more
            lines += check
            break
        waiting += check  # warm batch: every part first (one cold start), then the checks
    if waiting:
        lines += waiting
        check = waiting
    if brief.reel is not None and not check:
        item = package.items.get("reel")
        if item is None or item.status != "done":
            with runtime.for_item(registered.get("reel")):
                package.items["reel"], extra = _make_reel(brief, package, folder, settings)
            _report(registered.get("reel"), package.items["reel"])
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


def _report(item_id: str | None, part: PackageItem) -> None:
    """The part's state to the registry: done -> generated, failed -> failed/partial."""
    if part.status in ("done", "failed"):
        runtime.report_part(item_id, part.status)


def _job_config(settings: Settings) -> JobConfig:
    scope = runtime.current()
    return scope.config if scope is not None else load_job_config(settings.jobs_file)


def _cost_lines(
    folder: Path, brief: ContentBrief, package: ContentPackage, image_costs: dict[str, float],
    settings: Settings, redo_costs: dict[str, float] | None = None,
    providers: dict[str, str] | None = None,
) -> list[CostLine]:
    """The dry run per item, job type and provider: what an "ok" would authorize (D-4). The
    max of a part with the person includes one automatic redo of each such image. providers:
    the image provider per part (the static carousel: OpenRouter)."""
    config = _job_config(settings)
    items = runtime.package_items(folder)
    names = _part_names(brief, settings)
    lines = []
    for kind, cost in image_costs.items():
        provider = (providers or {}).get(kind, settings.image_provider)
        if cost > 0 or config.paid(provider):
            lines.append(CostLine(items.get(kind), "image", provider, config.unit(provider), cost,
                                  round(cost + (redo_costs or {}).get(kind, 0.0), 6),
                                  names[kind]))
    reel = package.items.get("reel")
    if brief.reel is not None and (reel is None or reel.status not in ("done", "waiting")):
        for job_type, scene_provider, estimate in _video_costs(brief, settings, config):
            lines.append(CostLine(items.get("reel"), job_type, scene_provider,
                                  config.unit(scene_provider), estimate, estimate, "video"))
    return lines


def _video_costs(brief: ContentBrief, settings: Settings, config: JobConfig
                 ) -> list[tuple[str, str, float]]:
    """Per paid video scene: job type, provider and the credit estimate from config/jobs.json."""
    empty = ContentPackage(package_id="", topic="", platform="", formats=[])
    plan = _reel_plan(brief, empty, check=True)
    if isinstance(plan, str):
        return []
    try:
        prepared = prepare_video(parse_plan(json.dumps(plan), check_scenes=False), settings)
    except (PlanError, VideoError, AvatarError):
        return []
    costs: list[tuple[str, str, float]] = []
    for item in prepared.scenes:
        if not config.paid(item.provider):
            continue
        job_type = "video_scene" if item.scene.type == "video" else "avatar_scene"
        costs.append((job_type, item.provider, config.estimate(job_type, item.provider) or 0.0))
    return costs


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


def _deliverable_problems(brief: ContentBrief, settings: Settings, folder: Path) -> list[str]:
    problems = _quality_problems(brief, settings, folder)
    if not brief.deliverables:
        return problems  # a brief from before deliverables: its formats decide
    try:
        return load_deliverables(settings.deliverables_file).problems(brief) + problems
    except DeliverableError as error:
        return [str(error), *problems]


def _quality_problems(brief: ContentBrief, settings: Settings, folder: Path) -> list[str]:
    """The story and specific content, insights from the research, captions with the offer,
    a platform CTA, and proof only from proof.md or the cited research."""
    proof_file = settings.company_file.parent / PROOF_FILE
    proof = proof_file.read_text(encoding="utf-8") if proof_file.is_file() else ""
    cited = {*brief.source_article_ids, *(insight.source for insight in brief.insights)}
    articles = {
        article_id: f"{found.title} {found.summary} {found.content}"
        for article_id in cited
        if (found := find_article(settings.research_dir, article_id)) is not None
    }
    research = [articles[key] for key in brief.source_article_ids if key in articles]
    research_md = folder / RESEARCH_FILE
    company = load_company(settings.company_file)
    offer = company.offer if company and brief.service != INSIGHT_ONLY else ""
    problems = proof_problems(brief, proof, research)
    try:
        problems += service_problems(brief, load_services(settings.services_file))
    except ServicesError as error:
        problems.append(str(error))
    problems += insight_problems(
        brief, research_md.read_text(encoding="utf-8") if research_md.is_file() else "", articles
    )
    platforms: dict[str, str] = {}  # brief part -> platform
    caption_platforms: dict[str, str] = {}  # deliverable -> platform
    if brief.deliverables:
        try:
            catalog = load_deliverables(settings.deliverables_file)
            for key in brief.deliverables:
                item = catalog.deliverables.get(key)
                if item is not None and item.platform:
                    platforms[item.brief_format] = item.platform
                    caption_platforms[key] = item.platform
        except DeliverableError:
            pass  # reported by the deliverable checks
    problems += post_problems(brief) + caption_problems(brief, offer, caption_platforms)
    problems += banned_problems(brief)
    if load_content(settings.content_file).for_platform(brief.platform) == "de":
        problems += check_texts(reader_texts(brief)).errors  # v5 R1.6: the German pass
    try:
        system = load_design_system(settings.design_system_file)
        problems = carousel_problems(brief, system, platforms, offer) + problems
    except WorkflowError as error:
        problems.append(str(error))
    if any(slot is not None and slot.direction for slot in (brief.post, brief.carousel)):
        try:
            problems = direction_problems(brief, load_directions(), settings) + problems
        except DirectionError as error:
            problems.append(str(error))
    if any(slot is not None and slot.post_format for slot in (brief.post, brief.carousel)):
        try:
            problems = format_problems(brief, load_formats(settings.post_formats_file),
                                       research) + problems
        except FormatError as error:
            problems.append(str(error))
    return problems


def _in_brief_words(message: str) -> str:
    """Name brief.json fields instead of command-line flags: --sub-highlight -> subHighlight."""

    def field_name(match: re.Match[str]) -> str:
        first, *rest = match.group(1).split("-")
        return first + "".join(part.capitalize() for part in rest)

    return re.sub(r"--([a-z]+(?:-[a-z]+)*)", field_name, message)


def _marked(slot: ImageSlot) -> str:
    """The headline with its highlight words marked like *word* (for the card)."""
    words = {word.casefold() for phrase in slot.highlight for word in phrase.split()}
    return " ".join(f"*{word}*" if word.casefold().strip(".,:;!?") in words else word
                    for word in (slot.headline or "").split())


def _planned_roman(folder: Path) -> bool | None:
    """v5 R6.3: package.json requiresRoman, set at stage 1 (None for an older package)."""
    try:
        data = json.loads((folder / PACKAGE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("requiresRoman") if isinstance(data, dict) else None
    return value if isinstance(value, bool) else None


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
        points=STEP_SEPARATOR.join(slot.points) or None,
        audience_line=slot.audience_line,
        slide=slot.slide,
        slide_role=slot.slide_role,
        no_person=slot.person is False,
        scene=slot.scene,
        wardrobe=slot.wardrobe,
        props=slot.props,
        logo=True,
        aspect_ratio=aspect,
        count=count,
        request=request,
        card=None if slot.templated else json.dumps(
            {"platform": brief.platform, "headline": _marked(slot),
             **(slot.card.model_dump(by_alias=True, exclude_none=True) if slot.card else {})},
            ensure_ascii=False),
        history=history,
        context=" ".join([brief.topic, brief.audience, brief.objective, *brief.key_points]),
        post_format=slot.post_format,
        format_copy=json.dumps(slot.copy_text, ensure_ascii=False) if slot.templated else None,
        topic=brief.topic,
        direction=slot.direction,
        direction_platform=brief.platform,
        requires_roman=_planned_roman(folder) if slot.direction else None,
    )
    if slot.templated and slot.slides:  # a static carousel: one image per slide
        total = len(slot.slides)
        return [
            replace(
                base,
                format_copy=json.dumps(slide.copy_text, ensure_ascii=False),
                slide_type=slide.direction_role if slot.direction else slide.type,
                prompt=slide.illustration or "",
                logo=number == total,  # the logo on the last slide only
                slide=f"{number}/{total}",
                count=1,
                request=f"{request}, slide {number}/{total}",
            )
            for number, slide in enumerate(slot.slides, start=1)
        ]
    if not slot.slides:
        return [base]
    total = len(slot.slides)
    person = (1, total)  # the first and last slides show the man; the middle ones do not
    return [
        replace(
            base,
            layout=slot.layout if number in person else None,
            audience_line=slot.audience_line if number == 1 else None,
            pose=slot.pose if number in person else None,
            wardrobe=slot.wardrobe if number in person else None,
            headline=slide.headline,
            highlight=", ".join(slide.highlight) or None,
            subheadline=slide.subheadline,
            sub_highlight=slide.sub_highlight,
            visual=slide.visual,
            chat="|".join(f"{bubble.speaker}: {bubble.text}" for bubble in slide.chat) or None,
            diagram=STEP_SEPARATOR.join(slide.diagram) or None,
            mini_checklist=STEP_SEPARATOR.join(slide.checklist) or None,
            before_after=(
                f"{slide.before_after.before}{STEP_SEPARATOR}{slide.before_after.after}"
                if slide.before_after else None
            ),
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
    settings: Settings | None = None  # this part's provider (the static carousel: OpenRouter)
    size: tuple[int, int] | None = None  # a post format: the final PNG size


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
    created = package.model_dump(mode="json", by_alias=True).get("createdAt")
    others = flatten(recent_packages(settings.packages_dir, exclude=folder,
                                     before=str(created) if created else None))
    picks = {name: item.picks for name, item in package.items.items() if item.picks is not None}
    plans: dict[str, _ImagePlan] = {}
    catalog = _formats(settings) if brief.post or brief.carousel else None
    for position, name in enumerate(IMAGE_SLOTS):
        slot: ImageSlot | None = getattr(brief, name)
        item = package.items.get(name)
        if slot is None or (item is not None and item.status == "done"):
            continue
        earlier = [picks[part] for part in IMAGE_SLOTS[:position] if part in picks]
        jobs = _slot_inputs(name, slot, brief, folder, earlier + others, counts[name])
        chosen = None
        if slot.post_format and catalog is not None:
            try:
                chosen = catalog.get(slot.post_format)
            except FormatError:
                chosen = None  # reported by the brief checks
        part_settings = _part_settings(chosen, slot, settings)
        plan = _ImagePlan(slot, jobs, settings=part_settings,
                          size=chosen.size if chosen is not None else None)
        try:
            if len(jobs) == 1 and jobs[0].count > 1:
                # One job per image: each image is checked on its own and can be made again
                # alone (same inputs, so the same look).
                plan.jobs = [replace(jobs[0], count=1) for _ in range(jobs[0].count)]
            for position, inputs in enumerate(plan.jobs, start=1):
                try:
                    plan.prepared.append(prepare_workflow("social_creative", inputs,
                                                          part_settings))
                except WorkflowError as error:  # name the slide or image it is about
                    where = "slide" if slot.format == "carousel" else "image"
                    raise WorkflowError(f"{where} {position}: {error}") from None
        except _IMAGE_ERRORS as error:
            plan.prepared = []
            plan.error = error
        if plan.prepared and plan.prepared[0].picks is not None:
            picks[name] = plan.prepared[0].picks
        plans[name] = plan
    return plans


def _image_job(item: PackageItem, position: int, settings: Settings) -> tuple[Job, str] | None:
    """The job and output file behind one image of a part (position 0 = the first image)."""
    job_id, _, name = item.image_refs[position].partition("/")
    folders = item.image_folders[position:position + 1] or (
        [item.job_folder] if item.job_folder and position == len(item.image_refs) - 1 else []
    )
    candidates = [Path(folder) / DETAILS_FILE for folder in folders]
    candidates += sorted(settings.output_dir.glob(f"*/*/{DETAILS_FILE}"), reverse=True)
    for details in candidates:
        try:
            job = Job.load(details)
        except (OSError, ValueError):
            continue
        if job.job_id == job_id:
            return job, name
    return None


def _check(
    item: PackageItem, position: int, check: ReviewCheck, settings: Settings
) -> str | None:
    """"pass", "fail" or None for one check of one image."""
    found = _image_job(item, position, settings)
    if found is None:
        return None
    review = found[0].review(found[1], check)
    return review.result if review is not None else None


def _person_copy_problems(plans: dict[str, "_ImagePlan"], settings: Settings) -> list[str]:
    """Live fix: a person post on ComfyUI is the app's branded card; its copy limits depend
    on personImage.mode (scene: tag, headline 3-7 words with one highlight, German subtitle,
    3 bullets with icons, CTA in English and German). Ads keep their own rules."""
    if settings.image_provider != "comfyui":
        return []
    config = compose_config(settings)
    allowed = tuple(person_card(settings)["icons"].get("allowed", ()))
    problems = []
    for kind, plan in plans.items():
        if kind != "post" or plan.slot.templated or not any(
                prepared.person_shown for prepared in plan.prepared):
            continue
        slot = plan.slot
        card = slot.card
        copy = Copy(slot.headline or "",
                    (card.subtitle if card and card.subtitle else None) or slot.subheadline
                    or slot.audience_line or "",
                    bullets=tuple(slot.points), tag=card.tag or "" if card else "",
                    icons=tuple(card.icons) if card else (),
                    cta_en=card.cta_en or "" if card else "",
                    cta_de=card.cta_de or "" if card else "", highlight=tuple(slot.highlight))
        problems += [f"{kind}: {problem}" for problem in copy_problems(copy, config,
                                                                       icons=allowed)]
    return problems


def _review_note(item: PackageItem, position: int, settings: Settings) -> str:
    found = _image_job(item, position, settings)
    review = found[0].review(found[1], "person") if found is not None else None
    return (review.note if review is not None else None) or "differs"


def _reject_check(job: Job, name: str, reason: str) -> None:
    """An automatic check failed: recorded on the image and its result never reused (D-6)."""
    job.add_review(name, "fail", reason, check="person")
    scope = runtime.current()
    found = find_by_result(scope.conn, job.folder.as_posix()) if scope is not None else None
    if found is not None and not found.rejected_at:
        runtime.reject(found.id, reason)


def _failed_twice(item: PackageItem, kind: str, position: int, folder: Path
                  ) -> tuple[PackageItem, list[str]]:
    """A failed person check that is not redone by itself (Codex's look, or the automatic
    checks a second time): failed, the reasons, the user's choice."""
    file = item.files[position] if position < len(item.files) else f"{kind} image {position + 1}"
    reasons = "; ".join(item.person_reasons.get(position, [])) or "no reason recorded"
    item.status = "failed"
    item.error = f"person check failed for {file}: {reasons}"
    no_person = ("the ad always shows him: only the retry" if kind == "ad" else
                 'the no-person version (LinkedIn posts: "post": {"person": false} in '
                 "brief.json; Facebook posts always show him)")
    return item, [
        f"{kind}: {item.error}.",
        "  Show the user the image and the reasons, then offer: 1) a retry: a new dry run, "
        f'uv run ca content build "{folder}" --dry-run, and after their "ok" --authorize '
        f"<dryrun_id>; 2) {no_person}. Never choose for the user.",
    ]


def _person_shown(item: PackageItem, position: int, settings: Settings) -> bool:
    found = _image_job(item, position, settings)
    return found is not None and found[0].inputs.get("personShown") is True


def _ad_claim_problems(brief: ContentBrief, folder: Path) -> list[str]:
    """Ad strict check (Phase 7): a number in the ad's overlay or copy must come from the ad
    copy saved with `ca script save` (whose check needs verified fact claims for numbers)."""
    ad = brief.ad
    if ad is None:
        return []
    texts = [text for text in (ad.headline, ad.subheadline, ad.cta, ad.primary_text)
             if text and re.search(r"\d", text)]
    scope = runtime.current()
    if not texts or scope is None:
        return []
    item_id = runtime.package_items(folder).get("ad")
    if item_id is None:
        return []
    saved = latest_artifact(scope.conn, item_id, "copy")
    if saved is not None and saved.check.get("ok"):
        try:
            script = json.loads(Path(saved.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            script = {}
        written = " ".join(str(s.get("text", "")) for s in script.get("sections", []))
        if all(text.strip() in written for text in texts):
            return []
    return [f"ad: number without verified source ({'; '.join(texts)}): write the ad copy with "
            f"`uv run ca script save {item_id} <file>` so its numbers cite verified claims"]


def image_checks(item: PackageItem, settings: Settings) -> list[str]:
    """"post-1.png person pass", … for the review view (recorded checks only)."""
    lines = []
    for position in range(min(len(item.files), len(item.image_refs))):
        for check in ("person", "set"):
            result = _check(item, position, check, settings)
            if result is not None:
                lines.append(f"{Path(item.files[position]).name} {check} {result}")
    return lines


def _todo(plan: _ImagePlan, item: PackageItem | None, settings: Settings) -> list[int]:
    """Positions still to make: missing ones, and those that failed a check."""
    if item is None or item.status not in ("failed", "review") or not item.image_refs:
        return list(range(len(plan.jobs)))
    redo = {
        position for position in range(min(len(item.image_refs), len(plan.jobs)))
        if _check(item, position, "person", settings) == "fail"
        or (position > 0 and _check(item, position, "set", settings) == "fail")
    }
    missing = range(len(item.image_refs), len(plan.jobs))
    asked = {position for position in item.redo if position < len(plan.jobs)}
    return sorted(redo | set(missing) | asked)


def _identity_photos(job: Job, settings: Settings) -> list[Path]:
    set_id = str(job.inputs.get("identitySet") or settings.default_identity_set)
    try:
        ref_set = load_set(set_id, settings.references_dir)
    except ReferenceLibraryError:
        return []
    photos = ref_set.primary_assets or ref_set.ok_assets
    return [(ref_set.folder / a.file).resolve() for a in photos[:IDENTITY_PHOTOS_TO_COMPARE]]


def _identity_sheet(job: Job, name: str, image: Path, settings: Settings) -> Path | None:
    """Phase D: the image beside 2 approved real photos (config/design_directions.json
    roman.approvedPhotos), saved in the job folder; None when they are not on this machine."""
    set_id = str(job.inputs.get("identitySet") or settings.default_identity_set)
    try:
        rules = load_directions().roman
        photos = approved_photos(rules, settings.references_dir / set_id)
        return identity_sheet(image, photos[:IDENTITY_PHOTOS_TO_COMPARE],
                              job.folder / f"identity_sheet_{Path(name).stem}.png")
    except (DirectionError, RomanError, OSError, ValueError):
        return None


def _cost_text(job: Job, settings: Settings) -> str:
    cost = f"${job.est_cost_usd:.3f}" if job.est_cost_usd else "the price of 1 image"
    return f"about {cost} per image via {settings.image_provider}"


def _person_lines(
    item: PackageItem, position: int, folder: Path, settings: Settings, *, waiting: bool = False
) -> list[str]:
    """The person check: compare with his photos, record, ask before making it again."""
    found = _image_job(item, position, settings)
    file = item.files[position]
    if found is None:
        return [f"PERSON CHECK for {file}: its job record is missing; make the part again."]
    job, name = found
    head = (
        f"PERSON CHECK (still not recorded) for {file}"
        if waiting
        else f"PERSON CHECK: stop here. {file} shows the person."
    )
    earlier = item.person_reasons.get(position, [])
    redo = ((f"  Made again once already ({'; '.join(earlier)})." if earlier else "")
            + "  Only a failed automatic check (text, no face, face too small) is made again "
            "once; your look is reported to the user, never redone by itself.")
    raw = raw_image(job.folder, name) if job.provider == "comfyui" else None
    checked = ("Raw checks (automatic: no text, one face, big enough): passed." if raw else
               "Face check (automatic): " + ("skipped (mock image, no face to find)."
                                             if job.provider == "mock" else "passed."))
    view = (f"  View the RAW photo: {raw.resolve()} (the composed post: "
            f"{(folder / file).resolve()})" if raw else f"  View it: {(folder / file).resolve()}")
    sheet = _identity_sheet(job, name, raw or folder / file, settings)
    return [
        head,
        f"  {checked}",
        view,
        (f"  Identity sheet (the image beside approved real photos): {sheet.resolve()}"
         if sheet is not None else "  beside his photos: "
         + ", ".join(str(path) for path in _identity_photos(job, settings))),
        "  Look at the one raw photo beside the 2 reference photos (never pass one you did "
        "not look at) and report whether it looks like Roman (hair, build, facial hair, age); "
        "no stray text or trigger word, hands and face free of obvious defects. Record it:",
        f'    uv run ca job review "{job.folder}" --image {name} --person pass "<what you saw>"',
        f'    uv run ca job review "{job.folder}" --image {name} --person fail "<what differs>"',
        redo,
        f'  A pass: uv run ca content build "{folder}" (continues). A fail: tell the user '
        f"what differs; they choose a retry (new dry run, {_cost_text(job, settings)}) or the "
        "no-person version.",
    ]


def _set_lines(
    item: PackageItem, positions: list[int], folder: Path, settings: Settings
) -> list[str]:
    """The set check: every image of the set against the first one."""
    lines = [
        "SET CHECK: stop here. Compare each image below with the first one of the set "
        f"({(folder / item.files[0]).resolve()}): the same two fonts and text sizes, the same "
        "colours, the same layout family (panel, decor, scene treatment). Record each one:",
    ]
    cost = ""
    for position in positions:
        found = _image_job(item, position, settings)
        if found is None:
            lines.append(f"  {item.files[position]}: its job record is missing")
            continue
        job, name = found
        cost = _cost_text(job, settings)
        lines += [
            f"  {(folder / item.files[position]).resolve()}",
            f'    uv run ca job review "{job.folder}" --check set --image {name} --pass',
            f'    uv run ca job review "{job.folder}" --check set --image {name} --fail '
            '"<what differs>"',
        ]
    lines += [
        "  If any differs: stop, show the user those images and ask whether to make them again "
        f"({cost}). Only after a yes: uv run ca content build \"{folder}\" (makes the "
        "failed ones again).",
        f'  When all pass: uv run ca content build "{folder}"   (continues)',
    ]
    return lines


@dataclass
class _Batch:
    """One build's image jobs. warm (provider batch_images, ComfyUI): every image of the
    package is made back-to-back on one warm worker, then the person checks follow; only the
    first job counts the cold start."""

    warm: bool = False
    cold: bool = True  # the next job may meet a cold worker


def _batch(settings: Settings) -> _Batch:
    try:
        warm = get_provider(settings.image_provider, settings).capabilities.batch_images
    except ImageError:  # reported by the image plans
        warm = False
    return _Batch(warm=warm)


def _make_images(
    kind: str,
    plan: _ImagePlan,
    folder: Path,
    settings: Settings,
    previous: PackageItem | None,
    batch: _Batch | None = None,
) -> tuple[PackageItem, list[str]]:
    """Make the part's missing images; the lines are a check that stops the build.

    Person check: right after each image with the man (a warm batch: after all of them, see
    _Batch). Set check: once every image of a set exists, each one against the first. A failed
    image is made again (after the user agreed) in its own place; the others are kept.
    """
    batch = batch or _Batch()
    unchecked: list[int] = []  # a warm batch: images with the person, checked afterwards
    now = datetime.now(UTC)
    keep = previous is not None and previous.status in ("failed", "review") and bool(
        previous.image_refs
    )
    if keep and previous is not None:
        item = previous.model_copy(update={"error": None, "updated_at": now}, deep=True)
        for position in range(len(item.image_refs)):  # a person check still to record
            if _person_shown(item, position, settings) and _check(
                item, position, "person", settings
            ) is None:
                item.status = "review"
                return item, _person_lines(item, position, folder, settings, waiting=True)
    else:
        item = PackageItem(status="failed", updated_at=now)
    if len(item.image_folders) < len(item.image_refs):  # an item from before this field
        item.image_folders += [""] * (len(item.image_refs) - len(item.image_folders))
    todo = _todo(plan, item if keep else None, settings)
    scope = runtime.current()
    if scope is not None and scope.authorizations:  # a new "ok": an authorized retry
        item.person_redos = {}
        # Keep Codex's rejection of the old image so the authorized retry can replace it;
        # automatic face-check failures get their one fresh-seed retry per authorization.
        item.person_reasons = {
            position: [reason for reason in reasons if reason.startswith("Codex check:")]
            for position, reasons in item.person_reasons.items()
            if any(reason.startswith("Codex check:") for reason in reasons)
        }
    for position in todo:  # Codex says it is not Roman: reported, never redone by itself
        if keep and position < len(item.image_refs) and _check(
                item, position, "person", settings) == "fail" and not any(
                reason.startswith("Codex") for reason in item.person_reasons.get(position, [])):
            reason = _review_note(item, position, settings)
            item.person_reasons.setdefault(position, []).append(f"Codex check: {reason}")
            return _failed_twice(item, kind, position, folder)
    queue = list(todo)
    while queue:
        position = queue.pop(0)
        inputs = plan.jobs[position]
        if (position > 0 and plan.slot.format == "carousel" and item.image_refs
                and not plan.slot.templated):
            # Later slides attach slide 1 (it passed the person check): one scene and design.
            inputs = replace(inputs, first_slide=item.image_refs[0])
        try:
            job = run_workflow("social_creative", inputs, settings, cold_start=batch.cold)
        except _IMAGE_ERRORS as error:
            item.status, item.error = "failed", str(error)
            return item, []
        batch.cold = False
        item.job_id, item.job_folder = job.job_id, str(job.folder)
        item.job_ids.append(job.job_id)
        item.est_cost_usd = _add_cost(item.est_cost_usd, job.est_cost_usd)
        if job.status != "completed":
            item.status, item.error = "failed", job.error
            item.cost_usd = _add_cost(item.cost_usd, job.actual_cost_usd)
            return item, []
        (folder / IMAGES_DIR).mkdir(exist_ok=True)
        name = job.outputs[0]  # one image per job
        target = folder / IMAGES_DIR / f"{kind}-{position + 1}{Path(name).suffix}"
        shutil.copyfile(job.folder / name, target)
        if plan.size is not None:
            _fit_size(target, plan.size)
        entry = (f"{IMAGES_DIR}/{target.name}", f"{job.job_id}/{name}", str(job.folder))
        if position < len(item.image_refs):  # made again in its own place
            item.files[position], item.image_refs[position], item.image_folders[position] = entry
            if position in item.redo:
                item.redo.remove(position)
        else:
            item.files.append(entry[0])
            item.image_refs.append(entry[1])
            item.image_folders.append(entry[2])
        cost = job.actual_cost_usd if job.actual_cost_usd is not None else job.est_cost_usd
        item.cost_usd = _add_cost(item.cost_usd, cost)
        checked = image_problems(target)
        if checked:  # Phase 7: size and not blank; never retried by itself
            item.status = "failed"
            item.error = f"image check {target.name}: {'; '.join(checked)}"
            return item, [f"{kind}: {item.error}; make it again only after the user agrees"]
        faces = check_job_image(job, name, settings) if job.inputs.get("personShown") else []
        if faces:  # Track L face check (free, local): made again once, then stop
            reason = "face check: " + "; ".join(faces)
            _reject_check(job, name, reason)
            item.person_reasons.setdefault(position, []).append(reason)
            if item.person_redos.get(position, 0) < 1:
                item.person_redos[position] = item.person_redos.get(position, 0) + 1
                queue.insert(0, position)
                continue
            return _failed_twice(item, kind, position, folder)
        if item.picks is None:
            item.picks = DesignPicks.from_recorded(job.inputs, job.style_asset_ids)
        if job.inputs.get("personShown") is True and batch.warm:
            unchecked.append(position)
        elif job.inputs.get("personShown") is True:
            item.status = "review"
            item.error = f"person check pending: {item.files[position]}"
            return item, _person_lines(item, position, folder, settings)
    if unchecked:  # a warm batch: all images are made; now the person checks, one per build
        item.status = "review"
        item.error = "person check pending: " + ", ".join(item.files[p] for p in unchecked)
        lines = _person_lines(item, unchecked[0], folder, settings)
        if len(unchecked) > 1:
            later = ", ".join(item.files[p] for p in unchecked[1:])
            lines.append(f"  Then the next build shows the next check ({later}).")
        return item, lines
    if len(plan.jobs) > 1:
        pending = [
            position for position in range(1, len(plan.jobs))
            if _check(item, position, "set", settings) is None
        ]
        if pending:
            item.status = "review"
            item.error = "set check pending: " + ", ".join(item.files[p] for p in pending)
            return item, _set_lines(item, pending, folder, settings)
    item.status, item.error = "done", None
    return item, []


def _fit_size(path: Path, size: tuple[int, int]) -> None:
    """A post format's PNG at its exact size (e.g. 1080x1350): centre crop, then Lanczos."""
    with Image.open(path) as source:
        image = source.convert("RGB")
    if image.size != size:
        image = ImageOps.fit(image, size, Image.Resampling.LANCZOS)
        image.save(path, format="PNG", optimize=True)


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
            missing.append(f"{LABELS[kind]}: check pending")
        elif state == "failed":
            missing.append(f"{LABELS[kind]} failed")
    return DONE_STATUS if not missing else f"{DONE_STATUS} — " + ", ".join(missing)


def _item_line(kind: str, item: PackageItem) -> str:
    cost = ""
    if item.cost_usd and item.est_cost_usd is not None:  # estimate vs actual, every build
        cost = f" (${item.cost_usd:.4f}; estimate ${item.est_cost_usd:.4f})"
    elif item.cost_usd:
        cost = f" (${item.cost_usd:.4f})"
    if item.status == "done":
        return f"{LABELS[kind]}: done{cost}: {', '.join(item.files)}"
    return f"{LABELS[kind]}: {item.status}{cost}" + (f": {item.error}" if item.error else "")


def _dry_run_lines(
    folder: Path,
    brief: ContentBrief,
    package: ContentPackage,
    plans: dict[str, _ImagePlan],
    settings: Settings,
) -> tuple[list[str], float, dict[str, float], dict[str, float]]:
    """The dry-run lines, the image total, the image cost per part and, per part, the cost of
    one automatic redo of each image with the person (Track L: in the max, not the estimate)."""
    costs: dict[str, float] = {}
    redos: dict[str, float] = {}
    lines = [
        "DRY RUN: nothing is made and nothing is spent.",
        f"Package: {folder}",
        f"Topic: {brief.topic} | platform: {brief.platform} | "
        f"formats: {', '.join(brief.formats)}",
    ]
    catalog = _formats(settings) if package.format else None
    if package.format:
        try:
            label = catalog.get(package.format).label() if catalog else package.format
        except FormatError:
            label = f"{package.format} (not in config/post_formats.json)"
        lines.append(f"Post format: {label}")
    if package.direction:
        try:
            found = load_directions().find(package.direction)
        except DirectionError:
            found = None
        lines.append("Design direction: " + (found.label if found is not None else
                     f"{package.direction} (not in config/design_directions.json)"))
    total = 0.0
    used: set[str] = set()
    names = _part_names(brief, settings)
    batch = _batch(settings)  # a warm batch counts one cold start for the whole package
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
        part = plan.settings or settings
        used.add(part.image_provider)
        todo = [plan.prepared[position] for position in _todo(plan, item, part)]
        cost = redo = 0.0
        for prepared in todo:
            own = prepared.settings or part  # a template slide: no picture, free
            cold = batch.cold if part is settings else True
            cost += estimate_cost_usd(prepared.request, own, cold_start=cold)
            batch.cold = batch.cold and part is not settings
            if prepared.person_shown:
                redo += estimate_cost_usd(prepared.request, own, cold_start=False)
        total += cost
        costs[kind] = round(cost, 6)
        redos[kind] = round(redo, 6)
        lead = plan.prepared[0]
        request = lead.request
        slot = plan.slot
        if len(plan.prepared) > 1:
            unit = "slides" if slot.format == "carousel" else "images"
            images = f"{len(todo)} of {len(plan.prepared)} {unit}"
        else:
            images = f"{request.count} image{'s' if request.count > 1 else ''}"
        layout = f", layout {slot.layout}" if slot.layout else ""
        if lead.inputs.get("postFormat"):
            layout = f", post format {lead.inputs['postFormat']}"
        title = slot.headline or slot.stat or (slot.slides[0].headline if slot.slides else "")
        if not title and slot.copy_text:
            first = next(iter(slot.copy_text.values()))
            title = first if isinstance(first, str) else (first[0] if first else "")
        picks: dict[str, str] = {}
        if lead.picks is not None:
            picks = lead.picks.model_dump(exclude={"format", "style_refs"}, exclude_none=True)
        look = ", ".join(f"{name} {value}" for name, value in picks.items()) or "-"
        person = "the man shown" if lead.inputs.get("personShown") else "no person"
        if slot.person is False:
            person = "no person (left out by the writer: the topic fits without him)"
        if lead.design is not None:  # Phase D: a design direction
            generated = [prepared for prepared in todo
                         if (prepared.settings or part).image_provider != "template"]
            source = (f"{len(generated)} picture(s) via {part.image_provider}" if generated
                      else "no picture (template, free)")
            layouts = ", ".join(dict.fromkeys(str(p.inputs.get("layout")) for p in plan.prepared))
            who = ("Roman via his LoRA (person check after)" if lead.person_shown
                   else "no generated person")
            lines.append(
                f"{names[kind]}: {images}, direction {slot.direction} ({layouts}), \"{title}\"; "
                f"{source}; {who}; "
                f"text, logo, footer and icons drawn by the app, then the design check: "
                f"about ${cost:.3f}"
            )
        else:
            lines.append(
                f"{names[kind]}: {images} x {request.aspect_ratio} {request.image_size} "
                f'(format {slot.format}{layout}), "{title}"; picked: {look}; '
                f"{person}, {len(request.identity_refs)} identity + {len(request.style_refs)} "
                f"style images (people-free and logo-free when he is shown), logo pasted by the "
                f"app, via {part.image_provider}: about ${cost:.3f}"
            )
        if lead.inputs.get("postFormat"):
            lines.append(f"  text: {lead.inputs.get('textOverlay')}")
        if lead.inputs.get("postFormat") and len(plan.prepared) > 1:
            kinds = [str(prepared.inputs.get("slideType")) for prepared in plan.prepared]
            pictures = sum(1 for prepared in plan.prepared
                           if (prepared.settings or part).image_provider != "template")
            hashtags = len(brief.hashtags)
            width, height = plan.size or (1080, 1350)
            lines.append(
                f"  static carousel: {len(kinds)} PNG slides at {width}x{height} "
                f"({', '.join(kinds)}); {pictures} picture(s) (the cover) via "
                f"{part.image_provider} ({part.image_model}), the other slides rendered by the "
                "app (template, free); the logo on the last slide only; "
                f"caption.txt ({hashtags} hashtags) and alt_text.txt go to Drive with the PNGs"
            )
        elif slot.format == "carousel" and len(plan.prepared) > 1 and lead.design is None:
            last = len(plan.prepared)
            lines.append(
                "  slides 2+ also attach slide 1's image (same scene, design and colours); "
                f"slides 1 and {last} show the man, slides 2-{last - 1} no person; no slide "
                "numbers"
            )
        checked = [n for n, prepared in enumerate(plan.prepared, start=1) if prepared.person_shown]
        if checked:
            which = "each image" if len(checked) == len(plan.prepared) else (
                f"images {' and '.join(map(str, checked))}"
            )
            if batch.warm:
                lines.append(
                    f"  person check: for {which}, after every image of the package is made "
                    "back-to-back on one warm GPU worker; one check per build"
                )
            else:
                lines.append(
                    f"  person check: the build stops after {which} so Codex can compare each "
                    "with his photos before anything else is made"
                )
            lines.append(
                "  automatic face check, then Codex's look; a fail is made again once with a "
                f"new seed (the max includes it: +${redos[kind]:.3f}); a second fail stops"
            )
        if len(plan.prepared) > 1:
            lines.append(
                "  set check: when all images exist, the build stops once more so Codex can "
                "compare images 2+ with the first (fonts, colours, layout family)"
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
        f"Estimated image cost: ${total:.3f} ({', '.join(sorted(used)) or settings.image_provider}"
        "). Run again without --dry-run to build."
    )
    try:
        basis = get_provider(settings.image_provider, settings).capabilities.cost_basis
    except ImageError:  # already reported with the image parts above
        basis = ""
    if basis:  # GPU time (ComfyUI): an estimate; the build shows estimate vs actual
        lines.insert(-1, f"Image cost basis: {basis}")
    return lines, round(total, 6), costs, redos


def _caption_file_text(brief: ContentBrief) -> str:
    """caption.txt: the carousel's caption and hashtags, ready to paste."""
    caption = brief.captions.get("instagram_carousel") or brief.caption or next(
        iter(brief.captions.values()), None
    )
    parts = []
    if caption is not None:
        parts += [
            caption.hook.strip(),
            "\n".join(f"- {line.strip()}" for line in caption.takeaways),
            caption.question.strip(),
        ]
    parts += [f"{brief.cta.strip()} {brief.link}", " ".join(brief.hashtags)]
    return "\n\n".join(parts) + "\n"


def _alt_text_file_text(brief: ContentBrief) -> str:
    """alt_text.txt: one line per slide, ready to paste into Instagram's alt text."""
    slides = brief.carousel.slides if brief.carousel is not None else []
    return "".join(f"Slide {number}: {(slide.alt_text or '').strip()}\n"
                   for number, slide in enumerate(slides, start=1))


def _carousel_texts(brief: ContentBrief, folder: Path, item: PackageItem) -> None:
    """The finished static carousel: caption.txt (caption + hashtags) and alt_text.txt beside
    the slide PNGs, so the Drive sync uploads them to Instagram/<Content ID>/."""
    for name, text in (("caption.txt", _caption_file_text(brief)),
                       ("alt_text.txt", _alt_text_file_text(brief))):
        path = folder / CAROUSEL_DIR / name
        path.parent.mkdir(exist_ok=True)
        atomic_write_text(path, text)
        relative = path.relative_to(folder).as_posix()
        if relative not in item.files:
            item.files.append(relative)


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
            *(f"- {line.strip()}" for line in caption.takeaways),
            "",
            caption.question.strip(),
            *([caption.closing_de.strip()] if caption.closing_de else []),
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


def load_package(folder: Path) -> ContentPackage:
    """package.json of a package folder; OSError or ValueError when missing or invalid."""
    return ContentPackage.model_validate_json((folder / PACKAGE_FILE).read_text(encoding="utf-8"))


def save_package(folder: Path, package: ContentPackage) -> None:
    _save(folder, package)


__all__ = [
    "DONE_STATUS",
    "BriefError",
    "PackageResult",
    "build_package",
    "load_package",
    "save_package",
    "start_package",
]
