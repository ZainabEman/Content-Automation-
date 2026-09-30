"""Voice capability: the only public entry point for text-to-speech providers.

App code calls ``generate_voice()``; adapters live in ``providers/`` and are chosen by
``VOICE_PROVIDER`` (adapter) and ``VOICE_MODEL`` (model passed to the adapter).
It saves <stepId>.mp3 (default voice.mp3) and <stepId>-timings.json with word timings;
``write_captions()`` turns word timings into captions.srt.
"""

import importlib
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from content_automation.core.config import Settings, load_settings
from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.core.jobs import AdapterMode, JobStep

MAX_TEXT_CHARS = 5000
WORDS_PER_MINUTE = 150  # used to estimate speech length
STEP_ID_PATTERN = r"^[a-z0-9][a-z0-9_-]*$"
TIMINGS_SUFFIX = "-timings.json"
VOICE_OFF = "none"  # VOICE_PROVIDER=none: voiceover disabled (MVP)

# Provider name -> adapter module. Adding a provider = one adapter file + one line here.
_ADAPTERS: dict[str, str] = {
    "mock": "content_automation.ai.voice.providers.mock",
    "elevenlabs": "content_automation.ai.voice.providers.elevenlabs",
}


class VoiceError(Exception):
    """Base class for voice capability errors."""

    retryable = False


class UnknownVoiceProviderError(VoiceError):
    """VOICE_PROVIDER names an adapter that does not exist."""


class VoiceProviderError(VoiceError):
    """The provider call failed; ``retryable`` marks temporary failures."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class VoiceTimeoutError(VoiceProviderError, TimeoutError):
    """The provider did not respond in time."""


class WordTiming(CamelModel):
    word: str
    start_sec: float
    end_sec: float


class VoiceTimings(CamelModel):
    """The <stepId>-timings.json file."""

    duration_sec: float
    words: list[WordTiming]


class VoiceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_id: str = Field(default="voice", pattern=STEP_ID_PATTERN)
    job_dir: Path
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)
    voice_id: str | None = None  # default: the adapter's (ELEVENLABS_VOICE_ID)


class VoiceAudio(BaseModel):
    """What an adapter returns; generate_voice() saves it."""

    data: bytes
    extension: str = "mp3"
    words: list[WordTiming]
    duration_sec: float
    provider_request_id: str | None = None
    credits_used: float | None = None


class VoiceResult(BaseModel):
    step: JobStep
    audio_path: Path
    timings_path: Path
    words: list[WordTiming]
    duration_sec: float


class VoiceProvider(Protocol):
    """Adapter contract. Each adapter module exposes ``create_provider(settings)``."""

    name: str
    mode: AdapterMode

    def synthesize(self, request: VoiceRequest, model: str) -> VoiceAudio: ...


def available_providers() -> tuple[str, ...]:
    return tuple(sorted(_ADAPTERS))


def get_provider(name: str, settings: Settings | None = None) -> VoiceProvider:
    """Load the adapter registered under ``name``; creating it makes no provider call."""
    module_name = _ADAPTERS.get(name)
    if module_name is None:
        raise UnknownVoiceProviderError(
            f"Voice provider '{name}' is not available. Set VOICE_PROVIDER to one of: "
            f"{', '.join(available_providers())}."
        )
    provider: VoiceProvider = importlib.import_module(module_name).create_provider(settings)
    return provider


def generate_voice(request: VoiceRequest, settings: Settings | None = None) -> VoiceResult:
    """Make the voiceover; save the audio and word timings in the job folder."""
    settings = settings or load_settings()
    if settings.voice_provider == VOICE_OFF:
        raise VoiceError("Voiceover is disabled (VOICE_PROVIDER=none).")
    provider = get_provider(settings.voice_provider, settings)
    audio = provider.synthesize(request, settings.voice_model)
    if not audio.data:
        raise VoiceProviderError(f"{provider.name} returned no audio.")
    if not audio.words:
        raise VoiceProviderError(f"{provider.name} returned no word timings.")
    request.job_dir.mkdir(parents=True, exist_ok=True)
    audio_path = request.job_dir / f"{request.step_id}.{audio.extension}"
    timings_path = request.job_dir / f"{request.step_id}{TIMINGS_SUFFIX}"
    audio_path.write_bytes(audio.data)
    timings = VoiceTimings(duration_sec=audio.duration_sec, words=audio.words)
    atomic_write_text(timings_path, timings.model_dump_json(by_alias=True, indent=2) + "\n")
    step = JobStep(
        step_id=request.step_id,
        capability="voice",
        provider=provider.name,
        mode=provider.mode,
        status="completed",
        file=audio_path.name,
        provider_job_id=audio.provider_request_id,
        credits_used=audio.credits_used,
    )
    return VoiceResult(
        step=step,
        audio_path=audio_path,
        timings_path=timings_path,
        words=audio.words,
        duration_sec=audio.duration_sec,
    )


def estimate_speech_sec(text: str) -> float:
    return max(1.0, round(len(text.split()) * 60 / WORDS_PER_MINUTE, 2))


def words_from_characters(
    characters: Sequence[str], starts: Sequence[float], ends: Sequence[float]
) -> list[WordTiming]:
    """Group per-character timings (as ElevenLabs returns them) into words."""
    if not len(characters) == len(starts) == len(ends):
        raise ValueError("Character timing lists have different lengths.")
    words: list[WordTiming] = []
    letters: list[str] = []
    start = end = 0.0

    def add_word() -> None:
        words.append(
            WordTiming(word="".join(letters), start_sec=round(start, 3), end_sec=round(end, 3))
        )
        letters.clear()

    for char, char_start, char_end in zip(characters, starts, ends, strict=True):
        if char.isspace():
            if letters:
                add_word()
            continue
        if not letters:
            start = char_start
        letters.append(char)
        end = char_end
    if letters:
        add_word()
    return words


def load_timings(path: Path) -> VoiceTimings:
    return VoiceTimings.model_validate_json(path.read_text(encoding="utf-8"))


def captions_srt(
    words: Sequence[WordTiming],
    *,
    max_words: int = 5,
    max_chars: int = 32,
    max_gap_sec: float = 0.6,
) -> str:
    """Short caption cues for burned-in subtitles: a new cue after a sentence end,
    a pause, or when the line gets too long."""
    cues: list[list[WordTiming]] = []
    for word in words:
        current = cues[-1] if cues else None
        if (
            current is None
            or len(current) >= max_words
            or len(" ".join(w.word for w in [*current, word])) > max_chars
            or word.start_sec - current[-1].end_sec > max_gap_sec
            or current[-1].word.endswith((".", "!", "?"))
        ):
            cues.append([word])
        else:
            current.append(word)
    blocks: list[str] = []
    for index, cue in enumerate(cues):
        start = cue[0].start_sec
        end = max(cue[-1].end_sec, start + 0.3)
        if index + 1 < len(cues):
            end = min(end, cues[index + 1][0].start_sec)
        text = " ".join(w.word for w in cue)
        blocks.append(f"{index + 1}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")
    return "\n".join(blocks)


def write_captions(words: Sequence[WordTiming], path: Path) -> None:
    atomic_write_text(path, captions_srt(words))


def _srt_time(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, rest = divmod(millis, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
