"""Validated application settings with secret-safe errors and summaries."""

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ImageProvider = Literal["mock", "openrouter", "template", "higgsfield_soul"]
# Roman's images: Higgsfield Soul 2.0 via Codex (PRD v6 R5: the only route for Roman)
RomanImageProvider = Literal["higgsfield_soul"]
# PRD v6 R8: the old flat output folders. An .env that still names one runs with the new tree
# (`ca doctor` names the line to change); any other path is used as given.
LEGACY_PATHS: dict[str, tuple[str, str]] = {
    "output_dir": ("outputs/jobs", "outputs/_system/jobs"),
    "packages_dir": ("outputs/content", "outputs"),
}
# "none": no provider is set; a content package then keeps its video pending.
# Agent providers are Codex plugins: Codex makes the clip, the app records it.
VideoProvider = Literal["none", "mock", "higgsfield-plugin"]
# "none" (default): no voiceover step runs; the MVP videos have no voiceover.
VoiceProvider = Literal["none", "mock", "elevenlabs"]
# "free" (default): our own scraper (RSS + article pages); no paid API, no account.
ScraperProvider = Literal["free", "mock"]
DesignSize = Literal["1K", "2K", "4K"]
# Who renders on-image text: "auto" = the app, only for providers that draw no text;
# "always" = the app; "never" = the image model.
TextOverlayMode = Literal["auto", "always", "never"]
# "mock" (default): the Drive layout in a local folder; "drive": Google Drive (`ca drive setup`).
StorageProvider = Literal["mock", "drive", "plugin"]


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
    references_dir: Path = Path("assets/reference")  # photos: git-ignored
    brand_file: Path = Path("config/brand.json")  # tracked; fallback: <references>/brand/
    references_file: Path = Path("config/references.json")  # tracked tags, primaries, masks
    company_file: Path = Path("brand/services.md")  # company profile (people); proof.md beside it
    services_file: Path = Path("config/services.json")  # services for generation (Phase D)
    # v6 (PRD R8): the platform tree under outputs/ (core/output_tree.py); internal files in
    # outputs/_system/ (never uploaded)
    output_dir: Path = Path("outputs/_system/jobs")
    research_dir: Path = Path("research")
    packages_dir: Path = Path("outputs")  # the root of the platform tree
    reports_dir: Path = Path("outputs/_system/reports")  # `ca report month` (Phase 10)
    deliverables_file: Path = Path("config/deliverables.json")  # names the user can ask for
    calendar_file: Path = Path("config/calendar.json")  # weekly cadence: weekday -> deliverable
    calendar_dir: Path = Path("calendar")  # calendar/<YYYY-Www>.csv: git-ignored

    image_provider: ImageProvider = "mock"
    image_model: str = Field(default="openai/gpt-image-2", min_length=1)
    image_parallel: int = Field(default=4, ge=1, le=8)  # OpenRouter images at once (a build)
    legacy_paths: list[str] = Field(default_factory=list)  # v6 R8: old .env path lines
    image_daily_limit: int = Field(default=10, gt=0)
    image_timeout_ms: int = Field(default=120_000, gt=0)
    image_max_retries: int = Field(default=1, ge=0, le=5)
    image_identity_refs_max: int = Field(default=4, ge=1, le=14)
    image_design_size: DesignSize = "2K"  # designed graphics (social_creative); photos stay 1K
    text_overlay: TextOverlayMode = "auto"
    design_system_file: Path = Path("config/design_system.json")
    compose_file: Path = Path("config/compose.json")  # person posts composed in the app
    post_formats_file: Path = Path("config/post_formats.json")  # post and carousel formats
    # The static Instagram carousel's slide images: always OpenRouter (OPENROUTER_API_KEY);
    # IMAGE_PROVIDER=mock keeps them mock.
    carousel_image_model: str = Field(default="openai/gpt-image-2", min_length=1)
    roman_image_provider: RomanImageProvider = "higgsfield_soul"
    default_identity_set: str = Field(default="identity/person_01", min_length=1)
    openrouter_api_key: SecretStr | None = None

    video_provider: VideoProvider = "mock"
    video_model: str = Field(default="mock", min_length=1)
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

    storage_provider: StorageProvider = "mock"
    drive_share_with: str = ""  # comma-separated emails: editors of the main Drive folder
    secrets_dir: Path = Path(".secrets")  # OAuth client, token, Drive folder IDs: git-ignored
    drive_mock_dir: Path = Path("outputs/_system/drive-mock")  # STORAGE_PROVIDER=mock
    # STORAGE_PROVIDER=plugin: the Drive folder IDs (root, platforms, Calendar) and the local
    # Content Tracker CSV whose rows the Drive plugin writes (storage/manifest.py).
    drive_folders_file: Path = Path("config/drive_folders.json")
    tracker_csv_file: Path = Path("outputs/_system/tracker.csv")
    state_dir: Path = Path("state")  # registry.db, backups, dry runs: git-ignored
    registry_file: Path = Path("config/registry.json")  # the first BG number (next_id)
    jobs_file: Path = Path("config/jobs.json")  # free providers, units, timeouts, estimates
    tracker_file: Path = Path("config/tracker.json")  # the registry's tracker column names
    strategy_file: Path = Path("config/strategy.json")  # pillars, audiences (Phase 5)
    content_file: Path = Path("config/content.json")  # content language (Phase 5)
    newsletters_file: Path = Path("config/newsletters.json")  # senders, fetch limits (Phase 5)
    formulas_file: Path = Path("config/formulas.json")  # editorial formulas (Phase 6)
    storage_file: Path = Path("config/storage.json")  # upload after review (Phase 7)
    production_file: Path = Path("config/production.json")  # targets, final rules (Phase 8)
    clips_file: Path = Path("config/clips.json")  # Opus Pro clips (Phase 9)
    platforms_file: Path = Path("config/platforms.json")  # variant sizes (Phase 9)
    publishing_file: Path = Path("config/publishing.json")  # integrations (Phase 9: none)

    @model_validator(mode="wrap")
    @classmethod
    def _legacy_paths(cls, data: Any, handler: Any) -> Any:
        legacy: list[str] = []
        if isinstance(data, dict):
            for name, (old, new) in LEGACY_PATHS.items():
                for key in (name, name.upper()):
                    value = data.get(key)
                    if isinstance(value, (str, Path)) and Path(value).as_posix().strip(
                            "/") == old:
                        legacy.append(f"{name.upper()}={old} -> {new}")
                        data = {**data, key: new}
        settings = handler(data)
        settings.legacy_paths = legacy
        return settings

    def summary_lines(self) -> tuple[str, ...]:
        """Return non-secret settings suitable for local CLI output."""
        return (
            f"User: {self.user_name}",
            "Paths: "
            f"references={self.references_dir}, outputs={self.output_dir}, "
            f"research={self.research_dir}, packages={self.packages_dir}",
            f"Image: {self.image_provider} ({self.image_model})",
            f"Video: {self.video_provider} ({self.video_model})",
            f"Voice: {self.voice_provider} ({self.voice_model})",
            f"Research: {self.scraper_provider} (sources: {self.sources_file})",
            f"Storage: {self.storage_provider}",
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
