"""Jobs, authorizations and dry runs (PRD §14 D-4, D-5, D-6, D-16)."""

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from content_automation.registry.audit import list_events
from content_automation.registry.auth import create_from_dry_run, list_authorizations
from content_automation.registry.dryruns import (
    CostLine,
    DryRunError,
    check_dry_run,
    load_dry_run,
    mark_used,
    save_dry_run,
)
from content_automation.registry.items import Item, get_item, set_status
from content_automation.registry.jobs import (
    BudgetExceeded,
    JobConfig,
    NotAuthorized,
    cancel_job,
    check_job,
    fail_job,
    get_job,
    list_jobs,
    open_job,
    reject_job,
    start_job,
    succeed_job,
)
from content_automation.registry.progress import (
    part_done,
    part_failed,
    set_upload,
    upload_label,
    upload_target,
)

CONFIG = JobConfig(free_providers=("mock", "drive"), timeouts={"image": 60, "default": 60})


def _approved(new_item: Callable[..., Item], registry: sqlite3.Connection) -> Item:
    item = new_item()
    set_status(registry, item.id, "idea", "approved")
    return item


def _authorize(registry: sqlite3.Connection, tmp_path: Path, item: str | None, amount: float,
               provider: str = "openrouter", unit: str = "usd") -> int:
    line = CostLine(item, "image", provider, unit, amount, amount)
    dry_run = save_dry_run(tmp_path / "state", "test", [item] if item else [], [line],
                           expiry_hours=24)
    [auth] = create_from_dry_run(registry, dry_run, free=CONFIG.free_providers)
    return auth.id


def _open(registry: sqlite3.Connection, item: str | None, inputs: dict[str, object],
          estimate: float = 0.04, provider: str = "openrouter") -> int:
    opened = open_job(registry, item_id=item, job_type="image", provider=provider,
                      inputs=inputs, config=CONFIG, estimate=estimate)
    return opened.job.id


def test_reuse_and_redo(registry: sqlite3.Connection, new_item: Callable[..., Item],
                        tmp_path: Path) -> None:
    item = _approved(new_item, registry)
    _authorize(registry, tmp_path, item.id, 1.0)
    first = _open(registry, item.id, {"prompt": "a"})
    start_job(registry, first, config=CONFIG)
    succeed_job(registry, first, actual=0.039, result_path="outputs/jobs/x")
    again = open_job(registry, item_id=item.id, job_type="image", provider="openrouter",
                     inputs={"prompt": "a"}, config=CONFIG, estimate=0.04)
    assert again.reused and again.job.id == first  # a rerun: no new call
    assert [e.type for e in list_events(registry, types=["job_reused"])] == ["job_reused"]
    reject_job(registry, first, "person check failed")
    redo = open_job(registry, item_id=item.id, job_type="image", provider="openrouter",
                    inputs={"prompt": "a"}, config=CONFIG, estimate=0.04)
    assert not redo.reused and redo.job.redo_n == 1 and redo.job.key != again.job.key
    start_job(registry, redo.job.id, config=CONFIG)
    fail_job(registry, redo.job.id, "provider error")
    third = open_job(registry, item_id=item.id, job_type="image", provider="openrouter",
                     inputs={"prompt": "a"}, config=CONFIG, estimate=0.04)
    assert third.job.redo_n == 2
    open_again = open_job(registry, item_id=item.id, job_type="image", provider="openrouter",
                          inputs={"prompt": "a"}, config=CONFIG, estimate=0.04)
    assert open_again.in_progress and open_again.job.id == third.job.id


def test_budget_stop_and_charges(registry: sqlite3.Connection, new_item: Callable[..., Item],
                                 tmp_path: Path) -> None:
    item = _approved(new_item, registry)
    auth = _authorize(registry, tmp_path, item.id, 0.1)
    first = _open(registry, item.id, {"n": 1}, estimate=0.06)
    start_job(registry, first, config=CONFIG)
    succeed_job(registry, first, actual=0.06)
    second = _open(registry, item.id, {"n": 2}, estimate=0.06)
    with pytest.raises(BudgetExceeded, match="0.04 of 0.1 left"):
        start_job(registry, second, config=CONFIG)
    assert get_job(registry, second).status == "queued"  # not started
    [exceeded] = list_events(registry, types=["authorization_exceeded"])
    assert exceeded.details["authorization_id"] == auth
    third = _open(registry, item.id, {"n": 3}, estimate=0.02)
    start_job(registry, third, config=CONFIG)
    succeed_job(registry, third)  # no actual reported: the estimate is counted
    [current] = list_authorizations(registry)
    assert current.spent == pytest.approx(0.08) and current.status == "open"
    event = list_events(registry, types=["job_succeeded"])[-1]
    assert event.details["basis"].startswith("estimate")


