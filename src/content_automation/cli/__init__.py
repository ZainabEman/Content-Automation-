"""Typer command line interface."""

import json
import re
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from content_automation.ai.avatar import AvatarError
from content_automation.ai.image import ASPECT_RATIOS, ImageError, ImageRequest
from content_automation.ai.video import VideoError
from content_automation.cli.bridge import (
    image_cost_line,
    package_registration,
    record_agent_job,
    reject_image_job,
    video_cost_lines,
)
from content_automation.cli.help import help_app
from content_automation.cli.ideas import claims_app, ideas_app
from content_automation.cli.items import audit_app, items_app
from content_automation.cli.jobs import auth_app, costs_app, jobs_app, report_app
from content_automation.cli.scope import (
    authorization_lines,
    authorize,
    registry_scope,
    require_budget,
    save_dry_run_lines,
)
from content_automation.cli.scripts import brief_app, script_app
from content_automation.content.backlog import RunCounts, newest_list, run_newsletters, run_sources
from content_automation.content.brief import BriefError
from content_automation.content.calendar import (
    CalendarError,
    Decision,
    calendar_packages,
    calendar_path,
    check_calendar,
    check_edits,
    generate_rows,
    mark_generated,
    new_calendar,
    parse_rows,
    read_view,
    ready_cost_lines,
    set_status,
    show_lines,
    sync_calendar_view,
    week_label,
)
from content_automation.content.carousel_format import check_format, package_format
from content_automation.content.clips import clips_handoff, clips_import, clips_select
from content_automation.content.deliverables import (
    DeliverableCatalog,
    DeliverableError,
    load_deliverables,
)
from content_automation.content.distribution import (
    copy_template,
    integrations,
    mark_failed,
    mark_published,
    prepare,
    publish_lines,
    save_copy,
)
from content_automation.content.migration import collect_sources, rewrite_old_calendars
from content_automation.content.package import (
    DONE_STATUS,
    build_package,
    carousel_slide_texts,
    finish_carousel,
    load_package,
    save_package,
    set_deliverables,
    start_package,
)
from content_automation.content.plan import (
    blocked_notes,
    load_plan_or_none,
    month_days,
    month_label,
    period,
    period_rows,
    plan_calendar,
)
from content_automation.content.plan_config import plan_only_types
from content_automation.content.podcast import (
    heygen_lines,
    heygen_request,
    make_thumbnail,
    podcast_audio,
    record_heygen,
)
from content_automation.content.production import (
    handoff,
    import_media,
    production_lines,
    set_production,
)
from content_automation.content.research_input import ResearchInputError, load_idea
from content_automation.content.review import (
    apply_regeneration,
    plan_regeneration,
    review_queue,
)
from content_automation.content.review import show_lines as review_show_lines
from content_automation.content.scripts import template_json as script_template_json
from content_automation.content.scripts import template_lines as script_template_lines
from content_automation.content.tracking import TrackerError, status_lines
from content_automation.core.agent_steps import record_agent_output, request_path
from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.core.files import atomic_write_text
from content_automation.core.jobs import DETAILS_FILE, Job, JobStateError, ReviewCheck, slugify
from content_automation.core.limits import DailyLimitError
from content_automation.core.log import configure_logging
from content_automation.core.media import MediaError
from content_automation.doctor import run_checks
from content_automation.lora import (
    LoraError,
    ModelKey,
    load_lora_config,
    newest_dataset,
    prepare_dataset,
    set_lora,
    training_config,
)
from content_automation.lora_remote import plan as remote_plan
from content_automation.lora_remote import result_lines
from content_automation.lora_remote import start as remote_start
from content_automation.lora_remote import status as remote_status
from content_automation.lora_remote import stop as remote_stop
from content_automation.lora_remote import watch as remote_watch
from content_automation.references import (
    REF_TYPES,
    BrandProfileError,
    ReferenceLibraryError,
    brand_path,
    extract_frames,
    list_sets,
    load_brand,
    load_company,
    mask_copies,
    scan,
    select_logo_ref,
    set_primary,
    tag_assets,
)
from content_automation.registry import db_path
from content_automation.registry.db import RegistryError
from content_automation.registry.dryruns import CostLine
from content_automation.registry.ids import resolve
from content_automation.registry.migrate import migrate_candidates
from content_automation.registry.progress import part_done
from content_automation.registry.runtime import Scope
from content_automation.registry.sources import add_source, find_by_url, link_source, set_text_path
from content_automation.registry.strategy import load_strategy
from content_automation.research.collectors import CollectorError
from content_automation.research.fetch import fetch_article, load_newsletters, unwrap
from content_automation.research.models import SourcesError
from content_automation.research.run import (
    DEFAULT_TOPIC_LIMIT,
    digest_lines,
    topic_digest,
    topic_note,
)
from content_automation.research.run import collect as collect_research
from content_automation.research.run import digest as research_digest_articles
from content_automation.storage import (
    EXPORT_NAME,
    FOLDERS,
    ROOT_FOLDER,
    AutoSync,
    StorageError,
    StorageNotSetUpError,
    SyncResult,
    export_tracker,
    get_storage,
    resolve_tracker,
    sync_calendar,
    sync_package,
    tracker_conflicts,
    tracker_lines,
)
from content_automation.storage.review_upload import record_plugin_upload, upload_approved
from content_automation.workflows.carousel_design import load_carousel_design
from content_automation.workflows.carousel_motion import render as render_carousel
from content_automation.workflows.carousel_plugin import (
    clips_check,
    continue_lines,
    record_attempt,
    stills_check,
    summary_lines,
)
from content_automation.workflows.carousel_render import PREVIEW_DIR, extract_style
from content_automation.workflows.carousel_render import preview as carousel_preview_slides
from content_automation.workflows.design_system import load_design_system, resolve_design
from content_automation.workflows.dry_run import dry_run_lines
from content_automation.workflows.image_job import run_image_job
from content_automation.workflows.image_workflows import (
    AD_VARIANTS,
    WorkflowInputs,
    prepare_workflow,
    run_workflow,
)
from content_automation.workflows.logo import LogoError, LogoOverlay, apply_logo
from content_automation.workflows.registry import DEFAULT_STYLE_COUNT, WorkflowError
from content_automation.workflows.text_overlay import (
    SAMPLE_TEXTS,
    apply_text,
    prepare_text_overlay,
)
from content_automation.workflows.video_job import (
    agent_checklist,
    pending_lines,
    prepare_video,
    resume_video_job,
    start_video_job,
)
from content_automation.workflows.video_job import dry_run_lines as video_dry_run_lines
from content_automation.workflows.video_plan import PlanError, load_plan

app = typer.Typer(name="ca", no_args_is_help=True, help="Content Automation CLI.")
refs_app = typer.Typer(no_args_is_help=True, help="Reference photo library.")
brand_app = typer.Typer(no_args_is_help=True, help="Brand profile (brand.json).")
job_app = typer.Typer(no_args_is_help=True, help="Job records, agent steps and person checks.")
env_app = typer.Typer(no_args_is_help=True, help="Set one allowed line in .env (never shown).")
video_app = typer.Typer(help="Short vertical videos (1080x1920) from a plan.json.")
research_app = typer.Typer(no_args_is_help=True, help="News research: collect and digest articles.")
content_app = typer.Typer(
    no_args_is_help=True, help="Content packages: research, brief, images, reel, post text."
)
calendar_app = typer.Typer(
    no_args_is_help=True, help="Content calendar: calendar/<YYYY-Www>.csv (free, nothing made)."
)
drive_app = typer.Typer(
    no_args_is_help=True,
    help="Drive folders and uploads (STORAGE_PROVIDER: mock or drive). A script, not a plugin.",
)
tracking_app = typer.Typer(
    no_args_is_help=True,
    help="Content Tracker (Google Sheet; mock: tracking.csv): statuses and a CSV export.",
)
overlay_app = typer.Typer(
    no_args_is_help=True,
    help="Text the app renders for image providers that draw no text (local and free).",
)
carousel_app = typer.Typer(
    no_args_is_help=True,
    help="Animated Instagram carousel: style frames, previews, plugin records, checks and the "
    "final MP4s (local, free).",
)
lora_app = typer.Typer(
    no_args_is_help=True,
    help="The person's LoRA for ComfyUI: dataset, AI Toolkit config, trained file (local, free).",
)
app.add_typer(refs_app, name="refs")
app.add_typer(brand_app, name="brand")
app.add_typer(job_app, name="job")
app.add_typer(video_app, name="video")
app.add_typer(research_app, name="research")
app.add_typer(content_app, name="content")
app.add_typer(calendar_app, name="calendar")
app.add_typer(drive_app, name="drive")
app.add_typer(tracking_app, name="tracking")
app.add_typer(overlay_app, name="overlay")
app.add_typer(carousel_app, name="carousel")
app.add_typer(lora_app, name="lora")
app.add_typer(env_app, name="env")
app.add_typer(items_app, name="item")
review_app = typer.Typer(no_args_is_help=True, help="The review gate: what waits, one item.")
app.add_typer(review_app, name="review")
app.add_typer(costs_app, name="costs")
app.add_typer(report_app, name="report")
production_app = typer.Typer(no_args_is_help=True, help="YouTube and podcast production.")
app.add_typer(production_app, name="production")
podcast_app = typer.Typer(no_args_is_help=True, help="Podcast recording (HeyGen) and audio.")
app.add_typer(podcast_app, name="podcast")
clips_app = typer.Typer(no_args_is_help=True, help="Opus Pro clips from a finished video.")
app.add_typer(clips_app, name="clips")
copy_app = typer.Typer(no_args_is_help=True, help="Per-platform copy (Phase 6 checks).")
app.add_typer(copy_app, name="copy")
publish_app = typer.Typer(no_args_is_help=True, help="What is ready; record published posts.")
app.add_typer(publish_app, name="publish")
app.add_typer(audit_app, name="audit")
app.add_typer(jobs_app, name="jobs")
app.add_typer(help_app, name="help")
app.add_typer(ideas_app, name="ideas")
app.add_typer(claims_app, name="claims")
app.add_typer(script_app, name="script")
app.add_typer(brief_app, name="brief")
app.add_typer(auth_app, name="auth")
registry_app = typer.Typer(no_args_is_help=True, help="The content-item registry.")
app.add_typer(registry_app, name="registry")
AuthorizeOption = Annotated[
    str | None,
    typer.Option("--authorize", help='The dry run ID the user said "ok" to (DR-...).'),
]
# The only .env lines a command may set: IDs chosen by the user in a plugin, never keys.
ENV_SETTABLE = ("HEYGEN_AVATAR_ID", "HEYGEN_VOICE_ID")
_ENV_VALUE = re.compile(r"[A-Za-z0-9_-]{1,128}")

JobDir = Annotated[Path, typer.Argument(help="Job folder (the one with details.json).")]
StepOption = Annotated[str, typer.Option("--step", help="Step ID, e.g. scene-1.")]


@app.callback()
def _root() -> None:
    """Root command for the Content Automation CLI."""


@contextmanager
def _registry(settings: Settings, command: str) -> Iterator[Scope]:
    """The registry for this command (jobs, authorizations, item statuses); a registry error is
    one line on stderr and exit code 1."""
    try:
        with registry_scope(settings, command) as scope:
            yield scope
    except RegistryError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None


def _settings(*, dry_run: bool = False, check_keys: bool = True) -> Settings:
    """Load settings; a dry run needs no API key and creates no folders.

    check_keys=False skips the API-key check for commands whose providers need none.
    """
    try:
        return load_settings(
            require_credentials=check_keys and not dry_run, create_directories=not dry_run
        )
    except ConfigurationError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None


@app.command()
def hello() -> None:
    """Show a safe summary of the local configuration."""
    settings = _settings()

    typer.echo(f"Hello, {settings.user_name}.")
    typer.echo("Configuration summary (credential values hidden):")
    for line in settings.summary_lines():
        typer.echo(f"  {line}")


