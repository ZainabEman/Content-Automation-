"""`ca calendar plan --week|--month` and `ca calendar show --month` (Phase 5 P5-D12).

The plan slots of config/calendar.json are filled from **approved ideas**, best score first while
keeping the strategy's pillar balance. One idea fills a slot: one row per platform (C5-13), each a
child item of the idea whose idea gate starts approved (inherited, logged with the idea's ID).
A derived type (a short) is planned from its parent video's row, `bufferDays` later; it shows
"blocked: waiting for BG-x" while its date is before the parent's date + buffer. Month rows go
into each week's CSV (C5-12); slots a week file already fills (same date and type) are kept.
"""

import calendar as month_calendar
import re
import sqlite3
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

from content_automation.content.calendar import (
    CalendarError,
    Row,
    assign_roman,
    calendar_path,
    check_edits,
    read_view,
    week_days,
    week_label,
    write_calendar,
)
from content_automation.content.deliverables import DeliverableCatalog
from content_automation.content.plan_config import (
    NOT_PRODUCIBLE,
    WEEKDAYS,
    Plan,
    PlanConfigError,
    load_plan,
)
from content_automation.core.config import Settings
from content_automation.registry import runtime
from content_automation.registry.db import transaction
from content_automation.registry.ideas import IdeaDetails, get_details, list_ideas
from content_automation.registry.items import Item, children, get_item
from content_automation.registry.link import plan_item
from content_automation.registry.strategy import Strategy

_MONTH = re.compile(r"(\d{4})-(\d{1,2})")


def month_label(text: str, today: date | None = None) -> str:
    """"this", "next" or "2026-11" -> "2026-11"."""
    value = text.strip().lower()
    day = today or date.today()
    if value in ("this", "next"):
        year, month = day.year, day.month + (value == "next")
        if month == 13:
            year, month = year + 1, 1
        return f"{year}-{month:02d}"
    match = _MONTH.fullmatch(value)
    if match is not None and 1 <= int(match[2]) <= 12:
        return f"{int(match[1])}-{int(match[2]):02d}"
    raise CalendarError(f'"{text}" is not a month: use this, next or e.g. 2026-11.')


def month_days(label: str) -> list[date]:
    year, month = (int(part) for part in label.split("-"))
    return [date(year, month, day) for day in range(1, month_calendar.monthrange(year, month)[1]
                                                     + 1)]


