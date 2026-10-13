"""Readers for `ca registry migrate` (PRD Phase 4 §9, §14 D-1, D-2, D-8, D-18).

Sources, read only: calendar CSVs (old 9-column and new headers), package.json files (v2 with
"deliverables"; v1 without: the deliverable is derived from the part and platform where it is
clear), carousel/carousel.json (stage), <SECRETS_DIR>/drive_state.json (only the number of known
Drive folders is reported; its content is never printed) and the mock tracker (rows that match
nothing are reported). A calendar row and the package it started are one item. After the
migration, old CSVs are rewritten with the new header (the registry view).
"""

import csv
import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from content_automation.content.calendar import (
    CalendarError,
    has_old_header,
    read_calendar,
    write_calendar,
)
from content_automation.content.deliverables import DeliverableCatalog
from content_automation.core.config import Settings
from content_automation.registry import runtime
from content_automation.registry.migrate import Candidate
from content_automation.storage import ROOT_FOLDER

PACKAGE_FILE = "package.json"
CAROUSEL_FILE = Path("carousel") / "carousel.json"
DRIVE_STATE = "drive_state.json"
TRACKER_FILE = "tracking.csv"
ROW_IDEA = {"Proposed": "proposed", "Approved": "approved", "In progress": "approved",
            "Failed": "approved", "Generated": "approved", "Rejected": "rejected",
            "Revision requested": "proposed"}
V1_DELIVERABLES = {("post", "facebook"): "facebook_post", ("post", "linkedin"): "linkedin_post",
                   ("ad", ""): "facebook_ad", ("carousel", ""): "instagram_carousel",
                   ("reel", ""): "reel_short"}
PART_KIND = {"post": "post", "ad": "ad", "carousel": "carousel", "reel": "short"}


@dataclass
class Sources:
    candidates: list[Candidate] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _key(folder: str, deliverable: str | None, fallback: str) -> str:
    if deliverable:
        return f"pkg:{Path(folder).resolve().as_posix()}#{deliverable}"
    return f"pkg:{Path(folder).resolve().as_posix()}#{fallback}"


def _calendar_rows(settings: Settings, catalog: DeliverableCatalog, found: Sources,
                   by_key: dict[str, Candidate]) -> None:
    for path in sorted(settings.calendar_dir.glob("*.csv")):
        try:
            rows = read_calendar(path)
        except CalendarError as error:
            found.unreadable.append(f"{path.as_posix()}: {error}")
            continue
        for row in rows:
            where = f"calendar {path.stem} row {row['Row']}"
            spec = catalog.deliverables.get(row["Content type"])
            if spec is None:
                found.unreadable.append(f"{where}: unknown content type "
                                        f"\"{row['Content type']}\"")
                continue
            content_id = row["Content ID"] or f"{path.stem}-{int(row['Row'] or 0):02d}"
            try:
                planned = date.fromisoformat(row["Planned date"]) if row["Planned date"] else None
            except ValueError:
                planned = None
            package = row["Package"] or None
            candidate = Candidate(
                key=(_key(package, row["Content type"], "") if package
                     else f"row:{content_id}"),
                source=where, order=row["Planned date"] or path.stem, kind=spec.item_kind,
                title=row["Topic"] or content_id, deliverable=row["Content type"],
                platforms=[spec.platform] if spec.platform else [], planned_date=planned,
                package_path=package,
                source_refs=[row["Research source"]] if row["Research source"] else [],
                aliases=[content_id] + ([f"{Path(package).name}#{row['Content type']}"]
                                        if package else []),
                idea=ROW_IDEA.get(row["Status"], "proposed"),
                generation="generated" if row["Status"] == "Generated" else "not_started",
            )
            by_key[candidate.key] = candidate
            found.candidates.append(candidate)


def _part_state(item: dict[str, Any]) -> str:
    return {"done": "generated", "failed": "failed", "review": "running",
            "waiting": "running"}.get(str(item.get("status", "pending")), "not_started")


def _uploads(data: dict[str, Any], files: list[str]) -> tuple[str | None, str | None]:
    records = _dict(data.get("uploads"))
    states = [_dict(records.get(name)) for name in files if isinstance(records.get(name), dict)]
    if not files or not states:
        return None, None
    providers = {str(state.get("provider", "mock")) for state in states}
    provider = "drive" if providers == {"drive"} else "mock"
    if any(state.get("status") == "upload_failed" for state in states):
        return "failed", provider
    if len(states) == len(files) and all(state.get("status") == "uploaded" for state in states):
        return "uploaded", provider
    return None, None


