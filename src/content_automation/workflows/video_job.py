"""Video jobs: plan.json → one step per scene → final.mp4 (docs/prd/module-2.md).

`ca video --plan` checks the plan and starts the job. Code steps (mock) finish at once;
agent steps pause the job (awaiting_agent) until Codex records them with `ca job complete`.
`ca video resume` then runs anything still missing and assembles final.mp4.
Voiceover is disabled in the MVP (VOICE_PROVIDER=none): scenes keep their own sound.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from content_automation.ai.avatar import AvatarRequest, generate_avatar_video
from content_automation.ai.avatar import get_provider as get_avatar_provider
from content_automation.ai.video import VideoRequest, generate_video
from content_automation.ai.video import get_provider as get_video_provider
from content_automation.ai.voice import VOICE_OFF
from content_automation.core.agent_steps import request_path
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.jobs import Job, JobParams, JobStep, create_job
from content_automation.core.log import get_logger, mask_secrets, secret_values
from content_automation.media.assemble import CAPTIONS_FILE, FINAL_FILE, Segment, assemble
from content_automation.media.assemble import text_support as assembly_text_support
from content_automation.workflows.start_images import (
    StartImage,
    StartImageError,
    resolve_start_image,
)
from content_automation.workflows.video_plan import (
    PlanError,
    PlanScene,
    VideoPlan,
    load_plan,
    parse_plan,
    scene_problems,
)
from content_automation.workflows.video_workflows import (
    VIDEO_WORKFLOWS,
    VideoWorkflowSpec,
    workflow_problems,
)

PLAN_FILE = "plan.json"
SCRIPT_FILE = "script.md"
ASPECT: Literal["9:16"] = "9:16"
# Credits per scene, by provider; agent providers are estimated in M2.C.
_CREDITS = {"mock": "0", "library": "0"}
_CREDITS_TBD = "TBD until M2.C"

logger = get_logger("workflows.video_job")


@dataclass(frozen=True)
class PreparedScene:
    scene: PlanScene
    step_id: str
    provider: str
    mode: str
    start_image: StartImage | None = None


@dataclass(frozen=True)
class PreparedVideo:
    plan: VideoPlan
    spec: VideoWorkflowSpec
    scenes: list[PreparedScene]


def prepare_video(plan: VideoPlan, settings: Settings) -> PreparedVideo:
    """Check the plan against its workflow and find start images; no job, no calls.

    Raises PlanError listing every problem, or VideoError/AvatarError when the selected
    provider does not exist.
    """
    problems = scene_problems(plan) + workflow_problems(plan)
    scenes: list[PreparedScene] = []
    for scene in plan.scenes:
        start_image = None
        if scene.start_image_asset_id:
            try:
                start_image = resolve_start_image(scene.start_image_asset_id, settings)
            except StartImageError as error:
                problems.append(f"scene {scene.n}: {error}")
        provider, mode = _provider_for(scene, settings)
        scenes.append(PreparedScene(scene, f"scene-{scene.n}", provider, mode, start_image))
    if problems:
        raise PlanError(problems)
    return PreparedVideo(plan, VIDEO_WORKFLOWS[plan.workflow_id], scenes)


def _provider_for(scene: PlanScene, settings: Settings) -> tuple[str, str]:
    if scene.type == "video":
        return settings.video_provider, get_video_provider(settings.video_provider, settings).mode
    if scene.type == "avatar":
        avatar = get_avatar_provider(settings.avatar_provider, settings)
        return settings.avatar_provider, avatar.mode
    return "library", "code"  # image scene: an existing picture, no provider call


def dry_run_lines(prepared: PreparedVideo, settings: Settings) -> list[str]:
    plan, spec = prepared.plan, prepared.spec
    lines = [
        "DRY RUN: no job created, no provider call, nothing spent.",
        f"Workflow: {spec.workflow_id} (v{spec.version}), max {spec.max_duration_sec}s: "
        f"{spec.description}",
        f"Plan: {plan.duration_sec:g}s, {len(plan.scenes)} scenes, platform {plan.platform}",
        _voice_note(plan, settings),
        "Scenes:",
    ]
    for item in prepared.scenes:
        scene = item.scene
        line = (
            f"  {scene.n}. {scene.type:<6} {scene.duration_sec:>4g}s  "
            f"{item.provider} ({item.mode})"
        )
        if item.start_image:
            line += f" | start image {item.start_image.source} [{item.start_image.asset_id}]"
        lines.append(line)
        lines.append(f"     {'says' if scene.type == 'avatar' else 'prompt'}: {scene.prompt}")
        if scene.on_screen_text:
            lines.append(f'     text: "{scene.on_screen_text}"')
    used = sorted({(item.scene.type, item.provider) for item in prepared.scenes})
    credits = " | ".join(
        f"{kind} ({provider}): {_CREDITS.get(provider, _CREDITS_TBD)}" for kind, provider in used
    )
    lines.append(f"Estimated credits: {credits}")
    font, note = assembly_text_support()
    text = note if font else f"not burned in ({note}); captions.srt instead"
    lines.append(f"Output: final.mp4, 1080x1920, 30 fps, H.264/AAC; text {text}")
    return lines


def start_video_job(
    plan_file: Path, settings: Settings, *, request: str | None = None
) -> Job:
    """Validate plan_file, create the job folder, and run as far as possible."""
    try:
        text = plan_file.read_text(encoding="utf-8")
    except OSError:
        raise PlanError([f"cannot read {plan_file}"]) from None
    prepared = prepare_video(parse_plan(text, check_scenes=False), settings)
    plan = prepared.plan
    providers = sorted({item.provider for item in prepared.scenes})
    job = create_job(
        settings.output_dir,
        workflow_id=plan.workflow_id,
        workflow_version=prepared.spec.version,
        requested_by=settings.user_name,
        request=request or plan.hook,
        prompt=plan.script,
        provider="+".join(providers),
        model="+".join(sorted(_models(prepared, settings))),
        params=JobParams(aspect_ratio=ASPECT, image_size="1080x1920", count=1),
        inputs=_inputs(prepared),
        est_cost_usd=0.0 if set(providers) <= set(_CREDITS) else None,
    )
    logger.info("Video job %s created in %s", job.job_id, job.folder)
    atomic_write_text(job.folder / PLAN_FILE, text)
    atomic_write_text(job.folder / SCRIPT_FILE, _script_markdown(prepared))
    job.notes.append(_voice_note(plan, settings))
    job.start()
    return advance(job, prepared, settings)


def resume_video_job(job: Job, settings: Settings) -> Job:
    """Continue a paused job: fail timed-out steps, run missing scenes, then assemble."""
    if job.status in ("completed", "failed", "cancelled"):
        return job
    if job.expire_steps(settings.agent_step_timeout_min):
        return job
    try:
        prepared = prepare_video(load_plan(job.folder / PLAN_FILE, check_scenes=False), settings)
    except PlanError as error:
        job.fail(str(error))
        return job
    if job.status == "queued":
        job.start()
    return advance(job, prepared, settings)


def advance(job: Job, prepared: PreparedVideo, settings: Settings) -> Job:
    """Run every scene that has no step yet; assemble once all steps are completed."""
    try:
        for item in prepared.scenes:
            if any(step.step_id == item.step_id for step in job.steps):
                continue
            job.add_step(_run_scene(job, item, settings))
        if job.waiting_steps():
            return job
        result = assemble(_segments(job, prepared), job.folder)
        job.notes.append(
            f"final.mp4: 1080x1920, 30 fps, {result.duration_sec:.1f}s, "
            f"{len(prepared.scenes)} scenes."
        )
        if result.text_burned_in:
            job.notes.append(f"On-screen text and captions {result.text_note}.")
        elif result.captions is not None:
            job.notes.append(
                f"Text NOT burned in ({result.text_note}); see {CAPTIONS_FILE} instead."
            )
        outputs = [FINAL_FILE] + ([CAPTIONS_FILE] if result.captions is not None else [])
        job.complete(outputs)
        logger.info("Video job %s completed", job.job_id)
    except KeyboardInterrupt:
        job.cancel()
        raise
    except Exception as error:
        message = mask_secrets(f"{type(error).__name__}: {error}", secret_values(settings))
        job.fail(message)
        logger.error("Video job %s failed: %s", job.job_id, message)
    return job


def _run_scene(job: Job, item: PreparedScene, settings: Settings) -> JobStep:
    scene = item.scene
    if scene.type == "video":
        return generate_video(
            VideoRequest(
                step_id=item.step_id,
                job_dir=job.folder,
                prompt=scene.prompt,
                duration_sec=scene.duration_sec,
                aspect_ratio=ASPECT,
                start_image_path=item.start_image.path if item.start_image else None,
                start_image_asset_id=item.start_image.asset_id if item.start_image else None,
            ),
            settings,
        )
    if scene.type == "avatar":
        return generate_avatar_video(
            AvatarRequest(
                step_id=item.step_id,
                job_dir=job.folder,
                script=scene.prompt,
                duration_sec=scene.duration_sec,
                aspect_ratio=ASPECT,
            ),
            settings,
        )
    if item.start_image is None:  # checked by the plan rules; kept for safety
        raise StartImageError(f"scene {scene.n}: no start image.")
    relative = f"clips/{item.step_id}{item.start_image.path.suffix.lower()}"
    (job.folder / "clips").mkdir(exist_ok=True)
    shutil.copyfile(item.start_image.path, job.folder / relative)
    return JobStep(
        step_id=item.step_id,
        capability="image",
        provider="library",
        mode="code",
        status="completed",
        file=relative,
        provider_job_id=item.start_image.asset_id,
    )


def _segments(job: Job, prepared: PreparedVideo) -> list[Segment]:
    segments: list[Segment] = []
    for item in prepared.scenes:
        scene = item.scene
        step = job.step(item.step_id)
        if step.status != "completed" or not step.file:
            raise RuntimeError(f"Step {item.step_id} is {step.status}; cannot assemble.")
        segments.append(
            Segment(
                path=job.folder / step.file,
                kind="image" if scene.type == "image" else "clip",
                # Video clips are cut to plan length; avatar clips keep all their speech.
                duration_sec=None if scene.type == "avatar" else scene.duration_sec,
                on_screen_text=scene.on_screen_text,
                speech=scene.prompt if scene.type == "avatar" else None,
            )
        )
    return segments


def agent_checklist(job: Job) -> list[str]:
    """What Codex has to do for each waiting step, numbered."""
    waiting = job.waiting_steps()
    folder = job.folder
    lines = [f"Waiting for Codex: {len(waiting)} agent step(s). For each one:"]
    for number, step in enumerate(waiting, start=1):
        request = request_path(folder, step.step_id).relative_to(folder).as_posix()
        lines += [
            f"  {number}. {step.step_id} ({step.capability} via {step.provider}): read {request}, "
            "make it with the MCP tool it names, save the file, then run:",
            f'     uv run ca job complete "{folder}" --step {step.step_id} --file <saved file>',
        ]
    lines += [
        f'  If a step fails: uv run ca job fail "{folder}" --step <step> --error "<what happened>"',
        f'  When all are recorded: uv run ca video resume "{folder}"',
    ]
    return lines


def _voice_note(plan: VideoPlan, settings: Settings) -> str:
    if settings.voice_provider == VOICE_OFF:
        note = "Voiceover disabled in MVP (VOICE_PROVIDER=none); scenes keep their own sound."
    else:
        note = (
            f"Voiceover disabled in MVP: VOICE_PROVIDER={settings.voice_provider} is ignored; "
            "scenes keep their own sound."
        )
    if plan.voice is not None:
        note += " The plan's voice setting is ignored."
    return note


def _models(prepared: PreparedVideo, settings: Settings) -> set[str]:
    models = set()
    for item in prepared.scenes:
        if item.scene.type == "video":
            models.add(settings.video_model)
        elif item.scene.type == "avatar":
            models.add(settings.avatar_model)
    return models or {"none"}


def _inputs(prepared: PreparedVideo) -> dict[str, str | bool]:
    inputs: dict[str, str | bool] = {"platform": prepared.plan.platform}
    for item in prepared.scenes:
        if item.start_image:
            inputs[f"{item.step_id}.startImageAssetId"] = item.start_image.asset_id
            inputs[f"{item.step_id}.startImage"] = item.start_image.source
    return inputs


def _script_markdown(prepared: PreparedVideo) -> str:
    plan = prepared.plan
    lines = [
        f"# {plan.hook}",
        "",
        f"Workflow: {plan.workflow_id} · Platform: {plan.platform} · {plan.duration_sec:g}s",
        "",
        "## Hook",
        "",
        plan.hook,
        "",
        "## Script",
        "",
        plan.script,
        "",
    ]
    if plan.cta:
        lines += ["## Call to action", "", plan.cta, ""]
    lines += ["## Scenes", "", "| # | Type | Seconds | Prompt / words | On-screen text |",
              "|---|---|---|---|---|"]
    for item in prepared.scenes:
        scene = item.scene
        cells = [str(scene.n), scene.type, f"{scene.duration_sec:g}", scene.prompt,
                 scene.on_screen_text or ""]
        lines.append("| " + " | ".join(cell.replace("|", "/") for cell in cells) + " |")
    return "\n".join(lines) + "\n"
