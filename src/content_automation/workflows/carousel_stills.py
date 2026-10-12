"""Carousel slide stills made by Codex with the Higgsfield plugin (Phase 3 Step 3).

The app calls no plugin. After the user's single "ok" the build writes, per slide that needs
one, <package>/carousel/requests/still_NN.json: the text-free prompt, the negative terms, the
size, the style frames (attached only if the image tool takes reference images) and the output
path <package>/carousel/stills/still_NN.png. Slide types marked "local" (the final slide) get
the app-drawn background as their still and no request.

Codex runs every request without asking again, saves each image, and records each attempt
with `ca carousel record` (credits used, or the error). Then `ca carousel stills-check` checks
every still (exists, 1:1, not blank, a calm left half for the text); a failed still is asked
for once more inside the approved max, and after that it gets the local background.

At most `stills.attempts` (2) attempts per still in total, whether the plugin failed or the
check did, so the dry run's max (estimate x attempts) holds. carousel/carousel.json keeps the
approved max; the spend is the credits recorded in the request files.
"""

import shutil
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from statistics import pstdev
from typing import Literal

from PIL import Image, ImageFilter, UnidentifiedImageError
from pydantic import ConfigDict, Field

from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.workflows.carousel_design import (
    CarouselDesign,
    CarouselDesignError,
    SlideText,
    SlideType,
    StillSource,
    StillsProvider,
    still_prompt,
)
from content_automation.workflows.carousel_render import background, style_frames
from content_automation.workflows.design_system import Box

CAROUSEL_DIR = "carousel"
PLAN_FILE = "carousel.json"
PLUGIN = "Higgsfield"
DECISION_DOC = "docs/PHASE3-DECISION.md"
TOOLS_SECTION = "section 10"
StillStatus = Literal["pending", "made", "failed", "passed", "fallback"]


def _now() -> datetime:
    return datetime.now().astimezone()


class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


class StillAttempt(_Model):
    at: datetime = Field(default_factory=_now)
    status: Literal["made", "failed"]
    credits: float | None = None  # what the plugin reported for this attempt
    provider_job_id: str | None = None
    error: str | None = None


class StillCheck(_Model):
    passed: bool
    reason: str
    metrics: dict[str, float] = Field(default_factory=dict)
    checked_at: datetime = Field(default_factory=_now)


class StillRequest(_Model):
    """carousel/requests/still_NN.json: what Codex sends to the plugin, and what came back."""

    step_id: str
    slide: int
    type: SlideType
    capability: Literal["image"] = "image"
    plugin: str = PLUGIN
    tool: str  # where the tool and model names are (found at run time until then)
    model: str
    prompt: str
    negative_prompt: str
    width: int
    height: int
    aspect_ratio: str
    size_rule: str
    reference_images: str  # unknown | yes | no
    style_references: list[str] = Field(default_factory=list)  # absolute paths
    output_path: str  # absolute
    estimated_credits: float
    max_attempts: int
    status: StillStatus = "pending"
    attempts: list[StillAttempt] = Field(default_factory=list)
    credits_used: float = 0.0
    retry_note: str | None = None  # why it is asked for again (already in the prompt)
    check: StillCheck | None = None
    instructions: list[str] = Field(default_factory=list)


class PlanSlide(_Model):
    slide: int
    type: SlideType
    source: StillSource
    still: str  # relative to the package folder
    request: str | None = None  # relative; None for a local still


class CarouselPlan(_Model):
    """carousel/carousel.json: written once, after the "ok"."""

    topic: str
    provider: StillsProvider
    created_at: datetime = Field(default_factory=_now)
    estimated_credits: float  # every plugin still once
    approved_max_credits: float  # with every retry: what the "ok" approved
    usd_per_credit: float | None = None
    slides: list[PlanSlide]


# --- Paths and files -------------------------------------------------------------------------


def carousel_dir(package: Path) -> Path:
    return package / CAROUSEL_DIR


def plan_path(package: Path) -> Path:
    return carousel_dir(package) / PLAN_FILE


def _step(slide: int) -> str:
    return f"still_{slide:02d}"


