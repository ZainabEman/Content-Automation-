"""The carousel output format (Phase 7 Step 2): static, animated or single_video.

- static: the 8 slide PNGs from the stills only (no clip requests, no MP4s);
- animated (default, config/carousel.json, client to confirm): 8 MP4 slides;
- single_video: the 8 MP4 slides joined into carousel/final/carousel.mp4 with FFmpeg.
`ca content build "<folder>" --format X` stores it in package.json; the dry run shows the cost of
that format, stills-check and render follow it.
"""

import json
from pathlib import Path
from typing import Literal, cast

from content_automation.core.config import Settings

CarouselFormat = Literal["static", "animated", "single_video"]
FORMATS: tuple[CarouselFormat, ...] = ("static", "animated", "single_video")
PACKAGE_KEY = "carouselFormat"


def default_format(settings: Settings) -> CarouselFormat:
    try:
        value = json.loads(settings.carousel_file.read_text(encoding="utf-8")).get("format")
    except (OSError, ValueError, AttributeError):
        value = None
    return cast(CarouselFormat, value) if value in FORMATS else "animated"


def package_format(folder: Path, settings: Settings) -> CarouselFormat:
    try:
        value = json.loads((folder / "package.json").read_text(encoding="utf-8")).get(PACKAGE_KEY)
    except (OSError, ValueError, AttributeError):
        value = None
    return cast(CarouselFormat, value) if value in FORMATS else default_format(settings)


def check_format(value: str) -> CarouselFormat:
    if value not in FORMATS:
        raise ValueError(f'--format must be {", ".join(FORMATS)}, not "{value}"')
    return value
