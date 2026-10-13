"""The Content Tracker: one row per finished package, shared with the social media manager.

Google Drive: the Google Sheet "Content Tracker" in the main folder (Sheets API). Mock:
tracking.csv in the mock main folder. Both follow the same merge rules (plan_upsert):

- Columns (PRD section 5). The workflow owns Content ID ... Image/video link; the manager owns
  Approval status, Publishing status and Publication date.
- Upsert by Content ID: only workflow cells that changed are written; a new package is a new
  row with Pending / Pending / blank, and the manager's cells are never written again. Rows
  are never deleted; columns are found by their header, so extra columns and a new column
  order are kept.
- One row per package: a carousel is one row; a Facebook ad's versions share one Caption cell,
  each starting with "— Version N —". Image/video link = the Drive folder of the Content ID.
- Registry columns (PRD Phase 4 §14 D-13..D-16; names in config/tracker.json, client to
  confirm): BG ID, Version, Idea, Generation, Review and Upload status, Last updated; appended
  after the existing columns when missing. Rows match by BG ID first, then Content ID, and the
  BG ID is filled in. Each workflow cell written is remembered (registry tracker_cells): a cell
  that differs from it was edited by hand, so the row is a conflict and is not written.
"""

import csv
import io
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from content_automation.content.brief import Caption, ContentBrief, ImageSlot
from content_automation.content.deliverables import DeliverableCatalog
from content_automation.content.package import BRIEF_FILE, ContentPackage
from content_automation.registry.tracker import CellRecord

WORKFLOW_COLUMNS = (
    "Content ID", "Topic", "Research source", "Platform", "Content type", "Caption",
    "Hashtags", "Image/video link",
)
MANAGER_DEFAULTS = {"Approval status": "Pending", "Publishing status": "Pending",
                    "Publication date": ""}  # written once, when the row is created
COLUMNS = (*WORKFLOW_COLUMNS, *MANAGER_DEFAULTS)
REGISTRY_KEYS = ("bg_id", "version", "idea", "generation", "review", "upload", "updated")
DEFAULT_REGISTRY_COLUMNS = {
    "bg_id": "BG ID", "version": "Version", "idea": "Idea status",
    "generation": "Generation status", "review": "Review status", "upload": "Upload status",
    "updated": "Last updated",
}
APPROVAL_STATUSES = ("Pending", "Approved", "Rejected")
PUBLISHING_STATUSES = ("Pending", "Posted")
PLATFORM_NAMES = {"linkedin": "LinkedIn", "facebook": "Facebook", "instagram": "Instagram"}
TRACKER_NAME = "Content Tracker"

Entry = dict[str, str]  # workflow column -> value
Table = list[list[str]]  # the header, then the rows as shown (a row may be shorter)


class TrackerError(ValueError):
    """The tracker lost a needed column, or a package's brief.json is unreadable."""


@dataclass(frozen=True)
class Cell:
    row: int  # 0-based; 0 is the header
    column: int  # 0-based
    value: str


@dataclass(frozen=True)
class Conflict:
    key: str  # the row's Content ID (or BG IDs)
    kind: str  # hand edit | duplicate | missing in the Sheet | missing in the registry
    detail: str

    def line(self) -> str:
        return f"{self.key}: {self.kind}: {self.detail}"


@dataclass
class TrackerPlan:
    cells: list[Cell] = field(default_factory=list)  # changed workflow cells (or a new header)
    rows: list[list[str]] = field(default_factory=list)  # new rows, after the last row
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    conflicts: list[Conflict] = field(default_factory=list)  # rows not written (D-15)
    records: dict[str, dict[str, CellRecord]] = field(default_factory=dict)  # after the write


def load_registry_columns(path: Path | None) -> dict[str, str]:
    """key -> column name (config/tracker.json "registry_columns"; defaults if missing)."""
    if path is None or not path.is_file():
        return dict(DEFAULT_REGISTRY_COLUMNS)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names = data.get("registry_columns", {})
    except (OSError, ValueError, AttributeError):
        return dict(DEFAULT_REGISTRY_COLUMNS)
    return {key: str(names.get(key) or DEFAULT_REGISTRY_COLUMNS[key]) for key in REGISTRY_KEYS}


