"""Carousel motion and the final slide MP4s (Phase 3 Step 4): local and free.

- Local animation, for slides that animate "local" and for fallbacks: a plugin still gets a slow
  zoom, a soft glow pulse and the app's animated particle wave on top; a slide whose still is the
  app background gets the animated background (the last slide also a pulsing glow behind the
  Like/Share/Save row).
- Render: per slide the plugin clip or the local animation, scaled and cropped to 1080x1080,
  24 fps, exactly 5.0 s (trimmed, or the last frame held), with the static layer on top (the
  text, and on the last slide the icon row and the logo) -> carousel/final/slide_NN.mp4 (H.264,
  yuv420p, CRF 18, faststart, silent) and slide_NN.png (the still with the layer). The raw stills
  stay in carousel/stills/.
- Set check: each final slide's brightness and palette against slide 1 and the dark navy style;
  it only reports.
"""

import colorsys
import json
import math
from collections.abc import Iterator, Sequence
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

from content_automation.core.media import probe_media, run_ffmpeg, write_video
from content_automation.workflows.carousel_design import (
    CarouselDesign,
    CarouselDesignError,
    SlideText,
)
from content_automation.workflows.carousel_plugin import (
    SlideSource,
    carousel_dir,
    render_sources,
)
from content_automation.workflows.carousel_render import Background, icon_row, slide_layer
from content_automation.workflows.design_system import DesignSystem
from content_automation.workflows.logo import LogoOverlay

_BLUE = (180 / 360, 260 / 360)  # hue range of the style's blues
_SET_FILE = "set-check.json"


def _size(design: CarouselDesign) -> tuple[int, int]:
    return design.canvas.width, design.canvas.height


def _frame_count(design: CarouselDesign) -> int:
    return round(design.timing.seconds_per_slide * design.timing.fps)


def _pulse(t: float, design: CarouselDesign) -> float:
    """0 -> 1 -> 0 once per slide, so the animation loops."""
    return 0.5 - 0.5 * math.cos(2 * math.pi * t / design.timing.seconds_per_slide)


def _zoom(image: Image.Image, factor: float) -> Image.Image:
    width, height = image.size
    crop_w, crop_h = width / factor, height / factor
    left, top = (width - crop_w) / 2, (height - crop_h) / 2
    return image.resize(
        image.size, Image.Resampling.BICUBIC, box=(left, top, left + crop_w, top + crop_h)
    )


def _local_frames(
    source: SlideSource, design: CarouselDesign, language: str
) -> Iterator[bytes]:
    size, fps, count = _size(design), design.timing.fps, _frame_count(design)
    motion = design.local_motion
    animator = Background(design)
    if source.plugin_still:
        with Image.open(source.still) as opened:
            still = opened.convert("RGB").resize(size, Image.Resampling.LANCZOS)
        glow = ImageChops.screen(still, still.filter(ImageFilter.GaussianBlur(size[0] * 0.012)))
        for index in range(count):
            t = index / fps
            frame = Image.blend(still, glow, motion.glow_pulse * _pulse(t, design))
            frame = _zoom(frame, 1 + motion.zoom * index / max(1, count - 1))
            wave = animator.wave(t).point(lambda value: round(value * motion.wave_opacity))
            band = frame.crop((0, animator.top, *size))
            frame.paste(ImageChops.screen(band, wave), (0, animator.top))
            yield frame.tobytes()
        return
    halo = None
    if source.type == design.structure[-1]:
        halo = icon_row(design, language).filter(ImageFilter.GaussianBlur(size[0] * 0.012))
    for index in range(count):
        t = index / fps
        frame = animator.frame(t)
        if halo is not None:
            strength = motion.icon_pulse * _pulse(t, design)
            glow_layer = halo.copy()
            alpha = halo.getchannel("A").point(lambda value, k=strength: round(value * k))
            glow_layer.putalpha(alpha)
            frame = Image.alpha_composite(frame.convert("RGBA"), glow_layer).convert("RGB")
        yield frame.tobytes()


def local_animation(
    source: SlideSource, design: CarouselDesign, language: str, target: Path
) -> Path:
    """The app's own 5 s animation of one slide (no text), as an MP4."""
    target.parent.mkdir(parents=True, exist_ok=True)
    write_video(_local_frames(source, design, language), _size(design), design.timing.fps, target)
    return target


