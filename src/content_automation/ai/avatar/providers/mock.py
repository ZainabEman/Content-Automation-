"""Offline mock adapter: a coloured MP4 card showing the avatar's script, at the requested
duration and aspect ratio. AVATAR_MODEL=mock-fail raises a provider error."""

from content_automation.ai.avatar import AvatarProviderError, AvatarRequest, clip_path
from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode, JobStep
from content_automation.core.media import MediaError, placeholder_clip


class MockAvatarProvider:
    name = "mock"
    mode: AdapterMode = "code"

    def __init__(self, default_avatar_id: str | None = None) -> None:
        self._default_avatar_id = default_avatar_id

    def generate(self, request: AvatarRequest, model: str) -> JobStep:
        if model == "mock-fail":
            raise AvatarProviderError("Mock provider failure (AVATAR_MODEL=mock-fail).")
        target = clip_path(request)
        avatar = request.avatar_id or self._default_avatar_id or "default"
        try:
            placeholder_clip(
                target,
                title=f"MOCK AVATAR {request.step_id} · {avatar} · {request.duration_sec:g}s",
                text=request.script,
                duration_sec=request.duration_sec,
                aspect_ratio=request.aspect_ratio,
                background=(49, 46, 129),
            )
        except MediaError as error:
            raise AvatarProviderError(f"Mock clip failed: {error}") from None
        return JobStep(
            step_id=request.step_id,
            capability="avatar",
            provider=self.name,
            mode="code",
            status="completed",
            file=target.relative_to(request.job_dir).as_posix(),
        )


def create_provider(settings: Settings | None = None) -> MockAvatarProvider:
    return MockAvatarProvider(settings.heygen_avatar_id if settings else None)
