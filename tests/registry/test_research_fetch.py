"""Phase 5 Step 2: `ca research fetch` follows links to the original article (mock HTTP)."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.registry import db_path, open_registry
from content_automation.registry.ideas import create_idea
from content_automation.registry.sources import item_sources
from content_automation.research import fetch
from content_automation.research.fetch import unwrap

HEAD = "<html><head><title>Deepfake calls hit German SMEs</title></head><body><article>"
ARTICLE = HEAD + "".join(
    f"<p>Paragraph {n}: criminals clone the voice of a managing director and call the "
    "accounts team, asking for an urgent transfer before the end of the day.</p>"
    for n in range(8)) + "</article></body></html>"


@pytest.fixture
def conn(isolated: Path) -> Iterator[sqlite3.Connection]:
    connection = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield connection
    connection.close()


def _transport(robots: str, calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=robots)
        if request.url.host == "click.news.example":
            return httpx.Response(302, headers={"location": "https://heise.de/news/deepfakes"})
        return httpx.Response(200, html=ARTICLE)
    return httpx.MockTransport(handler)


def test_fetch_follows_the_link_and_stores_the_source(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(fetch, "TRANSPORT", _transport("User-agent: *\nAllow: /", calls))
    idea = create_idea(conn, "Deepfake calls")
    url = "https://click.news.example/c/abc?utm_source=newsletter"
    result = CliRunner().invoke(app, ["research", "fetch", url, "--idea", idea.id,
                                      "--type", "newsletter"])
    assert result.exit_code == 0, result.output
    assert "SRC-0001" in result.stdout and "<- https://heise.de/news/deepfakes" in result.stdout
    [source] = item_sources(conn, idea.id)
    assert source.type == "newsletter" and source.original_url == "https://heise.de/news/deepfakes"
    assert source.text_path is not None
    assert "voice of a managing director" in Path(source.text_path).read_text(encoding="utf-8")
    before = len(calls)
    again = CliRunner().invoke(app, ["research", "fetch", url])
    assert "already a source" in again.stdout and len(calls) == before


def test_robots_txt_is_respected(conn: sqlite3.Connection,
                                 monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fetch, "TRANSPORT", _transport("User-agent: *\nDisallow: /", []))
    result = CliRunner().invoke(app, ["research", "fetch", "https://heise.de/news/x"])
    assert result.exit_code == 1 and "robots.txt disallows" in result.stdout
    assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0


def test_unwrap_tracking_links() -> None:
    wrapped = "https://t.example/r?url=https%3A%2F%2Fgolem.de%2Fa%3Futm_medium%3Demail"
    assert unwrap(wrapped) == "https://golem.de/a"
