"""Phase D step 5: which verified service a topic is about (config/services.json), free.

A topic matches a service by its topicKeywords (whole words); no match = "insight-only": the post
shares the insight and names no service, and its call to action is a question or nothing
(insightOnlyCtas). Copy may only claim verified services: "we/our" next to an unverified one
(SEO, web design, PPC, ...) is refused, as is a sales ask in an insight-only post.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from content_automation.references.services import ServiceCatalog

INSIGHT_ONLY = "insight-only"
_SALES = re.compile(
    r"\b(book(?:ing)?|call us|dm|direct message|contact us|consultation|demo|free (?:audit|check)"
    r"|our offer|get a quote|pricing|anfragen|termin\w*|kontakt\w*|beratung\w*|"
    r"potenzialanalyse)\b", re.IGNORECASE)
_CLAIM = r"\b(?:we|we'll|we're|our|us|wir|unser\w*)\b[^.!?\n]{{0,40}}\b(?:{terms})\b"


@dataclass(frozen=True)
class Fit:
    """The service a topic fits, or none (insight-only), with the keywords found."""

    service_id: str | None
    name: str
    hits: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.service_id is None:
            return f"{INSIGHT_ONLY} (no service keyword)"
        return f"{self.name} ({', '.join(self.hits[:3])})"


def service_fit(texts: Iterable[str], catalog: ServiceCatalog) -> Fit:
    matches = catalog.match(" ".join(texts))
    if not matches:
        return Fit(None, INSIGHT_ONLY)
    best = matches[0]
    return Fit(best.service_id, catalog.get(best.service_id).name, best.hits)


def _unverified_terms(catalog: ServiceCatalog) -> list[str]:
    """Names of the unverified services, split at & and brackets; a verified keyword is left."""
    verified = {word.lower() for service in catalog.verified() for word in service.topic_keywords}
    terms: list[str] = []
    for service in catalog.services:
        if service.status == "verified":
            continue
        for name in (service.name, service.name_de):
            for part in re.split(r"[&()/,]| and ", name):
                term = part.strip().lower()
                if len(term) >= 3 and term not in verified and term not in terms:
                    terms.append(term)
    return terms


def unverified_claims(texts: Iterable[tuple[str, str]], catalog: ServiceCatalog) -> list[str]:
    """Copy that presents an unverified service as Branded Genius's own."""
    terms = _unverified_terms(catalog)
    if not terms:
        return []
    pattern = re.compile(_CLAIM.format(terms="|".join(re.escape(t) for t in terms)),
                         re.IGNORECASE)
    return [f'{where} "{text}": names a service Branded Genius does not offer (config/'
            "services.json lists it unverified); write about verified services only"
            for where, text in texts if pattern.search(text)]


def cta_problems(service: str, cta: str) -> list[str]:
    """An insight-only post asks a question or nothing (service names: brief.py checks them)."""
    if service == INSIGHT_ONLY and _SALES.search(cta):
        return [f'cta "{cta}": an insight-only post has no sales ask: a question or no call to '
                "action (config/services.json insightOnlyCtas)"]
    return []


__all__ = ["INSIGHT_ONLY", "Fit", "cta_problems", "service_fit", "unverified_claims"]
