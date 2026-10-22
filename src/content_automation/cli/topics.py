"""`ca topics refill|search` (v6 R2): fill the topic pool when the weekly slots run dry.
refill: candidates across the 50/30/20 mix; search: candidates for one theme from authentic
German sources only (config/topic_sources.json). Without --from each writes the brief Codex
fills (Codex writes and browses, no paid API); with --from it checks the candidates, their
source URLs included (one free GET each), and saves what passes to state/topic_pool.json."""

from pathlib import Path
from typing import Annotated

import typer

from content_automation.cli.jobs import _fail, _settings
from content_automation.cli.scope import registry_scope
from content_automation.content.calendar import CalendarError, week_label
from content_automation.content.topic_pool import TopicPoolError, topic_memory
from content_automation.content.topic_refill import RefillError, refill_lines, write_brief
from content_automation.content.topic_search import search_lines, write_search_brief
from content_automation.content.topic_sources import TopicSourcesError
from content_automation.references.services import ServicesError
from content_automation.registry.db import RegistryError

topics_app = typer.Typer(no_args_is_help=True, help="The topic pool (v6 R2).")
ERRORS = (RefillError, TopicPoolError, TopicSourcesError, ServicesError, CalendarError,
          RegistryError)
FromOption = Annotated[Path | None, typer.Option(
    "--from", help="The brief Codex filled: check it and save what passes.")]
DryRunOption = Annotated[bool, typer.Option(
    "--dry-run", help="With --from: check and show, write nothing to the pool.")]


@topics_app.command("refill")
def topics_refill(
    count: Annotated[int, typer.Option(
        "--count", min=1, max=60, help="How many candidates the brief asks for.")] = 20,
    source: FromOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """New topic candidates for the pool (50/30/20 mix), written by Codex and checked by ca:
    a source, a theme or verified service, a reader angle, no unverified claim, an allowlisted
    source URL, and nothing used, rejected, deleted or close to it."""
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
    except ERRORS as error:
        _fail(str(error), code=2)
    for line in lines:
        typer.echo(line)


@topics_app.command("search")
def topics_search(
    theme: Annotated[str | None, typer.Option(
        "--theme", help='The theme to search, e.g. "KI-Betrug im Mittelstand".')] = None,
    count: Annotated[int, typer.Option(
        "--count", min=1, max=20, help="How many candidates the brief asks for.")] = 5,
    week: Annotated[str | None, typer.Option(
        "--week", help='Plan them first in this week: "next", "this" or e.g. 2026-W45.')]
        = None,
    source: FromOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Topic ideas for one theme from allowlisted German sources only: Codex browses, ca checks
    every source URL (allowlist, HTTP 200, title, date, quote, numbers and studies in the text)
    and the topic memory, and prints PASS or the reason per candidate."""
    settings = _settings()
    if source is None and not (theme or "").strip():
        _fail('Give --theme "<theme>" to write a search brief, or --from <brief> to check one.',
              code=2)
    command = "ca topics search" + (f" --from {source}" if source else f' --theme "{theme}"')
    try:
        label = week_label(week) if week else None
        with registry_scope(settings, command + (" --dry-run" if dry_run else "")) as scope:
            memory = topic_memory(conn=scope.conn, calendar_dir=settings.calendar_dir,
                                  packages_dir=settings.packages_dir)
            if source is None:
                _, lines = write_search_brief(settings, (theme or "").strip(), count, label,
                                              memory)
            else:
                lines = search_lines(settings, source, memory, dry_run=dry_run)
    except ERRORS as error:
        _fail(str(error), code=2)
    for line in lines:
        typer.echo(line)
