"""Video jobs: plan.json → one step per scene → final.mp4 (docs/prd/module-2.md).

`ca video --plan` checks the plan and starts the job. Code steps (mock) finish at once;
agent steps pause the job (awaiting_agent) until Codex records them with `ca job complete`.
`ca video resume` then runs anything still missing and assembles final.mp4.
Voiceover is disabled in the MVP (VOICE_PROVIDER=none): scenes keep their own sound.

A content package needs a real video, so it starts its job with real_only=True: while a
scene's provider is mock or none, the job is created but holds (status processing, no
steps) and says what is missing; `ca video resume` continues it once a real provider is set.

HeyGen clips need the person's avatar and a voice (HEYGEN_AVATAR_ID, HEYGEN_VOICE_ID). They
are checked before a job is created (AvatarSetupError), so a missing ID never leaves a
failed job behind; Codex confirms both IDs with the HeyGen plugin before the "ok".
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
from content_automation.core.agent_steps import load_request, request_path, save_request
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.jobs import Job, JobParams, JobStep, create_job
from content_automation.core.log import get_logger, mask_secrets, secret_values
from content_automation.media.assemble import CAPTIONS_FILE, FINAL_FILE, Segment, assemble
from content_automation.media.assemble import text_support as assembly_text_support
from content_automation.references import (
    ReferenceLibraryError,
    load_set,
    select_identity_refs,
)
from content_automation.registry import runtime
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
_CREDITS = {"mock": "0", "library": "0", "none": "0"}
MAX_IDENTITY_PHOTOS = 14  # all of the person's usable photos (the model limit)
_CREDITS_TBD = "TBD until M2.C"
HEYGEN = "heygen-plugin"
# Credit cost per scene as far as it is known before generation, by provider.
_SCENE_CREDITS = {
    "higgsfield-plugin": "reported by the Higgsfield plugin before generating",
    HEYGEN: "reported by the HeyGen plugin before generating",
}
NO_PROVIDER = "none"
PLACEHOLDER_PROVIDERS = frozenset({"mock", NO_PROVIDER})  # no real clips
REAL_ONLY = "realProvidersOnly"  # job input: wait for real providers instead of mock clips
# Scene type -> (setting, real provider, what to connect in Codex).
_REAL = {
    "video": ("VIDEO_PROVIDER", "higgsfield-plugin", "the Higgsfield plugin"),
    "avatar": ("AVATAR_PROVIDER", "heygen-plugin", "the HeyGen plugin (and set HEYGEN_AVATAR_ID)"),
}

logger = get_logger("workflows.video_job")


class AvatarSetupError(PlanError):
    """HeyGen avatar or voice ID is missing; raised before any job is created."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__(problems)
        lines = "\n".join(f"- {problem}" for problem in problems)
        self.args = (f"HeyGen is not set up, so no video job was created:\n{lines}",)


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
    identity_set: str | None = None  # the only person allowed in the clips
    identity_paths: tuple[Path, ...] = ()
    identity_asset_ids: tuple[str, ...] = ()


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
    identity_set, refs = None, []
    if any(scene.type == "video" for scene in plan.scenes):
        # Any person in a generated clip must be the identity person: send all his photos.
        try:
            refs = select_identity_refs(
                settings.default_identity_set, MAX_IDENTITY_PHOTOS, settings.references_dir
            )
            identity_set = load_set(settings.default_identity_set, settings.references_dir).set_id
        except ReferenceLibraryError as error:
            problems.append(f"identity photos for the video are missing: {error}")
        if identity_set is not None and not refs:
            problems.append(f"identity set {identity_set} has no usable photos for the video")
    if problems:
        raise PlanError(problems)
    return PreparedVideo(
        plan,
        VIDEO_WORKFLOWS[plan.workflow_id],
        scenes,
        identity_set,
        tuple(ref.path for ref in refs),
        tuple(ref.asset_id for ref in refs),
    )


