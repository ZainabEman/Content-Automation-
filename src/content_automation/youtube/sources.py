"""`ca youtube check-sources BG-x` (PRD v5 R9.5): free checks of a topic's sources.

For every source URL of the research file: HTTP status, final URL after redirects, page title and
publication date where the page states them. Every quotation must appear in that page's text;
every fact of sections 7 and 11a is flagged when its source page does not contain its numbers and
most of its key words. A fact whose words are found is still "needs human check" (the check only
sees words, not meaning): nothing is ever marked verified automatically. The results replace
the research file's VERIFICATION section. A failed check (a dead URL, a quotation not in the
page, a fact its source does not mention) blocks script writing until it is fixed or Roman
overrides it (`--override "<reason>"`, logged in the registry and package.json).

The only network access is `fetch_page`; tests set TRANSPORT to an httpx.MockTransport serving
local HTML fixtures, so no test reaches the internet.
"""

from __future__ import annotations

import html as html_lib
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx

from content_automation.youtube.research import Research

TRANSPORT: httpx.BaseTransport | None = None  # tests: httpx.MockTransport with fixtures
TIMEOUT_SECONDS = 20.0
USER_AGENT = "BrandedGenius-ContentAutomation/1.0 (source check)"
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META = re.compile(r"<meta\s+[^>]*>", re.I)
_ATTR = re.compile(r'([\w:-]+)\s*=\s*["\']([^"\']*)["\']')
_TIME = re.compile(r"<time[^>]+datetime=[\"']([^\"']+)[\"']", re.I)
_TAGS = re.compile(r"<(script|style|noscript)[^>]*>.*?</\1>|<[^>]+>", re.I | re.S)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_WORD = re.compile(r"[a-zäöüß]{5,}")
_STOP = frozenset({"einer", "eines", "einem", "einen", "diese", "dieser", "dieses", "werden",
                   "wurde", "wurden", "haben", "hatte", "nicht", "durch", "unter", "sowie",
                   "zwischen", "their", "which", "about", "would", "there", "these", "those"})
KEY_WORD_SHARE = 0.6


@dataclass
class Page:
    url: str
    ok: bool
    status: int | None = None
    final_url: str = ""
    title: str = ""
    date: str = ""
    text: str = ""
    error: str = ""


@dataclass
class SourceReport:
    lines: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    human_checks: int = 0

    @property
    def passed(self) -> bool:
        return not self.failures


def normalize(text: str) -> str:
    """Lower case, one kind of quote, dash and space; for finding a quotation in a page."""
    value = unicodedata.normalize("NFKC", html_lib.unescape(text)).lower()
    value = re.sub(r"[\"„“”»«‚‘’']", "", value)
    value = re.sub(r"[‐‑‒–—]", "-", value)
    return re.sub(r"\s+", " ", value).strip()


def _meta(html: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for tag in _META.findall(html):
        attrs = {key.lower(): value for key, value in _ATTR.findall(tag)}
        name = attrs.get("property") or attrs.get("name") or attrs.get("itemprop")
        if name and "content" in attrs:
            found.setdefault(name.lower(), attrs["content"])
    return found


def page_text(html: str) -> str:
    try:
        import trafilatura

        extracted = trafilatura.extract(html, include_comments=False)
    except Exception:  # noqa: BLE001 - fall back to plain tag stripping
        extracted = None
    stripped = _TAGS.sub(" ", html)
    return f"{extracted or ''} {stripped}"


def fetch_page(url: str) -> Page:
    """One GET with redirects; never raises (a failure is a Page with ok False)."""
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=True, transport=TRANSPORT,
                          headers={"User-Agent": USER_AGENT}) as client:
            response = client.get(url)
    except httpx.HTTPError as error:
        return Page(url, ok=False, error=f"{type(error).__name__}: {error}"[:200])
    html = response.text
    meta = _meta(html)
    title_match = _TITLE.search(html)
    title = meta.get("og:title") or (html_lib.unescape(title_match.group(1)).strip()
                                     if title_match else "")
    date = (meta.get("article:published_time") or meta.get("datepublished")
            or meta.get("date") or meta.get("dc.date") or "")
    if not date:
        time_match = _TIME.search(html)
        date = time_match.group(1) if time_match else ""
    return Page(url, ok=response.status_code < 400, status=response.status_code,
                final_url=str(response.url), title=re.sub(r"\s+", " ", title)[:200],
                date=date[:32], text=page_text(html) if response.status_code < 400 else "")


def fact_found(fact: str, text: str) -> bool:
    """The fact's numbers and most of its key words occur in the page text."""
    page = normalize(text)
    plain = normalize(fact)
    numbers = _NUMBER.findall(plain)
    if any(number not in page for number in numbers):
        return False
    words = {word for word in _WORD.findall(plain) if word not in _STOP}
    if not words:
        return bool(numbers)
    hits = sum(1 for word in words if word[:6] in page)
    return hits / len(words) >= KEY_WORD_SHARE


def check_sources(research: Research) -> SourceReport:
    """Fetch every source once, then check quotations and facts against the pages."""
    report = SourceReport()
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    report.lines.append(f"Checked {stamp} by ca youtube check-sources (free, automatic). "
                        "\"needs human check\" = words found, meaning not checked.")
    pages: dict[str, Page] = {}
    report.lines.append("Sources:")
    for source in research.sources.values():
        page = fetch_page(source.url) if source.url else Page("", ok=False, error="no URL")
        pages[source.id] = page
        if page.ok:
            moved = f"; final URL {page.final_url}" if page.final_url.rstrip("/") != \
                source.url.rstrip("/") else ""
            report.lines.append(f"- {source.id} OK {page.status}{moved}; title: "
                                f"{page.title or 'not found'}; date: {page.date or 'not stated'}")
        else:
            reason = f"HTTP {page.status}" if page.status else page.error
            report.lines.append(f"- {source.id} FAILED ({reason}): {source.url}")
            report.failures.append(f"{source.id}: the URL does not open ({reason})")
    report.lines.append("Quotations:")
    if not research.quotes:
        report.lines.append("- none in section 8")
    for quote, refs in research.quotes:
        found = [ref for ref in refs if ref in pages and pages[ref].ok
                 and normalize(quote) in normalize(pages[ref].text)]
        if found:
            report.lines.append(f'- FOUND in {", ".join(found)}: "{quote[:80]}"')
        else:
            report.lines.append(f'- NOT FOUND in {", ".join(refs) or "no source"}: '
                                f'"{quote[:80]}"')
            report.failures.append(f'quotation not in its source page: "{quote[:60]}"')
    report.lines.append("Facts (sections 7 and 11a):")
    seen: set[str] = set()
    for fact, refs in [*research.facts, *research.verified]:
        if fact in seen:
            continue
        seen.add(fact)
        found = [ref for ref in refs if ref in pages and pages[ref].ok
                 and fact_found(fact, pages[ref].text)]
        if found:
            report.human_checks += 1
            report.lines.append(f'- needs human check (words found in {", ".join(found)}): '
                                f'"{fact[:80]}"')
        else:
            report.lines.append(f'- NOT FOUND in {", ".join(refs) or "no source"}: '
                                f'"{fact[:80]}"')
            report.failures.append(f'fact its source does not mention: "{fact[:60]}"')
    report.lines.append(f"Result: {'PASSED' if report.passed else 'FAILED'} "
                        f"({len(report.failures)} problem(s); {report.human_checks} fact(s) "
                        "need a human check before use)")
    return report


__all__ = ["Page", "SourceReport", "TRANSPORT", "check_sources", "fact_found", "fetch_page",
           "normalize", "page_text"]
