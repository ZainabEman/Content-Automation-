"""PRD v5 R9 / §7.11-7.12: the YouTube planning workflow on local fixtures (no internet)."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import httpx
import pytest

from content_automation.youtube import sources
from content_automation.youtube.research import parse, structure_problems, template
from content_automation.youtube.scripts import (
    ENGLISH_PLACEHOLDER,
    bilingual_problems,
    bilingual_text,
    paragraphs,
    read_bilingual,
    similarity_flags,
    teleprompter_problems,
)
from content_automation.youtube.sources import check_sources, fact_found, fetch_page
from content_automation.youtube.topic import slug

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests" / "fixtures" / "youtube"
SCRIPT = REPO / "scripts" / "youtube_mock_package.py"


def _mock() -> ModuleType:
    spec = importlib.util.spec_from_file_location("youtube_mock_package", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sources, "TRANSPORT", _mock().transport())


def _research(**changes: str) -> str:
    text = (FIXTURES / "research.txt").read_text(encoding="utf-8").replace("{BG_ID}", "BG-1")
    for old, new in changes.items():
        text = text.replace(old, new)
    return text


def test_research_template_and_structure() -> None:
    blank = parse(template("Thema", "BG-1", "2026-11", "thema"))
    problems = structure_problems(blank)
    assert any("placeholder" in p for p in problems) and len(blank.sections) >= 13
    filled = parse(_research())
    assert structure_problems(filled) == []
    assert set(filled.sources) == {"S1", "S2"} and filled.sources["S2"].publisher
    assert len(filled.quotes) == 1 and filled.verified[0][1] == ["S1"]
    unsourced = parse(_research(**{"48.000 Euro freigeben [S1]": "48.000 Euro freigeben"}))
    assert any("names no source" in p for p in structure_problems(unsourced))


def test_source_check_passes_on_the_fixtures(served: None) -> None:
    report = check_sources(parse(_research()))
    assert report.passed, report.failures
    text = "\n".join(report.lines)
    assert "S1 OK 200" in text and "date: 2026-10-02" in text
    assert "title: Rückruf-Regel schützt Buchhaltungen" in text  # og:title wins
    assert "needs human check" in text and "verified" not in text.lower().replace(
        "verified facts", "")


def test_source_check_catches_a_dead_url_and_a_misquote(served: None) -> None:
    """§7.12."""
    broken = parse(_research(**{"https://example.org/artikel-2": "https://example.org/weg",
                                "klang genau wie": "klang fast wie"}))
    report = check_sources(broken)
    failures = " | ".join(report.failures)
    assert not report.passed
    assert "S2: the URL does not open (HTTP 404)" in failures
    assert "quotation not in its source page" in failures
    assert "fact its source does not mention" in failures  # S2 is dead, so its fact fails


def test_fact_found_needs_numbers_and_key_words() -> None:
    page = "Die Buchhaltung sollte eine Überweisung über 48.000 Euro freigeben."
    assert fact_found("Die Buchhaltung sollte 48.000 Euro freigeben", page)
    assert not fact_found("Die Buchhaltung sollte 58.000 Euro freigeben", page)
    assert not fact_found("Ein Konzern verlor Millionen durch Stimmenklone", page)


def test_fetch_failure_never_raises() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    sources.TRANSPORT = httpx.MockTransport(broken)
    try:
        page = fetch_page("https://example.org/x")
    finally:
        sources.TRANSPORT = None
    assert not page.ok and "ConnectError" in page.error


def test_teleprompter_rules() -> None:
    good = (FIXTURES / "teleprompter_B.txt").read_text(encoding="utf-8")
    errors, warnings = teleprompter_problems(good, "B")
    assert errors == [] and any("target is 1300-1600" in w for w in warnings)
    bad = ("HOOK:\n\nWarum das wichtig ist [S1], siehe https://example.org.\n\n"
           "Ich habe erlebt, wie so ein Anruf kam. Read more about the risk now.")
    errors, _ = teleprompter_problems(bad, "A")
    joined = " | ".join(errors)
    for expected in ("heading or label", "citation, URL", "never imply Roman",
                     "English left in German text"):
        assert expected in joined
    no_frame = (FIXTURES / "teleprompter_A.txt").read_text(encoding="utf-8")
    assert any("illustrative" in e for e in teleprompter_problems(no_frame, "C")[0])


def test_bilingual_is_made_from_the_teleprompter() -> None:
    german = (FIXTURES / "teleprompter_A.txt").read_text(encoding="utf-8")
    made = bilingual_text(german)
    pairs = read_bilingual(made)
    assert [g for g, _ in pairs] == paragraphs(german)
    assert all(e == ENGLISH_PLACEHOLDER for _, e in pairs)
    assert any("English translation is missing" in p for p in bilingual_problems(german, made))
    english = json.loads((FIXTURES / "english.json").read_text(encoding="utf-8"))["A"]
    filled = made
    for line in english:
        filled = filled.replace(ENGLISH_PLACEHOLDER, line, 1)
    assert bilingual_problems(german, filled) == []
    edited = filled.replace("ganz normaler Dienstagvormittag", "normaler Vormittag")
    assert any("German differs" in p for p in bilingual_problems(german, edited))
    again = bilingual_text(german, filled)  # regenerated: English kept for unchanged German
    assert bilingual_problems(german, again) == []


def test_similarity_flags_near_copies() -> None:
    a = (FIXTURES / "teleprompter_A.txt").read_text(encoding="utf-8")
    b = (FIXTURES / "teleprompter_B.txt").read_text(encoding="utf-8")
    assert similarity_flags({"A": a, "B": b}) == []
    copy = a.replace("Dienstagvormittag", "Mittwochvormittag")
    assert any("too similar" in flag for flag in similarity_flags({"A": a, "C": copy}))


def test_slug_is_file_safe() -> None:
    assert slug("Deepfake-Anrufe im Namen der Geschäftsführung") == (
        "deepfake-anrufe-im-namen-der-geschaeftsfuehrung")
    from content_automation.core.output_tree import safe_title

    assert safe_title('KI: "Fehler" / Risiken?') == "KI Fehler Risiken"  # Windows and Drive
    assert safe_title("CON") == "Thema CON"


def test_one_topic_end_to_end(tmp_path: Path) -> None:
    """§7.11 / PRD v6 §5 check 7: exactly the R7 tree, one storyboard per style; a second run
    makes no duplicate folder and overwrites nothing (a changed file becomes _v2)."""
    result = _mock().run(copy_to=tmp_path)
    steps = result["steps"]
    assert steps["blocked"] == 2 and result["failedCheck"]["code"] == 1  # the gate
    assert all(steps[name] == 0 for name in ("plan", "approve", "template", "check-sources",
                                             "scripts", "bilingual", "check", "select"))
    folder = tmp_path / result["folderName"]
    assert result["folderName"] == "Deepfake-Anrufe im Namen der Geschäftsführung"  # readable
    assert result["meta"]["bgId"] == result["bgId"]  # the BG ID is in the metadata
    styles = ("Style A", "Style B", "Style C")
    expected = {"research.txt"} | {f"{name}/{file}" for name in styles for file in (
        "script_de_teleprompter.txt", "script_de_en_bilingual.txt", "storyboard.txt")}
    assert set(result["files"]) == expected  # exactly the R7 tree, nothing else
    for name in styles[1:]:  # Style A's teleprompter is changed by the re-run below
        teleprompter = (folder / name / "script_de_teleprompter.txt").read_text(encoding="utf-8")
        assert teleprompter_problems(teleprompter, name[-1])[0] == []  # no English, no citation
        bilingual = (folder / name / "script_de_en_bilingual.txt").read_text(encoding="utf-8")
        assert bilingual_problems(teleprompter, bilingual) == []  # identical German
    research = (folder / "research.txt").read_text(encoding="utf-8")
    assert "Result: PASSED" in research
    boards = {name: (folder / name / "storyboard.txt").read_text(encoding="utf-8")
              for name in styles}
    assert len(set(boards.values())) == 3  # one per style, never shared
    board = boards["Style B"]
    assert board.count("## Scene ") >= 3 and "PENDING" in board
    for field in ("German (spoken by Roman)", "English (translation)", "Visual direction",
                  "On-screen text (German, exact)", "On-screen text (English explanation)",
                  "Sources for factual visuals", "Transitions, pacing"):
        assert field in board
    package = result["meta"]
    assert package["selectedStyle"] == "B" and package["sourceCheck"]["status"] == "passed"
    assert steps["upload"] == 0  # mock Drive mirrors YouTube Long-Form/<Topic Name>/ (R8)
    base = f"YouTube Long-Form/{folder.name}/"
    assert {base + path for path in expected} <= set(result["driveFiles"])
    rerun = result["rerun"]
    assert rerun["codes"] == [0, 0, 0] and rerun["unchanged"]
    assert rerun["topicFolders"] == [folder.name]  # no duplicate folder
    code, out = rerun["changedBilingual"]
    assert code == 0 and "new version" in out
    assert "script_de_en_bilingual_v2.txt" in rerun["versions"]  # the earlier one is kept
    tracker = result["tracker"]
    header = tracker.splitlines()[0]
    for column in ("Category", "Language", "Selected Script Style"):
        assert column in header
    assert result["bgId"] in tracker and "YouTube" in tracker and "teleprompter" in tracker


def test_plan_makes_at_most_8_proposed_topics_with_bg_ids() -> None:
    from typer.testing import CliRunner

    from content_automation.cli import app

    mock = _mock()
    with mock.sandbox():
        runner = CliRunner()
        topics = [arg for n in range(10) for arg in ("--topic", f"Thema {n} aus echter Recherche")]
        out = runner.invoke(app, ["youtube", "plan", "2026-11", *topics]).output
        ids = [line.split()[0] for line in out.splitlines() if line.startswith("BG-")]
        assert len(ids) == 8 and "2 topic(s) not added" in out
        blocked = runner.invoke(app, ["youtube", "research", ids[0]])
        assert blocked.exit_code == 2 and "approve the topic first" in blocked.output
        assert runner.invoke(app, ["item", "reject", ids[1], "zu", "allgemein"]
                             ).exit_code == 0
        status = runner.invoke(app, ["youtube", "status", "--month", "2026-11"]).output
        assert status.count("BG-") == 8 and "rejected" in status
        again = runner.invoke(app, ["youtube", "plan", "2026-11", "--topic", "Noch eins"]).output
        assert "8 topic(s) already planned" in again and "1 topic(s) not added" in again


def test_fact_ids_trace_from_script_to_source(served: None) -> None:
    """Phase 2 P2-R2: the source check reports each fact ID; script sentences map to them."""
    from content_automation.youtube.scripts import trace

    research = parse(_research())
    assert set(research.fact_ids) == {"F1", "F2"} and research.outline.thesis
    report = "\n".join(check_sources(research).lines)
    assert "- F1 (S1 Beispiel-Nachrichten (MOCK), 2026-10-02): needs human check" in report
    rows = trace("Die Buchhaltung sollte 48.000 Euro überweisen. Laut Polizei waren es zwölf "
                 "Firmen.\n\nDas war ein ganz normaler Tag.", research)
    assert [(number, ids) for number, _, ids in rows] == [(1, ["F1"]), (1, [])]
    unnumbered = parse(_research(**{"- [F2] Eine feste": "- Eine feste"}))
    assert any("has no fact ID" in p for p in structure_problems(unnumbered))


def test_bilingual_blocks_are_counted() -> None:
    """P2-R6: one English block per German block; a summarised English block is warned."""
    from content_automation.youtube.scripts import bilingual_warnings

    german = "Erster Satz hier. Zweiter Satz hier. Dritter Satz hier.\n\nNoch ein Absatz hier."
    pairs = [("Erster Satz hier. Zweiter Satz hier. Dritter Satz hier.",
              "First sentence here. Second sentence here."),
             ("Noch ein Absatz hier.", "One more paragraph here.\n\nAn extra block.")]
    text = "".join(f"German:\n{de}\n\nEnglish:\n{en}\n\n" for de, en in pairs)
    assert any("2 German block(s), 3 English block(s)" in p
               for p in bilingual_problems(german, text))
    assert any("2 English sentence(s) for 3 German" in w
               for w in bilingual_warnings(german, text))


def test_style_difference_flags_opening_order_and_sentences() -> None:
    """P2-R4: the same opening type, the same order of points, near-identical sentences."""
    research = parse(_research(**{"opening: incident | order: 1, 2, 3":
                                  "opening: question | order: 3, 1, 2"}))
    body = ("Die Buchhaltung sollte nach einem Anruf eine Überweisung über 48.000 Euro freigeben. "
            "Eine feste Rückruf-Regel über eine bekannte Nummer verhinderte am Ende die Zahlung.")
    texts = {"A": f"Würden Sie zahlen, wenn Ihr Chef anruft? {body}",
             "B": f"Würden Sie sofort überweisen? {body}",
             "C": f"Stellen Sie sich vor, das Telefon klingelt. {body}"}
    flags = " | ".join(similarity_flags(texts, research))
    assert "styles A and B: the same opening type (question)" in flags
    assert "styles A and B: the same order of the outline points (3, 1, 2)" in flags
    assert "near-identical sentences" in flags
    assert "styles A and C: the same opening type" not in flags
