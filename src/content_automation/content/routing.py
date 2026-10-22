"""Image routing per job (PRD v5 R6; v6 R5: two image providers only).

requires_roman is set at planning time (the calendar's Roman row, a founder variant named with
"as …", or a Roman combination such as "S-L/BG-1/P-2/H-3") and stored in package.json and the
registry. requires_roman → Higgsfield Soul 2.0 (Codex makes the image with the Higgsfield plugin
from his saved character; content/roman_prompt.py builds the prompt); every other image → Codex's
built-in image generation (codex_builtin, v5b), or OpenRouter only when IMAGE_PROVIDER=openrouter
opts in. For Roman IMAGE_PROVIDER does not decide (workflows/direction_job.direction_settings),
and IMAGE_PROVIDER=mock only stays mock for offline tests.

No silent fallback: a Roman job whose Higgsfield attempts fail fails clearly (never another
provider, never a real photo). Credentials stay in .env / settings and never reach prompts,
package files, logs or tracker rows (tests/test_routing.py).
"""

from __future__ import annotations

from typing import Literal

from content_automation.content.directions import Direction
from content_automation.core.config import Settings

Route = Literal["higgsfield_soul", "codex_builtin", "openrouter", "template"]
ROMAN_ROUTE: Route = "higgsfield_soul"
DEFAULT_ROUTE: Route = "codex_builtin"
OPT_IN_ROUTE: Route = "openrouter"  # IMAGE_PROVIDER=openrouter: OpenRouter for non-Roman images


class RoutingError(ValueError):
    """The job cannot run on its route (a mismatch with the plan)."""


def illustration_route(settings: Settings | None = None) -> Route:
    """A non-Roman picture: Codex's built-in image generation unless IMAGE_PROVIDER=openrouter."""
    opted = settings is not None and settings.image_provider == OPT_IN_ROUTE
    return OPT_IN_ROUTE if opted else DEFAULT_ROUTE


def image_route(requires_roman: bool, *, picture: bool = True,
                settings: Settings | None = None) -> Route:
    """The provider of one image job: Roman by requires_roman alone (never IMAGE_PROVIDER)."""
    if not picture:
        return "template"
    return ROMAN_ROUTE if requires_roman else illustration_route(settings)


def check_route(direction: Direction, settings: Settings, *,
                requires_roman: bool | None = None) -> Route:
    """The variant's route, checked: it matches requires_roman."""
    wanted = direction.roman if requires_roman is None else requires_roman
    if direction.roman != wanted:
        raise RoutingError(
            f"{direction.id} {'shows' if direction.roman else 'does not show'} Roman, but the "
            f"job was planned with requires_roman={str(wanted).lower()}: plan it again "
            "(the calendar's Roman row or \"as <founder variant>\"), never a silent swap")
    return image_route(wanted, picture=direction.visual.subject != "none", settings=settings)


__all__ = ["DEFAULT_ROUTE", "OPT_IN_ROUTE", "ROMAN_ROUTE", "Route", "RoutingError",
           "check_route", "illustration_route", "image_route"]
