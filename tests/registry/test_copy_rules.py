"""Live fix: the branded card copy rules (social_graphic) and the brief fields they fill."""

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
CARD = {"tag": "AI RISK · HR", "headline": "Your hiring AI can be *wrong*",
        "subtitle": "KI im Recruiting braucht menschliche Kontrolle",
        "bullets": "Review every AI shortlist\nAsk why candidates were rejected\n"
                   "Keep the final decision human",
        "icons": "checklist\nsearch\nuser-check", "cta_en": "Follow for weekly AI checks",
        "cta_de": "Jetzt folgen"}


@pytest.fixture
def conn(isolated: Path) -> Iterator[sqlite3.Connection]:
    (isolated / "config").mkdir()
    for name in ("formulas.json", "content.json", "strategy.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    # the live-fix card mixes English and German: only for a platform set to en since v5
    content = isolated / "config" / "content.json"
    data = json.loads(content.read_text(encoding="utf-8"))
    content.write_text(json.dumps({**data, "platforms": {"linkedin": "en"}}), encoding="utf-8")
    connection = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield connection
    connection.close()


def _script(post: str, texts: dict[str, str]) -> Script:
    return Script(item=post, version=1, formula="social_graphic", language="en",
                  sections=[ScriptSection(key=k, text=v) for k, v in texts.items()])


def test_card_rules_and_brief_fields(conn: sqlite3.Connection, isolated: Path) -> None:
    package = isolated / "pkg"
    package.mkdir()
    (package / "brief.json").write_text(json.dumps({"post": {"headline": "old"}}),
                                        encoding="utf-8")
    post = create_item(conn, kind="post", title="KI", topic="t", platforms=["linkedin"],
                       deliverable="linkedin_post", package_path=package.as_posix())
    template = build_template(conn, load_settings(env_file=None), post.id)
    problems = check_script(conn, template, _script(post.id, CARD)).problems
    keys = ("tag", "headline", "subtitle", "bullets", "icons", "cta_en", "cta_de")
    assert not [p for p in problems if p.startswith(keys)], problems
    bad = _script(post.id, {
        "tag": "AI risk", "headline": "Hiring AI is wrong",
        "bullets": "The CRM pipeline\n\"Ask\" everyone\nKeep it human every single time now",
        "icons": "checklist\nrobot\nsearch"})
    problems = check_script(conn, template, bad).problems
    assert "tag: write it in capitals" in problems
    assert "headline: mark exactly 1 highlight word like *word* (found 0)" in problems
    assert "bullets: jargon (CRM, pipeline): say it in plain words" in problems
    assert 'bullets line 1: start with a verb ("The" is not one)' in problems
    assert "bullets: no quotes" in problems and "bullets line 3: 7 words (at most 6)" in problems
    assert any(p.startswith("icons: robot not allowed") for p in problems)
    applied, _ = apply_copy(post, _script(post.id, CARD))
    slot = json.loads((package / "brief.json").read_text(encoding="utf-8"))["post"]
    assert "post.card" in applied and slot["headline"] == "Your hiring AI can be wrong"
    assert slot["highlight"] == ["wrong"] and slot["points"][0] == "Review every AI shortlist"
    assert slot["card"] == {"tag": "AI RISK · HR", "subtitle": CARD["subtitle"],
                            "icons": ["checklist", "search", "user-check"],
                            "ctaEn": "Follow for weekly AI checks", "ctaDe": "Jetzt folgen"}


def test_icon_lists_match() -> None:
    formulas = json.loads((REPO / "config" / "formulas.json").read_text(encoding="utf-8"))
    icons = next(s for s in formulas["formulas"]["social_graphic"]["sections"]
                 if s["key"] == "icons")["lineChoices"]
    system = json.loads((REPO / "config" / "design_system.json").read_text(encoding="utf-8"))
    codepoints = json.loads((REPO / "assets" / "icons" / "tabler-codepoints.json").read_text(
        encoding="utf-8"))
    assert icons == system["personTemplates"]["icons"]["allowed"] and set(icons) <= set(codepoints)
