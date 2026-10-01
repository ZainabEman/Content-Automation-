"""Rank saved articles by how well they match a topic (keywords + recency)."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from content_automation.research.models import SourceArticle

MIN_STRONG = 3  # fewer strong matches than this: fill up with the latest articles
_SHORT_KEYWORDS = frozenset({"ai", "seo", "crm", "ppc", "ux", "b2b", "b2c", "ads", "sem"})
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "about", "from", "into", "your", "our", "how", "what", "why",
    "are", "you", "this", "that", "new", "more", "use", "using", "make", "post", "reel", "ad",
    "small", "best", "tips", "guide",
})
_WORD = re.compile(r"[a-z0-9][a-z0-9+#-]*")


@dataclass(frozen=True)
class RankedArticle:
    article: SourceArticle
    score: float
    strong: bool


@dataclass(frozen=True)
class TopicDigest:
    topic: str
    keywords: list[str]
    articles: list[RankedArticle]
    strong_matches: int

    @property
    def weak(self) -> bool:
        return self.strong_matches < MIN_STRONG


def topic_keywords(topic: str) -> list[str]:
    words = _WORD.findall(topic.lower())
    keywords = [w for w in words if (len(w) >= 3 or w in _SHORT_KEYWORDS) and w not in _STOPWORDS]
    return list(dict.fromkeys(keywords))


def _pattern(keyword: str) -> re.Pattern[str]:
    """Match word forms: "automation" also finds "automate", "chatbots" finds "chatbot"."""
    stem = keyword if len(keyword) <= 5 else keyword[: max(5, len(keyword) - 3)]
    return re.compile(rf"\b{re.escape(stem)}\w*", re.IGNORECASE)


def rank_by_topic(
    articles: list[SourceArticle],
    topic: str,
    *,
    days: int,
    limit: int,
    now: datetime | None = None,
) -> TopicDigest:
    """Score = keywords in the title (x3) + keywords and hits in the text, times a recency
    bonus. Strong match: most keywords appear, at least one in the title or several times."""
    keywords = topic_keywords(topic) or [topic.lower().strip()]
    patterns = [_pattern(keyword) for keyword in keywords]
    current = now or datetime.now(UTC)
    ranked: list[RankedArticle] = []
    for article in articles:
        title_hits = sum(1 for pattern in patterns if pattern.search(article.title))
        text_counts = [len(pattern.findall(article.content)) for pattern in patterns]
        text_hits = sum(1 for count in text_counts if count)
        covered = sum(
            1 for pattern, count in zip(patterns, text_counts, strict=True)
            if count or pattern.search(article.title)
        )
        score = 3 * title_hits + text_hits + 0.2 * min(sum(text_counts), 10)
        if topic.lower().strip() in f"{article.title} {article.content}".lower():
            score += 2
        age_days = max((current - article.published_at).total_seconds() / 86400, 0.0)
        score *= 1 + 0.5 * max(0.0, 1 - age_days / days)
        strong = covered / len(patterns) >= 0.6 and (title_hits > 0 or sum(text_counts) >= 3)
        ranked.append(RankedArticle(article, round(score, 2), strong))

    strong_list = sorted((r for r in ranked if r.strong), key=lambda r: r.score, reverse=True)
    chosen = strong_list[:limit]
    if len(strong_list) < MIN_STRONG:  # add the latest articles so there is something to use
        chosen_ids = {r.article.article_id for r in chosen}
        latest = sorted(ranked, key=lambda r: r.article.published_at, reverse=True)
        chosen += [r for r in latest if r.article.article_id not in chosen_ids][
            : max(limit - len(chosen), 0)
        ]
    return TopicDigest(topic, keywords, chosen, len(strong_list))
