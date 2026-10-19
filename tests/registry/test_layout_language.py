"""Live fix: the layout language (config/content.json layoutLanguage) in templates and checks."""

import json
import shutil
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_automation.cli import app
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


def test_templates_carry_the_layout_language_and_the_check_warns(
        conn: sqlite3.Connection) -> None:
    post = create_item(conn, kind="post", title="Leads", topic="t", platforms=["linkedin"],
                       deliverable="linkedin_post")
    default = CliRunner().invoke(app, ["script", "template", post.id, "--json"])
    assert json.loads(default.output)["layoutLanguage"] is None  # v5: German, no mix
    content = Path("config/content.json")  # the old English/German mix: a platform set to en
    data = json.loads(content.read_text(encoding="utf-8"))
    content.write_text(json.dumps({**data, "platforms": {"linkedin": "en"}}), encoding="utf-8")
    shown = CliRunner().invoke(app, ["script", "template", post.id])
    assert shown.exit_code == 0, shown.output
    assert "subtitle in German; the CTA in English plus a short German CTA" in shown.output
    data = json.loads(CliRunner().invoke(app, ["script", "template", post.id, "--json"]).output)
    assert data["layoutLanguage"]["subtitle"] == "de" and data["layoutLanguage"]["rule"]

    template = build_template(conn, load_settings(env_file=None), post.id)
    english = Script(item=post.id, version=1, formula=template.formula_name, language="en",
                     sections=[ScriptSection(key="subtitle", text="Answer every lead fast"),
                               ScriptSection(key="copy", text="Hook line.\nWhy does it matter?")])
    warned = check_script(conn, template, english).warnings
    assert any(w.startswith("subtitle: reads as not German") for w in warned)
    assert any(w.startswith("copy: the caption should end with one German line") for w in warned)
    german = english.model_copy(update={"sections": [
        ScriptSection(key="subtitle", text="KI im Recruiting braucht Kontrolle"),
        ScriptSection(key="copy", text="Hook line.\nWhy does it matter?\nJetzt mehr erfahren.")]})
    warned = check_script(conn, template, german).warnings
    assert not any(w.startswith(("subtitle:", "copy: the caption")) for w in warned)
