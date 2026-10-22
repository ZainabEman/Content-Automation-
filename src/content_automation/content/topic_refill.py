"""`ca topics refill` (v6 R2): new topic candidates for the pool when the weekly slots run dry.

The candidates are written by Codex, not by a paid API, in the copy-template way: `ca` writes a
brief (outputs/_system/drafts/topics/refill_<stamp>.json) with the 50/30/20 split of the count,
the society themes, the verified services, the newest newsletter ideas as leads, the allowlisted
German source domains (config/topic_sources.json) and the topics to avoid; Codex fills its
`candidates`; `--from <brief>` checks each one: its source, the theme or verified service it
names, a short reader angle, no number and no unverified service claim, then the topic memory
(generated, rejected, deleted and close rewordings), the pool itself and the candidates before
it, then its source URLs (content/topic_sources.py: allowlisted, HTTP 200, dated, the quote in
the page; a candidate without one is refused). What passes is appended to config/topic_pool.json
`topics` with its sources (--dry-run: shown, nothing written); every skipped candidate is named
and counted.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field, ValidationError

from content_automation.content.calendar import (
    LIST_SUFFIX,
    NEWSLETTER_DIR,
    _newest_list,
    _newsletter_ideas,
)
from content_automation.content.relevance import INSIGHT_ONLY, unverified_claims
from content_automation.content.topic_pool import (
    Known,
    PoolTopic,
    TopicMemory,
    TopicPool,
    add_topics,
    load_pool,
)
from content_automation.content.topic_sources import (
    SourceIn,
    check_sources,
    host_of,
    load_allowlist,
)
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.core.output_tree import DRAFTS_DIR
from content_automation.references.services import ServiceCatalog, load_services
from content_automation.youtube.sources import Page

REFILL_DIR = DRAFTS_DIR / "topics"
MAX_ANGLE = 220
LEADS = 15  # newsletter ideas offered as leads
AVOID = 80  # known topics listed in the brief (the check reads all of them)
_REF = re.compile(r"newsletter:(\d{4}-\d{2}-\d{2})#(\d+)")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?\s?(?:%|prozent|percent|€|euro|mio|mrd)", re.IGNORECASE)
SOURCE_RULE = (
    "sources: 1-3 of {url, publisher, date, title, quote}, each an article on a `domains` "
    "domain (never social media, forums, Reddit, YouTube, content farms, press-release "
    "aggregators or unknown blogs); the quote copied word for word from the page; published "
    "within `maxAgeDays` unless `evergreen` is true (only for a timeless theme). ca opens every "
    "URL once and refuses a candidate whose source fails.")
RULES = [
    "topic: German, 8-140 characters, one concrete angle for German SME owners (Mittelstand); "
    "no generic marketing or SEO topic.",
    "source: society (theme = a `themes` id), services (service = a `services` id; only what "
    "its whatItDoes says) or newsletters (ref = a `newsletterLeads` ref, plus a German source "
    "below; a theme or service when one fits). Follow `mix`.",
    f"readerAngle: German, at most {MAX_ANGLE} characters: what it means for a German business "
    "reader.",
    SOURCE_RULE,
    "No number, price, statistic, result or client; no service that is not in `services` "
    "(never SEO, web design, PPC or photo/video as ours).",
    "Nothing from `avoid` and no close rewording of it; every candidate a different angle.",
]
SOURCE_EXAMPLE = {"url": "https://www.<allowlisted domain>/<article>", "publisher": "<name>",
                  "date": "YYYY-MM-DD", "title": "<the page title>",
                  "quote": "<one sentence copied from the page>"}


class RefillError(ValueError):
    """A brief that cannot be read or has no candidates."""


class Candidate(CamelModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=8, max_length=140)
    source: Literal["society", "services", "newsletters"]
    reader_angle: str = Field(min_length=10, max_length=MAX_ANGLE)
    theme: str | None = None
    service: str | None = None
    ref: str | None = None
    evergreen: bool = False
    sources: list[SourceIn] = Field(default_factory=list, max_length=3)


@dataclass
class Refill:
    accepted: list[PoolTopic] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # one line per skipped candidate
    blocked: int = 0  # used, rejected, deleted, in the pool, or a close rewording
    refused: int = 0  # broke a rule or a source failed


def split_mix(count: int, mix: dict[str, float]) -> dict[str, int]:
    """The count split by the mix, largest remainders first (20 -> 10/6/4)."""
    exact = {source: count * share for source, share in mix.items()}
    split = {source: int(value) for source, value in exact.items()}
    for source in sorted(exact, key=lambda key: split[key] - exact[key])[
            :count - sum(split.values())]:
        split[source] += 1
    return split


def avoid_list(memory: TopicMemory, pool: TopicPool) -> list[str]:
    """The newest known and pooled topics, for the brief."""
    return list(dict.fromkeys([entry.topic for entry in memory.known]
                              + [topic.topic for topic in pool.topics]))[-AVOID:]


def pool_memory(memory: TopicMemory, pool: TopicPool) -> TopicMemory:
    """The topic memory plus the pool's own topics (a pooled topic is not added twice)."""
    return TopicMemory([*memory.known, *(Known(topic.topic, "in the pool", "topic_pool.json")
                                         for topic in pool.topics)], pool)


