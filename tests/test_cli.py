import pytest
from typer.testing import CliRunner

from content_automation.cli import app


def test_hello_never_prints_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-cli-secret")
    result = CliRunner().invoke(app, ["hello"])

    assert result.exit_code == 0
    assert "Hello," in result.output
    assert "credential values hidden" in result.output
    assert "synthetic-cli-secret" not in result.output
