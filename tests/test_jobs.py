import json
from datetime import datetime
from pathlib import Path

import pytest

from content_automation.core.jobs import Job, JobParams, JobStateError, create_job, slugify

NOW = datetime(2026, 9, 30, 14, 5).astimezone()


def _job(output_dir: Path, request: str = "Sara at a café") -> Job:
    return create_job(
        output_dir,
        workflow_id="direct",
        workflow_version="1",
        requested_by="Tester",
        request=request,
        prompt="A woman at a café",
        provider="mock",
        model="mock",
        params=JobParams(aspect_ratio="4:5", image_size="1K", count=1),
        identity_asset_ids=["abc123def456"],
        now=NOW,
    )


def test_create_job_writes_dated_folder_and_camel_case_details(tmp_path: Path) -> None:
    job = _job(tmp_path)

    assert job.folder == tmp_path / "2026-09-30" / "1405_sara-at-a-caf"
    data = json.loads((job.folder / "details.json").read_text(encoding="utf-8"))
    assert data["status"] == "queued"
    for key in (
        "jobId", "workflowId", "workflowVersion", "requestedBy", "request", "prompt",
        "provider", "model", "params", "identityAssetIds", "productAssetIds",
        "brandAssetIds", "outputs", "error", "providerRequestIds", "estCostUsd",
        "createdAt", "updatedAt",
    ):
        assert key in data
    assert data["params"] == {"aspectRatio": "4:5", "imageSize": "1K", "count": 1}
    assert not list(job.folder.glob("*.tmp"))


def test_existing_folder_gets_unique_suffix(tmp_path: Path) -> None:
    first = _job(tmp_path)
    second = _job(tmp_path)

    assert second.folder.name == f"{first.folder.name}-2"


def test_complete_refuses_missing_outputs(tmp_path: Path) -> None:
    job = _job(tmp_path)
    job.start()

    with pytest.raises(JobStateError, match="image-1.png"):
        job.complete(["image-1.png"])
    with pytest.raises(JobStateError):
        job.complete([])
    assert Job.load(job.folder / "details.json").status == "processing"


def test_complete_records_outputs(tmp_path: Path) -> None:
    job = _job(tmp_path)
    job.start()
    (job.folder / "image-1.png").write_bytes(b"png")

    job.complete(["image-1.png"])

    saved = Job.load(job.folder / "details.json")
    assert saved.status == "completed"
    assert saved.outputs == ["image-1.png"]
    with pytest.raises(JobStateError):
        saved.fail("too late")


def test_fail_records_error(tmp_path: Path) -> None:
    job = _job(tmp_path)

    job.fail("Provider exploded")

    saved = Job.load(job.folder / "details.json")
    assert saved.status == "failed"
    assert saved.error == "Provider exploded"
    assert saved.outputs == []


def test_slugify_falls_back() -> None:
    assert slugify("!!!") == "job"
    assert len(slugify("word " * 50)) <= 40
