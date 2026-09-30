import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_automation.cli import app


@pytest.mark.usefixtures("isolated")
def test_hello_never_prints_secret_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-cli-secret")
    result = CliRunner().invoke(app, ["hello"])

    assert result.exit_code == 0
    assert "Hello," in result.output
    assert "credential values hidden" in result.output
    assert "synthetic-cli-secret" not in result.output


def test_image_command_end_to_end(isolated: Path) -> None:
    result = CliRunner().invoke(
        app, ["image", "--prompt", "test", "--count", "2", "--aspect", "4:5",
              "--request", "two test images"]
    )

    assert result.exit_code == 0, result.output
    folder = Path(result.stdout.strip())
    assert folder.parent.parent == isolated / "outputs"
    names = sorted(p.name for p in folder.iterdir())
    assert names == ["details.json", "image-1.png", "image-2.png"]
    details = json.loads((folder / "details.json").read_text(encoding="utf-8"))
    assert details["status"] == "completed"
    assert details["request"] == "two test images"


def test_image_command_failure_exits_non_zero(
    isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("IMAGE_MODEL", "mock-fail")
    result = CliRunner().invoke(app, ["image", "--prompt", "test"])

    assert result.exit_code == 1
    [details] = (isolated / "outputs").glob("*/*/details.json")
    assert json.loads(details.read_text(encoding="utf-8"))["status"] == "failed"


@pytest.mark.usefixtures("isolated")
def test_image_command_rejects_bad_aspect() -> None:
    result = CliRunner().invoke(app, ["image", "--prompt", "test", "--aspect", "3:2"])

    assert result.exit_code == 1
    assert "Aspect must be one of" in result.output
