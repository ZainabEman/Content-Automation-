"""Job records: one dated output folder per job with an atomically written details.json."""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, PrivateAttr

from content_automation.core.files import CamelModel, atomic_write_text

JobStatus = Literal[
    "queued", "processing", "awaiting_agent", "completed", "failed", "cancelled"
]
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})
DETAILS_FILE = "details.json"
_ACTIVE = {"processing", "awaiting_agent"}

# "code": the app calls the provider API. "agent": Codex uses a Codex plugin, then records
# the result with `ca job complete` / `ca job fail`.
AdapterMode = Literal["code", "agent"]
StepStatus = Literal["processing", "awaiting_agent", "completed", "failed"]


class JobStateError(RuntimeError):
    """Raised when a job is moved to a state it cannot reach."""


class JobParams(CamelModel):
    aspect_ratio: str
    image_size: str
    count: int


class JobStep(CamelModel):
    """One provider step of a multi-step job (voice, one scene clip, ...)."""

    step_id: str
    capability: str
    provider: str
    mode: AdapterMode
    status: StepStatus = "processing"
    file: str | None = None  # output file, relative to the job folder
    provider_job_id: str | None = None
    credits_used: float | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: _utc_now())
    updated_at: datetime = Field(default_factory=lambda: _utc_now())


ReviewResult = Literal["pass", "fail"]
# person: is it the identity person? set: does it match the first image of its set (fonts,
# colours, layout family)?
ReviewCheck = Literal["person", "set"]


class JobReference(CamelModel):
    """One reference image sent to the model, in the order attached (image 1 first)."""

    role: str  # identity, product, style or series (slide 1 of the same carousel)
    asset_id: str
    source: str
    people: bool | None = None  # style tags from the reference library
    logo: bool | None = None


class ImageReview(CamelModel):
    """A check of one output image: the person check or the set check."""

    image: str  # e.g. image-1.png
    check: ReviewCheck = "person"
    result: ReviewResult
    note: str | None = None  # what differs (hair, build, facial hair, age) or who accepted it
    reviewed_at: datetime = Field(default_factory=lambda: _utc_now())


