from pathlib import Path
from uuid import uuid4

import pytest

from content_automation.core.config import ConfigurationError, load_settings

SETTING_ENV_NAMES = (
    "USER_NAME",
    "REFERENCES_DIR",
    "OUTPUT_DIR",
    "RESEARCH_DIR",
    "PACKAGES_DIR",
    "IMAGE_PROVIDER",
    "IMAGE_MODEL",
    "IMAGE_DAILY_LIMIT",
    "IMAGE_TIMEOUT_MS",
    "GEMINI_API_KEY",
    "VIDEO_PROVIDER",
    "VIDEO_MODEL",
    "AVATAR_PROVIDER",
    "AVATAR_MODEL",
    "HEYGEN_AVATAR_ID",
    "VOICE_PROVIDER",
    "VOICE_MODEL",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "AGENT_STEP_TIMEOUT_MIN",
    "SCRAPER_PROVIDER",
    "SCRAPER_MODEL",
    "APIFY_TOKEN",
    "RESEARCH_MAX_ITEMS_PER_SOURCE",
    "RESEARCH_LOOKBACK_DAYS",
)


def clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTING_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_create_data_directories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_environment(monkeypatch)
    test_id = uuid4().hex
    monkeypatch.setenv("OUTPUT_DIR", f"outputs/.config-test-{test_id}")
    monkeypatch.setenv("RESEARCH_DIR", f"research/.config-test-{test_id}")
    monkeypatch.setenv("PACKAGES_DIR", f"packages/.config-test-{test_id}")

    settings = load_settings(env_file=None)

    assert settings.references_dir == Path("assets/reference")
    assert settings.output_dir.is_dir()
    assert settings.research_dir.is_dir()
    assert settings.packages_dir.is_dir()
    assert settings.image_provider == "mock"
    for directory in (settings.output_dir, settings.research_dir, settings.packages_dir):
        directory.rmdir()


def test_unknown_dotenv_values_are_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_environment(monkeypatch)

    settings = load_settings(env_file=".env.example", create_directories=False)

    assert settings.user_name == "Your Name"


def test_invalid_values_are_named_without_echoing_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "not-a-provider")
    monkeypatch.setenv("IMAGE_DAILY_LIMIT", "0")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-secret-value")

    with pytest.raises(ConfigurationError) as caught:
        load_settings(env_file=None, create_directories=False)

    message = str(caught.value)
    assert "IMAGE_PROVIDER" in message
    assert "IMAGE_DAILY_LIMIT" in message
    assert "synthetic-secret-value" not in message


def test_live_image_provider_names_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_environment(monkeypatch)
    monkeypatch.setenv("IMAGE_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")

    with pytest.raises(ConfigurationError, match="GEMINI_API_KEY"):
        load_settings(env_file=None, create_directories=False)