def _request_file(package: Path, slide: int) -> Path:
    return carousel_dir(package) / "requests" / f"{_step(slide)}.json"


def _still_file(package: Path, slide: int) -> Path:
    return carousel_dir(package) / "stills" / f"{_step(slide)}.png"


def _save(path: Path, model: CamelModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, model.model_dump_json(by_alias=True, indent=2) + "\n")


def load_plan(package: Path) -> CarouselPlan | None:
    path = plan_path(package)
    if not path.is_file():
        return None
    return CarouselPlan.model_validate_json(path.read_text(encoding="utf-8"))


def _load_request(package: Path, slide: int) -> StillRequest:
    path = _request_file(package, slide)
    if not path.is_file():
        raise CarouselDesignError(
            f"No still request for slide {slide} in {path.parent} (a local slide has none)."
        )
    return StillRequest.model_validate_json(path.read_text(encoding="utf-8"))


def _requests(package: Path, plan: CarouselPlan) -> list[StillRequest]:
    return [_load_request(package, item.slide) for item in plan.slides if item.request]


def _spent(requests: Sequence[StillRequest]) -> float:
    return sum(request.credits_used for request in requests)


def _credits(value: float, design: CarouselDesign) -> str:
    usd = design.stills.usd_per_credit
    return f"{value:g} credits" + (f" (≈ ${value * usd:.2f})" if usd else "")


# --- Dry run ---------------------------------------------------------------------------------


def _source(design: CarouselDesign, slide_type: SlideType) -> StillSource:
    return design.slide_types[slide_type].still


def _provider_problem(design: CarouselDesign) -> str | None:
    if design.stills.provider == "comfyui":
        return (
            "stills.provider comfyui is a stub until RunPod has credit; set it to higgsfield in "
            "config/carousel_design.json"
        )
    return None


def stills_dry_run(
    package: Path, slides: Sequence[SlideText], design: CarouselDesign
) -> list[str]:
    """Per slide: plugin still (estimated credits) or local background; total and max."""
    plan = load_plan(package)
    if plan is not None:
        return status_lines(package, design)
    problem = _provider_problem(design)
    if problem:
        return [f"  stills: {problem}"]
    stills = design.stills
    model = stills.model or "the tool's default image model"
    lines = [
        f"  stills via the {PLUGIN} plugin (plan credits; {model}; reference images: "
        f"{stills.reference_images}):"
    ]
    count = 0
    for number, slide in enumerate(slides, start=1):
        if _source(design, slide.type) == "local":
            lines.append(f"    slide {number} {slide.type}: local background (app-drawn, free)")
            continue
        count += 1
        lines.append(
            f"    slide {number} {slide.type}: 1 still, about {stills.estimated_credits:g} "
            "credits (estimate)"
        )
    total = count * stills.estimated_credits
    lines += [
        f"  stills total: {count} x {stills.estimated_credits:g} = about "
        f"{_credits(total, design)} (estimate; {stills.estimate_note or 'from config'}); max "
        f"with one retry per still: {_credits(total * stills.attempts, design)}",
        f'  after "ok": the build writes {count} still requests (carousel/requests/) for the '
        "make-carousel skill, which runs them all without asking again; then uv run ca carousel "
        f'stills-check "{package}"',
    ]
    return lines


# --- Requests --------------------------------------------------------------------------------


def _instructions(package: Path, request: StillRequest) -> list[str]:
    slide = request.slide
    record = f'uv run ca carousel record "{package}" --still {slide}'
    return [
        f"1. Use the {PLUGIN} plugin's image tool and model named in {DECISION_DOC} "
        f"{TOOLS_SECTION}; first run: list the plugin's tools there first. Never assume a "
        f"name. If the plugin is missing, stop and say so.",
        "2. No question to the user: this runs under the carousel's single \"ok\".",
        "3. Inputs: prompt; negativePrompt (as the negative field, or append \"Avoid: ...\" to "
        "the prompt); 1:1 at 1080x1080 or the closest size the tool offers (ca crops and "
        "resizes); model; styleReferences only if the tool accepts reference images.",
        f"4. Save the image to {request.output_path}.",
        f"5. Record it: {record} --credits <credits used> --provider-job-id <job ID>",
        f'6. If it fails: {record} --error "<reason>" [--credits <charged>]; retry once only '
        "if the record says a retry is left.",
        f'7. After every request: uv run ca carousel stills-check "{package}"',
    ]


