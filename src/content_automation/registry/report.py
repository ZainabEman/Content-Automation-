"""`ca item status`: everything known about one item, and where its files disagree (§14 D-7).

The registry owns the statuses; package.json, carousel/carousel.json and the mock tracker keep
pipeline detail. They are only read here: a disagreement is reported as a mismatch, never
fixed. Mock uploads are labelled "(mock)" and never count as Drive uploads (D-16).
"""

import csv
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from content_automation.registry.decisions import Decision, list_decisions
from content_automation.registry.gates import NextAction, next_actions
from content_automation.registry.items import Item, aliases, get_item, publications
from content_automation.registry.versions import Version, list_versions

PACKAGE_FILE = "package.json"
CAROUSEL_FILE = Path("carousel") / "carousel.json"
DONE_PACKAGE = "draft"  # package.json status once every part is made


@dataclass(frozen=True)
class JobSummary:
    counts: dict[str, int]  # job status -> number of jobs
    spent: dict[str, float]  # unit -> actual amount recorded

    def line(self) -> str:
        if not self.counts:
            return "none yet"
        counts = ", ".join(f"{n} {status}" for status, n in sorted(self.counts.items()))
        spent = ", ".join(f"{amount:g} {unit}" for unit, amount in sorted(self.spent.items()))
        return f"{counts}; spent {spent or 'nothing recorded'}"


@dataclass(frozen=True)
class ItemReport:
    item: Item
    aliases: list[str]
    publications: dict[str, str]
    versions: list[Version]
    decisions: list[Decision]  # the last 3, oldest first
    jobs: JobSummary
    drive: str
    tracker: str
    mismatches: list[str]
    next_actions: list[NextAction]

    def to_json(self) -> dict[str, Any]:
        item = asdict(self.item)
        planned = self.item.planned_date
        item["planned_date"] = planned.isoformat() if planned else None
        return {
            "item": item,
            "aliases": self.aliases,
            "statuses": {
                "idea": self.item.idea_status, "generation": self.item.generation_status,
                "review": self.item.review_status, "upload": self.item.upload_status,
                "publication": self.publications,
            },
            "versions": [asdict(v) for v in self.versions],
            "decisions": [asdict(d) for d in self.decisions],
            "jobs": asdict(self.jobs),
            "drive": self.drive,
            "tracker": self.tracker,
            "mismatches": self.mismatches,
            "next_actions": [asdict(a) for a in self.next_actions],
        }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _jobs(conn: sqlite3.Connection, item_id: str) -> JobSummary:
    counts = {
        str(row["status"]): int(row["n"]) for row in conn.execute(
            "SELECT status, COUNT(*) AS n FROM jobs WHERE item_id = ? GROUP BY status",
            (item_id,))
    }
    spent = {
        str(row["unit"]): float(row["total"]) for row in conn.execute(
            "SELECT unit, SUM(actual) AS total FROM jobs WHERE item_id = ? AND unit IS NOT NULL "
            "AND actual IS NOT NULL GROUP BY unit", (item_id,))
    }
    return JobSummary(counts, spent)


def _part_files(package: dict[str, Any], part: str | None) -> list[str] | None:
    items = package.get("items")
    if part is None or not isinstance(items, dict) or not isinstance(items.get(part), dict):
        return None
    files = items[part].get("files")
    return [str(f) for f in files] if isinstance(files, list) else []


def _uploads(package: dict[str, Any], files: list[str] | None) -> dict[str, dict[str, Any]]:
    uploads = package.get("uploads")
    if not isinstance(uploads, dict):
        return {}
    return {str(name): record for name, record in uploads.items()
            if isinstance(record, dict) and (files is None or name in files)}


