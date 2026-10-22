"""PRD v6 R2/R6 (T3): the topic pool, no forced service link, and rejected, deleted and already
generated topics that never come back (offline; every CLI call reopens the registry from disk)."""

import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.content.calendar import view_status
from content_automation.content.deliverables import load_deliverables
from content_automation.content.directions import load_directions
from content_automation.content.month_plan import Topic, plan_month
from content_automation.content.plan import month_days
from content_automation.content.relevance import INSIGHT_ONLY, unverified_claims
from content_automation.content.topic_pool import (
    CONFIG_FILE,
    SEED_FILE,
    Known,
    PoolTopic,
    TopicMemory,
    add_topics,
    load_pool,
    spread,
    theme_of,
)
from content_automation.core.config import Settings
from content_automation.references.services import load_services
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve
from content_automation.registry.ideas import create_idea, list_ideas

REPO = Path(__file__).resolve().parents[1]
SERVICES = load_services(REPO / "config" / "services.json")
GENERATED = "KI-Fehler in der Pflege: Wenn der Chatbot Angehörige falsch berät"


def test_the_pool_has_the_society_themes_and_the_mix() -> None:
    pool = load_pool()
    assert len(pool.themes) == 12 and pool.source_mix == {
        "society": 0.5, "services": 0.3, "newsletters": 0.2}
    assert theme_of("Deepfake-Anruf: die Stimme des Chefs war gefälscht") == "deepfakes"
    assert theme_of("Neue Betrugsmasche mit KI-Stimmen") == "ai_scams"


