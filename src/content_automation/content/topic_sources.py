"""Topic sources: the allowlist of authentic German sources (config/topic_sources.json) and the
free check of a topic candidate's sources, shared by `ca topics refill` and `ca topics search`.

One GET per source URL with the check-sources fetcher (youtube/sources.fetch_page; tests set its
TRANSPORT). A source passes when its domain, and the final URL after redirects, is on the
allowlist (or a subdomain of an entry), it answers HTTP 200 with a page title and a publication
date (from the page's metadata, else the candidate's stated date found in the page text) no
older than maxAgeDays unless the candidate is evergreen, and its quote is in the page text.
Every number (years, percentages and prices too) and every named study of the candidate must
then occur in its sources' text. The first problem refuses the candidate; nothing is fixed.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import ConfigDict, Field

from content_automation.content.topic_pool import TopicSource
from content_automation.core.files import CamelModel
from content_automation.youtube.sources import Page, fetch_page, normalize

CONFIG_FILE = Path("config/topic_sources.json")
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DOTTED = re.compile(r"(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})")
MONTHS = ("januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september",
          "oktober", "november", "dezember")
_STUDY = re.compile(r"[\wäöüßÄÖÜ-]*(?:[Ss]tudie|[Uu]mfrage|[Rr]eport|[Ll]agebericht|[Ll]agebild"
                    r"|[Ss]urvey|[Ss]tudy|[Ii]ndex)[\wäöüß-]*")
_PROPER = re.compile(r"\s+(?:(?:des|der|von|vom|zur|zum|of|by|from)\s+)?([A-ZÄÖÜ][\wäöüßÄÖÜ&-]+)")
_STUDY_STOP = frozenset({"des", "der", "von", "vom", "zur", "zum", "of", "by", "from"})


class TopicSourcesError(ValueError):
    """config/topic_sources.json is missing or invalid."""


@dataclass(frozen=True)
class Domain:
    domain: str
    name: str
    tier: int
    status: str  # confirmed | to confirm


@dataclass(frozen=True)
class Allowlist:
    domains: tuple[Domain, ...]
    max_age_days: int

    def find(self, url: str) -> Domain | None:
        """The entry of the URL's host (the longest matching domain), None: not allowed."""
        host = host_of(url)
        matches = [entry for entry in self.domains
                   if host == entry.domain or host.endswith(f".{entry.domain}")]
        return max(matches, key=lambda entry: len(entry.domain), default=None)

    def by_tier(self) -> dict[str, list[dict[str, str]]]:
        tiers: dict[str, list[dict[str, str]]] = {"tier1": [], "tier2": [], "tier3": []}
        for entry in self.domains:
            tiers.setdefault(f"tier{entry.tier}", []).append(
                {"domain": entry.domain, "name": entry.name})
        return tiers


class SourceIn(CamelModel):
    """A source as Codex writes it into a brief."""

    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=12, max_length=500)
    publisher: str = ""
    date: str = ""  # the publication date Codex read on the page
    title: str = ""
    quote: str = Field(min_length=20, max_length=400)  # word for word from the page


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def load_allowlist(path: Path = CONFIG_FILE) -> Allowlist:
    found = path if path.is_file() or path.is_absolute() else _PROJECT_ROOT / path
    try:
        data = json.loads(found.read_text(encoding="utf-8"))
        domains = tuple(Domain(str(item["domain"]).lower(), str(item["name"]), int(item["tier"]),
                               str(item.get("status", "to confirm")))
                        for item in data["domains"])
        max_age = int(data.get("maxAgeDays", 120))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise TopicSourcesError(f"{path}: {error}") from None
    if not domains:
        raise TopicSourcesError(f"{path}: needs at least one domain")
    return Allowlist(domains, max_age)