def _packages(settings: Settings, catalog: DeliverableCatalog, found: Sources,
              by_key: dict[str, Candidate]) -> None:
    for folder in sorted(path for path in settings.packages_dir.glob("*") if path.is_dir()):
        file = folder / PACKAGE_FILE
        if not file.is_file():
            continue
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
        except (OSError, ValueError) as error:
            found.unreadable.append(f"{file.as_posix()}: {error}")
            continue
        items = _dict(data.get("items"))
        platform = str(data.get("platform", ""))
        names = [str(name) for name in data.get("deliverables") or []]
        version = "v2" if names else "v1"
        parts: list[tuple[str, str | None]] = []
        if names:
            for name in names:
                spec = catalog.deliverables.get(name)
                if spec is None:
                    found.unreadable.append(f"{file.as_posix()}: unknown deliverable {name}")
                    continue
                parts.append((str(spec.brief_format), name))
        else:  # v1: one part per made item; the deliverable only where it is clear
            for part in items:
                derived = (V1_DELIVERABLES.get((part, platform))
                           or V1_DELIVERABLES.get((part, "")))
                parts.append((part, derived))
                if derived is None:
                    found.notes.append(f"{folder.name}: v1 {part} for {platform or '?'} has no "
                                       "matching deliverable; registered by its part only")
        path = folder.as_posix()
        for part, deliverable in parts:
            part_item = _dict(items.get(part))
            generation = _part_state(part_item) if part_item else "not_started"
            carousel = folder / CAROUSEL_FILE
            if part == "carousel" and carousel.is_file():
                try:
                    stage = json.loads(carousel.read_text(encoding="utf-8")).get("stage")
                    generation = "generated" if stage == "done" else "running"
                except (OSError, ValueError) as error:
                    found.notes.append(f"{carousel.as_posix()}: not readable ({error})")
            files = [str(f) for f in part_item.get("files", [])] if part_item else []
            upload, provider = _uploads(data, files)
            key = _key(path, deliverable, part)
            existing = by_key.get(key)
            if existing is not None:  # the calendar row that started this package
                if existing.idea == "approved":
                    existing.generation = generation
                existing.upload, existing.upload_provider = upload, provider
                continue
            spec = catalog.deliverables.get(deliverable) if deliverable else None
            content_id = data.get("contentId")
            aliases = [f"{folder.name}#{deliverable or part}"]
            aliases += [folder.name] if len(parts) == 1 else []
            aliases += [str(content_id)] if content_id else []
            candidate = Candidate(
                key=key, source=f"package {folder.name} ({version})",
                order=str(data.get("createdAt") or folder.name),
                kind=spec.item_kind if spec else PART_KIND.get(part, "post"),
                title=str(data.get("topic") or folder.name), deliverable=deliverable,
                platforms=[(spec.platform if spec and spec.platform else platform)]
                if (spec and spec.platform) or platform else [],
                package_path=path,
                source_refs=[str(data["researchSource"])] if data.get("researchSource") else [],
                aliases=aliases, idea="approved", generation=generation, upload=upload,
                upload_provider=provider,
                note=f"migrated: package made before the registry ({version})",
            )
            by_key[key] = candidate
            found.candidates.append(candidate)


def _drive_state(settings: Settings, found: Sources) -> None:
    path = settings.secrets_dir / DRIVE_STATE
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        folders = data.get("contentFolders") if isinstance(data, dict) else None
        count = len(folders) if isinstance(folders, dict) else 0
    except (OSError, ValueError):
        found.notes.append(f"{DRIVE_STATE}: not readable (left as it is)")
        return
    found.notes.append(f"{DRIVE_STATE}: {count} Drive content folder(s) known (read only; "
                       "uploads come from package.json)")


def _tracker(settings: Settings, found: Sources) -> None:
    path = settings.drive_mock_dir / ROOT_FOLDER / TRACKER_FILE
    if not path.is_file():
        return
    known = {alias for candidate in found.candidates for alias in candidate.aliases}
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except OSError as error:
        found.unreadable.append(f"{path.as_posix()}: {error}")
        return
    orphans = [row.get("Content ID", "") for row in rows
               if row.get("Content ID") and row.get("Content ID") not in known]
    found.notes.append(f"mock tracker: {len(rows)} row(s), {len(orphans)} without a calendar row "
                       "or package" + (f" ({', '.join(orphans)}; not migrated)" if orphans else ""))


def collect_sources(settings: Settings, catalog: DeliverableCatalog) -> Sources:
    found = Sources()
    by_key: dict[str, Candidate] = {}
    _calendar_rows(settings, catalog, found, by_key)
    _packages(settings, catalog, found, by_key)
    _drive_state(settings, found)
    _tracker(settings, found)
    return found


def rewrite_old_calendars(settings: Settings) -> list[str]:
    """After the migration: old 9-column CSVs get the new header with the BG IDs (the view)."""
    scope = runtime.current()
    if scope is None:
        return []
    lines: list[str] = []
    for path in sorted(settings.calendar_dir.glob("*.csv")):
        try:
            if not has_old_header(path):
                continue
            rows = read_calendar(path)
        except (OSError, CalendarError):
            continue
        for row in rows:
            content_id = row["Content ID"] or f"{path.stem}-{int(row['Row'] or 0):02d}"
            hit = scope.conn.execute("SELECT item_id FROM aliases WHERE alias = ?",
                                     (content_id,)).fetchone()
            row["BG ID"] = str(hit["item_id"]) if hit else ""
        write_calendar(path, rows, force=True)
        lines.append(f"{path.as_posix()}: rewritten with the new header (BG ID, Version).")
    return lines
