"""Ideas in the backlog (Phase 5 P5-D1, D9, D10, D11): items of kind `idea` plus their details.

An idea uses only the idea gate (approve, reject, revise via `ca item`). Its details: the pillar,
the score (0-100) and its parts, flags (e.g. off_strategy), the user's original words for a manual
topic and the assumptions Codex made, and `duplicate_of` once merged into an older idea.
"""

import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.items import Item, create_item, get_item


@dataclass(frozen=True)
class IdeaDetails:
    item_id: str
    pillar: str | None = None
    score: int | None = None
    score_parts: dict[str, Any] = field(default_factory=dict)
    flags: tuple[str, ...] = ()
    original_text: str | None = None
    assumptions: tuple[str, ...] = ()
    duplicate_of: str | None = None


def create_idea(
    conn: sqlite3.Connection, title: str, *, topic: str | None = None,
    original_text: str | None = None, assumptions: Sequence[str] = (),
    platforms: Sequence[str] = (), notes: str | None = None, actor: Actor = "system",
    command: str | None = None,
) -> Item:
    """A new idea item (proposed) with its details row."""
    with transaction(conn):
        item = create_item(conn, kind="idea", title=title, topic=topic or title,
                           platforms=platforms, notes=notes, actor=actor, command=command)
        conn.execute(
            "INSERT INTO ideas (item_id, original_text, assumptions, updated_at) "
            "VALUES (?, ?, ?, ?)",
            (item.id, original_text, json.dumps(list(assumptions), ensure_ascii=False), now()),
        )
        return item


def get_details(conn: sqlite3.Connection, ref: str) -> IdeaDetails:
    item = get_item(conn, ref)
    if not item.is_idea:
        raise RegistryError(f"{item.id} is a {item.kind}, not an idea.")
    row = conn.execute("SELECT * FROM ideas WHERE item_id = ?", (item.id,)).fetchone()
    if row is None:
        return IdeaDetails(item.id)
    return IdeaDetails(
        item_id=item.id, pillar=row["pillar"], score=row["score"],
        score_parts=dict(json.loads(row["score_parts"])),
        flags=tuple(json.loads(row["flags"])), original_text=row["original_text"],
        assumptions=tuple(json.loads(row["assumptions"])), duplicate_of=row["duplicate_of"],
    )


def update_details(
    conn: sqlite3.Connection, ref: str, *, actor: Actor = "system", command: str | None = None,
    **changes: Any,
) -> IdeaDetails:
    """Change pillar, score, score_parts, flags or duplicate_of (logged)."""
    allowed = {"pillar", "score", "score_parts", "flags", "duplicate_of"}
    unknown = set(changes) - allowed
    if unknown:
        raise RegistryError(f"Unknown idea field(s): {', '.join(sorted(unknown))}.")
    with transaction(conn):
        details = get_details(conn, ref)
        values: dict[str, Any] = {
            key: json.dumps(value, ensure_ascii=False) if key in ("score_parts", "flags")
            else value for key, value in changes.items()
        }
        conn.execute("INSERT OR IGNORE INTO ideas (item_id, updated_at) VALUES (?, ?)",
                     (details.item_id, now()))
        if values:
            sets = ", ".join(f"{key} = ?" for key in values)
            conn.execute(f"UPDATE ideas SET {sets}, updated_at = ? WHERE item_id = ?",
                         (*values.values(), now(), details.item_id))
        append_event(conn, "item_updated", actor=actor, command=command,
                     item_id=details.item_id, details={"idea": _plain(changes)})
        return get_details(conn, details.item_id)


def _plain(changes: Mapping[str, Any]) -> dict[str, Any]:
    return {key: list(value) if isinstance(value, tuple) else value
            for key, value in changes.items()}


def list_ideas(conn: sqlite3.Connection) -> list[tuple[Item, IdeaDetails]]:
    rows = conn.execute("SELECT id FROM items WHERE kind = 'idea' ORDER BY number")
    return [(get_item(conn, str(row["id"])), get_details(conn, str(row["id"]))) for row in rows]


GERMAN_SHARE = {"yes": 1.0, "partial": 0.5, "no": 0.0}
TRUST_SHARE = {"primary": 1.0, "secondary": 0.5, "unknown": 0.2}
DEFAULT_WEIGHTS = {"pillar": 40.0, "german": 20.0, "recency": 15.0, "trust": 15.0,
                   "evidence": 10.0}


