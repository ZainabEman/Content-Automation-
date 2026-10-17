"""`ca design preview` (Phase D step 3) and `ca design check` (step 7): the design directions
drawn locally with sample copy, and free checks of rendered designs. No provider is called, so
no cost estimate is needed."""

from pathlib import Path
from typing import Annotated

import typer

from content_automation.cli.jobs import _fail, _settings
from content_automation.content.design_preview import PREVIEW_DIR, preview
from content_automation.content.directions import DirectionError, load_directions
from content_automation.references import load_brand
from content_automation.references.brand import BrandProfileError
from content_automation.references.services import ServicesError, load_services
from content_automation.workflows.design_check import check_files
from content_automation.workflows.design_render import DesignRenderError

design_app = typer.Typer(no_args_is_help=True, help="Design directions: free local previews.")


@design_app.command("preview")
def design_preview(
    ids: Annotated[list[str] | None, typer.Argument(
        help="Direction IDs (e.g. FB-1 FD-2); default: all 12.")] = None,
    photo: Annotated[Path | None, typer.Option(
        "--photo", help="A real photo for the picture (green screen for FD-1's cut-out).")] = None,
    out: Annotated[Path, typer.Option("--out", help="Folder for the PNGs.")] = PREVIEW_DIR,
) -> None:
    """Draw every layout of the directions with config/design_preview_copy.json: PNG + render
    manifest per layout, placeholders for pictures (free, no provider called)."""
    settings = _settings()
    try:
        lines = preview(ids or [], photo, settings.references_dir, out)
    except (DesignRenderError, DirectionError, BrandProfileError, OSError, ValueError) as error:
        _fail(str(error))
    for line in lines:
        typer.echo(line)
    if " 0 failed," not in lines[-1]:
        raise typer.Exit(code=1)


@design_app.command("check")
def design_check(
    paths: Annotated[list[Path] | None, typer.Argument(
        help="Render manifests (.json beside the .png) or folders; default: the previews.")]
        = None,
    person: Annotated[str | None, typer.Option(
        "--person", help='"pass" once `ca job review --person pass` was recorded.')] = None,
) -> None:
    """Free checks of rendered designs: brand tokens, official logo, text fit and contrast,
    contact details, service claims and Roman's identity review. Exit 1 on any error."""
    settings = _settings()
    try:
        reports = check_files(paths or [PREVIEW_DIR], catalog=load_directions(),
                              brand=load_brand(settings.references_dir),
                              services=load_services(settings.services_file),
                              person_check=person)
    except (DirectionError, BrandProfileError, ServicesError) as error:
        _fail(str(error))
    if not reports:
        _fail("No render manifests found: run `uv run ca design preview` first.")
    for report in reports:
        for line in report.lines():
            typer.echo(line)
    failed = sum(not report.passed for report in reports)
    typer.echo(f"Design check: {len(reports) - failed} passed, {failed} failed (free).")
    if failed:
        raise typer.Exit(code=1)
