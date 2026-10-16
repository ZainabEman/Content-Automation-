"""The pipelines under the registry (PRD §14 D-4, D-5, D-6, D-16), offline with mocks."""

import json
import sqlite3
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_automation.ai.image import ImageRequest
from content_automation.cli import app
from content_automation.cli.bridge import record_agent_job
from content_automation.cli.scope import require_budget
from content_automation.content.deliverables import load_deliverables
from content_automation.content.package import ContentPackage, PackageItem, save_package
from content_automation.core.config import Settings
from content_automation.registry import db_path, open_registry
from content_automation.registry.audit import list_events
from content_automation.registry.auth import create_from_dry_run, list_authorizations
from content_automation.registry.dryruns import CostLine, save_dry_run
from content_automation.registry.items import Item, create_item, get_item, set_status
from content_automation.registry.jobs import (
    JobConfig,
    NotAuthorized,
    check_job,
    get_job,
    list_jobs,
    open_job,
)
from content_automation.registry.runtime import Scope, activate
from content_automation.storage import sync_package
from content_automation.storage.providers.mock import MockStorage
from content_automation.workflows.carousel_design import (
    CarouselDesign,
    SlideText,
    load_carousel_design,
)
from content_automation.workflows.carousel_plugin import (
    load_plan,
    load_request,
    output_file,
    planned_split,
    record_attempt,
    stills_check,
    write_still_requests,
)
from content_automation.workflows.carousel_render import background
from content_automation.workflows.image_job import run_image_job

REPO = Path(__file__).resolve().parents[2]
TYPES = ("cover", "point", "stat", "point", "list", "point", "point", "final")
PART_OF = {"instagram_carousel": "carousel", "linkedin_post": "post"}


@pytest.fixture
def conn(isolated: Path) -> Iterator[sqlite3.Connection]:
    connection = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield connection
    connection.close()


def _paid_mock(isolated: Path, make_settings: Callable[..., Settings]) -> Settings:
    """The mock image provider treated as paid (no free providers), so budgets apply."""
    jobs = isolated / "jobs.json"
    jobs.write_text(json.dumps({"free_providers": []}), encoding="utf-8")
    return make_settings(JOBS_FILE=str(jobs))


def _item(conn: sqlite3.Connection, folder: Path | None = None, kind: str = "carousel",
          deliverable: str = "instagram_carousel") -> Item:
    item = create_item(conn, kind=kind, title="Chatbots for dentists", topic="Chatbots",
                       platforms=["instagram"], deliverable=deliverable,
                       package_path=folder.as_posix() if folder else None)
    set_status(conn, item.id, "idea", "approved")
    return item


def _authorize(conn: sqlite3.Connection, lines: list[CostLine], free: tuple[str, ...] = ()
               ) -> list[int]:
    dry_run = save_dry_run(Path("state"), "test", [line.item for line in lines if line.item],
                           lines, expiry_hours=24)
    return [auth.id for auth in create_from_dry_run(conn, dry_run, free=free)]


def _request() -> ImageRequest:
    return ImageRequest(prompt="a calm office", aspect_ratio="1:1", count=1)


# --- images ------------------------------------------------------------------------------


def test_paid_image_without_authorization_is_refused(
    isolated: Path, make_settings: Callable[..., Settings], conn: sqlite3.Connection
) -> None:
    settings = _paid_mock(isolated, make_settings)
    with pytest.raises(NotAuthorized, match="--authorize"):
        run_image_job(_request(), settings)  # no `ca` command: refused before any job
    item = _item(conn, kind="post", deliverable="linkedin_post")
    scope = Scope(conn, JobConfig(free_providers=()), command="test", item=item.id)
    with activate(scope), pytest.raises(NotAuthorized):
        run_image_job(_request(), settings)
    assert not list(settings.output_dir.rglob("details.json"))  # nothing was made


def test_authorized_image_runs_once_and_is_reused(
    isolated: Path, make_settings: Callable[..., Settings], conn: sqlite3.Connection
) -> None:
    settings = _paid_mock(isolated, make_settings)
    item = _item(conn, kind="post", deliverable="linkedin_post")
    _authorize(conn, [CostLine(item.id, "image", "mock", "usd", 0.0, 0.0)])
    scope = Scope(conn, JobConfig(free_providers=()), command="test", item=item.id)
    with activate(scope):
        first = run_image_job(_request(), settings)
        again = run_image_job(_request(), settings)
    assert first.status == "completed" and again.job_id == first.job_id
    assert len(list(settings.output_dir.rglob("details.json"))) == 1  # no second call
    assert [e.type for e in list_events(conn, types=["job_reused"])] == ["job_reused"]
    [job] = list_jobs(conn, item_id=item.id)
    assert job.status == "succeeded" and job.result_path == first.folder.as_posix()
    assert get_item(conn, item.id).generation_status == "running"  # the part decides "done"


