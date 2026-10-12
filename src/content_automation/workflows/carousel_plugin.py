"""Carousel requests for the Higgsfield Codex plugin: slide stills (Phase 3 Step 3) and the
image-to-video clips made from them (Step 4).

The app calls no plugin. After the user's single "ok" the build writes, per slide that needs
one, <package>/carousel/requests/still_NN.json (text-free prompt, negative terms, size, style
frames to attach only if the image tool takes reference images, output stills/still_NN.png).
Slide types marked "local" get the app-drawn background as their still and no request.

Codex runs every request without asking again, saves each result and records each attempt with
`ca carousel record` (credits used, or the error). `ca carousel stills-check` checks the stills
(exists, 1:1, not blank, a calm left half); when all are settled it writes
requests/clip_NN.json for each slide whose type animates with "higgsfield" and whose still came
from the plugin (image-to-video, 5 s, output clips/clip_NN.mp4). `ca carousel clips-check`
checks the clips (decodes, long enough, moves, calm left half). Slides without a clip get the
app's own animation at `ca carousel render`.

Every request gets at most `attempts` (2) tries in total, whether the plugin failed or the check
did: a failed one is asked for once more inside the approved max, then it falls back to the
local background (stills) or the local animation (clips). carousel/carousel.json keeps the
approved max (stills and clips with every retry); the spend is the credits recorded in the
request files.
"""

import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import pstdev
from typing import Literal

from PIL import Image, ImageFilter, UnidentifiedImageError
from pydantic import ConfigDict, Field

from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.core.media import MediaError, gray_frames, probe_media
from content_automation.workflows.carousel_design import (
    CarouselDesign,
    CarouselDesignError,
    ClipSource,
    SlideText,
    SlideType,
    StillSource,
    StillsProvider,
    clip_prompt,
    still_prompt,
)
from content_automation.workflows.carousel_render import background, style_frames
from content_automation.workflows.design_system import Box

CAROUSEL_DIR = "carousel"
PLAN_FILE = "carousel.json"
PLUGIN = "Higgsfield"
DECISION_DOC = "docs/PHASE3-DECISION.md"
TOOLS_SECTION = "section 10"
Kind = Literal["still", "clip"]
RequestStatus = Literal["pending", "made", "failed", "passed", "fallback"]
_FRAME_SIDE, _FRAME_RATE = 180, 4  # clips-check samples grey frames like the calibration
_OUTPUT = {"still": ("stills", "png"), "clip": ("clips", "mp4")}


def _now() -> datetime:
    return datetime.now().astimezone()


class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


class Attempt(_Model):
    at: datetime = Field(default_factory=_now)
    status: Literal["made", "failed"]
    credits: float | None = None  # what the plugin reported for this attempt
    provider_job_id: str | None = None
    error: str | None = None


class Check(_Model):
    passed: bool
    reason: str
    metrics: dict[str, float] = Field(default_factory=dict)
    checked_at: datetime = Field(default_factory=_now)


class PluginRequest(_Model):
    """carousel/requests/still_NN.json or clip_NN.json: what Codex sends to the plugin, and
    what came back."""

    step_id: str
    slide: int
    type: SlideType
    capability: Literal["image", "video"]
    plugin: str = PLUGIN
    tool: str  # where the tool and model names are (found at run time until then)
    model: str
    prompt: str
    negative_prompt: str
    width: int
    height: int
    aspect_ratio: str
    size_rule: str
    reference_images: str = "no"  # stills: unknown | yes | no
    style_references: list[str] = Field(default_factory=list)  # stills: absolute paths
    start_image_path: str | None = None  # clips: the still to animate (absolute)
    duration_sec: float | None = None  # clips
    output_path: str  # absolute
    estimated_credits: float
    max_attempts: int
    status: RequestStatus = "pending"
    attempts: list[Attempt] = Field(default_factory=list)
    credits_used: float = 0.0
    retry_note: str | None = None  # why it is asked for again (already in the prompt)
    check: Check | None = None
    instructions: list[str] = Field(default_factory=list)


class PlanSlide(_Model):
    slide: int
    type: SlideType
    source: StillSource
    still: str  # relative to the package folder
    request: str | None = None  # the still request (relative); None for a local still
    motion: ClipSource = "higgsfield"
    clip_request: str | None = None  # written by stills-check for a plugin still