def stamped_path(kind: str, now: datetime | None = None) -> Path:
    return REFILL_DIR / f"{kind}_{(now or datetime.now()).strftime('%Y%m%d-%H%M%S')}.json"


def save_brief(path: Path, brief: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(brief, ensure_ascii=False, indent=2) + "\n")


def read_candidates(path: Path) -> tuple[dict[str, Any], list[Any]]:
    """The brief and its candidates (RefillError: unreadable or not filled yet)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RefillError(f"{path}: {error}") from None
    raw = data.get("candidates") if isinstance(data, dict) else None
    if not isinstance(raw, list) or not raw:
        raise RefillError(f"{path.name} has no candidates: Codex fills `candidates` first.")
    return data, raw


def invalid_fields(error: ValidationError) -> str:
    return ", ".join(sorted({".".join(str(part) for part in issue["loc"]) or "candidate"
                             for issue in error.errors()}))


def service_problem(service: str | None, texts: list[tuple[str, str]],
                    services: ServiceCatalog) -> str | None:
    """A service that is not verified, or copy that claims an unverified one."""
    if service not in (None, INSIGHT_ONLY, *(item.id for item in services.verified())):
        return f'service "{service}" is not a verified service (config/services.json)'
    claims = unverified_claims(texts, services)
    return claims[0] if claims else None


def write_brief(settings: Settings, count: int, memory: TopicMemory,
                now: datetime | None = None) -> tuple[Path, list[str]]:
    """The brief Codex fills; returns its path and the lines for Codex."""
    pool = load_pool()
    services = load_services(settings.services_file)
    allowlist = load_allowlist()
    newest = _newest_list(settings.research_dir)
    leads = [{"ref": idea.source, "title": idea.topic}
             for idea in (_newsletter_ideas(newest, []) if newest is not None else [])][:LEADS]
    mix = dict(pool.source_mix)
    if not leads:  # no newsletter list yet: its share goes to the society themes
        mix["society"] = mix.get("society", 0.0) + mix.pop("newsletters", 0.0)
    split = split_mix(count, mix)
    avoid = avoid_list(memory, pool)
    path = stamped_path("refill", now)
    brief: dict[str, Any] = {
        "_note": f"Codex: fill `candidates` with {count} topics by `rules`, then run "
                 f"uv run ca topics refill --from {path.as_posix()} (--dry-run: check only).",
        "count": count,
        "mix": split,
        "rules": RULES,
        "maxAgeDays": allowlist.max_age_days,
        "domains": allowlist.by_tier(),
        "themes": [{"id": theme.id, "label": theme.label} for theme in pool.themes],
        "services": [{"id": service.id, "name": service.name_de or service.name,
                      "whatItDoes": service.what_it_does} for service in services.verified()],
        "newsletterLeads": leads,
        "avoid": avoid,
        "example": {"topic": "KI-Telefonbetrug: Wenn der Chef plötzlich anruft",
                    "source": "society", "theme": "ai_scams", "service": None,
                    "readerAngle": "Ein Rückruf über die bekannte Nummer stoppt den Betrug, "
                                   "bevor Geld das Konto verlässt.", "ref": None,
                    "evergreen": False, "sources": [SOURCE_EXAMPLE]},
        "candidates": [],
    }
    save_brief(path, brief)
    shares = ", ".join(f"{source} {number}" for source, number in split.items())
    lines = [f"Brief: {path.as_posix()} ({count} candidates: {shares}; "
             f"{len(leads)} newsletter leads, {len(avoid)} topics to avoid)."]
    if not leads:
        lines.append("No newsletter content list: the newsletter share goes to the society "
                     "themes (run show content for leads).")
    lines.append(f"Next: Codex fills `candidates`, then uv run ca topics refill --from "
                 f"{path.as_posix()} [--dry-run]")
    return path, lines


def _problem(candidate: Candidate, themes: set[str], services: ServiceCatalog,
             research_dir: Path) -> str | None:
    if candidate.theme is not None and candidate.theme not in themes:
        return f'theme "{candidate.theme}" is not a pool theme'
    if candidate.source == "society" and candidate.theme is None:
        return "a society topic names its theme"
    if candidate.source == "services" and candidate.service in (None, INSIGHT_ONLY):
        return "a services topic names a verified service"
    if candidate.source == "newsletters":
        found = _REF.fullmatch(candidate.ref or "")
        if found is None:
            return 'a newsletter topic needs ref "newsletter:<YYYY-MM-DD>#<n>"'
        if not (research_dir / NEWSLETTER_DIR / f"{found[1]}{LIST_SUFFIX}").is_file():
            return f"newsletter list {found[1]}{LIST_SUFFIX} not found"
    texts = [("topic", candidate.topic), ("readerAngle", candidate.reader_angle)]
    if any(_NUMBER.search(text) for _, text in texts):
        return "a number, price or statistic needs a source: leave it out of a pool topic"
    return service_problem(candidate.service, texts, services)


def check_brief(settings: Settings, path: Path, memory: TopicMemory,
                today: date | None = None) -> tuple[Refill, dict[str, int]]:
    """The candidates that pass (in order) and the skipped ones; the brief's mix."""
    data, raw = read_candidates(path)
    count = int(data.get("count") or len(raw))
    pool = load_pool()
    services = load_services(settings.services_file)
    allowlist = load_allowlist()
    themes = {theme.id for theme in pool.themes}
    known = pool_memory(memory, pool)
    today = today or datetime.now().date()
    pages: dict[str, Page] = {}
    result = Refill()
    for number, item in enumerate(raw, 1):
        try:
            candidate = Candidate.model_validate(item)
        except ValidationError as error:
            result.refused += 1
            result.skipped.append(f"#{number} refused: check {invalid_fields(error)}")
            continue
        topic = candidate.topic.strip()
        problem = _problem(candidate, themes, services, settings.research_dir)
        if problem is None and len(result.accepted) >= count:
            problem = f"over the count ({count})"
        if problem is not None:
            result.refused += 1
            result.skipped.append(f'#{number} "{topic}" refused: {problem}')
            continue
        reason = known.check(topic)
        if reason is not None:
            result.blocked += 1
            result.skipped.append(f'#{number} "{topic}" blocked: {reason}')
            continue
        checked, problem = check_sources(candidate.sources, [topic, candidate.reader_angle],
                                         allowlist, evergreen=candidate.evergreen,
                                         today=today, pages=pages)
        if problem is not None:
            result.refused += 1
            result.skipped.append(f'#{number} "{topic}" refused: {problem}')
            continue
        result.accepted.append(PoolTopic(
            topic, candidate.source, candidate.reader_angle.strip(), candidate.theme,
            candidate.service, candidate.ref, today.isoformat(), tuple(checked),
            evergreen=candidate.evergreen))
        known.known.append(Known(topic, "proposed", f"candidate #{number}"))
    mix = data.get("mix")
    return result, {str(key): int(value) for key, value in mix.items()} \
        if isinstance(mix, dict) else {}