def test_the_live_pool_is_a_git_ignored_copy_of_the_tracked_seed(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "config").mkdir()
    shutil.copy(REPO / SEED_FILE, tmp_path / SEED_FILE)
    seed = (tmp_path / SEED_FILE).read_text(encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    load_pool.cache_clear()
    try:
        before = len(load_pool().topics)
        assert (tmp_path / CONFIG_FILE).read_text(encoding="utf-8") == seed  # copied on first use
        size = add_topics([PoolTopic("Ein neues Thema zur KI im Handwerk", "society", "Nutzen")])
        assert size == before + 1 and len(load_pool().topics) == before + 1
        assert (tmp_path / SEED_FILE).read_text(encoding="utf-8") == seed  # the seed is kept
        add_topics([PoolTopic("Noch ein Thema zur KI im Büro", "society", "Nutzen")])
        assert len(load_pool().topics) == before + 2  # an existing live pool is never re-seeded
    finally:
        load_pool.cache_clear()


@pytest.fixture
def settings(make_settings: Callable[..., Settings]) -> Settings:
    return make_settings(IMAGE_PROVIDER="mock",
                         DELIVERABLES_FILE=str(REPO / "config" / "deliverables.json"))


def test_a_plan_without_a_service_link_is_valid(settings: Settings) -> None:
    """§5 check 5: a topic with no service is planned (insight-only); a claim about an
    unverified service still fails."""
    topic = "Deepfake-Videos: Wenn der Bürgermeister nie gesprochen hat"
    label = "2026-11"
    assets = plan_month(settings, load_deliverables(settings.deliverables_file),
                        load_directions(), label, month_days(label),
                        [Topic(topic, f"topic:{topic}")], SERVICES)
    planned = next(asset for asset in assets if asset.topic == topic)
    assert planned.service is not None and planned.service.startswith(INSIGHT_ONLY)
    assert planned.theme == "deepfakes"
    informative = [("copy.headline", "Deepfakes erkennen: drei Warnzeichen am Telefon")]
    assert unverified_claims(informative, SERVICES) == []
    claim = [("copy.sub", "Wir übernehmen Ihre SEO und Ihr Webdesign.")]
    assert unverified_claims(claim, SERVICES)


def test_themes_are_spread_and_never_back_to_back(settings: Settings) -> None:
    topics = ["Deepfake-Video vom Bürgermeister", "Deepfake-Stimme am Telefon",
              "KI-Betrug per Telefon", "Deepfakes in Bewerbungsgesprächen",
              "Phishing-Betrug mit KI-Texten", "Pflege entlasten mit KI"]
    ordered = spread(topics, lambda text: text)
    themes = [theme_of(text) for text in ordered]
    assert all(first != second for first, second in zip(themes, themes[1:], strict=False)
               if first is not None)
    label = "2026-12"
    assets = plan_month(settings, load_deliverables(settings.deliverables_file),
                        load_directions(), label, month_days(label),
                        [Topic(text, f"topic:{text}") for text in topics], SERVICES)
    planned = [asset.theme for asset in assets if asset.topic]
    assert len(planned) == len(topics)
    assert all(a != b for a, b in zip(planned, planned[1:], strict=False) if a is not None)


def test_a_reworded_repeat_is_blocked_and_a_new_angle_is_not() -> None:
    """§5 check 6 (second half): near-duplicate check against everything generated."""
    memory = TopicMemory([Known(GENERATED, "generated", "package 2026-10-20_ki-fehler")])
    assert memory.check(GENERATED.upper() + "!") is not None  # normalised text
    assert memory.check("Wenn der Chatbot Angehörige falsch berät: KI-Fehler in der Pflege")
    assert memory.check("KI-Fehler bei Bewerbungen im Mittelstand") is None  # same theme
    assert memory.check("Deepfake-Anrufe bei Pflegeheimen") is None


def _registry_setup(isolated: Path) -> None:
    (isolated / "config").mkdir(exist_ok=True)
    for name in ("registry.json", "calendar.json", "strategy.json", "content.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)


def test_rejected_and_deleted_topics_never_come_back(settings: Settings,
                                                     isolated: Path) -> None:
    """§5 check 6: a rejected and a deleted topic are not suggested, planned or re-imported
    in later runs (each CLI call opens the stored registry afresh)."""
    _registry_setup(isolated)
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    rejected = create_idea(conn, "Deepfake-Anrufe: Wenn die Stimme des Chefs gefälscht ist")
    deleted = create_idea(conn, "KI-Betrug mit gefälschten Rechnungen im Handwerk")
    kept = create_idea(conn, "Pflegeheime entlasten: KI dokumentiert die Nachtschicht")
    approve(conn, deleted.id, gate="idea")
    approve(conn, kept.id, gate="idea")
    conn.close()
    runner = CliRunner()
    result = runner.invoke(app, ["item", "reject", rejected.id, "zu", "reißerisch"])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["item", "delete", deleted.id, "nicht", "unser", "Thema"])
    assert result.exit_code == 0, result.output
    assert f"{deleted.id}: deleted" in result.output
    # a newsletter or manual re-import: merged into the old idea or skipped, never a new one
    for title in (rejected.title, "Betrug mit gefälschten KI-Rechnungen im Handwerk"):
        assert runner.invoke(app, ["ideas", "add", title]).exit_code == 0
    # a new plan in a later run: neither comes back, the kept idea is planned
    result = runner.invoke(app, ["plan", "month", "2026-11", "--topic", rejected.title,
                                 "--topic", deleted.title])
    assert result.exit_code == 0, result.output
    assert result.output.count("Skipped") >= 2
    data = json.loads((isolated / "calendar" / "2026-11-month-plan.json").read_text("utf-8"))
    topics = {asset["topic"] for asset in data["assets"] if asset["topic"]}
    assert topics == {kept.title}
    conn = open_registry(db_path(Path("state")), Path("config/registry.json"))
    states = {item.title: item.idea_status for item, _ in list_ideas(conn)}
    conn.close()
    assert states[rejected.title] == "rejected" and states[deleted.title] == "deleted"
    assert not [title for title, status in states.items() if status == "proposed"]
    # the calendar shows the same status as the registry (and the tracker's Idea status)
    assert view_status("deleted", "not_started") == "Deleted"
    assert view_status("rejected", "not_started") == "Rejected"
