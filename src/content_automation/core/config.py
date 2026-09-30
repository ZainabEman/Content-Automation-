"""Validated application settings with secret-safe errors and summaries."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

ImageProvider = Literal["mock", "gemini"]
VideoProvider = Literal["mock", "higgsfield-mcp"]
AvatarProvider = Literal["mock", "heygen-mcp"]
VoiceProvider = Literal["mock", "elevenlabs"]
ScraperProvider = Literal["mock", "apify"]


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
    output_dir: Path = Path("outputs")
    research_dir: Path = Path("research")
    packages_dir: Path = Path("packages")

    image_provider: ImageProvider = "mock"
    image_model: str = Field(default="gemini-3.1-flash-image", min_length=1)
    image_daily_limit: int = Field(default=10, gt=0)
    image_timeout_ms: int = Field(default=120_000, gt=0)
    gemini_api_key: SecretStr | None = None

    video_provider: VideoProvider = "mock"
    video_model: str = Field(default="mock", min_length=1)
    avatar_provider: AvatarProvider = "mock"
    avatar_model: str = Field(default="mock", min_length=1)
    heygen_avatar_id: str | None = None
    voice_provider: VoiceProvider = "mock"
    voice_model: str = Field(default="mock", min_length=1)
    elevenlabs_api_key: SecretStr | None = None
    elevenlabs_voice_id: str | None = None
    agent_step_timeout_min: int = Field(default=30, gt=0)

    scraper_provider: ScraperProvider = "mock"
    scraper_model: str = Field(default="mock", min_length=1)
    apify_token: SecretStr | None = None
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
            f"Research: {self.scraper_provider} ({self.scraper_model})",
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
) -> Settings:
    """Load settings, report only variable names, and create data folders."""
    try:
        settings = Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as error:
        names = ", ".join(_invalid_names(error))
        raise ConfigurationError(
            f"Missing or invalid environment variables: {names}."
        ) from None

    missing: list[str] = []
    if settings.image_provider == "gemini" and not _secret_is_set(settings.gemini_api_key):
        missing.append("GEMINI_API_KEY")
    if settings.voice_provider == "elevenlabs" and not _secret_is_set(
        settings.elevenlabs_api_key
    ):
        missing.append("ELEVENLABS_API_KEY")
    if settings.scraper_provider == "apify" and not _secret_is_set(settings.apify_token):
        missing.append("APIFY_TOKEN")
    if missing:
        names = ", ".join(sorted(missing))
        raise ConfigurationError(f"Missing or invalid environment variables: {names}.")

    if create_directories:
        for directory in (
            settings.output_dir,
            settings.research_dir,
            settings.packages_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    return settings
