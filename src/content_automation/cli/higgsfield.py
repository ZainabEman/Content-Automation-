"""`ca higgsfield …` (2026-10-20): Roman's images, made by Codex with the Higgsfield plugin.

`ca content build` writes a job file per image (outputs/_system/higgsfield/<key>/job.json: the
Soul 2.0 prompt, the saved character, the aspect ratio, the expected output path and the credit
estimate). Codex runs the plugin, saves the image, then records it here and builds again. At
most 2 attempts per image; every attempt's credits count. Free and local: no provider call."""

from pathlib import Path
from typing import Annotated

import typer

from content_automation.ai.image import ImageError
from content_automation.ai.image.higgsfield import (
    HiggsfieldSoulProvider,
    fail,
    pending_jobs,
    record,
)
from content_automation.cli.jobs import _fail, _settings

higgsfield_app = typer.Typer(no_args_is_help=True,
                             help="Roman's images via the Higgsfield plugin (Codex, Soul 2.0).")
Key = Annotated[str, typer.Argument(help="The job key (from `ca higgsfield list`).")]


def _root() -> Path:
    return HiggsfieldSoulProvider(_settings()).root()


@higgsfield_app.command("list")
def higgsfield_list() -> None:
    """The pending jobs Codex still has to run, with their instructions."""
    jobs = pending_jobs(_root())
    if not jobs:
        typer.echo("No pending Higgsfield jobs.")
        return
    for job in jobs:
        data = job.data
        typer.echo(f"{data['key']}: {data['combination']}, {data['aspectRatio']}, attempt "
                   f"{len(data['attempts'])} of {data['maxAttempts']} ({job.path})")
        for line in data.get("instructions") or []:
            typer.echo(f"  {line}")


@higgsfield_app.command("record")
def higgsfield_record(
    key: Key,
    file: Annotated[Path, typer.Option("--file", help="The image the plugin made (PNG).")],
    credits: Annotated[
        float | None,
        typer.Option("--credits", help="The credits the plugin reported (missing: the "
                     "estimate is counted and marked as such)."),
    ] = None,
) -> None:
    """Record the delivered image of the current attempt."""
    try:
        job = record(_root(), key, file, credits)
    except ImageError as error:
        _fail(str(error), 2)
    typer.echo(f"{key}: attempt {len(job.data['attempts'])} recorded "
               f"({job.attempt['credits']:g} credits"
               + (", estimated" if job.attempt.get("creditsEstimated") else "")
               + "). Now: uv run ca content build \"<package folder>\".")


@higgsfield_app.command("fail")
def higgsfield_fail(
    key: Key,
    error: Annotated[str, typer.Option("--error", help="What went wrong at Higgsfield.")],
) -> None:
    """Record a failed attempt; ca asks for the second one, after that the image fails."""
    try:
        job = fail(_root(), key, error)
    except ImageError as problem:
        _fail(str(problem), 2)
    if job.data["status"] == "failed":
        typer.echo(f"{key}: failed after {len(job.data['attempts'])} attempts; no fallback. "
                   "Tell the user.")
    else:
        typer.echo(f"{key}: attempt {len(job.data['attempts'])} of {job.data['maxAttempts']} is "
                   f"next: uv run ca higgsfield list")