def parse_date(text: str) -> date | None:
    """YYYY-MM-DD (also at the start of a timestamp), DD.MM.YYYY or "D. Monat YYYY"."""
    value = text.strip().lower()
    try:
        if found := _ISO.search(value):
            return date(int(found[1]), int(found[2]), int(found[3]))
        if found := _DOTTED.search(value):
            return date(int(found[3]), int(found[2]), int(found[1]))
        for number, month in enumerate(MONTHS, 1):
            if spelled := re.search(rf"(\d{{1,2}})\.?\s+{month}\s+(\d{{4}})", value):
                return date(int(spelled[2]), number, int(spelled[1]))
    except ValueError:
        return None
    return None


def _stated_date(stated: str, page_text: str) -> date | None:
    """The candidate's date when the page text shows it (pages without date metadata)."""
    claimed = parse_date(stated)
    if claimed is None:
        return None
    text = normalize(page_text)
    forms = (claimed.isoformat(), f"{claimed.day:02d}.{claimed.month:02d}.{claimed.year}",
             f"{claimed.day}.{claimed.month}.{claimed.year}",
             f"{claimed.day}. {MONTHS[claimed.month - 1]} {claimed.year}")
    return claimed if any(form in text for form in forms) else None


def study_names(text: str) -> list[str]:
    """Every study, survey, report or index the text names, with up to 2 proper nouns after it
    ("Bitkom-Studie", "Lagebericht des BSI")."""
    names: list[str] = []
    for match in _STUDY.finditer(text):
        words = [match.group(0)]
        rest = text[match.end():]
        for _ in range(2):
            proper = _PROPER.match(rest)
            if proper is None:
                break
            words.append(proper.group(1))
            rest = rest[proper.end():]
        names.append(" ".join(words))
    return names


def check_sources(sources: Sequence[SourceIn], texts: Sequence[str], allowlist: Allowlist, *,
                  evergreen: bool, today: date, pages: dict[str, Page]
                  ) -> tuple[list[TopicSource], str | None]:
    """The candidate's sources as checked, or the first reason it is refused. `pages` caches
    the fetched pages (one GET per URL per run)."""
    if not sources:
        return [], "no source URL: cite an allowlisted German source (config/topic_sources.json)"
    checked: list[TopicSource] = []
    for source in sources:
        entry = allowlist.find(source.url)
        if entry is None:
            return [], f"{host_of(source.url)} is not on the allowlist (config/topic_sources.json)"
        if source.url not in pages:
            pages[source.url] = fetch_page(source.url)
        page = pages[source.url]
        if page.status != 200:
            answer = f"HTTP {page.status}" if page.status else page.error or "no answer"
            return [], f"{source.url} did not resolve ({answer})"
        if allowlist.find(page.final_url or source.url) is None:
            return [], f"{source.url} redirects off the allowlist ({host_of(page.final_url)})"
        if not page.title:
            return [], f"{source.url}: no page title"
        published = parse_date(page.date) or _stated_date(source.date, page.text)
        if published is None:
            return [], f"{source.url}: no publication date found on the page"
        if (today - published).days > allowlist.max_age_days and not evergreen:
            return [], (f"{host_of(source.url)}: published {published.isoformat()}, older than "
                        f"{allowlist.max_age_days} days (evergreen only for a timeless theme)")
        if normalize(source.quote) not in normalize(page.text):
            return [], f"{host_of(source.url)}: the quote is not in the page text"
        checked.append(TopicSource(source.url, entry.name, published.isoformat(), page.title,
                                   source.quote.strip(), entry.tier))
    found = " ".join(normalize(pages[source.url].text) for source in sources)
    for number in (number for text in texts for number in _NUMBER.findall(normalize(text))):
        if number not in found:
            return [], (f'"{number}" is in no source text (numbers, years, percentages and '
                        "prices only from the source)")
    for name in study_names(" ".join(texts)):
        words = [word for word in re.split(r"[\s-]+", normalize(name))
                 if len(word) >= 3 and word not in _STUDY_STOP]
        if any(word not in found for word in words):
            return [], f'study "{name}" is in no source text'
    return checked, None


__all__ = ["CONFIG_FILE", "Allowlist", "Domain", "SourceIn", "TopicSourcesError",
           "check_sources", "host_of", "load_allowlist", "parse_date", "study_names"]