def test_paid_jobs_need_an_authorization(registry: sqlite3.Connection,
                                         new_item: Callable[..., Item]) -> None:
    item = _approved(new_item, registry)
    paid = _open(registry, item.id, {"p": 1})
    with pytest.raises(NotAuthorized, match="--authorize"):
        start_job(registry, paid, config=CONFIG)
    free = _open(registry, item.id, {"p": 2}, provider="mock")
    assert start_job(registry, free, config=CONFIG).status == "running"


def test_generation_needs_an_approved_idea(registry: sqlite3.Connection,
                                           new_item: Callable[..., Item]) -> None:
    item = new_item()
    job = _open(registry, item.id, {"p": 1}, provider="mock")
    with pytest.raises(Exception, match="only while the idea is approved"):
        start_job(registry, job, config=CONFIG)
    assert get_job(registry, job).status == "queued"


def test_stale_jobs_and_check(registry: sqlite3.Connection, new_item: Callable[..., Item],
                              tmp_path: Path) -> None:
    item = _approved(new_item, registry)
    _authorize(registry, tmp_path, item.id, 1.0)
    job_id = _open(registry, item.id, {"s": 1})
    assert check_job(registry, job_id, config=CONFIG).decision == "go"
    assert check_job(registry, job_id, config=CONFIG).decision == "stop"  # already started
    old = (datetime.now(UTC) - timedelta(seconds=120)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    registry.execute("UPDATE jobs SET started_at = ? WHERE id = ?", (old, job_id))
    job = get_job(registry, job_id)
    assert job.stale()
    result = check_job(registry, job_id, config=CONFIG)
    assert result.decision == "stop" and "stale" in result.reason
    cancel_job(registry, job_id, "the plugin call never came back")
    assert check_job(registry, job_id, config=CONFIG).decision == "stop"
    done = _open(registry, item.id, {"s": 2})
    start_job(registry, done, config=CONFIG)
    succeed_job(registry, done, actual=0.01)
    skip = check_job(registry, done, config=CONFIG)
    assert skip.decision == "skip" and "reuse" in skip.reason
    over = _open(registry, item.id, {"s": 3}, estimate=5.0)
    assert check_job(registry, over, config=CONFIG).decision == "stop"


def test_generation_status_from_jobs_and_parts(registry: sqlite3.Connection,
                                               new_item: Callable[..., Item]) -> None:
    item = _approved(new_item, registry)
    first = _open(registry, item.id, {"g": 1}, provider="mock")
    start_job(registry, first, config=CONFIG)
    assert get_item(registry, item.id).generation_status == "running"
    succeed_job(registry, first)
    second = _open(registry, item.id, {"g": 2}, provider="mock")
    start_job(registry, second, config=CONFIG)
    part_failed(registry, item.id)
    assert get_item(registry, item.id).generation_status == "running"  # a job is still open
    fail_job(registry, second, "provider error")
    assert part_failed(registry, item.id).generation_status == "partial"
    assert part_done(registry, item.id).generation_status == "generated"
    other = _approved(new_item, registry)
    job = _open(registry, other.id, {"g": 3}, provider="mock")
    start_job(registry, job, config=CONFIG)
    fail_job(registry, job, "error")
    assert part_failed(registry, other.id).generation_status == "failed"
    untouched = _approved(new_item, registry)
    assert part_failed(registry, untouched.id).generation_status == "not_started"


def test_upload_status_from_files(registry: sqlite3.Connection,
                                  new_item: Callable[..., Item]) -> None:
    assert upload_target({}, []) == "not_uploaded"
    assert upload_target({"a": "uploaded", "b": "uploading"}, ["a", "b"]) == "uploading"
    assert upload_target({"a": "uploaded", "b": "failed"}, ["a", "b"]) == "failed"
    assert upload_target({"a": "uploaded"}, ["a", "b"]) == "uploading"
    assert upload_target({"a": "uploaded", "b": "uploaded"}, ["a", "b"]) == "uploaded"
    item = new_item()
    failed = set_upload(registry, item.id, "failed", "mock")
    assert failed.upload_status == "failed"
    done = set_upload(registry, item.id, "uploaded", "mock")
    assert done.upload_status == "uploaded" and done.upload_provider == "mock"
    assert upload_label(done, done.upload_provider) == "uploaded (mock)"
    assert upload_label(done, "drive") == "uploaded"


def test_dry_runs_expired_used_changed(tmp_path: Path) -> None:
    state = tmp_path / "state"
    line = CostLine("BG-001", "image", "openrouter", "usd", 0.04, 0.04)
    dry_run = save_dry_run(state, "content build x", ["BG-001"], [line], expiry_hours=24)
    assert dry_run.id.startswith("DR-") and load_dry_run(state, dry_run.id) == dry_run
    check_dry_run(dry_run, command="content build x", scope=["BG-001"], lines=[line])
    with pytest.raises(DryRunError, match="items changed"):
        check_dry_run(dry_run, command="content build x", scope=["BG-001", "BG-002"],
                      lines=[line])
    dearer = CostLine("BG-001", "image", "openrouter", "usd", 0.08, 0.08)
    with pytest.raises(DryRunError, match="costs changed"):
        check_dry_run(dry_run, command="content build x", scope=["BG-001"], lines=[dearer])
    with pytest.raises(DryRunError, match="was for"):
        check_dry_run(dry_run, command="content build y", scope=["BG-001"], lines=[line])
    later = datetime.now(UTC) + timedelta(hours=25)
    with pytest.raises(DryRunError, match="expired"):
        check_dry_run(dry_run, command="content build x", scope=["BG-001"], lines=[line],
                      now=later)
    mark_used(state, dry_run, [1])
    with pytest.raises(DryRunError, match="already used"):
        check_dry_run(load_dry_run(state, dry_run.id), command="content build x",
                      scope=["BG-001"], lines=[line])
    with pytest.raises(DryRunError, match="Unknown dry run"):
        load_dry_run(state, "DR-20260101-000000-abcd")


def test_one_authorization_per_provider_and_unit(registry: sqlite3.Connection,
                                                 tmp_path: Path) -> None:
    lines = [CostLine("BG-001", "image", "openrouter", "usd", 0.04, 0.04),
             CostLine("BG-002", "image", "openrouter", "usd", 0.08, 0.08),
             CostLine("BG-002", "still", "higgsfield-plugin", "credits", 35, 70),
             CostLine("BG-003", "image", "mock", "usd", 0, 0)]
    dry_run = save_dry_run(tmp_path / "state", "calendar generate 2026-W42",
                           ["BG-001", "BG-002", "BG-003"], lines, expiry_hours=24)
    auths = create_from_dry_run(registry, dry_run, free=CONFIG.free_providers)
    assert [(a.provider, a.unit, a.max_amount, a.item_ids) for a in auths] == [
        ("higgsfield-plugin", "credits", 70, ("BG-002",)),
        ("openrouter", "usd", pytest.approx(0.12), ("BG-001", "BG-002")),
    ]
    assert {a.dryrun_id for a in auths} == {dry_run.id}
    assert len(list_events(registry, types=["authorization_created"])) == 2


def test_jobs_listing(registry: sqlite3.Connection, new_item: Callable[..., Item]) -> None:
    item = _approved(new_item, registry)
    job = _open(registry, item.id, {"l": 1}, provider="mock")
    assert [j.id for j in list_jobs(registry, statuses=("queued", "running"))] == [job]
    start_job(registry, job, config=CONFIG)
    fail_job(registry, job, "boom")
    assert [j.status for j in list_jobs(registry, item_id=item.id)] == ["failed"]
    assert "failed" in get_job(registry, job).line() and "boom" in get_job(registry, job).line()
