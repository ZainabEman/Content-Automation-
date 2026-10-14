"""Confirmed 2026-10-14: English content with German touches (config/content.json)."""

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


def test_templates_carry_the_german_touch_and_the_check_warns(conn: sqlite3.Connection) -> None:
    post = create_item(conn, kind="post", title="Leads", topic="t", platforms=["linkedin"],
                       deliverable="linkedin_post")
    shown = CliRunner().invoke(app, ["script", "template", post.id])
    assert shown.exit_code == 0, shown.output
    assert "German touch: write mostly English with about 25% German touches; the headline " \
           "or the CTA in German; key terms in German; 1-2 German hashtags." in shown.output
    data = json.loads(CliRunner().invoke(app, ["script", "template", post.id, "--json"]).output)
    assert data["germanTouch"]["share"] == 0.25 and data["germanTouch"]["rule"]

    template = build_template(conn, load_settings(env_file=None), post.id)
    english = Script(item=post.id, version=1, formula=template.formula_name, language="en",
                     sections=[ScriptSection(key="copy", text="Answer every lead fast.")],
                     cta="Book a free analysis")
    warned = check_script(conn, template, english)
    assert any(w.startswith("no German element") for w in warned.warnings)
    touched = check_script(conn, template, english.model_copy(update={
        "cta": "Jetzt Termin buchen", "hashtags": ["#Mittelstand"]}))
    assert not any(w.startswith("no German element") for w in touched.warnings)
