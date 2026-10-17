"""`ca design preview` (Phase D step 3): the design directions drawn locally with sample copy.
Free: no provider is called, so no cost estimate is needed."""

from pathlib import Path
from typing import Annotated

import typer

from content_automation.cli.jobs import _fail, _settings
from content_automation.content.design_preview import PREVIEW_DIR, preview
from content_automation.content.directions import DirectionError
from content_automation.references.brand import BrandProfileError
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
