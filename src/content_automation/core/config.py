"""Validated application settings with secret-safe errors and summaries."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

ImageProvider = Literal["mock", "openrouter"]
# "none": no provider is set; a content package then keeps its video pending.
# Agent providers are Codex plugins: Codex makes the clip, the app records it.
VideoProvider = Literal["none", "mock", "higgsfield-plugin"]
AvatarProvider = Literal["none", "mock", "heygen-plugin"]
# "none" (default): no voiceover step runs; the MVP videos have no voiceover.
VoiceProvider = Literal["none", "mock", "elevenlabs"]
# "free" (default): our own scraper (RSS + article pages); no paid API, no account.
ScraperProvider = Literal["free", "mock"]
DesignSize = Literal["1K", "2K", "4K"]


class ConfigurationError(ValueError):
    """A sanitized configuration error that never includes input values."""


class Settings(BaseSettings):
    """Settings loaded from the environment and the local .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        str_strip_whitespace=True,
    )

    user_name: str = Field(default="User", min_length=1)
    references_dir: Path = Path("assets/reference")
    company_file: Path = Path("docs/company/services.md")
    output_dir: Path = Path("outputs/jobs")
    research_dir: Path = Path("research")
    packages_dir: Path = Path("outputs/content")
    deliverables_file: Path = Path("config/deliverables.json")  # names the user can ask for

    image_provider: ImageProvider = "mock"
    image_model: str = Field(default="google/gemini-3.1-flash-image", min_length=1)
    image_daily_limit: int = Field(default=10, gt=0)
    image_timeout_ms: int = Field(default=120_000, gt=0)
    image_max_retries: int = Field(default=1, ge=0, le=5)
    image_identity_refs_max: int = Field(default=4, ge=1, le=14)
    image_design_size: DesignSize = "2K"  # designed graphics (social_creative); photos stay 1K
    design_system_file: Path = Path("config/design_system.json")
    default_identity_set: str = Field(default="identity/person_01", min_length=1)
    openrouter_api_key: SecretStr | None = None

    video_provider: VideoProvider = "mock"
    video_model: str = Field(default="mock", min_length=1)
    avatar_provider: AvatarProvider = "mock"
    avatar_model: str = Field(default="mock", min_length=1)
    heygen_avatar_id: str | None = None  # the person's own HeyGen avatar
    heygen_voice_id: str | None = None  # passed with every HeyGen clip (never the default voice)
    voice_provider: VoiceProvider = "none"
    voice_model: str = Field(default="mock", min_length=1)
    elevenlabs_api_key: SecretStr | None = None
    elevenlabs_voice_id: str | None = None
    agent_step_timeout_min: int = Field(default=30, gt=0)

    scraper_provider: ScraperProvider = "free"
    scraper_model: str = Field(default="default", min_length=1)  # not used by free/mock
    sources_file: Path = Path("config/sources.json")
    research_max_items_per_source: int = Field(default=25, gt=0)
    research_lookback_days: int = Field(default=30, gt=0)

    def summary_lines(self) -> tuple[str, ...]:
        """Return non-secret settings suitable for local CLI output."""
        return (
            f"User: {self.user_name}",
            "Paths: "
            f"references={self.references_dir}, outputs={self.output_dir}, "
            f"research={self.research_dir}, packages={self.packages_dir}",
            f"Image: {self.image_provider} ({self.image_model})",
            f"Video: {self.video_provider} ({self.video_model})",
            f"Avatar: {self.avatar_provider} ({self.avatar_model})",
            f"Voice: {self.voice_provider} ({self.voice_model})",
            f"Research: {self.scraper_provider} (sources: {self.sources_file})",
            "Credential values: hidden",
        )


def _invalid_names(error: ValidationError) -> list[str]:
    names = {
        "_".join(str(part) for part in issue["loc"]).upper()
        for issue in error.errors(include_input=False)
    }
    return sorted(names)


def _secret_is_set(secret: SecretStr | None) -> bool:
    return secret is not None and bool(secret.get_secret_value().strip())


def load_settings(
    env_file: str | Path | None = ".env",
    *,
    create_directories: bool = True,
    require_credentials: bool = True,
) -> Settings:
    """Load settings, report only variable names, and create data folders.

    require_credentials=False skips the API-key check (dry runs make no calls).
    """
    try:
        settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as error:
        names = ", ".join(_invalid_names(error))
        raise ConfigurationError(
            f"Missing or invalid environment variables: {names}."
        ) from None

    missing: list[str] = []
    if settings.image_provider == "openrouter" and not _secret_is_set(
        settings.openrouter_api_key
    ):
        missing.append("OPENROUTER_API_KEY")
    if settings.voice_provider == "elevenlabs" and not _secret_is_set(
        settings.elevenlabs_api_key
    ):
        missing.append("ELEVENLABS_API_KEY")
    if missing and require_credentials:
        names = ", ".join(sorted(missing))
        raise ConfigurationError(
            f"{names} missing: add it to .env to use the selected provider."
        )

    if create_directories:
        for directory in (
            settings.output_dir,
            settings.research_dir,
            settings.packages_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    return settings
