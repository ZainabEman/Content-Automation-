"""FFmpeg helpers (bundled by imageio-ffmpeg, no manual install) for clips and audio."""

import functools
import os
import re
import subprocess
import tempfile
import textwrap
from collections.abc import Iterable
from dataclasses import dataclass
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
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_VIDEO = re.compile(r"Stream #[^\n]*Video:[^\n]*?(\d{2,5})x(\d{2,5})")
_FPS = re.compile(r"Stream #[^\n]*Video:[^\n]*?(\d+(?:\.\d+)?) fps")
_AUDIO = re.compile(r"Stream #[^\n]*Audio:")


class MediaError(RuntimeError):
    """FFmpeg failed or produced no output."""


@dataclass(frozen=True)
class MediaInfo:
    duration_sec: float | None
    width: int | None
    height: int | None
    fps: float | None
    has_audio: bool


def run_ffmpeg(
    args: list[str], *, timeout_s: float = _TIMEOUT_S, cwd: Path | None = None
) -> bytes:
    """Run ffmpeg with args; return stdout (used when writing to pipe:1)."""
    command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", *args]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout_s, check=False, cwd=cwd
        )
    except subprocess.TimeoutExpired:
        raise MediaError(f"FFmpeg did not finish within {timeout_s:g} seconds.") from None
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()[-_ERROR_TAIL:]
        raise MediaError(f"FFmpeg failed (exit {result.returncode}): {detail}")
    return result.stdout


def probe_media(path: Path) -> MediaInfo:
    """Read length, size, frame rate and whether there is sound (ffprobe is not bundled)."""
    try:
        result = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False,
        )
    except subprocess.TimeoutExpired:
        raise MediaError(f"FFmpeg could not read {path.name} in time.") from None
    info = result.stderr
    duration = _DURATION.search(info)
    size = _VIDEO.search(info)
    fps = _FPS.search(info)
    seconds = None
    if duration:
        hours, minutes, secs = duration.groups()
        seconds = int(hours) * 3600 + int(minutes) * 60 + float(secs)
    return MediaInfo(
        duration_sec=seconds,
        width=int(size.group(1)) if size else None,
        height=int(size.group(2)) if size else None,
        fps=float(fps.group(1)) if fps else None,
        has_audio=_AUDIO.search(info) is not None,
    )


def gray_frames(path: Path, side: int, fps: float) -> list[bytes]:
    """Square grey frames (centre-cropped, `side` px) sampled at `fps`, for motion checks;
    each frame is side*side bytes."""
    data = run_ffmpeg([
        "-i", str(path), "-an", "-vf",
        f"fps={fps:g},scale={side}:{side}:force_original_aspect_ratio=increase,"
        f"crop={side}:{side}",
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ])
    size = side * side
    return [data[start:start + size] for start in range(0, len(data) - size + 1, size)]


def write_video(
    frames: Iterable[bytes], size: tuple[int, int], fps: int, target: Path, *, crf: int = 10
) -> None:
    """Encode raw RGB frames (width*height*3 bytes each) as a silent H.264 MP4."""
    width, height = size
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}", "-r", str(fps),
        "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf),
        "-pix_fmt", "yuv420p", str(target),
    ]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert process.stdin is not None and process.stderr is not None
    try:
        for frame in frames:
            process.stdin.write(frame)
        process.stdin.close()
        detail = process.stderr.read().decode("utf-8", "replace").strip()[-_ERROR_TAIL:]
        code = process.wait(timeout=_TIMEOUT_S)
    except (BrokenPipeError, subprocess.TimeoutExpired) as error:
        process.kill()
        raise MediaError(f"FFmpeg could not encode {target.name}: {error}") from None
    if code != 0 or not target.is_file():
        raise MediaError(f"FFmpeg failed (exit {code}) on {target.name}: {detail}")


@functools.cache
def has_filter(name: str) -> bool:
    """Whether this ffmpeg build includes the named filter (e.g. drawtext)."""
    try:
        listing = run_ffmpeg(["-filters"]).decode("utf-8", "replace")
    except MediaError:
        return False
    return any(line.split()[1:2] == [name] for line in listing.splitlines())


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
