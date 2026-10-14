"""`ca research fetch`: follow a (newsletter) link to the original article (Phase 5 P5-D6, P5-D7).

Free HTTP, runtime only (tests pass a mock transport). Tracking wrappers (?url=, ?u=, ?redirect=)
are unwrapped and tracking parameters dropped; redirects are followed up to a cap; robots.txt is
checked for the first and the final host; responses over the size limit or not HTML are refused;
the text and metadata come from trafilatura. Failures come back per URL, never as an exception.
The newsletter senders (config/newsletters.json "senders") give a source its purpose.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
import trafilatura

from content_automation.research.collectors import USER_AGENT
from content_automation.research.store import clean_url

TRANSPORT: httpx.BaseTransport | None = None  # tests set a mock transport here
WRAPPER_KEYS = ("url", "u", "redirect", "redirect_url", "target", "dest", "destination")


@dataclass(frozen=True)
class Sender:
    domain: str
    name: str
    purpose: str
    pillar_affinity: tuple[str, ...] = ()
    follow_links: bool = True
    verified_domain: bool = False


@dataclass(frozen=True)
class FetchLimits:
    timeout_seconds: float = 15.0
    max_bytes: int = 3_000_000
    max_redirects: int = 5


@dataclass
class NewsletterConfig:
    senders: list[Sender] = field(default_factory=list)
    limits: FetchLimits = field(default_factory=FetchLimits)

    def sender_for(self, url_or_domain: str) -> Sender | None:
        host = (urlsplit(url_or_domain).hostname or url_or_domain).lower()
        return next((s for s in self.senders
                     if host == s.domain or host.endswith("." + s.domain)), None)


def load_newsletters(path: Path) -> NewsletterConfig:
    """config/newsletters.json: senders and fetch limits (a missing file: none, defaults)."""
    if not path.is_file():
        return NewsletterConfig()
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    senders = [
        Sender(str(s["domain"]).lower(), str(s.get("name", s["domain"])),
               str(s.get("purpose", "")), tuple(s.get("pillarAffinity", [])),
               bool(s.get("followLinks", True)), bool(s.get("verifiedDomain", False)))
        for s in data.get("senders", []) if isinstance(s, dict) and s.get("domain")
    ]
    fetch = data.get("fetch", {}) if isinstance(data.get("fetch"), dict) else {}
    limits = FetchLimits(float(fetch.get("timeoutSeconds", 15)),
                         int(fetch.get("maxBytes", 3_000_000)), int(fetch.get("maxRedirects", 5)))
    return NewsletterConfig(senders, limits)


@dataclass(frozen=True)
class Fetched:
    url: str  # as given (e.g. the newsletter's tracking link)
    original_url: str | None = None  # the article it led to
    title: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    language: str | None = None
    text: str | None = None
    error: str | None = None


def unwrap(url: str) -> str:
    """A tracking wrapper's target (?url=… and the like), then without tracking parameters."""
    for _ in range(3):
        query = parse_qs(urlsplit(url).query)
        target = next((unquote(values[0]) for key in WRAPPER_KEYS
                       if (values := query.get(key)) and values[0].startswith("http")), None)
        if target is None:
            break
        url = target
    return clean_url(url)


def _robots_allows(client: httpx.Client, url: str) -> bool | str:
    parts = urlsplit(url)
    try:
        response = client.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
    except httpx.HTTPError as error:
        return f"robots.txt not reachable ({type(error).__name__})"
    if response.status_code in (404, 410):
        return True
    if response.status_code >= 400:
        return f"robots.txt answered HTTP {response.status_code}"
    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


def fetch_article(url: str, limits: FetchLimits) -> Fetched:
    """Follow `url` to the original article and extract it; an error is returned, not raised."""
    target = unwrap(url)
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    try:
        with httpx.Client(timeout=limits.timeout_seconds, follow_redirects=True,
                          max_redirects=limits.max_redirects, headers=headers,
                          transport=TRANSPORT) as client:
            allowed = _robots_allows(client, target)
            if allowed is not True:
                reason = allowed if isinstance(allowed, str) else "robots.txt disallows it"
                return Fetched(url, error=f"{target}: {reason}")
            with client.stream("GET", target) as response:
                final = clean_url(str(response.url))
                if response.status_code >= 400:
                    return Fetched(url, final, error=f"HTTP {response.status_code}")
                kind = response.headers.get("content-type", "")
                if "html" not in kind:
                    return Fetched(url, final, error=f"not an HTML page ({kind or 'no type'})")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > limits.max_bytes:
                        return Fetched(url, final, error=f"larger than {limits.max_bytes} bytes")
            if urlsplit(final).netloc != urlsplit(target).netloc:
                allowed = _robots_allows(client, final)
                if allowed is not True:
                    return Fetched(url, final, error=f"{final}: robots.txt disallows it")
    except httpx.HTTPError as error:
        return Fetched(url, error=f"{type(error).__name__}: {error}")
    html = body.decode(response.encoding or "utf-8", errors="replace")
    raw = trafilatura.extract(html, output_format="json", with_metadata=True, url=final)
    if not raw:
        return Fetched(url, final, error="no article text found on the page")
    data = json.loads(raw)
    host = urlsplit(final).hostname or ""
    return Fetched(
        url=url, original_url=final, title=data.get("title"),
        publisher=data.get("sitename") or host.removeprefix("www."),
        published_at=data.get("date"), language=data.get("language"),
        text=data.get("text") or data.get("raw_text"),
    )
