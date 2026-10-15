"""Live fix: social_graphic copy rules (body, 3 bullets, no jargon) and their brief fields."""

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from content_automation.content.copy_apply import apply_copy
from content_automation.content.script_check import check_script
from content_automation.content.scripts import Script, ScriptSection, build_template
from content_automation.core.config import load_settings
from content_automation.registry import db_path, open_registry
from content_automation.registry.items import create_item

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def conn(isolated: Path) -> Iterator[sqlite3.Connection]:
    (isolated / "config").mkdir()
    for name in ("formulas.json", "content.json", "strategy.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    connection = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield connection
    connection.close()


def test_body_bullets_and_jargon(conn: sqlite3.Connection, isolated: Path) -> None:
    package = isolated / "pkg"
    package.mkdir()
    (package / "brief.json").write_text(json.dumps({"post": {"headline": "old"}}),
                                        encoding="utf-8")
    post = create_item(conn, kind="post", title="KI", topic="t", platforms=["linkedin"],
                       deliverable="linkedin_post", package_path=package.as_posix())
    template = build_template(conn, load_settings(env_file=None), post.id)
    texts = {"headline": "KI beantwortet Kundenfragen sofort",
             "body": "Viele Anfragen bleiben liegen, weil niemand antwortet. Das kostet Kunden.",
             "bullets": "Häufige Fragen sammeln\nAntworten freigeben\nZuerst im Chat testen"}
    script = Script(item=post.id, version=1, formula="social_graphic", language="en",
                    sections=[ScriptSection(key=k, text=v) for k, v in texts.items()])
    problems = check_script(conn, template, script).problems
    assert not any(p.startswith(("body", "bullets", "headline")) for p in problems)
    bad = script.model_copy(update={"sections": [
        ScriptSection(key="body", text="We leverage your lifecycle context for every lead."),
        ScriptSection(key="bullets", text="One\nTwo")]})
    problems = check_script(conn, template, bad).problems
    assert "body: jargon (lifecycle context, leverage): say it in plain words" in problems
    assert "bullets: 2 lines (exactly 3)" in problems
    applied, _ = apply_copy(post, script)
    brief = json.loads((package / "brief.json").read_text(encoding="utf-8"))
    assert "post.points" in applied and brief["post"]["points"][0] == "Häufige Fragen sammeln"
    assert brief["post"]["subheadline"].startswith("Viele Anfragen")