def _provider_for(scene: PlanScene, settings: Settings) -> tuple[str, str]:
    if scene.type == "video":
        if settings.video_provider == NO_PROVIDER:
            return NO_PROVIDER, NO_PROVIDER
        return settings.video_provider, get_video_provider(settings.video_provider, settings).mode
    if scene.type == "avatar":
        if settings.avatar_provider == NO_PROVIDER:
            return NO_PROVIDER, NO_PROVIDER
        avatar = get_avatar_provider(settings.avatar_provider, settings)
        return settings.avatar_provider, avatar.mode
    return "library", "code"  # image scene: an existing picture, no provider call


def missing_providers(prepared: PreparedVideo) -> list[str]:
    """What must be set before the plan's clips can be real (empty: nothing is missing)."""
    lines = []
    for kind in ("video", "avatar"):
        providers = {item.provider for item in prepared.scenes if item.scene.type == kind}
        for provider in sorted(providers & PLACEHOLDER_PROVIDERS):
            setting, real, connect = _REAL[kind]
            what = "no provider is set" if provider == NO_PROVIDER else "mock makes placeholders"
            lines.append(
                f"{kind} scenes: {setting}={provider} ({what}). Set {setting}={real} in .env; "
                f"{connect} must be installed in Codex."
            )
    return lines


def missing_avatar_ids(prepared: PreparedVideo, settings: Settings) -> list[str]:
    """HeyGen clips need the avatar and the voice ID; what is missing and how to set it."""
    if not any(item.provider == HEYGEN for item in prepared.scenes):
        return []
    lines = []
    for name, value, what in (
        ("HEYGEN_AVATAR_ID", settings.heygen_avatar_id, "avatars (his own avatar first)"),
        ("HEYGEN_VOICE_ID", settings.heygen_voice_id, "voices (his own or cloned voices first)"),
    ):
        if not value:
            lines.append(
                f"{name} is not set: list the account's {what} with the HeyGen plugin, let the "
                f"user choose, then run: uv run ca env set {name} <id>"
            )
    return lines


def scene_lines(prepared: PreparedVideo, settings: Settings) -> list[str]:
    """Per scene: provider, avatar, voice, duration and credits, for the "ok" step."""
    lines = []
    for item in prepared.scenes:
        scene = item.scene
        parts = [f"scene {scene.n}: {scene.type}", f"{scene.duration_sec:g} s", item.provider]
        if item.provider == HEYGEN:
            parts.append(f"avatar {settings.heygen_avatar_id or 'NOT SET'}")
            parts.append(f"voice {settings.heygen_voice_id or 'NOT SET'}")
        elif scene.type == "video" and item.provider not in PLACEHOLDER_PROVIDERS:
            parts.append(f"model {settings.video_model}")
        credits = _SCENE_CREDITS.get(item.provider, _CREDITS.get(item.provider, _CREDITS_TBD))
        parts.append(f"credits: {credits}")
        lines.append(", ".join(parts))
    return lines


def pending_lines(job: Job, settings: Settings) -> list[str]:
    """Why a held job (real_only, or HeyGen IDs missing) is still waiting, and how to finish it;
    else []."""
    if job.status != "processing" or job.steps:
        return []
    try:
        prepared = prepare_video(load_plan(job.folder / PLAN_FILE, check_scenes=False), settings)
    except (PlanError, StartImageError) as error:
        return [f"The video plan has a problem: {error}"]
    missing = missing_providers(prepared) or missing_avatar_ids(prepared, settings)
    if not missing:
        return [f'Real providers are set now: run uv run ca video resume "{job.folder}"']
    return [
        "Video pending: the job is created but no clips are made yet.",
        *(f"  Missing: {line}" for line in missing),
        f'  Then run: uv run ca video resume "{job.folder}"',
    ]


