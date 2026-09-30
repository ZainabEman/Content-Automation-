"""Find the image behind a plan's startImageAssetId.

An ID is either an asset ID (first 12 characters of the file's SHA-256, the same scheme for
reference photos and M1 image outputs) or "<jobId>/<file>" for an M1 output, for example
"job_1a2b3c4d5e6f/image-2.png". Reference sets are searched first, then M1 outputs.
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from content_automation.core.config import Settings
from content_automation.core.jobs import DETAILS_FILE, Job
from content_automation.references import asset_id_for, list_sets

IMAGE_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp"})


class StartImageError(ValueError):
    """The start image cannot be found."""


@dataclass(frozen=True)
class StartImage:
    asset_id: str
    path: Path  # absolute, so the agent can open it from anywhere
    source: str  # for people: e.g. "identity/person_01/3.jpg" or "2026-09-30/1405_x/image-1.png"


def resolve_start_image(reference: str, settings: Settings) -> StartImage:
    reference = reference.strip()
    if "/" in reference:
        job_id, _, name = reference.rpartition("/")
        is_image = Path(name).suffix.lower() in IMAGE_SUFFIXES
        for job in _image_jobs(settings.output_dir):
            if is_image and job_id in (job.job_id, job.folder.name) and name in job.outputs:
                path = (job.folder / name).resolve()
                return StartImage(asset_id_for(path), path, _output_source(job, name))
        raise StartImageError(f"startImageAssetId '{reference}': no such M1 image output.")

    for ref_set in list_sets(None, settings.references_dir):
        for asset in ref_set.ok_assets:
            if asset.asset_id == reference:
                # The resized copy is upright (photo rotation applied) and small enough.
                path = (ref_set.folder / (asset.resized or asset.file)).resolve()
                return StartImage(reference, path, f"{ref_set.set_id}/{asset.file}")

    for job in _image_jobs(settings.output_dir):
        names = [name for name in job.outputs if Path(name).suffix.lower() in IMAGE_SUFFIXES]
        ids = job.output_asset_ids or [asset_id_for(job.folder / name) for name in names]
        for name, asset_id in zip(names, ids, strict=False):
            if asset_id == reference:
                path = (job.folder / name).resolve()
                return StartImage(reference, path, _output_source(job, name))
    raise StartImageError(
        f"startImageAssetId '{reference}' is not in the reference sets or M1 image outputs."
    )


def _image_jobs(output_dir: Path) -> list[Job]:
    """Completed jobs with files, newest first."""
    jobs: list[Job] = []
    for details in sorted(output_dir.glob(f"*/*/{DETAILS_FILE}"), reverse=True):
        try:
            job = Job.load(details)
        except (OSError, ValueError, ValidationError):
            continue
        if job.status == "completed" and job.outputs:
            jobs.append(job)
    return jobs


def _output_source(job: Job, name: str) -> str:
    return f"{job.folder.parent.name}/{job.folder.name}/{name}"
