"""Local output persistence; callers use these functions rather than building paths."""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .config import PROJECT_ROOT
from .models import Asset, ImageGenerationJob


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _job_path(job_id: str) -> Path:
    return PROJECT_ROOT / "outputs" / "jobs" / f"{job_id}.json"


def _image_path(asset_id: str, output_format: str) -> Path:
    extension = "jpg" if output_format == "jpeg" else "png"
    return PROJECT_ROOT / "outputs" / "images" / f"{asset_id}.{extension}"


def relative_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def absolute_path(path: Path) -> str:
    return str(path.resolve())


def save_job(job: ImageGenerationJob) -> str:
    path = _job_path(job.job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(job.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)
    return relative_path(path)


def save_image(image_bytes: bytes, output_format: str) -> tuple[Asset, str, str]:
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source.load()
            image = source.convert("RGB") if output_format == "jpeg" else source.copy()
            width, height = image.size
            asset_id = new_id("asset")
            path = _image_path(asset_id, output_format)
            path.parent.mkdir(parents=True, exist_ok=True)
            image.save(path, format="JPEG" if output_format == "jpeg" else "PNG")
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError(f"BFL returned a file that is not a valid image: {exc}") from exc

    asset = Asset(
        asset_id=asset_id,
        type="image",
        uri=relative_path(path),
        mime_type="image/jpeg" if output_format == "jpeg" else "image/png",
        provider="bfl",
        created_at=utc_now(),
        metadata={"width": width, "height": height, "format": output_format},
    )
    return asset, relative_path(path), absolute_path(path)

