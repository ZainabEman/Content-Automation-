"""Shared image job runner: limit check, job record, generation, saved files.

Named workflows (person_lifestyle, person_product, social_creative) build an
ImageRequest and final prompt, then call run_image_job().
"""

import io
import json
from pathlib import Path

from PIL import Image

from content_automation.ai.image import (
    NETWORK_BACKOFF_S,
    NETWORK_RETRIES,
    ImageAwaitingAgent,
    ImageCreditsError,
    ImageNetworkError,
    ImageRequest,
    ImageResult,
    ReferenceImage,
    estimate_cost_usd,
    generate_image,
    get_provider,
    model_for,
)
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.jobs import DETAILS_FILE, Job, JobParams, JobReference, create_job
from content_automation.core.limits import check_daily_limit
from content_automation.core.log import get_logger, mask_secrets, secret_values
from content_automation.core.parallel import batch_stopped, stop_batch
from content_automation.core.retry import call_with_retry
from content_automation.references import asset_id_for
from content_automation.registry import runtime
from content_automation.registry.jobs import JobRecord, NotAuthorized, load_job_config
from content_automation.workflows.direction_job import (
    MANIFEST_SUFFIX,
    DirectionDesign,
    DirectionJobError,
)
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
    design: DirectionDesign | None = None,
) -> Job:
    """Run one image job and return its record (status completed or failed).

    cold_start=False: the job follows another one on a warm worker (a package build), so the
    estimate leaves out the per-request cost.
    text: rendered onto every image first (providers that draw no text), then the logo.
    logo: pasted onto every image; the image without it (and without the text) is kept in raw/.
    design (Phase D): the app draws the whole direction on the picture (text, logo, footer),
    writes image-N.design.json and runs the design check; a check error fails the job.
    Raises DailyLimitError before any job or provider call when the limit is hit.
    Mock images are free and do not count toward the limit.

    Costs and attempts (2026-10-21): an image the provider made and charged counts even when
    its check fails (the reported amount plus its text checks, or the estimate); a network
    error after the provider's own retries is never an image attempt; HTTP 402 (no credits)
    stops the whole batch (core/parallel.stop_batch) and no other paid image starts.

    Registry (§14 D-5, D-6): inside a `ca` command the image is a registry job of the current
    item (or of this run for a direct `ca image`). The same request made before is reused (no
    new call); a paid provider needs an open authorization with room, otherwise NotAuthorized or
    BudgetExceeded is raised before anything is made.
    """
    if settings.image_provider not in ("mock", "template"):  # free, no picture made
        stopped = batch_stopped()
        if stopped is not None:
            raise ImageCreditsError(f"not started, the batch stopped: {stopped}")
        check_daily_limit(
            settings.output_dir, limit=settings.image_daily_limit, requested=request.count
        )
    _await_agent(request, settings)  # Higgsfield: no registry job before Codex delivers
    registered, reused = _registry_job(request, settings, workflow_id, inputs, cold_start)
    if reused is not None:
        return reused
    object_ids = [ref.asset_id for ref in request.object_refs]
    job = create_job(
        settings.output_dir,
        workflow_id=workflow_id,
        workflow_version=workflow_version,
        requested_by=requested_by or settings.user_name,
        request=user_request or request.prompt,
        prompt=request.prompt,
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
    result: ImageResult | None = None  # set once the provider made (and charged) the images
    network = False  # a network error after the adapter's retries: not an image attempt
    versions: list[str] = []  # which logo version each image got
    scrims: list[str] = []  # where the text overlay added a scrim
    try:
        job.est_cost_usd = estimate_cost_usd(request, settings, cold_start=cold_start)
        job.start()
        # A safety net above the adapter's own limits: each image may take a full
        # IMAGE_TIMEOUT_MS call per attempt, plus short waits between retries. A polled
        # provider brings its own budget and cancels the job itself.
        budget = get_provider(settings.image_provider, settings).capabilities.timeout_s
        if budget is not None:
            per_image_s = budget + 30
        else:
            # the adapter retries one call NETWORK_RETRIES times with backoff (OpenRouter)
            tries = max(settings.image_max_retries, NETWORK_RETRIES) + 1
            per_image_s = (settings.image_timeout_ms / 1000 + 5 + NETWORK_BACKOFF_S * 2) * tries
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
            if design is not None:  # the raw picture kept; the design is drawn and checked
                raw = job.folder / RAW_DIR / f"image-{index}.{extension}"
                raw.parent.mkdir(exist_ok=True)
                raw.write_bytes(image.data)
                written.append(raw)
                with Image.open(io.BytesIO(image.data)) as source:
                    picture = None if settings.image_provider == "template" else source.convert(
                        "RGB")
                    drawn, report = design.render(
                        picture, settings, manual_acceptances=result.manual_acceptances)
                path = job.folder / f"image-{index}.png"
                drawn.image.save(path, format="PNG", optimize=True)
                manifest = drawn.manifest() | {"copy": design.copy, "check": {
                    "errors": report.errors, "warnings": report.warnings,
                    **({"romanChecks": report.checks} if report.checks else {})}}
                atomic_write_text(path.with_suffix(MANIFEST_SUFFIX),
                                  json.dumps(manifest, indent=2, ensure_ascii=False, default=str))
                written.append(path)
                if report.checks:
                    job.notes.append("Roman checks: " + "; ".join(
                        f"{name} {value}" for name, value in report.checks.items()
                        if name != "spelling") + ".")
                    job.notes.append(report.checks.get("spelling", ""))
                if result.manual_acceptances:
                    job.notes.append("Operator-accepted checks: " + "; ".join(
                        f"{name}: {reason}" for name, reason in
                        sorted(result.manual_acceptances.items())) + ".")
                if report.errors:
                    raise DirectionJobError(f"{path.name} failed the design check: "
                                            + "; ".join(report.errors))
                job.notes.append(f"Design: {design.describe()}; check passed"
                                 + (f" ({'; '.join(report.warnings)})" if report.warnings
                                    else "") + "."
                                 + "".join(f" {note}." for note in design.notes))
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
        if text is not None:
            job.notes.append(
                f"Text: {text.describe()}; scrims: {'; '.join(scrims) or 'none needed'}."
            )
        if logo is not None:
            job.notes.append(
                f"Logo: {logo.describe()}; used: {', '.join(versions)}; the images without it "
                f"are in {RAW_DIR}/."
            )
        if design is not None and design.check_cost_usd and job.actual_cost_usd is not None:
            job.actual_cost_usd = round(job.actual_cost_usd + design.check_cost_usd, 6)
        # Same ID scheme as reference photos, so a video plan can use it as startImageAssetId.
        job.output_asset_ids = [asset_id_for(path) for path in finals]
        job.complete([path.name for path in finals])
    except KeyboardInterrupt:
        _remove(written)
        job.cancel()
        if registered is not None:
            runtime.fail(registered.id, "interrupted (Ctrl+C)")
        raise
    except ImageAwaitingAgent:  # no image yet for this attempt; Codex makes it
        _remove(written)
        job.cancel("Higgsfield: waiting for Codex.")
        if registered is not None:  # failed, never left running: the next build opens a redo
            # (rejecting a running job raised and left a stale record that blocked the build)
            runtime.fail(registered.id, "Higgsfield: waiting for Codex")
        raise
    except Exception as error:
        _remove(written)
        message = mask_secrets(f"{type(error).__name__}: {error}", secret_values(settings))
        job.actual_cost_usd = getattr(error, "cost_usd", None)
        if result is not None:  # made and charged, then its check failed: the attempt costs
            checks = design.check_cost_usd if design is not None else 0.0
            if result.cost_usd is not None:
                job.actual_cost_usd = round(result.cost_usd + checks, 6)
            elif job.est_cost_usd:
                job.actual_cost_usd = round(job.est_cost_usd + checks, 6)
                job.notes.append(f"Cost: the estimate ${job.actual_cost_usd:.3f} (the provider "
                                 "reported no amount).")
        network = isinstance(error, ImageNetworkError)
        if network:
            job.notes.append("A network error after the retries of the same call: not an "
                             "image attempt.")
        if isinstance(error, ImageCreditsError):
            stop_batch(message)
        job.fail(message)
        logger.error("Job %s failed: %s", job.job_id, message)
    if registered is not None:
        if job.status == "completed":
            runtime.succeed(registered.id, actual=job.actual_cost_usd,
                            result_path=job.folder.as_posix())
        else:
            reported = result.cost_usd if result is not None else job.actual_cost_usd
            runtime.fail(registered.id, job.error or "failed",
                         actual=job.actual_cost_usd if reported is not None else None,
                         billed=result is not None,
                         count_attempt=not network)
    return job


def _await_agent(request: ImageRequest, settings: Settings) -> None:
    """An agent-mode image provider (higgsfield_soul): Codex makes the image with its plugin.
    Until the image is delivered only its job file is written (no registry job, nothing spent)
    and ImageAwaitingAgent is raised; a paid one only after the user's "ok"."""
    provider = get_provider(settings.image_provider, settings)
    waiting = getattr(provider, "waiting", None)
    if getattr(provider, "mode", "code") != "agent" or waiting is None:
        return
    scope = runtime.current()
    config = scope.config if scope is not None else load_job_config(settings.jobs_file)
    name = settings.image_provider
    authorized = scope is not None and (bool(scope.authorizations) or runtime.authorized_max(
        scope.item, name, config.unit(name)) is not None)
    if config.paid(name) and not authorized:
        raise NotAuthorized(
            f"Image jobs via {name} cost credits and run only under an authorization: run the "
            "dry run, show the estimate, and after the user's \"ok\" run with --authorize "
            "<dryrun_id>.")
    job_file = waiting(request)
    if job_file is not None:
        raise ImageAwaitingAgent(f"waiting for Codex: {job_file}", Path(job_file))


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
        if opened is not None and opened.in_progress and opened.job.status == "running":
            # left running by an earlier build that stopped (one build at a time per item):
            # failed, so this build attaches to a fresh record of the same request
            runtime.fail(opened.job.id, "stale: left running by an earlier build; replaced")
            opened = runtime.open_scoped_job("image", provider, job_inputs, estimate=estimate,
                                             unit=unit, direct=scope.item is None)
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