def _ids(text: str) -> set[str]:
    return {part.strip() for part in text.split(",") if part.strip()}


def row_index(table: Table, bg_column: str | None) -> tuple[dict[str, list[int]],
                                                            dict[str, list[int]]]:
    """Content ID -> rows and BG ID -> rows (a copied row shows up twice)."""
    index = _columns(table)
    header = [cell.strip() for cell in table[0]]
    bg = header.index(bg_column) if bg_column and bg_column in header else None
    by_content: dict[str, list[int]] = {}
    by_bg: dict[str, list[int]] = {}
    for number, row in enumerate(table[1:], start=1):
        content_id = _cell(row, index["Content ID"]).strip()
        if content_id:
            by_content.setdefault(content_id, []).append(number)
        if bg is not None:
            for item in _ids(_cell(row, bg)):
                by_bg.setdefault(item, []).append(number)
    return by_content, by_bg


def _find(entry: Entry, by_content: dict[str, list[int]], by_bg: dict[str, list[int]],
          bg_column: str | None) -> tuple[int | None, bool]:
    """(the row of the entry, whether it is ambiguous): BG ID first, then Content ID."""
    rows: set[int] = set()
    if bg_column and entry.get(bg_column):
        for item in _ids(entry[bg_column]):
            rows.update(by_bg.get(item, []))
    if not rows:
        rows.update(by_content.get(entry["Content ID"], []))
    if not rows:
        return None, False
    return min(rows), len(rows) > 1


def plan_upsert(
    table: Table,
    entries: list[Entry],
    last: dict[str, dict[str, CellRecord]] | None = None,
    extra: tuple[str, ...] = (),
) -> TrackerPlan:
    """What to write so every entry has its row; manager cells of existing rows untouched.

    extra: the registry column names (appended to the header when missing). last: what was
    written before per row and column; a cell edited by hand since makes the row a conflict
    (nothing written for it). A cell is written when the registry value changed since the last
    write, or when there is no record yet and the Sheet differs (rows from before the registry).
    """
    plan = TrackerPlan()
    last = last or {}
    if not table or not any(cell.strip() for cell in table[0]):
        plan.cells += [Cell(0, column, name) for column, name in enumerate(COLUMNS)]
        table = [list(COLUMNS), *table[1:]]
    header = [cell.strip() for cell in table[0]]
    for name in extra:
        if name not in header:
            plan.cells.append(Cell(0, len(header), name))
            header.append(name)
    table = [header, *table[1:]]
    index = _columns(table)
    index.update({name: header.index(name) for name in extra})
    owned = (*WORKFLOW_COLUMNS, *extra)
    bg_column = extra[0] if extra else None
    by_content, by_bg = row_index(table, bg_column)
    width = len(header)
    for entry in {entry["Content ID"]: entry for entry in entries}.values():
        key = entry["Content ID"]
        found, ambiguous = _find(entry, by_content, by_bg, bg_column)
        if ambiguous:
            plan.conflicts.append(Conflict(key, "duplicate", "several rows have its BG ID or "
                                           "Content ID; nothing written"))
            continue
        records = last.get(key, {})
        if found is None:
            new = [""] * width
            for name, value in {**entry, **MANAGER_DEFAULTS}.items():
                if name in index:
                    new[index[name]] = value
            plan.rows.append(new)
            plan.added.append(key)
            plan.records[key] = {name: CellRecord(entry[name], entry[name])
                                 for name in owned if name in entry}
            continue
        row = table[found]
        edited = [name for name in owned if name in records
                  and _cell(row, index[name]) != records[name].written]
        if edited:
            plan.conflicts.append(Conflict(key, "hand edit", ", ".join(
                f'{name} "{_cell(row, index[name])}" (written: "{records[name].written}")'
                for name in edited) + "; row not written"))
            continue
        changed: list[Cell] = []
        kept: dict[str, CellRecord] = {}
        for name in owned:
            if name not in entry:
                continue
            value, shown, record = entry[name], _cell(row, index[name]), records.get(name)
            if record is None:
                if shown != value:
                    changed.append(Cell(found, index[name], value))
                kept[name] = CellRecord(value, value)
            elif value != record.source and value != shown:
                changed.append(Cell(found, index[name], value))
                kept[name] = CellRecord(value, value)
            elif value != record.source:  # the Sheet already shows the new value
                kept[name] = CellRecord(shown, value)
        plan.cells += changed
        if kept:
            plan.records[key] = kept
        if changed:
            plan.updated.append(key)
        else:
            plan.unchanged += 1
    return plan


