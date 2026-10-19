"""Strategy and content-language configs (Phase 5 P5-D2, P5-D3); drafts, client to confirm.

config/strategy.json: pillars (description, keywords DE + EN, target share), audiences,
exclusions. config/content.json: the content language (default "de" since v5, PRD R1.4),
per-platform overrides and the layout language (live fix, only for a platform set to "en":
which part of a post is English and which German; templates show the rule, the script check
warns where German is missing). Missing files give the defaults.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from content_automation.registry.db import RegistryError

DEFAULT_PILLARS = ("german_problems", "ai_risks", "ai_misuse", "ai_mistakes", "ai_solutions")


@dataclass(frozen=True)
class Pillar:
    key: str
    description: str
    keywords: tuple[str, ...]
    target_share: float


@dataclass(frozen=True)
class Strategy:
    pillars: tuple[Pillar, ...]
    audiences: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    max_age_days: int = 90
    weights: dict[str, float] = field(default_factory=dict)
    duplicate_threshold: float = 0.8

    def pillar(self, key: str) -> Pillar | None:
        return next((pillar for pillar in self.pillars if pillar.key == key), None)


# German words that mark a German touch in English copy (umlauts and ß count as well).
_GERMAN = re.compile(r"[äöüß]|\b(und|der|das|mit|für|nicht|jetzt|ihr|ihre|ihren|wir|kostenlos|"
                     r"mehr|erfahren|termin|buchen|kunden|praxis|beratung|ist|auf|zum|zur|"
                     r"eine|oder|auch|schon|hier|anfrage|gespräch|ki|mittelstand|im|zu|den|dem|von|bei|"
                     r"ohne|wie|braucht|brauchen|folgen|kontrolle|menschliche|sicher|nutzen|"
                     r"digitalisierung|unternehmen|datenschutz|zahnarzt|kanzlei|handwerk)\b",
                     re.IGNORECASE)


@dataclass(frozen=True)
class LayoutLanguage:
    """config/content.json "layoutLanguage": the language of each part of a post."""

    headline: str = "en"
    subtitle: str = "de"
    tag: str = "en"
    bullets: str = "en"
    body: str = "en"
    caption: str = "en"
    cta: str = "en+de"
    caption_ends_german: bool = True

    def rule(self) -> str:
        parts = {"headline": self.headline, "tag": self.tag, "bullets": self.bullets,
                 "body": self.body, "caption": self.caption, "subtitle": self.subtitle}
        english = [name for name, lang in parts.items() if lang == "en"]
        german = [name for name, lang in parts.items() if lang == "de"]
        cta = ("the CTA in English plus a short German CTA (e.g. \"Jetzt folgen\", \"Mehr "
               "erfahren\")" if self.cta == "en+de" else f"the CTA in {self.cta}")
        end = "; the caption ends with one German line" if self.caption_ends_german else ""
        return (f"Layout language: {', '.join(english)} in English; {', '.join(german)} in "
                f"German; {cta}{end}.")

    @staticmethod
    def present(text: str) -> bool:
        """A German element: an umlaut, ß or a common German word."""
        return _GERMAN.search(text) is not None


@dataclass(frozen=True)
class ContentLanguage:
    language: str = "de"  # v5 (PRD R1.4): German is the default for everything the audience sees
    platforms: dict[str, str] = field(default_factory=dict)
    layout_language: LayoutLanguage | None = None

    def for_platform(self, platform: str | None) -> str:
        return self.platforms.get(platform or "", self.language)


def _read(path: Path) -> dict[str, object]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RegistryError(f"{path} is not readable JSON: {error}") from None
    if not isinstance(data, dict):
        raise RegistryError(f"{path} must hold a JSON object.")
    return data


def _list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def load_strategy(path: Path) -> Strategy:
    if not path.is_file():
        return Strategy(tuple(Pillar(key, key, (), 0.2) for key in DEFAULT_PILLARS))
    data = _read(path)
    raw = data.get("pillars")
    if not isinstance(raw, dict) or not raw:
        raise RegistryError(f'{path}: "pillars" must name each pillar.')
    pillars = tuple(
        Pillar(str(key), str(value.get("description", key)),
               tuple(str(k).lower() for lang in ("de", "en")
                     for k in _list(value.get("keywords", {}).get(lang))),
               float(value.get("targetShare", 0)))
        for key, value in raw.items() if not str(key).startswith("_") and isinstance(value, dict)
    )
    research = data.get("research") if isinstance(data.get("research"), dict) else {}
    assert isinstance(research, dict)
    weights = data.get("scoreWeights") if isinstance(data.get("scoreWeights"), dict) else {}
    assert isinstance(weights, dict)
    return Strategy(
        pillars=pillars,
        audiences=tuple(str(a) for a in _list(data.get("audiences"))),
        exclusions=tuple(str(e) for e in _list(data.get("exclusions"))),
        max_age_days=int(research.get("maxAgeDays", 90)),
        weights={str(k): float(v) for k, v in weights.items() if not str(k).startswith("_")},
        duplicate_threshold=float(research.get("duplicateThreshold", 0.8)),
    )


def load_content(path: Path) -> ContentLanguage:
    if not path.is_file():
        return ContentLanguage()
    data = _read(path)
    platforms = data.get("platforms") if isinstance(data.get("platforms"), dict) else {}
    assert isinstance(platforms, dict)
    found = data.get("layoutLanguage")
    layout = None
    if isinstance(found, dict):
        layout = LayoutLanguage(**{key: str(found[name]) for key, name in (
            ("headline", "headline"), ("subtitle", "subtitle"), ("tag", "tag"),
            ("bullets", "bullets"), ("body", "body"), ("caption", "caption"), ("cta", "cta"))
            if name in found}, caption_ends_german=bool(found.get("captionEndsGerman", True)))
    return ContentLanguage(str(data.get("language", "de")),
                           {str(k): str(v) for k, v in platforms.items()
                            if not str(k).startswith("_")}, layout)
