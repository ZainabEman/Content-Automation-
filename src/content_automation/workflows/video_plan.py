"""plan.json: the video plan Codex writes (hook, script, scenes), checked before any
provider is called so an invalid plan never spends credits. See docs/prd/module-2.md."""

from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError
from pydantic_core import ErrorDetails

from content_automation.core.files import CamelModel

MAX_SCENE_SEC = 15
MAX_VIDEO_SEC = 90  # the longest workflow (reel_short); each workflow has its own limit
DURATION_TOLERANCE_SEC = 1.0

# v5 (PRD R8): UGC ads, podcast clips and finished YouTube videos are no longer generated.
VideoWorkflow = Literal["reel_short"]
SceneType = Literal["video", "avatar", "image"]


class PlanError(ValueError):
    """plan.json is missing or invalid; ``problems`` lists every issue found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        lines = "\n".join(f"- {problem}" for problem in problems)
        super().__init__(f"plan.json has {len(problems)} problem(s):\n{lines}")


class _PlanModel(CamelModel):
    model_config = ConfigDict(extra="forbid")  # catches misspelled fields


class PlanVoice(_PlanModel):
    voice_id: str | None = None  # default: ELEVENLABS_VOICE_ID


class PlanScene(_PlanModel):
    n: int = Field(ge=1)
    type: SceneType
    prompt: str = Field(min_length=1)
    start_image_asset_id: str | None = None
    duration_sec: float = Field(gt=0, le=MAX_SCENE_SEC)
    on_screen_text: str | None = None


class VideoPlan(_PlanModel):
    workflow_id: VideoWorkflow
    platform: str = Field(min_length=1)
    duration_sec: float = Field(gt=0, le=MAX_VIDEO_SEC)
    hook: str = Field(min_length=1)
    script: str = Field(min_length=1)
    cta: str | None = None
    voice: PlanVoice | None = None  # optional: voiceover is disabled in the MVP
    scenes: list[PlanScene] = Field(min_length=1)


def parse_plan(text: str, *, check_scenes: bool = True) -> VideoPlan:
    """Validate plan JSON; raise PlanError with one readable line per problem.

    check_scenes=False skips the scene numbering/length checks so a caller can report
    them together with its own checks (see workflows.video_job.prepare_video).
    """
    try:
        plan = VideoPlan.model_validate_json(text)
    except ValidationError as error:
        raise PlanError([_describe(issue) for issue in error.errors(include_url=False)]) from None
    problems = scene_problems(plan) if check_scenes else []
    if problems:
        raise PlanError(problems)
    return plan


def load_plan(path: Path, *, check_scenes: bool = True) -> VideoPlan:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise PlanError([f"cannot read {path}"]) from None
    return parse_plan(text, check_scenes=check_scenes)


def scene_problems(plan: VideoPlan) -> list[str]:
    problems: list[str] = []
    numbers = [scene.n for scene in plan.scenes]
    if numbers != list(range(1, len(plan.scenes) + 1)):
        problems.append(f"scenes must be numbered 1, 2, 3... in order (found {numbers})")
    total = sum(scene.duration_sec for scene in plan.scenes)
    if abs(total - plan.duration_sec) > DURATION_TOLERANCE_SEC:
        problems.append(f"scenes add up to {total:g}s but durationSec is {plan.duration_sec:g}s")
    return problems


def _describe(issue: ErrorDetails) -> str:
    location = _location(issue["loc"])
    kind = issue["type"]
    message = issue["msg"]
    if kind == "json_invalid":
        return f"not valid JSON: {issue.get('ctx', {}).get('error', message)}"
    if kind == "missing":
        return f"{location}: missing"
    if kind == "extra_forbidden":
        return f"{location}: unknown field (check spelling; fields are camelCase)"
    if kind == "less_than_equal" and location.endswith("durationSec") and "scene" in location:
        return f"{location}: must be {MAX_SCENE_SEC}s or less; split it into two scenes"
    return f"{location}: {message}" if location else message


def _location(loc: tuple[int | str, ...]) -> str:
    """('scenes', 1, 'durationSec') -> 'scene 2 durationSec' (scenes counted from 1)."""
    parts: list[str] = []
    items = list(loc)
    for index, part in enumerate(items):
        if part == "scenes" and index + 1 < len(items) and isinstance(items[index + 1], int):
            continue
        if isinstance(part, int) and index > 0 and items[index - 1] == "scenes":
            parts.append(f"scene {part + 1}")
        else:
            parts.append(str(part))
    return " ".join(parts)
