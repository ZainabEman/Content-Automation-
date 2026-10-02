"""Typer command line interface."""

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from content_automation.ai.avatar import AvatarError
from content_automation.ai.image import ASPECT_RATIOS, ImageError, ImageRequest
from content_automation.ai.video import VideoError
from content_automation.content.brief import FORMATS, PLATFORMS, BriefError
from content_automation.content.package import build_package, start_package
from content_automation.core.agent_steps import record_agent_output, request_path
from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.core.jobs import DETAILS_FILE, Job, JobStateError
from content_automation.core.limits import DailyLimitError
from content_automation.core.log import configure_logging
from content_automation.doctor import run_checks
from content_automation.references import (
    REF_TYPES,
    BrandProfileError,
    ReferenceLibraryError,
    extract_frames,
    list_sets,
    load_brand,
    scan,
    set_primary,
)
from content_automation.research.collectors import CollectorError
from content_automation.research.models import SourcesError
from content_automation.research.run import collect as collect_research
from content_automation.research.run import digest as research_digest_articles
from content_automation.research.run import (
    DEFAULT_TOPIC_LIMIT,
    digest_lines,
    topic_digest,
    topic_note,
)
from content_automation.workflows.dry_run import dry_run_lines
from content_automation.workflows.image_job import run_image_job
from content_automation.workflows.image_workflows import (
    AD_VARIANTS,
    WorkflowInputs,
    prepare_workflow,
    run_workflow,
)
from content_automation.workflows.registry import DEFAULT_STYLE_COUNT, WorkflowError
from content_automation.workflows.video_job import (
    agent_checklist,
    prepare_video,
    resume_video_job,
    start_video_job,
)
from content_automation.workflows.video_job import dry_run_lines as video_dry_run_lines
from content_automation.workflows.video_plan import PlanError, load_plan

app = typer.Typer(name="ca", no_args_is_help=True, help="Content Automation CLI.")
refs_app = typer.Typer(no_args_is_help=True, help="Reference photo library.")
brand_app = typer.Typer(no_args_is_help=True, help="Brand profile (brand.json).")
job_app = typer.Typer(no_args_is_help=True, help="Job records and agent steps.")
video_app = typer.Typer(help="Short vertical videos (1080x1920) from a plan.json.")
research_app = typer.Typer(no_args_is_help=True, help="News research: collect and digest articles.")
content_app = typer.Typer(
    no_args_is_help=True, help="Content packages: research, brief, images, reel, post text."
)
app.add_typer(refs_app, name="refs")
app.add_typer(brand_app, name="brand")
app.add_typer(job_app, name="job")
app.add_typer(video_app, name="video")
app.add_typer(research_app, name="research")
app.add_typer(content_app, name="content")

JobDir = Annotated[Path, typer.Argument(help="Job folder (the one with details.json).")]
StepOption = Annotated[str, typer.Option("--step", help="Step ID, e.g. scene-1.")]


