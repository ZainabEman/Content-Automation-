"""Video generation capability: the only public entry point for video clip providers.

App code calls ``generate_video()``; adapters live in ``providers/`` and are chosen by
``VIDEO_PROVIDER`` (adapter) and ``VIDEO_MODEL`` (model passed to the adapter).
A "code" adapter writes clips/<stepId>.mp4 and returns a completed step. An "agent"
adapter writes requests/<stepId>.json and returns an awaiting_agent step.
"""

import importlib
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from content_automation.core.agent_steps import step_problem
from content_automation.core.config import Settings, load_settings
from content_automation.core.jobs import AdapterMode, JobStep

VideoAspect = Literal["9:16", "16:9", "1:1", "4:5"]
MAX_CLIP_SEC = 15
STEP_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"
CLIPS_DIR = "clips"

# Provider name -> adapter module. higgsfield-mcp (agent) is added in M2.T5.
_ADAPTERS: dict[str, str] = {
    "mock": "content_automation.ai.video.providers.mock",
}


class VideoError(Exception):
    """Base class for video capability errors."""

    retryable = False


class VideoRequestError(VideoError, ValueError):
    """The request is invalid (for example, a missing start image)."""


class UnknownVideoProviderError(VideoError):
    """VIDEO_PROVIDER names an adapter that does not exist."""


class VideoProviderError(VideoError):
    """The provider call failed; ``retryable`` marks temporary failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class VideoRequest(BaseModel):
    """One clip (one plan scene), at most 15 seconds, saved inside job_dir."""

    model_config = ConfigDict(frozen=True)

    step_id: str = Field(pattern=STEP_ID_PATTERN)  # e.g. scene-1
    job_dir: Path
    prompt: str = Field(min_length=1)
    duration_sec: float = Field(gt=0, le=MAX_CLIP_SEC)
    aspect_ratio: VideoAspect = "9:16"
    start_image_path: Path | None = None
    start_image_asset_id: str | None = None


class VideoProvider(Protocol):
    """Adapter contract. Each adapter module exposes ``create_provider(settings)``."""

    name: str
    mode: AdapterMode

    def generate(self, request: VideoRequest, model: str) -> JobStep: ...


def clip_path(request: VideoRequest) -> Path:
    return request.job_dir / CLIPS_DIR / f"{request.step_id}.mp4"


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def get_provider(name: str, settings: Settings | None = None) -> VideoProvider:
    """Load the adapter registered under ``name``; creating it makes no provider call."""
    module_name = _ADAPTERS.get(name)
    if module_name is None:
        raise UnknownVideoProviderError(
            f"Video provider '{name}' is not available. Set VIDEO_PROVIDER to one of: "
            f"{', '.join(available_providers())}."
        )
    provider: VideoProvider = importlib.import_module(module_name).create_provider(settings)
    return provider


def generate_video(request: VideoRequest, settings: Settings | None = None) -> JobStep:
    """Make one clip (code adapter) or request it from the agent (agent adapter)."""
    settings = settings or load_settings()
    if request.start_image_path is not None and not request.start_image_path.is_file():
        raise VideoRequestError(f"Start image not found: {request.start_image_path}.")
    provider = get_provider(settings.video_provider, settings)
    step = provider.generate(request, settings.video_model)
    problem = step_problem(step, request.job_dir)
    if problem:
        raise VideoProviderError(problem)
    return step
