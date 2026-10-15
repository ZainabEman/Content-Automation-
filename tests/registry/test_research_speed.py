"""Live fix: `ca research run` prints a line per source, spreads --limit, keeps partial results."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.research.models import SourceStats
from content_automation.research.run import progress_line

REPO = Path(__file__).resolve().parents[2]


def test_research_run_progress_limit_and_cap(isolated: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    (isolated / "config").mkdir()
    for name in ("strategy.json", "newsletters.json", "sources.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    monkeypatch.setenv("SCRAPER_PROVIDER", "mock")

    result = CliRunner().invoke(app, ["research", "run", "--sources"])  # default --limit 8
    assert result.exit_code == 0, result.output
    assert "Search Engine Journal: 1 new, 0 dup" in result.output
    assert result.output.count("skipped (limit 8 reached)") == 3  # 11 sources, 1 each
    assert "Research run: collected 8," in result.output

    sources = isolated / "config" / "sources.json"
    data = json.loads(sources.read_text(encoding="utf-8"))
    data["run"]["maxRunSeconds"] = 0.001
    sources.write_text(json.dumps(data), encoding="utf-8")
    capped = CliRunner().invoke(app, ["research", "run", "--sources"])
    assert capped.exit_code == 0, capped.output
    assert "skipped (the run's time cap)" in capped.output
    assert "Run cap 0.001 s reached: partial results" in capped.output

    stats = SourceStats(source="heise online", errors=["feed: ReadTimeout: timed out"])
    assert progress_line(stats) == "heise online: timeout"