def week_of(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def period(week: str | None, month: str | None) -> tuple[str, list[date]]:
    """The label and days of --week or --month (default: next week)."""
    if week and month:
        raise CalendarError("Give --week or --month, not both.")
    if month:
        label = month_label(month)
        return label, month_days(label)
    label = week_label(week or "next")
    return label, week_days(label)


def _plan(settings: Settings, catalog: DeliverableCatalog) -> Plan:
    try:
        plan = load_plan(settings.calendar_file, catalog)
    except PlanConfigError as error:
        raise CalendarError(str(error)) from None
    if plan is None:
        raise CalendarError(
            f"{settings.calendar_file.name} has no plan block: add one (see docs/phases/"
            "PHASE-5-PRD.md, P5-D12) or use `ca calendar new` for the weekly cadence."
        )
    return plan


def _approved_ideas(conn: sqlite3.Connection) -> list[tuple[Item, IdeaDetails]]:
    """Approved ideas not planned yet (no children), best score first."""
    waiting = [(item, details) for item, details in list_ideas(conn)
               if item.idea_status == "approved" and not details.duplicate_of
               and not children(conn, item.id)]
    return sorted(waiting, key=lambda pair: -(pair[1].score or 0))


def _pick(ideas: list[tuple[Item, IdeaDetails]], counts: dict[str, int],
          shares: dict[str, float]) -> tuple[Item, IdeaDetails] | None:
    """The idea whose pillar is furthest below its share, then the best score."""
    if not ideas:
        return None
    total = sum(counts.values()) + 1

    def rank(pair: tuple[Item, IdeaDetails]) -> tuple[float, int]:
        pillar = pair[1].pillar or ""
        deficit = shares[pillar] * total - counts.get(pillar, 0) if pillar in shares else -total
        return deficit, pair[1].score or 0

    best = max(ideas, key=rank)
    ideas.remove(best)
    return best


def _next_number(rows: list[Row]) -> int:
    return max((int(row["Row"]) for row in rows if row["Row"].isdigit()), default=0) + 1


def plan_calendar(settings: Settings, catalog: DeliverableCatalog, strategy: Strategy,
                  label: str, days: list[date]) -> tuple[list[Path], list[str]]:
    """Fill the plan slots of `days` from approved ideas; returns the week files and the lines
    for Codex."""
    scope = runtime.current()
    if scope is None:
        raise CalendarError("calendar plan needs the registry.")
    conn, plan = scope.conn, _plan(settings, catalog)
    weeks: dict[str, list[Row]] = {}

    def week_rows(week: str) -> list[Row]:
        if week not in weeks:
            path = calendar_path(settings, week)
            if path.exists():
                check_edits(path)
            weeks[week] = read_view(path) if path.exists() else []
        return weeks[week]

    for day in days:
        week_rows(week_of(day))
    # A rejected row no longer owns its slot; let an approved idea fill that date and type.
    occupied = {(row["Planned date"], row["Content type"])
                for rows in weeks.values() for row in rows if row["Status"] != "Rejected"}
    ideas = _approved_ideas(conn)
    used = len(ideas)
    shares = {pillar.key: pillar.target_share for pillar in strategy.pillars}
    counts: dict[str, int] = {}
    empty: list[str] = []
    planned: list[str] = []
    with transaction(conn):
        for day in days:
            for slot in plan.slots:
                if slot.weekday != WEEKDAYS[day.weekday()] or (
                        day.isocalendar().week % slot.every_weeks):
                    continue
                types = [kind for kind in slot.types
                         if plan.enabled(kind) and (day.isoformat(), kind) not in occupied]
                if not types:
                    continue
                picked = _pick(ideas, counts, shares)
                if picked is None:
                    empty.append(f"{day} {'+'.join(types)}")
                    continue
                idea, details = picked
                counts[details.pillar or ""] = counts.get(details.pillar or "", 0) + 1
                for content_type in types:
                    parent = _add_row(conn, catalog, plan, week_rows, idea, idea.id, day,
                                      content_type, scope.command)
                    occupied.add((day.isoformat(), content_type))
                    planned.append(parent.id)
                    for derived in plan.derived_from(content_type):
                        when = day + timedelta(days=plan.types[derived].buffer_days)
                        child = _add_row(conn, catalog, plan, week_rows, idea, parent.id, when,
                                         derived, scope.command)
                        planned.append(child.id)
    for week, rows in weeks.items():
        if rows:
            assign_roman(rows, week, catalog)  # Roman exactly once a week
            write_calendar(calendar_path(settings, week), rows)
    used -= len(ideas)
    lines = [f"Plan {label}: {len(planned)} new row(s) from {used} approved idea(s); each row's "
             "idea approval is inherited from its idea (logged). Nothing generated."]
    if empty:
        lines.append(f"No approved idea left for {len(empty)} slot(s): {', '.join(empty[:6])}"
                     + (" …" if len(empty) > 6 else "") + ". Review and approve more ideas, "
                     "then plan again (filled slots are kept).")
    rows = period_rows(settings, days)
    lines += target_lines(rows, plan, days) + pillar_lines(conn, rows, strategy, plan)
    plan_only = sorted({row["Content type"] for row in rows if row["Content type"] in plan.types})
    if plan_only:
        lines.append(f"Planned only ({NOT_PRODUCIBLE}): {', '.join(plan_only)}.")
    return [calendar_path(settings, week) for week, rows in weeks.items() if rows], lines


def _add_row(conn: sqlite3.Connection, catalog: DeliverableCatalog, plan: Plan,
             week_rows: Callable[[str], list[Row]], idea: Item, parent_id: str, day: date,
             content_type: str, command: str | None) -> Item:
    week = week_of(day)
    rows = week_rows(week)
    number = _next_number(rows)
    platform = plan.platform_of(content_type, catalog)
    row: Row = {
        "Row": str(number), "BG ID": "", "Planned date": day.isoformat(), "Topic": idea.title,
        "Research source": f"idea:{idea.id}", "Platform": platform,
        "Content type": content_type, "Status": "Approved", "Version": "", "Package": "",
        "Content ID": f"{week}-{number:02d}",
    }
    item = plan_item(conn, row, week, kind=plan.kind_of(content_type, catalog),
                     platform=platform, parent_id=parent_id, idea_id=idea.id, command=command)
    row["BG ID"] = item.id
    rows.append(row)
    return item


def period_rows(settings: Settings, days: list[date], *, numbered: bool = False) -> list[Row]:
    """The rows of `days` from each week's CSV (as the registry sees them); `numbered` prefixes
    Row with the week ("2026-W45#3") for the month view."""
    wanted = {day.isoformat() for day in days}
    rows: list[Row] = []
    for week in sorted({week_of(day) for day in days}):
        path = calendar_path(settings, week)
        if not path.exists():
            continue
        check_edits(path)
        for row in read_view(path):
            if row["Planned date"] in wanted:
                rows.append({**row, "Row": f"{week}#{row['Row']}"} if numbered else row)
    return rows


def target_lines(rows: list[Row], plan: Plan, days: list[date]) -> list[str]:
    """The targets the rows miss (rejected rows do not count)."""
    live = [row for row in rows if row["Status"] != "Rejected"]
    targets = plan.targets
    misses: list[str] = []
    if targets.post_types:
        for day in days:
            posts = sum(row["Planned date"] == day.isoformat()
                        and row["Content type"] in targets.post_types for row in live)
            if not targets.posts_per_day_min <= posts <= targets.posts_per_day_max:
                misses.append(f"{day}: {posts} post(s) (target {targets.posts_per_day_min}-"
                              f"{targets.posts_per_day_max})")
    for week in sorted({week_of(day) for day in days}):
        if not set(week_days(week)) <= set(days):
            continue  # a partly covered week is checked with its other month
        for content_type, wanted in targets.per_week.items():
            found = sum(week_of(date.fromisoformat(row["Planned date"])) == week
                        and row["Content type"] == content_type for row in live)
            if found < wanted:
                misses.append(f"{week}: {found} {content_type} (target {wanted})")
    if not misses:
        return ["Targets met."]
    return [f"Targets missed ({len(misses)}): " + "; ".join(misses[:8])
            + (" …" if len(misses) > 8 else "")]


def pillar_lines(conn: sqlite3.Connection, rows: list[Row], strategy: Strategy,
                 plan: Plan) -> list[str]:
    """The pillar shares of the ideas planned in these rows against config/strategy.json."""
    ideas = {row["Research source"].removeprefix("idea:") for row in rows
             if row["Research source"].startswith("idea:") and row["Status"] != "Rejected"}
    if not ideas:
        return []
    pillars = [get_details(conn, idea).pillar or "" for idea in ideas]
    parts: list[str] = []
    off: list[str] = []
    for pillar in strategy.pillars:
        share = pillars.count(pillar.key) / len(pillars)
        parts.append(f"{pillar.key} {share:.0%} (target {pillar.target_share:.0%})")
        if abs(share - pillar.target_share) > plan.pillar_tolerance:
            off.append(pillar.key)
    verdict = (f"outside ±{plan.pillar_tolerance:.0%}: {', '.join(off)}" if off
               else f"within ±{plan.pillar_tolerance:.0%}")
    return [f"Pillar balance ({len(ideas)} ideas, {verdict}): {', '.join(parts)}."]


def blocked_notes(conn: sqlite3.Connection, rows: list[Row], plan: Plan | None
                  ) -> dict[str, str]:
    """BG ID -> "blocked: waiting for BG-x" for derived rows (shorts) whose parent is not
    planned at least `bufferDays` before them, or was rejected."""
    notes: dict[str, str] = {}
    for row in rows:
        spec = plan.types.get(row["Content type"]) if plan else None
        if spec is None or spec.parent is None or not row["BG ID"]:
            continue
        item = get_item(conn, row["BG ID"])
        if item.parent_id is None:
            continue
        parent = get_item(conn, item.parent_id)
        ready = (parent.planned_date is not None and item.planned_date is not None
                 and item.planned_date >= parent.planned_date + timedelta(days=spec.buffer_days)
                 and parent.idea_status != "rejected")
        if not ready:
            notes[item.id] = f"blocked: waiting for {parent.id}"
    return notes


def load_plan_or_none(settings: Settings, catalog: DeliverableCatalog) -> Plan | None:
    try:
        return load_plan(settings.calendar_file, catalog)
    except PlanConfigError:
        return None