@app.callback()
def _root() -> None:
    """Root command for the Content Automation CLI."""


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
        str, typer.Option(help="Scene description (or the full prompt in raw mode).")
    ],
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
        typer.Option(
            help="Layouts B/C: arms_crossed, laptop, profile, leaning_back or stressed "
            "(config/design_system.json)."
        ),
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
) -> None:
    """Generate images and save them with a details.json record."""
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
        kind=kind,
        layout=layout,
        pose=pose,
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
    try:
        if dry_run:
            for line in _dry_run(workflow, inputs, settings):
                typer.echo(line)
            return
        if workflow is None:
            job = run_image_job(_raw_request(inputs), settings, user_request=inputs.request)
        else:
            job = run_workflow(workflow, inputs, settings)
    except (
        WorkflowError,
        ReferenceLibraryError,
        BrandProfileError,
        DailyLimitError,
        ImageError,
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
    return dry_run_lines(
        prepared.request,
        settings,
        workflow=f"{prepared.spec.workflow_id} (v{prepared.spec.version})",
        product_refs=prepared.product_refs,
        brand_refs=prepared.brand_refs,
    )


def _raw_request(inputs: WorkflowInputs) -> ImageRequest:
    """Raw mode: the prompt is sent as written, without references or brand rules."""
    if inputs.provided() or inputs.style_count is not None:
        raise WorkflowError(
            "Options other than --prompt, --aspect, --count and --request need --workflow."
        )
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
    typer.echo(f"{'type':<9} {'set':<{width}} {'ok':>3} {'rejected':>8} {'primary':>7}")
    for ref_set in sets:
        typer.echo(
            f"{ref_set.type:<9} {ref_set.set_id:<{width}} {len(ref_set.ok_assets):>3} "
            f"{len(ref_set.rejected_assets):>8} {len(ref_set.primary_assets):>7}"
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
    try:
        saved = record_agent_output(
            job, step, file, provider_job_id=provider_job_id, credits_used=credits
        )
    except (JobStateError, OSError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"{step} completed: {job.folder / saved}")
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
    try:
        job.fail_step(step, error)
    except JobStateError as state_error:
        typer.echo(str(state_error), err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"{step} failed; job {job.job_id} is now failed.")


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
) -> None:
    """Make a video from plan.json: check it, make each scene, assemble final.mp4.

    If a scene waits for Codex (an MCP provider), the job pauses; record each clip with
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
    try:
        if dry_run:
            prepared = prepare_video(load_plan(plan, check_scenes=False), settings)
            for line in video_dry_run_lines(prepared, settings):
                typer.echo(line)
            return
        configure_logging(settings)
        job = start_video_job(plan, settings, request=request)
    except (PlanError, VideoError, AvatarError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    _report_video(job)


@video_app.command("resume")
def video_resume(job_dir: JobDir) -> None:
    """Continue a paused video: once every step is recorded, assemble final.mp4."""
    settings = _settings(check_keys=False)
    configure_logging(settings)
    job = _load_job(job_dir)
    try:
        job = resume_video_job(job, settings)
    except (VideoError, AvatarError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    _report_video(job)


def _report_video(job: Job) -> None:
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
    topic: Annotated[str, typer.Option(help='What it is about, e.g. "AI chatbots for SMEs".')],
    platform: Annotated[str, typer.Option(help="instagram, facebook or linkedin.")] = "instagram",
    formats: Annotated[str, typer.Option(help="Comma-separated: post, ad, reel.")] = "post,ad,reel",
) -> None:
    """Collect news, rank it for the topic, and create the package folder for brief.json."""
    _utf8_output()
    parts = [part.strip().lower() for part in formats.split(",") if part.strip()]
    chosen = list(dict.fromkeys(parts))
    problems = []
    if platform not in PLATFORMS:
        problems.append(f"--platform must be one of: {', '.join(PLATFORMS)}.")
    if not chosen or any(item not in FORMATS for item in chosen):
        problems.append(f"--formats must be a comma list of: {', '.join(FORMATS)}.")
    if not topic.strip():
        problems.append("--topic cannot be empty.")
    if problems:
        typer.echo(" ".join(problems), err=True)
        raise typer.Exit(code=2)
    settings = _settings(check_keys=False)
    configure_logging(settings)
    result = start_package(topic.strip(), platform, chosen, settings)
    for line in result.lines:
        typer.echo(line)


@content_app.command("build")
def content_build(
    folder: Annotated[Path, typer.Argument(help="The package folder from `ca content start`.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Check brief.json and show the cost; make nothing.")
    ] = False,
) -> None:
    """Make what is still missing: post images, ad image, reel, post.md, package.json."""
    _utf8_output()
    if not folder.is_dir():
        typer.echo(f"Folder not found: {folder}", err=True)
        raise typer.Exit(code=1)
    # No key check here: a missing key fails only the part that needs it (shown in the status).
    settings = _settings(dry_run=dry_run, check_keys=False)
    if not dry_run:
        configure_logging(settings)
    try:
        result = build_package(folder, settings, dry_run=dry_run)
    except BriefError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None
    for line in result.lines:
        typer.echo(line)
    if dry_run or result.package is None:
        return
    package = result.package
    typer.echo(f"Status: {package.status}")
    typer.echo(f"Folder: {folder.resolve()}")
    for name in sorted(path.relative_to(folder).as_posix() for path in folder.rglob("*")
                       if path.is_file() and not path.name.startswith(".")):
        typer.echo(f"  {name}")


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
