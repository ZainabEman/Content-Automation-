"""`ca jobs` and `ca auth` (PRD §6, §14 D-4, D-5): the registry's jobs and authorizations.

check is what the make-carousel and make-video skills run before every plugin call: line 1 is
go, skip or stop, line 2 the reason. resume resumes the registered job types: only the carousel
in Phase 4 (its existing continue logic); every other type says "not resumable yet".
"""

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, NoReturn

import typer

from content_automation.cli.scope import registry_scope
from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.registry.auth import list_authorizations
from content_automation.registry.db import RegistryError
from content_automation.registry.ids import resolve
from content_automation.registry.items import get_item
from content_automation.registry.jobs import JobRecord, JobStatus, cancel_job, check_job, list_jobs
from content_automation.workflows.carousel_design import load_carousel_design
from content_automation.workflows.carousel_plugin import continue_lines
from content_automation.workflows.registry import WorkflowError

jobs_app = typer.Typer(no_args_is_help=True, help="Registry jobs: list, check, resume, cancel.")
auth_app = typer.Typer(no_args_is_help=True, help="Authorizations: what an \"ok\" approved.")
JsonOption = Annotated[bool, typer.Option("--json", help="Print JSON (for skills).")]
RESUMABLE = {"still": "carousel", "clip": "carousel"}  # job type -> registered resume


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


def _job_json(job: JobRecord) -> dict[str, object]:
    data = asdict(job)
    data["stale"] = job.stale()
    return data


@jobs_app.command("list")
def jobs_list(
    unfinished: Annotated[bool, typer.Option("--unfinished", help="Queued or running.")] = False,
    failed: Annotated[bool, typer.Option("--failed", help="Failed or cancelled.")] = False,
    item: Annotated[str | None, typer.Option("--item", help="Only this item.")] = None,
    as_json: JsonOption = False,
) -> None:
    """Jobs, oldest first ("what failed", "unfinished jobs"); stale ones are marked."""
    settings = _settings()
    statuses: tuple[JobStatus, ...] = ()
    if unfinished:
        statuses += ("queued", "running")
    if failed:
        statuses += ("failed", "cancelled")
    try:
        with registry_scope(settings, "ca jobs list") as scope:
            item_id = resolve(scope.conn, item) if item else None
            jobs = list_jobs(scope.conn, item_id=item_id, statuses=statuses)
    except RegistryError as error:
        _fail(str(error))
    if as_json:
        typer.echo(json.dumps([_job_json(job) for job in jobs], ensure_ascii=False))
        return
    if not jobs:
        typer.echo("No jobs match.")
        return
    for job in jobs:
        typer.echo(job.line())
    typer.echo(f"{len(jobs)} job(s).")


@jobs_app.command("check")
def jobs_check(
    job_id: Annotated[int, typer.Argument(help="The jobId in the request file.")],
    as_json: JsonOption = False,
) -> None:
    """Before a plugin call: go (call it now), skip (reuse the recorded result) or stop."""
    settings = _settings()
    try:
        with registry_scope(settings, f"ca jobs check {job_id}") as scope:
            result = check_job(scope.conn, job_id, config=scope.config, command=scope.command)
    except RegistryError as error:
        _fail(f"stop\n{error}")
    if as_json:
        typer.echo(json.dumps({"decision": result.decision, "reason": result.reason,
                               "job": _job_json(result.job)}, ensure_ascii=False))
        return
    typer.echo(result.decision)
    typer.echo(result.reason)


@jobs_app.command("cancel")
def jobs_cancel(
    job_id: Annotated[int, typer.Argument(help="The job to cancel (e.g. a stale one).")],
    reason: Annotated[list[str] | None, typer.Argument(help="Why (required).")] = None,
) -> None:
    """Cancel a queued, running (stale) or failed job; the next try is a new job."""
    settings = _settings()
    text = " ".join(reason or []).strip()
    if not text:
        _fail('A cancel needs a reason: ca jobs cancel <id> "<reason>".', 2)
    try:
        with registry_scope(settings, f'ca jobs cancel {job_id} "{text}"') as scope:
            job = cancel_job(scope.conn, job_id, text, command=scope.command)
    except RegistryError as error:
        _fail(str(error))
    typer.echo(job.line())


@jobs_app.command("resume")
def jobs_resume(
    ref: Annotated[str | None, typer.Argument(help="Only this item (BG ID or alias).")] = None,
) -> None:
    """Resume unfinished work of the registered job types ("resume unfinished jobs"): the
    carousel's next step; other types are listed as not resumable yet."""
    settings = _settings()
    lines: list[str] = []
    try:
        with registry_scope(settings, "ca jobs resume" + (f" {ref}" if ref else "")) as scope:
            item_id = resolve(scope.conn, ref) if ref else None
            open_jobs = list_jobs(scope.conn, item_id=item_id, statuses=("queued", "running"))
            by_item: dict[str | None, list[JobRecord]] = {}
            for job in open_jobs:
                by_item.setdefault(job.item_id, []).append(job)
            for owner, jobs in by_item.items():
                stale = [job for job in jobs if job.stale()]
                for job in stale:
                    lines.append(f"{job.line()}: cancel it first (ca jobs cancel {job.id} "
                                 '"<reason>"); never re-run by itself.')
                kinds = {RESUMABLE.get(job.job_type) for job in jobs}
                if kinds == {"carousel"} and owner is not None:
                    package = get_item(scope.conn, owner).package_path
                    if package is None:
                        lines.append(f"{owner}: carousel jobs but no package folder.")
                        continue
                    design = load_carousel_design(settings.carousel_design_file)
                    lines.append(f"{owner} (carousel):")
                    lines += [f"  {line}" for line in continue_lines(Path(package), design)]
                else:
                    types = ", ".join(sorted({job.job_type for job in jobs}))
                    lines.append(f"{owner or 'direct run'}: {types}: not resumable yet "
                                 f"(jobs {', '.join(f'#{job.id}' for job in jobs)}).")
    except (RegistryError, WorkflowError, OSError, ValueError) as error:
        _fail(str(error))
    if not lines:
        typer.echo("No unfinished jobs.")
        return
    for line in lines:
        typer.echo(line)


@auth_app.command("list")
def auth_list(
    open_only: Annotated[bool, typer.Option("--open", help="Only open ones.")] = False,
    as_json: JsonOption = False,
) -> None:
    """Authorizations with spent of max ("show authorizations")."""
    settings = _settings()
    try:
        with registry_scope(settings, "ca auth list") as scope:
            auths = list_authorizations(scope.conn, open_only=open_only)
    except RegistryError as error:
        _fail(str(error))
    if as_json:
        typer.echo(json.dumps([asdict(auth) for auth in auths], ensure_ascii=False))
        return
    if not auths:
        typer.echo("No authorizations.")
        return
    for auth in auths:
        typer.echo(auth.line())
