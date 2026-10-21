"""Phase D step 8: a design direction as one image job of the existing build.

The direction fixes the provider (never swapped; IMAGE_PROVIDER=mock stays mock for local tests):
no picture = the free template, an illustration = OpenRouter (Nano Banana 2, CAROUSEL_IMAGE_MODEL),
Roman = Higgsfield Soul 2.0 with his saved character (a real photo is never the final image).

v6 (PRD R3.4-R3.6), two modes for a non-Roman picture:
- designer (the default): the model drew the whole ad with the exact German strings; the app
  covers the logo corner with a small plate sampled from the background around it and places the
  official logo (and the website) in the layout's zones, reads the text back once
  (workflows/text_reader.py) and runs the image checks (workflows/image_check.py). It fails only
  for a wrong or missing intended string or a logo or wordmark that still shows outside the
  plate (2026-10-21; decoration in the corner is covered, never a failure); other glyphs in the
  illustration are warnings. A failure raises
  DesignerCheckError: run_workflow makes one regeneration; when that fails too, the scene is
  reused in composite mode with no model call where the layout covers the model's text (the
  text outside the picture's zone or under a filled panel), else one composite generation.
  A text-check service error retries the check NETWORK_RETRIES times with backoff and never
  fails the image: it then passes with a warning for Codex's visual review.
- composite (the fallback, and always for Roman): the model drew the scene only; the app draws the
  whole design (workflows/design_render.py: text, logo, footer, icons, CTA, decorations) in the
  package's variation (content/design_variation.py) and checks it.
The render manifest is written beside the PNG; an error fails that image, never a silent pass.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from PIL import Image, ImageOps

from content_automation.ai.image import (
    ASPECT_RATIOS,
    NETWORK_BACKOFF_S,
    NETWORK_RETRIES,
    AspectRatio,
)
from content_automation.content.design_variation import Variation
from content_automation.content.design_variation import apply as apply_variation
from content_automation.content.directions import (
    SIDE_LAYOUTS,
    Direction,
    DirectionCatalog,
    DirectionError,
    Layout,
    load_directions,
)
from content_automation.core.config import Settings
from content_automation.core.parallel import released
from content_automation.references import load_brand
from content_automation.references.services import load_services
from content_automation.workflows.cutout import CutoutError, cut_out
from content_automation.workflows.design_check import Report, check_manifest
from content_automation.workflows.design_render import (
    Assets,
    DesignRenderError,
    Rendered,
    design_fonts,
    emblem_file,
    logo_file,
    place_brand_marks,
    placeholder,
    plain,
    render_layout,
    token_colors,
)
from content_automation.workflows.image_check import CODES, ImageFacts, check_image
from content_automation.workflows.roman_check import run_checks
from content_automation.workflows.text_reader import TextReadError, reader_for

MANIFEST_SUFFIX = ".design.json"  # beside image-N.png in the job folder
DESIGNER_CHECK_FAILED = "designer check failed"  # run_workflow retries, then composite mode
_TEXT_CODES = {"coordinates", "placeholder", "slide_number", "extra_logo", "stray_text",
               "text_mismatch", "not_german"}


class DirectionJobError(ValueError):
    """The direction cannot be prepared or its design does not pass the check."""


class DesignerCheckError(DirectionJobError):
    """A designer-mode image failed the text verification or the image checks (R3.4)."""


def reusable_box(layout: Layout, size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    """The picture zone (pixels) when a failed designer scene can be reused under the app's own
    design: every text, list and icon zone lies outside it or on a filled panel that covers the
    model's text. None: it cannot, so composite mode makes a new picture."""
    visual = next((z for z in layout.zones.values() if z.kind == "visual"), None)
    if visual is None:
        return None
    panels = [z.box for z in layout.zones.values()
              if z.kind == "shape" and z.shape in ("panel", "glass", "bar") and z.fill]

    def overlaps(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
        return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]

    def inside(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
        return b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]

    for zone in layout.zones.values():
        if zone.kind in ("text", "items", "icons") and overlaps(zone.box, visual.box) and not any(
                inside(zone.box, panel) for panel in panels):
            return None
    width, height = size
    return (round(visual.box[0] * width), round(visual.box[1] * height),
            round(visual.box[2] * width), round(visual.box[3] * height))


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
    mode: str = "composite"  # v6: designer | composite (R3.4)
    texts: list[str] = field(default_factory=list)  # designer: the strings the model wrote
    variation: str | None = None  # v6 (R3.5), e.g. "R/open/chevrons/calendar"
    check_cost_usd: float = 0.0  # the text checks of the last render (actual)
    reuse_scene: bool = False  # the last designer attempt: a failure reuses its scene (composite)

    def describe(self) -> str:
        if self.mode == "designer":
            return (f"{self.direction} {self.layout}: designer mode (the model drew the ad with "
                    "the exact German text; the app placed the logo and the website, read the "
                    "text back and checked the image)")
        return (f"{self.direction} {self.layout}"
                + (f" ({self.variation})" if self.variation else "")
                + ": composite mode, drawn by the app (text, logo, footer, icons, CTA) on the "
                "generated scene; design check after rendering")

    def to_json(self) -> str:
        return json.dumps({"direction": self.direction, "layout": self.layout,
                           "platform": self.platform, "step": self.step, "mode": self.mode,
                           "variation": self.variation}, ensure_ascii=False)

    def drawn_layout(self) -> Layout:
        """The layout as drawn: the stored one in the package's variation (v6 R3.5)."""
        catalog = load_directions()
        direction = catalog.get(self.direction)
        layout = direction.layouts[self.layout]
        if not self.variation:
            return layout
        try:
            return apply_variation(direction, layout, Variation.parse(self.variation), catalog)
        except DirectionError as error:
            raise DirectionJobError(f"{self.direction} variation {self.variation}: {error}") \
                from None

    def picture(self, generated: Image.Image | None, mock: bool = False) -> Image.Image | None:
        """The generated picture; a cut-out zone keys out a green backdrop. A failed cut-out
        fails the image (mock test images have no backdrop)."""
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
            raise DirectionJobError(f"{self.direction}: the image cannot be cut out "
                                    f"({error}); make it again, never a real photo") from None

    def render(self, generated: Image.Image | None, settings: Settings, *,
               manual_acceptances: dict[str, str] | None = None
               ) -> tuple[Rendered, Report]:
        """Draw the design on the picture (designer mode: only the logo and the website), then
        check it: the manifest, the image itself and the text read back (R3.6)."""
        catalog = load_directions()
        direction = catalog.get(self.direction)
        brand = load_brand(settings.references_dir)
        assets = Assets(brand=brand, logo_path=logo_file(brand, settings.references_dir),
                        fonts=design_fonts(brand),
                        emblem_path=emblem_file(brand, settings.references_dir))
        layout = self.drawn_layout()
        mock = settings.image_provider == "mock"
        designer = self.mode == "designer" and generated is not None
        canvas: Image.Image | None = None
        try:
            if designer:
                assert generated is not None
                # the copy must fit the composite fallback too: a free fit check first
                render_layout(catalog, direction, self.layout, self.copy, assets, picture=None,
                              step=self.step, layout=layout)
                if mock:  # the mock picture is a light test card: a dark stand-in scene
                    generated = placeholder(catalog.size(direction), direction.id,
                                            token_colors(brand))
                canvas = ImageOps.fit(generated.convert("RGB"), catalog.size(direction),
                                      Image.Resampling.LANCZOS)
                rendered = place_brand_marks(canvas, direction, self.layout, layout, assets,
                                             self.copy)
            else:
                rendered = render_layout(catalog, direction, self.layout, self.copy, assets,
                                         picture=self.picture(generated, mock),
                                         step=self.step, layout=layout)
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
            roman, _ = run_checks(manifest, side, None if mock else generated,
                                  manual_acceptances=manual_acceptances)
            report.errors += roman.errors
            report.checks = roman.results
        if generated is not None and settings.image_provider != "template":
            try:
                self._check_image(rendered, report, direction, settings, designer)
            except DesignerCheckError as error:
                box = reusable_box(layout, rendered.size)
                if not self.reuse_scene or canvas is None or box is None:
                    raise
                # no model call: the failed scene under the app's own design (composite)
                self.mode, self.texts, self.reuse_scene = "composite", [], False
                self.notes.append(f"composite mode on the designer scene, no new call ({error})")
                return self.render(canvas.crop(box), settings)
        return rendered, report

    def _check_image(self, rendered: Rendered, report: Report, direction: Direction,
                     settings: Settings, designer: bool) -> None:
        """v6 R3.6: the image checks and the exact-text verification (designer: the model's
        strings; composite: the app's own text, so any stray text from the scene fails)."""
        from content_automation.workflows.design_check import image_rules

        width, height = rendered.size
        logo = rendered.logo.box if rendered.logo is not None else None
        intended = list(self.texts) if designer else [
            " ".join(text.drawn) if text.drawn else text.text for text in rendered.texts
            if text.zone not in ("footer",)]
        facts = ImageFacts(
            category=direction.category, roman=direction.roman,
            provider="higgsfield_soul" if direction.roman else "openrouter",
            last_slide=direction.format != "carousel" or self.layout == direction.last_layout(),
            logo_box=(logo[0] / width, logo[1] / height, logo[2] / width, logo[3] / height)
            if logo else None, website=bool(rendered.footer), intended=intended)
        if direction.roman:  # Higgsfield: no logo, no website, never a real photo; the text
            # and the German are checked by run_checks and Codex's visual review (R4.5)
            report.errors += check_image(rendered.image, facts, image_rules(), base=False)
            return
        reader = reader_for(settings)
        read, problem = None, ""
        for retry in range(NETWORK_RETRIES + 1):  # a service error retries the same check
            try:
                read = reader.read(rendered.image, intended)
                break
            except TextReadError as error:
                if not error.service:
                    report.errors.append(f"[text_mismatch] {error}")
                    return
                problem = str(error)
            if retry < NETWORK_RETRIES:
                with released():  # a parallel build: the others run meanwhile
                    time.sleep(NETWORK_BACKOFF_S * 2**retry)
        if read is None:  # never an image attempt: Codex's visual review checks the text
            report.warnings.append(f"[text_check_unavailable] {problem} (retried "
                                   f"{NETWORK_RETRIES} times); the text was not read: the "
                                   "visual review must confirm it")
            return
        self.check_cost_usd += read.cost_usd or 0.0
        facts.read = read.texts
        found = check_image(rendered.image, facts, image_rules(), warnings=report.warnings)
        if settings.image_provider == "mock":  # a mock picture is a stand-in: only its text
            report.warnings += [f"mock picture: {error}" for error in found
                                if error[1:].split("]")[0] not in _TEXT_CODES]
            found = [error for error in found if error[1:].split("]")[0] in _TEXT_CODES]
        report.errors += found
        report.checks["textRead"] = f"{read.reader}: {len(read.texts)} line(s)"
        if designer and found:
            raise DesignerCheckError(f"{DESIGNER_CHECK_FAILED}: " + "; ".join(found))


__all__ = ["CODES", "DESIGNER_CHECK_FAILED", "MANIFEST_SUFFIX", "DesignerCheckError",
           "DirectionDesign", "DirectionJobError", "direction_layout",
           "direction_settings", "has_picture", "illustration_prompt",
           "picture_aspect", "reusable_box"]
