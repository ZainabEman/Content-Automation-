from pathlib import Path

import pytest

from content_automation.core.config import ConfigurationError, load_settings


def test_defaults_create_data_directories(isolated: Path) -> None:
    settings = load_settings(env_file=None)

    assert settings.references_dir == Path("assets/reference")
    assert settings.output_dir == isolated / "outputs"
    assert settings.output_dir.is_dir()
    assert settings.research_dir.is_dir()
    assert settings.packages_dir.is_dir()
    assert settings.image_provider == "mock"
    assert settings.image_max_retries == 1


@pytest.mark.usefixtures("clean_env")
def test_unknown_dotenv_values_are_ignored() -> None:
    settings = load_settings(env_file=".env.example", create_directories=False)

    assert settings.user_name == "Your Name"


@pytest.mark.usefixtures("clean_env")
def test_invalid_values_are_named_without_echoing_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMAGE_PROVIDER", "not-a-provider")
    monkeypatch.setenv("IMAGE_DAILY_LIMIT", "0")
    monkeypatch.setenv("IMAGE_MAX_RETRIES", "-1")
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-secret-value")

    with pytest.raises(ConfigurationError) as caught:
        load_settings(env_file=None, create_directories=False)

    message = str(caught.value)
    assert "IMAGE_PROVIDER" in message
    assert "IMAGE_DAILY_LIMIT" in message
    assert "IMAGE_MAX_RETRIES" in message
    assert "synthetic-secret-value" not in message


@pytest.mark.usefixtures("clean_env")
def test_live_image_provider_names_missing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IMAGE_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "")

    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        load_settings(env_file=None, create_directories=False)
