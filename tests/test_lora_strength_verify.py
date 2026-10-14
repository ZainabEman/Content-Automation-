"""Track L Step 3: `ca lora strength` (logged) and the offline `ca verify run comfyui`."""

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.core.config import Settings
from content_automation.lora import set_lora
from content_automation.registry import db_path, open_registry
from content_automation.registry.audit import list_events

REPO = Path(__file__).resolve().parents[1]


def _config(isolated: Path) -> Path:
    (isolated / "config").mkdir()
    for name in ("comfyui.json", "lora.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    return isolated / "config" / "comfyui.json"


def test_lora_strength_is_written_and_logged(isolated: Path) -> None:
    config = _config(isolated)
    changed = CliRunner().invoke(app, ["lora", "strength", "0.9"])
    assert changed.exit_code == 0, changed.output
    assert json.loads(config.read_text(encoding="utf-8"))["loraStrength"] == 0.9
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    try:
        events = list_events(conn, types=["config_changed"])
    finally:
        conn.close()
    assert events and events[-1].details["to"] == 0.9
    assert CliRunner().invoke(app, ["lora", "strength", "1.5"]).exit_code == 1


def test_verify_comfyui_checks_the_lora_offline(isolated: Path,
                                                make_settings: Callable[..., Settings]) -> None:
    _config(isolated)
    lora = isolated / "outputs" / "lora" / "zimage" / "r0man_test.safetensors"
    lora.parent.mkdir(parents=True)
    lora.write_bytes(b"weights")
    (lora.parent / "MANIFEST.json").write_text(
        json.dumps({"sha256": hashlib.sha256(b"weights").hexdigest()}), encoding="utf-8")
    set_lora(make_settings(), "zimage", lora.as_posix())

    passed = CliRunner().invoke(app, ["verify", "run", "comfyui"])
    assert passed.exit_code == 0, passed.output
    assert "sha256 matches; LoraLoaderModelOnly node; model files match config" in passed.output
    assert "live test needs RUNPOD_ENDPOINT_ID: not set" in passed.output
    lora.write_bytes(b"changed")
    failed = CliRunner().invoke(app, ["verify", "run", "comfyui"])
    assert failed.exit_code == 1 and "sha256 does not match" in failed.output