def write_still_requests(
    package: Path, topic: str, slides: Sequence[SlideText], design: CarouselDesign
) -> list[str]:
    """After the "ok": one request per plugin slide, the local stills, carousel.json."""
    problem = _provider_problem(design)
    if problem:
        raise CarouselDesignError(problem)
    if load_plan(package) is not None:
        return status_lines(package, design)
    stills = design.stills
    entries: list[PlanSlide] = []
    count = 0
    for number, slide in enumerate(slides, start=1):
        still = _still_file(package, number)
        if _source(design, slide.type) == "local":
            still.parent.mkdir(parents=True, exist_ok=True)
            background(design).save(still, optimize=True)
            entries.append(PlanSlide(
                slide=number, type=slide.type, source="local",
                still=still.relative_to(package).as_posix(),
            ))
            continue
        count += 1
        references = [] if stills.reference_images == "no" else [
            str(path.resolve())
            for path in style_frames(design, slide.type)[: stills.style_references]
        ]
        request = StillRequest(
            step_id=_step(number),
            slide=number,
            type=slide.type,
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
        request.instructions = _instructions(package.resolve(), request)
        path = _request_file(package, number)
        _save(path, request)
        entries.append(PlanSlide(
            slide=number, type=slide.type, source="plugin",
            still=still.relative_to(package).as_posix(),
            request=path.relative_to(package).as_posix(),
        ))
    total = count * stills.estimated_credits
    plan = CarouselPlan(
        topic=topic,
        provider=stills.provider,
        estimated_credits=total,
        approved_max_credits=total * stills.attempts,
        usd_per_credit=stills.usd_per_credit,
        slides=entries,
    )
    _save(plan_path(package), plan)
    cap = _credits(plan.approved_max_credits, design)
    return [
        f"Carousel stills: {count} requests for the {PLUGIN} plugin in "
        f"{carousel_dir(package) / 'requests'} (approved max {cap}); "
        f"{len(entries) - count} local still(s) written.",
        "Codex: make-carousel skill: run every request without asking again, record each with "
        f'uv run ca carousel record, then uv run ca carousel stills-check "{package}".',
    ]


# --- Recording an attempt --------------------------------------------------------------------


def record_attempt(
    package: Path,
    slide: int,
    design: CarouselDesign,
    *,
    credits: float | None = None,
    provider_job_id: str | None = None,
    file: Path | None = None,
    error: str | None = None,
) -> list[str]:
    """`ca carousel record`: one plugin attempt (the image, or the error) and its credits."""
    plan = load_plan(package)
    if plan is None:
        raise CarouselDesignError(
            f"No carousel requests in {package}: run the build after the \"ok\" first."
        )
    request = _load_request(package, slide)
    if request.status in ("passed", "fallback"):
        raise CarouselDesignError(f"{request.step_id} is final ({request.status}); not recorded.")
    if len(request.attempts) >= request.max_attempts:
        raise CarouselDesignError(
            f"{request.step_id} already has {len(request.attempts)} attempts (the most); "
            "stills-check gives it the local background."
        )
    target = Path(request.output_path)
    if error is None:
        source = file or target
        if not source.is_file() or source.stat().st_size == 0:
            raise CarouselDesignError(f"Image not found or empty: {source}.")
        if source.resolve() != target.resolve():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    request.attempts.append(StillAttempt(
        status="failed" if error else "made", credits=credits,
        provider_job_id=provider_job_id, error=error,
    ))
    request.status = "failed" if error else "made"
    request.credits_used += credits or 0.0
    request.check = None
    _save(_request_file(package, slide), request)
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
        lines.append(f"No retry for {request.step_id}: stills-check gives it the local background.")
    pending = [item for item in requests if item.status == "pending"]
    if pending and spent + sum(item.estimated_credits for item in pending) > cap:
        lines.append(
            "STOP: the pending requests could go over the approved max; ask the user before "
            "making more."
        )
    return lines


# --- Check -----------------------------------------------------------------------------------


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
    change = abs(width / height - 1)
    if change > design.stills.check.max_aspect_change:
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


def check_still(path: Path, design: CarouselDesign) -> StillCheck:
    """Exists, 1:1 at the canvas size (after crop/resize), not blank, calm text panel."""
    if not path.is_file() or path.stat().st_size == 0:
        return StillCheck(passed=False, reason="missing")
    image, note = _normalize(path, design)
    if image is None:
        return StillCheck(passed=False, reason=note)
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
    return StillCheck(passed=not problems, reason=reason, metrics=metrics)


def _retry_note(reason: str) -> str:
    return (
        f"The previous image failed the check ({reason}). Keep the left half of the frame "
        "completely calm, dark and empty (no objects, lines, glow or letters there); put the "
        "subject only in the right half."
    )


def stills_check(package: Path, design: CarouselDesign) -> list[str]:
    """`ca carousel stills-check`: check every still; one re-request inside the max, then the
    local background. Lines per slide, the spend and what Codex does next."""
    plan = load_plan(package)
    if plan is None:
        raise CarouselDesignError(
            f"No carousel requests in {package}: run the build after the \"ok\" first."
        )
    requests = {request.slide: request for request in _requests(package, plan)}
    spent = _spent(list(requests.values()))
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
        if request.status == "failed" and not still.is_file():
            last = request.attempts[-1].error if request.attempts else None
            result = StillCheck(passed=False, reason=f"missing (plugin error: {last})")
        else:
            result = check_still(still, design)
        request.check = result
        if result.passed:
            request.status = "passed"
            counts["plugin"] += 1
            lines.append(f"{where}: passed ({result.reason})")
        elif (len(request.attempts) < request.max_attempts
              and spent + request.estimated_credits <= cap):
            request.status = "pending"
            request.retry_note = _retry_note(result.reason)
            request.prompt = f"{request.prompt} {request.retry_note}"
            spent += request.estimated_credits  # reserved for the re-request
            again.append(request.step_id)
            lines.append(f"{where}: failed ({result.reason}); asked for once more")
        else:
            why = "no attempt left" if len(request.attempts) >= request.max_attempts else (
                "the approved max would be exceeded"
            )
            if still.is_file():
                rejected = still.parent / "rejected"
                rejected.mkdir(exist_ok=True)
                shutil.move(still, rejected / still.name)
            background(design).save(still, optimize=True)
            request.status = "fallback"
            request.retry_note = f"{result.reason}; {why}"
            counts["fallback"] += 1
            lines.append(f"{where}: failed ({result.reason}); {why}: local background")
        _save(_request_file(package, item.slide), request)
    spent_now = _spent(list(requests.values()))
    lines.append(
        f"Credits: {spent_now:g} spent of the approved max {cap:g} "
        f"(estimate {plan.estimated_credits:g})."
    )
    if again:
        lines.append(
            f"Next (no question): run the {PLUGIN} plugin for {', '.join(again)}, record each "
            f'with uv run ca carousel record, then uv run ca carousel stills-check "{package}" '
            "again."
        )
    else:
        lines.append(
            f"All {len(plan.slides)} stills ready: {counts['plugin']} from the plugin, "
            f"{counts['local']} local, {counts['fallback']} local fallback."
        )
    return lines


def status_lines(package: Path, design: CarouselDesign) -> list[str]:
    """The state of requests written earlier (dry run and build print it)."""
    plan = load_plan(package)
    if plan is None:
        return []
    requests = _requests(package, plan)
    states: dict[str, int] = {}
    for request in requests:
        states[request.status] = states.get(request.status, 0) + 1
    shown = ", ".join(f"{count} {state}" for state, count in sorted(states.items())) or "none"
    return [
        f"  stills: requested {plan.created_at:%Y-%m-%d %H:%M} ({shown}); spent "
        f"{_credits(_spent(requests), design)} of the approved max "
        f"{_credits(plan.approved_max_credits, design)}; next: make-carousel skill, then "
        f'uv run ca carousel stills-check "{package}"'
    ]
