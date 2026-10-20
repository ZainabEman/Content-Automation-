"""Image routing per job (PRD v5 R6; v6 R5: two image providers only).

requires_roman is set at planning time (the calendar's Roman row, a founder variant named with
"as …", or a Roman combination such as "S-L/BG-1/P-2/H-3") and stored in package.json and the
registry. requires_roman → Higgsfield Soul 2.0 (Codex makes the image with the Higgsfield plugin
from his saved character; content/roman_prompt.py builds the prompt); every other image →
OpenRouter (the configured model). The global IMAGE_PROVIDER does not decide: the variant's
provider is used (workflows/direction_job.direction_settings), and IMAGE_PROVIDER=mock only
stays mock for offline tests.

No silent fallback: a Roman job whose Higgsfield attempts fail fails clearly (never another
provider, never a real photo). Credentials stay in .env / settings and never reach prompts,
package files, logs or tracker rows (tests/test_routing.py).
"""

from __future__ import annotations

from typing import Literal

from content_automation.content.directions import Direction
from content_automation.core.config import Settings

Route = Literal["higgsfield_soul", "openrouter", "template"]
ROMAN_ROUTE: Route = "higgsfield_soul"
DEFAULT_ROUTE: Route = "openrouter"


class RoutingError(ValueError):
    """The job cannot run on its route (a mismatch with the plan)."""


def image_route(requires_roman: bool, *, picture: bool = True) -> Route:
    """The provider of one image job: decided by requires_roman, never by IMAGE_PROVIDER."""
    if not picture:
        return "template"
    return ROMAN_ROUTE if requires_roman else DEFAULT_ROUTE


def check_route(direction: Direction, settings: Settings, *,
                requires_roman: bool | None = None) -> Route:
    """The variant's route, checked: it matches requires_roman."""
    del settings  # the route never depends on IMAGE_PROVIDER
    wanted = direction.roman if requires_roman is None else requires_roman
    if direction.roman != wanted:
        raise RoutingError(
            f"{direction.id} {'shows' if direction.roman else 'does not show'} Roman, but the "
            f"job was planned with requires_roman={str(wanted).lower()}: plan it again "
            "(the calendar's Roman row or \"as <founder variant>\"), never a silent swap")
    return image_route(wanted, picture=direction.visual.subject != "none")


__all__ = ["DEFAULT_ROUTE", "ROMAN_ROUTE", "Route", "RoutingError", "check_route",
           "image_route"]
