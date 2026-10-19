"""YouTube thumbnails (Phase 8 Step 2; the podcast parts were removed in v5, PRD R8).

`ca thumbnail BG-x`: 1280x720 from the newest imported thumbnail image (the background) with the
production brief's thumbnail text (at most 5 words) in the design system's overlay fonts.
"""

import json
import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from content_automation.content.production import produced_item, version_dir
from content_automation.core.config import Settings
from content_automation.registry.artifacts import add_artifact, latest_artifact
from content_automation.registry.db import RegistryError
from content_automation.workflows.design_system import load_design_system
from content_automation.workflows.text_overlay import resolve_fonts

THUMBNAIL_SIZE = (1280, 720)


def _brief(conn: sqlite3.Connection, item_id: str, version: int) -> dict[str, object]:
    found = latest_artifact(conn, item_id, "brief", version)
    if found is None:
        raise RegistryError(f"{item_id} has no production brief for v{version}: ca brief save.")
    data = json.loads(Path(found.path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def make_thumbnail(conn: sqlite3.Connection, settings: Settings, ref: str, *,
                   command: str | None = None) -> list[str]:
    item = produced_item(conn, ref)
    background = latest_artifact(conn, item.id, "thumbnail", item.current_version)
    if background is None:
        raise RegistryError(f"{item.id}: import a background first: uv run ca import {item.id} "
                            "<image> --as thumbnail")
    thumbnail = _brief(conn, item.id, item.current_version).get("thumbnail")
    text = str(thumbnail.get("text", "")) if isinstance(thumbnail, dict) else ""
    if not text or len(text.split()) > 5:
        raise RegistryError(f"{item.id}: the brief's thumbnail text must be 1-5 words.")
    system = load_design_system(settings.design_system_file)
    if system.text_overlay is None:
        raise RegistryError("design_system.json has no textOverlay fonts.")
    font_file = resolve_fonts(system.text_overlay.fonts, {"bold"})["bold"]
    with Image.open(background.path) as opened:
        image = ImageOps.fit(opened.convert("RGB"), THUMBNAIL_SIZE)
    draw = ImageDraw.Draw(image, "RGBA")
    size = 120
    font = ImageFont.truetype(str(font_file), size)
    while draw.textlength(text, font=font) > THUMBNAIL_SIZE[0] - 120 and size > 40:
        size -= 6
        font = ImageFont.truetype(str(font_file), size)
    width = draw.textlength(text, font=font)
    top = THUMBNAIL_SIZE[1] - size - 90
    draw.rectangle((40, top - 30, 80 + width, top + size + 30), fill=(10, 30, 90, 190))
    draw.text((60, top), text, font=font, fill=(255, 255, 255))
    out = version_dir(settings, item) / "production" / "thumbnail" / "thumbnail_1280x720.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, optimize=True)
    add_artifact(conn, item.id, item.current_version, "thumbnail", out.as_posix(),
                 {"ok": True, "text": text, "size": "1280x720"}, command=command)
    return [f"{item.id}: thumbnail {out.as_posix()} (\"{text}\")"]


__all__ = ["THUMBNAIL_SIZE", "make_thumbnail"]
