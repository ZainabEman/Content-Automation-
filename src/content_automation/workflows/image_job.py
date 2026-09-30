"""Shared image job runner: limit check, job record, generation, saved files.

Named workflows (person_lifestyle, person_product, social_creative) build an
ImageRequest and final prompt, then call run_image_job().
"""

from pathlib import Path

from content_automation.ai.image import ImageRequest, estimate_cost_usd, generate_image
from content_automation.core.config import Settings
from content_automation.core.jobs import Job, JobParams, create_job
from content_automation.core.limits import check_daily_limit
from content_automation.core.log import get_logger, mask_secrets, secret_values
from content_automation.core.retry import call_with_retry

_EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

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
) -> Job:
    """Run one image job and return its record (status completed or failed).

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
    )
    logger.info("Job %s created in %s", job.job_id, job.folder)

    written: list[Path] = []
    try:
        job.est_cost_usd = estimate_cost_usd(request, settings)
        job.start()
        result = call_with_retry(
            lambda: generate_image(request, settings=settings),
            # IMAGE_TIMEOUT_MS is per image; some providers make one call per image.
            timeout_s=settings.image_timeout_ms / 1000 * request.count,
            max_retries=settings.image_max_retries,
            on_retry=lambda attempt, error, delay: logger.warning(
                "Retry %d after error: %s (waiting %.0fs)", attempt, error, delay
            ),
        )
        job.provider_request_ids = result.provider_request_ids
        job.model = result.model
        for index, image in enumerate(result.images, start=1):
            path = job.folder / f"image-{index}.{_EXTENSIONS.get(image.mime_type, 'png')}"
            path.write_bytes(image.data)
            written.append(path)
        job.complete([path.name for path in written])
    except KeyboardInterrupt:
        _remove(written)
        job.cancel()
        raise
    except Exception as error:
        _remove(written)
        message = mask_secrets(f"{type(error).__name__}: {error}", secret_values(settings))
        job.fail(message)
        logger.error("Job %s failed: %s", job.job_id, message)
    return job


def _remove(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
