"""Storage of finished files: the only public entry point for the storage providers.

Layout (Google Drive, or a local folder with the mock):
Content Automation/{LinkedIn,Facebook,Instagram}/<Content ID>/<file>,
Content Automation/Calendar/<YYYY-Www>.csv (a read-only copy, replaced in place) and the
Content Tracker (Drive: a Google Sheet; mock: tracking.csv), plus "Content Tracker.csv" from
`ca tracking export`. Adapters live in ``providers/`` and are chosen with STORAGE_PROVIDER
(mock by default, so nothing needs a Google account before `ca drive setup`).

sync_package uploads a package's finished images and MP4s: each file's ID and link are saved
in package.json, so a new sync skips them and only tries the failed or missing ones again. A
failed upload is retried once, then marked upload_failed; the local file is always kept.
A finished package whose files are all uploaded then gets its tracker row (update_tracker,
merge rules in content/tracking.py); one with a failed upload waits for the next sync.
"""

import importlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Protocol

from content_automation.content.deliverables import DeliverableCatalog, load_deliverables
from content_automation.content.package import (
    DONE_STATUS,
    ContentPackage,
    UploadRecord,
    load_package,
    save_package,
)
from content_automation.content.tracking import (
    PLATFORM_NAMES,
    TRACKER_NAME,
    Cell,
    Conflict,
    Entry,
    Table,
    TrackerError,
    find_conflicts,
    header_index,
    plan_upsert,
    row_index,
    table_csv,
    tracker_entry,
)
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.registry import runtime
from content_automation.registry.audit import append_event
from content_automation.registry.db import RegistryError
from content_automation.registry.ids import resolve
from content_automation.registry.items import get_item
from content_automation.registry.progress import upload_label, upload_target
from content_automation.registry.tracker import CellRecord, last_cells, record_cells

ROOT_FOLDER = "Content Automation"
PLATFORM_FOLDERS = PLATFORM_NAMES  # platform -> folder name (and the tracker's Platform)
# Phase 7: YouTube, Shorts, Podcasts, Facebook Ads and TikTok folders (made by `ca drive setup`).
FOLDER_NAMES = {**PLATFORM_FOLDERS, "youtube": "YouTube", "shorts": "Shorts",
                "podcast": "Podcasts", "facebook_ads": "Facebook Ads", "tiktok": "TikTok"}
CALENDAR_FOLDER = "Calendar"
FOLDERS = (*FOLDER_NAMES.values(), CALENDAR_FOLDER)
EXPORT_NAME = f"{TRACKER_NAME}.csv"  # `ca tracking export`, in the main folder
# Images, MP4s and a carousel's caption.txt; captions.srt etc. stay local.
UPLOAD_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".mp4", ".txt")
NOT_SET_UP = "Drive not set up — run ca drive setup"

# Provider name -> adapter module. Adding a provider = one adapter file + one line here.
_ADAPTERS: dict[str, str] = {
    "mock": "content_automation.storage.providers.mock",
    "drive": "content_automation.storage.providers.drive_api",
}


class StorageError(Exception):
    """A storage call failed; the local file is kept."""


class StorageNotSetUpError(Exception):
    """Drive has no sign-in, folders or Content Tracker yet (`ca drive setup`)."""


@dataclass(frozen=True)
class Uploaded:
    file_id: str
    link: str


class Storage(Protocol):
    name: str

    def ensure_folders(self) -> str:
        """Find or make the main folder, its four folders and the tracker; its link."""
        ...

    def upload(
        self, file: Path, platform: str, content_id: str, subfolder: str | None = None
    ) -> Uploaded:
        """Into <Platform>/<Content ID>/ (or its `subfolder`, e.g. originals/)."""
        ...

    def upload_calendar(self, file: Path) -> Uploaded: ...

    def folder_link(self, platform: str, content_id: str) -> str: ...

    def read_tracker(self) -> Table: ...

    def write_tracker(self, cells: list[Cell], rows: list[list[str]]) -> None:
        """Write the changed cells, then add the new rows after the last row."""
        ...

    def tracker_link(self) -> str: ...

    def upload_export(self, file: Path) -> Uploaded:
        """The tracker CSV as EXPORT_NAME in the main folder (read-only, replaced in place)."""
        ...