class Job(CamelModel):
    """The details.json record described in docs/prd/module-1.md."""

    job_id: str
    workflow_id: str
    workflow_version: str
    requested_by: str
    request: str
    prompt: str
    provider: str
    model: str
    params: JobParams
    identity_asset_ids: list[str] = Field(default_factory=list)
    product_asset_ids: list[str] = Field(default_factory=list)
    brand_asset_ids: list[str] = Field(default_factory=list)
    style_asset_ids: list[str] = Field(default_factory=list)
    inputs: dict[str, str | bool] = Field(default_factory=dict)
    status: JobStatus = "queued"
    outputs: list[str] = Field(default_factory=list)
    output_asset_ids: list[str] = Field(default_factory=list)  # image outputs, same order
    error: str | None = None
    provider_request_ids: list[str] = Field(default_factory=list)
    est_cost_usd: float | None = None
    actual_cost_usd: float | None = None  # as reported by the provider
    steps: list[JobStep] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # plain-language remarks, e.g. about text
    references: list[JobReference] = Field(default_factory=list)  # in the order attached
    reviews: list[ImageReview] = Field(default_factory=list)  # person checks; newest last
    created_at: datetime
    updated_at: datetime

    _folder: Path | None = PrivateAttr(default=None)

    @property
    def folder(self) -> Path:
        if self._folder is None:
            raise JobStateError("This job has no output folder.")
        return self._folder

    @classmethod
    def load(cls, details_path: Path) -> "Job":
        job = cls.model_validate_json(details_path.read_text(encoding="utf-8"))
        job._folder = details_path.parent
        return job

    def save(self) -> None:
        """Write details.json atomically so readers never see a half-written file."""
        self.updated_at = _utc_now()
        text = self.model_dump_json(by_alias=True, indent=2) + "\n"
        atomic_write_text(self.folder / DETAILS_FILE, text)

    def start(self) -> None:
        self._transition("processing", allowed_from={"queued"})
        self.save()

    def complete(self, output_files: list[str]) -> None:
        """Mark completed only when every listed output file exists and is non-empty
        and every step is completed."""
        if not output_files:
            raise JobStateError("A job cannot be completed without output files.")
        missing = [name for name in output_files if not self._has_file(name)]
        if missing:
            raise JobStateError(f"Output files are missing or empty: {', '.join(missing)}.")
        unfinished = [step.step_id for step in self.steps if step.status != "completed"]
        if unfinished:
            raise JobStateError(f"Steps are not completed: {', '.join(unfinished)}.")
        self._transition("completed", allowed_from={"queued", "processing"})
        self.outputs = list(output_files)
        self.error = None
        self.save()

    def fail(self, error: str) -> None:
        self._transition("failed", allowed_from={"queued", *_ACTIVE})
        self.outputs = []
        self.error = error or "Unknown error."
        self._stop_steps("Stopped because the job failed.")
        self.save()

    def cancel(self, reason: str = "Cancelled by user.") -> None:
        self._transition("cancelled", allowed_from={"queued", *_ACTIVE})
        self.outputs = []
        self.error = reason
        self._stop_steps("Stopped because the job was cancelled.")
        self.save()

    def step(self, step_id: str) -> JobStep:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        known = ", ".join(step.step_id for step in self.steps) or "none"
        raise JobStateError(f"This job has no step '{step_id}' (steps: {known}).")

    def add_step(self, step: JobStep) -> None:
        """Record a step; an awaiting_agent step pauses the job until the agent reports."""
        if self.status not in _ACTIVE:
            raise JobStateError(f"Cannot add a step to a {self.status} job.")
        if any(existing.step_id == step.step_id for existing in self.steps):
            raise JobStateError(f"Step '{step.step_id}' already exists.")
        if step.status == "completed" and not (step.file and self._has_file(step.file)):
            raise JobStateError(f"Step '{step.step_id}' has no output file.")
        self.steps.append(step)
        if step.status == "awaiting_agent":
            self.status = "awaiting_agent"
        self.save()

    def complete_step(
        self,
        step_id: str,
        file: str,
        *,
        provider_job_id: str | None = None,
        credits_used: float | None = None,
    ) -> None:
        """Record an agent step's output; the job resumes once no step is waiting."""
        step = self.waiting_step(step_id)
        if not self._has_file(file):
            raise JobStateError(f"Output file is missing or empty: {file}.")
        step.status = "completed"
        step.file = file
        step.provider_job_id = provider_job_id
        step.credits_used = credits_used
        step.error = None
        step.updated_at = _utc_now()
        if not self.waiting_steps():
            self.status = "processing"
        self.save()

    def fail_step(self, step_id: str, error: str) -> None:
        """A failed step fails the whole job; it is never marked completed."""
        step = self.waiting_step(step_id)
        step.status = "failed"
        step.error = error or "Unknown error."
        step.updated_at = _utc_now()
        self.fail(f"Step {step_id} failed: {step.error}")

    def expire_steps(self, timeout_min: int, now: datetime | None = None) -> list[str]:
        """Fail agent steps waiting longer than timeout_min; return their IDs."""
        if self.status not in _ACTIVE:
            return []
        current = now or _utc_now()
        expired = [
            step
            for step in self.waiting_steps()
            if (current - step.created_at).total_seconds() > timeout_min * 60
        ]
        if not expired:
            return []
        for step in expired:
            step.status = "failed"
            step.error = f"Timed out after {timeout_min} min waiting for the agent."
            step.updated_at = current
        ids = [step.step_id for step in expired]
        self.fail(
            f"Agent step timed out ({', '.join(ids)}) after {timeout_min} min "
            "(AGENT_STEP_TIMEOUT_MIN)."
        )
        return ids

    def review(self, image: str, check: ReviewCheck = "person") -> ImageReview | None:
        """The newest check of one kind for one output image, if any."""
        found = [r for r in self.reviews if r.image == image and r.check == check]
        return found[-1] if found else None

    def add_review(
        self,
        image: str,
        result: ReviewResult,
        note: str | None = None,
        check: ReviewCheck = "person",
    ) -> None:
        if self.status != "completed":
            raise JobStateError(f"Only a completed job can be reviewed; this one is {self.status}.")
        if image not in self.outputs:
            outputs = ", ".join(self.outputs) or "none"
            raise JobStateError(f"{image} is not an output of this job (outputs: {outputs}).")
        self.reviews.append(
            ImageReview(image=image, check=check, result=result, note=note or None)
        )
        self.save()

    def waiting_steps(self) -> list[JobStep]:
        return [step for step in self.steps if step.status == "awaiting_agent"]

    def waiting_step(self, step_id: str) -> JobStep:
        if self.status in TERMINAL_STATUSES:
            raise JobStateError(f"This job is already {self.status}.")
        step = self.step(step_id)
        if step.status != "awaiting_agent":
            raise JobStateError(f"Step '{step_id}' is {step.status}, not awaiting_agent.")
        return step

    def _stop_steps(self, reason: str) -> None:
        now = _utc_now()
        for step in self.steps:
            if step.status in _ACTIVE:
                step.status = "failed"
                step.error = step.error or reason
                step.updated_at = now

    def _has_file(self, name: str) -> bool:
        path = self.folder / name
        return path.is_file() and path.stat().st_size > 0

    def _transition(self, new_status: JobStatus, *, allowed_from: set[str]) -> None:
        if self.status not in allowed_from:
            raise JobStateError(f"Cannot move a {self.status} job to {new_status}.")
        self.status = new_status


