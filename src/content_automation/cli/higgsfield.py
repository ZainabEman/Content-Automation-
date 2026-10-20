"""`ca higgsfield …` (2026-10-20): Roman's images, made by Codex with the Higgsfield plugin.

`ca content build` writes a job file per image (outputs/_system/higgsfield/<key>/job.json: the
Soul 2.0 prompt, the saved character, the aspect ratio, the expected output path and the credit
estimate). Codex runs the plugin, saves the image, then records it here and builds again. A
failed check never makes a new image by itself (2026-10-21): the row stops and the operator
runs `accept` (manual approval of an attempt, logged) or `retry` (a new costed attempt after a
new dry run and the "ok"). Every attempt's credits count once. Free and local: no provider
call."""

from pathlib import Path
from typing import Annotated

import typer

from content_automation.ai.image import ImageError
from content_automation.ai.image.higgsfield import (
    HiggsfieldSoulProvider,
    accept,
    fail,
    pending_jobs,
    record,
    retry,
)
from content_automation.cli.jobs import _fail, _settings

higgsfield_app = typer.Typer(no_args_is_help=True,
                             help="Roman's images via the Higgsfield plugin (Codex, Soul 2.0).")
Key = Annotated[str, typer.Argument(help="The job key (from `ca higgsfield list`).")]


def _root() -> Path:
    return HiggsfieldSoulProvider(_settings()).root()


@higgsfield_app.command("list")
def higgsfield_list() -> None:
    """The pending jobs Codex still has to run, with their instructions, and the stopped ones
    waiting for the operator's choice."""
    jobs = pending_jobs(_root())
    stopped = pending_jobs(_root(), "needs_operator")
    for job in stopped:
        typer.echo(f"{job.data['key']}: waits for the operator. {job.operator_message()}")
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
    typer.echo(f"{key}: stopped; no new attempt by itself. Tell the user: "
               + job.operator_message())


@higgsfield_app.command("accept")
def higgsfield_accept(
    key: Key,
    file: Annotated[Path, typer.Option("--file", help="The attempt image to approve (PNG).")],
) -> None:
    """The operator approves an attempt by hand (logged in job.json); then the build continues
    from it (no new image, no new credits)."""
    try:
        job = accept(_root(), key, file)
    except ImageError as error:
        _fail(str(error), 2)
    typer.echo(f"{key}: {Path(job.data['accepted']['file']).name} accepted by the operator "
               "(logged). Now: uv run ca content build \"<package folder>\".")


@higgsfield_app.command("retry")
def higgsfield_retry(key: Key) -> None:
    """The operator orders one new, costed attempt; Codex makes it only after a new dry run of
    the package and the user's "ok"."""
    try:
        job = retry(_root(), key)
    except ImageError as error:
        _fail(str(error), 2)
    typer.echo(f"{key}: attempt {len(job.data['attempts'])} is open. Run the package's dry run, "
               "show the cost, and after the user's \"ok\": uv run ca higgsfield list.")