def score_idea(
    conn: sqlite3.Connection, ref: str, *, pillar: str | None, relevance: int, german: str,
    reason: str, pillars: Sequence[str], weights: Mapping[str, float] | None = None,
    max_age_days: int = 90, command: str | None = None,
) -> IdeaDetails:
    """The score 0-100 (P5-D10): pillar relevance and German relevance from Codex (stored as
    by "assistant"), recency, source trust and evidence computed here. No pillar: off_strategy
    (shown, never rejected)."""
    from content_automation.registry.claims import list_claims  # claims imports sources
    from content_automation.registry.sources import item_sources

    if pillar is not None and pillar not in pillars:
        raise RegistryError(f'Unknown pillar "{pillar}" ({", ".join(pillars)}, or none).')
    if german not in GERMAN_SHARE:
        raise RegistryError("German relevance must be yes, partial or no.")
    if pillar is not None and not 1 <= relevance <= 5:
        raise RegistryError("Pillar relevance must be 1-5.")
    if not reason.strip():
        raise RegistryError("A score needs a one-line reason.")
    points = {**DEFAULT_WEIGHTS, **(weights or {})}
    item = get_item(conn, ref)
    sources = item_sources(conn, item.id)
    days = [source.published_at[:10] for source in sources if source.published_at]
    newest = max(days, default=None)
    age = None
    if newest:
        from datetime import UTC, date, datetime

        try:
            age = (datetime.now(UTC).date() - date.fromisoformat(newest)).days
        except ValueError:
            age = None
    recency = (0.0 if age is None else 1.0 if age <= 7 else 0.66 if age <= 30
               else 0.33 if age <= max_age_days else 0.0)
    trust = max((TRUST_SHARE[source.trust] for source in sources), default=0.0)
    verified = sum(claim.label == "fact" and claim.status == "verified"
                   for claim in list_claims(conn, item.id))
    parts: dict[str, Any] = {
        "pillar": {"points": round(points["pillar"] * (relevance / 5 if pillar else 0), 1),
                   "input": relevance if pillar else 0, "by": "assistant",
                   "reason": reason.strip()},
        "german": {"points": round(points["german"] * GERMAN_SHARE[german], 1),
                   "input": german, "by": "assistant"},
        "recency": {"points": round(points["recency"] * recency, 1), "input": newest,
                    "by": "computed"},
        "trust": {"points": round(points["trust"] * trust, 1), "by": "computed"},
        "evidence": {"points": round(points["evidence"] * min(verified, 2) / 2, 1),
                     "input": verified, "by": "computed"},
    }
    total = round(sum(float(part["points"]) for part in parts.values()))
    details = get_details(conn, item.id)
    flags = [flag for flag in details.flags if flag != "off_strategy"]
    flags += [] if pillar else ["off_strategy"]
    return update_details(conn, item.id, pillar=pillar, score=total, score_parts=parts,
                          flags=flags, command=command)


def merge_ideas(conn: sqlite3.Connection, duplicate_ref: str, into_ref: str, *,
                actor: Actor = "user", command: str | None = None) -> IdeaDetails:
    """Merge an idea into another (P5-D9): its sources move over, duplicate_of is set, and the
    duplicate is rejected with the reason "duplicate of BG-y"."""
    from content_automation.registry.approvals import reject
    from content_automation.registry.sources import item_sources, link_source

    with transaction(conn):
        duplicate, into = get_item(conn, duplicate_ref), get_item(conn, into_ref)
        if duplicate.id == into.id or not (duplicate.is_idea and into.is_idea):
            raise RegistryError("Merge two different ideas: ca ideas merge BG-x BG-y.")
        for source in item_sources(conn, duplicate.id):
            link_source(conn, into.id, source.id, role="merged", command=command)
        update_details(conn, duplicate.id, duplicate_of=into.id, command=command)
        if duplicate.idea_status in ("proposed", "approved"):
            reject(conn, duplicate.id, f"duplicate of {into.id}", gate="idea", actor=actor,
                   command=command)
        return get_details(conn, duplicate.id)


def review_queue(conn: sqlite3.Connection, limit: int = 10) -> list[tuple[Item, IdeaDetails]]:
    """Proposed ideas that are not duplicates, best score first (unscored last)."""
    waiting = [(item, details) for item, details in list_ideas(conn)
               if item.idea_status == "proposed" and not details.duplicate_of]
    waiting.sort(key=lambda pair: (pair[1].score is None, -(pair[1].score or 0), pair[0].number))
    return waiting[:limit]
