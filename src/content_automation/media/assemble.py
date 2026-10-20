"""Assemble scene clips into final.mp4: 1080×1920 (YouTube: 1920×1080), 30 fps, H.264 + AAC.

Each scene is first normalized on its own (scale + pad to the size, 30 fps, 48 kHz stereo,
silence when the clip has no sound) with its text burned in; the scenes are then joined in
order. An image scene becomes a slow zoom for its duration. Video scenes are cut to their
planned length.

Text is burned in with FFmpeg's drawtext filter and a system font. If this FFmpeg build has
no drawtext or no font is found, the video is made without text; captions.srt (always
written when there is text) then carries it.
"""

import math
import os
import re
import shutil
import tempfile
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from content_automation.core.files import atomic_write_text
from content_automation.core.media import MediaError, has_filter, probe_media, run_ffmpeg

WIDTH, HEIGHT, FPS = 1080, 1920, 30
FINAL_FILE = "final.mp4"
CAPTIONS_FILE = "captions.srt"
ZOOM = 0.08  # image scenes zoom in by 8% over their duration
MAX_CAPTION_CHARS = 56  # about two caption lines
FONT_CANDIDATES = (
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "arialbd.ttf",
    Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "segoeuib.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    Path("/Library/Fonts/Arial Bold.ttf"),
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_STYLE = {  # position -> (font size, characters per line, y position)
    "top": (64, 24, "h*0.10"),
    "bottom": (54, 30, "h*0.72"),
}

SegmentKind = Literal["clip", "image"]
TextPosition = Literal["top", "bottom"]


@dataclass(frozen=True)
class Segment:
    """One scene: a video clip or a still image, with its text."""

    path: Path
    kind: SegmentKind = "clip"
    duration_sec: float | None = None  # clip: cut to this (None = full length); image: length
    on_screen_text: str | None = None  # shown for the whole scene, near the top
    speech: str | None = None  # spoken words, shown as captions near the bottom


@dataclass(frozen=True)
class TextCue:
    start_sec: float
    end_sec: float
    text: str
    position: TextPosition


@dataclass(frozen=True)
class Assembly:
    final: Path
    captions: Path | None
    duration_sec: float
    text_burned_in: bool
    text_note: str


def text_support() -> tuple[Path | None, str]:
    """The font used to burn in text, or None with the reason text cannot be burned in."""
    if not has_filter("drawtext"):
        return None, "this FFmpeg build has no drawtext filter"
    for font in FONT_CANDIDATES:
        if font.is_file():
            return font, f"burned in with drawtext ({font.name})"
    return None, "no usable font file was found"


def caption_cues(speech: str, duration_sec: float) -> list[TextCue]:
    """Split spoken text into sentences (long ones into shorter parts) and give each a
    share of the scene's time in proportion to its length."""
    chunks: list[str] = []
    for sentence in _SENTENCE_END.split(speech.strip()):
        chunks += _split_evenly(sentence.split(), math.ceil(len(sentence) / MAX_CAPTION_CHARS))
    total = sum(len(chunk) for chunk in chunks)
    cues: list[TextCue] = []
    start = 0.0
    for chunk in chunks:
        end = start + duration_sec * len(chunk) / total
        cues.append(TextCue(round(start, 3), round(end, 3), chunk, "bottom"))
        start = end
    return cues


def _split_evenly(words: list[str], pieces: int) -> list[str]:
    """Split words into about `pieces` parts of similar length (no one-word leftovers)."""
    if pieces <= 1:
        return [" ".join(words)] if words else []
    target = len(" ".join(words)) / pieces
    parts: list[str] = []
    current: list[str] = []
    for word in words:
        current.append(word)
        if len(parts) < pieces - 1 and len(" ".join(current)) >= target:
            parts.append(" ".join(current))
            current = []
    if current:
        parts.append(" ".join(current))
    return parts


def _wrap(text: str, width: int) -> str:
    """Wrap into as few lines as `width` allows, with the lines about equally long."""
    lines = len(textwrap.wrap(text, width)) or 1
    for balanced in range(math.ceil(len(text) / lines), width + 1):
        wrapped = textwrap.wrap(text, balanced)
        if len(wrapped) <= lines:
            return "\n".join(wrapped)
    return "\n".join(textwrap.wrap(text, width))


def assemble(
    segments: list[Segment], job_dir: Path, size: tuple[int, int] = (WIDTH, HEIGHT)
) -> Assembly:
    """Build job_dir/final.mp4 at size (width, height), and captions.srt when there is text."""
    if not segments:
        raise MediaError("There are no scenes to assemble.")
    job_dir = job_dir.resolve()  # ffmpeg runs inside the work folder
    font, text_note = text_support()
    cues: list[TextCue] = []
    offset = 0.0
    with tempfile.TemporaryDirectory(
        dir=job_dir, prefix=".assembly-", ignore_cleanup_errors=True
    ) as temporary:
        work = Path(temporary)
        if font is not None:
            shutil.copyfile(font, work / "font.ttf")  # relative path: no filter escaping
        parts: list[str] = []
        for index, segment in enumerate(segments, start=1):
            name, duration, scene_cues = _normalize(segment, index, work, font is not None, size)
            parts.append(name)
            cues += [
                TextCue(c.start_sec + offset, c.end_sec + offset, c.text, c.position)
                for c in scene_cues
            ]
            offset += duration
        (work / "scenes.txt").write_text(
            "".join(f"file '{name}'\n" for name in parts), encoding="utf-8"
        )
        run_ffmpeg([
            "-f", "concat", "-safe", "0", "-i", "scenes.txt",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart",
            "-y", FINAL_FILE,
        ], cwd=work)
        final = job_dir / FINAL_FILE
        os.replace(work / FINAL_FILE, final)

    info = probe_media(final)
    if (info.width, info.height) != size:
        raise MediaError(f"final.mp4 is {info.width}x{info.height}, not {size[0]}x{size[1]}.")
    captions = None
    if cues:
        captions = job_dir / CAPTIONS_FILE
        atomic_write_text(captions, _srt(cues))
    return Assembly(
        final=final,
        captions=captions,
        duration_sec=info.duration_sec or offset,
        text_burned_in=font is not None and bool(cues),
        text_note=text_note,
    )


def _normalize(
    segment: Segment, index: int, work: Path, burn_text: bool, size: tuple[int, int]
) -> tuple[str, float, list[TextCue]]:
    """Encode one scene as work/scene-NN.mkv (H.264 + PCM, so joining adds no gaps)."""
    width, height = size
    inputs = ["-i", str(segment.path.resolve())]
    if segment.kind == "image":
        if not segment.duration_sec:
            raise MediaError(f"Image scene {index} has no duration.")
        duration = segment.duration_sec
        frames = max(1, round(duration * FPS))
        video = (
            f"[0:v]scale={2 * width}:{2 * height}:force_original_aspect_ratio=decrease,"
            f"pad={2 * width}:{2 * height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,"
            f"zoompan=z='1+{ZOOM}*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={width}x{height}:fps={FPS}"
        )
        has_audio = False
    else:
        info = probe_media(segment.path)
        if not info.duration_sec:
            raise MediaError(f"Cannot read the length of {segment.path.name}.")
        duration = info.duration_sec
        if segment.duration_sec:
            duration = min(duration, segment.duration_sec)
        video = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS}"
        )
        has_audio = info.has_audio

    cues: list[TextCue] = []
    if segment.on_screen_text and segment.on_screen_text.strip():
        cues.append(TextCue(0.0, duration, segment.on_screen_text.strip(), "top"))
    if segment.speech and segment.speech.strip():
        cues += caption_cues(segment.speech, duration)
    if burn_text:
        for number, cue in enumerate(cues, start=1):
            video += _drawtext(cue, _text_file(work, index, number, cue))
    graph = f"{video},format=yuv420p[v]"
    if has_audio:
        graph += ";[0:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,apad[a]"
        audio = "[a]"
    else:
        inputs += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
        audio = "1:a"
    name = f"scene-{index:02d}.mkv"
    run_ffmpeg([
        *inputs, "-filter_complex", graph, "-map", "[v]", "-map", audio,
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS),
        "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", "-y", name,
    ], cwd=work)
    return name, duration, cues