class CarouselPlan(_Model):
    """carousel/carousel.json: written once, after the "ok"."""

    topic: str
    provider: StillsProvider
    created_at: datetime = Field(default_factory=_now)
    still_estimate: float = 0.0  # every plugin still once
    clip_estimate: float = 0.0  # every planned clip once
    estimated_credits: float  # both
    approved_max_credits: float  # both, with every retry: what the "ok" approved
    usd_per_credit: float | None = None
    slides: list[PlanSlide]


# --- Paths and files -------------------------------------------------------------------------


def carousel_dir(package: Path) -> Path:
    return package / CAROUSEL_DIR


def plan_path(package: Path) -> Path:
    return carousel_dir(package) / PLAN_FILE


def _step(kind: Kind, slide: int) -> str:
    return f"{kind}_{slide:02d}"


def _request_file(package: Path, kind: Kind, slide: int) -> Path:
    return carousel_dir(package) / "requests" / f"{_step(kind, slide)}.json"


def output_file(package: Path, kind: Kind, slide: int) -> Path:
    folder, suffix = _OUTPUT[kind]
    return carousel_dir(package) / folder / f"{_step(kind, slide)}.{suffix}"


def _save(path: Path, model: CamelModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, model.model_dump_json(by_alias=True, indent=2) + "\n")


def load_plan(package: Path) -> CarouselPlan | None:
    path = plan_path(package)
    if not path.is_file():
        return None
    return CarouselPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _need_plan(package: Path) -> CarouselPlan:
    plan = load_plan(package)
    if plan is None:
        raise CarouselDesignError(
            f"No carousel requests in {package}: run the build after the \"ok\" first."
        )
    return plan


def load_request(package: Path, kind: Kind, slide: int) -> PluginRequest:
    path = _request_file(package, kind, slide)
    if not path.is_file():
        raise CarouselDesignError(
            f"No {kind} request for slide {slide} in {path.parent} (a local slide has none)."
        )
    return PluginRequest.model_validate_json(path.read_text(encoding="utf-8"))


def _requests(package: Path, plan: CarouselPlan, kind: Kind | None = None) -> list[PluginRequest]:
    found = []
    for item in plan.slides:
        if item.request and kind in (None, "still"):
            found.append(load_request(package, "still", item.slide))
        if item.clip_request and kind in (None, "clip"):
            found.append(load_request(package, "clip", item.slide))
    return found


def _spent(requests: Sequence[PluginRequest]) -> float:
    return sum(request.credits_used for request in requests)


def _credits(value: float, design: CarouselDesign) -> str:
    usd = design.stills.usd_per_credit
    return f"{value:g} credits" + (f" (≈ ${value * usd:.2f})" if usd else "")


# --- Dry run ---------------------------------------------------------------------------------


def _provider_problem(design: CarouselDesign) -> str | None:
    if design.stills.provider == "comfyui":
        return (
            "stills.provider comfyui is a stub until RunPod has credit; set it to higgsfield in "
            "config/carousel_design.json"
        )
    return None


def _planned(design: CarouselDesign, slide_type: SlideType) -> tuple[bool, bool]:
    """Whether the type gets a plugin still and a plugin clip (before any fallback)."""
    spec = design.slide_types[slide_type]
    still = spec.still == "plugin"
    return still, still and spec.clip == "higgsfield"


