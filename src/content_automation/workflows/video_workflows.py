"""Video workflow definitions: allowed scene types, length limits and plan checks."""

from dataclasses import dataclass
from typing import Literal

from content_automation.ai.voice import estimate_speech_sec
from content_automation.workflows.video_plan import SceneType, VideoPlan

SPEECH_TOLERANCE = 1.2  # avatar words may run up to 20% over the scene length


@dataclass(frozen=True)
class VideoWorkflowSpec:
    workflow_id: str
    version: str
    description: str
    max_duration_sec: int
    scene_types: tuple[SceneType, ...]
    required_scene_type: SceneType
    aspect: Literal["9:16", "16:9"] = "9:16"
    size: tuple[int, int] = (1080, 1920)  # final.mp4 width, height


VIDEO_WORKFLOWS: dict[str, VideoWorkflowSpec] = {
    spec.workflow_id: spec
    for spec in (
        VideoWorkflowSpec(
            workflow_id="reel_short",
            version="1",
            description="Instagram Reel / YouTube Short from generated clips and M1 images.",
            max_duration_sec=90,
            scene_types=("video", "image"),
            required_scene_type="video",
        ),
        VideoWorkflowSpec(
            workflow_id="ugc_ad",
            version="1",
            description="Short UGC-style ad from generated clips and M1 images.",
            max_duration_sec=60,
            scene_types=("video", "image"),
            required_scene_type="video",
        ),
        VideoWorkflowSpec(
            workflow_id="podcast_clip",
            version="1",
            description="Talking avatar speaking the script, with optional b-roll clips.",
            max_duration_sec=90,
            scene_types=("avatar", "video"),
            required_scene_type="avatar",
        ),
        VideoWorkflowSpec(
            workflow_id="youtube",
            version="1",
            description="YouTube video (16:9): the HeyGen avatar speaking the script, with "
            "optional b-roll clips and images.",
            max_duration_sec=600,
            scene_types=("avatar", "video", "image"),
            required_scene_type="avatar",
            aspect="16:9",
            size=(1920, 1080),
        ),
    )
}


def workflow_problems(plan: VideoPlan) -> list[str]:
    """Check the plan against its workflow; every problem is listed, nothing is spent."""
    spec = VIDEO_WORKFLOWS[plan.workflow_id]
    problems: list[str] = []
    if plan.duration_sec > spec.max_duration_sec:
        problems.append(
            f"durationSec {plan.duration_sec:g}s is over the {spec.max_duration_sec}s "
            f"limit for {spec.workflow_id}"
        )
    allowed = ", ".join(spec.scene_types)
    for scene in plan.scenes:
        label = f"scene {scene.n}"
        if scene.type not in spec.scene_types:
            problems.append(
                f"{label}: {spec.workflow_id} has no {scene.type} scenes (use {allowed})"
            )
        if scene.type == "image" and not scene.start_image_asset_id:
            problems.append(
                f"{label}: an image scene needs startImageAssetId (an M1 image or reference photo)"
            )
        if scene.type == "avatar":
            if scene.start_image_asset_id:
                problems.append(f"{label}: avatar scenes do not use startImageAssetId")
            speech = estimate_speech_sec(scene.prompt)
            if speech > scene.duration_sec * SPEECH_TOLERANCE:
                problems.append(
                    f"{label}: the avatar's words take about {speech:g}s to say but the scene is "
                    f"{scene.duration_sec:g}s; shorten the words or split the scene"
                )
    if not any(scene.type == spec.required_scene_type for scene in plan.scenes):
        problems.append(
            f"{spec.workflow_id} needs at least one {spec.required_scene_type} scene"
        )
    return problems