def _text_file(work: Path, index: int, number: int, cue: TextCue) -> str:
    """Write the wrapped text to a file; drawtext reads it, so no text escaping is needed."""
    width = _STYLE[cue.position][1]
    name = f"text-{index:02d}-{number:02d}.txt"
    # "\n" only: drawtext would show a Windows "\r\n" as an extra blank line.
    (work / name).write_text(_wrap(cue.text, width), encoding="utf-8", newline="\n")
    return name


def _drawtext(cue: TextCue, text_file: str) -> str:
    size, _, y = _STYLE[cue.position]
    return (
        f",drawtext=fontfile=font.ttf:textfile={text_file}:expansion=none"
        f":fontsize={size}:fontcolor=white:line_spacing=10:text_align=C"
        f":box=1:boxcolor=black@0.55:boxborderw=22"
        f":x=(w-text_w)/2:y={y}:enable='between(t,{cue.start_sec:.3f},{cue.end_sec:.3f})'"
    )


def _srt(cues: list[TextCue]) -> str:
    ordered = sorted(cues, key=lambda cue: (cue.start_sec, cue.position))
    return "\n".join(
        f"{number}\n{_srt_time(cue.start_sec)} --> {_srt_time(cue.end_sec)}\n{cue.text}\n"
        for number, cue in enumerate(ordered, start=1)
    )


def _srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
