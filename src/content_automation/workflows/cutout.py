"""Roman cut out of an approved green-screen photo (FD-1): his real photo, nothing generated.

First a plain chroma key (numpy/OpenCV): green pixels out, then the largest part that does not
touch the top edge. The approved selfies show the ceiling above the screen and shadowed green
at the bottom, so the key alone leaves the ceiling on his hair; then the person mask of rembg's
u2net_human_seg model (already a dependency; rembg MIT, model Apache-2.0, read from the local
.cache/rembg and never downloaded here) is combined with the key. Green spill on the edges is
pulled back to the other channels. Results are cached by photo hash in outputs/cache/cutouts/.
"""

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from typing import cast

import cv2
import numpy as np
from PIL import Image

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
MODEL = "u2net_human_seg"
MODEL_HOME = _PROJECT_ROOT / ".cache" / "rembg"  # the same cache as workflows/compose.py
CACHE = Path("outputs") / "cache" / "cutouts"
_SEGMENT_SIDE = 768  # the person mask is computed small and scaled up (fast on the CPU)
_GREEN_SOFT = (8.0, 38.0)  # greenness (g - max(r, b)): fully kept below, fully keyed above
Segmenter = Callable[[Image.Image], Image.Image]


class CutoutError(ValueError):
    """The photo cannot be cut out cleanly (no green screen, or no model for the fallback)."""


def _greenness(rgb: np.ndarray) -> np.ndarray:
    data = rgb.astype(np.int16)
    return (data[..., 1] - np.maximum(data[..., 0], data[..., 2])).astype(np.float32)


def key_alpha(image: Image.Image) -> np.ndarray:
    """0-1 alpha from the green screen alone (1 = keep)."""
    low, high = _GREEN_SOFT
    return np.clip(1 - (_greenness(np.asarray(image.convert("RGB"))) - low) / (high - low), 0, 1)


def _key_is_clean(alpha: np.ndarray) -> bool:
    """One main part that does not touch the top edge (no ceiling, no wall above the screen)."""
    binary = (alpha > 0.5).astype(np.uint8)
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if count < 2:
        return False
    areas = stats[1:, cv2.CC_STAT_AREA]
    main = int(np.argmax(areas)) + 1
    top_touch = bool(stats[main, cv2.CC_STAT_TOP] == 0)
    cover = float(binary.mean())
    return not top_touch and 0.15 <= cover <= 0.75 and float(areas.max() / areas.sum()) > 0.97


def _model_file() -> Path:
    return MODEL_HOME / "models" / MODEL / f"{MODEL}.onnx"


def rembg_segmenter() -> Segmenter:
    """The person mask from the locally cached model; CutoutError when it is not there."""
    if not _model_file().is_file():
        raise CutoutError(
            f"The person model {_model_file()} is missing, and the green screen alone does not "
            "cut this photo cleanly. Run `uv run ca compose preview` once on a machine with "
            "internet access (it downloads the public model into .cache/rembg), then retry.")
    os.environ["U2NET_HOME"] = str(MODEL_HOME)  # rembg reads <home>/models/<name>/<name>.onnx
    from rembg import new_session, remove

    session = new_session(MODEL, providers=["CPUExecutionProvider"])

    def segment(image: Image.Image) -> Image.Image:
        small = image.convert("RGB")
        small.thumbnail((_SEGMENT_SIDE, _SEGMENT_SIDE))
        mask = cast(Image.Image, remove(small, session=session, only_mask=True)).convert("L")
        return mask.resize(image.size, Image.Resampling.BILINEAR)

    return segment


def _despill(rgb: np.ndarray) -> np.ndarray:
    data = rgb.astype(np.int16).copy()
    limit = np.maximum(data[..., 0], data[..., 2])
    data[..., 1] = np.minimum(data[..., 1], limit + 6)
    return data.clip(0, 255).astype(np.uint8)


def cut_out(image: Image.Image, segmenter: Segmenter | None = None) -> tuple[Image.Image, str]:
    """RGBA of the person, trimmed to him, and how it was made ("key" or "key + model")."""
    rgb = image.convert("RGB")
    key = key_alpha(rgb)
    if float((key < 0.5).mean()) < 0.2:
        raise CutoutError("this photo has no green screen to key out (under 20% green)")
    method = "key"
    alpha = key
    if not _key_is_clean(key):
        segment = segmenter or rembg_segmenter()
        person = np.asarray(segment(rgb).convert("L")).astype(np.float32) / 255
        alpha = np.minimum(key, person)
        method = "key + model"
        if float((alpha > 0.5).mean()) < 0.1:
            raise CutoutError("the cut-out is nearly empty: check the photo")
    soft = cv2.GaussianBlur(alpha.astype(np.float32), (3, 3), 0)
    rgba = np.dstack([_despill(np.asarray(rgb)), (soft * 255).astype(np.uint8)])
    out = Image.fromarray(rgba, "RGBA")
    box = out.getchannel("A").point(lambda value: 255 if value > 24 else 0).getbbox()
    return (out.crop(box) if box else out), method


def cached_cutout(photo: Path, segmenter: Segmenter | None = None,
                  cache: Path = CACHE) -> tuple[Image.Image, str]:
    """cut_out with a cache by the photo's hash (the photo itself is never changed)."""
    digest = hashlib.sha256(photo.read_bytes()).hexdigest()[:16]
    target = cache / f"{digest}.png"
    if target.is_file():
        with Image.open(target) as cached:
            return cached.convert("RGBA"), "cached"
    with Image.open(photo) as source:
        made, method = cut_out(source, segmenter)
    target.parent.mkdir(parents=True, exist_ok=True)
    made.save(target, format="PNG", optimize=True)
    return made, method
