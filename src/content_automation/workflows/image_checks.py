"""Image checks after each generated image (Phase 7 Step 3): the size and not blank."""

from pathlib import Path

from PIL import Image, ImageStat

MIN_SIDE = 512  # pixels: smaller is not a usable social image
BLANK_SPREAD = 2.0  # grey standard deviation below this: one flat colour


def image_problems(path: Path, *, min_side: int = MIN_SIDE) -> list[str]:
    """What is wrong with one image (an empty list: it passed)."""
    try:
        with Image.open(path) as opened:
            width, height = opened.size
            spread = ImageStat.Stat(opened.convert("L")).stddev[0]
    except OSError as error:
        return [f"not a readable image ({error})"]
    problems = []
    if min(width, height) < min_side:
        problems.append(f"{width}x{height} is smaller than {min_side} px")
    if spread < BLANK_SPREAD:
        problems.append("blank (one flat colour)")
    return problems