def source_label(topic: PoolTopic) -> str:
    first = topic.sources[0] if topic.sources else None
    return f"{host_of(first.url)}, {first.date}" if first is not None else "no source"


def refill_lines(settings: Settings, path: Path, memory: TopicMemory, *,
                 dry_run: bool) -> list[str]:
    """Check the filled brief and (unless dry_run) save what passes to the pool."""
    result, mix = check_brief(settings, path, memory)
    lines = [f'+ [{topic.source}/{topic.service or topic.theme or "-"}] "{topic.topic}" '
             f"({source_label(topic)}): {topic.reader_angle}" for topic in result.accepted]
    lines += [f"- {line}" for line in result.skipped]
    got = {source: sum(1 for topic in result.accepted if topic.source == source)
           for source in mix}
    if mix:
        lines.append("Mix: " + ", ".join(f"{source} {got[source]}/{wanted}"
                                         for source, wanted in mix.items()))
    summary = (f"{len(result.accepted)} pass, {result.blocked} blocked, {result.refused} "
               "refused")
    if dry_run:
        lines.append(f"Dry run: {summary}; nothing written to config/topic_pool.json.")
    elif result.accepted:
        size = add_topics(result.accepted)
        lines.append(f"Saved: {summary}; the pool has {size} topics. Next: \"fill empty slots "
                     "for <week>\" (uv run ca calendar fill --week <week>).")
    else:
        lines.append(f"Nothing saved: {summary}.")
    return lines


__all__ = ["REFILL_DIR", "SOURCE_RULE", "Candidate", "Refill", "RefillError", "avoid_list",
           "check_brief", "invalid_fields", "pool_memory", "read_candidates", "refill_lines",
           "save_brief", "service_problem", "source_label", "split_mix", "stamped_path",
           "write_brief"]
