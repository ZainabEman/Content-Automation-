"""The free German quality pass (PRD v5 R1.6) on audience-facing text, before any dry run.

Checks per text (config/german_quality.json, editable):
- umlauts and ß: a word written as ae/oe/ue/ss where German writes ä/ö/ü/ß (known words: error;
  a word that starts with Ae/Oe/Ue: warning);
- spelling: frequent German misspellings (error). A full spell check needs a dictionary, which is
  not part of this free offline pass;
- English leftovers: English phrases ("learn more", "book a call") or two different English
  function words in one text (error), one such word (warning). Loanwords that are normal in
  German business copy (Business, Team, Workflow, KI-Tools …) are allowed;
- generic AI marketing language: the banned phrase list (error);
- form of address: "du" forms when the default is "Sie" (Q3), or the reverse (warning).

Hashtags (#…), URLs and e-mail addresses are skipped.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CONFIG_FILE = Path("config/german_quality.json")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SKIP = re.compile(r"#\w+|https?://\S+|www\.\S+|\S+@\S+\.\w+")
_TOKEN = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß'’-]*")
_UMLAUT_START = re.compile(r"\b(?:Ae|Oe|Ue)[a-zäöüß]{2,}")
_DU = re.compile(r"\b(?:du|dich|dir|dein|deine|deinen|deinem|deiner|deines|euch|euer|eure|"
                 r"euren|eurem)\b", re.IGNORECASE)
_SIE = re.compile(r"(?<![.!?:]\s)(?<!^)\b(?:Sie|Ihnen|Ihr|Ihre|Ihren|Ihrem|Ihrer|Ihres)\b")
_UMLAUT_START_OK = frozenset({"Aerobic", "Aerosol", "Oetker", "Uelzen", "Oeynhausen"})


@dataclass(frozen=True)
class GermanRules:
    address: str
    transliterations: dict[str, str]
    misspellings: dict[str, str]
    banned_phrases: tuple[str, ...]
    english_words: frozenset[str]
    english_phrases: tuple[str, ...]
    allow_english: frozenset[str]


@dataclass
class GermanReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors


def _resolve(path: Path) -> Path:
    if not path.is_absolute() and not path.exists() and (_PROJECT_ROOT / path).exists():
        return _PROJECT_ROOT / path
    return path


@lru_cache(maxsize=4)
def load_rules(path: Path = CONFIG_FILE) -> GermanRules:
    data = json.loads(_resolve(path).read_text(encoding="utf-8"))
    return GermanRules(
        address=str(data.get("address", "Sie")),
        transliterations={str(k): str(v) for k, v in data.get("transliterations", {}).items()},
        misspellings={str(k): str(v) for k, v in data.get("misspellings", {}).items()},
        banned_phrases=tuple(str(item) for item in data.get("bannedPhrases", [])),
        english_words=frozenset(str(item).lower() for item in data.get("englishWords", [])),
        english_phrases=tuple(str(item).lower() for item in data.get("englishPhrases", [])),
        allow_english=frozenset(str(item) for item in data.get("allowEnglish", [])),
    )


def _clean(text: str) -> str:
    return _SKIP.sub(" ", text.replace("*", " ").replace("[[", " ").replace("]]", " "))


def _phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![\wäöüß]){re.escape(phrase)}(?![\wäöüß])", text,
                     re.IGNORECASE) is not None


def check_text(text: str, where: str = "text", rules: GermanRules | None = None
               ) -> GermanReport:
    """Every problem in one audience-facing German text."""
    rules = rules or load_rules()
    report = GermanReport()
    body = _clean(text)
    tokens = _TOKEN.findall(body)
    for token in tokens:
        bare = token.strip("'’-")
        if bare in rules.transliterations:
            report.errors.append(f'{where}: "{bare}" → "{rules.transliterations[bare]}" '
                                 "(umlauts and ß, not ae/oe/ue/ss)")
        elif bare in rules.misspellings:
            report.errors.append(f'{where}: "{bare}" → "{rules.misspellings[bare]}" (spelling)')
    for match in _UMLAUT_START.finditer(body):
        word = match.group(0)
        if word not in rules.transliterations and word not in _UMLAUT_START_OK:
            report.warnings.append(f'{where}: "{word}" may need an umlaut (Ä/Ö/Ü)')
    for phrase in rules.banned_phrases:
        if _phrase(body, phrase):
            report.errors.append(f'{where}: "{phrase}" is generic AI marketing language; say '
                                 "it plainly")
    english_phrases = [phrase for phrase in rules.english_phrases if _phrase(body, phrase)]
    english_words = sorted({token.lower() for token in tokens
                            if token not in rules.allow_english
                            and token.lower() in rules.english_words})
    if english_phrases or len(english_words) >= 2:
        found = english_phrases + english_words
        report.errors.append(f"{where}: English left in German text ({', '.join(found[:6])})")
    elif english_words:
        report.warnings.append(f'{where}: "{english_words[0]}" looks English; check it')
    if rules.address == "Sie" and _DU.search(body):
        report.warnings.append(f'{where}: uses the "du" form; the default address is "Sie" (Q3)')
    elif rules.address == "du" and _SIE.search(body):
        report.warnings.append(f'{where}: uses the "Sie" form; the default address is "du"')
    return report


def check_texts(texts: Iterable[tuple[str, str]], rules: GermanRules | None = None
                ) -> GermanReport:
    """(where, text) pairs: all problems together."""
    rules = rules or load_rules()
    report = GermanReport()
    for where, text in texts:
        if not text or not text.strip():
            continue
        found = check_text(text, where, rules)
        report.errors += found.errors
        report.warnings += found.warnings
    return report


__all__ = ["CONFIG_FILE", "GermanReport", "GermanRules", "check_text", "check_texts",
           "load_rules"]
