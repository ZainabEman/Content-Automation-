"""Typer command line interface."""

from typing import Annotated

import typer
from pydantic import ValidationError

from content_automation.ai.image import ASPECT_RATIOS, ImageError, ImageRequest
from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.core.limits import DailyLimitError
from content_automation.core.log import configure_logging
from content_automation.workflows.image_job import run_image_job

app = typer.Typer(name="ca", no_args_is_help=True, help="Content Automation CLI.")


@app.callback()
def _root() -> None:
    """Root command for the Content Automation CLI."""


def _settings() -> Settings:
    try:
        return load_settings()
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
    prompt: Annotated[str, typer.Option(help="Final prompt sent to the image provider.")],
    aspect: Annotated[
        str, typer.Option(help=f"Aspect ratio: {', '.join(ASPECT_RATIOS)}.")
    ] = "1:1",
    count: Annotated[int, typer.Option(min=1, max=4, help="Number of variations (1-4).")] = 1,
    request: Annotated[
        str | None, typer.Option(help="The original plain-English request, for the record.")
    ] = None,
) -> None:
    """Generate images and save them with a details.json record."""
    settings = _settings()
    configure_logging(settings)
    try:
        image_request = ImageRequest(prompt=prompt, aspect_ratio=aspect, count=count)  # type: ignore[arg-type]
    except ValidationError as error:
        fields = sorted({str(issue["loc"][0]) for issue in error.errors()})
        message = f"Invalid image request: {', '.join(fields)}."
        if "aspect_ratio" in fields:
            message += f" Aspect must be one of {', '.join(ASPECT_RATIOS)}."
        typer.echo(message, err=True)
        raise typer.Exit(code=1) from None
    try:
        job = run_image_job(image_request, settings, user_request=request)
    except (DailyLimitError, ImageError) as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(code=1) from None

    if job.status != "completed":
        typer.echo(f"Failed: {job.error}", err=True)
        typer.echo(str(job.folder), err=True)
        raise typer.Exit(code=1)
    typer.echo(str(job.folder))
