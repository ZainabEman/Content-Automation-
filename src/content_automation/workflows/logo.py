"""The brand logo is pasted by the app onto the finished image; the image model never draws it.

One fixed size and place on every image: the logo is LOGO_WIDTH of the image width (smaller
if it would be taller than MAX_HEIGHT of the image height), with MARGIN of the image width
to the top and right edges. On 9:16 images it sits just below the top safe zone. The prompt
keeps that corner clear (design_system.json core.logo).
"""

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, UnidentifiedImageError

LOGO_WIDTH = 0.20  # share of the image width
MAX_HEIGHT = 0.09  # share of the image height
MARGIN = 0.04  # share of the image width, to the top and right edges
STORY_TOP = 0.13  # 9:16: the top safe zone (design_system.json kinds.story)
MIN_TRANSPARENT = 0.05  # share of transparent pixels that marks a transparent background


class LogoError(ValueError):
    """The logo file is missing or cannot be placed (no transparent background)."""


@dataclass(frozen=True)
class LogoOverlay:
    path: Path  # the original logo file
    source: str  # e.g. brand/logo/logo (1).png
    asset_id: str

    def describe(self) -> str:
        return (
            f"{self.source} pasted by the app at the top right, {LOGO_WIDTH:.0%} of the width "
            "(not drawn by the image model)"
        )


def load_logo(path: Path) -> Image.Image:
    """The logo with its transparent margins trimmed; LogoError if it has no transparency."""
    try:
        with Image.open(path) as source:
            logo = source.convert("RGBA")
    except (OSError, UnidentifiedImageError):
        raise LogoError(f"The logo file cannot be read: {path}.") from None
    alpha = logo.getchannel("A")
    transparent = sum(alpha.histogram()[:16]) / (logo.width * logo.height)
    box = alpha.getbbox()
    if transparent < MIN_TRANSPARENT or box is None:
        raise LogoError(
            f"The logo {path.name} has no transparent background, so it cannot be placed on "
            "the designs. Supply a PNG of the logo with a transparent background in "
            'assets/reference/brand/logo/, run `uv run ca refs scan`, and set "logoFile" in '
            "brand.json to it."
        )
    return logo.crop(box)


def check_logo(overlay: LogoOverlay) -> None:
    load_logo(overlay.path)


def logo_box(size: tuple[int, int], logo_size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Where the logo goes on an image of `size`: left, top, width, height in pixels."""
    width, height = size
    target_w = round(width * LOGO_WIDTH)
    target_h = round(target_w * logo_size[1] / logo_size[0])
    if target_h > height * MAX_HEIGHT:
        target_h = round(height * MAX_HEIGHT)
        target_w = round(target_h * logo_size[0] / logo_size[1])
    margin = round(width * MARGIN)
    top = margin + (round(height * STORY_TOP) if height / width > 1.5 else 0)
    return width - margin - target_w, top, target_w, target_h


def apply_logo(data: bytes, overlay: LogoOverlay) -> bytes:
    """Paste the logo onto one generated image; returns PNG bytes."""
    logo = load_logo(overlay.path)
    with Image.open(io.BytesIO(data)) as source:
        image = source.convert("RGBA")
    left, top, width, height = logo_box(image.size, logo.size)
    resized = logo.resize((width, height), Image.Resampling.LANCZOS)
    image.alpha_composite(resized, (left, top))
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
