"""Image routing per job (PRD v5 R6): requires_roman → RunPod LoRA endpoint, else OpenRouter.

requires_roman is set at planning time (the calendar's Roman row or a founder variant named with
"as …") and stored in package.json and the registry; the layout variant follows it (founder
variants show Roman by his LoRA, every other variant shows no person). The global IMAGE_PROVIDER
does not decide: the variant's provider is used (workflows/direction_job.direction_settings,
reused from 7d20445), and IMAGE_PROVIDER=mock only stays mock for offline tests.

No silent fallback: a Roman job whose RunPod endpoint is not configured fails in the dry run,
before any cost is approved, with the missing setting named (never another provider, never a
real photo). Credentials are read from .env / settings only and never written to prompts,
package files, logs or tracker rows (tests/test_routing.py scans them).
"""

from __future__ import annotations

from typing import Literal

from content_automation.content.directions import Direction
from content_automation.core.config import Settings

Route = Literal["comfyui", "openrouter", "template"]
ROMAN_ROUTE: Route = "comfyui"  # Roman's LoRA (Z-Image Turbo + r0man_bg) on RunPod Serverless
DEFAULT_ROUTE: Route = "openrouter"


class RoutingError(ValueError):
    """The job cannot run on its route (a Roman job without RunPod, or a mismatch)."""


def image_route(requires_roman: bool, *, picture: bool = True) -> Route:
    """The provider of one image job: decided by requires_roman, never by IMAGE_PROVIDER."""
    if not picture:
        return "template"
    return ROMAN_ROUTE if requires_roman else DEFAULT_ROUTE


def runpod_missing(settings: Settings) -> list[str]:
    """The RunPod settings a Roman job needs that are not set (names only, never values)."""
    missing: list[str] = []
    key = settings.runpod_api_key
    if key is None or not key.get_secret_value().strip():
        missing.append("RUNPOD_API_KEY")
    if not (settings.runpod_endpoint_id or "").strip():
        missing.append("RUNPOD_ENDPOINT_ID")
    return missing


def check_route(direction: Direction, settings: Settings, *,
                requires_roman: bool | None = None) -> Route:
    """The variant's route, checked: it matches requires_roman, and a Roman job has RunPod."""
    wanted = direction.roman if requires_roman is None else requires_roman
    if direction.roman != wanted:
        raise RoutingError(
            f"{direction.id} {'shows' if direction.roman else 'does not show'} Roman, but the "
            f"job was planned with requires_roman={str(wanted).lower()}: plan it again "
            "(the calendar's Roman row or \"as <founder variant>\"), never a silent swap")
    route = image_route(wanted, picture=direction.visual.subject != "none")
    if route == ROMAN_ROUTE and settings.image_provider != "mock":
        missing = runpod_missing(settings)
        if missing:
            raise RoutingError(
                f"{direction.id} needs Roman's LoRA on the RunPod endpoint (ComfyUI), but "
                f"{', '.join(missing)} is not set in .env. Add it (never in chat); there is no "
                "fallback to another provider or a real photo.")
    return route


__all__ = ["DEFAULT_ROUTE", "ROMAN_ROUTE", "Route", "RoutingError", "check_route",
           "image_route", "runpod_missing"]
