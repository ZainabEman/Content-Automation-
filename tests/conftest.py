from collections.abc import Callable
from pathlib import Path

import pytest

from content_automation.core.config import Settings, load_settings

SETTING_ENV_NAMES = tuple(name.upper() for name in Settings.model_fields)


def clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in SETTING_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every setting variable inherited from the shell."""
    clear_settings_environment(monkeypatch)


@pytest.fixture
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Run in an empty temp folder with no real .env and no inherited settings."""
    clear_settings_environment(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    return tmp_path


@pytest.fixture
def make_settings(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    def factory(**env: str) -> Settings:
        for name, value in env.items():
            monkeypatch.setenv(name.upper(), value)
        return load_settings(env_file=None)

    return factory
