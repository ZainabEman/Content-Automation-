"""Dry run: show what would be sent and what it would cost, without any job or call."""

import math
from datetime import date

from content_automation.ai.image import (
    ImageRequest,
    ReferenceImage,
    estimate_cost_usd,
    get_provider,
    validate_request,
)
from content_automation.core.config import Settings
from content_automation.core.limits import images_generated_on


def _refs_line(label: str, refs: list[ReferenceImage]) -> str:
    names = ", ".join(ref.source or ref.asset_id for ref in refs) or "-"
    return f"  {label} ({len(refs)}): {names}"


def dry_run_lines(
    request: ImageRequest,
    settings: Settings,
    *,
    workflow: str,
    product_refs: list[ReferenceImage] | None = None,
    brand_refs: list[ReferenceImage] | None = None,
) -> list[str]:
    """Validate the request against the provider's limits and describe it.

    Loads only the adapter's capabilities: no API key, job, file or provider call.
    """
    capabilities = get_provider(settings.image_provider).capabilities
    validate_request(request, capabilities)
    calls = math.ceil(request.count / capabilities.max_images_per_call)
    per_image = capabilities.est_cost_usd_per_image.get(request.image_size, 0.0)
    total = estimate_cost_usd(request, settings)
    lines = [
        "DRY RUN: no job created, no provider call, not counted toward the daily limit.",
        f"Workflow: {workflow}",
        f"Provider: {settings.image_provider}, model {settings.image_model}",
        f"Output: {request.count} image(s), {request.aspect_ratio}, {request.image_size}",
        f"Provider calls: {calls}",
        f"Estimated cost: ${total:.3f} ({request.count} x ${per_image:.3f})",
    ]
    if settings.image_provider != "mock":
        used = images_generated_on(settings.output_dir, date.today())
        lines.append(
            f"Daily limit: {used} of {settings.image_daily_limit} used today; "
            f"this request would add {request.count}."
        )
    lines += [
        "References:",
        _refs_line("identity", request.identity_refs),
        _refs_line("product", product_refs or []),
        _refs_line("brand", brand_refs or []),
        _refs_line("style", request.style_refs),
        "Final prompt:",
        request.prompt,
    ]
    return lines