def _drive_line(package: dict[str, Any] | None, files: list[str] | None) -> str:
    if package is None:
        return "no package yet"
    uploads = _uploads(package, files)
    drive = sum(1 for r in uploads.values()
                if r.get("status") == "uploaded" and r.get("provider") == "drive")
    mock = sum(1 for r in uploads.values()
               if r.get("status") == "uploaded" and r.get("provider") != "drive")
    failed = sum(1 for r in uploads.values() if r.get("status") == "upload_failed")
    waiting = len([f for f in files if f not in uploads]) if files is not None else 0
    if not uploads and not waiting:
        return "nothing uploaded yet"
    parts = [f"{drive} uploaded"] if drive else []
    parts += [f"{mock} uploaded (mock)"] if mock else []
    parts += [f"{failed} failed"] if failed else []
    parts += [f"{waiting} not uploaded"] if waiting else []
    return ", ".join(parts)


def _tracker_line(item: Item, names: list[str], tracker_csv: Path | None) -> str:
    if tracker_csv is None:
        return "not checked here (Google Sheet: ca tracking show)"
    if not tracker_csv.is_file():
        return "no mock tracker yet (mock)"
    with tracker_csv.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("BG ID") == item.id or (row.get("Content ID") or "") in names:
                return f"row found (Content ID {row.get('Content ID') or '—'}) (mock)"
    return "no row yet (mock)"


def _mismatches(item: Item, package: dict[str, Any] | None, part: str | None,
                carousel: dict[str, Any] | None) -> list[str]:
    found: list[str] = []
    generated = item.generation_status == "generated"
    if package is not None:
        items = package.get("items") if isinstance(package.get("items"), dict) else {}
        state = items.get(part, {}).get("status") if part and isinstance(items, dict) else None
        if part is not None and state is not None:
            if state == "done" and not generated:
                found.append(f"package.json: {part} is done, registry generation is "
                             f"{item.generation_status}")
            if state == "failed" and generated:
                found.append(f"package.json: {part} failed, registry generation is generated")
            if state in ("pending", "waiting", "review") and generated:
                found.append(f"package.json: {part} is {state}, registry generation is generated")
        elif part is None:
            done = str(package.get("status", "")).startswith(DONE_PACKAGE)
            if done != generated:
                found.append(f"package.json status is {package.get('status')!r}, registry "
                             f"generation is {item.generation_status}")
        files = _part_files(package, part)
        uploads = _uploads(package, files)
        expected = files if files is not None else list(uploads)
        all_up = bool(expected) and all(
            uploads.get(f, {}).get("status") == "uploaded" for f in expected)
        if all_up and item.upload_status != "uploaded":
            found.append(f"package.json: every file uploaded, registry upload is "
                         f"{item.upload_status}")
        if item.upload_status == "uploaded" and not all_up:
            found.append("registry upload is uploaded, package.json lists files not uploaded")
    if carousel is not None:
        stage = carousel.get("stage")
        if stage == "done" and not generated:
            found.append(f"carousel.json stage is done, registry generation is "
                         f"{item.generation_status}")
        if generated and stage not in ("done", None):
            found.append(f"carousel.json stage is {stage}, registry generation is generated")
    return found


def item_report(
    conn: sqlite3.Connection, ref: str, *, part: str | None = None,
    tracker_csv: Path | None = None,
) -> ItemReport:
    """The status report; `part` is the item's key in package.json "items" (post, ad,
    carousel, reel), `tracker_csv` the mock tracker (None for the Google Sheet)."""
    item = get_item(conn, ref)
    names = aliases(conn, item.id)
    folder = Path(item.package_path) if item.package_path else None
    package = _read_json(folder / PACKAGE_FILE) if folder else None
    carousel = (_read_json(folder / CAROUSEL_FILE)
                if folder and part in (None, "carousel") else None)
    files = _part_files(package, part) if package else None
    return ItemReport(
        item=item,
        aliases=names,
        publications=publications(conn, item.id),
        versions=list_versions(conn, item.id),
        decisions=list_decisions(conn, item.id)[-3:],
        jobs=_jobs(conn, item.id),
        drive=_drive_line(package, files),
        tracker=_tracker_line(item, names, tracker_csv),
        mismatches=_mismatches(item, package, part, carousel),
        next_actions=next_actions(item),
    )
