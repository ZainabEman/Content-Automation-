"""`ca ideas` and `ca claims` (Phase 5 §5): the idea backlog and the labelled claims.

Approve, reject and revise of ideas are the `ca item` commands. Scores from Codex are stored as
by "assistant"; claim statuses are decided by `ca`, never given.
"""

import json
import sys
from dataclasses import asdict
from typing import Annotated, NoReturn

import typer

from content_automation.cli.scope import registry_scope
from content_automation.content.backlog import Candidate, RunCounts, SourceInput, ingest
from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.registry.claims import LABELS, add_claim, check_claims, list_claims
from content_automation.registry.db import RegistryError
from content_automation.registry.ideas import (
    get_details,
    list_ideas,
    merge_ideas,
    review_queue,
    score_idea,
)
from content_automation.registry.sources import item_sources
from content_automation.registry.strategy import load_strategy

ideas_app = typer.Typer(no_args_is_help=True, help="The idea backlog: list, review, add, score.")
claims_app = typer.Typer(no_args_is_help=True, help="Labelled claims of an idea.")
JsonOption = Annotated[bool, typer.Option("--json", help="Print JSON (for skills).")]


def _fail(message: str, code: int = 1) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def _settings() -> Settings:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    try:
        return load_settings(require_credentials=False, create_directories=False)
    except ConfigurationError as error:
        _fail(str(error), 2)


@ideas_app.command("list")
def ideas_list(
    status: Annotated[str | None, typer.Option(help="Idea status, e.g. proposed.")] = None,
    pillar: Annotated[str | None, typer.Option(help="A strategy pillar.")] = None,
    min_score: Annotated[int | None, typer.Option("--min-score")] = None,
    as_json: JsonOption = False,
) -> None:
    """The backlog ("show backlog", "show ideas")."""
    settings = _settings()
    try:
        with registry_scope(settings, "ca ideas list") as scope:
            rows = [(item, details) for item, details in list_ideas(scope.conn)
                    if (status is None or item.idea_status == status)
                    and (pillar is None or details.pillar == pillar)
                    and (min_score is None or (details.score or 0) >= min_score)]
    except RegistryError as error:
        _fail(str(error))
    if as_json:
        typer.echo(json.dumps([{"id": item.id, "title": item.title, "idea": item.idea_status,
                                **asdict(details)} for item, details in rows],
                              ensure_ascii=False))
        return
    for item, details in rows:
        score = "—" if details.score is None else str(details.score)
        merged = f" (duplicate of {details.duplicate_of})" if details.duplicate_of else ""
        typer.echo(f"{item.id} {item.idea_status:<18} score {score:>3} "
                   f"{details.pillar or 'no pillar':<16} {', '.join(details.flags) or '—':<13} "
                   f"{item.title}{merged}")
    typer.echo(f"{len(rows)} idea(s).")


@ideas_app.command("review")
def ideas_review(limit: Annotated[int, typer.Option(min=1)] = 10) -> None:
    """The review queue: proposed ideas, best first, with sources, claims and flags
    ("review ideas"). Decide with approve / reject / revise BG-x."""
    settings = _settings()
    lines: list[str] = []
    try:
        with registry_scope(settings, "ca ideas review") as scope:
            for item, details in review_queue(scope.conn, limit):
                sources = item_sources(scope.conn, item.id)
                claims = list_claims(scope.conn, item.id)
                counts = {status: sum(c.status == status for c in claims)
                          for status in ("verified", "unverified", "disputed", "outdated")}
                lines.append(
                    f"{item.id} [score {details.score if details.score is not None else '—'}] "
                    f"{item.title}\n    pillar {details.pillar or '—'}; flags "
                    f"{', '.join(details.flags) or '—'}; sources: "
                    + (", ".join(f"{s.id} {s.publisher or s.type}" for s in sources) or "none")
                    + "; claims: " + (", ".join(f"{n} {k}" for k, n in counts.items() if n)
                                      or "none")
                )
    except RegistryError as error:
        _fail(str(error))
    typer.echo("\n".join(lines) if lines else "No ideas waiting for review.")


@ideas_app.command("add")
def ideas_add(
    text: Annotated[list[str], typer.Argument(help="The topic, in the user's words.")],
    notes: Annotated[str | None, typer.Option(help="Extra notes from the user.")] = None,
    assume: Annotated[
        list[str] | None, typer.Option(help="An assumption Codex made (repeatable).")
    ] = None,
) -> None:
    """A manual topic ("add topic …"): kept verbatim, then dedupe and a first pillar."""
    settings = _settings()
    words = " ".join(text).strip()
    if not words:
        _fail("Give the topic text.", 2)
    counts = RunCounts()
    try:
        strategy = load_strategy(settings.strategy_file)
        with registry_scope(settings, f'ca ideas add "{words}"') as scope:
            candidate = Candidate(words, notes or "", [SourceInput(
                "manual", title=words, publisher="user", text=words, role="manual")],
                original_text=words, assumptions=list(assume or []))
            item_id = ingest(scope.conn, settings, candidate, strategy, counts, actor="user",
                             command=scope.command)
    except RegistryError as error:
        _fail(str(error))
    typer.echo(counts.lines[-1] if counts.lines else item_id)