def get_storage(
    settings: Settings, *, provider: str | None = None, sign_in: bool = False
) -> Storage:
    """The adapter for STORAGE_PROVIDER (or `provider`). Only sign_in (`ca drive setup`) may
    open the browser; otherwise StorageNotSetUpError when Drive has no sign-in or folders."""
    name = provider or settings.storage_provider
    if name not in _ADAPTERS:  # "plugin": the Drive plugin uploads requests after the review
        raise StorageNotSetUpError(
            "STORAGE_PROVIDER=plugin: uploads are requests for the Google Drive plugin, written "
            "when a review is approved (upload skill; ca drive record)")
    module = importlib.import_module(_ADAPTERS[name])
    storage: Storage = module.create_storage(settings, sign_in=sign_in)
    return storage


def drive_setup_problem(settings: Settings) -> str | None:
    """What `ca drive setup` still has to do (None: done). Makes no network call."""
    module = importlib.import_module(_ADAPTERS["drive"])
    problem: str | None = module.setup_problem(settings)
    return problem


def platform_folder(platform: str) -> str:
    try:
        return FOLDER_NAMES[platform.lower()]
    except KeyError:
        raise StorageError(f'no Drive folder for platform "{platform}"') from None


@dataclass
class SyncResult:
    lines: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # "<file>: <error>"
    entry: Entry | None = None  # its tracker row: finished and every file uploaded
    waiting: str | None = None  # why it has no tracker row yet


def sync_package(folder: Path, storage: Storage, catalog: DeliverableCatalog) -> SyncResult:
    """Upload the finished images and MP4s not uploaded yet with this provider.

    OSError or ValueError when package.json is missing or invalid; StorageNotSetUpError
    stops the sync (every file done so far is already saved in package.json).
    """
    package = load_package(folder)
    names = dict.fromkeys(
        name for item in package.items.values() if item.status == "done"
        for name in item.files if Path(name).suffix.lower() in UPLOAD_SUFFIXES
    )
    subfolders = {
        name: sub for item in package.items.values() for name, sub in item.subfolders.items()
    }
    content_id = drive_folder_name(folder, package)
    where = f"{platform_folder(package.platform)}/{content_id}"
    result = SyncResult()
    if not names:
        result.lines.append(f"Drive ({storage.name}): {folder.name} has no finished images or "
                            "videos yet.")
        result.waiting = "no finished images or videos yet"
        return result
    kept = uploaded = 0
    links: list[str] = []
    owners = _file_items(folder, package)  # file -> BG ID (registered packages)
    for name in names:
        record = package.uploads.get(name)
        if record is not None and record.provider == storage.name and record.status == "uploaded":
            kept += 1
            continue
        now = datetime.now(UTC)
        job_id, earlier = _upload_job(owners.get(name), storage.name, name, where)
        if earlier is not None:  # the registry saw this upload succeed: never upload twice
            package.uploads[name] = UploadRecord(provider=storage.name, status="uploaded",
                                                 link=earlier, updated_at=now)
            kept += 1
            save_package(folder, package)
            continue
        call = partial(
            storage.upload, folder / name, package.platform, content_id, subfolders.get(name)
        )
        try:
            done = _twice(call, folder / name)
        except StorageError as error:
            package.uploads[name] = UploadRecord(
                provider=storage.name, status="upload_failed", error=str(error), updated_at=now
            )
            result.failed.append(f"{name}: {error}")
            if job_id is not None:
                runtime.fail(job_id, str(error))
            runtime.log(owners.get(name), "upload_failed",
                        {"file": name, "provider": storage.name, "error": str(error)})
        else:
            package.uploads[name] = UploadRecord(
                provider=storage.name, status="uploaded", file_id=done.file_id, link=done.link,
                updated_at=now,
            )
            uploaded += 1
            links.append(f"  {name}: {done.link}")
            if job_id is not None:
                runtime.succeed(job_id, result_path=done.link)
            runtime.log(owners.get(name), "upload_succeeded",
                        {"file": name, "provider": storage.name, "link": done.link})
        save_package(folder, package)  # after every file: an uploaded ID is never lost
    _report_uploads(package, owners, storage.name)
    result.lines.append(
        f"Drive ({storage.name}): {where}: {uploaded} uploaded, {kept} already there, "
        f"{len(result.failed)} failed."
    )
    result.lines += links
    if package.status != DONE_STATUS:
        result.waiting = "not finished yet"
    elif result.failed:
        result.waiting = "upload failed; the next sync tries again"
    else:
        try:
            link = storage.folder_link(package.platform, content_id)
            result.entry = tracker_entry(folder, package, catalog, link) | registry_cells(folder)
        except (StorageError, TrackerError) as error:
            result.waiting = str(error)
    return result


