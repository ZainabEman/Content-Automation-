"""Image routing per job (PRD v5 R6; Roman via Higgsfield since 2026-10-20).

requires_roman is set at planning time (the calendar's Roman row, a founder variant named with
"as …", or a Roman combination such as "S-L/BG-1/P-2/H-3") and stored in package.json and the
registry. requires_roman → ROMAN_IMAGE_PROVIDER (default higgsfield_soul: Codex makes the image
with the Higgsfield plugin, Soul 2.0, from his saved character; content/roman_prompt.py builds
the prompt); everything else → OpenRouter. The global IMAGE_PROVIDER does not decide: the
variant's provider is used (workflows/direction_job.direction_settings), and IMAGE_PROVIDER=mock
only stays mock for offline tests.

The RunPod/ComfyUI LoRA route is disabled: its code stays (providers/comfyui.py, runpod.py,
content/roman.py, `ca lora`), but ROMAN_IMAGE_PROVIDER=comfyui is refused with a clear message.
No silent fallback: a Roman job whose Higgsfield attempts fail fails clearly (never another
provider, never a real photo). Credentials stay in .env / settings and never reach prompts,
package files, logs or tracker rows (tests/test_routing.py).
"""

from __future__ import annotations

from typing import Literal

from content_automation.content.directions import Direction
from content_automation.core.config import Settings

Route = Literal["higgsfield_soul", "comfyui", "openrouter", "template"]
ROMAN_ROUTE: Route = "higgsfield_soul"  # Roman's images (2026-10-20)
DEFAULT_ROUTE: Route = "openrouter"
DISABLED: frozenset[str] = frozenset({"comfyui"})  # the RunPod LoRA route, off by decision


class RoutingError(ValueError):
    """The job cannot run on its route (a disabled route, or a mismatch with the plan)."""


def image_route(requires_roman: bool, *, picture: bool = True,
                roman_provider: str = ROMAN_ROUTE) -> Route:
    """The provider of one image job: decided by requires_roman, never by IMAGE_PROVIDER."""
    if not picture:
        return "template"
    if not requires_roman:
        return DEFAULT_ROUTE
    return "comfyui" if roman_provider == "comfyui" else "higgsfield_soul"


def runpod_missing(settings: Settings) -> list[str]:
    """The RunPod settings the disabled LoRA route would need (names only, never values)."""
    missing: list[str] = []
    key = settings.runpod_api_key
    if key is None or not key.get_secret_value().strip():
        missing.append("RUNPOD_API_KEY")
    if not (settings.runpod_endpoint_id or "").strip():
        missing.append("RUNPOD_ENDPOINT_ID")
    return missing


def check_route(direction: Direction, settings: Settings, *,
                requires_roman: bool | None = None) -> Route:
    """The variant's route, checked: it matches requires_roman; Roman's route is enabled."""
    wanted = direction.roman if requires_roman is None else requires_roman
    if direction.roman != wanted:
        raise RoutingError(
            f"{direction.id} {'shows' if direction.roman else 'does not show'} Roman, but the "
            f"job was planned with requires_roman={str(wanted).lower()}: plan it again "
            "(the calendar's Roman row or \"as <founder variant>\"), never a silent swap")
    route = image_route(wanted, picture=direction.visual.subject != "none",
                        roman_provider=settings.roman_image_provider)
    if route in DISABLED and settings.image_provider != "mock":
        raise RoutingError(
            f"{direction.id}: ROMAN_IMAGE_PROVIDER={route} is the RunPod/ComfyUI LoRA route, "
            "which is disabled (Roman is made with Higgsfield Soul 2.0 since 2026-10-20). Set "
            "ROMAN_IMAGE_PROVIDER=higgsfield_soul; there is no fallback to another provider or "
            "a real photo.")
    return route


__all__ = ["DEFAULT_ROUTE", "DISABLED", "ROMAN_ROUTE", "Route", "RoutingError", "check_route",
           "image_route", "runpod_missing"]