def dry_run_lines(prepared: PreparedVideo, settings: Settings) -> list[str]:
    plan, spec = prepared.plan, prepared.spec
    lines = [
        "DRY RUN: no job created, no provider call, nothing spent.",
        *(f"STOP: {line}" for line in missing_avatar_ids(prepared, settings)),
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
        if item.provider == HEYGEN:
            line += (
                f" | avatar {settings.heygen_avatar_id or 'NOT SET'}, "
                f"voice {settings.heygen_voice_id or 'NOT SET'}"
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
    plan_file: Path,
    settings: Settings,
    *,
    request: str | None = None,
    real_only: bool = False,
) -> Job:
    """Validate plan_file, create the job folder, and run as far as possible.

    real_only: with a mock or no provider the job is created and held (nothing is made)
    until a real provider is set; without it a missing provider (none) is an error.
    """
    try:
        text = plan_file.read_text(encoding="utf-8")
    except OSError:
        raise PlanError([f"cannot read {plan_file}"]) from None
    prepared = prepare_video(parse_plan(text, check_scenes=False), settings)
    plan = prepared.plan
    ids = missing_avatar_ids(prepared, settings)
    if ids:  # before the job exists, so nothing is marked failed
        raise AvatarSetupError(ids)
    unset = [item for item in prepared.scenes if item.provider == NO_PROVIDER]
    if unset and not real_only:
        raise PlanError([
            f"scene {item.scene.n}: no {item.scene.type} provider is set "
            f"({_REAL[item.scene.type][0]}=none in .env)"
            for item in unset
        ])
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
        identity_asset_ids=list(prepared.identity_asset_ids),
        inputs=_inputs(prepared) | ({REAL_ONLY: True} if real_only else {}),
        est_cost_usd=0.0 if set(providers) <= set(_CREDITS) else None,
    )
    logger.info("Video job %s created in %s", job.job_id, job.folder)
    atomic_write_text(job.folder / PLAN_FILE, text)
    atomic_write_text(job.folder / SCRIPT_FILE, _script_markdown(prepared))
    job.notes.append(_voice_note(plan, settings))
    job.start()
    if real_only and missing_providers(prepared):
        job.notes.append("Held: waiting for real video providers; no placeholder clips are made.")
        job.save()
        return job
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
    if job.inputs.get(REAL_ONLY) and missing_providers(prepared):
        return job  # still held: no placeholder clips for a content package
    if missing_avatar_ids(prepared, settings) and not any(
        step.provider == HEYGEN for step in job.steps
    ):
        return job  # held until the avatar and voice IDs are set (pending_lines says how)
    if any(item.provider == NO_PROVIDER for item in prepared.scenes):
        return job  # nothing can make these clips yet
    return advance(job, prepared, settings)


def advance(job: Job, prepared: PreparedVideo, settings: Settings) -> Job:
    """Run every scene that has no step yet; assemble once all steps are completed."""
    try:
        for item in prepared.scenes:
            if any(step.step_id == item.step_id for step in job.steps):
                continue
            step = _run_scene(job, item, settings, prepared.identity_paths)
            job.add_step(step)
            if step.mode == "agent" and step.status == "awaiting_agent":
                _registry_job(job, item)
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


def _run_scene(
    job: Job, item: PreparedScene, settings: Settings, identity: tuple[Path, ...] = ()
) -> JobStep:
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
                identity_image_paths=list(identity),
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
                avatar_id=settings.heygen_avatar_id,
                voice_id=settings.heygen_voice_id,
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


def _registry_job(job: Job, item: PreparedScene) -> None:
    """A plugin scene is a registry job (§14 D-5): opened now, its ID in the request file, closed
    by `ca job complete` / `ca job fail`; the make-video skill runs `ca jobs check` first."""
    scope = runtime.current()
    if scope is None:
        return
    job_type = "video_scene" if item.scene.type == "video" else "avatar_scene"
    estimate = scope.config.estimate(job_type, item.provider)
    opened = runtime.open_scoped_job(
        job_type, item.provider,
        {"video_job": job.job_id, "step": item.step_id, "prompt": item.scene.prompt,
         "seconds": item.scene.duration_sec},
        estimate=estimate, direct=True,
    )
    if opened is None:
        return
    request = load_request(job.folder, item.step_id)
    request.job_id = opened.job.id
    save_request(job.folder, request)


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
            f"  {number}. {step.step_id} ({step.capability} via {step.provider}): read {request} "
            "and follow its instructions (generate, wait, download), then run:",
            f'     uv run ca job complete "{folder}" --step {step.step_id} --file <saved file>',
        ]
    lines += [
        "  If that provider's plugin is not available in this Codex session, stop and tell the "
        "user which plugin is missing; then run the resume command below once it is installed.",
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
    if prepared.identity_set:
        inputs["identitySet"] = prepared.identity_set
        inputs["identityRefs"] = str(len(prepared.identity_paths))
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
