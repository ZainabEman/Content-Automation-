"""Shared image job runner: limit check, job record, generation, saved files.

Named workflows (person_lifestyle, person_product, social_creative) build an
ImageRequest and final prompt, then call run_image_job().
"""

import io
import json
from pathlib import Path

from PIL import Image

from content_automation.ai.image import (
    ImageRequest,
    ReferenceImage,
    comfyui_photo_prompt,
    estimate_cost_usd,
    generate_image,
    get_provider,
    model_for,
)
from content_automation.core.config import Settings
from content_automation.core.jobs import DETAILS_FILE, Job, JobParams, JobReference, create_job
from content_automation.core.limits import check_daily_limit
from content_automation.core.log import get_logger, mask_secrets, secret_values
from content_automation.core.retry import call_with_retry
from content_automation.references import asset_id_for
from content_automation.registry import runtime
from content_automation.registry.jobs import JobRecord, NotAuthorized, load_job_config
from content_automation.workflows.compose import compose_post, copy_from_overlay
from content_automation.workflows.logo import LogoOverlay, apply_logo
from content_automation.workflows.text_overlay import TextOverlay, apply_text

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
    text: TextOverlay | None = None,
    cold_start: bool = True,
) -> Job:
    """Run one image job and return its record (status completed or failed).

    cold_start=False: the job follows another one on a warm worker (a package build), so the
    estimate leaves out the per-request cost.
    text: rendered onto every image first (providers that draw no text), then the logo.
    logo: pasted onto every image; the image without it (and without the text) is kept in raw/.
    Raises DailyLimitError before any job or provider call when the limit is hit.
    Mock images are free and do not count toward the limit.

    Registry (§14 D-5, D-6): inside a `ca` command the image is a registry job of the current
    item (or of this run for a direct `ca image`). The same request made before is reused (no
    new call); a paid provider needs an open authorization with room, otherwise NotAuthorized or
    BudgetExceeded is raised before anything is made.
    """
    if settings.image_provider != "mock":
        check_daily_limit(
            settings.output_dir, limit=settings.image_daily_limit, requested=request.count
        )
    registered, reused = _registry_job(request, settings, workflow_id, inputs, cold_start)
    if reused is not None:
        return reused
    # Live fix: ComfyUI makes only a clean photo of the person; the app composes the post.
    composed = (request.person and settings.image_provider == "comfyui" and text is not None
                and not (inputs or {}).get("postFormat"))  # a post format draws its own zones
    object_ids = [ref.asset_id for ref in request.object_refs]
    job = create_job(
        settings.output_dir,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        requested_by=requested_by or settings.user_name,
        request=user_request or request.prompt,
        prompt=comfyui_photo_prompt(settings) if composed else request.prompt,
        provider=settings.image_provider,
        model=model_for(settings),
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
    scrims: list[str] = []  # where the text overlay added a scrim
    try:
        job.est_cost_usd = estimate_cost_usd(request, settings, cold_start=cold_start)
        job.start()
        # A safety net above the adapter's own limits: each image may take a full
        # IMAGE_TIMEOUT_MS call per attempt, plus short waits between retries. A polled
        # provider (ComfyUI on RunPod) brings its own budget and cancels the job itself.
        budget = get_provider(settings.image_provider, settings).capabilities.timeout_s
        if budget is not None:
            per_image_s = budget + 30
        else:
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
        job.provider_metrics = result.metrics
        for index, image in enumerate(result.images, start=1):
            extension = _EXTENSIONS.get(image.mime_type, "png")
            if composed and text is not None:  # raw photo kept; the post is designed here
                raw = job.folder / RAW_DIR / f"image-{index}.{extension}"
                raw.parent.mkdir(exist_ok=True)
                raw.write_bytes(image.data)
                written.append(raw)
                card = json.loads(str((inputs or {}).get("card") or "{}"))
                with Image.open(io.BytesIO(image.data)) as source:
                    made = compose_post(source.convert("RGB"), settings, request.aspect_ratio,
                                        copy_from_overlay(text, card), logo,
                                        platform=card.get("platform"))
                path = job.folder / f"image-{index}.png"
                made.image.save(path, format="PNG", optimize=True)
                job.notes += made.notes
                written.append(path)
                continue
            if logo is None and text is None:
                path = job.folder / f"image-{index}.{extension}"
                path.write_bytes(image.data)
            else:
                raw = job.folder / RAW_DIR / f"image-{index}.{extension}"
                raw.parent.mkdir(exist_ok=True)
                raw.write_bytes(image.data)
                written.append(raw)
                path = job.folder / f"image-{index}.png"
                final = image.data
                if text is not None:  # order: base image, text overlay, logo
                    final, notes = apply_text(final, text)
                    scrims += [f"{path.name}: {note}" for note in notes]
                if logo is not None:
                    final, version = apply_logo(final, logo)
                    versions.append(f"{path.name}: {version}")
                path.write_bytes(final)
            written.append(path)
        finals = [path for path in written if path.parent == job.folder]
        if text is not None and not composed:
            job.notes.append(
                f"Text: {text.describe()}; scrims: {'; '.join(scrims) or 'none needed'}."
            )
        if logo is not None and not composed:
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
        if registered is not None:
            runtime.fail(registered.id, "interrupted (Ctrl+C)")
        raise
    except Exception as error:
        _remove(written)
        message = mask_secrets(f"{type(error).__name__}: {error}", secret_values(settings))
        job.actual_cost_usd = getattr(error, "cost_usd", None)
        job.fail(message)
        logger.error("Job %s failed: %s", job.job_id, message)
    if registered is not None:
        if job.status == "completed":
            runtime.succeed(registered.id, actual=job.actual_cost_usd,
                            result_path=job.folder.as_posix())
        else:
            runtime.fail(registered.id, job.error or "failed", actual=job.actual_cost_usd)
    return job


def _job_inputs(
    request: ImageRequest, settings: Settings, workflow_id: str,
    inputs: dict[str, str | bool] | None,
) -> dict[str, object]:
    """What makes two image jobs the same (the idempotency key's inputs)."""
    return {
        "workflow": workflow_id, "prompt": request.prompt, "model": model_for(settings),
        "aspect": request.aspect_ratio, "size": request.image_size, "count": request.count,
        "identity": [ref.asset_id for ref in request.identity_refs],
        "objects": [ref.asset_id for ref in request.object_refs],
        "style": [ref.asset_id for ref in request.style_refs],
        "inputs": dict(sorted((inputs or {}).items())),
    }


def _registry_job(
    request: ImageRequest, settings: Settings, workflow_id: str,
    inputs: dict[str, str | bool] | None, cold_start: bool,
) -> tuple[JobRecord | None, Job | None]:
    """(the started registry job, or a reused earlier Job); refuses a paid call without one."""
    scope = runtime.current()
    config = scope.config if scope is not None else load_job_config(settings.jobs_file)
    provider = settings.image_provider
    paid = config.paid(provider)
    if scope is not None:
        estimate = estimate_cost_usd(request, settings, cold_start=cold_start)
        job_inputs = _job_inputs(request, settings, workflow_id, inputs)
        unit = config.unit(provider) if paid else None
        opened = runtime.open_scoped_job("image", provider, job_inputs, estimate=estimate,
                                         unit=unit, direct=scope.item is None)
        if opened is not None and opened.reused:
            details = Path(opened.job.result_path or "") / DETAILS_FILE
            try:
                return None, Job.load(details)
            except (OSError, ValueError):
                runtime.reject(opened.job.id, f"the earlier result is missing ({details})")
                opened = runtime.open_scoped_job("image", provider, job_inputs,
                                                 estimate=estimate, unit=unit,
                                                 direct=scope.item is None)
        if opened is not None:
            started = runtime.start(opened.job.id)
            return started, None
    if paid:
        raise NotAuthorized(
            f"Image jobs via {provider} cost money and run only under an authorization: run the "
            "dry run, show the cost, and after the user's \"ok\" run with --authorize "
            "<dryrun_id>."
        )
    return None, None


def _remove(paths: list[Path]) -> None:
    for path in paths:
        path.unlink(missing_ok=True)