def drive_folder_name(folder: Path, package: ContentPackage) -> str:
    """The Drive folder (D-13): the Content ID, else the BG ID of the package's first item,
    else (not registered) the package folder name."""
    if package.content_id:
        return package.content_id
    items = runtime.package_items(folder)
    first = sorted(items.values(), key=lambda bg: int(bg.split("-")[1]))[:1]
    return first[0] if first else package.package_id


def registry_cells(folder: Path) -> Entry:
    """The registry columns of a package's tracker row (D-14, D-16); empty outside a command."""
    scope = runtime.current()
    if scope is None or not scope.tracker_columns:
        return {}
    ids = sorted(runtime.package_items(folder).values(), key=lambda bg: int(bg.split("-")[1]))
    items = [get_item(scope.conn, item_id) for item_id in ids]
    if not items:
        return {}

    def joined(values: list[str]) -> str:
        if len(set(values)) == 1:
            return values[0]
        return "; ".join(f"{item.id} {value}" for item, value in zip(items, values, strict=True))

    names = scope.tracker_columns
    updated = max(item.updated_at for item in items)
    return {
        names["bg_id"]: ", ".join(item.id for item in items),
        names["version"]: joined([f"v{item.current_version}" for item in items]),
        names["idea"]: joined([item.idea_status for item in items]),
        names["generation"]: joined([item.generation_status for item in items]),
        names["review"]: joined([item.review_status for item in items]),
        names["upload"]: joined([upload_label(item, item.upload_provider) for item in items]),
        names["updated"]: f"{updated[:10]} {updated[11:16]} UTC",
    }


def _file_items(folder: Path, package: ContentPackage) -> dict[str, str]:
    """Each finished file of a registered part -> the BG ID of that part's item."""
    items = runtime.package_items(folder)
    return {name: items[part] for part, item in package.items.items() if part in items
            for name in item.files}


def _upload_job(item_id: str | None, provider: str, name: str, where: str
                ) -> tuple[int | None, str | None]:
    """(the started upload job, or the link of an earlier upload the registry recorded)."""
    if item_id is None:
        return None, None
    opened = runtime.open_scoped_job("upload", provider, {"file": name, "folder": where},
                                     item_id=item_id)
    if opened is None:
        return None, None
    if opened.reused:
        return None, opened.job.result_path or "(recorded earlier)"
    try:
        started = runtime.start(opened.job.id)
    except RegistryError:
        return None, None  # e.g. an upload still running elsewhere: upload as before
    return (started.id if started else None), None


def _report_uploads(package: ContentPackage, owners: dict[str, str], provider: str) -> None:
    """Each registered item's upload status from its files (D-16); mock stays labelled."""
    by_item: dict[str, list[str]] = {}
    for name, item_id in owners.items():
        by_item.setdefault(item_id, []).append(name)
    for item_id, files in by_item.items():
        states = {
            name: ("uploaded" if record.status == "uploaded" else "failed")
            for name in files if (record := package.uploads.get(name)) is not None
            and record.provider == provider
        }
        runtime.report_upload(item_id, upload_target(states, files), provider)


def failure_lines(folder: Path, failed: list[str]) -> list[str]:
    if not failed:
        return []
    return [
        f"{len(failed)} upload(s) failed (local files kept; `uv run ca drive sync \"{folder}\"` "
        "tries them again):",
        *(f"- {line}" for line in failed),
    ]


def update_tracker(storage: Storage, entries: list[Entry]) -> str:
    """Upsert the rows into the Content Tracker; one line. Inside a `ca` command the registry
    columns are added, the written cells are remembered and a hand-edited row is a conflict
    (not written, conflict_found logged).

    Raises StorageError, StorageNotSetUpError (no tracker yet) or TrackerError (header).
    """
    scope = runtime.current()
    extra = tuple(scope.tracker_columns.values()) if scope is not None else ()
    last = last_cells(scope.conn) if scope is not None else {}
    plan = plan_upsert(storage.read_tracker(), entries, last, extra)
    if plan.cells or plan.rows:
        storage.write_tracker(plan.cells, plan.rows)
    if scope is not None:
        record_cells(scope.conn, plan.records)
        bg_column = extra[0] if extra else ""
        owners = {entry["Content ID"]: _first_id(entry.get(bg_column, "")) for entry in entries}
        for conflict in plan.conflicts:
            append_event(scope.conn, "conflict_found", command=scope.command,
                         item_id=owners.get(conflict.key),
                         details={"row": conflict.key, "kind": conflict.kind,
                                  "detail": conflict.detail})
        for key in (*plan.added, *plan.updated):
            append_event(scope.conn, "tracker_synced", command=scope.command,
                         item_id=owners.get(key),
                         details={"row": key, "change": "added" if key in plan.added
                                  else "updated", "provider": storage.name})
    conflicts = (f", {len(plan.conflicts)} not written (conflicts: ca tracking conflicts)"
                 if plan.conflicts else "")
    return (f"Tracker ({storage.name}): {len(plan.added)} added, {len(plan.updated)} updated, "
            f"{plan.unchanged} unchanged{conflicts}: {storage.tracker_link()}")


