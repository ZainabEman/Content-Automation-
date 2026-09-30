"""Load, orient, budget, and encode a local identity reference set."""

from __future__ import annotations

import base64
import hashlib
import io
import math
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from .config import MAX_REFERENCE_IMAGES, MAX_REQUEST_PIXELS, PROJECT_ROOT

REFERENCE_ROOT = PROJECT_ROOT / "reference" / "identity"
SUPPORTED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


@dataclass
class PreparedReference:
    source_path: Path
    sha256: str
    width: int
    height: int
    jpeg_bytes: bytes
    image_base64: str

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    def metadata(self) -> dict[str, str | int]:
        return {
            "name": self.source_path.name,
            "sha256": self.sha256,
            "width": self.width,
            "height": self.height,
        }


@dataclass
class PreparedReferenceSet:
    name: str
    references: list[PreparedReference]
    omitted_count: int
    source_count: int
    total_pixels: int


def _read_oriented_rgb(path: Path) -> Image.Image:
    try:
        with Image.open(path) as source:
            oriented = ImageOps.exif_transpose(source)
            if oriented.mode in ("RGBA", "LA") or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                return background
            return oriented.convert("RGB")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"Could not read reference image '{path.name}': {exc}") from exc


def load_reference_set(
    folder_name: str,
    *,
    output_pixels: int,
    reference_root: Path = REFERENCE_ROOT,
    max_count: int = MAX_REFERENCE_IMAGES,
    request_pixel_budget: int = MAX_REQUEST_PIXELS,
) -> PreparedReferenceSet:
    """Prepare up to the endpoint's reference cap within its documented pixel budget."""
    if not folder_name or Path(folder_name).name != folder_name or folder_name in {".", ".."}:
        raise ValueError("Reference set must be a folder name, such as 'person_01'.")
    if output_pixels <= 0 or output_pixels >= request_pixel_budget:
        raise ValueError("Output size leaves no valid pixel budget for the reference images.")

    folder = (reference_root / folder_name).resolve()
    base = reference_root.resolve()
    if base not in folder.parents:
        raise ValueError("Reference set must be inside the identity reference folder.")
    if not folder.is_dir():
        raise ValueError(f"Reference set folder does not exist: {folder}")

    all_paths = sorted(
        (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES),
        key=lambda path: path.name.casefold(),
    )
    if not all_paths:
        raise ValueError(f"No supported images found in reference set '{folder_name}'.")

    selected_paths = all_paths[:max_count]
    images = [_read_oriented_rgb(path) for path in selected_paths]
    pixel_budget = request_pixel_budget - output_pixels
    original_pixels = sum(image.width * image.height for image in images)
    scale = min(1.0, math.sqrt(pixel_budget / original_pixels))

    # Pillow rounds dimensions independently; keep the sum strictly within budget.
    while True:
        sizes = [(max(1, int(image.width * scale)), max(1, int(image.height * scale))) for image in images]
        if sum(width * height for width, height in sizes) <= pixel_budget:
            break
        scale *= math.sqrt(pixel_budget / sum(width * height for width, height in sizes)) * 0.999

    prepared: list[PreparedReference] = []
    for path, image, (width, height) in zip(selected_paths, images, sizes):
        if image.size != (width, height):
            image = image.resize((width, height), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=92, optimize=True)
        jpeg_bytes = buffer.getvalue()
        prepared.append(
            PreparedReference(
                source_path=path,
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                width=width,
                height=height,
                jpeg_bytes=jpeg_bytes,
                image_base64=base64.b64encode(jpeg_bytes).decode("ascii"),
            )
        )

    return PreparedReferenceSet(
        name=folder_name,
        references=prepared,
        omitted_count=len(all_paths) - len(selected_paths),
        source_count=len(all_paths),
        total_pixels=sum(reference.pixel_count for reference in prepared),
    )

