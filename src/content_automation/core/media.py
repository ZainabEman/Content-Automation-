"""FFmpeg helpers (bundled by imageio-ffmpeg, no manual install) for clips and audio."""

import os
import subprocess
import tempfile
import textwrap
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

# Output size per aspect ratio; 9:16 is the 1080×1920 final video size.
CLIP_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
}
_TIMEOUT_S = 300
_ERROR_TAIL = 400


class MediaError(RuntimeError):
    """FFmpeg failed or produced no output."""


def run_ffmpeg(args: list[str], *, timeout_s: float = _TIMEOUT_S) -> bytes:
    """Run ffmpeg with args; return stdout (used when writing to pipe:1)."""
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", *args]
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        raise MediaError(f"FFmpeg did not finish within {timeout_s:g} seconds.") from None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()[-_ERROR_TAIL:]
        raise MediaError(f"FFmpeg failed (exit {result.returncode}): {detail}")
    return result.stdout


def placeholder_clip(
    target: Path,
    *,
    title: str,
    text: str,
    duration_sec: float,
    aspect_ratio: str,
    background: tuple[int, int, int] = (30, 41, 59),
) -> None:
    """Write an H.264 MP4 of a coloured card showing title and text for duration_sec."""
    width, height = CLIP_SIZES[aspect_ratio]
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=target.parent, prefix=".clip-") as work:
        card = Path(work) / "card.png"
        _text_card(width, height, title, text, background).save(card)
        partial = Path(work) / "clip.mp4"
        run_ffmpeg([
            "-loop", "1", "-framerate", "30", "-i", str(card), "-t", f"{duration_sec:.3f}",
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-y", str(partial),
        ])
        if not partial.is_file() or partial.stat().st_size == 0:
            raise MediaError("FFmpeg produced no clip.")
        os.replace(partial, target)


def tone_mp3(duration_sec: float, *, frequency: int = 220, volume: float = 0.05) -> bytes:
    """A quiet sine tone as MP3 bytes (mono, 44.1 kHz)."""
    data = run_ffmpeg([
        "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={duration_sec:.3f}",
        "-af", f"volume={volume}", "-ac", "1", "-ar", "44100",
        "-c:a", "libmp3lame", "-b:a", "64k", "-f", "mp3", "pipe:1",
    ])
    if not data:
        raise MediaError("FFmpeg produced no audio.")
    return data


def _text_card(
    width: int, height: int, title: str, text: str, background: tuple[int, int, int]
) -> Image.Image:
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    margin = width // 14
    body_size = width // 26
    title_font = ImageFont.load_default(size=width // 18)
    body_font = ImageFont.load_default(size=body_size)
    draw.rectangle((10, 10, width - 11, height - 11), outline=(148, 163, 184), width=6)
    draw.text((margin, margin), title, fill=(248, 250, 252), font=title_font)
    top = margin + width // 8
    chars_per_line = int((width - 2 * margin) / (body_size * 0.55))
    line_height = body_size + 12
    lines = textwrap.wrap(text, chars_per_line)[: max(1, (height - top - margin) // line_height)]
    draw.multiline_text(
        (margin, top), "\n".join(lines), fill=(226, 232, 240), font=body_font, spacing=12
    )
    return image
