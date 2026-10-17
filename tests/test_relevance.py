"""Phase D step 5: service relevance, insight-only posts and unverified-service claims."""

from pathlib import Path

from content_automation.content.calendar import service_lines
from content_automation.content.relevance import (
    INSIGHT_ONLY,
    cta_problems,
    service_fit,
    unverified_claims,
)
from content_automation.references.services import load_services


def test_topics_map_to_verified_services_or_insight_only() -> None:
    catalog = load_services()
    fit = service_fit(["Why WhatsApp chatbots cut FAQ load"], catalog)
    assert fit.service_id == "ai_chatbots" and "whatsapp" in fit.hits
    assert service_fit(["Missed calls cost appointments"], catalog).service_id == "ai_callbots"
    none = service_fit(["The history of the printing press"], catalog)
    assert none.service_id is None and none.label.startswith(INSIGHT_ONLY)
    # unverified services are never suggested, even when their name is in the topic
    assert service_fit(["SEO trends for web design"], catalog).service_id is None


def test_unverified_services_are_not_claimed() -> None:
    catalog = load_services()
    texts = [("caption", "Our SEO team gets you ranked."),
             ("post.headline", "We build web design that converts"),
             ("caption", "SEO is changing because of AI answers."),
             ("cta", "Ask us about AI chatbots")]
    problems = unverified_claims(texts, catalog)
    assert len(problems) == 2 and problems[0].startswith('caption "Our SEO')
    assert "post.headline" in problems[1]


def test_insight_only_has_no_sales_ask() -> None:
    assert cta_problems(INSIGHT_ONLY, "Book a free consultation today")
    assert cta_problems(INSIGHT_ONLY, "Jetzt KI-Potenzialanalyse anfragen")
    assert not cta_problems(INSIGHT_ONLY, "Which task would you hand to AI first?")
    assert not cta_problems("AI chatbots", "Book a call: KI-Chatbot entwickeln")


def test_calendar_rows_get_a_service_fit_line() -> None:
    rows = [{"Row": "1", "Topic": "AI agents for reporting"},
            {"Row": "2", "Topic": "A museum reopens"}]
    lines = service_lines(rows, Path("config/services.json"))
    assert lines[0].startswith("Service fit: row 1 AI agents & workflows")
    assert "row 2 insight-only" in lines[0] and "reject a row" in lines[1]
    assert service_lines(rows, Path("missing/services.json"))[0].startswith(
        "Service fit left out")