def credits_dry_run(
    package: Path, slides: Sequence[SlideText], design: CarouselDesign
) -> list[str]:
    """Per slide: the still and the clip (estimated credits) or the free local version; the
    totals and the max with one retry per request."""
    if load_plan(package) is not None:
        return status_lines(package, design)
    problem = _provider_problem(design)
    if problem:
        return [f"  stills: {problem}"]
    stills, clips = design.stills, design.clips
    lines = [
        f"  via the {PLUGIN} plugin (plan credits; image {stills.model or 'default model'}, "
        f"reference images {stills.reference_images}; video {clips.model or 'default model'}):"
    ]
    still_count = clip_count = 0
    for number, slide in enumerate(slides, start=1):
        still, clip = _planned(design, slide.type)
        still_count += still
        clip_count += clip
        parts = [
            f"still about {stills.estimated_credits:g} credits" if still
            else "local background (free)",
            f"clip {clips.seconds:g} s about {clips.estimated_credits:g} credits" if clip
            else "local animation (free)",
        ]
        lines.append(f"    slide {number} {slide.type}: {'; '.join(parts)} (estimate)")
    still_total = still_count * stills.estimated_credits
    clip_total = clip_count * clips.estimated_credits
    total = still_total + clip_total
    most = still_total * stills.attempts + clip_total * clips.attempts
    lines += [
        f"  credits: stills {still_count} x {stills.estimated_credits:g} + clips {clip_count} x "
        f"{clips.estimated_credits:g} = about {_credits(total, design)} (estimate); max with "
        f"one retry per request: {_credits(most, design)}",
        f"  estimates: stills {stills.estimate_note or 'from config'}; clips "
        f"{clips.estimate_note or 'from config'}",
        f'  after "ok": stills, then clips, run by the make-carousel skill without asking again; '
        f'then uv run ca carousel render "{package}"',
    ]
    return lines


# --- Still requests --------------------------------------------------------------------------


def _instructions(package: Path, request: PluginRequest, kind: Kind) -> list[str]:
    record = f'uv run ca carousel record "{package}" --{kind} {request.slide}'
    if kind == "still":
        tool = "image tool"
        inputs = (
            "prompt; negativePrompt (as the negative field, or append \"Avoid: ...\" to the "
            "prompt); 1:1 at 1080x1080 or the closest size the tool offers (ca crops and "
            "resizes); model; styleReferences only if the tool accepts reference images."
        )
        check = "stills-check"
    else:
        tool = "image-to-video tool"
        inputs = (
            f"startImagePath as the start image (upload it if the tool needs a URL); prompt; "
            f"negativePrompt (or \"Avoid: ...\"); {request.duration_sec:g} s; 1:1 or the "
            "nearest aspect the tool offers (ca crops); model; no audio."
        )
        check = "clips-check"
    return [
        f"1. Use the {PLUGIN} plugin's {tool} and model named in {DECISION_DOC} "
        f"{TOOLS_SECTION}; first run: list the plugin's tools there first. Never assume a "
        f"name. If the plugin is missing, stop and say so.",
        "2. No question to the user: this runs under the carousel's single \"ok\".",
        f"3. Inputs: {inputs}",
        f"4. Save the result to {request.output_path}.",
        f"5. Record it: {record} --credits <credits used> --provider-job-id <job ID>",
        f'6. If it fails: {record} --error "<reason>" [--credits <charged>]; retry once only '
        "if the record says a retry is left.",
        f'7. After every {kind} request: uv run ca carousel {check} "{package}"',
    ]


def write_still_requests(
    package: Path, topic: str, slides: Sequence[SlideText], design: CarouselDesign
) -> list[str]:
    """After the "ok": one request per plugin still, the local stills, carousel.json (whose
    max also covers the clips)."""
    problem = _provider_problem(design)
    if problem:
        raise CarouselDesignError(problem)
    if load_plan(package) is not None:
        return status_lines(package, design)
    stills, clips = design.stills, design.clips
    entries: list[PlanSlide] = []
    still_count = clip_count = 0
    for number, slide in enumerate(slides, start=1):
        still = output_file(package, "still", number)
        plugin_still, plugin_clip = _planned(design, slide.type)
        clip_count += plugin_clip
        entry = PlanSlide(
            slide=number, type=slide.type, source="plugin" if plugin_still else "local",
            still=still.relative_to(package).as_posix(),
            motion="higgsfield" if plugin_clip else "local",
        )
        entries.append(entry)
        if not plugin_still:
            still.parent.mkdir(parents=True, exist_ok=True)
            background(design).save(still, optimize=True)
            continue
        still_count += 1
        references = [] if stills.reference_images == "no" else [
            str(path.resolve())
            for path in style_frames(design, slide.type)[: stills.style_references]
        ]
        request = PluginRequest(
            step_id=_step("still", number),
            slide=number,
            type=slide.type,
            capability="image",
            tool=f"the image tool in {DECISION_DOC} {TOOLS_SECTION}",
            model=stills.model or "the tool's default image model",
            prompt=still_prompt(design, slide, topic),
            negative_prompt=stills.negative_prompt,
            width=design.canvas.width,
            height=design.canvas.height,
            aspect_ratio="1:1",
            size_rule="1080x1080, or the closest size the tool offers; ca crops and resizes",
            reference_images=stills.reference_images,
            style_references=references,
            output_path=str(still.resolve()),
            estimated_credits=stills.estimated_credits,
            max_attempts=stills.attempts,
        )
        request.instructions = _instructions(package.resolve(), request, "still")
        path = _request_file(package, "still", number)
        _save(path, request)
        entry.request = path.relative_to(package).as_posix()
    still_total = still_count * stills.estimated_credits
    clip_total = clip_count * clips.estimated_credits
    plan = CarouselPlan(
        topic=topic,
        provider=stills.provider,
        still_estimate=still_total,
        clip_estimate=clip_total,
        estimated_credits=still_total + clip_total,
        approved_max_credits=still_total * stills.attempts + clip_total * clips.attempts,
        usd_per_credit=stills.usd_per_credit,
        slides=entries,
    )
    _save(plan_path(package), plan)
    cap = _credits(plan.approved_max_credits, design)
    return [
        f"Carousel stills: {still_count} requests for the {PLUGIN} plugin in "
        f"{carousel_dir(package) / 'requests'} (approved max for stills and clips {cap}); "
        f"{len(entries) - still_count} local still(s) written.",
        "Codex: make-carousel skill: run every request without asking again, record each with "
        f'uv run ca carousel record, then uv run ca carousel stills-check "{package}".',
    ]