def create_job(
    output_dir: Path,
    *,
    workflow_id: str,
    workflow_version: str,
    requested_by: str,
    request: str,
    prompt: str,
    provider: str,
    model: str,
    params: JobParams,
    identity_asset_ids: list[str] | None = None,
    product_asset_ids: list[str] | None = None,
    brand_asset_ids: list[str] | None = None,
    style_asset_ids: list[str] | None = None,
    inputs: dict[str, str | bool] | None = None,
    est_cost_usd: float | None = None,
    references: list[JobReference] | None = None,
    now: datetime | None = None,
) -> Job:
    """Create OUTPUT_DIR/YYYY-MM-DD/HHmm_<slug>/ and write a queued details.json."""
    local_now = (now or datetime.now()).astimezone()
    folder = _unique_folder(
        output_dir / local_now.strftime("%Y-%m-%d"),
        f"{local_now.strftime('%H%M')}_{slugify(request or prompt)}",
    )
    created = local_now.astimezone(UTC)
    job = Job(
        job_id=f"job_{uuid.uuid4().hex[:12]}",
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        requested_by=requested_by,
        request=request,
        prompt=prompt,
        provider=provider,
        model=model,
        params=params,
        identity_asset_ids=identity_asset_ids or [],
        product_asset_ids=product_asset_ids or [],
        brand_asset_ids=brand_asset_ids or [],
        style_asset_ids=style_asset_ids or [],
        inputs=inputs or {},
        est_cost_usd=est_cost_usd,
        references=references or [],
        created_at=created,
        updated_at=created,
    )
    job._folder = folder
    job.save()
    return job


def slugify(text: str, max_length: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_length].rstrip("-") or "job"


def _unique_folder(parent: Path, name: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while True:
        candidate = parent / (name if suffix == 1 else f"{name}-{suffix}")
        try:
            candidate.mkdir()
        except FileExistsError:
            suffix += 1
            continue
        return candidate


def _utc_now() -> datetime:
    return datetime.now(UTC)
