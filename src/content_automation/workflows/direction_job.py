"""Phase D step 8: a design direction as one image job of the existing build.

The direction fixes the provider (never swapped; IMAGE_PROVIDER=mock stays mock for local tests):
no picture = the free template, an illustration = OpenRouter (Nano Banana 2, CAROUSEL_IMAGE_MODEL),
Roman = his LoRA on comfyui in every founder direction (FD-1 is cut out by the app from the
LoRA image; a real photo is never the final image, and a failed LoRA job is never replaced by
one or by another provider). The picture prompt never carries the copy and ends with
"no text". After generation the app draws the whole design (workflows/design_render.py: text,
logo, footer, icons, cards), writes the render manifest beside the PNG and runs the free design
check (workflows/design_check.py); an error fails that image, never a silent pass.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from content_automation.ai.image import ASPECT_RATIOS, AspectRatio
from content_automation.content.directions import (
    SIDE_LAYOUTS,
    Direction,
    DirectionCatalog,
    DirectionError,
    Layout,
    load_directions,
)
from content_automation.content.roman import RomanError, roman_prompt
from content_automation.core.config import Settings
from content_automation.references import load_brand
from content_automation.references.services import load_services
from content_automation.workflows.cutout import CutoutError, cut_out
from content_automation.workflows.design_check import Report, check_manifest
from content_automation.workflows.design_render import (
    Assets,
    DesignRenderError,
    Rendered,
    design_fonts,
    logo_file,
    plain,
    render_layout,
)
from content_automation.workflows.roman_check import run_checks

MANIFEST_SUFFIX = ".design.json"  # beside image-N.png in the job folder


class DirectionJobError(ValueError):
    """The direction cannot be prepared or its design does not pass the check."""


def direction_layout(direction: Direction, *, platform: str | None, seed: str,
                     role: str | None = None, side: str | None = None) -> tuple[str, Layout]:
    """The layout the template, the brief check and the build all use (same seed, same one;
    a Higgsfield founder variant: the layout of Roman's side)."""
    return direction.layout_for(platform, seed=seed, role=role, side=side)


def has_picture(direction: Direction, layout: Layout, role: str | None = None) -> bool:
    if direction.visual.subject == "none":
        return False
    if role is not None:
        found = next((item for item in direction.slide_roles if item.role == role), None)
        if found is not None and not found.visual:
            return False
    return any(zone.kind == "visual" for zone in layout.zones.values())


def direction_settings(direction: Direction, picture: bool, settings: Settings) -> Settings:
    """The direction's own provider: never swapped (mock stays mock in local tests)."""
    if not picture or direction.provider == "template":
        return settings.model_copy(update={"image_provider": "template"})
    if settings.image_provider in ("mock", direction.provider):
        return settings
    update: dict[str, str] = {"image_provider": direction.provider}
    if direction.provider == "openrouter":  # Nano Banana 2 via OpenRouter
        update["image_model"] = settings.carousel_image_model
    return settings.model_copy(update=update)


def picture_aspect(direction: Direction, layout: Layout, catalog: DirectionCatalog) -> AspectRatio:
    """The supported aspect nearest to the picture's zone (it is cover-cropped into it)."""
    width, height = catalog.size(direction)
    zone = next((z for z in layout.zones.values() if z.kind == "visual"), None)
    if zone is None:
        return "4:5"
    ratio = ((zone.box[2] - zone.box[0]) * width) / max(1.0, (zone.box[3] - zone.box[1]) * height)

    def distance(aspect: str) -> float:
        left, _, right = aspect.partition(":")
        return abs(int(left) / int(right) - ratio)

    return min(ASPECT_RATIOS, key=distance)


def illustration_prompt(direction: Direction, catalog: DirectionCatalog, copy: dict[str, Any],
                        illustration: str | None) -> str:
    """An illustration direction's prompt: the writer's picture, never the copy, no text."""
    picture = (illustration or str(copy.get("illustration") or "")).strip()
    if not picture:
        raise DirectionJobError(f"{direction.id}: describe the picture in copy.illustration "
                                "(a place or objects, nothing written, no people)")
    blocked = [word for word in catalog.blocked_visual_words
               if re.search(rf"(?<![a-z]){re.escape(word.lower())}(?![a-z])", picture.lower())]
    if blocked:
        raise DirectionJobError(f"{direction.id} illustration: leave out {', '.join(blocked)} "
                                "(the image model draws no text, people or logos)")
    texts = [plain(str(value)) for name, value in copy.items()
             if name not in ("illustration", "icons", "service_icons") and isinstance(value, str)]
    words = picture.lower().split()
    for text in texts:
        lowered = text.lower()
        for start in range(max(0, len(words) - 3)):
            if " ".join(words[start:start + 4]) in lowered:
                raise DirectionJobError(f"{direction.id} illustration repeats the copy "
                                        f'("{" ".join(words[start:start + 4])}"): describe the '
                                        "picture, not the text")
    return direction.visual.prompt.format(illustration=picture)


@dataclass
class DirectionDesign:
    """What the app draws after generation; recorded in the job inputs as JSON."""

    direction: str
    layout: str
    copy: dict[str, Any]
    platform: str | None = None
    step: int = 0
    person_check: str | None = None
    notes: list[str] = field(default_factory=list)

    def describe(self) -> str:
        return (f"{self.direction} {self.layout}: drawn by the app (text, logo, footer, icons) "
                "on the generated picture; the image model draws no text; design check after "
                "rendering")

    def to_json(self) -> str:
        return json.dumps({"direction": self.direction, "layout": self.layout,
                           "platform": self.platform, "step": self.step},
                          ensure_ascii=False)

    def picture(self, generated: Image.Image | None, mock: bool = False) -> Image.Image | None:
        """The generated picture; a cut-out zone (FD-1) keys out the LoRA image's green
        backdrop. A failed cut-out fails the image (mock test images have no backdrop)."""
        if generated is None:
            return None
        direction = load_directions().get(self.direction)
        zone = next((z for z in direction.layouts[self.layout].zones.values()
                     if z.kind == "visual"), None)
        if zone is None or zone.visual_shape != "cutout" or mock:
            return generated
        try:
            return cut_out(generated)[0]
        except CutoutError as error:
            raise DirectionJobError(f"{self.direction}: the LoRA image cannot be cut out "
                                    f"({error}); make it again, never a real photo") from None

    def render(self, generated: Image.Image | None, settings: Settings) -> tuple[Rendered, Report]:
        """Draw the design on the picture, then check it (free)."""
        catalog = load_directions()
        direction = catalog.get(self.direction)
        brand = load_brand(settings.references_dir)
        assets = Assets(brand=brand, logo_path=logo_file(brand, settings.references_dir),
                        fonts=design_fonts(brand))
        try:
            rendered = render_layout(catalog, direction, self.layout, self.copy, assets,
                                     picture=self.picture(
                                         generated, settings.image_provider == "mock"),
                                     step=self.step)
        except DesignRenderError as error:
            raise DirectionJobError(str(error)) from None
        manifest = json.loads(json.dumps(rendered.manifest(), default=str))
        manifest["copy"] = self.copy
        report = check_manifest(manifest, catalog=catalog, brand=brand,
                                services=load_services(settings.services_file),
                                name=f"{self.direction} {self.layout}", image=rendered.image,
                                person_check=self.person_check)
        if direction.visual.subject == "roman_higgsfield":  # the strict checks (2026-10-20)
            side = "S-L" if self.layout == SIDE_LAYOUTS["S-L"] else "S-R"
            mock = settings.image_provider == "mock"
            roman, _ = run_checks(manifest, side, None if mock else generated)
            report.errors += roman.errors
            report.checks = roman.results
        return rendered, report


def lora_prompt(direction: Direction, layout: Layout, seed: str) -> str:
    try:
        return roman_prompt(direction, layout, load_directions().roman, seed=seed)
    except (RomanError, DirectionError) as error:
        raise DirectionJobError(str(error)) from None


__all__ = ["MANIFEST_SUFFIX", "DirectionDesign", "DirectionJobError", "direction_layout",
           "direction_settings", "has_picture", "illustration_prompt", "lora_prompt",
           "picture_aspect"]
