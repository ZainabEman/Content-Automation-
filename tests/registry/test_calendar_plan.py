"""Phase 5 Step 5: calendar v2 — plan from approved ideas, inherited approval, shorts, month."""

import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from content_automation.cli import app
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve
from content_automation.registry.decisions import list_decisions
from content_automation.registry.ideas import create_idea, update_details
from content_automation.registry.items import children, get_item, list_items, set_planned_date
from content_automation.registry.strategy import load_strategy

REPO = Path(__file__).resolve().parents[2]
WEEK = "2026-W45"  # Mon 2026-11-02 .. Sun 2026-11-08


@pytest.fixture
def env(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DELIVERABLES_FILE", str(REPO / "config" / "deliverables.json"))
    (isolated / "config").mkdir()
    # A fixed cadence (the v5 plan slots with YouTube and shorts), so these tests do not follow
    # the user's editable config/calendar.json.
    shutil.copy(REPO / "tests" / "fixtures" / "calendar_plan_fixture.json",
                isolated / "config" / "calendar.json")
    shutil.copy(REPO / "config" / "strategy.json", isolated / "config" / "strategy.json")
    return isolated


def _open() -> sqlite3.Connection:
    return open_registry(db_path(Path("state")), Path("config/registry.json"))


def _seed(count: int) -> list[str]:
    """`count` approved ideas, spread over the pillars by their target share."""
    pillars = load_strategy(Path("config/strategy.json")).pillars
    spread = [p.key for p in pillars for _ in range(round(p.target_share * 20))]
    conn = _open()
    try:
        ids = []
        for n in range(count):
            idea = create_idea(conn, f"Idea number {n} about {spread[n % len(spread)]}")
            update_details(conn, idea.id, pillar=spread[n % len(spread)], score=90 - n)
            approve(conn, idea.id, gate="idea")
            ids.append(idea.id)
        return ids
    finally:
        conn.close()


def ca(*args: str) -> Result:
    return CliRunner().invoke(app, list(args))


def test_month_plan_meets_targets_with_pillar_balance(env: Path) -> None:
    _seed(50)
    result = ca("calendar", "plan", "--month", "2026-11")
    assert result.exit_code == 0, result.output
    assert "Targets met." in result.output and "within ±15%" in result.output
    assert "No approved idea left" not in result.output
    assert {path.name for path in Path("calendar").glob("*.csv")} >= {
        "2026-W45.csv", "2026-W48.csv"}
    conn = _open()
    try:
        videos = [item for item in list_items(conn) if item.deliverable == "youtube_longform"]
        assert len(videos) >= 8
        video = videos[0]
        shorts = children(conn, video.id)
        assert sorted(s.deliverable or "" for s in shorts) == ["tiktok_short", "youtube_short"]
        assert video.planned_date and all(
            s.planned_date and (s.planned_date - video.planned_date).days == 2 for s in shorts)
        idea = get_item(conn, video.parent_id or "")
        assert idea.kind == "idea" and video.idea_status == "approved"
        (decision,) = list_decisions(conn, video.id)
        assert decision.actor == "system" and idea.id in (decision.text or "")
    finally:
        conn.close()
    shown = ca("calendar", "show", "--month", "2026-11")
    assert shown.exit_code == 0 and "2026-W45#1" in shown.output


def test_short_is_blocked_until_its_parent_is_planned_before_it(env: Path) -> None:
    _seed(12)
    assert ca("calendar", "plan", "--week", WEEK).exit_code == 0
    assert ca("calendar", "check", "--week", WEEK).exit_code == 0
    conn = _open()
    try:
        video = next(i for i in list_items(conn) if i.deliverable == "youtube_longform")
        set_planned_date(conn, video.id, date(2026, 11, 8))
    finally:
        conn.close()
    shown = ca("calendar", "show", "--week", WEEK)
    assert f"blocked: waiting for {video.id}" in shown.output


def test_generate_skips_plan_only_rows(env: Path) -> None:
    path = Path("config/calendar.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["plan"]["slots"] = [{"weekday": "tue", "types": ["youtube_longform"]}]
    data["plan"]["targets"] = {}
    path.write_text(json.dumps(data), encoding="utf-8")
    _seed(1)
    assert ca("calendar", "plan", "--week", WEEK).exit_code == 0
    result = ca("calendar", "generate", "--week", WEEK)
    assert result.exit_code == 0, result.output
    assert result.output.count("not producible until Phase 8/9") == 3  # video + 2 shorts
    assert "package started" not in result.output


def test_plan_uses_only_approved_ideas(env: Path) -> None:
    conn = _open()
    try:
        create_idea(conn, "A proposed idea that waits")
    finally:
        conn.close()
    result = ca("calendar", "plan", "--week", WEEK)
    assert result.exit_code == 0, result.output
    assert "0 new row(s)" in result.output and "No approved idea left" in result.output
