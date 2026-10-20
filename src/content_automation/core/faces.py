"""Face detection on a picture (OpenCV Haar cascades; free and local).

Moved from the deleted LoRA module (PRD v6 R5): the person check, the person post composition
and the card use it.
"""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

_DETECT_SIDE = 1024  # faces are searched on a copy scaled to this long side
_MIN_FACE = 0.08  # smallest face side, share of the image's short side
_SMALL_FACE = 0.25  # faces under this share of the largest one are ignored (background)
_CASCADES: dict[str, cv2.CascadeClassifier] = {}


def _cascade(name: str) -> cv2.CascadeClassifier:
    if name not in _CASCADES:  # the cascades ship in cv2/data (OpenCV 4.x)
        path = Path(cv2.__file__).parent / "data" / name
        _CASCADES[name] = cv2.CascadeClassifier(str(path))
    return _CASCADES[name]


def count_faces(image: Image.Image) -> int:
    """Faces in the photo: frontal, else profile (both sides); overlapping and tiny
    background boxes are not counted."""
    return len(face_boxes(image))


def face_boxes(image: Image.Image) -> list[tuple[float, float, float, float]]:
    """The faces counted by count_faces as (left, top, right, bottom) shares of the image
    (OpenCV Haar cascades; free and local)."""
    scale = min(1.0, _DETECT_SIDE / max(image.size))
    small = image.convert("L").resize(
        (round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS
    )
    gray = np.asarray(small)
    side = round(min(gray.shape) * _MIN_FACE)
    boxes: list[tuple[int, int, int, int]] = []
    for name, flip in (
        ("haarcascade_frontalface_default.xml", False),
        ("haarcascade_profileface.xml", False),
        ("haarcascade_profileface.xml", True),
    ):
        source = np.ascontiguousarray(gray[:, ::-1]) if flip else gray
        found = _cascade(name).detectMultiScale(
            source, scaleFactor=1.1, minNeighbors=6, minSize=(side, side)
        )
        width = gray.shape[1]  # a mirrored pass: its boxes are mirrored back
        boxes += [(int(width - x - w) if flip else int(x), int(y), int(w), int(h))
                  for x, y, w, h in found]
        if boxes:
            break
    if not boxes:
        return []
    largest = max(w for _, _, w, _ in boxes)
    kept: list[tuple[int, int, int, int]] = []
    for box in sorted(boxes, key=lambda b: -b[2]):
        x, y, w, h = box
        if w < largest * _SMALL_FACE:
            continue
        center = (x + w / 2, y + h / 2)
        if any(kx <= center[0] <= kx + kw and ky <= center[1] <= ky + kh
               for kx, ky, kw, kh in kept):
            continue
        kept.append(box)
    high, wide = gray.shape
    return [(x / wide, y / high, (x + w) / wide, (y + h) / high) for x, y, w, h in kept]


__all__ = ["count_faces", "face_boxes"]
