"""Shared image job runner: limit check, job record, generation, saved files.

Named workflows (person_lifestyle, person_product, social_creative) build an
ImageRequest and final prompt, then call run_image_job().
"""

from pathlib import Path

from content_automation.ai.image import (
    ImageRequest,
    ReferenceImage,
    estimate_cost_usd,
    generate_image,
)
from content_automation.core.config import Settings
from content_automation.core.jobs import Job, JobParams, JobReference, create_job
from content_automation.core.limits import check_daily_limit
from content_automation.core.log import get_logger, mask_secrets, secret_values
from content_automation.core.retry import call_with_retry
from content_automation.references import asset_id_for
from content_automation.workflows.logo import LogoOverlay, apply_logo

_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
RAW_DIR = "raw"  # the model's image before the logo is pasted (slide 1 for later slides)


def raw_image(folder: Path, name: str) -> Path | None:
    """The logo-free original of an output image, if the logo was pasted onto it."""
    path = folder / RAW_DIR / name
    return path if path.is_file() else None


def job_references(
    request: ImageRequest, series: list[ReferenceImage] | None = None
) -> list[JobReference]:
    """Every reference image in the order the adapter attaches it (image 1 first)."""
    series_ids = {ref.asset_id for ref in series or []}
    groups = (
        ("identity", request.identity_refs),
        ("product", request.object_refs),
        ("style", request.style_refs),
    )
    return [
        JobReference(
            role="series" if role == "style" and ref.asset_id in series_ids else role,
            asset_id=ref.asset_id,
            source=ref.source,
            people=ref.people,
            logo=ref.logo,
        )
        for role, refs in groups
        for ref in refs
    ]

logger = get_logger("workflows.image_job")


def run_image_job(
    request: ImageRequest,
    settings: Settings,
    *,
    workflow_id: str = "direct",
    workflow_version: str = "1",
    user_request: str | None = None,
    requested_by: str | None = None,
    product_asset_ids: list[str] | None = None,
    brand_asset_ids: list[str] | None = None,
    inputs: dict[str, str | bool] | None = None,
    logo: LogoOverlay | None = None,
    references: list[JobReference] | None = None,
) -> Job:
    """Run one image job and return its record (status completed or failed).

    logo: pasted onto every image; the image without it is kept in raw/.
    Raises DailyLimitError before any job or provider call when the limit is hit.
    Mock images are free and do not count toward the limit.
    """
    if settings.image_provider != "mock":
        check_daily_limit(
            settings.output_dir, limit=settings.image_daily_limit, requested=request.count
        )
    object_ids = [ref.asset_id for ref in request.object_refs]
    job = create_job(
        settings.output_dir,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        requested_by=requested_by or settings.user_name,
        request=user_request or request.prompt,
        prompt=request.prompt,
        provider=settings.image_provider,
        model=settings.image_model,
        params=JobParams(
            aspect_ratio=request.aspect_ratio,
            image_size=request.image_size,
            count=request.count,
        ),
        identity_asset_ids=[ref.asset_id for ref in request.identity_refs],
        product_asset_ids=product_asset_ids if product_asset_ids is not None else object_ids,
        brand_asset_ids=brand_asset_ids or [],
        style_asset_ids=[ref.asset_id for ref in request.style_refs],
        inputs=inputs,
        references=references if references is not None else job_references(request),
    )
    logger.info("Job %s created in %s", job.job_id, job.folder)

    written: list[Path] = []
    versions: list[str] = []  # which logo version each image got
    try:
        job.est_cost_usd = estimate_cost_usd(request, settings)
        job.start()
        # A safety net above the adapter's own limits: each image may take a full
        # IMAGE_TIMEOUT_MS call per attempt, plus short waits between retries.
        per_image_s = (settings.image_timeout_ms / 1000 + 5) * (settings.image_max_retries + 1)
        result = call_with_retry(
            lambda: generate_image(request, settings=settings),
            timeout_s=(per_image_s + 30) * request.count,
            max_retries=settings.image_max_retries,
            on_retry=lambda attempt, error, delay: logger.warning(
                "Retry %d after error: %s (waiting %.0fs)", attempt, error, delay
            ),
        )
        job.provider_request_ids = result.provider_request_ids
        job.model = result.model
        job.actual_cost_usd = result.cost_usd
        for index, image in enumerate(result.images, start=1):
            extension = _EXTENSIONS.get(image.mime_type, "png")
            if logo is None:
                path = job.folder / f"image-{index}.{extension}"
                path.write_bytes(image.data)
            else:
                raw = job.folder / RAW_DIR / f"image-{index}.{extension}"
                raw.parent.mkdir(exist_ok=True)
                raw.write_bytes(image.data)
                written.append(raw)
                path = job.folder / f"image-{index}.png"
                final, version = apply_logo(image.data, logo)
                path.write_bytes(final)
                versions.append(f"{path.name}: {version}")
            written.append(path)
        finals = [path for path in written if path.parent == job.folder]
        if logo is not None:
            job.notes.append(
                f"Logo: {logo.describe()}; used: {', '.join(versions)}; the images without it "
                f"are in {RAW_DIR}/."
            )
        # Same ID scheme as reference photos, so a video plan can use it as startImageAssetId.
        job.output_asset_ids = [asset_id_for(path) for path in finals]
        job.complete([path.name for path in finals])
    except KeyboardInterrupt:
        _remove(written)
        job.cancel()
        raise
    except Exception as error:
        _remove(written)
        message = mask_secrets(f"{type(error).__name__}: {error}", secret_values(settings))
        job.actual_cost_usd = getattr(error, "cost_usd", None)
        job.fail(message)
        logger.error("Job %s failed: %s", job.job_id, message)
    return job


def _remove(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
