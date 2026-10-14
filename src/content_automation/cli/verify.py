"""`ca verify list|run|record` (Phase 10 Step 2): the integrations, their offline checks and the
user's live results. Operational only with a recorded live pass."""

import json
from typing import Annotated

import typer

from content_automation.cli.jobs import JsonOption, _fail, _settings
from content_automation.cli.scope import registry_scope
from content_automation.content.verification import (
    INTEGRATIONS,
    VerifyFailed,
    get_integration,
    run_offline,
)
from content_automation.registry.db import RegistryError
from content_automation.registry.verifications import (
    Result,
    Verification,
    latest,
    record_verification,
)

verify_app = typer.Typer(no_args_is_help=True, help="Integration checks: offline, then live.")
LIVE_HINT = "docs/VERIFICATION.md"


def _state(live: Verification | None) -> str:
    if live is None:
        return "not operational (no recorded live pass)"
    return "operational" if live.result == "pass" else "not operational (last live test failed)"


@verify_app.command("list")
def verify_list(as_json: JsonOption = False) -> None:
    """Each integration: success condition, failure path, last result ("verification
    status"); operational only with a recorded live pass."""
    settings = _settings()
    try:
        with registry_scope(settings, "ca verify list") as scope:
            rows = [(integration, latest(scope.conn, integration.name, "offline"),
                     latest(scope.conn, integration.name, "live")) for integration in INTEGRATIONS]
    except RegistryError as error:
        _fail(str(error))
    if as_json:
        typer.echo(json.dumps([{
            "name": i.name, "title": i.title, "success": i.success, "failure": i.failure,
            "note": i.note, "offline": off.result if off else None,
            "live": live.result if live else None,
            "operational": live is not None and live.result == "pass"}
            for i, off, live in rows], ensure_ascii=False))
        return
    for integration, offline, live in rows:
        note = f" — {integration.note}" if integration.note else ""
        typer.echo(f"{integration.name} ({integration.title}){note}: {_state(live)}")
        typer.echo(f"  success: {integration.success}")
        typer.echo(f"  failure: {integration.failure}")
        typer.echo(f"  last offline: {offline.line() if offline else 'not run'}; last live: "
                   f"{live.line() if live else 'pending'}")
    operational = sum(live is not None and live.result == "pass" for _, _, live in rows)
    typer.echo(f"{operational} of {len(rows)} operational (each needs a recorded live pass; "
               f"manual live tests: {LIVE_HINT}).")


@verify_app.command("run")
def verify_run(
    name: Annotated[str, typer.Argument(help="The integration, e.g. gmail (ca verify list).")],
) -> None:
    """Offline only ("verify <integration>"): config present, adapter loads, failure path with
    a fake; the result is recorded. Never a live or paid call."""
    settings = _settings()
    try:
        integration = get_integration(name)
    except VerifyFailed as error:
        _fail(str(error), 2)
    result: Result = "pass"
    try:
        lines = run_offline(settings, integration)
        note = lines[-1]
    except Exception as error:  # any problem is this integration's offline fail, recorded
        lines, result, note = [f"fail: {error}"], "fail", str(error)
    try:
        with registry_scope(settings, f"ca verify run {integration.name}") as scope:
            record_verification(scope.conn, integration.name, "offline", result, note,
                                command=scope.command)
    except RegistryError as error:
        _fail(str(error))
    for line in lines:
        typer.echo(line)
    typer.echo(f"{integration.name}: offline {result}. Operational only after the live test "
               f"({LIVE_HINT}): uv run ca verify record {integration.name} --live pass|fail "
               '"<note>"')
    if result == "fail":
        raise typer.Exit(code=1)


@verify_app.command("record")
def verify_record(
    name: Annotated[str, typer.Argument(help="The integration (ca verify list).")],
    live: Annotated[str, typer.Option("--live", help="pass or fail: the manual live test.")],
    note: Annotated[list[str] | None, typer.Argument(help="What was tested (required).")] = None,
) -> None:
    """The user's manual live test result (docs/VERIFICATION.md); only the user runs it."""
    settings = _settings()
    text = " ".join(note or []).strip()
    if live not in ("pass", "fail") or not text:
        _fail(f'Use: ca verify record {name} --live pass|fail "<what was tested>".', 2)
    try:
        integration = get_integration(name)
    except VerifyFailed as error:
        _fail(str(error), 2)
    try:
        with registry_scope(settings, f"ca verify record {integration.name} --live {live}"
                            ) as scope:
            saved = record_verification(scope.conn, integration.name, "live",
                                        "pass" if live == "pass" else "fail", text,
                                        actor="user", command=scope.command)
    except RegistryError as error:
        _fail(str(error))
    typer.echo(f"{integration.name}: live {saved.result} recorded — {_state(saved)}.")
