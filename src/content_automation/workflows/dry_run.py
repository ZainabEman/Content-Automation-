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
from content_automation.workflows.logo import LogoOverlay


def _yes_no(value: bool | None) -> str:
    return "untagged" if value is None else ("yes" if value else "no")


def _tags(ref: ReferenceImage) -> str:
    if not ref.source.startswith("creative/"):
        return " [earlier output: slide 1 of this carousel]"
    return f" [people {_yes_no(ref.people)}, logo {_yes_no(ref.logo)}]"


def _refs_line(label: str, refs: list[ReferenceImage], *, tags: bool = False) -> str:
    names = ", ".join((ref.source or ref.asset_id) + (_tags(ref) if tags else "") for ref in refs)
    return f"  {label} ({len(refs)}): {names or '-'}"


def dry_run_lines(
    request: ImageRequest,
    settings: Settings,
    *,
    workflow: str,
    product_refs: list[ReferenceImage] | None = None,
    logo: LogoOverlay | None = None,
) -> list[str]:
    """Validate the request against the provider's limits and describe it.

    Loads only the adapter's capabilities: no API key, job, file or provider call.
    """
    capabilities = get_provider(settings.image_provider, settings).capabilities
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
        "References (attached in this order):",
        _refs_line("identity", request.identity_refs),
        _refs_line("product", product_refs or []),
        _refs_line("style", request.style_refs, tags=True),
        f"Logo: {logo.describe() if logo else 'none'}",
        "Final prompt:",
        request.prompt,
    ]
    return lines
