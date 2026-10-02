"""Article files and run reports under RESEARCH_DIR."""

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import ValidationError

from content_automation.core.files import atomic_write_text
from content_automation.research.models import RunReport, SourceArticle

ARTICLES_DIR = "articles"
RUNS_DIR = "runs"
_TRACKING_PREFIXES = ("utm_", "hsa_", "_hs")
_TRACKING_NAMES = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid", "ref"})
_ARTICLE_ID = re.compile(r"[0-9a-f]{16}")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def clean_url(url: str) -> str:
    """Normalize a link so the same article always gets the same ID: lower-case host,
    no fragment, no tracking parameters, no trailing slash."""
    parts = urlsplit(url.strip())
    query = sorted(
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES) and key.lower() not in _TRACKING_NAMES
    )
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def article_id(url: str) -> str:
    return hashlib.sha256(clean_url(url).encode("utf-8")).hexdigest()[:16]


def known_article_ids(research_dir: Path) -> set[str]:
    return {path.stem for path in research_dir.glob(f"{ARTICLES_DIR}/*/*.json")}


def find_article(research_dir: Path, wanted_id: str) -> SourceArticle | None:
    """The saved article with this ID, or None."""
    if not _ARTICLE_ID.fullmatch(wanted_id):
        return None
    for path in research_dir.glob(f"{ARTICLES_DIR}/*/{wanted_id}.json"):
        try:
            return SourceArticle.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            continue
    return None


def number_in_article(text: str, article: SourceArticle) -> bool:
    """True when every number in ``text`` (e.g. "73%") is written in the article."""
    wanted = _numbers(text)
    found = _numbers(f"{article.title}\n{article.summary}\n{article.content}")
    return bool(wanted) and wanted <= found


def _numbers(text: str) -> set[str]:
    return {match.replace(",", "") for match in _NUMBER.findall(text)}


def save_article(research_dir: Path, article: SourceArticle) -> Path:
    month = article.published_at.astimezone(UTC).strftime("%Y-%m")
    path = research_dir / ARTICLES_DIR / month / f"{article.article_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, article.model_dump_json(by_alias=True, indent=2) + "\n")
    return path


def load_articles(research_dir: Path, since: datetime) -> list[SourceArticle]:
    """Saved articles published since `since`, newest first."""
    articles: list[SourceArticle] = []
    for path in research_dir.glob(f"{ARTICLES_DIR}/*/*.json"):
        try:
            article = SourceArticle.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError):
            continue
        if article.published_at >= since:
            articles.append(article)
    return sorted(articles, key=lambda a: a.published_at, reverse=True)


def save_run_report(research_dir: Path, report: RunReport) -> Path:
    path = research_dir / RUNS_DIR / f"{report.run_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, report.model_dump_json(by_alias=True, indent=2) + "\n")
    return path
