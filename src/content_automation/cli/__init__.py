"""Typer command line interface."""

from typing import Annotated

import typer
from pydantic import ValidationError

from content_automation.ai.image import ASPECT_RATIOS, ImageError, ImageRequest
from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.core.limits import DailyLimitError
from content_automation.core.log import configure_logging
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
from content_automation.workflows.dry_run import dry_run_lines
from content_automation.workflows.image_job import run_image_job
from content_automation.workflows.image_workflows import (
    WorkflowInputs,
    prepare_workflow,
    run_workflow,
)
from content_automation.workflows.registry import DEFAULT_STYLE_COUNT, WorkflowError

app = typer.Typer(name="ca", no_args_is_help=True, help="Content Automation CLI.")
refs_app = typer.Typer(no_args_is_help=True, help="Reference photo library.")
brand_app = typer.Typer(no_args_is_help=True, help="Brand profile (brand.json).")
app.add_typer(refs_app, name="refs")
app.add_typer(brand_app, name="brand")


@app.callback()
def _root() -> None:
    """Root command for the Content Automation CLI."""


def _settings(*, dry_run: bool = False) -> Settings:
    """Load settings; a dry run needs no API key and creates no folders."""
    try:
        return load_settings(require_credentials=not dry_run, create_directories=not dry_run)
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
            help="person_lifestyle, person_product or social_creative. Omit for raw mode."
        ),
    ] = None,
    identity_set: Annotated[
        str | None, typer.Option("--set", help="Identity set, e.g. identity/person_01.")
    ] = None,
    product: Annotated[str | None, typer.Option(help="Product set, e.g. product/mug.")] = None,
    style: Annotated[
        str | None, typer.Option(help="Style set, e.g. creative/facebook_ads.")
    ] = None,
    style_count: Annotated[
        int | None,
        typer.Option(help=f"Style images to send (default {DEFAULT_STYLE_COUNT}).", min=1),
    ] = None,
    variant: Annotated[
        str | None, typer.Option(help="social_creative: post, ad or carousel_slide.")
    ] = None,
    headline: Annotated[str | None, typer.Option(help="Exact text to show in the image.")] = None,
    logo: Annotated[bool, typer.Option("--logo", help="Add the brand logo.")] = False,
    aspect: Annotated[
        str | None,
        typer.Option(
            help=f"Aspect ratio: {', '.join(ASPECT_RATIOS)} (default: workflow's; raw mode 1:1)."
        ),
    ] = None,
    count: Annotated[int, typer.Option(min=1, max=4, help="Number of variations (1-4).")] = 1,
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
    settings = _settings(dry_run=dry_run)
    if not dry_run:
        configure_logging(settings)
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
            "--set, --product, --style, --style-count, --variant, --headline and --logo "
            "need --workflow."
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
    typer.echo(f"Do: {len(brand.do)} rules; Don't: {len(brand.dont)} rules")
    if brand.needs_review:
        typer.echo("Needs review:")
        for item in brand.needs_review:
            typer.echo(f"  - {item}")
