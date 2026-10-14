"""Phase 5 Step 3: sources.json v2, German candidates, `ca research run` (mock HTTP/scraper)."""

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.registry import db_path, open_registry
from content_automation.registry.ideas import get_details, list_ideas
from content_automation.registry.sources import item_sources
from content_automation.research import fetch
from content_automation.research.models import load_sources

REPO = Path(__file__).resolve().parents[2]
PAGE = "<html><head><title>Voice clones</title></head><body><article>" + "".join(
    f"<p>Part {n}: fraudsters use AI voice clones of managers to order transfers.</p>"
    for n in range(8)) + "</article></body></html>"


@pytest.fixture
def conn(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sqlite3.Connection]:
    for name in ("strategy.json", "newsletters.json", "sources.json"):
        (isolated / "config").mkdir(exist_ok=True)
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    monkeypatch.setenv("SCRAPER_PROVIDER", "mock")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        if request.url.host == "link.marketingaiinstitute.com":
            return httpx.Response(302, headers={"location": "https://golem.de/voice-clones"})
        return httpx.Response(200, html=PAGE)

    monkeypatch.setattr(fetch, "TRANSPORT", httpx.MockTransport(handler))
    connection = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield connection
    connection.close()


def _content_list(folder: Path) -> Path:
    data = {"date": "2026-10-13", "ideas": [
        {"number": 1, "title": "AI voice clones target German Mittelstand finance teams",
         "summary": "Deepfake calls ask for urgent transfers.", "sources": [
             {"title": "Voice clone fraud", "source": "Marketing AI Institute",
              "url": "https://link.marketingaiinstitute.com/c/123", "date": "2026-10-12",
              "excerpt": "Fraudsters clone a manager's voice."}]},
        {"number": 2, "title": "Ten Instagram caption templates",
         "summary": "Templates for captions.", "sources": [
             {"title": "Captions", "source": "Unknown Weekly", "url": None,
              "date": "2026-10-12", "excerpt": "Caption ideas."}]},
    ]}
    path = folder / "research" / "newsletters" / "2026-10-13_content-list.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_german_sources_confirmed_where_the_feed_works() -> None:
    sources = load_sources(REPO / "config" / "sources.json")
    german = {s.name: s for s in sources if s.language == "de"}
    assert set(german) >= {"tagesschau.de", "heise online", "netzpolitik.org", "golem.de", "t3n",
                           "BSI (press)", "Destatis (press)", "BfDI"}
    assert [name for name, s in german.items() if not s.runs] == ["BfDI"]  # HTTP 404 on check
    assert all(s.note for s in german.values())
    assert all(s.runs for s in sources if s.language == "en")


def test_newsletter_run_makes_ideas_with_sources(conn: sqlite3.Connection,
                                                 isolated: Path) -> None:
    _content_list(isolated)
    result = CliRunner().invoke(app, ["research", "run", "--newsletters"])
    assert result.exit_code == 0, result.output
    assert ("Research run: collected 2, new ideas 2, duplicates 0, off_strategy 1, flagged "
            "claims 0, failed fetches 0; unknown senders (reported, kept): Unknown Weekly."
            ) in result.stdout
    (first, first_details), (second, second_details) = list_ideas(conn)
    [source] = item_sources(conn, first.id)
    assert source.original_url == "https://golem.de/voice-clones"
    assert source.purpose and "AI in marketing" in source.purpose
    assert first_details.pillar in ("ai_misuse", "german_problems")
    assert second_details.flags == ("off_strategy",)
    again = CliRunner().invoke(app, ["research", "run", "--newsletters"])
    assert "new ideas 0, duplicates 2" in again.stdout


def test_source_run_uses_the_scraper(conn: sqlite3.Connection) -> None:
    result = CliRunner().invoke(app, ["research", "run", "--sources", "--limit", "5"])
    assert result.exit_code == 0, result.output
    assert "new ideas" in result.stdout and len(list_ideas(conn)) >= 1
    item, _ = list_ideas(conn)[0]
    assert get_details(conn, item.id).pillar or "off_strategy" in get_details(conn, item.id).flags