@ideas_app.command("score")
def ideas_score(
    ref: Annotated[str, typer.Argument(help="The idea (BG ID).")],
    pillar: Annotated[str, typer.Option(help='A strategy pillar, or "none".')],
    relevance: Annotated[int, typer.Option(help="Pillar relevance 1-5 (0 with none).")],
    german: Annotated[str, typer.Option(help="German relevance: yes, partial or no.")],
    reason: Annotated[str, typer.Option(help="One line: why this pillar and relevance.")],
) -> None:
    """Store Codex's pillar and German relevance; recency, trust and evidence are computed."""
    settings = _settings()
    try:
        strategy = load_strategy(settings.strategy_file)
        with registry_scope(settings, f"ca ideas score {ref}") as scope:
            details = score_idea(
                scope.conn, ref, pillar=None if pillar == "none" else pillar,
                relevance=relevance, german=german, reason=reason,
                pillars=[p.key for p in strategy.pillars], weights=strategy.weights,
                max_age_days=strategy.max_age_days, command=scope.command)
    except RegistryError as error:
        _fail(str(error))
    parts = ", ".join(f"{key} {part['points']:g}" for key, part in details.score_parts.items())
    typer.echo(f"{details.item_id}: score {details.score} ({parts}); pillar "
               f"{details.pillar or '—'}; flags {', '.join(details.flags) or '—'}")


@ideas_app.command("merge")
def ideas_merge(
    duplicate: Annotated[str, typer.Argument(help="The duplicate idea.")],
    into: Annotated[str, typer.Argument(help="The idea it merges into (kept).")],
) -> None:
    """Merge one idea into another ("merge BG-x into BG-y"): sources move, duplicate_of set."""
    settings = _settings()
    try:
        with registry_scope(settings, f"ca ideas merge {duplicate} {into}") as scope:
            details = merge_ideas(scope.conn, duplicate, into, command=scope.command)
    except RegistryError as error:
        _fail(str(error))
    typer.echo(f"{details.item_id} merged into {details.duplicate_of}; its sources moved over.")


@claims_app.command("add")
def claims_add(
    ref: Annotated[str, typer.Argument(help="The idea (BG ID).")],
    text: Annotated[str, typer.Option(help="The claim, from the source text.")],
    label: Annotated[str, typer.Option(help="fact, opinion or speculation.")],
    source: Annotated[list[str], typer.Option(help="A source ID (SRC-…), repeatable.")],
    counter: Annotated[
        list[str] | None, typer.Option(help="A source of the other side (disputed).")
    ] = None,
) -> None:
    """Add a claim; `ca` decides its status (verified only by the rules)."""
    settings = _settings()
    if label not in LABELS:
        _fail(f"--label must be {', '.join(LABELS)}.", 2)
    try:
        strategy = load_strategy(settings.strategy_file)
        with registry_scope(settings, f"ca claims add {ref} --label {label}") as scope:
            claim = add_claim(scope.conn, ref, text, label, source,
                              counter_ids=counter or [], max_age_days=strategy.max_age_days,
                              command=scope.command)
    except RegistryError as error:
        _fail(str(error))
    typer.echo(f"{claim.id} {claim.label}: {claim.status} ({claim.reason})")


@claims_app.command("list")
def claims_list(ref: Annotated[str, typer.Argument()], as_json: JsonOption = False) -> None:
    """The claims of an idea ("show claims for BG-x")."""
    settings = _settings()
    try:
        with registry_scope(settings, f"ca claims list {ref}") as scope:
            claims = list_claims(scope.conn, ref)
            title = get_details(scope.conn, ref).item_id
    except RegistryError as error:
        _fail(str(error))
    if as_json:
        typer.echo(json.dumps([asdict(claim) for claim in claims], ensure_ascii=False))
        return
    typer.echo(f"{title}: {len(claims)} claim(s)")
    for claim in claims:
        refs = ", ".join(claim.source_refs) + (
            f" vs {', '.join(claim.counter_refs)}" if claim.counter_refs else "")
        typer.echo(f"- {claim.id} {claim.label} {claim.status}: {claim.text} [{refs}] "
                   f"({claim.reason})")


@claims_app.command("check")
def claims_check(ref: Annotated[str, typer.Argument()]) -> None:
    """Decide the idea's claims again (e.g. sources became outdated)."""
    settings = _settings()
    try:
        strategy = load_strategy(settings.strategy_file)
        with registry_scope(settings, f"ca claims check {ref}") as scope:
            claims = check_claims(scope.conn, ref, max_age_days=strategy.max_age_days,
                                  command=scope.command)
    except RegistryError as error:
        _fail(str(error))
    for claim in claims:
        typer.echo(f"{claim.id} {claim.label}: {claim.status} ({claim.reason})")
