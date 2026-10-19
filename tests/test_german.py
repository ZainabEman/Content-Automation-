"""PRD v5 R1.4-R1.6: German defaults, German-safe rendering and the free German quality pass."""

import json
from pathlib import Path

import pytest
from PIL import ImageFont

from content_automation.content.german import check_text, check_texts
from content_automation.references import load_brand
from content_automation.registry.strategy import ContentLanguage, load_content
from content_automation.workflows.design_render import _joined, design_fonts, parse

REPO = Path(__file__).resolve().parents[1]
GERMAN_GLYPHS = "ÄÖÜäöüß„“–"


def test_language_defaults_are_german() -> None:
    assert load_content(REPO / "config" / "content.json").language == "de"
    assert ContentLanguage().language == "de"
    brand = json.loads((REPO / "config" / "brand.json").read_text(encoding="utf-8"))
    assert brand["language"] == "de" and brand["carousel"]["language"] == "de"


def test_clean_german_passes() -> None:
    report = check_text("Ihr Vertrieb schläft. Unsere KI beantwortet Anfragen in Sekunden – "
                        "rund um die Uhr, per WhatsApp und E-Mail. #BrandedGenius")
    assert report.passed and not report.warnings


@pytest.mark.parametrize(("text", "message"), [
    ("Die Loesung fuer Ihr Team", '"Loesung" → "Lösung"'),
    ("Diese Massnahmen helfen", '"Massnahmen" → "Maßnahmen"'),
    ("Der Standart für KI-Projekte", '"Standart" → "Standard"'),
    ("Jetzt Termin sichern – learn more", "English left in German text"),
    ("Your team and the AI", "English left in German text"),
    ("Ein echter Gamechanger für Ihr Unternehmen", "generic AI marketing language"),
    ("In der heutigen schnelllebigen Welt zählt Tempo", "generic AI marketing language"),
])
def test_problems_are_errors(text: str, message: str) -> None:
    report = check_text(text, "post.headline")
    assert not report.passed and any(message in error for error in report.errors), report
    assert all(error.startswith("post.headline: ") for error in report.errors)


def test_warnings_do_not_block() -> None:
    report = check_texts([("a", "Weißt du, was deine Kunden wollen?"),
                          ("b", "Die Oekonomie der Daten"), ("c", "Mehr Leads with KI")])
    assert report.passed
    assert any('"du" form' in w for w in report.warnings)
    assert any("Oekonomie" in w for w in report.warnings)
    assert any('"with" looks English' in w for w in report.warnings)


def test_urls_mails_and_hashtags_are_skipped() -> None:
    assert check_text("Mehr auf https://brandedgenius.de/the-free-guide oder "
                      "info@brandedgenius.de #AIforYou").passed


def test_brand_fonts_draw_german_characters() -> None:
    brand = load_brand()
    for path in set(design_fonts(brand).values()):
        font = ImageFont.truetype(str(path), 48)
        missing = bytes(font.getmask(chr(0xE000)))  # a private-use point: the .notdef box
        for char in GERMAN_GLYPHS:
            assert bytes(font.getmask(char)) != missing, f"{path.name} lacks {char!r}"


def test_long_words_break_only_at_hyphens_or_soft_hyphens() -> None:
    words = parse("KI-gestützte Daten\u00adschutz\u00adverordnung im *Mittelstand*")
    assert [(w.text, w.glue) for w in words] == [
        ("KI-", False), ("gestützte", True), ("Daten", False), ("schutz", True),
        ("verordnung", True), ("im", False), ("Mittelstand", False)]
    assert words[2].soft and not words[4].soft
    assert _joined(words) == "KI-gestützte Datenschutzverordnung im Mittelstand"
    assert [w.text for w in parse("straße", upper=True)] == ["STRASSE"]
