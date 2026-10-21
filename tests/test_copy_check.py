"""Phase 1 (GERMAN_CONTENT_AND_IMAGE_WORKFLOW_PRD.md): the free copy check's claims, address and
cross-platform checks (content/copy_check.py, config/copy_rules.json). Offline."""

from content_automation.content.brief import Caption, ContentBrief, ImageSlot
from content_automation.content.copy_check import (
    claim_problems,
    copy_items,
    item_problems,
    load_rules,
    near_duplicates,
)
from content_automation.content.directions import load_directions


def test_claims_need_the_evidence() -> None:
    evidence = "Google results and the API found 26.2% of the pages, according to the paper."
    rules = load_rules()
    supported = [("body", "Im Test fanden die Ersatz-Tools nur 26,2 % der Seiten."),
                 ("caption", "Laut Google sehen Sie das in 5 Minuten, rund um die Uhr, 24/7.")]
    assert claim_problems("[copy] post", supported, evidence, rules) == []
    found = claim_problems("[copy] post", [
        ("ad", "73 % der KMU nutzen 2026 schon KI, laut Bitkom; OpenAI bestätigt die Studie.")],
        "no figures here", rules)
    assert len(found) == 1 and "unbelegte Aussage" in found[0]
    for claim in ('"73"', '"2026"', '"OpenAI"', '"Bitkom"', '"Studie"'):
        assert claim in found[0]


def _post(caption: str) -> ContentBrief:
    slot = ImageSlot.model_validate({"format": "statement", "direction": "FB-1", "copy": {
        "headline": "Empfiehlt ChatGPT Ihre Firma?", "sub": "Fragen Sie selbst nach.",
        "cta": "Mehr erfahren", "illustration": "a laptop"}})
    return ContentBrief.model_construct(
        post=slot, ad=None, carousel=None, platform="facebook", topic="KI-Suche",
        service="insight-only", cta="Welche Frage stellen Ihre Kunden?", caption=None,
        captions={"facebook_post": Caption(hook=caption, takeaways=["a", "b", "c"],
                                           question="Was meinen Sie?")})


def test_the_address_covers_the_caption() -> None:
    catalog = load_directions()
    good = _post("Wird Ihre Firma in ChatGPT genannt?")
    item = copy_items(good, catalog)[0]
    assert not [p for p in item_problems(item, good) if 'not "du"' in p]
    wrong = _post("Wird deine Firma in ChatGPT genannt?")
    found = [p for p in item_problems(copy_items(wrong, catalog)[0], wrong) if 'not "du"' in p]
    assert len(found) == 1 and 'caption hook "deine"' in found[0]


def test_same_topic_copy_is_flagged_across_platforms() -> None:
    rules = load_rules()
    caption = "Ein KI-Zitat zeigt, wo etwas steht. Ob es stimmt, zeigt es nicht."
    same = near_duplicates("[copy] week", [
        ("BG-1 (linkedin_post)", "Ihre KI zitiert. Ihr Name steht drunter.", caption),
        ("BG-2 (facebook_post)", "Ihre KI zitiert. Ihr Name steht drunter!", caption)], rules)
    assert len(same) == 2 and all("near-identical" in line for line in same)
    assert near_duplicates("[copy] week", [
        ("BG-1 (linkedin_post)", "Ihre KI zitiert. Ihr Name steht drunter.", caption),
        ("BG-2 (facebook_post)", "Wie sicher sind Ihre Quellen?",
         "Vier Tools zitierten Erfundenes. So prüfen Sie Ihre Quellen in Minuten.")],
        rules) == []
