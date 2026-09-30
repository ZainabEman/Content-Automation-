"""Offline mock adapter: a quiet tone as long as the text would take to say, with
fake word timings spread over it. VOICE_MODEL=mock-fail raises a provider error."""

import uuid

from content_automation.ai.voice import (
    VoiceAudio,
    VoiceProviderError,
    VoiceRequest,
    WordTiming,
    estimate_speech_sec,
)
from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode
from content_automation.core.media import MediaError, tone_mp3


class MockVoiceProvider:
    name = "mock"
    mode: AdapterMode = "code"

    def synthesize(self, request: VoiceRequest, model: str) -> VoiceAudio:
        if model == "mock-fail":
            raise VoiceProviderError("Mock provider failure (VOICE_MODEL=mock-fail).")
        duration = estimate_speech_sec(request.text)
        try:
            data = tone_mp3(duration)
        except MediaError as error:
            raise VoiceProviderError(f"Mock voice failed: {error}") from None
        return VoiceAudio(
            data=data,
            words=_fake_timings(request.text.split(), duration),
            duration_sec=duration,
            provider_request_id=f"mock-{uuid.uuid4().hex[:12]}",
            credits_used=0.0,
        )


def _fake_timings(tokens: list[str], duration: float) -> list[WordTiming]:
    """Longer words get more time; each word ends slightly before the next starts."""
    weights = [len(token) + 1 for token in tokens]
    total = sum(weights)
    words: list[WordTiming] = []
    elapsed = 0.0
    for token, weight in zip(tokens, weights, strict=True):
        span = duration * weight / total
        words.append(
            WordTiming(
                word=token,
                start_sec=round(elapsed, 3),
                end_sec=round(elapsed + span * 0.9, 3),
            )
        )
        elapsed += span
    return words


def create_provider(settings: Settings | None = None) -> MockVoiceProvider:
    return MockVoiceProvider()