def find_conflicts(
    table: Table,
    last: dict[str, dict[str, CellRecord]],
    expected: dict[str, set[str]],
    known_ids: set[str],
    extra: tuple[str, ...] = (),
) -> list[Conflict]:
    """`ca tracking conflicts`: hand edits, rows missing on either side, duplicate IDs.

    expected: row key (Content ID) -> BG IDs of every uploaded registry package; known_ids: every
    BG ID and alias the registry knows."""
    conflicts: list[Conflict] = []
    if not table or not any(cell.strip() for cell in table[0]):
        return [Conflict(key, "missing in the Sheet", f"{', '.join(sorted(ids))} uploaded, no "
                         "row") for key, ids in sorted(expected.items())]
    header = [cell.strip() for cell in table[0]]
    index = _columns(table)
    bg_column = extra[0] if extra and extra[0] in header else None
    by_content, by_bg = row_index(table, bg_column)
    for key, rows in sorted(by_content.items()):
        if len(rows) > 1:
            numbers = ", ".join(str(r + 1) for r in rows)
            conflicts.append(Conflict(key, "duplicate", f"rows {numbers} have this Content ID"))
    for item, rows in sorted(by_bg.items()):
        if len(set(rows)) > 1:
            conflicts.append(Conflict(item, "duplicate",
                                      f"rows {', '.join(str(r + 1) for r in sorted(set(rows)))}"
                                      " have this BG ID"))
    for number, row in enumerate(table[1:], start=1):
        key = _cell(row, index["Content ID"]).strip()
        ids = _ids(_cell(row, header.index(bg_column))) if bg_column else set()
        if not key and not ids:
            continue
        records = last.get(key, {})
        edited = [name for name, record in records.items() if name in header
                  and _cell(row, header.index(name)) != record.written]
        if edited:
            conflicts.append(Conflict(key, "hand edit", f"row {number + 1}: " + ", ".join(
                f'{name} "{_cell(row, header.index(name))}" (written: '
                f'"{records[name].written}")' for name in edited)))
        if key not in known_ids and not ids & known_ids:
            conflicts.append(Conflict(key or ", ".join(sorted(ids)), "missing in the registry",
                                      f"row {number + 1} matches no item"))
    for key, ids in sorted(expected.items()):
        if key not in by_content and not any(item in by_bg for item in ids):
            conflicts.append(Conflict(key, "missing in the Sheet",
                                      f"{', '.join(sorted(ids))} uploaded, no row"))
    return conflicts


def tracker_entry(
    folder: Path, package: ContentPackage, catalog: DeliverableCatalog, link: str
) -> Entry:
    """The workflow cells of a finished package; TrackerError if brief.json is unreadable."""
    try:
        raw: Any = json.loads((folder / BRIEF_FILE).read_text(encoding="utf-8"))
        brief = ContentBrief.model_validate(
            {key: value for key, value in raw.items() if not str(key).startswith("_")}
        )
    except (OSError, ValueError, AttributeError):
        raise TrackerError(f"{folder.name}: {BRIEF_FILE} missing or invalid") from None
    source = package.research_source or ", ".join(
        f"article:{article_id}" for article_id in package.source_article_ids
    ) or f"topic:{package.topic}"
    return {
        "Content ID": package.content_id or package.package_id,
        "Topic": package.topic,
        "Research source": source,
        "Platform": PLATFORM_NAMES.get(package.platform, package.platform),
        "Content type": ", ".join(package.deliverables or package.formats),
        "Caption": _caption_cell(brief, package, catalog),
        "Hashtags": " ".join(brief.hashtags),
        "Image/video link": link,
    }


