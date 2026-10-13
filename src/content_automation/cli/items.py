"""`ca item` and `ca audit`: content items by BG ID (PRD §6). Thin: the logic is in registry/.

Every command logs command_run (actor user); errors are one line on stderr and a non-zero exit.
A reference is a BG ID, an alias (Content ID, package folder name) or a calendar row number
together with --week (§14 D-12).
"""

import json
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Annotated, Any, NoReturn, cast

import typer

from content_automation.content.calendar import CalendarError, week_days, week_label
from content_automation.content.deliverables import DeliverableError, load_deliverables
from content_automation.core.config import ConfigurationError, Settings, load_settings
from content_automation.registry import db_path, open_registry
from content_automation.registry.approvals import approve, reject
from content_automation.registry.audit import EVENT_TYPES, Event, append_event, list_events
from content_automation.registry.db import RegistryError
from content_automation.registry.decisions import Gate
from content_automation.registry.ids import resolve, resolve_row
from content_automation.registry.items import Item, get_item, list_items
from content_automation.registry.report import ItemReport, item_report
from content_automation.registry.statuses import DIMENSIONS, Dimension
from content_automation.registry.versions import resubmit, revise
from content_automation.storage import ROOT_FOLDER
from content_automation.storage.providers.mock import TRACKER_FILE

items_app = typer.Typer(
    no_args_is_help=True,
    help="Content items by BG ID: list, status, approve, reject, revise, resubmit, history.",
)
audit_app = typer.Typer(no_args_is_help=True, help="The audit log (append-only).")

WeekOption = Annotated[
    str | None, typer.Option(help='The calendar week for a row number: "next", "this", 2026-W42.')
]
JsonOption = Annotated[bool, typer.Option("--json", help="Print JSON (for skills).")]
GateOption = Annotated[
    str | None, typer.Option("--gate", help="idea or review (default: the open gate).")
]
GATES = ("idea", "review")
VIDEO_PART = "reel"  # package.json key of the video part


def _utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")


def _fail(message: str, code: int = 1) -> NoReturn:
    typer.echo(message, err=True)
    raise typer.Exit(code=code)


def _settings() -> Settings:
    try:
        return load_settings(require_credentials=False, create_directories=False)
    except ConfigurationError as error:
        _fail(str(error), 2)


@contextmanager
def _registry(settings: Settings, command: str) -> Iterator[sqlite3.Connection]:
    """Open the registry, log the command, close it; registry errors become one line."""
    _utf8()
    try:
        conn = open_registry(db_path(settings.state_dir), settings.registry_file)
    except (RegistryError, sqlite3.Error) as error:
        _fail(f"Registry not usable: {error}", 2)
    try:
        append_event(conn, "command_run", actor="user", command=command)
        yield conn
    except RegistryError as error:
        _fail(str(error))
    finally:
        conn.close()


def _command(name: str, *parts: object) -> str:
    """The command as typed: ca <name> <args>; values with spaces quoted ("--flag value" parts
    keep the flag outside the quotes)."""
    words = ["ca", name]
    for part in parts:
        if part is None or part is False:
            continue
        text = str(part)
        flag, value = text.split(" ", 1) if text.startswith("--") and " " in text else ("", text)
        quoted = f'"{value}"' if " " in value else value
        words.append(f"{flag} {quoted}" if flag else quoted)
    return " ".join(words)


def _label(week: str) -> str:
    try:
        return week_label(week)
    except CalendarError as error:
        _fail(str(error), 2)


def _resolve(conn: sqlite3.Connection, ref: str, week: str | None) -> str:
    text = ref.strip()
    if text.isdigit():
        if week is None:
            raise RegistryError(
                f"Row {text} needs its week: add --week next (or this, or e.g. 2026-W42)."
            )
        return resolve_row(conn, _label(week), int(text))
    return resolve(conn, text)


def _gate(value: str | None) -> Gate | None:
    if value is None:
        return None
    if value not in GATES:
        _fail(f'--gate must be idea or review, not "{value}".', 2)
    return cast(Gate, value)


def _text(words: list[str] | None) -> str:
    return " ".join(words or []).strip()


