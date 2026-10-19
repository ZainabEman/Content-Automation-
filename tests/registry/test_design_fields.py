"""v5: the registry stores the layout variant, treatment, requires_roman and language (R5.4,
R6.3); a Facebook ad carries its own text fields with a Meta CTA button (R4)."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from content_automation.content.brief import ContentBrief, brief_problems, meta_cta_buttons
from content_automation.registry import db_path, open_registry
from content_automation.registry.audit import list_events
from content_automation.registry.db import RegistryError
from content_automation.registry.items import create_item, get_item, set_design


@pytest.fixture
def conn(isolated: Path) -> Iterator[sqlite3.Connection]:
    connection = open_registry(db_path(Path("state")), Path("config/registry.json"))
    yield connection
    connection.close()


def test_design_fields_are_stored_and_logged(conn: sqlite3.Connection) -> None:
    item = create_item(conn, kind="post", title="KI im Team", topic="t", platforms=["linkedin"],
                       deliverable="linkedin_post")
    assert item.layout_variant is None and item.requires_roman is False
    set_design(conn, item.id, layout_variant="LI-R1", background_treatment="dark_founder",
               requires_roman=True, language="de")
    found = get_item(conn, item.id)
    assert (found.layout_variant, found.background_treatment, found.requires_roman,
            found.language) == ("LI-R1", "dark_founder", True, "de")
    assert any(e.details.get("design") for e in list_events(conn, item_id=item.id))
    with pytest.raises(RegistryError, match="not a design field"):
        set_design(conn, item.id, colour="red")


def _ad_brief(ad_fields: dict[str, str] | None) -> ContentBrief:
    ad: dict[str, object] = {"format": "ad", "direction": "FA-1",
                             "copy": {"headline": "Jede Anfrage verdient eine *Antwort*"}}
    if ad_fields is not None:
        ad["adFields"] = ad_fields
    return ContentBrief.model_validate({
        "topic": "KI-Chatbots", "platform": "facebook", "formats": ["ad"],
        "service": "AI chatbots", "audience": "Praxen", "objective": "Termine",
        "keyPoints": ["a", "b", "c"], "ad": ad,
        "caption": {"hook": "h", "takeaways": ["a", "b", "c"], "question": "q?"},
        "cta": "Analyse anfragen", "link": "https://brandedgenius.de",
        "hashtags": ["#KI", "#Chatbots", "#BrandedGenius"]})


def test_facebook_ad_needs_its_fields_and_a_meta_button() -> None:
    assert "Learn more" in meta_cta_buttons()
    kwargs: dict[str, object] = {"services": [], "known_article_ids": set()}
    missing = brief_problems(_ad_brief(None), **kwargs)  # type: ignore[arg-type]
    assert any("ad.adFields" in p for p in missing)
    fields = {"primaryText": "Ihr Vertrieb schläft. Unser KI-Chatbot nicht.",
              "headline": "KI-Chatbot für Praxen", "description": "Kostenfrei testen",
              "ctaButton": "Jetzt klicken"}
    wrong = brief_problems(_ad_brief(fields), **kwargs)  # type: ignore[arg-type]
    assert any("not one of Meta's standard buttons" in p for p in wrong)
    fields["ctaButton"] = "Learn more"
    assert not [p for p in brief_problems(_ad_brief(fields), **kwargs)  # type: ignore[arg-type]
                if "adFields" in p]
