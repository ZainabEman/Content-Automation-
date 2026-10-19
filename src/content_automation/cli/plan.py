"""`ca plan month YYYY-MM [--topic …] [--apply]` (PRD v5 R7): the monthly social plan at about
2 graphics a day, with the cost of the planned volume. Free; --apply writes Approved rows (from
approved ideas) into the weekly calendars. Nothing is generated or paid."""

from pathlib import Path
from typing import Annotated

import typer

from content_automation.cli.jobs import _fail, _settings
from content_automation.cli.scope import registry_scope
from content_automation.content.calendar import CalendarError
from content_automation.content.deliverables import DeliverableError, load_deliverables
from content_automation.content.directions import DirectionError, load_directions
from content_automation.content.month_plan import (
    MonthPlanError,
    Topic,
    apply_plan,
    plan_month,
    summary_lines,
    write_plan,
)
from content_automation.content.plan import _approved_ideas, month_days, month_label
from content_automation.references.services import ServicesError, load_services
from content_automation.registry.db import RegistryError

plan_app = typer.Typer(no_args_is_help=True, help="Monthly social planning (v5).")


@plan_app.command("month")
def plan_month_command(
    month: Annotated[str, typer.Argument(help='"next", "this" or 2026-11.')],
    topic: Annotated[list[str] | None, typer.Option(
        "--topic", help="A topic to plan (repeat); approved ideas come first.")] = None,
    apply: Annotated[bool, typer.Option(
        "--apply", help="Write the rows with an approved idea into the weekly calendars.")]
        = False,
) -> None:
    """About 2 graphics a day across Instagram carousels, Facebook posts, Facebook ads and
    LinkedIn (config/deliverables.json monthlyPlan), each with its layout variant, route,
    German metadata to write and cost estimate; writes calendar/<YYYY-MM>-month-plan.json/csv."""
    settings = _settings()
    try:
        label = month_label(month)
        days = month_days(label)
        deliverables = load_deliverables(settings.deliverables_file)
        catalog = load_directions()
        try:
            services = load_services(settings.services_file)
        except ServicesError:
            services = None
        command = f"ca plan month {label}" + (" --apply" if apply else "")
        with registry_scope(settings, command) as scope:
            topics = [Topic(item.title, f"idea:{item.id}", item.id, float(details.score or 0))
                      for item, details in _approved_ideas(scope.conn)]
            topics += [Topic(text, f"topic:{text}") for text in topic or []]
            assets = plan_month(settings, deliverables, catalog, label, days, topics, services)
            files = write_plan(settings, label, assets)
            lines = summary_lines(label, assets, len(days))
            if apply:
                paths, applied = apply_plan(settings, deliverables, assets, scope.command)
                lines += applied + [f"Week file: {path}" for path in paths]
    except (MonthPlanError, DeliverableError, DirectionError, CalendarError, RegistryError,
            ValueError) as error:
        _fail(str(error), code=2)
    for line in lines:
        typer.echo(line)
    for path in files:
        typer.echo(f"Plan: {Path(path).as_posix()}")
    if not apply:
        typer.echo("Next: review the plan; \"apply the plan\" writes the rows with approved ideas "
                   "into the weekly calendars (free). Generating stays approve -> dry run -> ok.")
