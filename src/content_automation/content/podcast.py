"""Thumbnails and podcast audio (Phase 8 Step 2).

- `ca thumbnail BG-x`: 1280x720 from the newest imported thumbnail image (the background) with
  the production brief's thumbnail text (at most 5 words) in the design system's overlay fonts.
- `ca podcast heygen BG-x`: the HeyGen recording of a podcast whose brief says heygen, through
  the make-video plugin pattern (dry run, "ok", request file, plugin, `ca podcast record`).
  Without HEYGEN_VOICE_ID the dry run stops: "HeyGen voice ID not configured (client)".
- `ca podcast audio BG-x`: an MP3 of the newest final, edit or recording with FFmpeg loudnorm
  (config/production.json podcastLoudnessLufs, default -16 LUFS).
"""

import json
import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from content_automation.content.production import (
    import_media,
    produced_item,
    production_config,
    version_dir,
)
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.media import run_ffmpeg
from content_automation.registry.artifacts import add_artifact, latest_artifact
from content_automation.registry.db import RegistryError
from content_automation.registry.dryruns import CostLine
from content_automation.registry.jobs import get_job, load_job_config, open_job, succeed_job
from content_automation.workflows.design_system import load_design_system
from content_automation.workflows.text_overlay import resolve_fonts

THUMBNAIL_SIZE = (1280, 720)
HEYGEN_PROVIDER = "heygen-plugin"
NO_VOICE = "HeyGen voice ID not configured (client)"


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


def heygen_lines(conn: sqlite3.Connection, settings: Settings, ref: str) -> list[CostLine]:
    """The dry run of a HeyGen podcast recording (stops without the voice ID)."""
    item = produced_item(conn, ref)
    if item.kind != "podcast":
        raise RegistryError(f"{item.id} is not a podcast.")
    if not settings.heygen_voice_id:
        raise RegistryError(NO_VOICE)
    brief = _brief(conn, item.id, item.current_version)
    if brief.get("recordingSource") != "heygen":
        raise RegistryError(f"{item.id}: the brief's recordingSource is "
                            f"{brief.get('recordingSource')}, not heygen.")
    per = load_job_config(settings.jobs_file).estimate("avatar_scene", HEYGEN_PROVIDER) or 0.0
    segments = brief.get("segments")
    count = len(segments) if isinstance(segments, list) else 1
    return [CostLine(item.id, "avatar_scene", HEYGEN_PROVIDER, "credits", per * count,
                     per * count, f"HeyGen podcast recording ({count} segment(s))")]


def heygen_request(conn: sqlite3.Connection, settings: Settings, ref: str, *,
                   command: str | None = None) -> list[str]:
    """After the "ok": one request file for the make-video skill (HeyGen plugin)."""
    lines = heygen_lines(conn, settings, ref)
    item = produced_item(conn, ref)
    script = latest_artifact(conn, item.id, "script", item.current_version)
    if script is None:
        raise RegistryError(f"{item.id} has no saved script for v{item.current_version}.")
    opened = open_job(conn, item_id=item.id, job_type="avatar_scene", provider=HEYGEN_PROVIDER,
                      inputs={"script": script.path, "voiceId": settings.heygen_voice_id,
                              "avatarId": settings.heygen_avatar_id or ""},
                      config=load_job_config(settings.jobs_file), estimate=lines[0].estimate,
                      unit="credits", command=command)
    request = settings.state_dir / "heygen" / f"{opened.job.id}.json"
    request.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(request, json.dumps({
        "jobId": opened.job.id, "item": item.id, "script": Path(script.path).with_suffix(".md")
        .as_posix(), "voiceId": settings.heygen_voice_id, "avatarId": settings.heygen_avatar_id,
    }, indent=2) + "\n")
    return [f"HeyGen request #{opened.job.id}: {request.as_posix()}",
            f"Next (make-video skill): uv run ca jobs check {opened.job.id}, the HeyGen plugin, "
            f"then uv run ca podcast record {opened.job.id} <file>"]


def record_heygen(conn: sqlite3.Connection, settings: Settings, job_id: int, file: Path, *,
                  credits: float | None = None, command: str | None = None) -> list[str]:
    job = get_job(conn, job_id)
    if job.item_id is None or job.provider != HEYGEN_PROVIDER:
        raise RegistryError(f"Job #{job_id} is not a HeyGen podcast request.")
    lines = import_media(conn, settings, job.item_id, file, "recording", command=command)
    succeed_job(conn, job_id, actual=credits, result_path=file.as_posix(), command=command)
    return [f"Job #{job.id} recorded.", *lines]


def podcast_audio(conn: sqlite3.Connection, settings: Settings, ref: str, *,
                  command: str | None = None) -> list[str]:
    item = produced_item(conn, ref)
    source = next((found for kind in ("final", "edit", "recording")
                   if (found := latest_artifact(conn, item.id, kind, item.current_version))),
                  None)
    if source is None:
        raise RegistryError(f"{item.id}: import a recording, edit or final first.")
    lufs = float(production_config(settings).get("podcastLoudnessLufs", -16))
    out = version_dir(settings, item) / "production" / "audio" / f"{item.id}.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-y", "-i", source.path, "-vn", "-af", f"loudnorm=I={lufs:g}:TP=-1.5:LRA=11",
                "-ar", "44100", "-codec:a", "libmp3lame", "-b:a", "128k", str(out)],
               timeout_s=900)
    add_artifact(conn, item.id, item.current_version, "audio", out.as_posix(),
                 {"ok": True, "lufs": lufs, "source": source.path}, command=command)
    return [f"{item.id}: {out.as_posix()} (MP3, loudnorm {lufs:g} LUFS, from {source.type})"]
