"""`ca youtube …` (PRD v5 R9): YouTube research and production planning, separate from social.

plan → approve/reject (`ca item approve|reject`) → research → check-sources → scripts →
bilingual → check → select-style. All free and local; check-sources opens the source URLs
(no cost). The agent (Codex, with web access) researches and writes the German texts."""

from typing import Annotated

import typer

from content_automation.cli.jobs import _fail, _settings
from content_automation.cli.scope import registry_scope
from content_automation.content.plan import month_label
from content_automation.registry.db import RegistryError
from content_automation.youtube.topic import YoutubeError
from content_automation.youtube.workflow import (
    check_scripts,
    make_bilingual,
    plan_topics,
    research,
    run_source_check,
    select_style,
    status_lines,
    write_briefs,
)

youtube_app = typer.Typer(no_args_is_help=True,
                          help="YouTube research and production planning (v5; no video).")
BgId = Annotated[str, typer.Argument(help="The YouTube topic (BG ID).")]


def _run(command: str, step: str, bg_id: str | None = None, **kwargs: object) -> list[str]:
    settings = _settings()
    try:
        with registry_scope(settings, command) as scope:
            if step == "plan":
                return plan_topics(scope.conn, str(kwargs["month"]),
                                   list(kwargs["topics"]),  # type: ignore[call-overload]
                                   command=scope.command)
            if step == "status":
                return status_lines(scope.conn, kwargs.get("month"))  # type: ignore[arg-type]
            assert bg_id is not None
            if step == "research":
                return research(scope.conn, bg_id)
            if step == "check-sources":
                return run_source_check(scope.conn, bg_id,
                                        override=kwargs.get("override"),  # type: ignore[arg-type]
                                        command=scope.command)
            if step == "scripts":
                return write_briefs(scope.conn, bg_id)
            if step == "bilingual":
                return make_bilingual(scope.conn, bg_id)
            if step == "check":
                ok, lines = check_scripts(scope.conn, bg_id)
                if not ok:
                    for line in lines:
                        typer.echo(line)
                    raise typer.Exit(code=1)
                return lines
            return select_style(scope.conn, bg_id, str(kwargs["style"]), command=scope.command)
    except (YoutubeError, RegistryError, ValueError) as error:
        _fail(str(error), code=2)


def _echo(lines: list[str]) -> None:
    for line in lines:
        typer.echo(line)


@youtube_app.command("plan")
def youtube_plan(
    month: Annotated[str, typer.Argument(help='"next", "this" or 2026-11.')],
    topic: Annotated[list[str] | None, typer.Option(
        "--topic", help="A German topic from real research (repeat, up to 8 a month).")] = None,
) -> None:
    """Up to 8 German topics for the month as Proposed items with BG IDs and a folder each."""
    label = month_label(month)
    _echo(_run(f"ca youtube plan {label}", "plan", month=label, topics=topic or []))


@youtube_app.command("research")
def youtube_research(bg_id: BgId) -> None:
    """The research TXT: the template first, then its structure check (free)."""
    _echo(_run(f"ca youtube research {bg_id}", "research", bg_id))


@youtube_app.command("check-sources")
def youtube_check_sources(
    bg_id: BgId,
    override: Annotated[str | None, typer.Option(
        "--override", help="Roman's reason to continue despite failed checks (logged).")]
        = None,
) -> None:
    """Open every source URL; check quotations and facts; write the results into the file."""
    lines = _run(f"ca youtube check-sources {bg_id}" + (" --override" if override else ""),
                 "check-sources", bg_id, override=override)
    _echo(lines)
    if any(line.startswith("Result: FAILED") for line in lines) and not override:
        raise typer.Exit(code=1)


@youtube_app.command("scripts")
def youtube_scripts(bg_id: BgId) -> None:
    """The three style briefs (A investigativ, B direkte Warnung, C menschlich); needs a passed
    or overridden source check."""
    _echo(_run(f"ca youtube scripts {bg_id}", "scripts", bg_id))


@youtube_app.command("bilingual")
def youtube_bilingual(bg_id: BgId) -> None:
    """script_DE-EN.txt from each teleprompter file (German word for word, English below)."""
    _echo(_run(f"ca youtube bilingual {bg_id}", "bilingual", bg_id))


@youtube_app.command("check")
def youtube_check(bg_id: BgId) -> None:
    """Teleprompter rules, German identity of the bilingual files, the difference check."""
    _echo(_run(f"ca youtube check {bg_id}", "check", bg_id))


@youtube_app.command("select-style")
def youtube_select_style(
    bg_id: BgId,
    style: Annotated[str, typer.Argument(help="A, B or C.")],
) -> None:
    """Mark the chosen style and write the storyboard for the editing agency."""
    _echo(_run(f"ca youtube select-style {bg_id} {style}", "select", bg_id, style=style))


@youtube_app.command("status")
def youtube_status(
    month: Annotated[str | None, typer.Option("--month", help="2026-11")] = None,
) -> None:
    """Every YouTube topic: approval, source check, passed styles, the selected style."""
    _echo(_run("ca youtube status", "status", month=month_label(month) if month else None))
