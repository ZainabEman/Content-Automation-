"""`ca outputs migrate [--apply]` (PRD v6 R8): the old local outputs into
outputs/_system/rejected_legacy/ (a dry run by default; nothing deleted, no record changed).
`ca outputs collect [--week YYYY-Www]` (2026-10-21): copies of the passed final images into
outputs/_system/review/<week>/ for quick viewing (the packages keep theirs).
`ca outputs rename [--apply]` (PRD v6 weekly §6): item folders to "<English Topic Title>
<YYYY-MM-DD>", locally and on Drive (a dry run by default)."""

from typing import Annotated

import typer

from content_automation.cli.jobs import _fail, _settings
from content_automation.cli.scope import registry_scope
from content_automation.content.folder_rename import (
    apply_renames,
    plan_renames,
    write_titles_file,
)
from content_automation.content.folder_rename import plan_lines as rename_lines
from content_automation.content.outputs_migrate import (
    apply_migration,
    plan_lines,
    plan_migration,
)
from content_automation.core.output_tree import collect_final

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


@outputs_app.command("collect")
def outputs_collect(
    week: Annotated[str | None, typer.Option(
        "--week", help="Only this ISO week, e.g. 2026-W44 (default: every week).")] = None,
) -> None:
    """Copy the passed final images of the platform tree into outputs/_system/review/<week>/
    for quick viewing (copies; never move or edit a package's final/ folder)."""
    settings = _settings()
    if week is not None and not (len(week) == 8 and week[4:6] == "-W" and week[:4].isdigit()
                                 and week[6:].isdigit()):
        _fail(f'--week must look like 2026-W44, not "{week}"', 2)
    try:
        copied = collect_final(settings.packages_dir, week)
    except OSError as error:
        _fail(f"collect stopped: {error}")
    folders = sorted({target.parent for _, target in copied})
    typer.echo(f"{len(copied)} final image(s) copied" + (": " + ", ".join(
        folder.as_posix() for folder in folders) if folders else
        " (no passed final images" + (f" in {week}" if week else "") + ")") + ".")


@outputs_app.command("rename")
def outputs_rename(
    apply: Annotated[bool, typer.Option(
        "--apply", help="Rename for real (only after the user's ok to the dry run).")] = False,
) -> None:
    """List every item folder (local and Drive) not named "<English Topic Title> <YYYY-MM-DD>"
    with its new name; --apply renames them in place and updates the tracker."""
    settings = _settings()
    command = "ca outputs rename" + (" --apply" if apply else "")
    try:
        with registry_scope(settings, command) as scope:
            plan = plan_renames(settings, scope.conn)
            titles = write_titles_file(plan, settings)
            done = apply_renames(plan, settings, scope.conn) if apply else []
            lines = rename_lines(plan, settings, applied=apply) + done
    except (OSError, ValueError) as error:
        _fail(f"rename stopped: {error}")
    for line in lines:
        typer.echo(line)
    if titles is not None:
        typer.echo(f"Titles to fill: {titles.as_posix()}")
