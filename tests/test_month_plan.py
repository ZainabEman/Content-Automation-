"""PRD v5 R7 / §7.7, §7.9: the monthly planner over simulated months (offline, nothing called)."""

import json
import shutil
from collections import Counter
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.content.deliverables import load_deliverables
from content_automation.content.directions import load_directions
from content_automation.content.month_plan import (
    Topic,
    day_quotas,
    month_total,
    plan_month,
    scale_mix,
    schedule,
    summary_lines,
    three_in_a_row,
)
from content_automation.content.plan import month_days
from content_automation.core.config import Settings
from content_automation.references.services import load_services
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve
from content_automation.registry.ideas import create_idea

REPO = Path(__file__).resolve().parents[1]
TOPICS = ["So erkennen Sie Deepfake-Anrufe im Unternehmen",
          "KI-Chatbots beantworten Patientenfragen nach Praxisschluss",
          "BSI-Bericht: KI-gestützter Phishing-Betrug nimmt zu",
          "5 Fehler bei der Einführung von KI-Agenten",
          "Datenschutz bei KI-Tools im Mittelstand"]


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(IMAGE_PROVIDER="mock",
                         DELIVERABLES_FILE=str(REPO / "config" / "deliverables.json"))


def _plan(settings: Settings, label: str, topics: list[str] | None = None) -> list:  # type: ignore[type-arg]
    return plan_month(settings, load_deliverables(settings.deliverables_file), load_directions(),
                      label, month_days(label), [Topic(t, f"topic:{t}") for t in topics or []],
                      load_services(REPO / "config" / "services.json"))


def test_counts_mix_and_quotas() -> None:
    config = load_deliverables(REPO / "config" / "deliverables.json").monthly_plan
    assert config is not None
    assert month_total(config, 30) == 60 and month_total(config, 31) == 60
    assert month_total(config, 28) == 56 and month_total(config, 10) == 30
    assert scale_mix(config.mix, 60) == config.mix
    assert sum(scale_mix(config.mix, 56).values()) == 56
    assert sum(day_quotas(60, 31, 2)) == 60 and max(day_quotas(60, 31, 2)) == 2


@pytest.mark.parametrize("label", ["2026-11", "2026-12", "2027-02"])
def test_a_simulated_month(settings: Settings, label: str) -> None:
    assets = _plan(settings, label, TOPICS)
    days = len(month_days(label))
    assert 30 <= len(assets) <= 60  # §7.9; a carousel is one asset
    counts = Counter(asset.deliverable for asset in assets)
    assert set(counts) == {"linkedin_post", "facebook_post", "instagram_carousel", "facebook_ad"}
    per_day = Counter(asset.day for asset in assets)
    assert max(per_day.values()) <= 2 and len(per_day) == days
    for day_assets in _by_day(assets).values():
        assert len({a.deliverable for a in day_assets}) == len(day_assets)  # never twice a day
    streak = _longest_daily_streak(assets)
    assert streak <= 2  # formats spread: no category on 3 days in a row
    assert three_in_a_row(assets) == []  # §7.7 / R5.3
    roman = [a for a in assets if a.requires_roman]
    assert roman and all(a.variant.split("-")[1].startswith("R") for a in roman)
    assert all(a.deliverable != "instagram_carousel" for a in roman)
    carousels = [a for a in assets if a.deliverable == "instagram_carousel"]
    assert all(5 <= a.pictures <= 6 and a.category == "instagram_carousel" for a in carousels)


def test_metadata_topics_services_and_cost(settings: Settings) -> None:
    assets = _plan(settings, "2026-11", TOPICS)
    for asset in assets:
        meta = asset.metadata
        assert {"caption", "hashtags", "headline", "hook", "cta", "altText"} <= set(meta)
        assert meta["language"] == "de"
        if asset.deliverable == "facebook_ad":
            assert set(meta["adFields"]) == {"primaryText", "headline", "description",
                                             "ctaButton"}
        if asset.platform == "linkedin":
            assert "3-5 hashtags" in meta["hashtags"]  # 2026-10-22: 3-5, 3 by default
        if asset.requires_roman:
            assert "KI-generiertes Bild" in meta["aiDisclosure"]
    with_topic = [a for a in assets if a.topic]
    assert len(with_topic) == len(TOPICS) and all(a.service for a in with_topic)
    chatbot = next(a for a in with_topic if "Chatbots" in str(a.topic))
    assert chatbot.deliverable == "facebook_ad" and str(chatbot.service).startswith("AI chatbots")
    how_to = next(a for a in with_topic if str(a.topic).startswith("5 Fehler"))
    assert how_to.deliverable == "instagram_carousel"
    lines = summary_lines("2026-11", assets, 30)
    assert any("Dry run of the planned volume" in line and "$" in line for line in lines)
    assert any("no platform has three near-identical images" in line for line in lines)


def test_schedule_never_runs_a_category_every_day() -> None:
    days = schedule({"a": 16, "b": 16, "c": 16, "d": 12}, [2] * 30)
    for first, second, third in zip(days, days[1:], days[2:], strict=False):
        assert not set(first) & set(second) & set(third)


def test_cli_plan_and_apply(settings: Settings, isolated: Path) -> None:
    (isolated / "config").mkdir(exist_ok=True)
    for name in ("registry.json", "calendar.json", "strategy.json", "content.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    idea = create_idea(conn, "KI-Chatbots beantworten Patientenfragen nach Praxisschluss")
    approve(conn, idea.id, gate="idea")
    conn.close()
    result = CliRunner().invoke(app, ["plan", "month", "2026-11", "--topic", TOPICS[0]])
    assert result.exit_code == 0, result.output
    assert "Month plan 2026-11: 60 graphics" in result.output
    data = json.loads((isolated / "calendar" / "2026-11-month-plan.json").read_text("utf-8"))
    assert len(data["assets"]) == 60 and not list((isolated / "calendar").glob("*-W*.csv"))
    applied = CliRunner().invoke(app, ["plan", "month", "2026-11", "--apply"])
    assert applied.exit_code == 0, applied.output
    assert "Applied: 1 row(s)" in applied.output and "Not applied (59" in applied.output
    weeks = list((isolated / "calendar").glob("2026-W*.csv"))
    assert len(weeks) == 1 and "Approved" in weeks[0].read_text(encoding="utf-8")


def _by_day(assets: list) -> dict[str, list]:  # type: ignore[type-arg]
    found: dict[str, list] = {}  # type: ignore[type-arg]
    for asset in assets:
        found.setdefault(asset.day, []).append(asset)
    return found


def _longest_daily_streak(assets: list) -> int:  # type: ignore[type-arg]
    by_day = _by_day(assets)
    longest = 0
    for name in {a.deliverable for a in assets}:
        run = 0
        for day in sorted(by_day):
            run = run + 1 if any(a.deliverable == name for a in by_day[day]) else 0
            longest = max(longest, run)
    return longest


def test_month_days_cover_the_month() -> None:
    assert month_days("2027-02")[0] == date(2027, 2, 1) and len(month_days("2027-02")) == 28