# --- Recording an attempt --------------------------------------------------------------------


def record_attempt(
    package: Path,
    kind: Kind,
    slide: int,
    design: CarouselDesign,
    *,
    credits: float | None = None,
    provider_job_id: str | None = None,
    file: Path | None = None,
    error: str | None = None,
) -> list[str]:
    """`ca carousel record`: one plugin attempt (the file, or the error) and its credits."""
    plan = _need_plan(package)
    request = load_request(package, kind, slide)
    if request.status in ("passed", "fallback"):
        raise CarouselDesignError(f"{request.step_id} is final ({request.status}); not recorded.")
    if len(request.attempts) >= request.max_attempts:
        raise CarouselDesignError(
            f"{request.step_id} already has {len(request.attempts)} attempts (the most); the "
            f"{kind}s check gives it the local version."
        )
    target = Path(request.output_path)
    if error is None:
        source = file or target
        if not source.is_file() or source.stat().st_size == 0:
            raise CarouselDesignError(f"File not found or empty: {source}.")
        if source.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    request.attempts.append(Attempt(
        status="failed" if error else "made", credits=credits,
        provider_job_id=provider_job_id, error=error,
    ))
    request.status = "failed" if error else "made"
    request.credits_used += credits or 0.0
    request.check = None
    _save(_request_file(package, kind, slide), request)
    requests = _requests(package, plan)
    spent, cap = _spent(requests), plan.approved_max_credits
    shown = f"{credits:g} credits" if credits is not None else "credits not reported"
    lines = [
        f"{request.step_id}: {request.status} ({shown}). Spent {_credits(spent, design)} of "
        f"the approved max {_credits(cap, design)}."
    ]
    left = request.max_attempts - len(request.attempts)
    if error and left and spent + request.estimated_credits <= cap:
        lines.append(f"Retry {request.step_id} once now (no question).")
    elif error:
        lines.append(
            f"No retry for {request.step_id}: the {kind}s check gives it the local version."
        )
    pending = [item for item in requests if item.status == "pending"]
    if pending and spent + sum(item.estimated_credits for item in pending) > cap:
        lines.append(
            "STOP: the pending requests could go over the approved max; ask the user before "
            "making more."
        )
    return lines


# --- Checks: shared --------------------------------------------------------------------------


