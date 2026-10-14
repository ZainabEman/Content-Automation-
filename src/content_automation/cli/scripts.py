"""`ca script` and `ca brief` (Phase 6 §5): templates for Codex, then save, check and show."""

import json
import sys
from typing import Annotated, NoReturn

import typer

from content_automation.cli.scope import registry_scope
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
