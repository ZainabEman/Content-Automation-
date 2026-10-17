"""Content calendar: calendar/<YYYY-Www>.csv, one row per planned post (`ca calendar`).

new: fill the week's cadence slots (config/calendar.json) in weekday order, first with the
picks (--topic values, then --idea numbers from the newest newsletter content list, then
--article IDs), then with the newest list's other ideas and the newest scraper articles.
Ideas and articles already planned in another week are skipped. Every row starts as Proposed.
check: dates inside the week, known platforms and deliverables, a research source on every
row, no topic twice in one week. Nothing is generated or charged by new, check or show.
approve / reject: Proposed -> Approved or Rejected, and Approved <-> Rejected; a Generated row
never changes.
generate: stage 1 (free, `ca content start` unchanged) for every Approved row without a
package, then one combined dry run with the cost per row and the total. generate --build
(after the user's "ok") builds each ready row once with the normal build; person and set
checks then go on per package with `ca content build`. A finished package makes its row
Generated; a failed row stays Approved, is reported, and is never retried by itself.
The row's Content ID and Research source are saved in its package.json (the package's
Drive folder name and its Content Tracker row).

Inside a `ca` command the CSV is a view of the registry (PRD Phase 4 D10, §14 D-8, D-9, D-11,
D-12): every row is an item (BG ID column), Status and Version come from the registry, and each
write stores the file's text, so a file edited by hand since stops the command with a diff
(CalendarEdited; `ca calendar sync --discard-edits|--import-edits`). Old 9-column files are
still read; their next write uses the new header.
"""

import csv
import io
import re
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError

from content_automation.content.backlog import pillar_guess
from content_automation.content.brief import PLATFORMS
from content_automation.content.deliverables import DeliverableCatalog
from content_automation.content.formats import ROMAN, FormatError, load_formats
from content_automation.content.package import (
    BRIEF_FILE,
    DONE_STATUS,
    PACKAGE_FILE,
    ContentPackage,
    build_package,
    load_package,
    save_package,
    start_package,
)
from content_automation.content.plan_config import (
    NOT_PRODUCIBLE,
    WEEKDAYS,
    Weekday,
    plan_only_types,
)
from content_automation.content.relevance import service_fit
from content_automation.content.research_input import ResearchFile, ResearchIdea, load_idea
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.references.services import ServicesError, load_services
from content_automation.registry import runtime
from content_automation.registry.approvals import approve, reject
from content_automation.registry.db import RegistryError
from content_automation.registry.dryruns import CostLine
from content_automation.registry.files import edited_diff, last_written, record_written
from content_automation.registry.gates import gate_open
from content_automation.registry.items import get_item, set_planned_date, set_title
from content_automation.registry.link import register_row
from content_automation.registry.strategy import load_strategy
from content_automation.research.run import digest
from content_automation.research.store import find_article
from content_automation.storage.manifest import MANIFEST_FILE, PENDING_STATUS

COLUMNS = (
    "Row", "BG ID", "Planned date", "Topic", "Research source", "Platform", "Content type",
    "Status", "Version", "Package", "Content ID", "Format",
)
# Before the Format column (2026-10-16): still read; the next write adds the column.
NO_FORMAT_COLUMNS = COLUMNS[:-1]
ROMAN_PLATFORMS = ("linkedin", "facebook")  # Roman's weekly post alternates between them
OLD_COLUMNS = (  # before the registry (Phase 1-3): still read (D-8)
    "Row", "Planned date", "Topic", "Research source", "Platform", "Content type", "Status",
    "Package", "Content ID",
)
STATUSES = ("Proposed", "Approved", "Rejected", "Generated", "Revision requested",
            "In progress", "Failed")
APPROVED_STATES = ("Approved", "In progress", "Failed")  # the idea is approved, not generated
Decision = Literal["Approved", "Rejected"]
CHANGES_FROM: dict[Decision, tuple[str, ...]] = {  # the statuses each decision may replace
    "Approved": ("Proposed", "Rejected"),
    "Rejected": ("Proposed", "Approved"),
}
NEWSLETTER_DIR = "newsletters"  # under RESEARCH_DIR, written by the show-content skill
LIST_SUFFIX = "_content-list.json"
ARTICLE_DAYS = 14  # scraper articles from the last N days fill the remaining slots
SOURCE_HELP = ('"topic:<text>", "newsletter:<YYYY-MM-DD>#<n>", "article:<id>" or '
               '"idea:<BG-x>"')
_WEEK = re.compile(r"(\d{4})-W(\d{1,2})")
_SOURCE = re.compile(r"(topic|newsletter|article|idea):(\S.*)")
_NEWSLETTER = re.compile(r"(\d{4}-\d{2}-\d{2})#(\d+)")

Row = dict[str, str]


class CalendarError(ValueError):
    """A bad week, cadence file, calendar file or pick."""


class CalendarEdited(CalendarError):
    """The CSV was edited by hand since the app last wrote it (D10): nothing was written."""

    def __init__(self, path: Path, label: str, diff: str) -> None:
        self.path = path
        self.diff = diff
        super().__init__(
            f"{path} was edited by hand since the last write; nothing was changed. The edits:\n"
            f"{diff.rstrip()}\nChoose one: uv run ca calendar sync --week {label} "
            "--discard-edits (keep the registry) or --import-edits (take the Topic and Planned "
            "date edits; Status edits are never imported: approve or reject instead)."
        )