def _short(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _version(item: Item) -> str:
    approved = f"v{item.approved_version}" if item.approved_version else "—"
    return f"v{item.current_version}/{approved}"


def _item_json(item: Item) -> dict[str, Any]:
    return {
        "id": item.id, "kind": item.kind, "title": item.title, "deliverable": item.deliverable,
        "platforms": list(item.platforms),
        "planned_date": item.planned_date.isoformat() if item.planned_date else None,
        "idea": item.idea_status, "generation": item.generation_status,
        "review": item.review_status, "upload": item.upload_status,
        "current_version": item.current_version, "approved_version": item.approved_version,
        "package_path": item.package_path,
    }


def _filters(values: list[str] | None) -> dict[Dimension, str]:
    filters: dict[Dimension, str] = {}
    for value in values or []:
        name, _, status = value.partition("=")
        if name not in DIMENSIONS or not status:
            _fail(f'--status takes dimension=value, e.g. idea=proposed (got "{value}").', 2)
        filters[name] = status
    return filters


@items_app.command("list")
def item_list(
    status: Annotated[
        list[str] | None,
        typer.Option("--status", help="dimension=value, e.g. idea=proposed (repeatable)."),
    ] = None,
    kind: Annotated[str | None, typer.Option(help="post, carousel, ad ...")] = None,
    week: Annotated[
        str | None, typer.Option(help='Planned in this week: "next", "this" or 2026-W42.')
    ] = None,
    as_json: JsonOption = False,
) -> None:
    """Items with their four item statuses and versions ("show items", "what's pending")."""
    settings = _settings()
    filters = _filters(status)
    span: tuple[date, date] | None = None
    if week is not None:
        days = week_days(_label(week))
        span = (days[0], days[-1])
    command = _command("item list", *(f"--status {s}" for s in status or []),
                       kind and f"--kind {kind}", week and f"--week {week}")
    with _registry(settings, command) as conn:
        items = list_items(conn, kind=kind, statuses=filters,
                           planned_from=span[0] if span else None,
                           planned_to=span[1] if span else None)
    if as_json:
        typer.echo(json.dumps([_item_json(item) for item in items], ensure_ascii=False))
        return
    if not items:
        typer.echo("No items match.")
        return
    typer.echo(f"{'ID':<8} {'Kind':<9} {'Title':<40} {'Idea':<19} {'Generation':<12} "
               f"{'Review':<18} {'Upload':<13} Ver")
    for item in items:
        typer.echo(f"{item.id:<8} {item.kind:<9} {_short(item.title, 40):<40} "
                   f"{item.idea_status:<19} {item.generation_status:<12} "
                   f"{item.review_status:<18} {item.upload_status:<13} {_version(item)}")
    typer.echo(f"{len(items)} item(s).")


def _part(settings: Settings, item: Item) -> str | None:
    if item.deliverable is None:
        return None
    try:
        catalog = load_deliverables(settings.deliverables_file)
    except DeliverableError:
        return None
    spec = catalog.deliverables.get(item.deliverable)
    if spec is None:
        return None
    return VIDEO_PART if spec.part == "video" else str(spec.part)


def _report_lines(report: ItemReport) -> list[str]:
    item = report.item
    deliverable = f" ({item.deliverable})" if item.deliverable else ""
    pubs = ", ".join(f"{p} {s}" for p, s in report.publications.items()) or "—"
    lines = [
        f"{item.id} {item.kind}{deliverable}: {item.title}",
        f"Aliases: {', '.join(report.aliases) or '—'}",
        f"Planned: {item.planned_date or '—'} · Platforms: {', '.join(item.platforms) or '—'} · "
        f"Package: {item.package_path or '—'}",
        f"Statuses: idea {item.idea_status} · generation {item.generation_status} · "
        f"review {item.review_status} · upload {item.upload_status} · publication {pubs}",
        "Versions:",
    ]
    for version in report.versions:
        marks = [m for m, on in (("current", version.version == item.current_version),
                                 ("approved", version.version == item.approved_version)) if on]
        extra = f" ({', '.join(marks)})" if marks else ""
        feedback = f' — feedback: "{version.feedback}"' if version.feedback else ""
        lines.append(f"- v{version.version} {version.status}{extra}{feedback}")
    lines.append("Last decisions:" if report.decisions else "Last decisions: none")
    for decision in report.decisions:
        text = f': "{decision.text}"' if decision.text else ""
        lines.append(f"- {decision.created_at[:16].replace('T', ' ')} {decision.gate} "
                     f"{decision.action} v{decision.version} ({decision.actor}){text}")
    lines += [f"Jobs: {report.jobs.line()}", f"Drive: {report.drive}",
              f"Tracker: {report.tracker}"]
    lines.append("Mismatches:" if report.mismatches else "Mismatches: none")
    lines += [f"- {m} (reported only, not fixed)" for m in report.mismatches]
    lines.append("Next allowed actions:" if report.next_actions else "Next allowed actions: none")
    for action in report.next_actions:
        gate = f" ({action.gate} gate)" if action.gate else ""
        lines.append(f"- {action.action}{gate}: {action.hint}")
    return lines


@items_app.command("status")
def item_status(
    ref: Annotated[str, typer.Argument(help="BG ID, Content ID, package folder or row number.")],
    week: WeekOption = None,
    as_json: JsonOption = False,
) -> None:
    """Everything about one item: statuses, versions, decisions, jobs, files, next actions."""
    settings = _settings()
    tracker = (settings.drive_mock_dir / ROOT_FOLDER / TRACKER_FILE
               if settings.storage_provider == "mock" else None)
    with _registry(settings, _command("item status", ref, week and f"--week {week}")) as conn:
        item_id = _resolve(conn, ref, week)
        part = _part(settings, get_item(conn, item_id))
        report = item_report(conn, item_id, part=part, tracker_csv=tracker)
    if as_json:
        typer.echo(json.dumps(report.to_json(), ensure_ascii=False))
        return
    for line in _report_lines(report):
        typer.echo(line)


@items_app.command("approve")
def item_approve(
    refs: Annotated[list[str], typer.Argument(help="One or more BG IDs (or aliases).")],
    gate: GateOption = None,
    week: WeekOption = None,
) -> None:
    """Approve the open gate of each item ("approve BG-007 BG-008"); one failure does not stop
    the others."""
    settings = _settings()
    chosen = _gate(gate)
    failed = 0
    with _registry(settings, _command("item approve", *refs, gate and f"--gate {gate}",
                                      week and f"--week {week}")) as conn:
        for ref in refs:
            try:
                change = approve(conn, _resolve(conn, ref, week), gate=chosen,
                                 command=_command("item approve", ref))
            except RegistryError as error:
                if len(refs) == 1:
                    raise
                failed += 1
                message = str(error)
                typer.echo(message if message.startswith(f"{ref}:") else f"{ref}: {message}",
                           err=True)
                continue
            typer.echo(change.line())
    if failed:
        _fail(f"{failed} of {len(refs)} not approved (see above).")


@items_app.command("reject")
def item_reject(
    ref: Annotated[str, typer.Argument(help="BG ID (or alias).")],
    reason: Annotated[
        list[str] | None, typer.Argument(help="Why it is rejected (required).")
    ] = None,
    gate: GateOption = None,
    week: WeekOption = None,
) -> None:
    """Reject with a reason ("reject BG-007 too generic")."""
    settings = _settings()
    text = _text(reason)
    if not text:
        _fail("A reject needs a reason: ca item reject BG-007 \"<reason>\".", 2)
    chosen = _gate(gate)
    with _registry(settings, _command("item reject", ref, text, gate and f"--gate {gate}")) as conn:
        change = reject(conn, _resolve(conn, ref, week), text, gate=chosen,
                        command=_command("item reject", ref, text))
        typer.echo(f'{change.line()} — reason: "{text}"')


@items_app.command("revise")
def item_revise(
    ref: Annotated[str, typer.Argument(help="BG ID (or alias).")],
    feedback: Annotated[list[str] | None, typer.Argument(help="What should change.")] = None,
    title: Annotated[
        str | None, typer.Option(help="Idea gate: the new topic, rewritten from the feedback.")
    ] = None,
    gate: GateOption = None,
    week: WeekOption = None,
) -> None:
    """Ask for changes: a new version (v n+1); the idea or review gate must approve it again."""
    settings = _settings()
    text = _text(feedback)
    if not text:
        _fail("A revise needs feedback: ca item revise BG-007 \"<what should change>\".", 2)
    chosen = _gate(gate)
    command = _command("item revise", ref, text, title and f"--title {title}")
    with _registry(settings, command) as conn:
        result = revise(conn, _resolve(conn, ref, week), text, title=title, gate=chosen,
                        command=command)
    item = result.item
    status = item.idea_status if result.gate == "idea" else item.review_status
    typer.echo(f"{item.id} {result.gate}: revise → {status}; v{result.version.version} created "
               f"(pending) with the feedback.")
    if result.gate == "idea" and title:
        typer.echo(f'New title: "{item.title}". Approve it again before it is generated.')
    elif result.gate == "idea":
        typer.echo(f'Next: ca item resubmit {item.id} --title "<new topic>", then approve it.')
    else:
        typer.echo("The new version is generated in Phase 7; it then needs a new review.")


@items_app.command("resubmit")
def item_resubmit(
    ref: Annotated[str, typer.Argument(help="BG ID (or alias).")],
    title: Annotated[str, typer.Option(help="The new topic.")],
    week: WeekOption = None,
) -> None:
    """After a revise without --title: set the new topic and propose the idea again."""
    settings = _settings()
    command = _command("item resubmit", ref, f"--title {title}")
    with _registry(settings, command) as conn:
        item = resubmit(conn, _resolve(conn, ref, week), title, command=command)
    typer.echo(f'{item.id} idea: revision_requested → proposed (v{item.current_version}); '
               f'title "{item.title}".')


def _event_line(event: Event) -> str:
    when = event.created_at[:19].replace("T", " ")
    item = f" {event.item_id}" if event.item_id else ""
    version = f" v{event.version}" if event.version else ""
    details = event.details
    if event.type == "status_changed":
        summary = f"{details.get('dimension')}: {details.get('from')} → {details.get('to')}"
    elif event.type == "decision":
        text = f' "{details["text"]}"' if details.get("text") else ""
        summary = f"{details.get('gate')} {details.get('action')}{text}"
    elif event.type == "command_run":
        summary = event.command or ""
    else:
        summary = ", ".join(f"{k}={v}" for k, v in details.items() if v not in (None, "", []))
    return f"{when} {event.actor:<6} {event.type:<16}{item}{version} {summary}".rstrip()


@items_app.command("history")
def item_history(
    ref: Annotated[str, typer.Argument(help="BG ID (or alias).")],
    week: WeekOption = None,
    as_json: JsonOption = False,
) -> None:
    """Every event of one item, oldest first ("history of BG-007")."""
    settings = _settings()
    with _registry(settings, _command("item history", ref)) as conn:
        item_id = _resolve(conn, ref, week)
        events = list_events(conn, item_id=item_id)
    if as_json:
        typer.echo(json.dumps([e.__dict__ for e in events], ensure_ascii=False))
        return
    typer.echo(f"History of {item_id} ({len(events)} events):")
    for event in events:
        typer.echo(_event_line(event))


@audit_app.command("show")
def audit_show(
    since: Annotated[
        str | None, typer.Option(help="From this date or time (ISO, e.g. 2026-10-13).")
    ] = None,
    event_type: Annotated[
        list[str] | None, typer.Option("--type", help="Event type (repeatable).")
    ] = None,
    item: Annotated[str | None, typer.Option("--item", help="Only this item.")] = None,
    limit: Annotated[int, typer.Option(min=1, help="The newest N events.")] = 50,
    as_json: JsonOption = False,
) -> None:
    """The audit log, newest last ("show audit log")."""
    settings = _settings()
    unknown = [t for t in event_type or [] if t not in EVENT_TYPES]
    if unknown:
        _fail(f"Unknown event type {', '.join(unknown)} ({', '.join(sorted(EVENT_TYPES))}).", 2)
    with _registry(settings, _command("audit show", since and f"--since {since}",
                                      item and f"--item {item}")) as conn:
        item_id = resolve(conn, item) if item else None
        events = list_events(conn, item_id=item_id, types=event_type or (), since=since,
                             last=limit)
    if as_json:
        typer.echo(json.dumps([e.__dict__ for e in events], ensure_ascii=False))
        return
    typer.echo(f"Audit log: {len(events)} event(s) (newest last).")
    for event in events:
        typer.echo(_event_line(event))