def _settle(
    request: PluginRequest, result: Check, spent: float, cap: float, again_note: str
) -> tuple[RequestStatus, str, float]:
    """Passed; asked for once more (inside the max); or fallback. Returns the new status, the
    line ending and the credits reserved for a re-request."""
    request.check = result
    if result.passed:
        request.status = "passed"
        return "passed", f"passed ({result.reason})", 0.0
    if len(request.attempts) < request.max_attempts and spent + request.estimated_credits <= cap:
        request.status = "pending"
        request.retry_note = (
            f"The previous result failed the check ({result.reason}). {again_note}"
        )
        request.prompt = f"{request.prompt} {request.retry_note}"
        ending = f"failed ({result.reason}); asked for once more"
        return "pending", ending, request.estimated_credits
    why = "no attempt left" if len(request.attempts) >= request.max_attempts else (
        "the approved max would be exceeded"
    )
    request.status = "fallback"
    request.retry_note = f"{result.reason}; {why}"
    return "fallback", f"failed ({result.reason}); {why}: local version", 0.0


def _reject(path: Path) -> None:
    """Keep a failed result beside the folder's output, in rejected/."""
    if path.is_file():
        rejected = path.parent / "rejected"
        rejected.mkdir(exist_ok=True)
        shutil.move(path, rejected / path.name)


def _missing(request: PluginRequest) -> Check:
    last = request.attempts[-1].error if request.attempts else None
    return Check(passed=False, reason=f"missing (plugin error: {last})" if last else "missing")


# --- Still check -----------------------------------------------------------------------------


def _crop_box(size: tuple[int, int], box: Box) -> tuple[int, int, int, int]:
    width, height = size
    return (round(box[0] * width), round(box[1] * height), round(box[2] * width),
            round(box[3] * height))


def _metrics(image: Image.Image, box: Box) -> tuple[float, float, float]:
    """Edge share, brightness spread (0-255) and 95th-percentile brightness (0-1)."""
    region = image.convert("L").crop(_crop_box(image.size, box))
    region = region.resize((256, max(1, round(256 * region.height / region.width))))
    edges = region.filter(ImageFilter.FIND_EDGES).tobytes()  # one byte per pixel (L)
    pixels = sorted(region.tobytes())
    return (
        sum(value > 32 for value in edges) / len(edges),
        pstdev(pixels),
        pixels[int(len(pixels) * 0.95)] / 255,
    )


def _normalize(path: Path, design: CarouselDesign) -> tuple[Image.Image | None, str]:
    """Open the still, centre-crop it to 1:1 and resize it to the canvas (kept as PNG); the
    original goes to stills/originals/. Returns the image, or None and the reason."""
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
            kind = (source.format or "png").lower()
    except (OSError, UnidentifiedImageError):
        return None, "not a readable image"
    size = (design.canvas.width, design.canvas.height)
    if image.size == size and kind == "png":
        return image, ""
    width, height = image.size
    if abs(width / height - 1) > design.stills.check.max_aspect_change:
        return None, f"wrong shape {width}x{height} (1:1 wanted; too far off to crop)"
    side = min(width, height)
    left, top = (width - side) // 2, (height - side) // 2
    fixed = image.crop((left, top, left + side, top + side)).resize(
        size, Image.Resampling.LANCZOS
    )
    originals = path.parent / "originals"
    originals.mkdir(exist_ok=True)
    shutil.copyfile(path, originals / f"{path.stem}.{kind}")
    fixed.save(path, format="PNG", optimize=True)
    return fixed, f"cropped and resized from {width}x{height}"


def check_still(path: Path, design: CarouselDesign) -> Check:
    """Exists, 1:1 at the canvas size (after crop/resize), not blank, calm text panel."""
    if not path.is_file() or path.stat().st_size == 0:
        return Check(passed=False, reason="missing")
    image, note = _normalize(path, design)
    if image is None:
        return Check(passed=False, reason=note)
    limits = design.stills.check
    edges, spread, bright = _metrics(image, design.text_panel)
    _, art_spread, _ = _metrics(image, design.illustration_area)
    metrics = {
        "textEdgeShare": round(edges, 4), "textStdDev": round(spread, 1),
        "textBrightness": round(bright, 3), "illustrationStdDev": round(art_spread, 1),
    }
    problems = []
    if art_spread < limits.min_std_dev:
        problems.append("blank (no illustration)")
    if edges > limits.max_edge_share:
        problems.append(f"busy text area (edges {edges:.3f} > {limits.max_edge_share:g})")
    if spread > limits.max_std_dev:
        problems.append(f"high contrast in the text area ({spread:.0f} > {limits.max_std_dev:g})")
    if bright > limits.max_brightness:
        problems.append(f"bright text area ({bright:.2f} > {limits.max_brightness:g})")
    reason = "; ".join(problems) or "ok"
    if note:
        reason += f" ({note})"
    return Check(passed=not problems, reason=reason, metrics=metrics)