class _Model(CamelModel):
    model_config = ConfigDict(extra="forbid")


class Slot(_Model):
    weekday: Weekday
    deliverable: str = Field(min_length=1)


class Cadence(_Model):
    note: str | None = Field(default=None, alias="_note")
    slots: list[Slot] = Field(min_length=1)
    plan: dict[str, object] | None = None  # calendar v2, read by content/plan_config.py


@dataclass(frozen=True)
class Idea:
    topic: str
    source: str  # topic:<text> | newsletter:<YYYY-MM-DD>#<n> | article:<id>


def week_label(text: str, today: date | None = None) -> str:
    """"this", "next" or "2026-W42" -> "2026-W42" (ISO week)."""
    value = text.strip().lower()
    if value in ("this", "next"):
        day = (today or date.today()) + timedelta(weeks=value == "next")
        year, week, _ = day.isocalendar()
        return f"{year}-W{week:02d}"
    match = _WEEK.fullmatch(value.upper())
    if match is not None:
        year, week = int(match[1]), int(match[2])
        try:
            date.fromisocalendar(year, week, 1)
            return f"{year}-W{week:02d}"
        except ValueError:
            pass
    raise CalendarError(f'"{text}" is not a week: use this, next or e.g. 2026-W42.')


def week_days(label: str) -> list[date]:
    year, week = label.split("-W")
    monday = date.fromisocalendar(int(year), int(week), 1)
    return [monday + timedelta(days=offset) for offset in range(7)]


def calendar_path(settings: Settings, label: str) -> Path:
    return settings.calendar_dir / f"{label}.csv"


def load_cadence(path: Path, catalog: DeliverableCatalog) -> Cadence:
    try:
        cadence = Cadence.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError:
        raise CalendarError(
            f"Cadence file not found at {path}. Restore config/calendar.json or set "
            "CALENDAR_FILE in .env."
        ) from None
    except ValidationError as error:
        fields = sorted({".".join(str(p) for p in issue["loc"]) for issue in error.errors()})
        raise CalendarError(f"{path.name} is invalid; check: {', '.join(fields)}.") from None
    unknown = [slot.deliverable for slot in cadence.slots if slot.deliverable not in
               catalog.deliverables]
    if unknown:
        raise CalendarError(
            f"{path.name}: unknown deliverables {', '.join(unknown)} (see `uv run ca content "
            "deliverables`)."
        )
    return cadence


def read_calendar(path: Path) -> list[Row]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = tuple(reader.fieldnames or ())
            rows = [{key: (value or "").strip() for key, value in row.items() if key}
                    for row in reader]
    except OSError:
        raise CalendarError(
            f"No calendar at {path}: make it with `uv run ca calendar new`."
        ) from None
    if header not in (COLUMNS, NO_FORMAT_COLUMNS, OLD_COLUMNS):
        raise CalendarError(f"{path.name}: the columns must be {', '.join(COLUMNS)}.")
    return [{column: row.get(column, "") for column in COLUMNS} for row in rows]


def has_old_header(path: Path) -> bool:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return tuple(csv.DictReader(handle).fieldnames or ()) == OLD_COLUMNS


def _label_of(path: Path) -> str:
    return path.stem