def _first_id(text: str) -> str | None:
    first = text.split(",")[0].strip()
    return first or None


def tracker_conflicts(storage: Storage) -> list[Conflict]:
    """`ca tracking conflicts`: hand edits, rows missing on either side, duplicate IDs."""
    scope = runtime.current()
    if scope is None:
        raise StorageError("the conflict report needs the registry")
    extra = tuple(scope.tracker_columns.values())
    known = {str(row["id"]) for row in scope.conn.execute("SELECT id FROM items")}
    known |= {str(row["alias"]) for row in scope.conn.execute("SELECT alias FROM aliases")}
    expected: dict[str, set[str]] = {}
    for row in scope.conn.execute("SELECT id, package_path FROM items WHERE upload_status = "
                                  "'uploaded' AND package_path IS NOT NULL"):
        folder = Path(str(row["package_path"]))
        try:
            package = load_package(folder)
        except (OSError, ValueError):
            continue
        key = package.content_id or package.package_id
        expected.setdefault(key, set()).add(str(row["id"]))
    return find_conflicts(storage.read_tracker(), last_cells(scope.conn), expected, known, extra)


def resolve_tracker(storage: Storage, catalog: DeliverableCatalog, ref: str, *,
                    keep_sheet: bool) -> list[str]:
    """`ca tracking resolve`: keep the Sheet's hand edits (they become the written values) or
    write the registry's values over them."""
    scope = runtime.current()
    if scope is None:
        raise StorageError("resolving needs the registry")
    item = get_item(scope.conn, resolve(scope.conn, ref))
    if item.package_path is None:
        raise StorageError(f"{item.id} has no package, so no tracker row.")
    folder = Path(item.package_path)
    package = load_package(folder)
    key = package.content_id or package.package_id
    table = storage.read_tracker()
    extra = tuple(scope.tracker_columns.values())
    header = header_index(table)
    by_content, by_bg = row_index(table, extra[0] if extra else None)
    rows = sorted(set(by_bg.get(item.id, [])) | set(by_content.get(key, [])))
    if len(rows) != 1:
        raise StorageError(f"{key}: {'no' if not rows else 'several'} tracker rows; fix the "
                           "Sheet first (ca tracking conflicts).")
    row = table[rows[0]]
    records = last_cells(scope.conn).get(key, {})

    def shown(name: str) -> str:
        column = header.get(name)
        return row[column] if column is not None and column < len(row) else ""

    if keep_sheet:
        kept = {name: CellRecord(shown(name), record.source) for name, record in records.items()
                if name in header and shown(name) != record.written}
        record_cells(scope.conn, {key: kept})
        lines = [f"{key}: kept the Sheet's values for {', '.join(kept) or 'no cell'}; they stay "
                 "until the registry value changes."]
    else:
        link = storage.folder_link(package.platform, drive_folder_name(folder, package))
        entry = tracker_entry(folder, package, catalog, link) | registry_cells(folder)
        cells = [Cell(rows[0], header[name], value) for name, value in entry.items()
                 if name in header and name != "Content ID" and shown(name) != value]
        if cells:
            storage.write_tracker(cells, [])
        record_cells(scope.conn, {key: {name: CellRecord(value, value)
                                        for name, value in entry.items()}})
        lines = [f"{key}: wrote the registry's values over {len(cells)} cell(s)."]
    append_event(scope.conn, "tracker_synced", command=scope.command, item_id=item.id,
                 details={"row": key, "resolved": "keep-sheet" if keep_sheet
                          else "use-registry"})
    return lines


