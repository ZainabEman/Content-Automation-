"""`ca report month [YYYY-MM]` (Phase 10 Step 1, UC-19): the month's recorded final states
against the targets, written to `outputs/reports/<YYYY-MM>.md`.

Only final states recorded in the registry count, in the month they were recorded: the last
status_changed event to review approved (YouTube finals, clips, graphics) or to production
final (podcasts), and published_at for a publication. Mock uploads and mock results are listed
separately and never counted. Targets: config/production.json (`targetsPerMonth.youtube`,
`reportTargets`); podcasts against the number scheduled (planned) that month.
"""

import json
import re
import sqlite3
from calendar import monthrange
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from content_automation.content.production import production_config
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.registry.db import RegistryError
from content_automation.registry.items import Item, get_item, list_items

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
GRAPHIC_KINDS = ("post", "carousel", "graphic", "ad")
DEFAULT_TARGETS: dict[str, Any] = {"clips": [32, 40], "graphics": [30, 60],
                                   "reviewedPublishedPercent": 100}


@dataclass(frozen=True)
class Row:
    label: str
    count: int
    target: str
    met: bool
    items: list[str]


@dataclass
class MonthReport:
    month: str
    rows: list[Row]
    published: dict[str, list[str]]  # platform -> "BG-x <url>"
    reviewed: tuple[int, int]  # published items with an approved review, published items
    reviewed_target: int
    mock: list[str] = field(default_factory=list)  # "BG-x kind: why" (never counted)
    path: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    def lines(self) -> list[str]:
        lines = [f"{row.label}: {row.count} of {row.target}" + (" — target met" if row.met
                                                                 else "") for row in self.rows]
        for platform, posts in sorted(self.published.items()):
            lines.append(f"Published on {platform}: {len(posts)} ({', '.join(posts)})")
        if not self.published:
            lines.append("Published: none")
        lines.append(self.reviewed_line())
        lines.append(f"Mock (not counted): {len(self.mock)}" + (
            f" ({'; '.join(self.mock)})" if self.mock else ""))
        return lines

    def reviewed_line(self) -> str:
        approved, total = self.reviewed
        share = f"{approved} of {total} ({approved * 100 // total}%)" if total else "none published"
        return f"Published with an approved review: {share}, target {self.reviewed_target}%"

    def markdown(self) -> str:
        table = ["| What | Count | Target | Met |", "|---|---|---|---|"]
        table += [f"| {row.label} | {row.count} | {row.target} | {'yes' if row.met else 'no'} |"
                  for row in self.rows]
        published = [f"- {platform}: {len(posts)} — {', '.join(posts)}"
                     for platform, posts in sorted(self.published.items())] or ["- none"]
        mock = [f"- {line}" for line in self.mock] or ["- none"]
        counted = [f"- {row.label}: {', '.join(row.items)}" for row in self.rows if row.items]
        return "\n".join([
            f"# Monthly report {self.month}", "",
            "Only final states recorded in the registry, in the month they were recorded. Mock "
            "uploads and mock results are listed separately and never counted.", "",
            *table, "", "## Published per platform", "", *published, "",
            "## Review before publishing", "", self.reviewed_line(), "",
            "## Counted items", "", *(counted or ["- none"]), "",
            "## Mock (not counted)", "", *mock, "",
        ])


def check_month(month: str | None) -> str:
    if month is None:
        return datetime.now(UTC).strftime("%Y-%m")
    if not MONTH.match(month):
        raise RegistryError(f'A month is YYYY-MM (e.g. 2026-11), not "{month}".')
    return month


def _reached(conn: sqlite3.Connection, dimension: str, target: str) -> dict[str, str]:
    """item -> when it last moved to `target` (item-level status_changed events)."""
    found: dict[str, str] = {}
    rows = conn.execute("SELECT item_id, created_at, details FROM events WHERE type = "
                        "'status_changed' AND item_id IS NOT NULL ORDER BY id")
    for row in rows:
        details = json.loads(row["details"])
        if (details.get("dimension") == dimension and details.get("to") == target
                and "platform" not in details):
            found[str(row["item_id"])] = str(row["created_at"])
    return found


