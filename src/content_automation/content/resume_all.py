"""`ca jobs resume --all` (Phase 10 Step 1, UC-21): every resumable type at once.

- carousel (still and clip jobs): the carousel's next step (its existing continue logic);
- queued image jobs: within an open authorization the build that continues them; without
  one, a new dry run and the user's "ok" (never run here);
- uploads: a stale (running too long) or failed upload is re-queued (a new request file);
  a queued one is an outstanding plugin request for the upload skill;
- HeyGen podcast requests and video jobs: waiting plugin steps are listed for the make-video
  skill; a video job with every step recorded is resumed (`ca video resume`);
- anything else: "needs manual action: <what>".
Nothing here calls a paid or external service.
"""

import sqlite3
from pathlib import Path

from content_automation.ai.avatar import AvatarError
from content_automation.ai.video import VideoError
from content_automation.core.agent_steps import request_path
from content_automation.core.config import Settings
from content_automation.core.jobs import DETAILS_FILE, Job
from content_automation.core.media import MediaError
from content_automation.registry.auth import get_authorization
from content_automation.registry.db import RegistryError
from content_automation.registry.items import get_item
from content_automation.registry.jobs import (
    JobConfig,
    JobRecord,
    cancel_job,
    list_jobs,
    retry_candidates,
)
from content_automation.storage.review_upload import REQUESTS_DIR, queue_upload
from content_automation.workflows.carousel_design import load_carousel_design
from content_automation.workflows.carousel_plugin import continue_lines
from content_automation.workflows.video_job import PLAN_FILE, resume_video_job

CAROUSEL_JOBS = ("still", "clip")
VIDEO_OPEN = ("queued", "processing", "awaiting_agent")


def _manual(job: JobRecord, what: str) -> str:
    return f"{job.line()}: needs manual action: {what}"


def _requeue(conn: sqlite3.Connection, settings: Settings, job: JobRecord,
             command: str | None) -> str:
    if job.item_id is None or "file" not in job.inputs or "folder" not in job.inputs:
        return _manual(job, "an upload without its item, file or folder")
    if job.status == "running":
        cancel_job(conn, job.id, "stale: re-queued by ca jobs resume --all", actor="system",
                   command=command)
    line = queue_upload(conn, settings, job.item_id, Path(str(job.inputs["file"])),
                        str(job.inputs["folder"]), command=command)
    return f"#{job.id} {job.item_id} upload {job.status}: re-queued as {line} (upload skill)"


def _image(conn: sqlite3.Connection, job: JobRecord) -> str:
    auth = get_authorization(conn, job.authorization_id) if job.authorization_id else None
    if auth is None or auth.status != "open" or auth.remaining < (job.estimate or 0.0):
        return _manual(job, "no open authorization: a new dry run and the user's \"ok\"")
    package = get_item(conn, job.item_id).package_path if job.item_id else None
    if package is None:
        return _manual(job, "a direct image run: run the ca image command again")
    return (f"{job.line()}: resume (authorization #{auth.id} open, {auth.remaining:g} "
            f'{auth.unit} left): uv run ca content build "{package}"')


def _carousel(conn: sqlite3.Connection, settings: Settings, item_id: str) -> list[str]:
    package = get_item(conn, item_id).package_path
    if package is None:
        return [f"{item_id}: needs manual action: carousel jobs but no package folder"]
    design = load_carousel_design(settings.carousel_design_file)
    return [f"{item_id} (carousel):",
            *[f"  {line}" for line in continue_lines(Path(package), design)]]


def _videos(settings: Settings) -> list[str]:
    lines = []
    for details in sorted(Path(settings.output_dir).glob(f"*/*/{DETAILS_FILE}")):
        if not (details.parent / PLAN_FILE).is_file():
            continue
        try:
            job = Job.load(details)
        except (OSError, ValueError):
            lines.append(f"{details.parent.as_posix()}: needs manual action: unreadable "
                         f"{DETAILS_FILE}")
            continue
        if job.status not in VIDEO_OPEN:
            continue
        waiting = job.waiting_steps()
        if waiting:
            lines += [f"Video {job.job_id} {step.step_id}: plugin request "
                      f"{request_path(job.folder, step.step_id).as_posix()} (make-video skill)"
                      for step in waiting]
            continue
        try:
            job = resume_video_job(job, settings)
        except (VideoError, AvatarError, MediaError, OSError, ValueError) as error:
            lines.append(f"Video {job.job_id}: needs manual action: {error}")
            continue
        lines.append(f"Video {job.job_id}: resumed, {job.status} ({job.folder.as_posix()})")
    return lines


def resume_all(conn: sqlite3.Connection, settings: Settings, config: JobConfig, *,
               command: str | None = None) -> list[str]:
    lines: list[str] = []
    carousels: list[str] = []
    for job in list_jobs(conn, statuses=("queued", "running")):
        if job.job_type == "upload":
            if job.stale():
                lines.append(_requeue(conn, settings, job, command))
            else:
                request = settings.state_dir / REQUESTS_DIR / f"{job.id}.json"
                lines.append(f"{job.line()}: plugin request {request.as_posix()} (upload "
                             "skill)")
        elif job.stale():
            lines.append(_manual(job, f'stale: ca jobs cancel {job.id} "<reason>" first; '
                                      "never re-run by itself"))
        elif job.job_type in CAROUSEL_JOBS and job.item_id is not None:
            if job.item_id not in carousels:
                carousels.append(job.item_id)
        elif job.job_type == "image" and job.status == "queued":
            lines.append(_image(conn, job))
        elif "video_job" in job.inputs:
            continue  # a video job's plugin step: listed with its job folder below
        elif job.job_type == "avatar_scene" and job.provider == "heygen-plugin":
            request = settings.state_dir / "heygen" / f"{job.id}.json"
            lines.append(f"{job.line()}: plugin request {request.as_posix()} (make-video "
                         f"skill; then uv run ca podcast record {job.id} <file>)")
        elif job.status == "running":
            lines.append(f"{job.line()}: still running")
        else:
            lines.append(_manual(job, f"{job.job_type} via {job.provider} has no resume step"))
    for item_id in carousels:
        try:
            lines += _carousel(conn, settings, item_id)
        except (RegistryError, OSError, ValueError) as error:
            lines.append(f"{item_id}: needs manual action: carousel ({error})")
    retry, capped = retry_candidates(conn, item_id=None, max_attempts=config.max_attempts)
    for job in retry:
        if job.job_type == "upload":
            lines.append(_requeue(conn, settings, job, command))
        else:
            lines.append(_manual(job, f"failed: uv run ca jobs retry "
                                      f"{job.item_id or '--all-failed'} (a dry run, then the "
                                      "user's \"ok\")"))
    lines += [_manual(job, f"failed {job.attempts or 1} time(s), max attempts reached")
              for job in capped]
    return lines + _videos(settings)
