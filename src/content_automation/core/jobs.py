"""Job records: one dated output folder per job with an atomically written details.json."""

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, PrivateAttr

from content_automation.core.files import CamelModel, atomic_write_text

JobStatus = Literal["queued", "processing", "completed", "failed", "cancelled"]
TERMINAL_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})
DETAILS_FILE = "details.json"


class JobStateError(RuntimeError):
    """Raised when a job is moved to a state it cannot reach."""


class JobParams(CamelModel):
    aspect_ratio: str
    image_size: str
    count: int


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
    error: str | None = None
    provider_request_ids: list[str] = Field(default_factory=list)
    est_cost_usd: float | None = None
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
        """Mark completed only when every listed output file exists and is non-empty."""
        if not output_files:
            raise JobStateError("A job cannot be completed without output files.")
        missing = [
            name
            for name in output_files
            if not (self.folder / name).is_file() or (self.folder / name).stat().st_size == 0
        ]
        if missing:
            raise JobStateError(f"Output files are missing or empty: {', '.join(missing)}.")
        self._transition("completed", allowed_from={"queued", "processing"})
        self.outputs = list(output_files)
        self.error = None
        self.save()

    def fail(self, error: str) -> None:
        self._transition("failed", allowed_from={"queued", "processing"})
        self.outputs = []
        self.error = error or "Unknown error."
        self.save()

    def cancel(self, reason: str = "Cancelled by user.") -> None:
        self._transition("cancelled", allowed_from={"queued", "processing"})
        self.outputs = []
        self.error = reason
        self.save()

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
