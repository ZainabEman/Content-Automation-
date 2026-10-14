"""Free scraper (no paid API, no account): httpx + feedparser + trafilatura.

Per source: find article links (the RSS feed first; if there is none or it is empty, links
on the homepage that stay on the same site), keep the newest max_items, skip articles that
are already saved or too old, then fetch each article and extract its title, date, author
and clean text with trafilatura.

Polite by design: a clear user agent, robots.txt is respected for every request, 1–2 s
between requests to the same site (or the site's Crawl-delay, up to 10 s), timeouts, and
one failing article never stops the rest.
"""

import calendar
import html
import json
import random
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import feedparser
import httpx
import trafilatura

from content_automation.core.config import Settings
from content_automation.core.jobs import AdapterMode
from content_automation.research.collectors import USER_AGENT, CollectRequest, CollectResult
from content_automation.research.models import Source, SourceArticle, SourceStats
from content_automation.research.store import article_id, clean_url

DELAY_RANGE_S = (1.0, 2.0)
MAX_CRAWL_DELAY_S = 10.0
TIMEOUT_S = 20.0
MIN_TEXT_CHARS = 300
SUMMARY_CHARS = 400
_ERROR_CHARS = 160
_SKIP_PATH = re.compile(
    r"/(tags?|categor(y|ies)|authors?|page|search|about|contact|privacy|terms|legal|login|"
    r"sign-?up|subscribe|feed|careers|jobs|events?|webinars?|podcasts?|videos?|newsletters?)(/|$)",
    re.IGNORECASE,
)
_SKIP_EXT = re.compile(r"\.(jpe?g|png|gif|webp|svg|pdf|xml|zip|mp4|mp3|css|js)$", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
# WordPress feeds end summaries with "The post <title> appeared first on <site>."
_FEED_FOOTER = re.compile(r"\s*The post .+ appeared first on .+$")


class SourceBlockedError(RuntimeError):
    """The site asks us not to crawl it (robots.txt or a very long Crawl-delay)."""


@dataclass
class _Candidate:
    url: str
    title: str = ""
    published: datetime | None = None
    author: str | None = None
    summary: str = ""


class _Robots:
    """robots.txt of one site: allow all, deny all, or the parsed rules."""

    def __init__(self, rules: RobotFileParser | None, allow_all: bool) -> None:
        self._rules = rules
        self._allow_all = allow_all

    def allowed(self, url: str) -> bool:
        if self._rules is None:
            return self._allow_all
        return self._rules.can_fetch(USER_AGENT, url)

    def crawl_delay(self) -> float | None:
        if self._rules is None:
            return None
        delay = self._rules.crawl_delay(USER_AGENT)
        return float(delay) if delay is not None else None


class _Polite:
    """Every request goes through here: robots.txt check, pacing per site, timeouts."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        sleep: Callable[[float], None],
        delay_range: tuple[float, float],
        rng: random.Random,
    ) -> None:
        self._client = client
        self._sleep = sleep
        self._delay_range = delay_range
        self._rng = rng
        self._robots: dict[str, _Robots] = {}
        self._last_request: dict[str, float] = {}

    def allowed(self, url: str) -> bool:
        return self._robots_for(url).allowed(url)

    def get(self, url: str) -> httpx.Response:
        robots = self._robots_for(url)
        if not robots.allowed(url):
            raise SourceBlockedError(f"robots.txt does not allow {url}")
        delay = robots.crawl_delay()
        if delay is not None and delay > MAX_CRAWL_DELAY_S:
            raise SourceBlockedError(f"robots.txt asks for {delay:g} s between requests")
        response = self._request(url, delay)
        response.raise_for_status()
        return response

    def _request(self, url: str, crawl_delay: float | None = None) -> httpx.Response:
        host = urlsplit(url).netloc.lower()
        wait = max(self._rng.uniform(*self._delay_range), crawl_delay or 0.0)
        last = self._last_request.get(host)
        if last is not None:
            remaining = last + wait - time.monotonic()
            if remaining > 0:
                self._sleep(remaining)
        try:
            return self._client.get(url)
        finally:
            self._last_request[host] = time.monotonic()

    def _robots_for(self, url: str) -> _Robots:
        parts = urlsplit(url)
        host = parts.netloc.lower()
        if host not in self._robots:
            self._robots[host] = self._load_robots(f"{parts.scheme}://{parts.netloc}/robots.txt")
        return self._robots[host]

    def _load_robots(self, robots_url: str) -> _Robots:
        # Same rules as Python's robotparser: 401/403 = deny all, other 4xx = allow all;
        # an unreachable robots.txt (5xx, network error) = deny all, to be safe.
        try:
            response = self._request(robots_url)
        except httpx.HTTPError:
            return _Robots(None, allow_all=False)
        if response.status_code in (401, 403) or response.status_code >= 500:
            return _Robots(None, allow_all=False)
        if response.status_code >= 400:
            return _Robots(None, allow_all=True)
        rules = RobotFileParser()
        rules.parse(response.text.splitlines())
        return _Robots(rules, allow_all=True)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)


class FreeCollector:
    name = "free"
    mode: AdapterMode = "code"

    def __init__(
        self,
        *,
        delay_range: tuple[float, float] = DELAY_RANGE_S,
        timeout_s: float = TIMEOUT_S,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        seed: int | None = None,
    ) -> None:
        self._delay_range = delay_range
        self._timeout_s = timeout_s
        self._transport = transport
        self._sleep = sleep
        self._rng = random.Random(seed)

    def collect(self, request: CollectRequest) -> CollectResult:
        source = request.source
        stats = SourceStats(source=source.name)
        articles: list[SourceArticle] = []
        headers = {"User-Agent": USER_AGENT, "Accept-Language": "en"}
        with httpx.Client(
            headers=headers,
            timeout=self._timeout_s,
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            polite = _Polite(
                client, sleep=self._sleep, delay_range=self._delay_range, rng=self._rng
            )
            candidates: list[_Candidate] = []
            if source.use_feed and source.rss_url:
                try:
                    candidates = _from_feed(polite, source.rss_url)
                    stats.via = "rss"
                except Exception as error:
                    stats.errors.append(f"feed: {_short(error)}")
            if not candidates:
                try:
                    candidates = _from_homepage(polite, source.url)
                    stats.via = "homepage"
                except Exception as error:
                    stats.errors.append(f"homepage: {_short(error)}")
                    return CollectResult(stats=stats)
            stats.found = len(candidates)
            seen: set[str] = set()
            for candidate in candidates[: request.max_items]:
                key = article_id(candidate.url)
                if key in request.known_ids or key in seen:
                    stats.duplicates += 1  # already saved: not fetched again
                    continue
                seen.add(key)
                if candidate.published is not None and candidate.published < request.since:
                    stats.too_old += 1
                    continue
                if not polite.allowed(candidate.url):
                    stats.blocked += 1
                    continue
                try:
                    article = _read_article(polite, candidate, source, key, request.since, stats)
                except Exception as error:  # one article never stops the others
                    stats.failed += 1
                    stats.errors.append(f"{candidate.url}: {_short(error)}")
                    continue
                if article is not None:
                    articles.append(article)
        return CollectResult(stats=stats, articles=articles)


def _from_feed(polite: _Polite, feed_url: str) -> list[_Candidate]:
    feed: Any = feedparser.parse(polite.get(feed_url).content)
    candidates = []
    for entry in feed.entries:
        link = entry.get("link")
        if not link:
            continue
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        candidates.append(
            _Candidate(
                url=str(link),
                title=str(entry.get("title") or "").strip(),
                published=datetime.fromtimestamp(calendar.timegm(parsed), UTC) if parsed else None,
                author=str(entry.get("author") or "").strip() or None,
                summary=_FEED_FOOTER.sub("", _plain(str(entry.get("summary") or ""))),
            )
        )
    oldest = datetime.min.replace(tzinfo=UTC)
    return sorted(candidates, key=lambda c: c.published or oldest, reverse=True)


def _from_homepage(polite: _Polite, home_url: str) -> list[_Candidate]:
    """Links on the homepage that stay on the same site and look like articles."""
    response = polite.get(home_url)
    parser = _LinkParser()
    parser.feed(response.text)
    site = _site(str(response.url))
    candidates: list[_Candidate] = []
    seen: set[str] = set()
    for href in parser.links:
        url = urljoin(str(response.url), href.strip())
        if urlsplit(url).scheme not in ("http", "https") or _site(url) != site:
            continue
        key = clean_url(url)
        if key in seen or not _looks_like_article(key):
            continue
        seen.add(key)
        candidates.append(_Candidate(url=key))
    return candidates


def _site(url: str) -> str:
    return urlsplit(url).netloc.lower().removeprefix("www.")


def _looks_like_article(url: str) -> bool:
    path = urlsplit(url).path
    segments = [segment for segment in path.split("/") if segment]
    if not segments or _SKIP_PATH.search(path) or _SKIP_EXT.search(path):
        return False
    last = segments[-1]
    return last.count("-") >= 2 or (re.search(r"/20\d\d/", path) is not None and len(last) > 5)


def _read_article(
    polite: _Polite,
    candidate: _Candidate,
    source: Source,
    key: str,
    since: datetime,
    stats: SourceStats,
) -> SourceArticle | None:
    response = polite.get(candidate.url)
    extracted = trafilatura.extract(
        response.text,
        url=str(response.url),
        output_format="json",
        with_metadata=True,
        include_comments=False,
        include_tables=False,
    )
    data: dict[str, Any] = json.loads(extracted) if extracted else {}
    text = str(data.get("text") or "").strip()
    if len(text) < MIN_TEXT_CHARS:
        raise ValueError("no article text found on the page")
    published = candidate.published or _parse_date(data.get("date"))
    if published is None:
        stats.no_date += 1
        return None
    if published < since:
        stats.too_old += 1
        return None
    title = str(data.get("title") or candidate.title or "").strip()
    if not title:
        raise ValueError("no title found on the page")
    summary = candidate.summary or _plain(str(data.get("excerpt") or "")) or text
    return SourceArticle(
        article_id=key,
        source=source.name,
        url=clean_url(candidate.url),
        title=title,
        author=candidate.author or (str(data.get("author") or "").strip() or None),
        published_at=published,
        content=text,
        summary=_clip(summary, SUMMARY_CHARS),
        topics=list(source.topics),
        collected_at=datetime.now(UTC),
    )


def _parse_date(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _plain(text: str) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", text)).split())


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rsplit(" ", 1)[0] + "…"


def _short(error: BaseException) -> str:
    return f"{type(error).__name__}: {' '.join(str(error).split())[:_ERROR_CHARS]}"


def create_provider(settings: Settings | None = None) -> FreeCollector:
    return FreeCollector()