def render_calendar(rows: list[Row]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows([{column: row.get(column, "") for column in COLUMNS} for row in rows])
    return buffer.getvalue()


def view_status(idea: str, generation: str) -> str:
    """The CSV Status of an item (D-9): its idea status, then its generation."""
    if idea != "approved":
        return {"proposed": "Proposed", "revision_requested": "Revision requested",
                "rejected": "Rejected"}.get(idea, "Proposed")
    return {"not_started": "Approved", "queued": "In progress", "running": "In progress",
            "generated": "Generated", "failed": "Failed", "partial": "Failed"}[generation]


def _view_row(conn: sqlite3.Connection, row: Row) -> Row:
    if not row.get("BG ID"):
        return row
    try:
        item = get_item(conn, row["BG ID"])
    except RegistryError:
        return row  # an ID this registry does not know: shown as written
    view = dict(row)
    view.update({
        "Topic": item.topic,
        "Planned date": item.planned_date.isoformat() if item.planned_date else "",
        "Status": view_status(item.idea_status, item.generation_status),
        "Version": str(item.current_version),
        "Package": item.package_path or row.get("Package", ""),
    })
    return view


def read_view(path: Path) -> list[Row]:
    """The rows as the registry sees them (Status, Version, Topic, dates); outside a `ca`
    command the file as written."""
    rows = read_calendar(path)
    scope = runtime.current()
    return [_view_row(scope.conn, row) for row in rows] if scope is not None else rows


def check_edits(path: Path) -> None:
    """Inside a `ca` command: CalendarEdited if the CSV was edited by hand since the last
    write (D10)."""
    scope = runtime.current()
    if scope is None:
        return
    diff = edited_diff(scope.conn, path)
    if diff:
        raise CalendarEdited(path, _label_of(path), diff)


def write_calendar(path: Path, rows: list[Row], *, force: bool = False) -> None:
    """Write the CSV. Inside a `ca` command: refuse a hand-edited file (unless force: the
    sync command), fill Status, Version, Topic and dates from the registry, store the text."""
    scope = runtime.current()
    if scope is not None:
        if not force:
            check_edits(path)
        rows = [_view_row(scope.conn, row) for row in rows]
    text = render_calendar(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, text)
    if scope is not None:
        record_written(scope.conn, path, text)


def is_roman(value: str) -> bool:
    """A row's Format that shows Roman: "roman" (picked at stage 1) or a roman_* format."""
    return value.strip().lower().startswith(ROMAN)


def assign_roman(rows: list[Row], label: str, catalog: DeliverableCatalog) -> str | None:
    """Roman exactly once a week: one LinkedIn or Facebook post row gets Format "roman" (one of
    the 4 Roman formats, rotated at stage 1), the platform alternating week by week; nothing
    when the week already has one. Returns the row number it went to."""
    if any(is_roman(row.get("Format", "")) for row in rows):
        return None
    weeks = week_days(label)[0].toordinal() // 7
    first = ROMAN_PLATFORMS[weeks % 2]
    for platform in (first, *(name for name in ROMAN_PLATFORMS if name != first)):
        options = sorted(
            (row for row in rows
             if row["Platform"] == platform and not row.get("Format") and not row["Package"]
             and row["Status"] in ("Proposed", "Approved")
             and (item := catalog.deliverables.get(row["Content type"])) is not None
             and item.part == "post"),
            key=lambda row: row["Planned date"],
        )
        if options:
            options[0]["Format"] = ROMAN
            return options[0]["Row"]
    return None


def _pillar_fit(settings: Settings) -> Callable[[str], bool] | None:
    """Whether a topic fits a content pillar (config/strategy.json keywords); None: no
    pillar keywords, nothing is filtered."""
    try:
        strategy = load_strategy(settings.strategy_file)
    except (RegistryError, OSError, ValueError):
        return None
    if not any(pillar.keywords for pillar in strategy.pillars):
        return None  # no strategy file: the default pillars name no keywords
    return lambda topic: pillar_guess(topic, strategy) is not None


def new_calendar(
    settings: Settings,
    catalog: DeliverableCatalog,
    label: str,
    *,
    topics: list[str],
    idea_numbers: list[int],
    article_ids: list[str],
    replace: bool = False,
) -> tuple[Path, list[str]]:
    """Write the week's calendar; returns its path and the lines for Codex."""
    path = calendar_path(settings, label)
    if path.exists():
        if not replace:
            raise CalendarError(
                f"{path} already exists: show it with `uv run ca calendar show --week {label}`, "
                "or add --replace to make it again (only while every row is Proposed)."
            )
        check_edits(path)
        decided = [row["Row"] for row in read_view(path) if row["Status"] != "Proposed"]
        if decided:
            raise CalendarError(
                f"{path.name} cannot be replaced: rows {', '.join(decided)} are no longer "
                "Proposed."
            )
    cadence = load_cadence(settings.calendar_file, catalog)
    newest = _newest_list(settings.research_dir)
    if idea_numbers and newest is None:
        raise CalendarError("--idea needs a newsletter content list: run show content first.")

    picks = [Idea(topic.strip(), f"topic:{topic.strip()}") for topic in topics if topic.strip()]
    if newest is not None and idea_numbers:
        picks += _newsletter_ideas(newest, idea_numbers)
    picks += [_article_idea(settings.research_dir, article) for article in article_ids]
    planned = _planned_sources(settings.calendar_dir, skip=path)
    automatic = _newsletter_ideas(newest, []) if newest is not None else []
    automatic += [Idea(article.title.strip(), f"article:{article.article_id}")
                  for article in digest(settings, ARTICLE_DAYS)]
    fits = _pillar_fit(settings)
    if fits is not None:  # every topic fits a content pillar
        off = [idea.topic for idea in picks if not fits(idea.topic)]
        if off:
            raise CalendarError(
                f"Not on a content pillar (config/strategy.json): {'; '.join(off)}. Name the "
                "pillar's subject in the topic (e.g. Mittelstand, DSGVO, deepfake, KI-Fehler, "
                "automation) or pick another topic."
            )
        automatic = [idea for idea in automatic if fits(idea.topic)]
    candidates = iter(picks + [idea for idea in automatic if idea.source not in planned])

    days = week_days(label)
    rows: list[Row] = []
    empty: list[str] = []
    used_topics: set[str] = set()
    used_sources: set[str] = set()
    for slot in sorted(cadence.slots, key=lambda item: WEEKDAYS.index(item.weekday)):
        idea = _next_idea(candidates, used_topics, used_sources)
        if idea is None:
            empty.append(f"{slot.weekday.title()} {slot.deliverable}")
            continue
        used_topics.add(_topic_key(idea.topic))
        used_sources.add(idea.source)
        number = len(rows) + 1
        rows.append({
            "Row": str(number),
            "BG ID": "",
            "Planned date": days[WEEKDAYS.index(slot.weekday)].isoformat(),
            "Topic": idea.topic,
            "Research source": idea.source,
            "Platform": catalog.deliverables[slot.deliverable].platform or "",
            "Content type": slot.deliverable,
            "Status": "Proposed",
            "Version": "",
            "Package": "",
            "Content ID": f"{label}-{number:02d}",
            "Format": "",
        })
    if not rows:
        raise CalendarError(
            "No ideas to plan: give --topic values, run show content, or run "
            "`uv run ca research collect`."
        )
    if path.exists():
        check_edits(path)
    ids = [_row_item(row, label, catalog, replace=replace) for row in rows]
    for row, item_id in zip(rows, ids, strict=True):
        row["BG ID"] = item_id or ""
    roman = assign_roman(rows, label, catalog)
    write_calendar(path, rows, force=True)
    lines = [f"Calendar {label}: {path} ({len(rows)} rows, all Proposed; nothing generated)."]
    if roman is not None:
        lines.append(f"Roman's post this week: row {roman} (Format roman; one of the 4 Roman "
                     "formats is picked at stage 1).")
    if any(ids):
        lines.append("Items: " + ", ".join(
            f"row {row['Row']} {row['BG ID']}" for row in rows if row["BG ID"]))
    lines += service_lines(rows, settings.services_file)
    if newest is None:
        lines.append("No newsletter content list found; used topics and scraper articles.")
    if empty:
        lines.append(
            f"No idea left for: {', '.join(empty)}. Add --topic values and run again with "
            "--replace."
        )
    lines.append(f"Next: uv run ca calendar check --week {label}")
    return path, lines


def service_lines(rows: list[Row], services_file: Path) -> list[str]:
    """Phase D: the verified service each row's topic is about, or insight-only (free)."""
    try:
        services = load_services(services_file)
    except ServicesError as error:
        return [f"Service fit left out: {error}"]
    fits = [(row["Row"], service_fit([row["Topic"]], services)) for row in rows]
    lines = ["Service fit: " + "; ".join(f"row {number} {fit.label}" for number, fit in fits)]
    if any(fit.service_id is None for _, fit in fits):
        lines.append("Insight-only rows name no service and ask a question, no sales ask; "
                     "reject a row that fits neither a service nor a content pillar.")
    return lines


def check_calendar(path: Path, label: str, catalog: DeliverableCatalog,
                   research_dir: Path, plan_types: dict[str, str] | None = None) -> list[str]:
    """Every problem in the calendar file (an empty list: it is fine). `plan_types`: the
    plan-only content types and their platforms (C5-5); rows of one idea may share a topic."""
    rows = read_view(path)
    if not rows:
        return ["the calendar has no rows"]
    days = set(week_days(label))
    problems: list[str] = []
    topics: dict[str, tuple[str, str]] = {}
    for row in rows:
        where = f"row {row['Row'] or '?'}"
        try:
            day: date | None = date.fromisoformat(row["Planned date"])
        except ValueError:
            day = None
            problems.append(f"{where}: planned date must be YYYY-MM-DD")
        if day is not None and day not in days:
            problems.append(f"{where}: {day} is not in {label}")
        platform = row["Platform"]
        item = catalog.deliverables.get(row["Content type"])
        plan_platform = None if item else (plan_types or {}).get(row["Content type"])
        if plan_platform is not None:  # a plan-only type (C5-5)
            if platform != plan_platform:
                problems.append(f"{where}: {row['Content type']} is for {plan_platform}, not "
                                f"{platform}")
        elif platform not in PLATFORMS:
            problems.append(f'{where}: unknown platform "{platform}" (use {", ".join(PLATFORMS)})')
        if item is None and plan_platform is None:
            problems.append(
                f'{where}: unknown content type "{row["Content type"]}" (see `uv run ca content '
                "deliverables`)"
            )
        elif item is not None and item.platform and item.platform != platform:
            problems.append(
                f"{where}: {row['Content type']} is for {item.platform}, not {platform}"
            )
        if row["Status"] not in STATUSES:
            problems.append(f'{where}: status "{row["Status"]}" must be {", ".join(STATUSES)}')
        problems += [f"{where}: {problem}" for problem in _format_problems(row)]
        key = _topic_key(row["Topic"])
        idea = row["Research source"] if row["Research source"].startswith("idea:") else ""
        if not key:
            problems.append(f"{where}: no topic")
        elif key in topics and not (idea and topics[key][1] == idea):  # C5-13: one idea, rows
            problems.append(f"{where}: same topic as row {topics[key][0]}")  # per platform
        else:
            topics.setdefault(key, (row["Row"], idea))
        source_problem = _source_problem(row["Research source"], research_dir)
        if source_problem:
            problems.append(f"{where}: {source_problem}")
    return problems


def _format_problems(row: Row) -> list[str]:
    """The Format column: empty (picked at stage 1), "roman" (a LinkedIn or Facebook post) or a
    format of config/post_formats.json for the row's platform."""
    value = row.get("Format", "").strip()
    if not value:
        return []
    if value.lower() == ROMAN:
        return [] if row["Platform"] in ROMAN_PLATFORMS else [
            f"Format roman is for a LinkedIn or Facebook post, not {row['Platform']}"]
    try:
        found = load_formats().find(value)
    except FormatError:
        return []  # reported when the package is started
    if found is None:
        return [f'unknown Format "{value}" (config/post_formats.json, or roman)']
    if row["Platform"] not in found.platforms:
        return [f"Format {value} is for {'/'.join(found.platforms)}, not {row['Platform']}"]
    return []


def parse_rows(values: list[str], *, allow_all: bool) -> list[int] | None:
    """["1", "3,5"] -> [1, 3, 5]; ["all"] -> None (every Proposed row)."""
    words = [word for value in values for word in re.split(r"[\s,]+", value) if word]
    if allow_all and [word.lower() for word in words] == ["all"]:
        return None
    if not words or not all(word.isdigit() and int(word) > 0 for word in words):
        expected = '"all" or row numbers' if allow_all else "row numbers"
        raise CalendarError(f"Give {expected}, e.g. 1 3 5 (got: {' '.join(values)}).")
    return list(dict.fromkeys(int(word) for word in words))


def set_status(path: Path, numbers: list[int] | None, status: Decision, *,
               catalog: DeliverableCatalog | None = None, reason: str | None = None
               ) -> list[str]:
    """Approve or reject rows (numbers None: every Proposed row); all or nothing. Inside a `ca`
    command this goes through the registry (the idea gate of each row's item, D-12)."""
    if runtime.current() is not None and catalog is not None:
        return _registry_decision(path, numbers, status, catalog, reason)
    rows = read_calendar(path)
    if numbers is None:
        targets = [row for row in rows if row["Status"] == "Proposed"]
        if not targets:
            raise CalendarError(f"{path.name} has no Proposed rows.")
    else:
        by_number = {row["Row"]: row for row in rows}
        missing = [str(number) for number in numbers if str(number) not in by_number]
        if missing:
            raise CalendarError(f"{path.name} has no row {', '.join(missing)}.")
        targets = [by_number[str(number)] for number in numbers]
    blocked = [
        f"row {row['Row']} is {row['Status']}" for row in targets
        if row["Status"] != status and row["Status"] not in CHANGES_FROM[status]
    ]
    if blocked:
        raise CalendarError(
            f"Nothing changed: {'; '.join(blocked)} (a Generated row cannot change)."
        )
    for row in targets:
        row["Status"] = status
    write_calendar(path, rows)
    return [f"{path.name}: rows {', '.join(row['Row'] for row in targets)} are {status}."]


def _registry_decision(path: Path, numbers: list[int] | None, status: Decision,
                       catalog: DeliverableCatalog, reason: str | None) -> list[str]:
    scope = runtime.current()
    assert scope is not None
    check_edits(path)
    label = _label_of(path)
    rows = read_calendar(path)
    for row in rows:  # rows from before the registry become items first
        row["BG ID"] = row["BG ID"] or (_row_item(row, label, catalog) or "")
    rows = [_view_row(scope.conn, row) for row in rows]
    if numbers is None:
        targets = [row for row in rows if row["Status"] == "Proposed"]
        if not targets:
            raise CalendarError(f"{path.name} has no Proposed rows.")
    else:
        by_number = {row["Row"]: row for row in rows}
        missing = [str(number) for number in numbers if str(number) not in by_number]
        if missing:
            raise CalendarError(f"{path.name} has no row {', '.join(missing)}.")
        targets = [by_number[str(number)] for number in numbers]
    action: Literal["approve", "reject"] = "approve" if status == "Approved" else "reject"
    todo = [row for row in targets if row["Status"] != status]
    blocked = [
        f"row {row['Row']} ({row['BG ID']}) is {row['Status']}" for row in todo
        if not gate_open(get_item(scope.conn, row["BG ID"]), action, "idea")
    ]
    if blocked:
        raise CalendarError(f"Nothing changed: {'; '.join(blocked)} (decisions on a generated "
                            "row move to the review gate: ca item approve|reject BG-x).")
    lines = []
    for row in todo:
        if action == "approve":
            change = approve(scope.conn, row["BG ID"], gate="idea", command=scope.command)
        else:
            text = reason or f"rejected in calendar {label} (no reason given)"
            change = reject(scope.conn, row["BG ID"], text, gate="idea", command=scope.command)
        lines.append(f"{path.name}: row {row['Row']} {change.line()}")
    lines += [f"{path.name}: row {row['Row']} {row['BG ID']} is already {status}."
              for row in targets if row not in todo]
    write_calendar(path, rows, force=True)
    return lines


def sync_calendar_view(path: Path, *, discard: bool = False, take: bool = False) -> list[str]:
    """`ca calendar sync`: rewrite the view from the registry. A hand-edited file needs a choice:
    discard the edits, or import the Topic and Planned date edits (logged)."""
    scope = runtime.current()
    if scope is None:
        raise CalendarError("calendar sync needs the registry.")
    diff = edited_diff(scope.conn, path)
    rows = read_calendar(path)
    lines: list[str] = []
    if diff and not (discard or take):
        raise CalendarEdited(path, _label_of(path), diff)
    if diff and discard:
        before = last_written(scope.conn, path) or ""
        rows = [{column: row.get(column, "") or "" for column in COLUMNS}
                for row in csv.DictReader(io.StringIO(before))]
        lines.append(f"{path.name}: hand edits discarded.")
    elif diff and take:
        for row in rows:
            if not row["BG ID"]:
                continue
            item = get_item(scope.conn, row["BG ID"])
            if row["Topic"] and row["Topic"] != item.topic:
                set_title(scope.conn, item.id, row["Topic"], actor="user", command=scope.command)
                lines.append(f"{item.id}: topic imported: \"{row['Topic']}\"")
            planned = item.planned_date.isoformat() if item.planned_date else ""
            if row["Planned date"] and row["Planned date"] != planned:
                try:
                    day = date.fromisoformat(row["Planned date"])
                except ValueError:
                    lines.append(f"{item.id}: planned date \"{row['Planned date']}\" is not "
                                 "YYYY-MM-DD; not imported.")
                    continue
                set_planned_date(scope.conn, item.id, day, actor="user", command=scope.command)
                lines.append(f"{item.id}: planned date imported: {day}")
            if row["Status"] != view_status(item.idea_status, item.generation_status):
                lines.append(f"{item.id}: Status edit \"{row['Status']}\" not imported "
                             "(approve or reject instead).")
        lines.append(f"{path.name}: edits imported where allowed.")
    write_calendar(path, rows, force=True)
    lines.append(f"{path.name}: in sync with the registry.")
    return lines


def generate_rows(
    settings: Settings,
    catalog: DeliverableCatalog,
    label: str,
    *,
    build: bool,
    after_build: Callable[[Path], list[str]] | None = None,
    costs: list[CostLine] | None = None,
) -> tuple[list[str], list[str]]:
    """Stage 1 and the combined dry run, or (build) the build of every ready row.

    after_build runs for each package the build finished (the Drive sync); its lines are
    shown under the row. Returns the lines for Codex and the failed rows (reported at the
    end, never retried). Inside a `ca` command each Approved row is a registry item (created
    from the row if needed) and the dry run's cost lines are added to `costs`.
    """
    path = calendar_path(settings, label)
    plan_types = plan_only_types(settings.calendar_file)
    problems = check_calendar(path, label, catalog, settings.research_dir, plan_types)
    if problems:
        raise CalendarError(
            f"{path.name} has {len(problems)} problem(s): run `uv run ca calendar check --week "
            f"{label}` and fix them first."
        )
    check_edits(path)
    rows = read_view(path)
    approved = [row for row in rows if row["Status"] in APPROVED_STATES]
    if not approved:
        raise CalendarError(f"{path.name} has no Approved rows: approve rows first.")
    lines: list[str] = []
    failed: list[str] = []
    total = 0.0
    ready = 0
    for row in approved:
        where = f"Row {row['Row']} ({row['Planned date']}, {row['Content type']})"
        if row["Content type"] in plan_types and row["Content type"] not in catalog.deliverables:
            lines.append(f"{where} {row['BG ID']}: {NOT_PRODUCIBLE}; skipped.")
            continue
        item_id = _row_item(row, label, catalog)
        if item_id:
            row["BG ID"] = item_id
            where += f" {item_id}"
        if not row["Package"]:
            if build:
                lines.append(f"{where}: no package yet; run generate without --build first.")
                continue
            try:
                topic, idea = _row_research(row, settings.research_dir)
                content_id = row["Content ID"] or f"{label}-{int(row['Row']):02d}"
                started = start_package(topic, [row["Content type"]], catalog, settings,
                                        idea=idea, content_id=content_id,
                                        format_override=row.get("Format") or None)
            except (OSError, ValueError) as error:
                failed.append(f"{where}: stage 1 failed: {error}")
                continue
            row["Package"] = started.folder.as_posix()
            row["Content ID"] = content_id
            write_calendar(path, rows)
            _save_row_link(started.folder, row)
            _row_item(row, label, catalog)  # links the item to its new package
            lines.append(f"{where}: package started, {row['Package']}")
            lines += [f"  {line}" for line in started.lines]
            continue
        folder = Path(row["Package"])
        _save_row_link(folder, row)
        state, detail = _package_state(folder)
        if state == "done":
            row["Status"] = "Generated"
            write_calendar(path, rows)
            runtime.report_part(item_id, "done")
            lines.append(f"{where}: Generated ({folder})")
        elif state == "failed":
            failed.append(
                f"{where}: failed earlier ({detail}); not retried. Only if the user agrees to "
                f'the cost: uv run ca content build "{folder}"'
            )
        elif state == "review":
            lines.append(
                f"{where}: waits for the person or set check; continue with the make-content "
                f'checks and uv run ca content build "{folder}"'
            )
        elif state == "upload":
            lines.append(f"{where}: waits for the Drive upload: upload each entry of "
                         f"{folder / MANIFEST_FILE} with the Drive plugin, then uv run ca drive "
                         f'record "{folder}" --results <results.json>')
        elif state == "brief":
            lines.append(f"{where}: write content.md and brief.json in {folder}")
        elif state == "missing":
            failed.append(f"{where}: package folder {folder} not found")
        else:  # ready: a valid package with brief.json
            try:
                result = build_package(folder, settings, dry_run=not build)
            except (OSError, ValueError) as error:
                failed.append(f"{where}: {error}")
                continue
            ready += 1
            total += result.estimated_usd or 0.0
            if costs is not None and not build:
                costs += result.cost_lines
            cost = f"about ${result.estimated_usd:.3f}" if not build else "built"
            lines.append(f"{where}: {cost}")
            lines += [f"  {line}" for line in result.lines
                      if not line.startswith(("DRY RUN:", "Estimated image cost:"))]
            if build and result.package is not None:
                lines.append(f"  Status: {result.package.status}")
                if result.package.status == DONE_STATUS and settings.storage_provider == "plugin":
                    if after_build is not None:  # writes upload_manifest.json
                        lines += [f"  {line}" for line in after_build(folder)]
                    lines.append("  Row turns Generated once the Drive plugin uploaded it "
                                 "(ca drive record).")
                elif result.package.status == DONE_STATUS:
                    row["Status"] = "Generated"
                    write_calendar(path, rows)
                    lines.append("  Row is Generated.")
                    if after_build is not None:
                        lines += [f"  {line}" for line in after_build(folder)]
                elif failure := _failed_part(result.package):
                    failed.append(f"{where}: {failure}; not retried")
    if not build and ready:
        lines.append(
            f"Combined dry run: {ready} row(s), about ${total:.3f} in total (per row: its "
            "providers; the Instagram carousel via OpenRouter). Nothing has been made or spent. "
            f"Only after the user says ok: uv run ca calendar generate --week {label} --build "
            "--authorize <the dry run ID below>"
        )
    if build and ready:
        lines.append(
            "Person and set checks: follow make-content steps 5-6 for each package that "
            "stopped, then run uv run ca content build \"<folder>\" (never for a failed row "
            "without the user's yes)."
        )
    return lines, failed


def _row_item(row: Row, label: str, catalog: DeliverableCatalog, *,
              replace: bool = False) -> str | None:
    """The row's BG ID inside a `ca` command (the row is registered if it was not yet)."""
    scope = runtime.current()
    spec = catalog.deliverables.get(row["Content type"])
    if scope is None or spec is None:
        return None
    item, _ = register_row(scope.conn, row, label, kind=spec.item_kind, platform=spec.platform,
                           command=scope.command, replace=replace)
    return item.id


def ready_cost_lines(settings: Settings, catalog: DeliverableCatalog, label: str
                     ) -> list[CostLine]:
    """The cost lines of every Approved row whose package is ready to build (no stage 1, no
    build): what `generate --build --authorize` checks against the saved dry run."""
    path = calendar_path(settings, label)
    lines: list[CostLine] = []
    for row in read_view(path):
        if row["Status"] not in APPROVED_STATES or not row["Package"]:
            continue
        folder = Path(row["Package"])
        if _package_state(folder)[0] != "ready":
            continue
        _row_item(row, label, catalog)
        try:
            lines += build_package(folder, settings, dry_run=True).cost_lines
        except (OSError, ValueError):
            continue
    return lines


def mark_generated(settings: Settings, folder: Path) -> list[Path]:
    """A finished package's Approved rows become Generated (any week); the changed calendar
    files, for their Drive copies. The caller checks that the package is finished."""
    target = folder.resolve()
    changed: list[Path] = []
    for path in sorted(settings.calendar_dir.glob("*.csv")):
        try:
            rows = read_view(path)
        except CalendarError:
            continue
        hits = [
            row for row in rows
            if row["Package"] and row["Status"] in APPROVED_STATES
            and Path(row["Package"]).resolve() == target
        ]
        for row in hits:
            row["Status"] = "Generated"
        if hits:
            try:
                write_calendar(path, rows)
            except CalendarEdited:
                continue  # hand-edited: left as it is; `ca calendar sync` shows the edits
            changed.append(path)
    return changed


def calendar_packages(settings: Settings) -> list[Path]:
    """Every package folder named in a calendar (any week), oldest week first."""
    folders: list[Path] = []
    for path in sorted(settings.calendar_dir.glob("*.csv")):
        try:
            folders += [Path(row["Package"]) for row in read_calendar(path) if row["Package"]]
        except CalendarError:
            continue
    return list(dict.fromkeys(folders))


def _save_row_link(folder: Path, row: Row) -> None:
    """The row's Content ID (Drive folder name) and Research source in package.json."""
    content_id, source = row["Content ID"] or None, row["Research source"] or None
    try:
        package = load_package(folder)
    except (OSError, ValueError):
        return  # a missing package is reported by _package_state
    if (package.content_id, package.research_source) != (content_id, source):
        package.content_id, package.research_source = content_id, source
        save_package(folder, package)


def _row_research(row: Row, research_dir: Path) -> tuple[str, ResearchIdea | None]:
    """The topic to start with, and the newsletter idea when the row comes from one."""
    source = _SOURCE.fullmatch(row["Research source"])
    if source is None or source[1] != "newsletter":
        return row["Topic"], None  # topic and article rows: the scraper ranks by the topic
    found = _NEWSLETTER.fullmatch(source[2].strip())
    if found is None:
        raise CalendarError(f"research source must be {SOURCE_HELP}")
    path = research_dir / NEWSLETTER_DIR / f"{found[1]}{LIST_SUFFIX}"
    return row["Topic"], load_idea(path, int(found[2]))


def _package_state(folder: Path) -> tuple[str, str]:
    """missing, done, upload (STORAGE_PROVIDER=plugin: the manifest waits), failed (with the
    error), review, brief (no brief.json yet) or ready."""
    try:
        package = ContentPackage.model_validate_json(
            (folder / PACKAGE_FILE).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return "missing", ""
    if package.items and package.status == DONE_STATUS:
        return "done", ""
    if package.status == PENDING_STATUS:  # built; the Drive plugin uploads it
        return "upload", ""
    failure = _failed_part(package)
    if failure:
        return "failed", failure
    if any(item.status == "review" for item in package.items.values()):
        return "review", ""
    if not (folder / BRIEF_FILE).is_file():
        return "brief", ""
    return "ready", ""


def _failed_part(package: ContentPackage) -> str:
    """The first failed part and its error ("" when nothing failed)."""
    for kind, item in package.items.items():
        if item.status == "failed":
            return f"{kind} failed: {item.error or 'see its job folder'}"
    return ""


def show_lines(rows: list[Row], notes: dict[str, str] | None = None) -> list[str]:
    """A Markdown table for Codex to show; `notes` (by BG ID) go after the Status."""
    columns = ("Row", "BG ID", "Planned date", "Platform", "Content type", "Status", "Topic",
               "Research source")
    lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
    for row in rows:
        cells = [(row.get(column) or "—").replace("|", "/") for column in columns]
        cells[2] = _with_weekday(cells[2])
        if notes and row.get("BG ID") in notes:
            cells[5] += f" ({notes[row['BG ID']]})"
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def _with_weekday(text: str) -> str:
    try:
        return f"{text} {date.fromisoformat(text):%a}"
    except ValueError:
        return text


def _topic_key(topic: str) -> str:
    return " ".join(topic.casefold().split())


def _next_idea(candidates: Iterator[Idea], topics: set[str], sources: set[str]) -> Idea | None:
    return next(
        (idea for idea in candidates
         if idea.topic and _topic_key(idea.topic) not in topics and idea.source not in sources),
        None,
    )


def _newest_list(research_dir: Path) -> Path | None:
    files = sorted((research_dir / NEWSLETTER_DIR).glob(f"*{LIST_SUFFIX}"))
    return files[-1] if files else None


def _newsletter_ideas(path: Path, numbers: list[int]) -> list[Idea]:
    """The picked ideas of a content list, in the order given (no numbers: all of them)."""
    try:
        data = ResearchFile.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        raise CalendarError(f"{path.name} could not be read: run show content again.") from None
    day = path.name.removesuffix(LIST_SUFFIX)
    by_number = {idea.number: idea for idea in data.ideas}
    missing = [str(number) for number in numbers if number not in by_number]
    if missing:
        raise CalendarError(
            f"{path.name} has no idea {', '.join(missing)} (it has "
            f"{', '.join(str(number) for number in by_number)})."
        )
    chosen = [by_number[number] for number in numbers] if numbers else data.ideas
    return [Idea(idea.title.strip(), f"newsletter:{day}#{idea.number}") for idea in chosen]


def _article_idea(research_dir: Path, wanted: str) -> Idea:
    article = find_article(research_dir, wanted.strip())
    if article is None:
        raise CalendarError(
            f"Article {wanted} not found: pick an ID from `uv run ca research digest`."
        )
    return Idea(article.title.strip(), f"article:{article.article_id}")


def _planned_sources(calendar_dir: Path, *, skip: Path) -> set[str]:
    """Research sources already planned in other weeks (unreadable files are ignored)."""
    sources: set[str] = set()
    for path in calendar_dir.glob("*.csv"):
        if path == skip:
            continue
        try:
            sources.update(row["Research source"] for row in read_calendar(path))
        except CalendarError:
            continue
    return sources


def _source_problem(source: str, research_dir: Path) -> str | None:
    match = _SOURCE.fullmatch(source)
    if match is None:
        return f"research source must be {SOURCE_HELP}"
    kind, value = match[1], match[2].strip()
    if kind == "idea":
        scope = runtime.current()
        if not re.fullmatch(r"BG-\d+", value.upper()):
            return f"research source must be {SOURCE_HELP}"
        if scope is not None:
            try:
                if get_item(scope.conn, value).kind != "idea":
                    return f"{value} is not an idea"
            except RegistryError:
                return f"idea {value} not found"
    if kind == "newsletter":
        found = _NEWSLETTER.fullmatch(value)
        if found is None:
            return f"research source must be {SOURCE_HELP}"
        if not (research_dir / NEWSLETTER_DIR / f"{found[1]}{LIST_SUFFIX}").is_file():
            return f"newsletter list {found[1]}{LIST_SUFFIX} not found"
    if kind == "article" and find_article(research_dir, value) is None:
        return f"article {value} not found (see `uv run ca research digest`)"
    return None