@app.command()
def image(
    prompt: Annotated[
        str,
        typer.Option(
            help="Scene description (raw mode: the full prompt). Optional for social_creative."
        ),
    ] = "",
    workflow: Annotated[
        str | None,
        typer.Option(
            help="person_lifestyle, person_service or social_creative. Omit for raw mode."
        ),
    ] = None,
    identity_set: Annotated[
        str | None, typer.Option("--set", help="Identity set, e.g. identity/person_01.")
    ] = None,
    service: Annotated[
        str | None,
        typer.Option(help='person_service: the service shown, e.g. "Tax advice for startups".'),
    ] = None,
    product: Annotated[
        str | None, typer.Option(help="social_creative: product set, e.g. product/mug.")
    ] = None,
    style: Annotated[
        str | None, typer.Option(help="Style set, e.g. creative/facebook_ads.")
    ] = None,
    style_count: Annotated[
        int | None,
        typer.Option(help=f"Style images to send (default {DEFAULT_STYLE_COUNT}).", min=1),
    ] = None,
    variant: Annotated[
        str | None, typer.Option(help="Old name of --kind: post (= organic), ad, carousel_slide.")
    ] = None,
    format_: Annotated[
        str | None,
        typer.Option(
            "--format",
            help="social_creative: ad (default), statement, stat, news, carousel, person_photo "
            "or checklist.",
        ),
    ] = None,
    kind: Annotated[
        str | None,
        typer.Option(help="social_creative: organic (default), ad, story or carousel_slide."),
    ] = None,
    layout: Annotated[
        str | None,
        typer.Option(
            help="A text + system visual (no person), B text + person, C person + text, "
            "D before/after split."
        ),
    ] = None,
    pose: Annotated[
        str | None,
        typer.Option(help="A pose from the pools in config/design_system.json (default: picked)."),
    ] = None,
    scene: Annotated[
        str | None,
        typer.Option(help="A scene from the pools, or your own words (default: picked)."),
    ] = None,
    wardrobe: Annotated[
        str | None,
        typer.Option(help="A wardrobe from the pools, or your own words (default: picked)."),
    ] = None,
    props: Annotated[
        str | None,
        typer.Option(help="Props from the pools, or your own words (default: picked)."),
    ] = None,
    stat: Annotated[
        str | None, typer.Option(help='Format stat: the one big number, e.g. "73%".')
    ] = None,
    source: Annotated[
        str | None,
        typer.Option(help="Format stat/news: ID of the research article it comes from."),
    ] = None,
    source_name: Annotated[
        str | None,
        typer.Option(
            help='Format stat: the publisher shown as "Source: ..." (default: the article\'s).'
        ),
    ] = None,
    audience_line: Annotated[
        str | None,
        typer.Option(help='Statement, stat, checklist, carousel hook: "For dental practices".'),
    ] = None,
    chat: Annotated[
        str | None,
        typer.Option(help='Carousel tip: 2-3 bubbles, "Customer: ...|Bot: ...".'),
    ] = None,
    diagram: Annotated[
        str | None,
        typer.Option(help='Carousel middle slide: 3-4 steps, "Lead asks|Bot answers|CRM".'),
    ] = None,
    mini_checklist: Annotated[
        str | None,
        typer.Option(help='Carousel middle slide: 3 checklist rows, "One|Two|Three".'),
    ] = None,
    before_after: Annotated[
        str | None,
        typer.Option(help='Carousel middle slide: "<before>|<after>", each at most 12 words.'),
    ] = None,
    points: Annotated[
        str | None,
        typer.Option(help='Post (statement, checklist, news): 3 key points, "One|Two|Three".'),
    ] = None,
    first_slide: Annotated[
        str | None,
        typer.Option(
            help="Format carousel, slides 2+: slide 1's image as <jobId>/image-1.png "
            "(same scene, decor and colours)."
        ),
    ] = None,
    steps: Annotated[
        str | None,
        typer.Option(help='Format checklist: 3-5 short steps separated by "|".'),
    ] = None,
    headline: Annotated[
        str | None, typer.Option(help="Headline, shown exactly as written in capitals.")
    ] = None,
    highlight: Annotated[
        str | None,
        typer.Option(help="1-2 headline words in the highlight colour, comma-separated."),
    ] = None,
    subheadline: Annotated[
        str | None, typer.Option(help="Subheadline, shown exactly as written.")
    ] = None,
    sub_highlight: Annotated[
        str | None, typer.Option(help="One subheadline word in the highlight colour.")
    ] = None,
    cta: Annotated[str | None, typer.Option(help='CTA button label, e.g. "Learn more".')] = None,
    cta_icon: Annotated[
        str | None,
        typer.Option(help="arrow, calendar or play (default: chosen from the CTA label)."),
    ] = None,
    icons: Annotated[
        str | None,
        typer.Option(help='Icon row: 3-4 labels of 1-2 words, e.g. "Chatbots,CRM,Email".'),
    ] = None,
    visual: Annotated[
        str | None, typer.Option(help="Layout A: the system visual shown on the right.")
    ] = None,
    slide: Annotated[
        str | None, typer.Option(help="carousel_slide: slide number as N/TOTAL, e.g. 2/5.")
    ] = None,
    slide_role: Annotated[
        str | None,
        typer.Option(help="carousel_slide: hook, tip or cta (default: from --slide)."),
    ] = None,
    logo: Annotated[
        bool, typer.Option("--logo", help="Add the brand logo (social_creative always does).")
    ] = False,
    aspect: Annotated[
        str | None,
        typer.Option(
            help=f"Aspect ratio: {', '.join(ASPECT_RATIOS)} (default: workflow's; raw mode 1:1)."
        ),
    ] = None,
    count: Annotated[
        int | None,
        typer.Option(min=1, max=4, help="Number of variations (1-4; default 1, ads 3)."),
    ] = None,
    request: Annotated[
        str | None, typer.Option(help="The original plain-English request, for the record.")
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Show prompt, references, calls and cost; make nothing."
        ),
    ] = False,
    authorize_id: AuthorizeOption = None,
) -> None:
    """Generate images and save them with a details.json record. A paid provider needs the
    dry run's ID after the user's "ok": --authorize <dryrun_id>."""
    _utf8_output()
    settings = _settings(dry_run=dry_run)
    if not dry_run:
        configure_logging(settings)
    if count is None:
        count = AD_VARIANTS if (kind or variant) == "ad" else 1
    inputs = WorkflowInputs(
        prompt=prompt,
        identity_set=identity_set,
        product_set=product,
        style_set=style,
        style_count=style_count,
        variant=variant,
        headline=headline,
        logo=logo,
        aspect_ratio=aspect,
        count=count,
        request=request,
        service=service,
        format=format_,
        kind=kind,
        layout=layout,
        pose=pose,
        scene=scene,
        wardrobe=wardrobe,
        props=props,
        stat=stat,
        source=source,
        source_name=source_name,
        steps=steps,
        first_slide=first_slide,
        audience_line=audience_line,
        chat=chat,
        diagram=diagram,
        mini_checklist=mini_checklist,
        before_after=before_after,
        points=points,
        highlight=highlight,
        subheadline=subheadline,
        sub_highlight=sub_highlight,
        cta=cta,
        cta_icon=cta_icon,
        icons=icons,
        visual=visual,
        slide=slide,
        slide_role=slide_role,
    )
    command = f"ca image --workflow {workflow or 'raw'}" + (" --dry-run" if dry_run else "")
    try:
        raw = _raw_request(inputs) if workflow is None else None
        if dry_run:
            for line in _dry_run(workflow, inputs, settings):
                typer.echo(line)
            cost, extra = _image_cost(workflow, inputs, settings)
            with _registry(settings, command) as scope:
                for line in save_dry_run_lines(settings, scope, "image", [cost], extra):
                    typer.echo(line)
            return
        with _registry(settings, command) as scope:
            if authorize_id:
                cost, extra = _image_cost(workflow, inputs, settings)
                for line in authorization_lines(
                    authorize(settings, scope, authorize_id, "image", [cost], extra)
                ):
                    typer.echo(line)
            if raw is not None:
                job = run_image_job(raw, settings, user_request=inputs.request)
            else:
                assert workflow is not None
                job = run_workflow(workflow, inputs, settings)
    except (
        WorkflowError,
        ReferenceLibraryError,
        BrandProfileError,
        DailyLimitError,
        ImageError,
        RegistryError,
    ) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None

    if job.status != "completed":
        typer.echo(f"Failed: {job.error}", err=True)
        typer.echo(str(job.folder), err=True)
        raise typer.Exit(code=1)
    typer.echo(str(job.folder))


def _dry_run(workflow: str | None, inputs: WorkflowInputs, settings: Settings) -> list[str]:
    if workflow is None:
        return dry_run_lines(_raw_request(inputs), settings, workflow="raw (prompt as written)")
    prepared = prepare_workflow(workflow, inputs, settings)
    lines = dry_run_lines(
        prepared.request,
        settings,
        workflow=f"{prepared.spec.workflow_id} (v{prepared.spec.version})",
        product_refs=prepared.product_refs,
        logo=prepared.logo,
        text=prepared.text,
    )
    if prepared.picks is not None:  # what the design takes from the pools (saved with the job)
        picks = prepared.picks.model_dump(exclude={"style_refs"}, exclude_none=True)
        chosen = ", ".join(f"{name} {value}" for name, value in picks.items())
        lines.insert(lines.index("References (attached in this order):"), f"Design: {chosen}")
    return lines


def _image_cost(workflow: str | None, inputs: WorkflowInputs, settings: Settings
                ) -> tuple[CostLine, str]:
    """The direct run's cost line and what must stay the same between dry run and build."""
    request = (_raw_request(inputs) if workflow is None
               else prepare_workflow(workflow, inputs, settings).request)
    line = image_cost_line(request, settings, label=workflow or "raw")
    extra = json.dumps([workflow, settings.image_provider, settings.image_model,
                        asdict(inputs)], sort_keys=True, default=str)
    return line, extra


def _raw_request(inputs: WorkflowInputs) -> ImageRequest:
    """Raw mode: the prompt is sent as written, without references or brand rules."""
    if inputs.provided() or inputs.style_count is not None:
        raise WorkflowError(
            "Options other than --prompt, --aspect, --count and --request need --workflow."
        )
    if not inputs.prompt.strip():
        raise WorkflowError("--prompt cannot be empty (or pick a --workflow).")
    try:
        return ImageRequest(
            prompt=inputs.prompt,
            aspect_ratio=inputs.aspect_ratio or "1:1",  # type: ignore[arg-type]
            count=inputs.count,
        )
    except ValidationError as error:
        fields = sorted({str(issue["loc"][0]) for issue in error.errors()})
        message = f"Invalid image request: {', '.join(fields)}."
        if "aspect_ratio" in fields:
            message += f" Aspect must be one of {', '.join(ASPECT_RATIOS)}."
        raise WorkflowError(message) from None


@refs_app.command("scan")
def refs_scan() -> None:
    """Register reference folders in place and write set.json files."""
    settings = _settings()
    try:
        report = scan(settings.references_dir)
    except ReferenceLibraryError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for ref_set in report.sets:
        typer.echo(
            f"{ref_set.set_id}: {len(ref_set.ok_assets)} ok, "
            f"{len(ref_set.rejected_assets)} rejected, {len(ref_set.primary_assets)} primary"
        )
        for asset in ref_set.rejected_assets:
            typer.echo(f"  rejected {asset.file}: {asset.reason}")
    for skipped in report.skipped:
        typer.echo(f"skipped {skipped.path}: {skipped.reason}")
    for warning in report.warnings:
        typer.echo(f"warning: {warning}", err=True)
    typer.echo(f"{len(report.sets)} sets scanned, {len(report.skipped)} folders skipped.")


@refs_app.command("mask")
def refs_mask() -> None:
    """Make the masked copies listed in config/references.json (logos covered), then rescan.

    Designs use only these copies of the past ads; the originals are never sent.
    """
    settings = _settings()
    try:
        made = mask_copies(settings.references_dir)
        report = scan(settings.references_dir)
    except ReferenceLibraryError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for name in made:
        typer.echo(f"masked {name}")
    typer.echo(f"{len(made)} masked copies made; {len(report.sets)} sets scanned.")


