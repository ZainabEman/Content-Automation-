"""Jobs and idempotency for every external or paid operation (PRD D7, §14 D-5, D-6).

A job is one provider call (or one plugin call made by Codex): an image, a carousel still or
clip, a video scene, a Drive upload, a tracker write. Its key is sha256(item, version, job type,
normalized inputs, redo_n):
- open_job: a succeeded job with the same inputs whose result was not rejected is reused
  (job_reused, no new call); a queued or running one is returned as it is; otherwise a new job
  is queued with redo_n = the number of earlier failed, cancelled or rejected tries, so a
  deliberate redo (a failed person check, a carousel retry) is a new job that must fit the
  authorization.
- start_job: a paid provider needs an open authorization with room: spent + estimate <= max,
  otherwise BudgetExceeded (logged as authorization_exceeded) and the job does not start.
- succeed_job / fail_job charge the actual amount (the estimate when the provider reported
  none; said so in the event); cancel_job and reject_job end or discard a job.
- A running job past its type's timeout (config/jobs.json) is stale: never re-run by itself.
- check_job answers a Codex skill before each plugin call: go, skip or stop.
"""

import hashlib
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.auth import charge, find_authorization, get_authorization
from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.items import get_item
from content_automation.registry.progress import GENERATION_JOBS, job_started

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
Decision = Literal["go", "skip", "stop"]
DEFAULT_CONFIG_PATH = Path("config/jobs.json")


class NotAuthorized(RegistryError):
    """A paid job without an open authorization."""


