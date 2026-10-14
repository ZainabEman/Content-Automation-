"""Strategy and content-language configs (Phase 5 P5-D2, P5-D3); drafts, client to confirm.

config/strategy.json: pillars (description, keywords DE + EN, target share), audiences,
exclusions. config/content.json: the content language (default "en", today's behaviour),
per-platform overrides and the German touch (confirmed 2026-10-14: mostly English with German
touches; templates show the rule, the script check warns when no German element is present).
Missing files give the defaults; nothing switches to German silently.
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
                     r"eine|oder|auch|schon|hier|anfrage|gespräch|ki|mittelstand|"
                     r"digitalisierung|unternehmen|datenschutz|zahnarzt|kanzlei|handwerk)\b",
                     re.IGNORECASE)


@dataclass(frozen=True)
class GermanTouch:
    """config/content.json "german_touch": English content with German touches."""

    share: float = 0.25
    headline_or_cta_de: bool = True
    key_terms_de: bool = True
    hashtags_de: str = "1-2"

    def rule(self) -> str:
        parts = [f"write mostly English with about {self.share:.0%} German touches"]
        if self.headline_or_cta_de:
            parts.append("the headline or the CTA in German")
        if self.key_terms_de:
            parts.append("key terms in German")
        if self.hashtags_de:
            parts.append(f"{self.hashtags_de} German hashtags")
        return "German touch: " + "; ".join(parts) + "."

    @staticmethod
    def present(text: str) -> bool:
        return _GERMAN.search(text) is not None


@dataclass(frozen=True)
class ContentLanguage:
    language: str = "en"
    platforms: dict[str, str] = field(default_factory=dict)
    german_touch: GermanTouch | None = None

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
    touch = data.get("german_touch")
    return ContentLanguage(str(data.get("language", "en")),
                           {str(k): str(v) for k, v in platforms.items()
                            if not str(k).startswith("_")},
                           GermanTouch(float(touch.get("share", 0.25)),
                                       bool(touch.get("headline_or_cta_de", True)),
                                       bool(touch.get("key_terms_de", True)),
                                       str(touch.get("hashtags_de", "1-2")))
                           if isinstance(touch, dict) else None)
