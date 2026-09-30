"""ElevenLabs text-to-speech with timestamps (code adapter, elevenlabs SDK >= 2.70).

One ``text_to_speech.convert_with_timestamps`` call
(POST /v1/text-to-speech/{voice_id}/with-timestamps) returns base64 MP3 plus start/end
times per character, grouped here into words. The raw response headers give the
request ID (``request-id``) and the credits charged (``character-cost``).
See https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps.
"""

import base64
import binascii
from collections.abc import Callable
from typing import Any

from content_automation.ai.voice import (
    VoiceAudio,
    VoiceProviderError,
    VoiceRequest,
    VoiceTimeoutError,
    words_from_characters,
)
from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode
from content_automation.core.retry import OperationTimeoutError, call_with_retry

MISSING_KEY = "ELEVENLABS_API_KEY missing: add it to .env to use VOICE_PROVIDER=elevenlabs."
MISSING_VOICE = "No voice ID: set voice.voiceId in plan.json or ELEVENLABS_VOICE_ID in .env."
MOCK_MODEL = (
    "VOICE_MODEL is 'mock': set it to an ElevenLabs model such as eleven_multilingual_v2."
)
OUTPUT_FORMAT = "mp3_44100_128"
TIMEOUT_S = 120.0
MAX_RETRIES = 2
_DETAIL_LIMIT = 300

ClientFactory = Callable[[str, float], Any]


def _elevenlabs_client(api_key: str, timeout_s: float) -> Any:
    from elevenlabs import ElevenLabs

    return ElevenLabs(api_key=api_key, timeout=timeout_s)


class ElevenLabsVoiceProvider:
    name = "elevenlabs"
    mode: AdapterMode = "code"

    def __init__(
        self,
        api_key: str | None,
        *,
        default_voice_id: str | None = None,
        timeout_s: float = TIMEOUT_S,
        max_retries: int = MAX_RETRIES,
        client_factory: ClientFactory | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._api_key = api_key
        self._default_voice_id = default_voice_id
        self._timeout_s = timeout_s
        self._max_retries = max_retries
        self._client_factory = client_factory or _elevenlabs_client
        self._sleep = sleep

    def synthesize(self, request: VoiceRequest, model: str) -> VoiceAudio:
        if not self._api_key:
            raise VoiceProviderError(MISSING_KEY)
        voice_id = request.voice_id or self._default_voice_id
        if not voice_id:
            raise VoiceProviderError(MISSING_VOICE)
        if model.startswith("mock"):
            raise VoiceProviderError(MOCK_MODEL)
        client = self._client_factory(self._api_key, self._timeout_s)

        def call() -> Any:
            try:
                return client.text_to_speech.with_raw_response.convert_with_timestamps(
                    voice_id, text=request.text, model_id=model, output_format=OUTPUT_FORMAT
                )
            except Exception as error:
                raise map_error(error) from None

        kwargs: dict[str, Any] = {}
        if self._sleep is not None:
            kwargs["sleep"] = self._sleep
        try:
            response = call_with_retry(
                call, timeout_s=self._timeout_s + 5, max_retries=self._max_retries, **kwargs
            )
        except OperationTimeoutError as error:
            raise VoiceTimeoutError(f"ElevenLabs did not respond in time: {error}") from None
        except VoiceProviderError as error:
            error.retryable = False  # already retried here
            raise
        return _to_audio(response)


def _to_audio(response: Any) -> VoiceAudio:
    data = response.data
    headers = {key.lower(): value for key, value in (response.headers or {}).items()}
    try:
        audio = base64.b64decode(data.audio_base_64, validate=True)
    except (binascii.Error, ValueError, TypeError):
        raise VoiceProviderError("ElevenLabs returned audio that is not valid base64.") from None
    alignment = data.alignment or data.normalized_alignment
    if alignment is None:
        raise VoiceProviderError("ElevenLabs returned no timestamps.")
    try:
        words = words_from_characters(
            alignment.characters,
            alignment.character_start_times_seconds,
            alignment.character_end_times_seconds,
        )
    except ValueError as error:
        raise VoiceProviderError(f"ElevenLabs timestamps are unusable: {error}") from None
    if not audio or not words:
        raise VoiceProviderError("ElevenLabs returned empty audio or no words.")
    return VoiceAudio(
        data=audio,
        extension="mp3",
        words=words,
        duration_sec=round(max(word.end_sec for word in words), 3),
        provider_request_id=headers.get("request-id") or None,
        credits_used=_number(headers.get("character-cost")),
    )


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None


def _short(text: object) -> str:
    return " ".join(str(text).split())[:_DETAIL_LIMIT]


def map_error(error: Exception) -> VoiceProviderError:
    """Translate SDK/HTTP errors: 429 and 5xx retryable; 4xx and others not."""
    if isinstance(error, VoiceProviderError):
        return error
    name = type(error).__name__
    body = getattr(error, "body", None)
    detail = _short(body if body else error) or name
    if isinstance(error, TimeoutError) or "Timeout" in name:
        return VoiceTimeoutError(f"ElevenLabs did not respond in time: {detail}")
    status = getattr(error, "status_code", None)
    if isinstance(status, int):
        if status == 429:
            return VoiceProviderError(
                f"ElevenLabs rate limit or quota reached (HTTP 429): {detail}", retryable=True
            )
        if status >= 500:
            return VoiceProviderError(
                f"ElevenLabs server error (HTTP {status}): {detail}", retryable=True
            )
        if status in (401, 403):
            return VoiceProviderError(
                f"ElevenLabs rejected the API key (HTTP {status}); check ELEVENLABS_API_KEY."
            )
        return VoiceProviderError(f"ElevenLabs rejected the request (HTTP {status}): {detail}")
    if "Connect" in name:
        return VoiceProviderError(f"Could not reach ElevenLabs: {detail}", retryable=True)
    return VoiceProviderError(f"ElevenLabs call failed ({name}): {detail}")


def create_provider(settings: Settings | None = None) -> ElevenLabsVoiceProvider:
    if settings is None:
        return ElevenLabsVoiceProvider(api_key=None)
    key = (
        settings.elevenlabs_api_key.get_secret_value().strip()
        if settings.elevenlabs_api_key
        else None
    )
    return ElevenLabsVoiceProvider(
        api_key=key or None, default_voice_id=settings.elevenlabs_voice_id
    )