_STILL_AGAIN = (
    "Keep the left half of the frame completely calm, dark and empty (no objects, lines, glow "
    "or letters there); put the subject only in the right half."
)
_CLIP_AGAIN = (
    "Only the illustration in the right half may move, gently and visibly; the left half stays "
    "dark and still; the camera does not move."
)


def stills_check(package: Path, design: CarouselDesign) -> list[str]:
    """`ca carousel stills-check`: check every still; one re-request inside the max, then the
    local background. When every still is settled, write the clip requests."""
    plan = _need_plan(package)
    requests = {request.slide: request for request in _requests(package, plan, "still")}
    spent = _spent(_requests(package, plan))
    cap = plan.approved_max_credits
    lines: list[str] = []
    again: list[str] = []
    counts = {"plugin": 0, "local": 0, "fallback": 0}
    for item in plan.slides:
        still = package / item.still
        where = f"Slide {item.slide} ({item.type})"
        request = requests.get(item.slide)
        if request is None:
            if not still.is_file():
                still.parent.mkdir(parents=True, exist_ok=True)
                background(design).save(still, optimize=True)
            counts["local"] += 1
            lines.append(f"{where}: local background")
            continue
        if request.status == "fallback":
            counts["fallback"] += 1
            lines.append(f"{where}: local background (fallback: {request.retry_note or ''})")
            continue
        if request.status == "pending":
            again.append(request.step_id)
            lines.append(f"{where}: pending (no attempt recorded yet)")
            continue
        result = check_still(still, design) if still.is_file() else _missing(request)
        state, ending, reserved = _settle(request, result, spent, cap, _STILL_AGAIN)
        spent += reserved
        if state == "pending":
            again.append(request.step_id)
        elif state == "passed":
            counts["plugin"] += 1
        else:
            _reject(still)
            background(design).save(still, optimize=True)
            counts["fallback"] += 1
        lines.append(f"{where}: {ending}")
        _save(_request_file(package, "still", item.slide), request)
    lines.append(_spend_line(package, plan))
    if again:
        lines.append(_next_line(again, package, "stills-check"))
        return lines
    lines.append(
        f"All {len(plan.slides)} stills ready: {counts['plugin']} from the plugin, "
        f"{counts['local']} local, {counts['fallback']} local fallback."
    )
    return lines + _write_clip_requests(package, plan, design)


# --- Clip requests and check -----------------------------------------------------------------


def _write_clip_requests(package: Path, plan: CarouselPlan, design: CarouselDesign) -> list[str]:
    """One image-to-video request per slide that animates with the plugin and whose still came
    from the plugin; written once."""
    clips = design.clips
    written: list[str] = []
    for item in plan.slides:
        if item.motion != "higgsfield" or item.clip_request or not item.request:
            continue
        still = load_request(package, "still", item.slide)
        if still.status != "passed":
            continue  # a fallback still gets the local animation
        clip = output_file(package, "clip", item.slide)
        request = PluginRequest(
            step_id=_step("clip", item.slide),
            slide=item.slide,
            type=item.type,
            capability="video",
            tool=f"the image-to-video tool in {DECISION_DOC} {TOOLS_SECTION}",
            model=clips.model or "the tool's default video model",
            prompt=clip_prompt(design, item.type),
            negative_prompt=clips.negative_prompt,
            width=design.canvas.width,
            height=design.canvas.height,
            aspect_ratio="1:1",
            size_rule="1:1 at 1080x1080, or the nearest aspect the tool offers; ca crops",
            start_image_path=str((package / item.still).resolve()),
            duration_sec=clips.seconds,
            output_path=str(clip.resolve()),
            estimated_credits=clips.estimated_credits,
            max_attempts=clips.attempts,
        )
        request.instructions = _instructions(package.resolve(), request, "clip")
        path = _request_file(package, "clip", item.slide)
        _save(path, request)
        item.clip_request = path.relative_to(package).as_posix()
        written.append(request.step_id)
    if not written:
        if any(item.clip_request for item in plan.slides):
            return [f'Clips requested earlier: uv run ca carousel clips-check "{package}"']
        return [f'No clips to make (all local). Next: uv run ca carousel render "{package}"']
    _save(plan_path(package), plan)
    requests = _requests(package, plan)
    spent = _spent(requests)
    pending = sum(item.estimated_credits for item in requests if item.status == "pending")
    lines = [
        f"Clip requests: {', '.join(written)} ({len(written)} x about "
        f"{clips.estimated_credits:g} credits, estimate)."
    ]
    if spent + pending > plan.approved_max_credits:
        lines.append(
            f"STOP: the clips could go over the approved max (spent {spent:g}, clips about "
            f"{pending:g}, max {plan.approved_max_credits:g}); ask the user before making them."
        )
    else:
        lines.append(_next_line(written, package, "clips-check"))
    return lines


