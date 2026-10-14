"""`ca script` and `ca brief` (Phase 6 §5): templates for Codex, then save, check and show."""

import json
import sys
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from content_automation.cli.scope import registry_scope
from content_automation.content.script_check import (
    Check,
    recheck,
    save_script,
    stored_script,
)
from content_automation.content.scripts import (
    ScriptError,
    build_template,
    template_json,
    template_lines,
)
from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.registry.db import RegistryError

script_app = typer.Typer(no_args_is_help=True,
                         help="Scripts and copy from the editorial formulas.")
JsonOption = Annotated[bool, typer.Option("--json", help="Print JSON (for skills).")]
RefArgument = Annotated[str, typer.Argument(help="The item (BG ID or Content ID).")]
VersionOption = Annotated[int | None, typer.Option("--version", min=1,
                                                   help="A saved version (default: newest).")]


def _check_lines(check: Check) -> list[str]:
    lines = [f"- {problem}" for problem in check.problems]
    lines += [f"- warning: {warning}" for warning in check.warnings]
    return lines


def _fail(message: str, code: int = 1) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def _settings() -> Settings:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    try:
        return load_settings(require_credentials=False, create_directories=False)
    except ConfigurationError as error:
        _fail(str(error), 2)


@script_app.command("template")
def script_template(ref: RefArgument, as_json: JsonOption = False) -> None:
    """The item's formula: sections and word ranges, platform rules, language, the claims with
    their status and the current version's feedback."""
    settings = _settings()
    try:
        with registry_scope(settings, f"ca script template {ref}") as scope:
            template = build_template(scope.conn, settings, ref)
    except (RegistryError, ScriptError) as error:
        _fail(str(error), 2)
    if as_json:
        typer.echo(json.dumps(template_json(template), ensure_ascii=False))
        return
    for line in template_lines(template):
        typer.echo(line)


@script_app.command("save")
def script_save(
    ref: RefArgument,
    draft: Annotated[Path, typer.Argument(help="The script.json Codex wrote.")],
) -> None:
    """Check the draft; valid: stored as script.json + script.md in the current version's
    folder (an older version is never written). Invalid: nothing stored, exit 1."""
    settings = _settings()
    try:
        with registry_scope(settings, f"ca script save {ref}") as scope:
            saved = save_script(scope.conn, settings, ref, draft, command=scope.command)
    except (RegistryError, ScriptError) as error:
        _fail(str(error), 2)
    check = saved.check
    if not check.ok:
        typer.echo(f"Not saved: {len(check.problems)} problem(s):")
        for line in _check_lines(check):
            typer.echo(line)
        raise typer.Exit(code=1)
    minutes = f", about {check.minutes:g} min" if check.minutes else ""
    version = saved.artifact.version if saved.artifact else 0
    typer.echo(f"Saved v{version}: {saved.folder.as_posix()}/script.json + script.md "
               f"({check.words} words{minutes}); check OK.")
    for line in _check_lines(check):
        typer.echo(line)


@script_app.command("check")
def script_check(ref: RefArgument, version: VersionOption = None) -> None:
    """Check a saved script again (e.g. after its claims changed)."""
    settings = _settings()
    try:
        with registry_scope(settings, f"ca script check {ref}") as scope:
            script, check = recheck(scope.conn, settings, ref, version, command=scope.command)
    except (RegistryError, ScriptError) as error:
        _fail(str(error), 2)
    status = "OK" if check.ok else f"{len(check.problems)} problem(s)"
    typer.echo(f"{script.item} v{script.version} ({script.formula}): {status}")
    for line in _check_lines(check):
        typer.echo(line)
    if not check.ok:
        raise typer.Exit(code=1)


@script_app.command("show")
def script_show(ref: RefArgument, version: VersionOption = None) -> None:
    """The saved script as Markdown (script.md)."""
    settings = _settings()
    try:
        with registry_scope(settings, f"ca script show {ref}") as scope:
            _, script, path = stored_script(scope.conn, settings, ref, version)
    except (RegistryError, ScriptError) as error:
        _fail(str(error), 2)
    markdown = path.with_suffix(".md")
    typer.echo(markdown.read_text(encoding="utf-8") if markdown.is_file()
               else json.dumps(script.model_dump(by_alias=True), indent=2, ensure_ascii=False))
