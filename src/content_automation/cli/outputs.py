"""`ca outputs migrate [--apply]` (PRD v6 R8): the old local outputs into
outputs/_system/rejected_legacy/ (a dry run by default; nothing deleted, no record changed)."""

from typing import Annotated

import typer

from content_automation.cli.jobs import _fail, _settings
from content_automation.content.outputs_migrate import (
    apply_migration,
    plan_lines,
    plan_migration,
)

outputs_app = typer.Typer(no_args_is_help=True, help="The output folder tree (v6).")


@outputs_app.command("migrate")
def outputs_migrate(
    apply: Annotated[bool, typer.Option(
        "--apply", help="Move the files (without it: only list the moves).")] = False,
) -> None:
    """Move every old output folder (all rejected) unchanged into
    outputs/_system/rejected_legacy/, keeping relative paths. Dry run unless --apply."""
    settings = _settings()
    plan = plan_migration(settings.packages_dir)
    try:
        done = apply_migration(plan) if apply else []
    except OSError as error:
        _fail(f"migration stopped: {error}")
    for line in [*plan_lines(plan, applied=apply), *done]:
        typer.echo(line)