@refs_app.command("frames")
def refs_frames() -> None:
    """Extract 3 still frames (10%, 50%, 90%) from each reference video into _frames/."""
    settings = _settings()
    report = extract_frames(settings.references_dir)
    for label in report.extracted:
        typer.echo(f"extracted {label}")
    for label, reason in report.failed:
        typer.echo(f"failed {label}: {reason}", err=True)
    typer.echo(
        f"{len(report.extracted)} videos extracted, {len(report.skipped)} already done, "
        f"{len(report.failed)} failed. Run `ca refs scan` next."
    )
    if report.failed:
        raise typer.Exit(code=1)


@refs_app.command("list")
def refs_list(
    type_: Annotated[
        str | None, typer.Option("--type", help=f"Only one type: {', '.join(REF_TYPES)}.")
    ] = None,
) -> None:
    """Show scanned sets with ok, rejected and primary counts."""
    settings = _settings()
    if type_ is not None and type_ not in REF_TYPES:
        typer.echo(f"--type must be one of: {', '.join(REF_TYPES)}.", err=True)
        raise typer.Exit(code=1)
    sets = list_sets(type_, settings.references_dir)
    if not sets:
        typer.echo("No sets found. Run `ca refs scan` first.")
        return
    width = max(len("set"), *(len(s.set_id) for s in sets))
    typer.echo(
        f"{'type':<9} {'set':<{width}} {'ok':>3} {'rejected':>8} {'primary':>7} {'untagged':>8}"
    )
    for ref_set in sets:
        untagged = str(len(ref_set.untagged_assets)) if ref_set.type == "creative" else "-"
        typer.echo(
            f"{ref_set.type:<9} {ref_set.set_id:<{width}} {len(ref_set.ok_assets):>3} "
            f"{len(ref_set.rejected_assets):>8} {len(ref_set.primary_assets):>7} {untagged:>8}"
        )


@refs_app.command("primary")
def refs_primary(
    set_id: Annotated[str, typer.Option("--set", help="Identity set, e.g. identity/person_01.")],
    files: Annotated[str, typer.Option(help="Comma-separated file names, at most 4.")],
) -> None:
    """Choose the primary photos (max 4) sent for an identity set."""
    settings = _settings()
    try:
        ref_set = set_primary(set_id, files.split(","), settings.references_dir)
    except ReferenceLibraryError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    chosen = ", ".join(asset.file for asset in ref_set.primary_assets)
    typer.echo(f"{ref_set.set_id} primary: {chosen}")


def _yes_no(value: str, flag: str) -> bool:
    answer = value.strip().lower()
    if answer not in ("yes", "no"):
        typer.echo(f"{flag} must be yes or no.", err=True)
        raise typer.Exit(code=2)
    return answer == "yes"


@refs_app.command("tag")
def refs_tag(
    asset: Annotated[
        list[str], typer.Option("--asset", help="Asset ID (repeat for several images).")
    ],
    people: Annotated[
        str, typer.Option(help="yes if it shows a person, face, hand or human figure.")
    ],
    logo: Annotated[str, typer.Option(help="yes if it shows a logo, wordmark or brand mark.")],
) -> None:
    """Record what a style image shows, after viewing it (saved in its set.json).

    Designs with the person use only images tagged people no + logo no; images with a logo
    are never sent.
    """
    settings = _settings(dry_run=True)
    try:
        tagged = tag_assets(
            asset,
            people=_yes_no(people, "--people"),
            logo=_yes_no(logo, "--logo"),
            root=settings.references_dir,
        )
    except ReferenceLibraryError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for name in tagged:
        typer.echo(f"tagged {name}: people {people}, logo {logo}")


@brand_app.command("show")
def brand_show() -> None:
    """Show a short summary of brand.json."""
    settings = _settings()
    try:
        brand = load_brand(settings.references_dir)
    except BrandProfileError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"{brand.brand_name} ({brand.status})")
    typer.echo("Colors: " + ", ".join(f"{c.name} {c.hex}" for c in brand.colors))
    typer.echo("Fonts: " + (", ".join(f"{f.name} ({f.usage})" for f in brand.fonts) or "-"))
    typer.echo(f"Language: {brand.language or '-'}")
    typer.echo(f"Tone: {brand.tone or '-'}")
    typer.echo(f"Audience: {brand.audience or '-'}")
    typer.echo(f"Content pillars: {', '.join(brand.content_pillars) or '-'}")
    typer.echo(f"Services: {', '.join(brand.services) or '- (add them to brand.json)'}")
    typer.echo(f"Do: {len(brand.do)} rules; Don't: {len(brand.dont)} rules")
    if brand.needs_review:
        typer.echo("Needs review:")
        for item in brand.needs_review:
            typer.echo(f"  - {item}")


def _load_job(job_dir: Path) -> Job:
    folder = job_dir.parent if job_dir.name == DETAILS_FILE else job_dir
    details = folder / DETAILS_FILE
    if not details.is_file():
        typer.echo(f"No {DETAILS_FILE} in {folder}.", err=True)
        raise typer.Exit(code=1)
    try:
        return Job.load(details)
    except (OSError, ValueError) as error:
        typer.echo(f"Cannot read {details}: {error}", err=True)
        raise typer.Exit(code=1) from None


