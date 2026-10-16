"""config/services.json: verified services from the website, the keyword pre-match, CTAs."""

import json
from pathlib import Path

import pytest

from content_automation.references.services import ServicesError, load_services

REPO = Path(__file__).resolve().parents[1]


def test_repo_services_are_verified_with_sources() -> None:
    catalog = load_services(REPO / "config" / "services.json")
    verified = catalog.verified()
    assert [s.id for s in verified] == ["ai_agents_workflows", "ai_chatbots", "ai_callbots",
                                       "marketing_sales_automation", "ai_workshops"]
    for service in verified:
        assert service.source.url.startswith("https://brandedgenius.de")
        assert service.source.quote_de and service.what_it_does
        assert service.proof == []  # no confirmed proof yet
    assert {s.id for s in catalog.services if s.status == "unverified"} >= {"seo", "web_design"}


def test_unverified_or_unknown_ids_are_refused() -> None:
    catalog = load_services(REPO / "config" / "services.json")
    with pytest.raises(ServicesError, match="not verified"):
        catalog.get("seo")
    with pytest.raises(ServicesError, match="unknown service"):
        catalog.get("crypto")


def test_cta_types_per_service_and_insight_only() -> None:
    catalog = load_services(REPO / "config" / "services.json")
    assert catalog.allowed_cta_types(None) == ["question", "none"]
    assert "enquiry" in catalog.allowed_cta_types("ai_callbots")


def test_keyword_match_suggests_services() -> None:
    catalog = load_services(REPO / "config" / "services.json")
    matches = catalog.match("Clinics miss calls after 18:00; a WhatsApp chatbot answers")
    assert [m.service_id for m in matches][:2] == ["ai_chatbots", "ai_callbots"]
    assert catalog.match("Football results from the weekend") == []


def test_a_verified_service_needs_its_source(tmp_path: Path) -> None:
    data = json.loads((REPO / "config" / "services.json").read_text(encoding="utf-8"))
    data["services"][0]["source"]["url"] = ""
    path = tmp_path / "services.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ServicesError, match="source.url"):
        load_services(path)
