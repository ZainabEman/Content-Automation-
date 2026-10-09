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
    UploadRecord,
    load_package,
    save_package,
)
from content_automation.content.tracking import (
    PLATFORM_NAMES,
    TRACKER_NAME,
    Cell,
    Entry,
    Table,
    TrackerError,
    plan_upsert,
    table_csv,
    tracker_entry,
)
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text

ROOT_FOLDER = "Content Automation"
PLATFORM_FOLDERS = PLATFORM_NAMES  # platform -> folder name (and the tracker's Platform)
CALENDAR_FOLDER = "Calendar"
FOLDERS = (*PLATFORM_FOLDERS.values(), CALENDAR_FOLDER)
EXPORT_NAME = f"{TRACKER_NAME}.csv"  # `ca tracking export`, in the main folder
UPLOAD_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".mp4")  # captions.srt etc. stay local
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

    def upload(self, file: Path, platform: str, content_id: str) -> Uploaded: ...

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
    module = importlib.import_module(_ADAPTERS[provider or settings.storage_provider])
    storage: Storage = module.create_storage(settings, sign_in=sign_in)
    return storage


def drive_setup_problem(settings: Settings) -> str | None:
    """What `ca drive setup` still has to do (None: done). Makes no network call."""
    module = importlib.import_module(_ADAPTERS["drive"])
    problem: str | None = module.setup_problem(settings)
    return problem


def platform_folder(platform: str) -> str:
    try:
        return PLATFORM_FOLDERS[platform.lower()]
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
    content_id = package.content_id or package.package_id
    where = f"{platform_folder(package.platform)}/{content_id}"
    result = SyncResult()
    if not names:
        result.lines.append(f"Drive ({storage.name}): {folder.name} has no finished images or "
                            "videos yet.")
        result.waiting = "no finished images or videos yet"
        return result
    kept = uploaded = 0
    links: list[str] = []
    for name in names:
        record = package.uploads.get(name)
        if record is not None and record.provider == storage.name and record.status == "uploaded":
            kept += 1
            continue
        call = partial(storage.upload, folder / name, package.platform, content_id)
        now = datetime.now(UTC)
        try:
            done = _twice(call, folder / name)
        except StorageError as error:
            package.uploads[name] = UploadRecord(
                provider=storage.name, status="upload_failed", error=str(error), updated_at=now
            )
            result.failed.append(f"{name}: {error}")
        else:
            package.uploads[name] = UploadRecord(
                provider=storage.name, status="uploaded", file_id=done.file_id, link=done.link,
                updated_at=now,
            )
            uploaded += 1
            links.append(f"  {name}: {done.link}")
        save_package(folder, package)  # after every file: an uploaded ID is never lost
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
            result.entry = tracker_entry(folder, package, catalog, link)
        except (StorageError, TrackerError) as error:
            result.waiting = str(error)
    return result


def failure_lines(folder: Path, failed: list[str]) -> list[str]:
    if not failed:
        return []
    return [
        f"{len(failed)} upload(s) failed (local files kept; `uv run ca drive sync \"{folder}\"` "
        "tries them again):",
        *(f"- {line}" for line in failed),
    ]


def update_tracker(storage: Storage, entries: list[Entry]) -> str:
    """Upsert the rows into the Content Tracker; one line.

    Raises StorageError, StorageNotSetUpError (no tracker yet) or TrackerError (header).
    """
    plan = plan_upsert(storage.read_tracker(), entries)
    if plan.cells or plan.rows:
        storage.write_tracker(plan.cells, plan.rows)
    return (f"Tracker ({storage.name}): {len(plan.added)} added, {len(plan.updated)} updated, "
            f"{plan.unchanged} unchanged: {storage.tracker_link()}")


def tracker_lines(storage: Storage, results: list[tuple[Path, SyncResult]]) -> list[str]:
    """The tracker upsert after a sync, never raising: its line, then the packages waiting."""
    entries = [result.entry for _, result in results if result.entry is not None]
    lines: list[str] = []
    if entries:
        try:
            lines.append(update_tracker(storage, entries))
        except StorageNotSetUpError as error:
            lines.append(str(error))
        except (StorageError, TrackerError) as error:
            lines.append(f"Tracker not updated ({error}); the next sync tries again.")
    lines += [f"Tracker waits for {folder.name}: {result.waiting}"
              for folder, result in results if result.waiting]
    return lines


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
