"""`ca topics refill [--count N] [--from <brief>] [--dry-run]` (v6 R2): refill the topic pool
when the weekly slots run dry. Without --from it writes the brief Codex fills (no paid API);
with --from it checks the candidates and saves what passes to config/topic_pool.json. Free."""

from pathlib import Path
from typing import Annotated

import typer

from content_automation.cli.jobs import _fail, _settings
from content_automation.cli.scope import registry_scope
from content_automation.content.calendar import CalendarError
from content_automation.content.topic_pool import TopicPoolError, topic_memory
from content_automation.content.topic_refill import RefillError, refill_lines, write_brief
from content_automation.references.services import ServicesError
from content_automation.registry.db import RegistryError

topics_app = typer.Typer(no_args_is_help=True, help="The topic pool (v6 R2).")


@topics_app.command("refill")
def topics_refill(
    count: Annotated[int, typer.Option(
        "--count", min=1, max=60, help="How many candidates the brief asks for.")] = 20,
    source: Annotated[Path | None, typer.Option(
        "--from", help="The brief Codex filled: check it and save what passes.")] = None,
    dry_run: Annotated[bool, typer.Option(
        "--dry-run", help="With --from: check and show, write nothing to the pool.")] = False,
) -> None:
    """New topic candidates for the pool (50/30/20 mix), written by Codex and checked by ca:
    a source, a theme or verified service, a reader angle, no unverified claim, and nothing
    used, rejected, deleted or close to it."""
    settings = _settings()
    command = "ca topics refill" + (f" --from {source}" if source else f" --count {count}")
    try:
        with registry_scope(settings, command + (" --dry-run" if dry_run else "")) as scope:
            memory = topic_memory(conn=scope.conn, calendar_dir=settings.calendar_dir,
                                  packages_dir=settings.packages_dir)
            if source is None:
                _, lines = write_brief(settings, count, memory)
            else:
                lines = refill_lines(settings, source, memory, dry_run=dry_run)
    except (RefillError, TopicPoolError, ServicesError, CalendarError, RegistryError) as error:
        _fail(str(error), code=2)
    for line in lines:
        typer.echo(line)
