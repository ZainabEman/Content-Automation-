"""`ca topics search --theme "<theme>" [--count N] [--week <w>]` (v6): topic ideas for one theme,
found by Codex's own browsing on authentic German sources only (config/topic_sources.json) and
checked by `ca` before they enter the pool. No paid call: `ca` writes a brief
(outputs/_system/drafts/topics/search_<stamp>.json: the theme, the allowlisted domains per tier,
the rules and the candidate schema), Codex fills its `candidates`, and `--from <brief>` checks
each one: the schema, a verified service if any and no unverified service claim, the topic
memory and the pool (content/topic_pool.py), then its sources (content/topic_sources.py: on the
allowlist, HTTP 200, a title, dated within maxAgeDays unless evergreen, the quote in the page,
every number and named study in the source text). One line per candidate: title, source domain,
date and PASS, or why it was refused or blocked; nothing is dropped silently. Without --dry-run
the passing ones are appended to state/topic_pool.json `topics` with the theme, the week and
their sources, so later copy and research steps can trace each topic back to its URLs.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, ValidationError

from content_automation.content.topic_pool import (
    Known,
    PoolTopic,
    TopicMemory,
    TopicSource,
    add_topics,
    load_pool,
    theme_of,
)
from content_automation.content.topic_refill import (
    MAX_ANGLE,
    SOURCE_EXAMPLE,
    SOURCE_RULE,
    avoid_list,
    invalid_fields,
    pool_memory,
    read_candidates,
    save_brief,
    service_problem,
    stamped_path,
)
from content_automation.content.topic_sources import (
    SourceIn,
    check_sources,
    host_of,
    load_allowlist,
)
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel
from content_automation.references.services import load_services
from content_automation.youtube.sources import Page

NO_DATE = "no date"
SEARCH_RULES = [
    "Search with your own browsing, ONLY on the `domains` (e.g. `site:heise.de <theme>`); "
    "tier 1 (official) and tier 2 (established German media) first, tier 3 only if listed.",
    "title: German, 8-140 characters, one concrete angle on the theme for German SME owners.",
    f"readerAngle: German, at most {MAX_ANGLE} characters: what it means for a German "
    "business reader.",
    "service: a `services` id only when the topic really fits it, else null (no sales angle).",
    SOURCE_RULE,
    "No number, percentage, price, year or named study in title or readerAngle unless it is in "
    "the source text; never invent a source, URL, quote or date.",
    "Nothing from `avoid` and no close rewording of it; every candidate a different angle.",
]


class SearchCandidate(CamelModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=8, max_length=140)
    reader_angle: str = Field(min_length=10, max_length=MAX_ANGLE)
    service: str | None = None
    evergreen: bool = False
    sources: list[SourceIn] = Field(default_factory=list, max_length=3)


@dataclass
class Search:
    accepted: list[PoolTopic] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)  # one per candidate, in order
    blocked: int = 0
    refused: int = 0


def write_search_brief(settings: Settings, theme: str, count: int, week: str | None,
                       memory: TopicMemory, now: datetime | None = None
                       ) -> tuple[Path, list[str]]:
    """The search brief Codex fills; returns its path and the lines for Codex."""
    pool = load_pool()
    services = load_services(settings.services_file)
    allowlist = load_allowlist()
    avoid = avoid_list(memory, pool)
    path = stamped_path("search", now)
    brief: dict[str, Any] = {
        "_note": f"Codex: search the theme with your own browsing on the `domains` only, fill "
                 f"`candidates` with {count} topics by `rules`, then run uv run ca topics search "
                 f"--from {path.as_posix()} --dry-run; show the result and wait for the user's "
                 "ok before running it again without --dry-run.",
        "theme": theme,
        "week": week,
        "count": count,
        "maxAgeDays": allowlist.max_age_days,
        "rules": SEARCH_RULES,
        "domains": allowlist.by_tier(),
        "services": [{"id": service.id, "name": service.name_de or service.name,
                      "whatItDoes": service.what_it_does} for service in services.verified()],
        "avoid": avoid,
        "schema": {"title": "<German topic>", "readerAngle": "<what it means for the reader>",
                   "service": None, "evergreen": False, "sources": [SOURCE_EXAMPLE]},
        "candidates": [],
    }
    save_brief(path, brief)
    tiers = ", ".join(f"{tier} {len(domains)}" for tier, domains in brief["domains"].items())
    return path, [
        f'Search brief: {path.as_posix()} (theme "{theme}", {count} candidates'
        + (f", week {week}" if week else "") + f"; domains {tiers}; {len(avoid)} topics to avoid).",
        f"Next: Codex searches the allowlisted domains and fills `candidates`, then uv run ca "
        f"topics search --from {path.as_posix()} --dry-run",
    ]


def _where(candidate: SearchCandidate, pages: dict[str, Page]) -> str:
    """The first source's domain and date, for the candidate's line."""
    if not candidate.sources:
        return f"no source | {NO_DATE}"
    first = candidate.sources[0]
    page = pages.get(first.url)
    shown = (page.date[:10] if page is not None and page.date else "") or first.date or NO_DATE
    return f"{host_of(first.url)} | {shown}"


def check_search(settings: Settings, path: Path, memory: TopicMemory,
                 today: date | None = None) -> tuple[Search, str]:
    """Every candidate checked in order; the brief's theme."""
    data, raw = read_candidates(path)
    theme = str(data.get("theme") or "").strip()
    week = str(data["week"]) if data.get("week") else None
    count = int(data.get("count") or len(raw))
    pool = load_pool()
    services = load_services(settings.services_file)
    allowlist = load_allowlist()
    known = pool_memory(memory, pool)
    today = today or datetime.now().date()
    pages: dict[str, Page] = {}
    result = Search()
    for number, item in enumerate(raw, 1):
        try:
            candidate = SearchCandidate.model_validate(item)
        except ValidationError as error:
            result.refused += 1
            result.lines.append(f"#{number} REFUSED: check {invalid_fields(error)}")
            continue
        title = candidate.title.strip()
        texts = [("title", title), ("readerAngle", candidate.reader_angle)]
        problem = service_problem(candidate.service, texts, services)
        if problem is None and len(result.accepted) >= count:
            problem = f"over the count ({count})"
        reason = known.check(title) if problem is None else None
        if reason is not None:
            result.blocked += 1
            result.lines.append(f'#{number} BLOCKED "{title}" | {_where(candidate, pages)}: '
                                f"{reason}")
            continue
        checked: list[TopicSource] = []
        if problem is None:
            checked, problem = check_sources(candidate.sources, [title, candidate.reader_angle],
                                             allowlist, evergreen=candidate.evergreen,
                                             today=today, pages=pages)
        if problem is not None:
            result.refused += 1
            result.lines.append(f'#{number} REFUSED "{title}" | {_where(candidate, pages)}: '
                                f"{problem}")
            continue
        result.accepted.append(PoolTopic(
            title, "search", candidate.reader_angle.strip(), theme_of(f"{theme} {title}", pool),
            candidate.service, None, today.isoformat(), tuple(checked), theme or None, week,
            candidate.evergreen))
        known.known.append(Known(title, "proposed", f"candidate #{number}"))
        result.lines.append(f'#{number} PASS "{title}" | {host_of(checked[0].url)} | '
                            f"{checked[0].date} ({checked[0].publisher}, tier {checked[0].tier})")
    return result, theme


def search_lines(settings: Settings, path: Path, memory: TopicMemory, *,
                 dry_run: bool) -> list[str]:
    """Check the filled search brief and (unless dry_run) save what passes to the pool."""
    result, theme = check_search(settings, path, memory)
    lines = list(result.lines)
    summary = (f'theme "{theme}": {len(result.accepted)} pass, {result.blocked} blocked, '
               f"{result.refused} refused")
    if dry_run:
        lines.append(f"Dry run, {summary}; nothing written to state/topic_pool.json. Save "
                     f"after the user's ok: uv run ca topics search --from {path.as_posix()}")
    elif result.accepted:
        size = add_topics(result.accepted)
        lines.append(f"Saved, {summary}; the pool has {size} topics.")
    else:
        lines.append(f"Nothing saved, {summary}.")
    return lines


__all__ = ["SEARCH_RULES", "Search", "SearchCandidate", "check_search", "search_lines",
           "write_search_brief"]
