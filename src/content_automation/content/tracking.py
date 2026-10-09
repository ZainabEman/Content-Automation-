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

WORKFLOW_COLUMNS = (
    "Content ID", "Topic", "Research source", "Platform", "Content type", "Caption",
    "Hashtags", "Image/video link",
)
MANAGER_DEFAULTS = {"Approval status": "Pending", "Publishing status": "Pending",
                    "Publication date": ""}  # written once, when the row is created
COLUMNS = (*WORKFLOW_COLUMNS, *MANAGER_DEFAULTS)
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


@dataclass
class TrackerPlan:
    cells: list[Cell] = field(default_factory=list)  # changed workflow cells (or a new header)
    rows: list[list[str]] = field(default_factory=list)  # new rows, after the last row
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0


def plan_upsert(table: Table, entries: list[Entry]) -> TrackerPlan:
    """What to write so every entry has its row; manager cells of existing rows untouched."""
    plan = TrackerPlan()
    if not table or not any(cell.strip() for cell in table[0]):
        plan.cells += [Cell(0, column, name) for column, name in enumerate(COLUMNS)]
        table = [list(COLUMNS), *table[1:]]
    index = _columns(table)
    rows_by_id: dict[str, int] = {}
    for number, row in enumerate(table[1:], start=1):
        content_id = _cell(row, index["Content ID"]).strip()
        if content_id:
            rows_by_id.setdefault(content_id, number)  # a copied row: the first one counts
    width = len(table[0])
    for entry in {entry["Content ID"]: entry for entry in entries}.values():
        found = rows_by_id.get(entry["Content ID"])
        if found is None:
            new = [""] * width
            for name, value in {**entry, **MANAGER_DEFAULTS}.items():
                new[index[name]] = value
            plan.rows.append(new)
            plan.added.append(entry["Content ID"])
            continue
        changed = [
            Cell(found, index[name], entry[name]) for name in WORKFLOW_COLUMNS
            if _cell(table[found], index[name]) != entry[name]
        ]
        plan.cells += changed
        if changed:
            plan.updated.append(entry["Content ID"])
        else:
            plan.unchanged += 1
    return plan


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
    """A CSV file as a table (OSError when it cannot be read)."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [list(row) for row in csv.reader(handle)]


def table_csv(table: Table) -> str:
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(table)
    return buffer.getvalue()


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
