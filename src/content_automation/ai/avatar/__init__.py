"""Avatar video capability: the only public entry point for talking-avatar providers.

App code calls ``generate_avatar_video()``; adapters live in ``providers/`` and are chosen
by ``AVATAR_PROVIDER`` (adapter) and ``AVATAR_MODEL`` (model passed to the adapter).
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

AvatarAspect = Literal["9:16", "16:9", "1:1", "4:5"]
MAX_CLIP_SEC = 15
STEP_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"
CLIPS_DIR = "clips"

# Provider name -> adapter module. Adding a provider = one adapter file + one line here.
_ADAPTERS: dict[str, str] = {
    "heygen-mcp": "content_automation.ai.avatar.providers.heygen_mcp",
    "mock": "content_automation.ai.avatar.providers.mock",
}


class AvatarError(Exception):
    """Base class for avatar capability errors."""

    retryable = False


class UnknownAvatarProviderError(AvatarError):
    """AVATAR_PROVIDER names an adapter that does not exist."""


class AvatarProviderError(AvatarError):
    """The provider call failed; ``retryable`` marks temporary failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AvatarRequest(BaseModel):
    """One avatar clip (one plan scene), at most 15 seconds, saved inside job_dir."""

    model_config = ConfigDict(frozen=True)

    step_id: str = Field(pattern=STEP_ID_PATTERN)  # e.g. scene-2
    job_dir: Path
    script: str = Field(min_length=1)  # what the avatar says
    duration_sec: float = Field(gt=0, le=MAX_CLIP_SEC)
    aspect_ratio: AvatarAspect = "9:16"
    avatar_id: str | None = None  # default: HEYGEN_AVATAR_ID


class AvatarProvider(Protocol):
    """Adapter contract. Each adapter module exposes ``create_provider(settings)``."""

    name: str
    mode: AdapterMode

    def generate(self, request: AvatarRequest, model: str) -> JobStep: ...


def clip_path(request: AvatarRequest) -> Path:
    return request.job_dir / CLIPS_DIR / f"{request.step_id}.mp4"


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def get_provider(name: str, settings: Settings | None = None) -> AvatarProvider:
    """Load the adapter registered under ``name``; creating it makes no provider call."""
    module_name = _ADAPTERS.get(name)
    if module_name is None:
        raise UnknownAvatarProviderError(
            f"Avatar provider '{name}' is not available. Set AVATAR_PROVIDER to one of: "
            f"{', '.join(available_providers())}."
        )
    provider: AvatarProvider = importlib.import_module(module_name).create_provider(settings)
    return provider


def generate_avatar_video(request: AvatarRequest, settings: Settings | None = None) -> JobStep:
    """Make one avatar clip (code adapter) or request it from the agent (agent adapter)."""
    settings = settings or load_settings()
    provider = get_provider(settings.avatar_provider, settings)
    step = provider.generate(request, settings.avatar_model)
    problem = step_problem(step, request.job_dir)
    if problem:
        raise AvatarProviderError(problem)
    return step