def test_ca_image_dry_run_then_authorize(isolated: Path) -> None:
    runner = CliRunner()
    dry = runner.invoke(app, ["image", "--prompt", "x", "--dry-run"])
    assert dry.exit_code == 0, dry.output
    line = next(text for text in dry.stdout.splitlines() if text.startswith("Dry run ID:"))
    dryrun_id = line.split()[3]
    assert dryrun_id.startswith("DR-") and "free: nothing to authorize" in line
    built = runner.invoke(app, ["image", "--prompt", "x", "--authorize", dryrun_id])
    assert built.exit_code == 0, built.output
    assert "Authorized: nothing to pay for" in built.stdout
    again = runner.invoke(app, ["image", "--prompt", "x", "--authorize", dryrun_id])
    assert again.exit_code == 1 and "already used" in again.stderr


def test_require_budget(conn: sqlite3.Connection) -> None:
    item = _item(conn, kind="post", deliverable="linkedin_post")
    scope = Scope(conn, JobConfig(free_providers=("mock",)), command="test")
    paid = [CostLine(item.id, "image", "openrouter", "usd", 0.04, 0.04)]
    require_budget(scope, [CostLine(item.id, "image", "mock", "usd", 0.0, 0.0)], "x")
    with pytest.raises(NotAuthorized, match="Not authorized"):
        require_budget(scope, paid, "uv run ca content build")
    _authorize(conn, paid, free=("mock",))
    require_budget(scope, paid, "uv run ca content build")


# --- carousel ------------------------------------------------------------------------------


def _design() -> CarouselDesign:
    design = load_carousel_design(REPO / "config" / "carousel_design.json")
    stills = design.stills.model_copy(update={"reference_images": "no", "provider": "higgsfield"})
    return design.model_copy(update={"stills": stills})


def _slides() -> list[SlideText]:
    return [SlideText(type=kind, headline=f"Slide {n}", body="Text")  # type: ignore[arg-type]
            for n, kind in enumerate(TYPES, start=1)]


def _record_still(package: Path, slide: int, design: CarouselDesign, conn: sqlite3.Connection,
                  config: JobConfig) -> None:
    request = load_request(package, "still", slide)
    assert request.job_id is not None
    assert check_job(conn, request.job_id, config=config).decision == "go"
    target = output_file(package, "still", slide)
    target.parent.mkdir(parents=True, exist_ok=True)
    background(design).save(target)
    record_attempt(package, "still", slide, design, credits=5)


def test_mock_carousel_makes_every_slide_local(isolated: Path, conn: sqlite3.Connection) -> None:
    design = _design()
    design = design.model_copy(
        update={"stills": design.stills.model_copy(update={"provider": "mock"})})
    package = Path("outputs/content/2026-10-16_carousel")
    package.mkdir(parents=True)
    item = _item(conn, package)
    assert planned_split(package, _slides(), design) == (0, 0, 0, 0)
    with activate(Scope(conn, JobConfig(), command="test", part_of=PART_OF)):
        lines = write_still_requests(package, "Chatbots", _slides(), design)
    assert "no Higgsfield requests, 8 local still(s)" in lines[0]
    plan = load_plan(package)
    assert plan is not None and plan.estimated_credits == 0
    assert all(slide.source == "local" and slide.motion == "local" and not slide.request
               for slide in plan.slides)
    assert all((package / slide.still).is_file() for slide in plan.slides)
    assert list_jobs(conn, item_id=item.id) == []
    assert "No clips to make (all local)" in stills_check(package, design)[-1]


