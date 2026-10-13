"""The registry for one `ca` command that builds, records or uploads (§14 D-4, D-5).

registry_scope opens the registry, logs command_run and activates a runtime Scope that the
pipelines report to. save_dry_run_lines saves a dry run and prints its ID; authorize checks a
dry run against the current one and creates the authorizations ("ok" was said); require_budget
refuses a paid build that no open authorization covers.
"""

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

from content_automation.content.deliverables import DeliverableError, load_deliverables
from content_automation.core.config import Settings
from content_automation.registry import db_path, open_registry
from content_automation.registry.audit import append_event
from content_automation.registry.auth import Authorization, create_from_dry_run, find_authorization
from content_automation.registry.db import RegistryError
from content_automation.registry.dryruns import (
    CostLine,
    DryRunError,
    check_dry_run,
    cost_summary,
    load_dry_run,
    mark_used,
    save_dry_run,
)
from content_automation.registry.jobs import NotAuthorized, load_job_config
from content_automation.registry.runtime import Scope, activate


def part_map(settings: Settings) -> dict[str, str]:
    """deliverable -> package part key (post, ad, carousel, reel)."""
    try:
        catalog = load_deliverables(settings.deliverables_file)
    except DeliverableError:
        return {}
    return {key: str(spec.brief_format) for key, spec in catalog.deliverables.items()}


@contextmanager
def registry_scope(settings: Settings, command: str) -> Iterator[Scope]:
    """Open the registry for this command; RegistryError if it cannot be used."""
    try:
        conn = open_registry(db_path(settings.state_dir), settings.registry_file)
    except sqlite3.Error as error:
        raise RegistryError(f"Registry not usable: {error}") from None
    try:
        scope = Scope(conn=conn, config=load_job_config(settings.jobs_file), command=command,
                      part_of=part_map(settings))
        append_event(conn, "command_run", actor="user", command=command)
        with activate(scope):
            yield scope
    finally:
        conn.close()


def save_dry_run_lines(settings: Settings, scope: Scope, key: str, lines: Sequence[CostLine],
                       extra: str = "") -> list[str]:
    """Save the dry run (state/dryruns) and return the lines that show its ID and totals."""
    items = [line.item for line in lines if line.item]
    dry_run = save_dry_run(settings.state_dir, key, items, lines,
                           expiry_hours=scope.config.dryrun_expiry_hours, extra=extra)
    return cost_summary(dry_run, scope.config.free_providers)


def authorize(settings: Settings, scope: Scope, dryrun_id: str, key: str,
              lines: Sequence[CostLine], extra: str = "") -> list[Authorization]:
    """After "ok": check the dry run still matches, then one authorization per paid
    provider/unit; the dry run is marked used. DryRunError when it does not match."""
    dry_run = load_dry_run(settings.state_dir, dryrun_id)
    items = [line.item for line in lines if line.item]
    check_dry_run(dry_run, command=key, scope=items, lines=lines, extra=extra)
    created = create_from_dry_run(scope.conn, dry_run, free=scope.config.free_providers,
                                  command=scope.command)
    mark_used(settings.state_dir, dry_run, [auth.id for auth in created])
    scope.authorizations += [auth.id for auth in created]
    return created


def require_budget(scope: Scope, lines: Sequence[CostLine], hint: str) -> None:
    """Without --authorize: every paid line needs an open authorization with room for it."""
    missing = []
    for line in lines:
        if not scope.config.paid(line.provider) or line.estimate <= 0:
            continue
        auth = find_authorization(scope.conn, item_id=line.item, provider=line.provider,
                                  unit=line.unit, explicit=scope.authorizations,
                                  estimate=line.estimate)
        if auth is None or auth.remaining < line.estimate:
            missing.append(f"{line.item or 'direct'} {line.job_type} via {line.provider}")
    if missing:
        raise NotAuthorized(
            f"Not authorized: {', '.join(dict.fromkeys(missing))}. Run {hint} --dry-run, show the "
            'cost, and after the user\'s "ok" run it again with --authorize <dryrun_id>.'
        )


def authorization_lines(created: Sequence[Authorization]) -> list[str]:
    if not created:
        return ["Authorized: nothing to pay for (free providers only)."]
    return [f"Authorized: {auth.line()}" for auth in created]


__all__ = [
    "DryRunError",
    "authorization_lines",
    "authorize",
    "part_map",
    "registry_scope",
    "require_budget",
    "save_dry_run_lines",
]
