"""Offline mock adapter: a coloured MP4 card showing the prompt, at the requested
duration and aspect ratio. VIDEO_MODEL=mock-fail raises a provider error."""

from content_automation.ai.video import (
    VideoProviderError,
    VideoRequest,
    clip_path,
)
from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode, JobStep
from content_automation.core.media import MediaError, placeholder_clip


class MockVideoProvider:
    name = "mock"
    mode: AdapterMode = "code"

    def generate(self, request: VideoRequest, model: str) -> JobStep:
        if model == "mock-fail":
            raise VideoProviderError("Mock provider failure (VIDEO_MODEL=mock-fail).")
        target = clip_path(request)
        start = " · start image" if request.start_image_path else ""
        try:
            placeholder_clip(
                target,
                title=f"MOCK VIDEO {request.step_id} · {request.duration_sec:g}s{start}",
                text=request.prompt,
                duration_sec=request.duration_sec,
                aspect_ratio=request.aspect_ratio,
            )
        except MediaError as error:
            raise VideoProviderError(f"Mock clip failed: {error}") from None
        return JobStep(
            step_id=request.step_id,
            capability="video",
            provider=self.name,
            mode="code",
            status="completed",
            file=target.relative_to(request.job_dir).as_posix(),
        )


def create_provider(settings: Settings | None = None) -> MockVideoProvider:
    return MockVideoProvider()
