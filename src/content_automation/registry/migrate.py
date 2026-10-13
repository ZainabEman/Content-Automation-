"""`ca registry migrate`: what existed before the registry becomes items (PRD §9, §14 D-8,
D-18).

The readers (content/migration.py) turn calendar CSVs, package.json files (v1 and v2),
carousel.json, drive_state.json and the mock tracker into candidates. Here: a candidate already
registered (one of its aliases, or its package and deliverable) is skipped; the rest are
created oldest first after a backup of the database, with their aliases, v1 and the status
mapping of PRD §9 (Proposed -> idea proposed; Approved -> approved; Rejected -> rejected;
Generated -> approved + generated; uploaded files -> upload uploaded, mock kept as mock), each
decision noting that it was migrated. One migration_run event. Running it again creates nothing.
"""

import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from content_automation.registry.approvals import approve, reject
from content_automation.registry.audit import append_event
from content_automation.registry.db import backup
from content_automation.registry.ids import parse_id
from content_automation.registry.items import add_alias, create_item
from content_automation.registry.link import package_item
from content_automation.registry.progress import job_started, part_done, part_failed, set_upload


@dataclass
class Candidate:
    key: str  # one item: "pkg:<folder>#<deliverable>" or "row:<Content ID>"
    source: str  # where it was found (for the report)
    order: str  # oldest first
    kind: str
    title: str
    deliverable: str | None = None
    platforms: list[str] = field(default_factory=list)
    planned_date: date | None = None
    package_path: str | None = None
    source_refs: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    idea: str = "approved"  # proposed | approved | rejected
    generation: str = "not_started"  # not_started | running | generated | failed
    upload: str | None = None  # uploaded | failed
    upload_provider: str | None = None
    note: str = ""


@dataclass
class MigrationReport:
    created: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    backup: Path | None = None

    def lines(self, *, dry_run: bool) -> list[str]:
        verb = "would be created" if dry_run else "created"
        lines = [f"{'DRY RUN: ' if dry_run else ''}{len(self.created)} {verb}, "
                 f"{len(self.skipped)} skipped (already migrated), {len(self.unreadable)} "
                 "unreadable."]
        lines += [f"  {'+' if dry_run else 'created'} {line}" for line in self.created]
        lines += [f"  skipped {line}" for line in self.skipped]
        lines += [f"  unreadable {line}" for line in self.unreadable]
        lines += [f"  note: {line}" for line in self.notes]
        if self.backup is not None:
            lines.append(f"Backup first: {self.backup.as_posix()}")
        return lines


def registered(conn: sqlite3.Connection, candidate: Candidate) -> str | None:
    """The BG ID of an item that already stands for this candidate."""
    for alias in candidate.aliases:
        row = conn.execute("SELECT item_id FROM aliases WHERE alias = ?", (alias,)).fetchone()
        if row is not None:
            return str(row["item_id"])
    if candidate.package_path and candidate.deliverable:
        item = package_item(conn, Path(candidate.package_path), candidate.deliverable)
        if item is not None:
            return item.id
    return None


def _describe(candidate: Candidate, item_id: str | None = None) -> str:
    what = candidate.deliverable or candidate.kind
    head = f"{item_id} " if item_id else ""
    return (f"{head}{what}: {candidate.title} ({candidate.source}; idea {candidate.idea}, "
            f"generation {candidate.generation}"
            + (f", upload {candidate.upload}" + (f" ({candidate.upload_provider})"
                                                if candidate.upload_provider != "drive" else "")
               if candidate.upload else "") + ")")


def _create(conn: sqlite3.Connection, candidate: Candidate, command: str) -> str:
    item = create_item(
        conn, kind=candidate.kind, title=candidate.title, topic=candidate.title,
        platforms=candidate.platforms, planned_date=candidate.planned_date,
        source_refs=candidate.source_refs, package_path=candidate.package_path,
        deliverable=candidate.deliverable, notes=candidate.note or None, command=command,
    )
    for alias in candidate.aliases:
        taken = conn.execute("SELECT 1 FROM aliases WHERE alias = ?", (alias,)).fetchone()
        if alias and taken is None and parse_id(alias) is None:
            add_alias(conn, item.id, alias, command=command)
    note = f"migrated from {candidate.source} (decided before the registry)"
    if candidate.idea in ("approved",):
        approve(conn, item.id, gate="idea", actor="user", command=command, note=note)
    elif candidate.idea == "rejected":
        reject(conn, item.id, note, gate="idea", actor="user", command=command)
    if candidate.idea == "approved":
        if candidate.generation == "generated":
            part_done(conn, item.id, command=command)
        elif candidate.generation in ("running", "failed"):
            job_started(conn, item.id, command=command)
            if candidate.generation == "failed":
                part_failed(conn, item.id, command=command)
    if candidate.upload in ("uploaded", "failed"):
        set_upload(conn, item.id, candidate.upload, candidate.upload_provider or "mock",
                   command=command)
    return item.id


def plan_migration(conn: sqlite3.Connection, candidates: list[Candidate]
                   ) -> tuple[list[Candidate], list[str]]:
    """(the candidates to create, oldest first; the skipped ones with their BG IDs)."""
    todo: list[Candidate] = []
    skipped: list[str] = []
    for candidate in sorted(candidates, key=lambda c: (c.order, c.key)):
        found = registered(conn, candidate)
        if found is not None:
            skipped.append(f"{found} {candidate.deliverable or candidate.kind}: "
                           f"{candidate.title} ({candidate.source})")
        else:
            todo.append(candidate)
    return todo, skipped


def migrate_candidates(
    conn: sqlite3.Connection, db_file: Path, candidates: list[Candidate], *,
    unreadable: list[str], notes: list[str], dry_run: bool, command: str,
) -> MigrationReport:
    """Create what is missing (after a backup), or with dry_run only report it."""
    todo, skipped = plan_migration(conn, candidates)
    report = MigrationReport(skipped=skipped, unreadable=list(unreadable), notes=list(notes))
    if dry_run:
        report.created = [_describe(candidate) for candidate in todo]
        return report
    if todo:
        report.backup = backup(conn, db_file)
    for candidate in todo:
        item_id = _create(conn, candidate, command)
        report.created.append(_describe(candidate, item_id))
    append_event(conn, "migration_run", actor="user", command=command,
                 details={"kind": "data", "created": len(report.created),
                          "skipped": len(report.skipped), "unreadable": len(report.unreadable),
                          "backup": report.backup.as_posix() if report.backup else None})
    return report
