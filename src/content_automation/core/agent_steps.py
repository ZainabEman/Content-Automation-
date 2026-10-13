"""Agent steps: provider work that Codex does with a Codex plugin while the job waits.

An agent adapter calls nothing. It writes requests/<stepId>.json (what to make and which
plugin to use) and returns an awaiting_agent step. Codex finds the plugin's tool at run time,
calls it, saves the result, then records it with `ca job complete` (or `ca job fail`).
"""

import shutil
from datetime import datetime
from pathlib import Path

from pydantic import Field

from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.core.jobs import Job, JobStep

REQUESTS_DIR = "requests"
# Where `ca job complete` copies a step's file, by capability (default: the job folder).
OUTPUT_DIRS = {"video": "clips", "avatar": "clips"}


class AgentRequest(CamelModel):
    """The requests/<stepId>.json file Codex reads before using the plugin."""

    step_id: str
    capability: str
    provider: str
    model: str
    plugin: str  # the Codex plugin to use; its tools are found at run time, never hardcoded
    prompt: str
    duration_sec: float | None = None
    aspect_ratio: str | None = None
    start_image_path: str | None = None
    start_image_asset_id: str | None = None
    identity_images: list[str] = Field(default_factory=list)  # the only person allowed
    person_rule: str = ""
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)
    instructions: list[str] = Field(default_factory=list)  # numbered steps for Codex
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    job_id: int | None = None  # the registry job: `ca jobs check <jobId>` before the plugin call


def request_path(job_dir: Path, step_id: str) -> Path:
    return job_dir / REQUESTS_DIR / f"{step_id}.json"


def load_request(job_dir: Path, step_id: str) -> AgentRequest:
    path = request_path(job_dir, step_id)
    return AgentRequest.model_validate_json(path.read_text(encoding="utf-8"))


def save_request(job_dir: Path, request: AgentRequest) -> None:
    atomic_write_text(request_path(job_dir, request.step_id),
                      request.model_dump_json(by_alias=True, indent=2) + "\n")


def create_agent_step(job_dir: Path, request: AgentRequest) -> JobStep:
    """Write the request file and return the matching awaiting_agent step."""
    path = request_path(job_dir, request.step_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, request.model_dump_json(by_alias=True, indent=2) + "\n")
    return JobStep(
        step_id=request.step_id,
        capability=request.capability,
        provider=request.provider,
        mode="agent",
        status="awaiting_agent",
    )


def step_problem(step: JobStep, job_dir: Path) -> str | None:
    """Check what an adapter returned: a completed step has its file, an agent step
    has its request file. Returns the problem, or None."""
    if step.status == "completed" and not (step.file and _non_empty(job_dir / step.file)):
        return f"Step {step.step_id} is completed but its output file is missing or empty."
    if step.status == "awaiting_agent" and not request_path(job_dir, step.step_id).is_file():
        return f"Step {step.step_id} awaits the agent but has no request file."
    return None


def _non_empty(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def record_agent_output(
    job: Job,
    step_id: str,
    source: Path,
    *,
    provider_job_id: str | None = None,
    credits_used: float | None = None,
) -> str:
    """Copy the agent's file into the job folder and complete the step; return its name."""
    step = job.waiting_step(step_id)  # check the state before copying anything
    if not _non_empty(source):
        raise FileNotFoundError(f"File not found or empty: {source}.")
    folder = OUTPUT_DIRS.get(step.capability)
    name = f"{step_id}{source.suffix.lower()}"
    relative = f"{folder}/{name}" if folder else name
    target = job.folder / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    job.complete_step(
        step_id, relative, provider_job_id=provider_job_id, credits_used=credits_used
    )
    return relative