@job_app.command("status")
def job_status(job_dir: JobDir) -> None:
    """Show a job and its steps; agent steps waiting too long are marked failed."""
    settings = _settings(dry_run=True)  # job commands call no provider and need no key
    job = _load_job(job_dir)
    timeout_min = settings.agent_step_timeout_min
    expired = job.expire_steps(timeout_min)
    now = datetime.now(UTC)
    typer.echo(f"{job.job_id} ({job.workflow_id}): {job.status}")
    typer.echo(f"Folder: {job.folder}")
    for step in job.steps:
        line = f"  {step.step_id}: {step.status} ({step.capability}, {step.provider}, {step.mode})"
        if step.file:
            line += f" -> {step.file}"
        typer.echo(line)
        if step.status == "awaiting_agent":
            waited = int((now - step.created_at).total_seconds() // 60)
            request = request_path(job.folder, step.step_id).relative_to(job.folder)
            typer.echo(f"    request: {request.as_posix()} (waiting {waited} of {timeout_min} min)")
        if step.error:
            typer.echo(f"    error: {step.error}")
    if job.error:
        typer.echo(f"Error: {job.error}")
    if expired:
        typer.echo(f"Timed out, marked failed: {', '.join(expired)}", err=True)


@job_app.command("complete")
def job_complete(
    job_dir: JobDir,
    step: StepOption,
    file: Annotated[Path, typer.Option("--file", help="The file the agent saved.")],
    provider_job_id: Annotated[
        str | None, typer.Option(help="The provider's job or request ID.")
    ] = None,
    credits: Annotated[
        float | None, typer.Option(min=0, help="Credits the provider charged.")
    ] = None,
) -> None:
    """Record an agent step's file; it is copied into the job folder."""
    job = _load_job(job_dir)
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca job complete {job.job_id} --step {step}"):
        try:
            saved = record_agent_output(
                job, step, file, provider_job_id=provider_job_id, credits_used=credits
            )
        except (JobStateError, OSError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from None
        note = record_agent_job(job.folder, step, credits=credits,
                                result=(job.folder / saved).as_posix())
    typer.echo(f"{step} completed: {job.folder / saved}")
    if note:
        typer.echo(note)
    waiting = [waiting_step.step_id for waiting_step in job.waiting_steps()]
    if waiting:
        typer.echo(f"Still waiting for: {', '.join(waiting)}")
    else:
        typer.echo("All agent steps are done; the job can continue.")


@job_app.command("fail")
def job_fail(
    job_dir: JobDir,
    step: StepOption,
    error: Annotated[str, typer.Option("--error", help="What went wrong.")],
) -> None:
    """Record that an agent step failed; the whole job ends as failed."""
    job = _load_job(job_dir)
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca job fail {job.job_id} --step {step}"):
        try:
            job.fail_step(step, error)
        except JobStateError as state_error:
            typer.echo(str(state_error), err=True)
            raise typer.Exit(code=1) from None
        note = record_agent_job(job.folder, step, error=error)
    typer.echo(f"{step} failed; job {job.job_id} is now failed.")
    if note:
        typer.echo(note)


@job_app.command("review")
def job_review(
    job_dir: JobDir,
    image: Annotated[str, typer.Option(help="The output file checked.")] = "image-1.png",
    passed: Annotated[
        bool, typer.Option("--pass", help="It is the identity person.")
    ] = False,
    failed: Annotated[
        str | None,
        typer.Option("--fail", help="It is not him: what differs (hair, build, beard, age)."),
    ] = None,
    note: Annotated[
        str | None, typer.Option(help='With --pass: e.g. "accepted by the user".')
    ] = None,
    check: Annotated[
        str,
        typer.Option(
            help="person: is it him? set: does it match the first image of its set (fonts, "
            "colours, layout family)?"
        ),
    ] = "person",
) -> None:
    """Record a person or set check of an image (saved in details.json; the newest counts)."""
    if check not in ("person", "set"):
        typer.echo("--check must be person or set.", err=True)
        raise typer.Exit(code=2)
    if passed == (failed is not None):
        typer.echo("Give exactly one of --pass or --fail \"<what differs>\".", err=True)
        raise typer.Exit(code=2)
    job = _load_job(job_dir)
    try:
        kind: ReviewCheck = "set" if check == "set" else "person"
        if failed is not None:
            job.add_review(image, "fail", failed.strip() or "differs", check=kind)
        else:
            job.add_review(image, "pass", note, check=kind)
    except JobStateError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    if failed is not None:  # the result is never reused: the next image is a redo (D-6)
        settings = _settings(dry_run=True)
        with _registry(settings, f"ca job review {job.job_id} --fail") as scope:
            reject_image_job(scope.conn, job.folder, f"{check} check failed: {failed.strip()}",
                             command=scope.command)
    result = "passed" if passed else "failed"
    typer.echo(f"{image} of {job.job_id}: {check} check {result} (recorded in {DETAILS_FILE}).")


@env_app.command("set")
def env_set(
    name: Annotated[str, typer.Argument(help=f"One of: {', '.join(ENV_SETTABLE)}.")],
    value: Annotated[str, typer.Argument(help="The ID the user chose.")],
    env_file: Annotated[Path, typer.Option(hidden=True)] = Path(".env"),
) -> None:
    """Set one ID line in .env; nothing else in the file is changed or shown."""
    key = name.strip().upper()
    if key not in ENV_SETTABLE:
        typer.echo(f"Only these can be set here: {', '.join(ENV_SETTABLE)}.", err=True)
        raise typer.Exit(code=2)
    if not _ENV_VALUE.fullmatch(value.strip()):
        typer.echo("The ID may contain only letters, digits, - and _.", err=True)
        raise typer.Exit(code=2)
    if not env_file.is_file():
        typer.echo(f"{env_file} not found: copy .env.example to .env first.", err=True)
        raise typer.Exit(code=1)
    lines = env_file.read_text(encoding="utf-8").splitlines()
    line = f"{key}={value.strip()}"
    found = [i for i, text in enumerate(lines) if text.split("=", 1)[0].strip() == key]
    if found:
        lines[found[0]] = line
        for extra in reversed(found[1:]):
            del lines[extra]
    else:
        lines.append(line)
    atomic_write_text(env_file, "\n".join(lines) + "\n")
    typer.echo(f"{key} set in {env_file}.")


@video_app.callback(invoke_without_command=True)
def video(
    ctx: typer.Context,
    plan: Annotated[
        Path | None, typer.Option("--plan", help="The plan.json Codex wrote.")
    ] = None,
    request: Annotated[
        str | None, typer.Option(help="The original plain-English request, for the record.")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Check the plan and show scenes and credits.")
    ] = False,
    authorize_id: AuthorizeOption = None,
) -> None:
    """Make a video from plan.json: check it, make each scene, assemble final.mp4. Plugin
    scenes cost credits: --authorize <dryrun_id> after the user's "ok" to the dry run.

    If a scene waits for Codex (a plugin provider), the job pauses; record each clip with
    `ca job complete`, then run `ca video resume <job folder>`.
    """
    if ctx.invoked_subcommand is not None:
        if plan is not None or request is not None or dry_run:
            typer.echo("--plan, --request and --dry-run belong to `ca video` itself.", err=True)
            raise typer.Exit(code=2)
        return
    if plan is None:
        typer.echo(ctx.get_help())
        raise typer.Exit(code=2)
    # Video, avatar and image scenes need no API key in the MVP (mock or agent providers).
    settings = _settings(dry_run=dry_run, check_keys=False)
    key = f"video {plan.resolve().as_posix()}"
    try:
        prepared = prepare_video(load_plan(plan, check_scenes=False), settings)
        costs = video_cost_lines(prepared, settings)
        if dry_run:
            for line in video_dry_run_lines(prepared, settings):
                typer.echo(line)
            if costs:
                with _registry(settings, f"ca video --plan {plan} --dry-run") as scope:
                    for line in save_dry_run_lines(settings, scope, key, costs):
                        typer.echo(line)
            return
        configure_logging(settings)
        with _registry(settings, f"ca video --plan {plan}") as scope:
            if authorize_id:
                for line in authorization_lines(
                    authorize(settings, scope, authorize_id, key, costs)
                ):
                    typer.echo(line)
            else:
                require_budget(scope, costs, f'uv run ca video --plan "{plan}" --dry-run')
            job = start_video_job(plan, settings, request=request)
    except (PlanError, VideoError, AvatarError, RegistryError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    _report_video(job, settings)


@video_app.command("resume")
def video_resume(job_dir: JobDir) -> None:
    """Continue a paused video: once every step is recorded, assemble final.mp4."""
    settings = _settings(check_keys=False)
    configure_logging(settings)
    job = _load_job(job_dir)
    try:
        with _registry(settings, f"ca video resume {job.job_id}"):
            job = resume_video_job(job, settings)
    except (VideoError, AvatarError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    _report_video(job, settings)


def _report_video(job: Job, settings: Settings) -> None:
    if job.status == "completed":
        for note in job.notes:
            typer.echo(note)
        typer.echo(f"Completed: {job.folder / 'final.mp4'}")
        typer.echo(str(job.folder))
        return
    if job.status == "awaiting_agent":
        for line in agent_checklist(job):
            typer.echo(line)
        typer.echo(f"Status: awaiting_agent ({job.folder})")
        return
    held = pending_lines(job, settings)
    if held:  # a content package's video waits for a real provider
        for line in held:
            typer.echo(line)
        typer.echo(f"Status: video pending ({job.folder})")
        return
    typer.echo(f"Failed: {job.error or job.status}", err=True)
    typer.echo(str(job.folder), err=True)
    raise typer.Exit(code=1)


def _utf8_output() -> None:
    """Article titles can contain any character; print them as UTF-8 for Codex."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


@research_app.command("collect")
def research_collect() -> None:
    """Collect new articles from every active source in config/sources.json."""
    _utf8_output()
    settings = _settings(check_keys=False)
    try:
        report, path = collect_research(settings)
    except (SourcesError, CollectorError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for stats in report.sources:
        typer.echo(
            f"{stats.source} ({stats.via or 'not reached'}): {stats.new} new, "
            f"{stats.duplicates} duplicates, {stats.too_old} too old, {stats.no_date} undated, "
            f"{stats.blocked} blocked by robots.txt, {stats.failed} failed"
        )
        for problem in stats.errors:
            typer.echo(f"  error: {problem}")
    typer.echo(f"Total: {report.new} new, {report.duplicates} duplicates. Report: {path}")


@research_app.command("fetch")
def research_fetch(
    urls: Annotated[list[str], typer.Argument(help="One or more links (newsletter or article).")],
    idea: Annotated[str | None, typer.Option(help="Link the sources to this idea (BG-x).")] = None,
    source_type: Annotated[
        str, typer.Option("--type", help="newsletter (a link from a newsletter) or web.")
    ] = "web",
) -> None:
    """Follow each link to the original article and save it as a source ("research this link").
    Free HTTP; robots.txt, timeout and size limit respected; failures are listed per link."""
    _utf8_output()
    if source_type not in ("newsletter", "web"):
        typer.echo("--type must be newsletter or web.", err=True)
        raise typer.Exit(code=2)
    settings = _settings(check_keys=False)
    newsletters = load_newsletters(settings.newsletters_file)
    failed = 0
    with _registry(settings, f"ca research fetch {' '.join(urls)}"
                   + (f" --idea {idea}" if idea else "")) as scope:
        idea_id = resolve(scope.conn, idea) if idea else None
        for url in urls:
            known = find_by_url(scope.conn, url, unwrap(url))
            if known is not None:
                if idea_id:
                    link_source(scope.conn, idea_id, known.id, role=source_type,
                                command=scope.command)
                typer.echo(f"{known.id}: already a source ({known.original_url or known.url}); "
                           "not fetched again.")
                continue
            result = fetch_article(url, newsletters.limits)
            if result.error is not None or not result.text:
                failed += 1
                typer.echo(f"{url}: not fetched: {result.error or 'no text'}")
                continue
            sender = newsletters.sender_for(url)
            source, _ = add_source(
                scope.conn, "newsletter" if source_type == "newsletter" else "web", url=url,
                original_url=result.original_url, title=result.title,
                publisher=result.publisher, language=result.language,
                published_at=result.published_at,
                fetched_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                purpose=sender.purpose if sender else None, command=scope.command,
            )
            text_file = settings.research_dir / "sources" / f"{source.id}.txt"
            text_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(text_file, result.text + "\n")
            set_text_path(scope.conn, source.id, text_file.as_posix())
            if idea_id:
                link_source(scope.conn, idea_id, source.id, role=source_type,
                            command=scope.command)
            typer.echo(f"{source.id}: {result.title or '(no title)'} ({result.publisher or '?'}, "
                       f"{result.published_at or 'no date'}) <- {result.original_url}; text "
                       f"{text_file.as_posix()}" + (f"; linked to {idea_id}" if idea_id else ""))
    if failed:
        typer.echo(f"{failed} of {len(urls)} link(s) not fetched.", err=True)
        raise typer.Exit(code=1)


@research_app.command("run")
def research_run(
    sources: Annotated[
        bool, typer.Option("--sources", help="The enabled scraper sources.")
    ] = False,
    newsletters: Annotated[
        bool, typer.Option("--newsletters", help="The newest newsletter content list.")
    ] = False,
    list_file: Annotated[
        Path | None, typer.Option("--list", help="A content list file (default: the newest).")
    ] = None,
    limit: Annotated[int, typer.Option(min=1, help="At most this many article ideas.")] = 20,
) -> None:
    """Find new ideas ("find new ideas"): scraper articles and newsletter ideas into the backlog,
    duplicates merged, off-strategy ones flagged; prints the run counts. Both without options."""
    _utf8_output()
    settings = _settings(check_keys=False)
    both = not sources and not newsletters
    counts = RunCounts()
    try:
        strategy = load_strategy(settings.strategy_file)
        with _registry(settings, "ca research run" + (" --sources" if sources else "")
                       + (" --newsletters" if newsletters else "")) as scope:
            if sources or both:
                run_sources(scope.conn, settings, strategy, counts, limit=limit,
                            command=scope.command)
            if newsletters or both:
                chosen = list_file or newest_list(settings)
                if chosen is None:
                    counts.lines.append("No newsletter content list yet: run show content.")
                else:
                    run_newsletters(scope.conn, settings, strategy,
                                    load_newsletters(settings.newsletters_file), chosen, counts,
                                    command=scope.command)
    except (SourcesError, CollectorError, OSError, ValueError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for line in counts.lines:
        typer.echo(line)
    typer.echo(counts.summary())


@research_app.command("digest")
def research_digest(
    topic: Annotated[
        str | None, typer.Option(help='Rank by relevance to a topic, e.g. "AI chatbots".')
    ] = None,
    days: Annotated[int, typer.Option(min=1, help="Only articles from the last N days.")] = 14,
    limit: Annotated[
        int | None,
        typer.Option(min=1, help="At most N articles (default 10 with --topic)."),
    ] = None,
) -> None:
    """Compact list of saved articles for Codex: id, source, date, title, snippet."""
    _utf8_output()
    settings = _settings(dry_run=True)
    if topic:
        result = topic_digest(settings, topic, days, limit or DEFAULT_TOPIC_LIMIT)
        articles = [ranked.article for ranked in result.articles]
        header = f'{len(articles)} articles for "{topic}" from the last {days} days (best first):'
    else:
        articles = research_digest_articles(settings, days)[:limit]
        header = f"{len(articles)} articles from the last {days} days (newest first):"
    if not articles:
        typer.echo(f"No articles from the last {days} days. Run `uv run ca research collect`.")
        return
    typer.echo(header)
    if topic and (note := topic_note(result)):
        typer.echo(note)
    for line in digest_lines(articles):
        typer.echo(line)


@content_app.command("start")
def content_start(
    topic: Annotated[
        str | None,
        typer.Option(help='What it is about, e.g. "AI chatbots" (default: the idea title).'),
    ] = None,
    deliverables: Annotated[
        str | None,
        typer.Option(
            help='Only if the user already named them, e.g. "insta post, reel" '
            "(see `ca content deliverables`). Leave out to decide later with `ca content set`."
        ),
    ] = None,
    research_file: Annotated[
        Path | None,
        typer.Option(
            help="Research from a file instead of the scraper: the content list JSON saved by "
            "the show-content skill."
        ),
    ] = None,
    idea: Annotated[
        int | None, typer.Option(min=1, help="With --research-file: the idea number to use.")
    ] = None,
    request: Annotated[
        str | None,
        typer.Option(help="The user's own words (stored with the item's approval)."),
    ] = None,
) -> None:
    """Stage 1 (free): research and the package folder with research.md.

    Deliverables are optional here; nothing is built until they are named. An unknown or
    ambiguous name stops with exit code 2 so Codex can ask the user.
    """
    _utf8_output()
    settings = _settings(check_keys=False)
    chosen_idea = None
    try:
        if research_file is not None:
            chosen_idea = load_idea(research_file, idea)
        elif idea is not None:
            raise ResearchInputError("--idea needs --research-file.")
        catalog = load_deliverables(settings.deliverables_file)
        chosen = catalog.resolve(deliverables) if deliverables else []
    except (DeliverableError, ResearchInputError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    title = (topic or "").strip() or (chosen_idea.title if chosen_idea else "")
    if not title:
        typer.echo("Give --topic, or --research-file with --idea.", err=True)
        raise typer.Exit(code=2)
    configure_logging(settings)
    result = start_package(title, chosen, catalog, settings, idea=chosen_idea)
    for line in result.lines:
        typer.echo(line)
    if chosen:
        for line in _register(settings, result.folder, catalog,
                              request or f"make-content: {title}", "ca content start"):
            typer.echo(line)


@content_app.command("set")
def content_set(
    folder: Annotated[Path, typer.Argument(help="The package folder from `ca content start`.")],
    deliverables: Annotated[
        str,
        typer.Option(help='Exactly what the user named, e.g. "facebook ad only".'),
    ],
    request: Annotated[
        str | None,
        typer.Option(help="The user's own words (stored with the item's approval)."),
    ] = None,
) -> None:
    """Stage 2: name the deliverables of a package and write its brief template.

    An unknown or ambiguous name stops with exit code 2 so Codex can ask the user.
    """
    _utf8_output()
    settings = _settings(check_keys=False)
    try:
        catalog = load_deliverables(settings.deliverables_file)
        chosen = catalog.resolve(deliverables)
        result = set_deliverables(folder, chosen, catalog, settings)
    except DeliverableError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    for line in result.lines:
        typer.echo(line)
    for line in _register(settings, folder, catalog, request or f"make-content: {deliverables}",
                          "ca content set"):
        typer.echo(line)


def _register(settings: Settings, folder: Path, catalog: DeliverableCatalog,
              request: str | None, command: str) -> list[str]:
    """The package's items (one per deliverable, D-1/D-3); their BG IDs for Codex."""
    with _registry(settings, f'{command} "{folder}"') as scope:
        return package_registration(scope.conn, folder, catalog, request=request,
                                    command=scope.command)


@content_app.command("deliverables")
def content_deliverables() -> None:
    """List what can be made and the names (aliases) that ask for it."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        catalog = load_deliverables(settings.deliverables_file)
    except DeliverableError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for key, item in catalog.deliverables.items():
        typer.echo(f"{key}: {item.label}")
        typer.echo(f"  names: {', '.join(item.aliases)}")
    typer.echo("Any other word: ask the user which of these they mean.")


@content_app.command("build")
def content_build(
    folder: Annotated[Path, typer.Argument(help="The package folder from `ca content start`.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Check brief.json and show the cost; make nothing.")
    ] = False,
    authorize_id: AuthorizeOption = None,
    carousel_format: Annotated[
        str | None, typer.Option("--format", help="Carousel: static, animated or single_video "
                                 "(default config/carousel.json).")
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", help="Image provider for this build (default: "
                                 "the deliverable's, else IMAGE_PROVIDER).")
    ] = None,
) -> None:
    """Make what is still missing: post images, ad image, reel, post.md, package.json.

    The dry run prints its ID; after the user's "ok" build with --authorize <dryrun_id>. A
    build that continues (after a person or set check) uses the authorization it already has."""
    _utf8_output()
    if not folder.is_dir():
        typer.echo(f"Folder not found: {folder}", err=True)
        raise typer.Exit(code=1)
    # No key check here: a missing key fails only the part that needs it (shown in the status).
    settings = _settings(dry_run=dry_run, check_keys=False)
    if not dry_run:
        configure_logging(settings)
    if provider is not None and provider not in ("mock", "openrouter", "comfyui"):
        typer.echo(f'--provider must be mock, openrouter or comfyui, not "{provider}"', err=True)
        raise typer.Exit(code=2)
    if carousel_format is not None:
        try:
            chosen = check_format(carousel_format)
            saved = load_package(folder)
        except (ValueError, OSError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=2) from None
        saved.carousel_format = chosen
        save_package(folder, saved)
    key = f"content build {folder.resolve().as_posix()}"
    command = f'ca content build "{folder}"' + (" --dry-run" if dry_run else "")
    with _registry(settings, command) as scope:
        try:
            catalog = load_deliverables(settings.deliverables_file)
            for line in package_registration(scope.conn, folder, catalog, request=None,
                                             command=scope.command, legacy=True):
                typer.echo(line)
            preview = build_package(folder, settings, dry_run=True, provider=provider)
            if dry_run:
                for line in preview.lines:
                    typer.echo(line)
                if preview.cost_lines:
                    for line in save_dry_run_lines(settings, scope, key, preview.cost_lines):
                        typer.echo(line)
                return
            if authorize_id:
                for line in authorization_lines(
                    authorize(settings, scope, authorize_id, key, preview.cost_lines)
                ):
                    typer.echo(line)
            else:
                require_budget(scope, preview.cost_lines,
                               f'uv run ca content build "{folder}" --dry-run')
            result = build_package(folder, settings, dry_run=False, provider=provider)
        except (BriefError, DeliverableError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from None
        for line in result.lines:
            typer.echo(line)
        if result.package is None:
            return
        package = result.package
        typer.echo(f"Status: {package.status}")
        typer.echo(f"Folder: {folder.resolve()}")
        for name in sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*")
                           if path.is_file() and not path.name.startswith(".")):
            typer.echo(f"  {name}")
        if package.status == DONE_STATUS:  # every part made: upload the images and MP4s
            for line in AutoSync(settings)(folder):
                typer.echo(line)


WeekOption = Annotated[
    str, typer.Option(help='The ISO week: "next" (default), "this" or e.g. 2026-W42.')
]


@calendar_app.command("new")
def calendar_new(
    week: WeekOption = "next",
    topic: Annotated[
        list[str] | None, typer.Option(help="A user topic; repeat for more. Fills slots first.")
    ] = None,
    idea: Annotated[
        list[int] | None,
        typer.Option(min=1, help="An idea number from the newest newsletter content list."),
    ] = None,
    article: Annotated[
        list[str] | None, typer.Option(help="An article ID from `ca research digest`.")
    ] = None,
    replace: Annotated[
        bool, typer.Option("--replace", help="Make the week again (only if all rows are Proposed).")
    ] = False,
) -> None:
    """Propose the week's calendar: the cadence slots filled with ideas, all rows Proposed.

    Picks go first (topics, ideas, articles), then the newest list and the scraper digest.
    """
    _utf8_output()
    settings = _settings(check_keys=False)
    try:
        label = week_label(week)
        catalog = load_deliverables(settings.deliverables_file)
        with _registry(settings, f"ca calendar new --week {label}"
                       + (" --replace" if replace else "")):
            path, lines = new_calendar(
                settings, catalog, label,
                topics=topic or [], idea_numbers=idea or [], article_ids=article or [],
                replace=replace,
            )
            rows = read_view(path)
    except (CalendarError, DeliverableError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    for line in [*lines, *show_lines(rows)]:
        typer.echo(line)
    typer.echo(sync_calendar(path, settings))


@calendar_app.command("check")
def calendar_check(week: WeekOption = "next") -> None:
    """Check the week's calendar: dates, platforms, content types, sources, repeated topics."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        label = week_label(week)
        catalog = load_deliverables(settings.deliverables_file)
        with _registry(settings, f"ca calendar check --week {label}"):
            check_edits(calendar_path(settings, label))
            problems = check_calendar(
                calendar_path(settings, label), label, catalog, settings.research_dir,
                plan_only_types(settings.calendar_file),
            )
    except (CalendarError, DeliverableError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    if problems:
        typer.echo(f"Calendar {label}: {len(problems)} problem(s):")
        for problem in problems:
            typer.echo(f"- {problem}")
        raise typer.Exit(code=1)
    typer.echo(f"Calendar {label} is OK.")


MonthOption = Annotated[
    str | None, typer.Option(help='The month: "next", "this" or e.g. 2026-11.')
]


@calendar_app.command("show")
def calendar_show(week: WeekOption = "next", month: MonthOption = None) -> None:
    """Show the week's calendar (or --month: the month's rows of every week) as a table."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        catalog = load_deliverables(settings.deliverables_file)
        plan = load_plan_or_none(settings, catalog)
        if month is not None:
            label = month_label(month)
            with _registry(settings, f"ca calendar show --month {label}") as scope:
                rows = period_rows(settings, month_days(label), numbered=True)
                notes = blocked_notes(scope.conn, rows, plan)
            heading = f"Calendar {label}: {len(rows)} row(s) from the week files"
        else:
            label = week_label(week)
            path = calendar_path(settings, label)
            with _registry(settings, f"ca calendar show --week {label}") as scope:
                check_edits(path)
                rows = read_view(path)
                notes = blocked_notes(scope.conn, rows, plan)
            heading = f"Calendar {label}: {path}"
    except (CalendarError, DeliverableError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    typer.echo(heading)
    for line in show_lines(rows, notes):
        typer.echo(line)


@calendar_app.command("plan")
def calendar_plan(
    week: Annotated[
        str | None, typer.Option(help='The ISO week: "next" (default), "this" or 2026-W42.')
    ] = None,
    month: MonthOption = None,
) -> None:
    """Fill the plan slots of config/calendar.json from approved ideas (score, pillar balance);
    rows start Approved, inherited from their idea. Nothing is generated."""
    _utf8_output()
    settings = _settings(check_keys=False)
    try:
        label, days = period(week, month)
        catalog = load_deliverables(settings.deliverables_file)
        strategy = load_strategy(settings.strategy_file)
        flag = "--month" if month else "--week"
        with _registry(settings, f"ca calendar plan {flag} {label}") as scope:
            paths, lines = plan_calendar(settings, catalog, strategy, label, days)
            rows = period_rows(settings, days, numbered=month is not None)
            notes = blocked_notes(scope.conn, rows, load_plan_or_none(settings, catalog))
    except (CalendarError, DeliverableError, RegistryError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    for line in [*lines, *show_lines(rows, notes)]:
        typer.echo(line)
    for path in paths:
        typer.echo(sync_calendar(path, settings))


@calendar_app.command("approve")
def calendar_approve(
    rows: Annotated[list[str], typer.Argument(help='"all" (every Proposed row) or e.g. 1 3 5.')],
    week: WeekOption = "next",
) -> None:
    """Approve rows: Proposed or Rejected -> Approved (the idea gate of each row's item, which
    the output names by BG ID). A generated row never changes here."""
    _calendar_decision(rows, week, "Approved", None)


@calendar_app.command("reject")
def calendar_reject(
    rows: Annotated[list[str], typer.Argument(help="Row numbers, e.g. 2.")],
    week: WeekOption = "next",
    reason: Annotated[
        str | None, typer.Option(help="Why (the make-calendar skill asks the user for it).")
    ] = None,
) -> None:
    """Reject rows: Proposed or Approved -> Rejected (the idea gate of each row's item). A
    generated row never changes here."""
    _calendar_decision(rows, week, "Rejected", reason)


def _calendar_decision(rows: list[str], week: str, status: Decision, reason: str | None) -> None:
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        label = week_label(week)
        numbers = parse_rows(rows, allow_all=status == "Approved")
        catalog = load_deliverables(settings.deliverables_file)
        with _registry(settings, f"ca calendar {'approve' if status == 'Approved' else 'reject'} "
                       f"{' '.join(rows)} --week {label}"):
            lines = set_status(calendar_path(settings, label), numbers, status,
                               catalog=catalog, reason=reason)
    except (CalendarError, DeliverableError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    for line in lines:
        typer.echo(line)
    typer.echo(sync_calendar(calendar_path(settings, label), settings))


@registry_app.command("migrate")
def registry_migrate(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Only list what would be created.")
    ] = False,
) -> None:
    """Register what existed before the registry (calendar rows, packages v1/v2, carousel.json,
    uploads, mock tracker): a backup first, oldest first, BG IDs and aliases, the PRD §9 status
    mapping; old calendar CSVs get the new header. Running it again creates nothing."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        catalog = load_deliverables(settings.deliverables_file)
    except DeliverableError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    command = "ca registry migrate" + (" --dry-run" if dry_run else "")
    with _registry(settings, command) as scope:
        found = collect_sources(settings, catalog)
        report = migrate_candidates(
            scope.conn, db_path(settings.state_dir), found.candidates,
            unreadable=found.unreadable, notes=found.notes, dry_run=dry_run, command=command,
        )
        lines = report.lines(dry_run=dry_run)
        if not dry_run:
            lines += rewrite_old_calendars(settings)
    for line in lines:
        typer.echo(line)


@calendar_app.command("sync")
def calendar_sync(
    week: WeekOption = "next",
    discard_edits: Annotated[
        bool, typer.Option("--discard-edits", help="Overwrite hand edits with the registry.")
    ] = False,
    import_edits: Annotated[
        bool,
        typer.Option("--import-edits",
                     help="Import hand-edited Topic and Planned date (logged); never Status."),
    ] = False,
) -> None:
    """Rewrite the week's CSV from the registry. A hand-edited file shows its diff and needs
    --discard-edits or --import-edits."""
    _utf8_output()
    if discard_edits and import_edits:
        typer.echo("Give only one of --discard-edits or --import-edits.", err=True)
        raise typer.Exit(code=2)
    settings = _settings(dry_run=True)
    try:
        label = week_label(week)
        path = calendar_path(settings, label)
        with _registry(settings, f"ca calendar sync --week {label}"
                       + (" --discard-edits" if discard_edits else "")
                       + (" --import-edits" if import_edits else "")):
            lines = sync_calendar_view(path, discard=discard_edits, take=import_edits)
    except CalendarError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    for line in lines:
        typer.echo(line)
    typer.echo(sync_calendar(path, settings))


@calendar_app.command("generate")
def calendar_generate(
    week: WeekOption = "next",
    build: Annotated[
        bool,
        typer.Option(
            "--build",
            help="Build the ready rows (costs money): only after the user said ok to the "
            "combined dry run.",
        ),
    ] = False,
    authorize_id: AuthorizeOption = None,
) -> None:
    """Approved rows: stage 1 (free) and one combined dry run; --build makes them.

    Failed rows stay Approved, are listed at the end and are never retried by themselves.
    Each package the build finishes is uploaded (Drive sync), then the calendar copy.
    """
    _utf8_output()
    settings = _settings(check_keys=False)
    if build:
        configure_logging(settings)
    try:
        label = week_label(week)
        catalog = load_deliverables(settings.deliverables_file)
        key = f"calendar generate {label}"
        with _registry(settings, f"ca calendar generate --week {label}"
                       + (" --build" if build else "")) as scope:
            if build:
                preview = ready_cost_lines(settings, catalog, label)
                if authorize_id:
                    for line in authorization_lines(
                        authorize(settings, scope, authorize_id, key, preview)
                    ):
                        typer.echo(line)
                else:
                    require_budget(scope, preview,
                                   f"uv run ca calendar generate --week {label} (no --build)")
            costs: list[CostLine] = []
            lines, failed = generate_rows(
                settings, catalog, label, build=build, after_build=AutoSync(settings),
                costs=costs,
            )
            if not build and costs:
                lines += save_dry_run_lines(settings, scope, key, costs)
    except (CalendarError, DeliverableError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=2) from None
    for line in lines:
        typer.echo(line)
    typer.echo(sync_calendar(calendar_path(settings, label), settings))
    if failed:
        typer.echo(f"{len(failed)} row(s) not done (they stay Approved; not retried):")
        for line in failed:
            typer.echo(f"- {line}")
        raise typer.Exit(code=1)


@drive_app.command("setup")
def drive_setup() -> None:
    """Sign in to Google once (browser), then find or make the Drive folders and tracker.

    Content Automation/{LinkedIn,Facebook,Instagram,Calendar} and the "Content Tracker"
    Google Sheet; the main folder is shared as editor with DRIVE_SHARE_WITH (no public
    links). Safe to run again: an existing tracker is never formatted again.
    """
    _utf8_output()
    settings = _settings(check_keys=False)
    try:
        link = get_storage(settings, provider="drive", sign_in=True).ensure_folders()
    except (StorageError, StorageNotSetUpError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Drive is set up: {ROOT_FOLDER}/{{{','.join(FOLDERS)}}} + Content Tracker")
    typer.echo(f"Main folder: {link}")
    shared = [email.strip() for email in settings.drive_share_with.split(",") if email.strip()]
    typer.echo(f"Editors: {', '.join(shared)}" if shared else "Shared with: nobody (private)")
    if settings.storage_provider != "drive":
        typer.echo("Next: set STORAGE_PROVIDER=drive in .env; until then uploads go to "
                   f"{settings.drive_mock_dir} (mock).")


@drive_app.command("sync")
def drive_sync(
    folders: Annotated[
        list[Path] | None,
        typer.Argument(help="Package folders (default: every package named in a calendar)."),
    ] = None,
) -> None:
    """Upload finished images and MP4s to <Platform>/<Content ID>/ ("sync drive").

    Files already uploaded are skipped; failed or missing ones are tried again. Then each
    finished, fully uploaded package gets its Content Tracker row (upsert by Content ID; the
    manager's columns are never written again). Without folders it also refreshes this and
    next week's calendar copies.
    """
    _utf8_output()
    settings = _settings(check_keys=False)
    targets = folders or calendar_packages(settings)
    failed: list[str] = []
    synced: list[tuple[Path, SyncResult]] = []
    with _registry(settings, "ca drive sync"):
        try:
            catalog = load_deliverables(settings.deliverables_file)
            storage = get_storage(settings)
            for folder in targets:
                try:
                    result = sync_package(folder, storage, catalog)
                except (OSError, ValueError):
                    failed.append(f"{folder}: no readable package.json")
                    continue
                except StorageError as error:
                    failed.append(f"{folder}: {error}")
                    continue
                for line in result.lines:
                    typer.echo(line)
                failed += [f"{folder.name}/{line}" for line in result.failed]
                synced.append((folder, result))
        except DeliverableError as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=2) from None
        except (StorageNotSetUpError, StorageError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from None
        for line in tracker_lines(storage, synced):
            typer.echo(line)
    if not targets:
        typer.echo("No packages to sync: no calendar names a package yet.")
    if not folders:
        for label in (week_label("this"), week_label("next")):
            if calendar_path(settings, label).is_file():
                typer.echo(sync_calendar(calendar_path(settings, label), settings))
    if failed:
        typer.echo(f"{len(failed)} upload(s) failed (local files kept; sync drive again to retry):")
        for line in failed:
            typer.echo(f"- {line}")
        raise typer.Exit(code=1)


@tracking_app.command("export")
def tracking_export(
    out: Annotated[
        Path, typer.Option(help="Where to save the CSV on this computer.")
    ] = Path("outputs/content-tracker.csv"),
) -> None:
    """Save the Content Tracker as CSV here and as "Content Tracker.csv" in the main folder.

    The Drive copy is read-only and replaced in place; edits belong in the Sheet itself.
    """
    _utf8_output()
    settings = _settings(check_keys=False)
    try:
        uploaded = export_tracker(get_storage(settings), out)
    except OSError as error:
        typer.echo(f"Could not write {out} ({type(error).__name__}).", err=True)
        raise typer.Exit(code=1) from None
    except (StorageNotSetUpError, StorageError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Saved: {out.resolve()}")
    typer.echo(f"{EXPORT_NAME} ({settings.storage_provider}): {uploaded.link}")


@tracking_app.command("show")
def tracking_show() -> None:
    """Counts per Approval status and Publishing status, one line each ("show tracker")."""
    _utf8_output()
    settings = _settings(check_keys=False)
    try:
        storage = get_storage(settings)
        lines = status_lines(storage.read_tracker())
        link = storage.tracker_link()
    except (StorageNotSetUpError, StorageError, TrackerError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Content Tracker ({settings.storage_provider}): {link}")
    for line in lines:
        typer.echo(line)


@tracking_app.command("conflicts")
def tracking_conflicts(
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON (for skills).")] = False,
) -> None:
    """Hand-edited workflow cells, rows missing in the Sheet or in the registry, duplicate IDs
    ("tracker conflicts"). Nothing is written."""
    _utf8_output()
    settings = _settings(check_keys=False)
    with _registry(settings, "ca tracking conflicts"):
        try:
            conflicts = tracker_conflicts(get_storage(settings))
        except (StorageNotSetUpError, StorageError, TrackerError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from None
    if as_json:
        typer.echo(json.dumps([asdict(conflict) for conflict in conflicts], ensure_ascii=False))
        return
    if not conflicts:
        typer.echo(f"Content Tracker ({settings.storage_provider}): no conflicts.")
        return
    typer.echo(f"Content Tracker ({settings.storage_provider}): {len(conflicts)} conflict(s):")
    for conflict in conflicts:
        typer.echo(f"- {conflict.line()}")
    typer.echo("Decide per row: uv run ca tracking resolve <BG ID or Content ID> --keep-sheet "
               "or --use-registry")


@tracking_app.command("resolve")
def tracking_resolve(
    ref: Annotated[str, typer.Argument(help="The row: a BG ID or Content ID.")],
    keep_sheet: Annotated[
        bool, typer.Option("--keep-sheet", help="Keep the hand edits in the Sheet.")
    ] = False,
    use_registry: Annotated[
        bool, typer.Option("--use-registry", help="Write the registry's values over them.")
    ] = False,
) -> None:
    """Settle a hand-edited tracker row: keep the Sheet's values, or write the registry's."""
    _utf8_output()
    if keep_sheet == use_registry:
        typer.echo("Give exactly one of --keep-sheet or --use-registry.", err=True)
        raise typer.Exit(code=2)
    settings = _settings(check_keys=False)
    with _registry(settings, f"ca tracking resolve {ref} "
                   + ("--keep-sheet" if keep_sheet else "--use-registry")):
        try:
            catalog = load_deliverables(settings.deliverables_file)
            lines = resolve_tracker(get_storage(settings), catalog, ref, keep_sheet=keep_sheet)
        except (StorageNotSetUpError, StorageError, TrackerError, DeliverableError,
                OSError, ValueError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=1) from None
    for line in lines:
        typer.echo(line)


@overlay_app.command("preview")
def overlay_preview(
    format_id: Annotated[
        str,
        typer.Option("--format", help=f"One of: {', '.join(SAMPLE_TEXTS)}."),
    ],
    image: Annotated[Path, typer.Option(help="Any picture to put the sample text on.")],
    layout: Annotated[
        str | None, typer.Option(help="A-D (default: the format's first layout).")
    ] = None,
    no_person: Annotated[
        bool, typer.Option("--no-person", help="A LinkedIn post without the person.")
    ] = False,
    out: Annotated[
        Path | None, typer.Option(help="Where to save the PNG (default: outputs/overlay-preview/).")
    ] = None,
) -> None:
    """Render sample text (the brief template's fields at their word limits), then the logo,
    onto an image, to check the text zones. Local and free: no provider call."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        sample = SAMPLE_TEXTS.get(format_id)
        if sample is None:
            raise WorkflowError(f"--format must be one of: {', '.join(SAMPLE_TEXTS)}.")
        system = load_design_system(settings.design_system_file)
        spec = system.formats[format_id]  # type: ignore[index]
        chosen = None if no_person or not spec.layouts else (
            layout or spec.default_layout or spec.layouts[0]
        )
        inputs = WorkflowInputs(format=format_id, layout=chosen, no_person=no_person)
        for name, value in sample.items():
            setattr(inputs, name, value)
        design = resolve_design(inputs, system, kind="ad" if format_id == "ad" else None)
        has_brand = brand_path(settings.references_dir).is_file()
        brand = load_brand(settings.references_dir) if has_brand else None
        text = prepare_text_overlay(design, system, brand, load_company(settings.company_file))
        data, notes = apply_text(image.read_bytes(), text)
        try:
            ref = select_logo_ref(
                settings.references_dir, preferred=brand.logo_file if brand else None
            )
            logo = LogoOverlay(path=ref.path, source=ref.source, asset_id=ref.asset_id)
            data, version = apply_logo(data, logo)
            logo_line = f"Logo: {version} ({ref.source})"
        except (ReferenceLibraryError, LogoError) as error:
            logo_line = f"Logo: not pasted ({error})"
        target = out or Path("outputs/overlay-preview") / (
            f"{image.stem}-{format_id}-{chosen or 'none'}.png"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    except (WorkflowError, BrandProfileError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Saved: {target.resolve()}")
    typer.echo(f"Format {format_id}, layout {chosen or 'none'}: {text.panel.label}")
    typer.echo(f"Text: {text.describe()}")
    typer.echo(f"Scrims: {'; '.join(notes) or 'none needed'}")
    typer.echo(logo_line)


@carousel_app.command("style")
def carousel_style() -> None:
    """Extract the reference frames of each slide type from the sample carousels (FFmpeg) and
    write palette.json into the style folder. Local and free."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        lines = extract_style(load_carousel_design(settings.carousel_design_file))
    except (WorkflowError, MediaError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for line in lines:
        typer.echo(line)


def _carousel_brand(settings: Settings) -> tuple[str, LogoOverlay | None]:
    """The carousel language (brand.json carousel.language) and the logo, if one is usable."""
    has_brand = brand_path(settings.references_dir).is_file()
    brand = load_brand(settings.references_dir) if has_brand else None
    try:
        ref = select_logo_ref(settings.references_dir, preferred=brand.logo_file if brand else None)
    except ReferenceLibraryError as error:
        typer.echo(f"Logo: not pasted ({error})")
        ref = None
    logo = LogoOverlay(path=ref.path, source=ref.source, asset_id=ref.asset_id) if ref else None
    return (brand.carousel.language if brand else "en"), logo


@carousel_app.command("preview")
def carousel_preview(
    topic: Annotated[str, typer.Option(help="The topic the sample text and still prompts use.")],
    out: Annotated[
        Path | None,
        typer.Option(help="Folder for the stills (default: outputs/carousel-preview/<topic>/)."),
    ] = None,
) -> None:
    """Render all slides as stills: sample text over the sample frames, the Like/Share/Save
    row and the logo on the last slide, to check the layout before any paid run. Also writes
    the still prompts. Local and free: no provider or plugin call."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        design = load_carousel_design(settings.carousel_design_file)
        system = load_design_system(settings.design_system_file)
        language, logo = _carousel_brand(settings)
        target = out or PREVIEW_DIR / slugify(topic)
        lines = carousel_preview_slides(design, system, topic, language, logo, target)
    except (WorkflowError, BrandProfileError, MediaError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(
        f"Carousel preview ({design.slides} slides, {design.canvas.width}x"
        f"{design.canvas.height}, text in {design.language_name(language)}; sample text is "
        f"English): {target.resolve()}"
    )
    for line in lines:
        typer.echo(line)


@carousel_app.command("record")
def carousel_record(
    folder: Annotated[Path, typer.Argument(help="The package folder.")],
    still: Annotated[
        int | None, typer.Option(help="The slide number of a still request (still_NN).")
    ] = None,
    clip: Annotated[
        int | None, typer.Option(help="The slide number of a clip request (clip_NN).")
    ] = None,
    credits: Annotated[
        float | None, typer.Option(help="Credits the plugin reported for this attempt.")
    ] = None,
    provider_job_id: Annotated[str | None, typer.Option(help="The plugin's job ID.")] = None,
    file: Annotated[
        Path | None,
        typer.Option(help="The saved file, if it is not at the request's outputPath already."),
    ] = None,
    error: Annotated[
        str | None, typer.Option(help="The plugin failed: the reason (no file recorded).")
    ] = None,
) -> None:
    """Record one plugin attempt for a still or clip request: the file or the error, and the
    credits used. Says whether a retry is left inside the approved max. Local and free."""
    _utf8_output()
    if (still is None) == (clip is None):
        typer.echo("Give exactly one of --still N or --clip N.", err=True)
        raise typer.Exit(code=2)
    settings = _settings(dry_run=True)
    try:
        design = load_carousel_design(settings.carousel_design_file)
        with _registry(settings, f'ca carousel record "{folder}"'):
            lines = record_attempt(
                folder, "still" if still is not None else "clip", still or clip or 0, design,
                credits=credits, provider_job_id=provider_job_id, file=file, error=error,
            )
    except (WorkflowError, ValidationError, OSError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(code=1) from None
    for line in lines:
        typer.echo(line)


@carousel_app.command("stills-check")
def carousel_stills_check(
    folder: Annotated[Path, typer.Argument(help="The package folder.")],
) -> None:
    """Check every slide still: it exists, is 1:1 at 1080x1080 (cropped and resized if
    needed), is not blank and leaves the text area calm. A failed still is asked for once more
    inside the approved max, then it gets the local background. When all are settled, it
    writes the clip requests. Local and free."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        with _registry(settings, f'ca carousel stills-check "{folder}"'):
            lines = stills_check(folder, load_carousel_design(settings.carousel_design_file),
                                 package_format(folder, settings))
    except (WorkflowError, ValidationError, MediaError, OSError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(code=1) from None
    for line in lines:
        typer.echo(line)


@carousel_app.command("clips-check")
def carousel_clips_check(
    folder: Annotated[Path, typer.Argument(help="The package folder.")],
) -> None:
    """Check every clip: it decodes, lasts at least 4.5 s, moves, and keeps the text area calm.
    A failed clip is asked for once more inside the approved max, then that slide gets the
    local animation. Local and free."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        with _registry(settings, f'ca carousel clips-check "{folder}"'):
            lines = clips_check(folder, load_carousel_design(settings.carousel_design_file))
    except (WorkflowError, ValidationError, MediaError, OSError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(code=1) from None
    for line in lines:
        typer.echo(line)


@carousel_app.command("render")
def carousel_render(
    folder: Annotated[Path, typer.Argument(help="The package folder.")],
) -> None:
    """Make carousel/final/slide_01.mp4 ... (1080x1080, 24 fps, 5.0 s, H.264, silent) and
    slide_NN.png: the plugin clip or the local animation, the static text on top, and the
    Like/Share/Save row and logo on the last slide; then the set check (report only). Local
    and free."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        design = load_carousel_design(settings.carousel_design_file)
        system = load_design_system(settings.design_system_file)
        language, logo = _carousel_brand(settings)
        lines = render_carousel(
            folder, design, system, carousel_slide_texts(folder), language, logo,
            package_format(folder, settings),
        )
    except (WorkflowError, BriefError, BrandProfileError, ValidationError, MediaError,
            OSError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(code=1) from None
    for line in lines:
        typer.echo(line)
    with _registry(settings, f'ca carousel render "{folder}"'):
        _finish_carousel(folder, settings)


@carousel_app.command("finish")
def carousel_finish(
    folder: Annotated[Path, typer.Argument(help="The package folder.")],
) -> None:
    """After the render (`ca carousel render` runs this itself): the package is finished, its
    files go to Drive Instagram/<Content ID>/ (MP4s, PNGs, caption.txt, originals/), the
    tracker gets its row, the calendar row becomes Generated; then the summary. Files already
    uploaded are skipped."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f'ca carousel finish "{folder}"'):
        _finish_carousel(folder, settings)


@carousel_app.command("continue")
def carousel_continue(
    folder: Annotated[Path, typer.Argument(help="The package folder.")],
) -> None:
    """Where a carousel stopped (carousel/carousel.json) and the next step. Nothing that passed
    is made again; it says STOP if the pending requests could go over the approved max."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        with _registry(settings, f'ca carousel continue "{folder}"'):
            lines = continue_lines(folder, load_carousel_design(settings.carousel_design_file))
    except (WorkflowError, ValidationError, OSError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(code=1) from None
    for line in lines:
        typer.echo(line)


def _finish_carousel(folder: Path, settings: Settings) -> None:
    """Package done, Drive sync and tracker, calendar row Generated, the summary (8 lines)."""
    try:
        design = load_carousel_design(settings.carousel_design_file)
        package = finish_carousel(folder, settings)
        summary = summary_lines(folder, design)
    except (WorkflowError, BriefError, ValidationError, OSError) as failure:
        typer.echo(str(failure), err=True)
        raise typer.Exit(code=1) from None
    if package.status != DONE_STATUS:
        typer.echo(f"Status: {package.status} (not uploaded until every part is done)")
        return
    sync = AutoSync(settings)(folder)
    for line in sync:
        typer.echo(line)
    calendar_rows = []
    for path in mark_generated(settings, folder):
        calendar_rows.append(path.stem)
        typer.echo(sync_calendar(path, settings))
    content_id = package.content_id or package.package_id
    try:
        drive = get_storage(settings).folder_link(package.platform, content_id)
    except (StorageError, StorageNotSetUpError) as error:
        drive = f"not uploaded ({error}); later: uv run ca drive sync \"{folder}\""
    tracker = next((line for line in sync if line.startswith(("Tracker", "Drive not"))), "")
    typer.echo("Summary:")
    for line in [
        f"Carousel finished: {package.topic} ({content_id})",
        f"Drive folder: {drive}",
        *summary,
        tracker or "Tracker: no row yet (see the lines above)",
        "Calendar: " + (f"row Generated ({', '.join(calendar_rows)})" if calendar_rows
                        else "no Approved row for this package"),
    ][:8]:
        typer.echo(f"  {line}")


LoraModel = Annotated[str, typer.Argument(help="qwen (Qwen-Image-2512) or zimage (Z-Image Turbo).")]


def _lora_model(value: str) -> ModelKey:
    if value not in ("qwen", "zimage"):
        typer.echo("The model must be qwen or zimage.", err=True)
        raise typer.Exit(code=2)
    return "qwen" if value == "qwen" else "zimage"


@lora_app.command("prepare")
def lora_prepare(
    keep: Annotated[
        list[str] | None,
        typer.Option(help="A photo (e.g. 7.jpg or extra/a.jpg) whose face the detector missed, "
                     "checked by eye; repeat for more."),
    ] = None,
) -> None:
    """Check consent and photos, write the training dataset zip to outputs/lora/ (free).

    Refused without CONSENT.md in the identity folder, or with fewer than 9 usable photos.
    """
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        result = prepare_dataset(settings, keep=keep)
    except LoraError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for line in result.lines:
        typer.echo(line)


@lora_app.command("config")
def lora_config(
    model: Annotated[str, typer.Option(help="qwen (Qwen-Image-2512) or zimage (Z-Image Turbo).")],
    dataset: Annotated[
        Path | None, typer.Option(help="The dataset zip (default: the newest in outputs/lora/).")
    ] = None,
) -> None:
    """Write the AI Toolkit YAML for one model and show the Pod cost estimate (free)."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        _, lines = training_config(settings, _lora_model(model), dataset or newest_dataset())
    except LoraError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for line in lines:
        typer.echo(line)


@lora_app.command("set")
def lora_set(
    model: LoraModel,
    filename: Annotated[str, typer.Argument(help="The LoRA file name in models/loras/.")],
) -> None:
    """Point config/comfyui.json at the trained LoRA, so images with the person are allowed."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        lines = set_lora(settings, _lora_model(model), filename)
    except LoraError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for line in lines:
        typer.echo(line)


@lora_app.command("train-remote")
def lora_train_remote(
    model: Annotated[str, typer.Option(help="qwen, zimage or both.")] = "both",
    yes: Annotated[
        bool, typer.Option("--yes", help="The user said ok to the estimate: start the Pod.")
    ] = False,
) -> None:
    """Train the LoRA on a temporary RunPod Pod in one command (paid: needs --yes).

    Without --yes: consent, dataset and the cost estimate only (free). With --yes: upload to
    the network volume, create the Pod, watch it (samples to outputs/lora/<model>/samples/) and
    terminate it at the hard limit, on Ctrl+C or on any error.
    """
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        chosen = remote_plan(settings, model, typer.echo)
        for line in chosen.lines:
            typer.echo(line)
        if not yes:
            typer.echo(
                "Nothing started. Show this estimate to the user; only after their \"ok\": "
                f"uv run ca lora train-remote --model {model} --yes"
            )
            return
        config = load_lora_config(settings.lora_config_file)
        run, rest, store = remote_start(settings, chosen, typer.echo)
        run = remote_watch(run, rest, store, typer.echo, config=config)
    except KeyboardInterrupt:
        typer.echo("Stopped with Ctrl+C; the Pod was terminated (`uv run ca lora status`).",
                   err=True)
        raise typer.Exit(code=130) from None
    except LoraError as error:
        typer.echo(str(error), err=True)
        typer.echo("If a Pod was started it has been terminated; check: uv run ca lora status",
                   err=True)
        raise typer.Exit(code=1) from None
    for line in result_lines(run):
        typer.echo(line)
    if not run.status.startswith("done"):
        raise typer.Exit(code=1)


@lora_app.command("status")
def lora_status() -> None:
    """The latest remote training run: Pod state, progress, new samples, cost so far."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        remote_status(settings, typer.echo)
    except LoraError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None


@lora_app.command("stop")
def lora_stop() -> None:
    """Terminate this tool's training Pod now (billing stops) and record the run as stopped."""
    _utf8_output()
    settings = _settings(dry_run=True)
    try:
        remote_stop(settings, typer.echo)
    except LoraError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None


@app.command()
def doctor() -> None:
    """Check the setup (keys are only shown as set yes/no) and say how to fix problems."""
    _utf8_output()
    checks = run_checks()
    labels = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}
    for check in checks:
        typer.echo(f"{labels[check.level]} {check.name}: {check.detail}")
        if check.fix:
            typer.echo(f"       Fix: {check.fix}")
    failures = sum(check.level == "fail" for check in checks)
    warnings = sum(check.level == "warn" for check in checks)
    typer.echo(f"{failures} problem(s), {warnings} warning(s).")
    if failures:
        raise typer.Exit(code=1)


@review_app.command("list")
def review_list() -> None:
    """Items generated and not reviewed yet ("what needs review")."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, "ca review list") as scope:
        items = review_queue(scope.conn)
    for item in items:
        typer.echo(f"{item.id} v{item.current_version} {item.deliverable or item.kind}: "
                   f"{item.title}")
    typer.echo(f"{len(items)} item(s) to review. Decide: uv run ca item approve|reject|revise "
               "BG-x (review gate).")


@review_app.command("show")
def review_show(ref: Annotated[str, typer.Argument(help="The item (BG ID).")]) -> None:
    """Version, files, checks, costs and the last feedback of one item."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca review show {ref}") as scope:
        lines = review_show_lines(scope.conn, settings, ref)
    for line in lines:
        typer.echo(line)


@app.command("regenerate")
def regenerate(
    ref: Annotated[str, typer.Argument(help="The item (BG ID) after a review revise.")],
    only: Annotated[
        str | None, typer.Option("--only", help='Parts, e.g. "slide3,text" or "2".')
    ] = None,
    authorize_id: AuthorizeOption = None,
) -> None:
    """Make the named parts again for the new version: a dry run first; after the user's
    "ok" --authorize <dryrun_id>. Unchanged parts are kept; text-only changes of an animated
    carousel re-render the overlay for free."""
    _utf8_output()
    settings = _settings(check_keys=False)
    parts = [part for part in (only or "").split(",") if part.strip()]
    with _registry(settings, f"ca regenerate {ref}" + (f" --only {only}" if only else "")
                   + (" --authorize" if authorize_id else "")) as scope:
        plan = plan_regeneration(scope.conn, settings, ref, parts)
        key = f"regenerate {plan.item.id} {plan.names}"
        paid = [line for line in plan.lines if scope.config.paid(line.provider)]
        if paid and not authorize_id:
            for cost in plan.lines:
                typer.echo(f"{cost.item} {cost.label}: {cost.estimate:g} {cost.unit} via "
                           f"{cost.provider}")
            for line in save_dry_run_lines(settings, scope, key, plan.lines):
                typer.echo(line)
            typer.echo(f"Only after the user says ok: uv run ca regenerate {plan.item.id} "
                       f"--only {plan.names} --authorize <the dry run ID above>")
            return
        if authorize_id:  # a changed or used dry run is a RegistryError (exit 1)
            for line in authorization_lines(
                    authorize(settings, scope, authorize_id, key, plan.lines)):
                typer.echo(line)
        for line in apply_regeneration(scope.conn, plan, command=scope.command):
            typer.echo(line)
        if plan.text:
            design = load_carousel_design(settings.carousel_design_file)
            system = load_design_system(settings.design_system_file)
            language, logo = _carousel_brand(settings)
            for line in render_carousel(plan.folder, design, system,
                                        carousel_slide_texts(plan.folder), language, logo):
                typer.echo(line)
            if not plan.positions:
                part_done(scope.conn, plan.item.id, command=scope.command)
        if plan.positions:
            result = build_package(plan.folder, settings, dry_run=False)
            for line in result.lines:
                typer.echo(line)


@drive_app.command("record")
def drive_record(
    job_id: Annotated[int, typer.Argument(help="The upload request's jobId.")],
    file_id: Annotated[str, typer.Option("--file-id", help="The Drive file ID.")],
    link: Annotated[str, typer.Option("--link", help="The Drive link of the file.")],
) -> None:
    """After the Drive plugin uploaded an upload request (STORAGE_PROVIDER=plugin)."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca drive record {job_id}") as scope:
        lines = record_plugin_upload(scope.conn, job_id, file_id, link, command=scope.command)
    for line in lines:
        typer.echo(line)


@production_app.command("list")
def production_list(
    month: Annotated[str | None, typer.Option(help="A month, e.g. 2026-11.")] = None,
) -> None:
    """YouTube and podcast items with their production status; finals vs the targets."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, "ca production list") as scope:
        lines = production_lines(scope.conn, settings, month)
    for line in lines:
        typer.echo(line)


@production_app.command("set")
def production_set(
    ref: Annotated[str, typer.Argument(help="The item (BG ID).")],
    status: Annotated[str, typer.Argument(help="recorded, editing, edited or final.")],
) -> None:
    """Move the production status (only the legal moves; "BG-x recorded")."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca production set {ref} {status}") as scope:
        lines = set_production(scope.conn, ref, status, command=scope.command)
    for line in lines:
        typer.echo(line)


@app.command("import")
def import_file(
    ref: Annotated[str, typer.Argument(help="The item (BG ID).")],
    file: Annotated[Path, typer.Argument(help="The file to import (it is copied).")],
    kind: Annotated[str, typer.Option("--as", help="recording, edit, final, thumbnail or audio.")],
) -> None:
    """Copy a recording, edit, final, thumbnail or audio into the item's version folder."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca import {ref} --as {kind}") as scope:
        lines = import_media(scope.conn, settings, ref, file, kind, command=scope.command)
    for line in lines:
        typer.echo(line)


@app.command("handoff")
def handoff_command(
    ref: Annotated[str, typer.Argument(help="The item (BG ID).")],
    editor: Annotated[str, typer.Option("--to", help="The editor's name.")],
) -> None:
    """A handoff folder for the editor; production -> editing."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca handoff {ref}") as scope:
        lines = handoff(scope.conn, settings, ref, editor, command=scope.command)
    for line in lines:
        typer.echo(line)


@app.command("thumbnail")
def thumbnail(ref: Annotated[str, typer.Argument(help="The item (BG ID).")]) -> None:
    """1280x720 thumbnail: the imported background and the brief's text (at most 5 words)."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca thumbnail {ref}") as scope:
        lines = make_thumbnail(scope.conn, settings, ref, command=scope.command)
    for line in lines:
        typer.echo(line)


@podcast_app.command("heygen")
def podcast_heygen(
    ref: Annotated[str, typer.Argument(help="The podcast item (BG ID).")],
    authorize_id: AuthorizeOption = None,
) -> None:
    """The HeyGen recording: a dry run; after the user's "ok" --authorize writes the request."""
    _utf8_output()
    settings = _settings(check_keys=False)
    with _registry(settings, f"ca podcast heygen {ref}"
                   + (" --authorize" if authorize_id else "")) as scope:
        lines = heygen_lines(scope.conn, settings, ref)
        key = f"podcast heygen {lines[0].item}"
        if authorize_id is None:
            for cost in lines:
                typer.echo(f"{cost.item} {cost.label}: about {cost.estimate:g} {cost.unit}")
            for line in save_dry_run_lines(settings, scope, key, lines):
                typer.echo(line)
            typer.echo(f"Only after the user says ok: uv run ca podcast heygen {ref} "
                       "--authorize <the dry run ID above>")
            return
        for line in authorization_lines(authorize(settings, scope, authorize_id, key, lines)):
            typer.echo(line)
        for line in heygen_request(scope.conn, settings, ref, command=scope.command):
            typer.echo(line)


@podcast_app.command("record")
def podcast_record(
    job_id: Annotated[int, typer.Argument(help="The HeyGen request's jobId.")],
    file: Annotated[Path, typer.Argument(help="The file the HeyGen plugin made.")],
    credits: Annotated[float | None, typer.Option(help="Credits the plugin reported.")] = None,
) -> None:
    """Record the HeyGen result and import it as the recording."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca podcast record {job_id}") as scope:
        lines = record_heygen(scope.conn, settings, job_id, file, credits=credits,
                              command=scope.command)
    for line in lines:
        typer.echo(line)


@podcast_app.command("audio")
def podcast_audio_command(ref: Annotated[str, typer.Argument(help="The item (BG ID).")]) -> None:
    """MP3 with FFmpeg loudnorm (-16 LUFS, config/production.json)."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca podcast audio {ref}") as scope:
        lines = podcast_audio(scope.conn, settings, ref, command=scope.command)
    for line in lines:
        typer.echo(line)


@clips_app.command("handoff")
def clips_handoff_command(ref: Annotated[str, typer.Argument(help="The video (BG ID).")]) -> None:
    """The note for Opus Pro: the final video, 10-12 candidates, 9:16."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca clips handoff {ref}") as scope:
        lines = clips_handoff(scope.conn, settings, ref, command=scope.command)
    for line in lines:
        typer.echo(line)


@clips_app.command("import")
def clips_import_command(
    ref: Annotated[str, typer.Argument(help="The video (BG ID).")],
    folder: Annotated[Path, typer.Argument(help="The folder with the returned clips.")],
) -> None:
    """Candidate short items from the clips (vertical, 15-90 s)."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca clips import {ref}") as scope:
        lines = clips_import(scope.conn, settings, ref, folder, command=scope.command)
    for line in lines:
        typer.echo(line)


@clips_app.command("select")
def clips_select_command(
    ref: Annotated[str, typer.Argument(help="The video (BG ID).")],
    numbers: Annotated[list[int], typer.Argument(help="The candidate numbers the user picked.")],
    force: Annotated[bool, typer.Option("--force", help="Another count than 4-5.")] = False,
) -> None:
    """The user's picks are approved; the other candidates are rejected ("not selected")."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca clips select {ref} " + " ".join(map(str, numbers))) as scope:
        lines = clips_select(scope.conn, settings, ref, numbers, force=force,
                             command=scope.command)
    for line in lines:
        typer.echo(line)


PlatformOption = Annotated[str, typer.Option("--platform", help="e.g. linkedin, tiktok, reels.")]


@app.command("prepare")
def prepare_command(
    ref: Annotated[str, typer.Argument(help="The item (BG ID), review approved.")],
    platforms: Annotated[
        str | None, typer.Option("--platforms", help="Variants, e.g. linkedin,facebook "
                                 "(default: the item's platforms).")
    ] = None,
) -> None:
    """Resize the approved version for each platform (config/platforms.json); the variants
    upload after the approval."""
    _utf8_output()
    settings = _settings(dry_run=True)
    chosen = [part.strip() for part in (platforms or "").split(",") if part.strip()] or None
    with _registry(settings, f"ca prepare {ref}") as scope:
        lines, made = prepare(scope.conn, settings, ref, chosen, command=scope.command)
        for variant in sorted({variant for _, variant in made}):
            lines += upload_approved(scope.conn, settings, ref,
                                     files=[file for file, v in made if v == variant],
                                     subfolder=variant, command=scope.command)
    for line in lines:
        typer.echo(line)


@copy_app.command("template")
def copy_template_command(
    ref: Annotated[str, typer.Argument(help="The item (BG ID).")],
    platform: PlatformOption,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON (for skills).")] = False,
) -> None:
    """The per-platform copy template (social_graphic formula, that platform's rules)."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca copy template {ref} --platform {platform}") as scope:
        template = copy_template(scope.conn, settings, ref, platform)
    if as_json:
        typer.echo(json.dumps(script_template_json(template), ensure_ascii=False))
        return
    for line in script_template_lines(template):
        typer.echo(line)


@copy_app.command("save")
def copy_save_command(
    ref: Annotated[str, typer.Argument(help="The item (BG ID).")],
    draft: Annotated[Path, typer.Argument(help="The copy JSON Codex wrote.")],
    platform: PlatformOption,
) -> None:
    """Check the copy with the Phase 6 rules and save it next to the platform variant."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca copy save {ref} --platform {platform}") as scope:
        check, lines = save_copy(scope.conn, settings, ref, platform, draft,
                                 command=scope.command)
    if not check.ok:
        typer.echo(f"Not saved: {len(check.problems)} problem(s):")
        for problem in check.problems:
            typer.echo(f"- {problem}")
        raise typer.Exit(code=1)
    for line in lines:
        typer.echo(line)


@publish_app.command("list")
def publish_list(
    ready: Annotated[bool, typer.Option("--ready", help="Only what is ready.")] = False,
) -> None:
    """Platforms ready to publish (or every prepared one); no direct integrations."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, "ca publish list") as scope:
        lines = publish_lines(scope.conn, ready)
    for line in lines:
        typer.echo(line)
    if not integrations(settings):
        typer.echo("Direct integrations: none (config/publishing.json); the user posts, then "
                   "uv run ca publish mark BG-x --platform <p> --url <url>.")


@publish_app.command("mark")
def publish_mark(
    ref: Annotated[str, typer.Argument(help="The item (BG ID).")],
    platform: PlatformOption,
    url: Annotated[str, typer.Option("--url", help="The live post's URL (required).")],
) -> None:
    """The post is live: ready -> published with its URL."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca publish mark {ref} --platform {platform}") as scope:
        lines = mark_published(scope.conn, ref, platform, url, command=scope.command)
    for line in lines:
        typer.echo(line)


@publish_app.command("fail")
def publish_fail(
    ref: Annotated[str, typer.Argument(help="The item (BG ID).")],
    reason: Annotated[str, typer.Argument(help="Why it failed (required).")],
    platform: PlatformOption,
) -> None:
    """Publishing failed on a platform: ready -> failed with the reason."""
    _utf8_output()
    settings = _settings(dry_run=True)
    with _registry(settings, f"ca publish fail {ref} --platform {platform}") as scope:
        lines = mark_failed(scope.conn, ref, platform, reason, command=scope.command)
    for line in lines:
        typer.echo(line)