class BudgetExceeded(RegistryError):
    """The job's estimate does not fit in what is left of the authorization."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class JobStateError(RegistryError):
    """The job is not in a state that allows this."""


@dataclass(frozen=True)
class JobConfig:
    dryrun_expiry_hours: float = 24.0
    free_providers: tuple[str, ...] = ("mock", "local", "ffmpeg", "library", "none", "drive",
                                       "sheets")
    units: dict[str, str] = field(default_factory=lambda: {
        "openrouter": "usd", "comfyui": "usd", "elevenlabs": "usd",
        "higgsfield-plugin": "credits", "heygen-plugin": "credits"})
    timeouts: dict[str, int] = field(default_factory=lambda: {"default": 3600})
    estimates: dict[str, dict[str, float]] = field(default_factory=dict)

    def paid(self, provider: str) -> bool:
        return provider not in self.free_providers

    def unit(self, provider: str) -> str:
        return self.units.get(provider, "usd")

    def timeout(self, job_type: str) -> int:
        return int(self.timeouts.get(job_type, self.timeouts.get("default", 3600)))

    def estimate(self, job_type: str, provider: str) -> float | None:
        value = self.estimates.get(job_type, {}).get(provider)
        return None if value is None else float(value)


def load_job_config(path: Path = DEFAULT_CONFIG_PATH) -> JobConfig:
    """config/jobs.json; a missing file gives the defaults."""
    if not path.is_file():
        return JobConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RegistryError(f"{path} is not valid JSON: {error}") from None
    estimates = {
        str(kind): {str(p): float(v) for p, v in values.items() if not str(p).startswith("_")}
        for kind, values in data.get("estimates", {}).items()
        if not str(kind).startswith("_") and isinstance(values, dict)
    }
    defaults = JobConfig()
    return JobConfig(
        dryrun_expiry_hours=float(data.get("dryrun_expiry_hours", defaults.dryrun_expiry_hours)),
        free_providers=tuple(data.get("free_providers", defaults.free_providers)),
        units={str(k): str(v) for k, v in data.get("units", defaults.units).items()},
        timeouts={str(k): int(v)
                  for k, v in data.get("timeouts_seconds", {"default": 3600}).items()},
        estimates=estimates,
    )


@dataclass(frozen=True)
class JobRecord:
    id: int
    item_id: str | None
    version: int | None
    job_type: str
    provider: str
    base_key: str
    redo_n: int
    key: str
    inputs: dict[str, Any]
    status: JobStatus
    attempts: int
    max_attempts: int
    estimate: float | None
    actual: float | None
    unit: str | None
    authorization_id: int | None
    result_path: str | None
    error: str | None
    rejected_at: str | None
    reject_reason: str | None
    timeout_seconds: int | None
    created_at: str
    started_at: str | None
    finished_at: str | None

    def stale(self, moment: datetime | None = None) -> bool:
        if self.status != "running" or self.started_at is None or self.timeout_seconds is None:
            return False
        started = datetime.strptime(self.started_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
        return (moment or datetime.now(UTC)) > started + timedelta(seconds=self.timeout_seconds)

    def line(self) -> str:
        cost = ""
        if self.unit:
            amount = self.actual if self.actual is not None else self.estimate
            kind = "actual" if self.actual is not None else "estimate"
            cost = f", {amount:g} {self.unit} ({kind})" if amount is not None else ""
        state = "stale" if self.stale() else self.status
        rejected = " [result rejected]" if self.rejected_at else ""
        redo = f" redo {self.redo_n}" if self.redo_n else ""
        return (f"#{self.id} {self.item_id or 'direct'} {self.job_type} via {self.provider}: "
                f"{state}{rejected}{redo}{cost}" + (f" — {self.error}" if self.error else ""))


@dataclass(frozen=True)
class Opened:
    job: JobRecord
    reused: bool = False  # a succeeded job with the same key: no new call
    in_progress: bool = False  # queued or running already


@dataclass(frozen=True)
class CheckResult:
    decision: Decision
    reason: str
    job: JobRecord


def _record(row: sqlite3.Row) -> JobRecord:
    def opt_float(name: str) -> float | None:
        return None if row[name] is None else float(row[name])

    def opt_str(name: str) -> str | None:
        return None if row[name] is None else str(row[name])

    return JobRecord(
        id=int(row["id"]), item_id=opt_str("item_id"),
        version=None if row["version"] is None else int(row["version"]),
        job_type=str(row["job_type"]), provider=str(row["provider"]),
        base_key=str(row["base_key"]), redo_n=int(row["redo_n"]),
        key=str(row["idempotency_key"]), inputs=dict(json.loads(row["inputs"])),
        status=cast(JobStatus, str(row["status"])), attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]), estimate=opt_float("estimate"),
        actual=opt_float("actual"), unit=opt_str("unit"),
        authorization_id=None if row["authorization_id"] is None else int(row["authorization_id"]),
        result_path=opt_str("result_path"), error=opt_str("error"),
        rejected_at=opt_str("rejected_at"), reject_reason=opt_str("reject_reason"),
        timeout_seconds=None if row["timeout_seconds"] is None else int(row["timeout_seconds"]),
        created_at=str(row["created_at"]), started_at=opt_str("started_at"),
        finished_at=opt_str("finished_at"),
    )


def normalize(inputs: Mapping[str, Any]) -> str:
    return json.dumps(inputs, sort_keys=True, ensure_ascii=False, default=str)


def _sha(*parts: object) -> str:
    return hashlib.sha256(json.dumps(parts, default=str).encode("utf-8")).hexdigest()


def get_job(conn: sqlite3.Connection, job_id: int) -> JobRecord:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise RegistryError(f"Job #{job_id} does not exist.")
    return _record(row)


def list_jobs(
    conn: sqlite3.Connection, *, item_id: str | None = None,
    statuses: Sequence[JobStatus] = (), job_types: Sequence[str] = (),
) -> list[JobRecord]:
    clauses: list[str] = []
    params: list[Any] = []
    if item_id is not None:
        clauses.append("item_id = ?")
        params.append(item_id)
    if statuses:
        clauses.append(f"status IN ({', '.join('?' for _ in statuses)})")
        params += list(statuses)
    if job_types:
        clauses.append(f"job_type IN ({', '.join('?' for _ in job_types)})")
        params += list(job_types)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    return [_record(row) for row in conn.execute(f"SELECT * FROM jobs{where} ORDER BY id", params)]


def _event(conn: sqlite3.Connection, kind: str, job: JobRecord, command: str | None,
           actor: Actor = "system", **details: Any) -> None:
    append_event(conn, kind, actor=actor, command=command, item_id=job.item_id,
                 version=job.version,
                 details={"job": job.id, "type": job.job_type, "provider": job.provider,
                          **details})


def open_job(
    conn: sqlite3.Connection,
    *,
    item_id: str | None,
    job_type: str,
    provider: str,
    inputs: Mapping[str, Any],
    config: JobConfig,
    estimate: float | None = None,
    unit: str | None = None,
    max_attempts: int = 1,
    explicit_auths: Sequence[int] = (),
    command: str | None = None,
) -> Opened:
    """Reuse, return the open one, or queue a new job (see the module text)."""
    with transaction(conn):
        version = get_item(conn, item_id).current_version if item_id is not None else None
        normalized = normalize(inputs)
        base = _sha(item_id, version, job_type, normalized)
        earlier = [_record(row) for row in conn.execute(
            "SELECT * FROM jobs WHERE base_key = ? ORDER BY id", (base,))]
        reusable = [job for job in earlier if job.status == "succeeded" and not job.rejected_at]
        if reusable:
            job = reusable[-1]
            _event(conn, "job_reused", job, command, key=job.key, result=job.result_path)
            return Opened(job, reused=True)
        active = [job for job in earlier if job.status in ("queued", "running")]
        if active:
            return Opened(active[-1], in_progress=True)
        redo_n = len(earlier)
        key = _sha(base, redo_n)
        paid = config.paid(provider)
        charged_unit = unit or (config.unit(provider) if paid else None)
        auth = (find_authorization(conn, item_id=item_id, provider=provider,
                                   unit=charged_unit or "usd", explicit=explicit_auths,
                                   estimate=estimate or 0.0) if paid else None)
        stamp = now()
        cursor = conn.execute(
            "INSERT INTO jobs (item_id, version, job_type, provider, base_key, redo_n, "
            "idempotency_key, inputs, status, attempts, max_attempts, estimate, unit, "
            "authorization_id, timeout_seconds, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, version, job_type, provider, base, redo_n, key, normalized, max_attempts,
             estimate, charged_unit, auth.id if auth else None, config.timeout(job_type), stamp,
             stamp),
        )
        job = get_job(conn, int(cursor.lastrowid or 0))
        _event(conn, "job_queued", job, command, key=key, redo_n=redo_n, estimate=estimate,
               unit=charged_unit, authorization_id=job.authorization_id)
        return Opened(job)


def _budget(conn: sqlite3.Connection, job: JobRecord, config: JobConfig,
            explicit: Sequence[int], command: str | None) -> int | None:
    """The authorization the job runs under (None for a free provider)."""
    if not config.paid(job.provider):
        return None
    estimate = job.estimate or 0.0
    unit = job.unit or config.unit(job.provider)
    auth = get_authorization(conn, job.authorization_id) if job.authorization_id else None
    if auth is None or auth.status != "open" or auth.remaining < estimate:
        auth = find_authorization(conn, item_id=job.item_id, provider=job.provider, unit=unit,
                                  explicit=explicit, estimate=estimate) or auth
    if auth is None or auth.status == "closed":
        raise NotAuthorized(
            f"Job #{job.id} ({job.job_type} via {job.provider}) has no open authorization: run "
            'the dry run, show the cost, and after the user\'s "ok" build with --authorize '
            "<dryrun_id>."
        )
    if auth.status == "exceeded" or auth.remaining < estimate:
        raise BudgetExceeded(
            f"Job #{job.id} needs about {estimate:g} {unit} but authorization #{auth.id} has "
            f"{max(auth.remaining, 0):g} of {auth.max_amount:g} left: not started. Ask the user; "
            "a new dry run and \"ok\" can authorize more.",
            {"authorization_id": auth.id, "needed": estimate, "remaining": auth.remaining,
             "unit": unit},
        )
    return auth.id


def start_job(
    conn: sqlite3.Connection, job_id: int, *, config: JobConfig, explicit_auths: Sequence[int] = (),
    actor: Actor = "system", command: str | None = None,
) -> JobRecord:
    """queued (or failed with an attempt left) -> running, inside the budget. A refusal for the
    budget is logged (authorization_exceeded) after nothing else was written."""
    try:
        return _start(conn, job_id, config, explicit_auths, actor, command)
    except BudgetExceeded as refused:
        _event(conn, "authorization_exceeded", get_job(conn, job_id), command,
               **refused.details)
        raise


def _start(conn: sqlite3.Connection, job_id: int, config: JobConfig,
           explicit_auths: Sequence[int], actor: Actor, command: str | None) -> JobRecord:
    with transaction(conn):
        job = get_job(conn, job_id)
        retry = job.status == "failed" and job.attempts < job.max_attempts
        if job.status != "queued" and not retry:
            raise JobStateError(f"Job #{job.id} is {job.status}; it cannot start.")
        auth_id = _budget(conn, job, config, explicit_auths, command)
        if job.item_id is not None and job.job_type in GENERATION_JOBS:
            job_started(conn, job.item_id, actor=actor, command=command)
        stamp = now()
        conn.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1, started_at = ?, "
            "authorization_id = ?, error = NULL, updated_at = ? WHERE id = ?",
            (stamp, auth_id, stamp, job.id),
        )
        job = get_job(conn, job.id)
        _event(conn, "job_started", job, command, actor, attempt=job.attempts,
               authorization_id=auth_id, estimate=job.estimate, unit=job.unit)
        return job


def _charge(conn: sqlite3.Connection, job: JobRecord, actual: float | None,
            command: str | None) -> tuple[float | None, str]:
    if job.authorization_id is None:
        return None, "free" if job.unit is None else "no authorization"
    if actual is not None:
        charge(conn, job.authorization_id, actual, job_id=job.id, command=command)
        return actual, "actual"
    if job.estimate:
        charge(conn, job.authorization_id, job.estimate, job_id=job.id, command=command)
        return job.estimate, "estimate (the provider reported no amount)"
    return 0.0, "nothing reported"


def succeed_job(
    conn: sqlite3.Connection, job_id: int, *, actual: float | None = None,
    result_path: str | None = None, actor: Actor = "system", command: str | None = None,
) -> JobRecord:
    """running (or queued: a plugin call recorded without a check) -> succeeded."""
    with transaction(conn):
        job = get_job(conn, job_id)
        if job.status not in ("queued", "running"):
            raise JobStateError(f"Job #{job.id} is {job.status}; it cannot succeed.")
        if job.status == "queued" and job.item_id is not None and job.job_type in GENERATION_JOBS:
            job_started(conn, job.item_id, actor=actor, command=command)
        counted, basis = _charge(conn, job, actual, command)
        stamp = now()
        conn.execute(
            "UPDATE jobs SET status = 'succeeded', actual = ?, result_path = ?, finished_at = ?, "
            "attempts = MAX(attempts, 1), updated_at = ? WHERE id = ?",
            (actual, result_path, stamp, stamp, job.id),
        )
        job = get_job(conn, job.id)
        _event(conn, "job_succeeded", job, command, actor, actual=actual, charged=counted,
               basis=basis, result=result_path)
        return job


def fail_job(
    conn: sqlite3.Connection, job_id: int, error: str, *, actual: float | None = None,
    actor: Actor = "system", command: str | None = None,
) -> JobRecord:
    """queued or running -> failed (an amount the provider still charged is counted)."""
    with transaction(conn):
        job = get_job(conn, job_id)
        if job.status not in ("queued", "running"):
            raise JobStateError(f"Job #{job.id} is {job.status}; it cannot fail.")
        counted = None
        if actual and job.authorization_id is not None:
            charge(conn, job.authorization_id, actual, job_id=job.id, command=command)
            counted = actual
        stamp = now()
        conn.execute(
            "UPDATE jobs SET status = 'failed', actual = ?, error = ?, finished_at = ?, "
            "attempts = MAX(attempts, 1), updated_at = ? WHERE id = ?",
            (actual, error, stamp, stamp, job.id),
        )
        job = get_job(conn, job.id)
        _event(conn, "job_failed", job, command, actor, error=error, charged=counted)
        return job


def cancel_job(conn: sqlite3.Connection, job_id: int, reason: str, *, actor: Actor = "user",
               command: str | None = None) -> JobRecord:
    """queued, running (e.g. stale) or failed -> cancelled; nothing is charged."""
    with transaction(conn):
        job = get_job(conn, job_id)
        if job.status in ("succeeded", "cancelled"):
            raise JobStateError(f"Job #{job.id} is {job.status}; it cannot be cancelled.")
        stamp = now()
        conn.execute("UPDATE jobs SET status = 'cancelled', error = ?, finished_at = ?, "
                     "updated_at = ? WHERE id = ?", (reason, stamp, stamp, job.id))
        job = get_job(conn, job.id)
        _event(conn, "job_cancelled", job, command, actor, reason=reason)
        return job


def reject_job(conn: sqlite3.Connection, job_id: int, reason: str, *, actor: Actor = "system",
               command: str | None = None) -> JobRecord:
    """A succeeded job whose result failed a check: never reused; the next try is a redo."""
    with transaction(conn):
        job = get_job(conn, job_id)
        if job.status != "succeeded":
            raise JobStateError(f"Job #{job.id} is {job.status}; only a succeeded result is "
                                "rejected.")
        if job.rejected_at:
            return job
        stamp = now()
        conn.execute("UPDATE jobs SET rejected_at = ?, reject_reason = ?, updated_at = ? "
                     "WHERE id = ?", (stamp, reason, stamp, job.id))
        job = get_job(conn, job.id)
        _event(conn, "job_rejected", job, command, actor, reason=reason)
        return job


def find_by_result(conn: sqlite3.Connection, result_path: str) -> JobRecord | None:
    """The newest job that produced this result (a job folder, an output file)."""
    target = Path(result_path).resolve()
    for job in reversed(list_jobs(conn, statuses=("succeeded",))):
        if job.result_path and Path(job.result_path).resolve() == target:
            return job
    return None


def check_job(
    conn: sqlite3.Connection, job_id: int, *, config: JobConfig, actor: Actor = "system",
    command: str | None = None,
) -> CheckResult:
    """Before a plugin call: go (it starts now, inside the budget), skip (already succeeded:
    reuse the recorded result) or stop (over budget, stale, cancelled, failed, running)."""
    job = get_job(conn, job_id)
    if job.status == "succeeded":
        reason = ("already succeeded: reuse the recorded result" if not job.rejected_at
                  else "its result was rejected; the request has a newer job")
        return CheckResult("skip" if not job.rejected_at else "stop", reason, job)
    if job.status == "cancelled":
        return CheckResult("stop", f"cancelled ({job.error or 'no reason'})", job)
    if job.status == "failed":
        return CheckResult("stop", f"failed ({job.error or 'no reason'}); a retry is a new job",
                           job)
    if job.status == "running":
        if job.stale():
            return CheckResult("stop", f"stale: running since {job.started_at} (longer than "
                               f"{job.timeout_seconds} s); cancel it with ca jobs cancel "
                               f"{job.id} before trying again", job)
        return CheckResult("stop", f"already started at {job.started_at}: record its result "
                           "instead of calling again", job)
    try:
        started = start_job(conn, job.id, config=config, actor=actor, command=command)
    except (NotAuthorized, BudgetExceeded) as error:
        return CheckResult("stop", str(error), get_job(conn, job.id))
    return CheckResult("go", "inside the authorization; it is marked running now", started)
