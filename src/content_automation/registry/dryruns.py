"""Saved dry runs (PRD §14 D-4): what an "ok" approves.

Every dry run is saved as <STATE_DIR>/dryruns/<DR-YYYYMMDD-HHMMSS-xxxx>.json: the command, the
item IDs in scope, one cost line per item, job type, provider and unit (estimate and max with
retries), the totals per provider/unit, when it expires and whether it was used. A build runs
with --authorize <id> only if the dry run exists, has not expired, was not used before and
still matches: the same command, the same items and the same costs. Otherwise the user is told
to run a new dry run. Free lines (mock, local) need no authorization.
"""

import hashlib
import json
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from content_automation.core.files import atomic_write_text
from content_automation.registry.db import RegistryError

DRYRUN_DIR = "dryruns"
NEW_DRY_RUN = "run the dry run again and approve the new one"


class DryRunError(RegistryError):
    """The dry run cannot authorize this build; the message says why and what to do."""


@dataclass(frozen=True)
class CostLine:
    item: str | None  # BG ID, or None for a direct `ca image` / `ca video`
    job_type: str  # image, still, clip, video_scene, avatar_scene
    provider: str
    unit: str  # usd or credits
    estimate: float
    max: float  # with every retry the plan allows
    label: str = ""

    def key(self) -> str:
        return f"{self.provider}/{self.unit}"


@dataclass
class DryRun:
    id: str
    created_at: str
    expires_at: str
    command: str
    scope: list[str]
    lines: list[CostLine]
    fingerprint: str
    used: bool = False
    used_at: str | None = None
    authorization_ids: list[int] = field(default_factory=list)

    def totals(self, free: Iterable[str] = ()) -> dict[str, dict[str, float]]:
        """estimate and max per provider/unit (free providers left out when given)."""
        skip = set(free)
        totals: dict[str, dict[str, float]] = {}
        for line in self.lines:
            if line.provider in skip:
                continue
            entry = totals.setdefault(line.key(), {"estimate": 0.0, "max": 0.0})
            entry["estimate"] = round(entry["estimate"] + line.estimate, 6)
            entry["max"] = round(entry["max"] + line.max, 6)
        return totals

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["totals"] = self.totals()
        return data


def _stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _parse(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def fingerprint(command: str, scope: Sequence[str], lines: Sequence[CostLine],
                extra: str = "") -> str:
    """The same command, items and costs give the same fingerprint (order does not matter)."""
    rows = sorted(
        (line.item or "", line.job_type, line.provider, line.unit, round(line.estimate, 6),
         round(line.max, 6)) for line in lines
    )
    payload = json.dumps([command, sorted(scope), rows, extra], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _folder(state_dir: Path) -> Path:
    return state_dir / DRYRUN_DIR


def _path(state_dir: Path, dryrun_id: str) -> Path:
    if not dryrun_id.startswith("DR-") or "/" in dryrun_id or "\\" in dryrun_id:
        raise DryRunError(f'"{dryrun_id}" is not a dry run ID (DR-YYYYMMDD-HHMMSS-xxxx).')
    return _folder(state_dir) / f"{dryrun_id}.json"


def save_dry_run(
    state_dir: Path,
    command: str,
    scope: Sequence[str],
    lines: Sequence[CostLine],
    *,
    expiry_hours: float,
    extra: str = "",
    now: datetime | None = None,
) -> DryRun:
    """Save a dry run and return it (its ID goes into the dry-run output)."""
    moment = now or datetime.now(UTC)
    dryrun_id = f"DR-{moment.astimezone(UTC):%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"
    dry_run = DryRun(
        id=dryrun_id,
        created_at=_stamp(moment),
        expires_at=_stamp(moment + timedelta(hours=expiry_hours)),
        command=command,
        scope=sorted(set(scope)),
        lines=list(lines),
        fingerprint=fingerprint(command, scope, lines, extra),
    )
    _write(state_dir, dry_run)
    return dry_run


def _write(state_dir: Path, dry_run: DryRun) -> None:
    path = _path(state_dir, dry_run.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(dry_run.to_json(), indent=2, ensure_ascii=False) + "\n")


def load_dry_run(state_dir: Path, dryrun_id: str) -> DryRun:
    path = _path(state_dir, dryrun_id.strip())
    if not path.is_file():
        raise DryRunError(f"Unknown dry run {dryrun_id}: {NEW_DRY_RUN}.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return DryRun(
            id=str(data["id"]),
            created_at=str(data["created_at"]),
            expires_at=str(data["expires_at"]),
            command=str(data["command"]),
            scope=[str(item) for item in data["scope"]],
            lines=[CostLine(**line) for line in data["lines"]],
            fingerprint=str(data["fingerprint"]),
            used=bool(data.get("used", False)),
            used_at=data.get("used_at"),
            authorization_ids=[int(i) for i in data.get("authorization_ids", [])],
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise DryRunError(
            f"Dry run {dryrun_id} is not readable ({error}): {NEW_DRY_RUN}."
        ) from None


def check_dry_run(
    dry_run: DryRun,
    *,
    command: str,
    scope: Sequence[str],
    lines: Sequence[CostLine],
    extra: str = "",
    now: datetime | None = None,
) -> None:
    """Refuse an expired, used or changed dry run (DryRunError says which)."""
    moment = now or datetime.now(UTC)
    if dry_run.used:
        raise DryRunError(f"Dry run {dry_run.id} was already used ({dry_run.used_at}): "
                          f"{NEW_DRY_RUN}.")
    if moment >= _parse(dry_run.expires_at):
        raise DryRunError(f"Dry run {dry_run.id} expired at {dry_run.expires_at}: "
                          f"{NEW_DRY_RUN}.")
    if dry_run.command != command:
        raise DryRunError(f'Dry run {dry_run.id} was for "{dry_run.command}", not "{command}": '
                          f"{NEW_DRY_RUN}.")
    if sorted(set(scope)) != dry_run.scope:
        raise DryRunError(
            f"The items changed since dry run {dry_run.id} ({', '.join(dry_run.scope) or 'none'}"
            f" then, {', '.join(sorted(set(scope))) or 'none'} now): {NEW_DRY_RUN}."
        )
    if fingerprint(command, scope, lines, extra) != dry_run.fingerprint:
        raise DryRunError(f"The costs changed since dry run {dry_run.id}: {NEW_DRY_RUN}.")


def mark_used(state_dir: Path, dry_run: DryRun, authorization_ids: Sequence[int],
              now: datetime | None = None) -> DryRun:
    dry_run.used = True
    dry_run.used_at = _stamp(now or datetime.now(UTC))
    dry_run.authorization_ids = list(authorization_ids)
    _write(state_dir, dry_run)
    return dry_run


def cost_summary(dry_run: DryRun, free: Iterable[str]) -> list[str]:
    """The lines to print under a dry run: its ID, the totals and how to approve it."""
    totals = dry_run.totals(free)
    if not totals:
        return [f"Dry run ID: {dry_run.id} (free: nothing to authorize)."]
    parts = [f"{key}: about {value['estimate']:g}, max {value['max']:g}"
             for key, value in sorted(totals.items())]
    return [
        f"Dry run ID: {dry_run.id} (expires {dry_run.expires_at[:16].replace('T', ' ')} UTC); "
        f"{'; '.join(parts)}.",
        f'After the user says "ok", build with: --authorize {dry_run.id}',
    ]