def test_carousel_interrupted_then_resumed(
    isolated: Path, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CAROUSEL_DESIGN_FILE", str(REPO / "config" / "carousel_design.json"))
    design = _design()
    package = Path("outputs/content/2026-10-13_carousel")
    package.mkdir(parents=True)
    item = _item(conn, package)
    split = planned_split(package, _slides(), design)
    assert split is not None
    still_est, still_max, clip_est, clip_max = split
    [auth] = _authorize(conn, [
        CostLine(item.id, "still", "higgsfield-plugin", "credits", still_est, still_max),
        CostLine(item.id, "clip", "higgsfield-plugin", "credits", clip_est, clip_max),
    ])
    config = JobConfig()
    scope = Scope(conn, config, command="test", part_of=PART_OF)
    with activate(scope):
        write_still_requests(package, "Chatbots", _slides(), design)
        plan = load_plan(package)
        assert plan is not None and plan.approved_max_credits == still_max + clip_max
        for slide in (1, 2, 3):  # then the session stops
            _record_still(package, slide, design, conn, config)
    unfinished = list_jobs(conn, statuses=("queued", "running"))
    assert [job.inputs["slide"] for job in unfinished] == [4, 5, 6, 7]
    runner = CliRunner()
    listed = runner.invoke(app, ["jobs", "list", "--unfinished"])
    assert listed.exit_code == 0 and "4 job(s)" in listed.stdout
    resumed = runner.invoke(app, ["jobs", "resume", item.id])
    assert resumed.exit_code == 0, resumed.output
    assert "still_04" in resumed.stdout and "still_07" in resumed.stdout
    with activate(scope):
        for slide in (4, 5, 6, 7):
            _record_still(package, slide, design, conn, config)
    assert list_jobs(conn, statuses=("queued", "running")) == []
    assert runner.invoke(app, ["jobs", "resume"]).stdout.strip() == "No unfinished jobs."
    [authorization] = list_authorizations(conn)
    assert authorization.id == auth and authorization.spent == pytest.approx(35)
    assert get_item(conn, item.id).generation_status == "running"
    check = runner.invoke(app, ["jobs", "check", str(unfinished[0].id)])
    assert check.stdout.splitlines()[0] == "skip"


def test_legacy_carousel_resumes_under_its_old_max(
    isolated: Path, conn: sqlite3.Connection
) -> None:
    design = _design()
    package = Path("outputs/content/2026-10-01_legacy")
    package.mkdir(parents=True)
    write_still_requests(package, "Old", _slides(), design)  # before the registry: no jobs
    assert load_request(package, "still", 1).job_id is None
    item = _item(conn, package)
    scope = Scope(conn, JobConfig(), command="test", part_of=PART_OF)
    with activate(scope):
        lines = record_attempt(package, "still", 1, design,
                               error="plugin timeout")
    assert any("Retry still_01" in line for line in lines)
    retry = load_request(package, "still", 1)
    assert retry.job_id is not None
    [legacy] = list_authorizations(conn)
    plan = load_plan(package)
    assert plan is not None and legacy.max_amount == plan.approved_max_credits
    assert legacy.note is not None and "before the registry" in legacy.note
    assert get_job(conn, retry.job_id).item_id == item.id


# --- video agent steps and Drive uploads ---------------------------------------------------


def test_agent_step_job_is_closed_by_job_complete(isolated: Path,
                                                  conn: sqlite3.Connection) -> None:
    item = _item(conn, kind="short", deliverable="reel_short")
    _authorize(conn, [CostLine(item.id, "video_scene", "higgsfield-plugin", "credits", 35, 35)])
    config = JobConfig()
    opened = open_job(conn, item_id=item.id, job_type="video_scene", provider="higgsfield-plugin",
                      inputs={"step": "scene-1"}, config=config, estimate=35)
    folder = isolated / "outputs" / "jobs" / "v1"
    (folder / "requests").mkdir(parents=True)
    (folder / "requests" / "scene-1.json").write_text(json.dumps({
        "stepId": "scene-1", "capability": "video", "provider": "higgsfield-plugin",
        "model": "m", "plugin": "Higgsfield", "prompt": "p", "jobId": opened.job.id,
    }), encoding="utf-8")
    with activate(Scope(conn, config, command="test")):
        note = record_agent_job(folder, "scene-1", credits=30, result="clip.mp4")
    assert note is not None and "succeeded" in note
    job = get_job(conn, opened.job.id)
    assert job.status == "succeeded" and job.actual == 30


def test_drive_uploads_are_jobs_and_set_the_upload_status(
    isolated: Path, conn: sqlite3.Connection
) -> None:
    folder = Path("outputs/content/2026-10-13_post")
    (folder / "images").mkdir(parents=True)
    (folder / "images" / "post-1.png").write_bytes(b"png")
    save_package(folder, ContentPackage(
        package_id=folder.name, topic="Chatbots", platform="linkedin", formats=["post"],
        deliverables=["linkedin_post"], content_id="2026-W42-01",
        items={"post": PackageItem(status="done", files=["images/post-1.png"])},
    ))
    item = _item(conn, folder, kind="post", deliverable="linkedin_post")
    storage = MockStorage(isolated / "outputs" / "drive" / "Content Automation")
    catalog = load_deliverables(REPO / "config" / "deliverables.json")
    with activate(Scope(conn, JobConfig(), command="test", part_of=PART_OF)):
        first = sync_package(folder, storage, catalog)
        second = sync_package(folder, storage, catalog)
    assert "1 uploaded" in first.lines[0] and "1 already there" in second.lines[0]
    [upload] = list_jobs(conn, item_id=item.id)
    assert upload.job_type == "upload" and upload.status == "succeeded"
    after = get_item(conn, item.id)
    assert (after.upload_status, after.upload_provider) == ("uploaded", "mock")
