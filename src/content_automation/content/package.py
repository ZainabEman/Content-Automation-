"""`ca content start` and `ca content build`: one content package per topic.

start: collect news, rank articles for the topic, then create PACKAGES_DIR/YYYY-MM-DD_<slug>/
with research.md, brief.template.json and package.json. Codex then writes brief.json.
build: check brief.json, then make the post images (2), the ad image (1) and the reel (first
frame = post-1) into images/, video/, post.md and package.json. Each part is saved as soon as
it is done; a failed or pending part never blocks the others, and running build again redoes
only what is missing.
"""

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from content_automation.ai.avatar import AvatarError
from content_automation.ai.image import ImageError, estimate_cost_usd
from content_automation.ai.video import VideoError
from content_automation.content.brief import (
    ASPECT_BY_PLATFORM,
    DEFAULT_IDENTITY_SET,
    BriefError,
    ContentBrief,
    ImageSlot,
    load_brief,
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
from content_automation.workflows.image_workflows import (
    WorkflowInputs,
    prepare_workflow,
    run_workflow,
)
from content_automation.workflows.registry import WorkflowError
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
IMAGE_COUNTS = {"post": 2, "ad": 1}
LABELS = {"post": "post images", "ad": "ad image", "reel": "video"}
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
    job_id: str | None = None
    job_folder: str | None = None
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
    atomic_write_text(folder / RESEARCH_FILE, _research_markdown(topic, articles, note))
    template = _brief_template(topic, platform, formats, articles, brand, company)
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
        "and the brand rules in _help; no invented results, statistics, prices or client "
        "names; headlines at most 6 words).",
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


def _brief_template(
    topic: str,
    platform: str,
    formats: list[str],
    articles: list[SourceArticle],
    brand: BrandProfile | None,
    company: CompanyProfile | None,
) -> dict[str, Any]:
    template: dict[str, Any] = {
        "_help": {
            "howTo": (
                f"Save a copy as {BRIEF_FILE} in this folder and replace every <...>. English "
                "only. Use docs/company/services.md and the brand rules below. Never invent "
                "results, statistics, prices or client names. Headlines: at most 6 words. "
                "This _help block is ignored."
            ),
            "services": service_names(brand, company),
            "brandRules": {
                "tone": brand.tone if brand else "",
                "language": "English",
                "avoid": brand.dont if brand else [],
                "contentRules": company.content_rules if company else "",
            },
            "formats": {
                "post": "2 image options: social_creative post with headline, logo, brand style",
                "ad": "1 ad image: social_creative ad with the headline and logo",
                "reel": (
                    "9:16 video; each scene at most 15 s, all scenes at most 90 s; scene 1 "
                    'starts from firstFrame; a scene with "image": "post-1" shows that picture'
                ),
            },
            "topArticles": [f"{a.article_id} | {a.source} | {a.title}" for a in articles],
        },
        "topic": topic,
        "platform": platform,
        "formats": formats,
        "service": "<one of the services in _help>",
        "audience": brand.audience if brand and brand.audience else "<who this is for>",
        "objective": "<what this content should achieve>",
        "keyPoints": ["<key point 1>", "<key point 2>", "<key point 3>"],
        "identitySet": DEFAULT_IDENTITY_SET,
        "sourceArticleIds": [a.article_id for a in articles[:3]],
    }
    scene = "<rich scene: action, setting, light, camera/lens, mood; clean space for the headline>"
    for kind in ("post", "ad"):
        if kind in formats:
            template[kind] = {"headline": "<at most 6 words>", "scene": scene, "withPerson": True}
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
    template["caption"] = "<post text: 2-4 short paragraphs>"
    template["hashtags"] = ["#AIMarketing", "#MarketingAutomation"]
    template["cta"] = "<one clear call to action>"
    return template


# ----------------------------------------------------------------------------- build


def build_package(folder: Path, settings: Settings, *, dry_run: bool) -> PackageResult:
    """Raises BriefError when brief.json is missing or invalid (nothing is made)."""
    brand = _brand(settings)
    company = load_company(settings.company_file)
    known = known_article_ids(settings.research_dir)
    brief = load_brief(
        folder / BRIEF_FILE, services=service_names(brand, company), known_article_ids=known
    )
    package = _load(folder, brief)
    if dry_run:
        return PackageResult(folder, _dry_run_lines(folder, brief, package, settings), package)

    lines: list[str] = []
    for kind in ("post", "ad"):
        item = package.items.get(kind)
        if kind not in brief.formats or (item is not None and item.status == "done"):
            continue
        package.items[kind] = _make_images(kind, brief, folder, settings)
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


def _image_inputs(
    kind: str, slot: ImageSlot, brief: ContentBrief, folder: Path
) -> WorkflowInputs:
    return WorkflowInputs(
        prompt=slot.scene,
        identity_set=brief.identity_set if slot.with_person else None,
        variant=kind,
        headline=slot.headline,
        logo=True,
        aspect_ratio=ASPECT_BY_PLATFORM[brief.platform],
        count=IMAGE_COUNTS[kind],
        request=f"{brief.topic}: {kind} for {brief.platform} (package {folder.name})",
    )


def _make_images(
    kind: str, brief: ContentBrief, folder: Path, settings: Settings
) -> PackageItem:
    slot: ImageSlot = getattr(brief, kind)
    now = datetime.now(UTC)
    try:
        job = run_workflow("social_creative", _image_inputs(kind, slot, brief, folder), settings)
    except _IMAGE_ERRORS as error:
        return PackageItem(status="failed", error=str(error), updated_at=now)
    if job.status != "completed":
        return PackageItem(
            status="failed",
            job_id=job.job_id,
            job_folder=str(job.folder),
            error=job.error,
            cost_usd=job.actual_cost_usd,
            updated_at=now,
        )
    (folder / IMAGES_DIR).mkdir(exist_ok=True)
    files, refs = [], []
    for index, name in enumerate(job.outputs, start=1):
        target = folder / IMAGES_DIR / f"{kind}-{index}{Path(name).suffix}"
        shutil.copyfile(job.folder / name, target)
        files.append(f"{IMAGES_DIR}/{target.name}")
        refs.append(f"{job.job_id}/{name}")
    cost = job.actual_cost_usd if job.actual_cost_usd is not None else job.est_cost_usd
    return PackageItem(
        status="done",
        job_id=job.job_id,
        job_folder=str(job.folder),
        files=files,
        image_refs=refs,
        cost_usd=cost,
        updated_at=now,
    )


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
    folder: Path, brief: ContentBrief, package: ContentPackage, settings: Settings
) -> list[str]:
    lines = [
        "DRY RUN: nothing is made and nothing is spent.",
        f"Package: {folder}",
        f"Topic: {brief.topic} | platform: {brief.platform} | "
        f"formats: {', '.join(brief.formats)}",
    ]
    total = 0.0
    for kind in ("post", "ad"):
        slot: ImageSlot | None = getattr(brief, kind)
        if slot is None:
            continue
        item = package.items.get(kind)
        if item is not None and item.status == "done":
            lines.append(f"{LABELS[kind]}: already done ({', '.join(item.files)}); skipped")
            continue
        try:
            prepared = prepare_workflow(
                "social_creative", _image_inputs(kind, slot, brief, folder), settings
            )
            cost = estimate_cost_usd(prepared.request, settings)
        except _IMAGE_ERRORS as error:
            lines.append(f"{LABELS[kind]}: cannot be made yet: {error}")
            continue
        total += cost
        lines.append(
            f"{LABELS[kind]}: {IMAGE_COUNTS[kind]} x {ASPECT_BY_PLATFORM[brief.platform]}, "
            f'headline "{slot.headline}", via {settings.image_provider}: about ${cost:.3f}'
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
        brief.caption.strip(),
        "",
        "## Call to action",
        "",
        brief.cta.strip(),
        "",
        "## Hashtags",
        "",
        " ".join(brief.hashtags) or "-",
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