def _mock(conn: sqlite3.Connection, item: Item) -> str | None:
    if item.upload_provider == "mock":
        return "mock upload"
    row = conn.execute("SELECT 1 FROM jobs WHERE item_id = ? AND provider = 'mock' AND "
                       "status = 'succeeded' LIMIT 1", (item.id,)).fetchone()
    return "mock result" if row else None


def _range(value: Any) -> tuple[int, int]:
    if isinstance(value, list) and len(value) == 2:
        return int(value[0]), int(value[1])
    return int(value), int(value)


def _row(label: str, items: list[Item], target: tuple[int, int]) -> Row:
    low, high = target
    shown = f"{low}–{high}" if low != high else str(low)
    return Row(label, len(items), shown, len(items) >= low, [item.id for item in items])


def month_report(conn: sqlite3.Connection, settings: Settings, month: str) -> MonthReport:
    year, number = (int(part) for part in month.split("-"))
    first, last = date(year, number, 1), date(year, number, monthrange(year, number)[1])
    config = production_config(settings)
    targets = {**DEFAULT_TARGETS, **config.get("reportTargets", {})}
    approved_at = _reached(conn, "review", "approved")
    final_at = _reached(conn, "production", "final")
    mock: dict[str, str] = {}

    def counted(item: Item, when: dict[str, str]) -> bool:
        if not when.get(item.id, "").startswith(month):
            return False
        reason = _mock(conn, item)
        if reason is not None:
            mock[item.id] = f"{item.id} {item.kind}: {reason}"
            return False
        return True

    items = list_items(conn)
    approved = [item for item in items if item.review_status == "approved"
                and counted(item, approved_at)]
    youtube = [item for item in approved
               if item.kind == "youtube" and item.production_status == "final"]
    clips = [item for item in approved if item.kind == "short" and item.parent_id is not None
             and item.idea_status == "approved"]
    graphics = [item for item in approved if item.kind in GRAPHIC_KINDS]
    podcasts = [item for item in items if item.kind == "podcast"
                and item.production_status == "final" and counted(item, final_at)]
    scheduled = len(list_items(conn, kind="podcast", planned_from=first, planned_to=last))
    youtube_target = int(config.get("targetsPerMonth", {}).get("youtube", 8))
    rows = [
        _row("YouTube finals (review approved)", youtube, (youtube_target, youtube_target)),
        _row("Clips selected and approved", clips, _range(targets["clips"])),
        _row("Graphics approved (posts, carousels, ads)", graphics, _range(targets["graphics"])),
        _row("Podcast finals (of those scheduled)", podcasts, (scheduled, scheduled)),
    ]
    published: dict[str, list[str]] = {}
    published_items: set[str] = set()
    for row in conn.execute("SELECT item_id, platform, url, published_at FROM publications "
                            "WHERE status = 'published' ORDER BY item_id, platform"):
        item = get_item(conn, str(row["item_id"]))
        if not counted(item, {item.id: str(row["published_at"] or "")}):
            continue
        published.setdefault(str(row["platform"]), []).append(f"{item.id} {row['url']}")
        published_items.add(item.id)
    reviewed = sum(get_item(conn, item_id).review_status == "approved"
                   for item_id in published_items)
    return MonthReport(month, rows, published, (reviewed, len(published_items)),
                       int(targets["reviewedPublishedPercent"]), sorted(mock.values()))


def write_report(conn: sqlite3.Connection, settings: Settings, month: str) -> MonthReport:
    report = month_report(conn, settings, month)
    path = Path(settings.reports_dir) / f"{month}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, report.markdown())
    report.path = path.as_posix()
    return report
