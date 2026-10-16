"""What Branded Genius sells: config/services.json (SERVICES_FILE), one entry per service.

Generation uses only "verified" entries (checked against the website, with a source). A topic
maps to one of them or is insight-only; a call to action comes from the service's allowedCtas
(insight-only posts: insightOnlyCtas). The keyword match here is a free first suggestion for
Codex, never the final decision.
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.core.files import CamelModel

CtaType = Literal["question", "enquiry", "visit_site", "none"]
CTA_TYPES: tuple[CtaType, ...] = ("question", "enquiry", "visit_site", "none")
INSIGHT_ONLY: tuple[CtaType, ...] = ("question", "none")  # no sales ask without a service
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class ServicesError(ValueError):
    """services.json is missing or invalid, or a service id is unknown or not verified."""


class _ServiceModel(CamelModel):
    model_config = ConfigDict(extra="forbid")


class ServiceSource(_ServiceModel):
    url: str = ""
    section: str = Field(min_length=1)
    quote_de: str = ""


class AllowedCta(_ServiceModel):
    type: CtaType
    label: str = ""  # the website's button text for enquiries, e.g. "KI-Chatbot entwickeln"


class Service(_ServiceModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1)
    name_de: str = ""
    what_it_does: str = ""
    for_whom: list[str] = Field(default_factory=list)
    problems_solved: list[str] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    topic_keywords: list[str] = Field(default_factory=list)
    allowed_ctas: list[AllowedCta] = Field(default_factory=list)
    proof: list[str] = Field(default_factory=list)
    source: ServiceSource
    status: Literal["verified", "unverified"]

    @model_validator(mode="after")
    def _verified_is_complete(self) -> "Service":
        if self.status == "verified":
            missing = [name for name, value in (
                ("whatItDoes", self.what_it_does), ("source.url", self.source.url),
                ("source.quoteDe", self.source.quote_de), ("topicKeywords", self.topic_keywords),
                ("allowedCtas", self.allowed_ctas)) if not value]
            if missing:
                raise ValueError(f"verified service {self.id} lacks {', '.join(missing)}")
        return self

    def cta_types(self) -> list[CtaType]:
        return list(dict.fromkeys(cta.type for cta in self.allowed_ctas))


class ServiceMatch(_ServiceModel):
    service_id: str
    hits: list[str]


class ServiceCatalog(_ServiceModel):
    note: str = Field(default="", alias="_note")
    checked_on: str = ""
    cta_types_help: dict[str, str] = Field(default_factory=dict, alias="ctaTypes")
    insight_only_ctas: list[CtaType] = Field(default_factory=lambda: list(INSIGHT_ONLY))
    services: list[Service] = Field(min_length=1)
    proof_candidates: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _unique(self) -> "ServiceCatalog":
        ids = [service.id for service in self.services]
        if len(ids) != len(set(ids)):
            raise ValueError("service ids must be unique")
        return self

    def verified(self) -> list[Service]:
        return [service for service in self.services if service.status == "verified"]

    def get(self, service_id: str) -> Service:
        """A verified service by id; ServicesError for an unknown or unverified one."""
        for service in self.services:
            if service.id == service_id:
                if service.status != "verified":
                    raise ServicesError(f"service {service_id} is not verified (config/"
                                        "services.json): never used in generation")
                return service
        raise ServicesError(f"unknown service {service_id!r} (config/services.json: "
                            f"{', '.join(s.id for s in self.verified())})")

    def allowed_cta_types(self, service_id: str | None) -> list[CtaType]:
        """CTA types a post may use: the service's, or the insight-only ones."""
        if service_id is None:
            return list(self.insight_only_ctas)
        return self.get(service_id).cta_types()

    def match(self, text: str) -> list[ServiceMatch]:
        """Verified services whose topic keywords occur in the text, best first (free)."""
        lowered = f" {text.lower()} "
        found: list[ServiceMatch] = []
        for service in self.verified():
            hits = [word for word in service.topic_keywords
                    if re.search(rf"(?<![a-z0-9]){re.escape(word.lower())}(?![a-z0-9])",
                                 lowered)]
            if hits:
                found.append(ServiceMatch(service_id=service.id, hits=hits))
        return sorted(found, key=lambda item: -len(item.hits))


def _resolve(path: Path) -> Path:
    if not path.is_absolute() and not path.exists() and (_PROJECT_ROOT / path).exists():
        return _PROJECT_ROOT / path
    return path


@lru_cache(maxsize=8)
def _load(path: Path, stamp: float) -> ServiceCatalog:
    try:
        return ServiceCatalog.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in issue['loc'])}: {issue['msg']}"
            for issue in error.errors()[:5])
        raise ServicesError(f"{path} is invalid: {problems}") from None


def load_services(path: Path = Path("config/services.json")) -> ServiceCatalog:
    """Read and check services.json; a relative path is also tried in the project folder."""
    found = _resolve(path)
    if not found.is_file():
        raise ServicesError(f"{path} not found: the list of services (Phase D)")
    return _load(found, found.stat().st_mtime)
