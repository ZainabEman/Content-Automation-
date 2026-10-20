"""Where Roman is in a generated image, and a crop that never cuts his head or hands.

A simple, documented, offline method (no model download): skin-tone pixels (YCrCb ranges that
work on the warm frontal key light the guidelines ask for) form the person-like regions; the
face is the topmost skin region (an OpenCV Haar frontal face, bundled with opencv, refines it
when it finds one), the hands are the skin regions below it. The bright, low-saturation shirt
joins the person box when it touches a skin region. Blue holograms and the near-black navy
background are not skin. It is a heuristic: the Codex visual review confirms every image.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

Box = tuple[int, int, int, int]  # left, top, right, bottom (pixels)
_MIN_SHARE = 0.0005  # a skin region smaller than this share of the image is noise


class CropError(ValueError):
    """No crop to the target aspect keeps the head and the hands."""


@dataclass
class PersonZone:
    size: tuple[int, int]
    regions: list[Box] = field(default_factory=list)  # person-like (skin) regions
    box: Box | None = None  # the person: skin regions (and the shirt touching them)
    head_top: int | None = None
    hands_bottom: int | None = None

    @property
    def found(self) -> bool:
        return self.box is not None


def _components(mask: np.ndarray, min_area: int) -> list[Box]:
    count, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8),
                                                          connectivity=8)
    boxes = []
    for index in range(1, count):
        x, y, width, height, area = (int(value) for value in stats[index])
        if area >= min_area:
            boxes.append((x, y, x + width, y + height))
    return boxes


def _union(boxes: list[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
            max(b[3] for b in boxes))


def _touches(first: Box, second: Box, slack: int) -> bool:
    return (first[0] - slack < second[2] and second[0] - slack < first[2]
            and first[1] - slack < second[3] and second[1] - slack < first[3])


def detect(image: Image.Image, min_share: float = _MIN_SHARE) -> PersonZone:
    rgb = np.asarray(image.convert("RGB"))
    height, width = rgb.shape[:2]
    ycrcb = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb)
    y, cr, cb = ycrcb[..., 0], ycrcb[..., 1], ycrcb[..., 2]
    raw = ((cr >= 135) & (cr <= 180) & (cb >= 80) & (cb <= 130) & (y >= 60)).astype(np.uint8)
    kernel = np.ones((5, 5), np.uint8)
    skin = np.asarray(cv2.morphologyEx(raw, cv2.MORPH_OPEN, kernel), dtype=np.uint8)
    min_area = max(30, int(width * height * min_share))
    regions = _components(skin, min_area)
    zone = PersonZone(size=(width, height), regions=regions)
    if not regions:
        return zone
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    shirt = ((hsv[..., 1] < 40) & (hsv[..., 2] > 170)).astype(np.uint8)
    shirts = [box for box in _components(shirt, min_area)
              if any(_touches(box, region, width // 40) for region in regions)]
    zone.box = _union(regions + shirts)
    face = min(regions, key=lambda box: box[1])
    zone.head_top = face[1]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    cascade = cv2.CascadeClassifier(str(Path(cv2.__file__).parent / "data"
                                        / "haarcascade_frontalface_default.xml"))
    faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(width // 40, width // 40))
    if len(faces):
        fx, fy, fw, fh = (int(v) for v in max(faces, key=lambda f: f[2] * f[3]))
        zone.head_top = min(zone.head_top, max(0, fy - fh // 3))  # hair above the face box
    lower = [box for box in regions if box is not face]
    zone.hands_bottom = max(box[3] for box in lower) if lower else face[3]
    return zone


def safe_crop(image: Image.Image, aspect: tuple[int, int], zone: PersonZone,
              margin: int = 8) -> tuple[Image.Image, Box]:
    """Crop the height to `aspect` (width:height) keeping the head and the hands; more is taken
    from the bottom unless that cuts his hands. CropError when no such crop exists."""
    width, height = image.size
    target_height = round(width * aspect[1] / aspect[0])
    if target_height > height:
        raise CropError(f"{width}x{height} is too short for {aspect[0]}:{aspect[1]} (would "
                        "need an upscale)")
    cut = height - target_height
    if cut == 0:
        return image, (0, 0, width, height)
    head = zone.head_top if zone.head_top is not None else height
    hands = zone.hands_bottom if zone.hands_bottom is not None else 0
    bottom_room = max(0, height - hands - margin)  # rows below the hands
    top = max(0, cut - bottom_room)  # take as much as possible from the bottom
    if zone.found and top > max(0, head - margin):
        raise CropError(f"no crop to {aspect[0]}:{aspect[1]} keeps his head (top {head}px) and "
                        f"his hands (bottom {hands}px) in a {width}x{height} image")
    box = (0, top, width, top + target_height)
    return image.crop(box), box


def shift_crop(image: Image.Image, zone: PersonZone, side: str, share: float, *,
               min_keep: float = 0.7, margin: int = 8) -> tuple[Image.Image, Box]:
    """A crop with the image's own aspect that moves the person into the outer `share` of the
    width on his side (S-R: right) by trimming the strip beyond him on that side (and the same
    share of the height), keeping his whole box (head and hands). At least `min_keep` of the
    width stays. CropError when no such crop exists (then the operator decides; nothing is
    regenerated)."""
    if zone.box is None:
        raise CropError("no person found to shift")
    width, height = image.size
    left, top, right, bottom = zone.box
    if side == "S-L":  # mirrored: the left edge is the outer one
        left, right = width - right, width - left
    # keep the outer side up to the person's far edge plus a margin; trim beyond it
    window = min(width, left / (1 - share)) if share < 1 else width
    if window < min(width, right + margin) or window < width * min_keep:
        raise CropError(f"no crop keeps him whole within the outer {share:.0%} (he starts at "
                        f"{left / width:.0%} of the width)")
    new_width = int(window)
    new_height = round(height * new_width / width)
    head = zone.head_top if zone.head_top is not None else top
    hands = zone.hands_bottom if zone.hands_bottom is not None else bottom
    y = max(0, min(head - margin, height - new_height))
    if y + new_height < min(height, hands + margin):
        raise CropError("no crop keeps his head and hands while moving him outward")
    # S-R keeps the left (text) side and trims the strip beyond him on the right; S-L mirrors
    x = width - new_width if side == "S-L" else 0
    box = (x, y, x + new_width, y + new_height)
    return image.crop(box), box


__all__ = ["Box", "CropError", "PersonZone", "detect", "safe_crop", "shift_crop"]
