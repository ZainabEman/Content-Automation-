"""Labelled claims of an idea (Phase 5 P5-D5): CL-#### records whose status `ca` decides.

Codex proposes the text and the label (fact, opinion, speculation) from the source text; the
status follows mechanically and can never be set by hand:
- a fact needs at least one source with a URL and a date; it is verified with sources from 2
  different publishers or 1 primary source, otherwise unverified;
- an opinion needs a source with a publisher (who said it);
- speculation is always unverified;
- disputed needs the sources of both sides (counter sources);
- outdated when its newest source is older than research.maxAgeDays (config/strategy.json).
"""

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast

from content_automation.registry.audit import Actor, append_event
from content_automation.registry.db import RegistryError, now, transaction
from content_automation.registry.ids import allocate_counter, resolve
from content_automation.registry.sources import Source, get_source

Label = Literal["fact", "opinion", "speculation"]
ClaimStatus = Literal["verified", "unverified", "disputed", "outdated"]
LABELS: tuple[Label, ...] = ("fact", "opinion", "speculation")


@dataclass(frozen=True)
class Claim:
    id: str
    item_id: str
    text: str
    label: Label
    status: ClaimStatus
    source_refs: tuple[str, ...]
    counter_refs: tuple[str, ...]
    reason: str
    checked_at: str


def _day(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def decide(label: Label, sources: Sequence[Source], counter: Sequence[Source], *,
           max_age_days: int, today: date | None = None) -> tuple[ClaimStatus, str]:
    """The status and why; RegistryError when the claim may not be stored at all."""
    if label not in LABELS:
        raise RegistryError(f'Unknown label "{label}" ({", ".join(LABELS)}).')
    if not sources:
        raise RegistryError("A claim needs at least one source (SRC-…).")
    if label == "opinion" and not any(source.publisher for source in sources):
        raise RegistryError("An opinion needs an attributed source (one with a publisher).")
    dated = [source for source in sources if source.url and _day(source.published_at)]
    if label == "fact" and not dated:
        raise RegistryError("A fact needs at least one source with a URL and a published date.")
    days = [day for source in sources if (day := _day(source.published_at)) is not None]
    newest = max(days, default=None)
    limit = (today or datetime.now(UTC).date()) - timedelta(days=max_age_days)
    if newest is not None and newest < limit:
        return "outdated", f"newest source {newest} is older than {max_age_days} days"
    if counter:
        return "disputed", f"{len(sources)} source(s) for, {len(counter)} against"
    if label != "fact":
        return "unverified", f"{label}: never verified"
    publishers = {(source.publisher or "").lower() for source in dated if source.publisher}
    if any(source.trust == "primary" for source in dated):
        return "verified", "a primary source"
    if len(publishers) >= 2:
        return "verified", f"{len(publishers)} independent publishers"
    return "unverified", "one publisher only (needs 2 independent publishers or 1 primary)"


def _claim(row: sqlite3.Row) -> Claim:
    return Claim(
        id=str(row["id"]), item_id=str(row["item_id"]), text=str(row["text"]),
        label=cast(Label, str(row["label"])), status=cast(ClaimStatus, str(row["status"])),
        source_refs=tuple(json.loads(row["source_refs"])),
        counter_refs=tuple(json.loads(row["counter_refs"])), reason=str(row["reason"] or ""),
        checked_at=str(row["checked_at"]),
    )


def add_claim(
    conn: sqlite3.Connection, ref: str, text: str, label: Label, source_ids: Sequence[str], *,
    counter_ids: Sequence[str] = (), max_age_days: int = 90, actor: Actor = "system",
    command: str | None = None,
) -> Claim:
    """Store a claim; its status is decided here (never given)."""
    if not text.strip():
        raise RegistryError("A claim needs its text.")
    with transaction(conn):
        item_id = resolve(conn, ref)
        sources = [get_source(conn, source_id) for source_id in source_ids]
        counter = [get_source(conn, source_id) for source_id in counter_ids]
        status, reason = decide(label, sources, counter, max_age_days=max_age_days)
        number = allocate_counter(conn, "claim")
        claim_id = f"CL-{number:04d}"
        stamp = now()
        conn.execute(
            "INSERT INTO claims (id, number, item_id, text, label, status, source_refs, "
            "counter_refs, reason, checked_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?)",
            (claim_id, number, item_id, text.strip(), label, status,
             json.dumps([s.id for s in sources]), json.dumps([s.id for s in counter]), reason,
             stamp, stamp),
        )
        append_event(conn, "item_updated", actor=actor, command=command, item_id=item_id,
                     details={"claim": claim_id, "label": label, "status": status,
                              "reason": reason})
        return get_claim(conn, claim_id)


def get_claim(conn: sqlite3.Connection, claim_id: str) -> Claim:
    row = conn.execute("SELECT * FROM claims WHERE id = ?", (claim_id.upper(),)).fetchone()
    if row is None:
        raise RegistryError(f"Claim {claim_id} does not exist.")
    return _claim(row)


def list_claims(conn: sqlite3.Connection, ref: str) -> list[Claim]:
    item_id = resolve(conn, ref)
    rows = conn.execute("SELECT * FROM claims WHERE item_id = ? ORDER BY number", (item_id,))
    return [_claim(row) for row in rows]


def check_claims(conn: sqlite3.Connection, ref: str, *, max_age_days: int = 90,
                 today: date | None = None, command: str | None = None) -> list[Claim]:
    """Decide every claim of the item again (sources and dates may have changed)."""
    with transaction(conn):
        claims = list_claims(conn, ref)
        for claim in claims:
            sources = [get_source(conn, source_id) for source_id in claim.source_refs]
            counter = [get_source(conn, source_id) for source_id in claim.counter_refs]
            status, reason = decide(claim.label, sources, counter, max_age_days=max_age_days,
                                    today=today)
            if (status, reason) != (claim.status, claim.reason):
                conn.execute("UPDATE claims SET status = ?, reason = ?, checked_at = ? "
                             "WHERE id = ?", (status, reason, now(), claim.id))
                append_event(conn, "item_updated", command=command, item_id=claim.item_id,
                             details={"claim": claim.id, "status": status, "was": claim.status,
                                      "reason": reason})
        return list_claims(conn, ref)