def _encode(clip: Path, layer: Path, target: Path, design: CarouselDesign) -> None:
    """1080x1080, 24 fps, exactly 5.0 s (trim, or hold the last frame), the static layer on
    top; H.264 yuv420p, faststart, no audio."""
    width, height = _size(design)
    fps, frames = design.timing.fps, _frame_count(design)
    seconds = design.timing.seconds_per_slide
    graph = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1,fps={fps},"
        f"tpad=stop_mode=clone:stop_duration={seconds:g},trim=end_frame={frames},"
        f"setpts=PTS-STARTPTS[v];[v][1:v]overlay=0:0:format=auto,format=yuv420p[out]"
    )
    run_ffmpeg([
        "-y", "-i", str(clip), "-loop", "1", "-i", str(layer), "-filter_complex", graph,
        "-map", "[out]", "-frames:v", str(frames), "-r", str(fps), "-an",
        "-c:v", "libx264", "-preset", design.render.preset, "-crf", str(design.render.crf),
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(target),
    ])


# --- Set check -------------------------------------------------------------------------------


def _look(path: Path) -> tuple[float, float]:
    """Mean brightness (0-1) and the share of saturated colour outside the blues."""
    with Image.open(path) as opened:
        small = opened.convert("RGB").resize((64, 64))
    data = small.tobytes()
    pixels = [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]
    light = sum(0.2126 * r + 0.7152 * g + 0.0722 * b for r, g, b in pixels) / 255 / len(pixels)
    hues = [
        hue for hue, saturation, value in (
            colorsys.rgb_to_hsv(r / 255, g / 255, b / 255) for r, g, b in pixels
        )
        if saturation > 0.35 and value > 0.2
    ]
    off = sum(not _BLUE[0] <= hue <= _BLUE[1] for hue in hues) / max(1, len(hues))
    return light, off


def set_check(finals: Sequence[Path], design: CarouselDesign, target: Path) -> list[str]:
    """Each final slide against slide 1 and the style; notes only, never a stop."""
    limits = design.set_check
    looks = [_look(path) for path in finals]
    first_light = looks[0][0]
    notes = []
    for number, (light, off) in enumerate(looks, start=1):
        if number > 1 and abs(light - first_light) > limits.max_brightness_diff:
            notes.append(
                f"slide {number}: brightness {light:.2f} vs slide 1 {first_light:.2f}"
            )
        if light > limits.max_brightness:
            notes.append(f"slide {number}: lighter than the dark navy style ({light:.2f})")
        if off > limits.max_off_palette:
            notes.append(f"slide {number}: {off:.0%} of its colour is outside the blue palette")
    report = {
        "slides": [
            {"slide": number, "brightness": round(light, 3), "offPalette": round(off, 3)}
            for number, (light, off) in enumerate(looks, start=1)
        ],
        "notes": notes,
    }
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return notes


# --- Render ----------------------------------------------------------------------------------


def render(
    package: Path,
    design: CarouselDesign,
    system: DesignSystem,
    slides: Sequence[SlideText],
    language: str,
    logo: LogoOverlay | None,
) -> list[str]:
    """`ca carousel render`: carousel/final/slide_NN.mp4 and slide_NN.png for every slide,
    then the set check. Refused while a request is still with Codex."""
    sources = render_sources(package)
    if [source.type for source in sources] != [slide.type for slide in slides]:
        raise CarouselDesignError(
            "brief.json's carousel slides no longer match carousel/carousel.json; render the "
            "carousel the requests were made for."
        )
    folder = carousel_dir(package)
    final, work = folder / "final", folder / "work"
    final.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    size = _size(design)
    lines: list[str] = []
    pictures: list[Path] = []
    for source, slide in zip(sources, slides, strict=True):
        number = source.slide
        with Image.open(source.still) as opened:
            still = opened.convert("RGB").resize(size, Image.Resampling.LANCZOS)
        layer, notes = slide_layer(slide, design, system, still, language, logo)
        layer_file = work / f"layer_{number:02d}.png"
        layer.save(layer_file)
        picture = final / f"slide_{number:02d}.png"
        Image.alpha_composite(still.convert("RGBA"), layer).convert("RGB").save(
            picture, optimize=True
        )
        pictures.append(picture)
        clip = source.clip or local_animation(
            source, design, language, work / f"local_{number:02d}.mp4"
        )
        video = final / f"slide_{number:02d}.mp4"
        _encode(clip, layer_file, video, design)
        seconds = probe_media(video).duration_sec or 0.0
        lines.append(
            f"Slide {number} ({slide.type}): {source.note}; {video.name} {seconds:.2f} s, "
            f"{picture.name}" + (f"; {'; '.join(notes)}" if notes else "")
        )
    notes = set_check(pictures, design, final / _SET_FILE)
    lines.append(
        "Set check: " + ("; ".join(notes) if notes else "every slide matches slide 1 and the style")
        + f" ({final / _SET_FILE})"
    )
    lines.append(f"Final: {final}")
    return lines
