"""Phase 10 Step 2: `ca verify list|run|record` (offline; fakes only)."""

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner, Result

from content_automation.cli import app

REPO = Path(__file__).resolve().parents[2]


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def test_verify_run_record_list(isolated: Path) -> None:
    (isolated / "config").mkdir()
    shutil.copy(REPO / "config" / "publishing.json", isolated / "config" / "publishing.json")

    passed = ca("verify", "run", "publishing")
    assert passed.exit_code == 0, passed.output
    assert "published without a URL is refused" in passed.output
    assert "publishing: offline pass" in passed.output
    missing = ca("verify", "run", "gmail")  # no config/newsletters.json here
    assert missing.exit_code == 1 and "config missing" in missing.output
    assert ca("verify", "run", "nope").exit_code == 2

    listed = ca("verify", "list")
    assert listed.exit_code == 0, listed.output
    assert "publishing (publishing (manual URL)): not operational (no recorded live pass)" \
        in listed.output
    assert "0 of 10 operational" in listed.output  # v6 R5: the image-server check is gone

    assert ca("verify", "record", "publishing", "--live", "maybe", "x").exit_code == 2
    recorded = ca("verify", "record", "publishing", "--live", "pass", "posted on LinkedIn")
    assert recorded.exit_code == 0 and "operational" in recorded.output, recorded.output
    rows = json.loads(ca("verify", "list", "--json").output)
    states = {row["name"]: (row["offline"], row["live"], row["operational"]) for row in rows}
    assert states["publishing"] == ("pass", "pass", True)
    assert states["gmail"] == ("fail", None, False)
    assert "1 of 10 operational" in ca("verify", "list").output