def _region(frame: bytes, box: Box) -> list[int]:
    left, top, right, bottom = (round(share * _FRAME_SIDE) for share in box)
    return [
        value
        for row in range(top, bottom)
        for value in frame[row * _FRAME_SIDE + left: row * _FRAME_SIDE + right]
    ]


def _motion(frames: Sequence[bytes], box: Box) -> tuple[float, float]:
    """Mean change between frames (0-255) and the range of the mean brightness."""
    regions = [_region(frame, box) for frame in frames]
    changes = [
        sum(abs(a - b) for a, b in zip(first, second, strict=True)) / len(first)
        for first, second in zip(regions, regions[1:], strict=False)
    ]
    means = [sum(region) / len(region) for region in regions]
    return sum(changes) / len(changes), max(means) - min(means)


def check_clip(path: Path, design: CarouselDesign) -> Check:
    """Decodes, long enough, near 1:1 (render crops), moves, calm text panel."""
    if not path.is_file() or path.stat().st_size == 0:
        return Check(passed=False, reason="missing")
    limits = design.clips.check
    try:
        info = probe_media(path)
        frames = gray_frames(path, _FRAME_SIDE, _FRAME_RATE)
    except MediaError as error:
        return Check(passed=False, reason=f"does not decode ({error})")
    if info.duration_sec is None or not info.width or not info.height or len(frames) < 3:
        return Check(passed=False, reason="does not decode (no video frames)")
    if info.duration_sec < limits.min_seconds:
        return Check(
            passed=False, reason=f"too short ({info.duration_sec:.2f} s < {limits.min_seconds:g})"
        )
    if abs(info.width / info.height - 1) > limits.max_aspect_change:
        return Check(passed=False, reason=f"wrong shape {info.width}x{info.height}")
    art, _ = _motion(frames, design.illustration_area)
    text, text_light = _motion(frames, design.text_panel)
    metrics = {
        "seconds": round(info.duration_sec, 2), "illustrationMotion": round(art, 2),
        "textMotion": round(text, 2), "textBrightnessChange": round(text_light, 2),
    }
    problems = []
    if art < limits.min_motion:
        problems.append(f"frozen (motion {art:.2f} < {limits.min_motion:g})")
    if text > limits.max_text_motion:
        problems.append(f"the text area moves ({text:.2f} > {limits.max_text_motion:g})")
    if text_light > limits.max_text_brightness_change:
        problems.append(
            f"the text area flickers ({text_light:.1f} > {limits.max_text_brightness_change:g})"
        )
    return Check(passed=not problems, reason="; ".join(problems) or "ok", metrics=metrics)


