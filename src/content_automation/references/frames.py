"""Extract still frames from reference videos so they can be used as style references.

Frames go to <set>/_frames/<video>_<n>.jpg; scan() treats them as assets of that set.
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import imageio_ffmpeg

from content_automation.references.models import FRAMES_DIR, RESIZED_DIR

FRAME_POSITIONS = (0.10, 0.50, 0.90)
FRAME_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".webm"})
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_TIMEOUT_S = 120


@dataclass
class FramesReport:
    extracted: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def frame_paths(video: Path) -> list[Path]:
    return [
        video.parent / FRAMES_DIR / f"{video.stem}_{index}.jpg"
        for index in range(1, len(FRAME_POSITIONS) + 1)
    ]


def find_videos(root: Path) -> list[Path]:
    videos: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames if d not in (RESIZED_DIR, FRAMES_DIR) and not d.startswith(".")
        ]
        videos.extend(
            Path(dirpath) / name
            for name in filenames
            if Path(name).suffix.lower() in FRAME_SUFFIXES and not name.startswith(".")
        )
    return sorted(videos)


def video_duration(video: Path) -> float:
    """Read the duration from ffmpeg's header output (no full decode)."""
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(video)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=_TIMEOUT_S,
        check=False,
    )
    match = _DURATION.search(result.stderr)
    if match is None:
        raise ValueError("could not read the video duration")
    hours, minutes, seconds = match.groups()
    duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    if duration <= 0:
        raise ValueError("video has no duration")
    return duration


def _extract_frame(video: Path, seconds: float, target: Path) -> None:
    temporary = target.with_name(f".{target.stem}.tmp.jpg")
    try:
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
                "-ss", f"{seconds:.3f}", "-i", str(video),
                "-frames:v", "1", "-q:v", "2", "-y", str(temporary),
            ],
            capture_output=True,
            timeout=_TIMEOUT_S,
            check=True,
        )
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise ValueError(f"no frame at {seconds:.2f}s")
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def extract_frames(root: Path) -> FramesReport:
    """Extract frames at 10%, 50% and 90% of every video; skip videos already done."""
    report = FramesReport()
    for video in find_videos(root):
        label = video.relative_to(root).as_posix()
        targets = frame_paths(video)
        if all(target.is_file() for target in targets):
            report.skipped.append(label)
            continue
        try:
            duration = video_duration(video)
            targets[0].parent.mkdir(exist_ok=True)
            for position, target in zip(FRAME_POSITIONS, targets, strict=True):
                if not target.is_file():
                    _extract_frame(video, duration * position, target)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            report.failed.append((label, str(error) or type(error).__name__))
            continue
        report.extracted.append(label)
    return report