def status_lines(table: Table) -> list[str]:
    """Rows, then one line per status of each manager status column (`ca tracking show`)."""
    if not table:
        return ["Rows: 0"]
    index = _columns(table)
    rows = [row for row in table[1:] if _cell(row, index["Content ID"]).strip()]
    lines = [f"Rows: {len(rows)}"]
    for column, known in (("Approval status", APPROVAL_STATUSES),
                          ("Publishing status", PUBLISHING_STATUSES)):
        counts = Counter(_cell(row, index[column]).strip() or "(blank)" for row in rows)
        for status in (*known, *sorted(set(counts) - set(known))):
            lines.append(f"{column} {status}: {counts[status]}")
    return lines


def read_csv_table(path: Path) -> Table:
    """A CSV file as a table (OSError when it cannot be read). Line breaks inside a cell come
    back as LF (Windows writes them as CRLF), so an unchanged caption compares equal."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [[cell.replace("\r\n", "\n") for cell in row] for row in csv.reader(handle)]


def table_csv(table: Table) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(table)
    return buffer.getvalue()


def header_index(table: Table) -> dict[str, int]:
    """Column name -> position in row 1."""
    return {cell.strip(): number for number, cell in enumerate(table[0])} if table else {}


def _columns(table: Table) -> dict[str, int]:
    header = [cell.strip() for cell in table[0]]
    missing = [name for name in COLUMNS if name not in header]
    if missing:
        raise TrackerError(
            f"{TRACKER_NAME}: row 1 has no {', '.join(missing)} column; put the header back "
            "(any order, extra columns are fine) and sync again."
        )
    return {name: header.index(name) for name in COLUMNS}


def _cell(row: list[str], column: int) -> str:
    return row[column] if column < len(row) else ""


def _caption_cell(brief: ContentBrief, package: ContentPackage, catalog: DeliverableCatalog) -> str:
    captions = dict(brief.captions) or ({"caption": brief.caption} if brief.caption else {})
    ad = package.items.get("ad")
    blocks: list[str] = []
    for name, caption in captions.items():
        text = _caption_text(caption, brief)
        item = catalog.deliverables.get(name)
        if item is not None and item.part == "ad" and brief.ad is not None and ad is not None:
            text = "\n\n".join(
                _version(number, file, brief.ad, text)
                for number, file in enumerate(ad.files, start=1)
            ) or text
        blocks.append(text if len(captions) == 1 else f"— {name} —\n{text}")
    notes = [note for item in package.items.values() for note in item.notes]
    if notes:  # carousel fallbacks and set-check notes, for the manager
        blocks.append("Notes: " + "; ".join(notes))
    return "\n\n".join(blocks)


def _caption_text(caption: Caption, brief: ContentBrief) -> str:
    """The post text as in post.md, without the hashtags (they have their own column)."""
    takeaways = "\n".join(f"- {line.strip()}" for line in caption.takeaways)
    return (f"{caption.hook.strip()}\n\n{takeaways}\n\n{caption.question.strip()}\n\n"
            f"{brief.cta.strip()} {brief.link}")


def _version(number: int, file: str, slot: ImageSlot, caption: str) -> str:
    """One ad version: its image, the ad text on it, then the caption."""
    lines = [f"— Version {number} —", f"Image: {Path(file).name}"]
    lines += [f"{label}: {value.strip()}" for label, value in (
        ("Headline", slot.headline), ("Subheadline", slot.subheadline), ("Button", slot.cta)
    ) if value]
    return "\n".join(lines) + "\n\n" + caption