def clips_check(package: Path, design: CarouselDesign) -> list[str]:
    """`ca carousel clips-check`: check every clip; one re-request inside the max, then the
    local animation."""
    plan = _need_plan(package)
    if not any(item.clip_request for item in plan.slides):
        raise CarouselDesignError(
            f'No clip requests yet: run uv run ca carousel stills-check "{package}" first.'
        )
    spent = _spent(_requests(package, plan))
    cap = plan.approved_max_credits
    lines: list[str] = []
    again: list[str] = []
    made = local = 0
    for item in plan.slides:
        where = f"Slide {item.slide} ({item.type})"
        if not item.clip_request:
            local += 1
            lines.append(f"{where}: local animation")
            continue
        request = load_request(package, "clip", item.slide)
        clip = Path(request.output_path)
        if request.status == "fallback":
            local += 1
            lines.append(f"{where}: local animation (fallback: {request.retry_note or ''})")
            continue
        if request.status == "pending":
            again.append(request.step_id)
            lines.append(f"{where}: pending (no attempt recorded yet)")
            continue
        result = check_clip(clip, design) if clip.is_file() else _missing(request)
        state, ending, reserved = _settle(request, result, spent, cap, _CLIP_AGAIN)
        spent += reserved
        if state == "pending":
            again.append(request.step_id)
        elif state == "passed":
            made += 1
        else:
            _reject(clip)
            local += 1
        lines.append(f"{where}: {ending}")
        _save(_request_file(package, "clip", item.slide), request)
    lines.append(_spend_line(package, plan))
    if again:
        lines.append(_next_line(again, package, "clips-check"))
    else:
        lines.append(
            f"All clips settled: {made} from the plugin, {local} local animation. Next: "
            f'uv run ca carousel render "{package}"'
        )
    return lines


# --- Render input and status -----------------------------------------------------------------


@dataclass(frozen=True)
class SlideSource:
    slide: int
    type: SlideType
    still: Path
    clip: Path | None  # a passed plugin clip; None = the local animation
    plugin_still: bool  # the still came from the plugin (zoom it); else the app background
    note: str  # how the picture was made, for the summary


def render_sources(package: Path) -> list[SlideSource]:
    """What `ca carousel render` uses per slide; CarouselDesignError while anything is still
    with Codex."""
    plan = _need_plan(package)
    waiting = [
        request.step_id for request in _requests(package, plan)
        if request.status not in ("passed", "fallback")
    ]
    if waiting:
        raise CarouselDesignError(
            f"Not ready to render: {', '.join(waiting)} still with Codex or not checked "
            "(run stills-check / clips-check)."
        )
    if any(item.motion == "higgsfield" and item.request and not item.clip_request
           and load_request(package, "still", item.slide).status == "passed"
           for item in plan.slides):
        raise CarouselDesignError(
            f'Clip requests are not written yet: run uv run ca carousel stills-check "{package}".'
        )
    found = []
    for item in plan.slides:
        still = load_request(package, "still", item.slide) if item.request else None
        clip = load_request(package, "clip", item.slide) if item.clip_request else None
        plugin_still = still is not None and still.status == "passed"
        if clip is not None and clip.status == "passed":
            path, note = Path(clip.output_path), "plugin clip"
        elif clip is not None:
            path, note = None, "local animation (clip fallback)"
        elif still is not None and not plugin_still:
            path, note = None, "local animation (still fallback)"
        else:
            path, note = None, "local animation"
        found.append(SlideSource(
            slide=item.slide, type=item.type, still=package / item.still, clip=path,
            plugin_still=plugin_still, note=note,
        ))
    return found


def _spend_line(package: Path, plan: CarouselPlan) -> str:
    return (
        f"Credits: {_spent(_requests(package, plan)):g} spent of the approved max "
        f"{plan.approved_max_credits:g} (estimate {plan.estimated_credits:g})."
    )


def _next_line(steps: Sequence[str], package: Path, check: str) -> str:
    kind = "clip" if check == "clips-check" else "still"
    return (
        f"Next (no question): run the {PLUGIN} plugin for {', '.join(steps)}, record each with "
        f"uv run ca carousel record --{kind} N, then uv run ca carousel {check} \"{package}\"."
    )


def status_lines(package: Path, design: CarouselDesign) -> list[str]:
    """The state of requests written earlier (dry run and build print it)."""
    plan = load_plan(package)
    if plan is None:
        return []
    requests = _requests(package, plan)
    states: dict[str, int] = {}
    for request in requests:
        key = f"{request.step_id.split('_')[0]} {request.status}"
        states[key] = states.get(key, 0) + 1
    shown = ", ".join(f"{count} {state}" for state, count in sorted(states.items())) or "none"
    return [
        f"  requested {plan.created_at:%Y-%m-%d %H:%M} ({shown}); spent "
        f"{_credits(_spent(requests), design)} of the approved max "
        f"{_credits(plan.approved_max_credits, design)}; next: make-carousel skill (stills, "
        f'clips), then uv run ca carousel render "{package}"'
    ]
