"""`ca help commands` lists every phrase of the AGENTS.md Skills map."""

import re
from pathlib import Path

from typer.testing import CliRunner

from content_automation.cli import app

AGENTS = Path(__file__).resolve().parents[1] / "AGENTS.md"


def agents_phrases() -> list[str]:
    """The quoted phrases after "Phrases:" on each Skills-map bullet (up to the list's end)."""
    phrases: list[str] = []
    for line in AGENTS.read_text(encoding="utf-8").splitlines():
        if not line.startswith("- ") or "Phrases:" not in line:
            continue
        segment = line.split("Phrases:", 1)[1]
        end = re.search(r'"\.(\s|$)', segment)
        segment = segment[: end.start() + 1] if end else ""
        phrases += re.findall(r'"([^"]+)"', segment)
    return phrases


def test_every_agents_phrase_is_in_ca_help_commands() -> None:
    phrases = agents_phrases()
    assert len(phrases) >= 30 and "show items" in phrases and "ok" in phrases
    output = CliRunner().invoke(app, ["help", "commands"]).stdout
    missing = [phrase for phrase in phrases if f'"{phrase}"' not in output]
    assert missing == []


def test_help_commands_json() -> None:
    result = CliRunner().invoke(app, ["help", "commands", "--json"])
    assert result.exit_code == 0 and '"skill": "manage-items"' in result.stdout