def tracker_lines(storage: Storage, results: list[tuple[Path, SyncResult]]) -> list[str]:
    """The tracker upsert after a sync, never raising: its line, then the packages waiting."""
    entries = [result.entry for _, result in results if result.entry is not None]
    lines: list[str] = []
    if entries:
        jobs = [_tracker_job(folder, storage.name, result.entry)
                for folder, result in results if result.entry is not None]
        try:
            lines.append(update_tracker(storage, entries))
        except StorageNotSetUpError as error:
            lines.append(str(error))
            _close_tracker_jobs(jobs, str(error))
        except (StorageError, TrackerError) as error:
            lines.append(f"Tracker not updated ({error}); the next sync tries again.")
            _close_tracker_jobs(jobs, str(error))
        else:
            _close_tracker_jobs(jobs, None)
    lines += [f"Tracker waits for {folder.name}: {result.waiting}"
              for folder, result in results if result.waiting]
    return lines


def _tracker_job(folder: Path, provider: str, entry: Entry) -> int | None:
    """One registry job per tracker row write (never reused: a write is cheap and idempotent)."""
    items = runtime.package_items(folder)
    if not items:
        return None
    scope = runtime.current()
    opened = runtime.open_scoped_job(
        "tracker_write", "sheets" if provider == "drive" else provider,
        {"content_id": entry["Content ID"], "run": scope.run_id if scope else ""},
        item_id=next(iter(items.values())),
    )
    if opened is None:
        return None
    try:
        started = runtime.start(opened.job.id)
    except RegistryError:
        return None
    return started.id if started else None


def _close_tracker_jobs(jobs: list[int | None], error: str | None) -> None:
    for job_id in jobs:
        if job_id is None:
            continue
        if error is None:
            runtime.succeed(job_id)
        else:
            runtime.fail(job_id, error)


def export_tracker(storage: Storage, target: Path) -> Uploaded:
    """Write the tracker as CSV to target, and as EXPORT_NAME in the main folder.

    OSError when target cannot be written; StorageError / StorageNotSetUpError otherwise.
    """
    text = table_csv(storage.read_tracker())
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, text)
    return _twice(partial(storage.upload_export, target), target)


def sync_calendar(path: Path, settings: Settings) -> str:
    """Upload the week's read-only calendar copy (replaced in place); one line, never raises."""
    try:
        storage = get_storage(settings)
        done = _twice(partial(storage.upload_calendar, path), path)
    except StorageNotSetUpError as error:
        return str(error)
    except StorageError as error:
        return f"Calendar copy not uploaded ({error}); the next calendar command tries again."
    return f"Calendar copy ({storage.name}): {done.link}"


class AutoSync:
    """Sync each package a build finished (files, then its tracker row) without failing it.

    Storage is opened on the first package; "not set up" is said only once per command.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._storage: Storage | None = None
        self._catalog: DeliverableCatalog | None = None
        self._not_set_up = False

    def __call__(self, folder: Path) -> list[str]:
        if self._not_set_up:
            return []
        from content_automation.storage.review_upload import load_storage_config

        if load_storage_config(self._settings.storage_file).require_review:
            self._not_set_up = True  # said once per command
            return ["Upload waits for the review approval (config/storage.json "
                    "upload.requireReview): uv run ca item approve BG-x after the review."]
        try:
            if self._storage is None or self._catalog is None:
                self._catalog = load_deliverables(self._settings.deliverables_file)
                self._storage = get_storage(self._settings)
            result = sync_package(folder, self._storage, self._catalog)
        except StorageNotSetUpError as error:
            self._not_set_up = True
            return [str(error)]
        except (OSError, ValueError, StorageError) as error:
            return [f'Drive sync stopped ({error}); later: uv run ca drive sync "{folder}"']
        return [
            *result.lines,
            *failure_lines(folder, result.failed),
            *tracker_lines(self._storage, [(folder, result)]),
        ]


def _twice(call: Callable[[], Uploaded], file: Path) -> Uploaded:
    """The upload, retried once after a failure (the second error is raised)."""
    if not file.is_file():
        raise StorageError("the local file is missing")
    try:
        return call()
    except StorageError:
        return call()


__all__ = [
    "CALENDAR_FOLDER",
    "EXPORT_NAME",
    "FOLDERS",
    "NOT_SET_UP",
    "PLATFORM_FOLDERS",
    "ROOT_FOLDER",
    "AutoSync",
    "Storage",
    "StorageError",
    "StorageNotSetUpError",
    "SyncResult",
    "Uploaded",
    "drive_setup_problem",
    "export_tracker",
    "failure_lines",
    "get_storage",
    "platform_folder",
    "sync_calendar",
    "sync_package",
    "tracker_lines",
    "update_tracker",
]
