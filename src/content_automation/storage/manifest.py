"""STORAGE_PROVIDER=plugin: the upload manifest the Codex Google Drive plugin works through.

`ca` cannot call plugins, so instead of uploading a package gets
<package folder>/upload_manifest.json: first "create_folder" entries for the Drive
folders that do not exist yet (<Platform>/<Content ID>/ and its subfolders, parents first),
then one "upload" entry per file {local_path, target_folder_id, target_name}. Folder IDs come
from config/drive_folders.json (root, the platform folders, Calendar) plus the folders made
through earlier manifests (state/drive_folders.json). A complete package becomes
"upload_pending".

`ca drive record <package> --results <json>` marks each file uploaded with its Drive file ID
(package.json uploads) and remembers each new folder ID; entries already recorded are skipped,
so a rerun never makes a duplicate. Once every file is up, the post-upload steps follow: the
tracker row (merged into the local tracker CSV with the Sheet's rules) as a "sheet_append"
entry for the Content Tracker Sheet, with tracker.csv into Content Automation/Calendar/ as the
fallback when the plugin cannot write Sheets, and the calendar row Generated (its CSV copy as
one more upload entry). Google Cloud credentials are not needed.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from content_automation.content.deliverables import DeliverableCatalog
from content_automation.content.package import (
    DONE_STATUS,
    ContentPackage,
    UploadRecord,
    load_package,
    save_package,
)
from content_automation.content.tracking import TRACKER_NAME, TrackerError, tracker_entry
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.output_tree import iter_package_files
from content_automation.registry import runtime
from content_automation.registry.progress import upload_target
from content_automation.storage import (
    CALENDAR_FOLDER,
    StorageError,
    drive_folder_name,
    get_storage,
    package_folder_key,
    platform_folder,
    registry_cells,
    update_tracker,
    upload_names,
)

MANIFEST_FILE = "upload_manifest.json"
PENDING_STATUS = "upload_pending"  # package.json status while the plugin uploads
PROVIDER = "plugin"
CREATED_FILE = "drive_folders.json"  # in STATE_DIR: folders made through earlier manifests
FOLDER_LINK = "https://drive.google.com/drive/folders/{}"
FILE_LINK = "https://drive.google.com/file/d/{}/view"
TRACKER_CSV = "tracker.csv"  # the Sheet fallback in Content Automation/Calendar/


class ManifestError(StorageError):
    """No manifest, a result that does not fit it, or a folder ID that is missing."""


@dataclass(frozen=True)
class Target:
    key: str  # the package.json uploads key
    path: Path
    folder: str  # e.g. Instagram/2026-W43-05 or Instagram/2026-W43-05/v2
    item: str | None = None  # the BG ID of the file's part


def known_folders(settings: Settings) -> dict[str, str]:
    """Folder name or path -> Drive folder ID: config/drive_folders.json, then the folders
    created through earlier manifests."""
    found: dict[str, str] = {}
    for path in (settings.drive_folders_file, settings.state_dir / CREATED_FILE):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            found |= {str(key): str(value) for key, value in data.items()
                      if isinstance(value, str) and value and not str(key).startswith("_")}
    return found


def _remember(settings: Settings, folder: str, folder_id: str) -> None:
    path = settings.state_dir / CREATED_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data[folder] = folder_id
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def manifest_path(folder: Path) -> Path:
    return folder / MANIFEST_FILE


def load_manifest(folder: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(manifest_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _save(folder: Path, data: dict[str, Any]) -> None:
    atomic_write_text(manifest_path(folder), json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def pending(data: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in data.get("entries", []) if not entry.get("done")]


def package_targets(folder: Path, package: ContentPackage) -> list[Target]:
    """The finished files of the package's done parts, as `ca drive sync` uploads them."""
    content_id = drive_folder_name(folder, package)
    base = f"{platform_folder(package_folder_key(package))}/{content_id}"
    items = runtime.package_items(folder)
    owner = {name: part for part, item in package.items.items() for name in item.files}
    first = next(iter(items.values()), None)
    return [Target(name, folder / name, f"{base}/{sub}" if sub else base,
                   items.get(owner[name]) if name in owner else first)
            for name, sub in upload_names(folder, package).items()]


def write_manifest(folder: Path, settings: Settings, targets: list[Target]) -> list[str]:
    """Write (or refresh) the package's manifest for every target not uploaded yet; a complete
    package becomes upload_pending. Done entries are dropped, pending post-upload entries kept."""
    package = load_package(folder)
    folders = known_folders(settings)
    if "root" not in folders:
        raise ManifestError(f"{settings.drive_folders_file} has no root folder ID")
    old = load_manifest(folder) or {}
    entries: list[dict[str, Any]] = [entry for entry in pending(old)
                                     if entry.get("kind") not in ("folder", "file")]
    earlier = [Target(str(entry["id"]), Path(str(entry["local_path"])),
                      str(entry["target_folder"]), entry.get("item"))
               for entry in pending(old) if entry.get("kind") == "file"]
    keys = {target.key for target in targets}
    every = [*targets, *(target for target in earlier if target.key not in keys)]
    todo = [target for target in every if not _uploaded(package, target.key)]
    wanted: list[str] = []
    for target in todo:
        parts = target.folder.split("/")
        for depth in range(1, len(parts) + 1):
            key = "/".join(parts[:depth])
            if key not in folders and key not in wanted:
                wanted.append(key)
    for key in wanted:
        parent = key.rpartition("/")[0] or "root"
        entries.append({
            "id": f"folder:{key}", "kind": "folder", "action": "create_folder",
            "folder": key, "name": key.rpartition("/")[2],
            "parent_folder_id": folders.get(parent), "parent_folder": parent,
        })
    for target in todo:
        entries.append({
            "id": target.key, "kind": "file", "action": "upload",
            "local_path": target.path.resolve().as_posix(),
            "target_folder_id": folders.get(target.folder), "target_folder": target.folder,
            "target_name": target.path.name, "item": target.item,
        })
    complete = package.status in (DONE_STATUS, PENDING_STATUS)
    data = {
        "package": folder.resolve().as_posix(),
        "content_id": drive_folder_name(folder, package),
        "complete": complete,
        "post_upload_done": bool(old.get("post_upload_done")),  # the Sheet row once
        "entries": entries,
    }
    _save(folder, data)
    if todo and complete and package.status != PENDING_STATUS:
        package.status = PENDING_STATUS
        save_package(folder, package)
    files = sum(1 for entry in entries if entry["kind"] == "file")
    if not entries:
        return [f"Drive (plugin): {folder.name}: every file is uploaded."]
    return [
        f"Drive (plugin): {manifest_path(folder)}: {len(wanted)} folder(s) to create, {files} "
        f"file(s) to upload, {len(entries) - files - len(wanted)} post-upload step(s).",
        f'  Next: upload each entry with the Google Drive plugin, then: uv run ca drive record '
        f'"{folder}" --results <results.json>',
    ]


def _uploaded(package: ContentPackage, key: str) -> bool:
    record = package.uploads.get(key)
    return record is not None and record.provider == PROVIDER and record.status == "uploaded"


def _match(entries: list[dict[str, Any]], result: dict[str, Any]) -> dict[str, Any] | None:
    wanted = str(result.get("id") or "")
    local = str(result.get("local_path") or "")
    local = Path(local).resolve().as_posix() if local else ""
    for entry in entries:
        if wanted and entry.get("id") == wanted:
            return entry
        if local and entry.get("local_path") == local:
            return entry
    return None


def record_results(folder: Path, settings: Settings, results: list[dict[str, Any]],
                   catalog: DeliverableCatalog) -> list[str]:
    """`ca drive record`: mark the plugin's results; idempotent (recorded entries are skipped).
    When every file is up: the tracker row and the calendar row (post-upload steps)."""
    data = load_manifest(folder)
    if data is None:
        raise ManifestError(f"No {MANIFEST_FILE} in {folder}: nothing to record "
                            "(uv run ca drive sync writes it).")
    package = load_package(folder)
    entries: list[dict[str, Any]] = data.get("entries", [])
    now = datetime.now(UTC)
    lines: list[str] = []
    recorded = skipped = 0
    for result in results:
        entry = _match(entries, result)
        if entry is None:
            lines.append(f"Not in the manifest (ignored): {json.dumps(result)[:120]}")
            continue
        if entry.get("done"):
            skipped += 1
            continue
        if result.get("status") == "failed":
            entry["error"] = str(result.get("error") or "failed")
            lines.append(f"{entry['id']}: failed ({entry['error']}); stays pending")
            continue
        if entry["kind"] == "folder":
            folder_id = str(result.get("folder_id") or result.get("file_id") or "")
            if not folder_id:
                lines.append(f"{entry['id']}: no folder_id in the result; stays pending")
                continue
            _remember(settings, entry["folder"], folder_id)
            entry.update(done=True, folder_id=folder_id)
            for other in entries:
                if other.get("parent_folder") == entry["folder"]:
                    other["parent_folder_id"] = folder_id
                if other.get("target_folder") == entry["folder"]:
                    other["target_folder_id"] = folder_id
        elif entry["kind"] == "file":
            file_id = str(result.get("file_id") or "")
            if not file_id:
                lines.append(f"{entry['id']}: no file_id in the result; stays pending")
                continue
            if not _uploaded(package, entry["id"]):
                package.uploads[entry["id"]] = UploadRecord(
                    provider=PROVIDER, status="uploaded", file_id=file_id,
                    link=str(result.get("link") or FILE_LINK.format(file_id)), updated_at=now)
            entry.update(done=True, file_id=file_id)
        else:  # tracker, tracker.csv, calendar copy
            status = str(result.get("status") or "done")
            entry.update(done=True, result=status)
            if entry["kind"] == "tracker" and status != "skipped":
                for other in entries:  # the Sheet has the row: the CSV fallback is not needed
                    if other.get("kind") == "tracker_csv" and not other.get("done"):
                        other.update(done=True, result="not needed")
        recorded += 1
    save_package(folder, package)
    lines.insert(0, f"Recorded {recorded}, already recorded {skipped}.")
    files_left = [entry for entry in pending(data) if entry["kind"] in ("folder", "file")]
    if not files_left and data.get("complete") and not data.get("post_upload_done"):
        lines += _post_upload(folder, settings, catalog, data)
    left = pending(data)
    data["status"] = "done" if not left else PENDING_STATUS
    _save(folder, data)
    lines.append(f"Manifest: {len(left)} entr{'y' if len(left) == 1 else 'ies'} left"
                 + ("" if left else " (all done)") + ".")
    return lines


def _post_upload(folder: Path, settings: Settings, catalog: DeliverableCatalog,
                 data: dict[str, Any]) -> list[str]:
    """Every file is up: the package is done again, the items' upload status, the tracker row
    (local CSV, then sheet_append with the tracker.csv fallback) and the calendar row."""
    from content_automation.content.calendar import mark_generated

    package = load_package(folder)
    if package.status == PENDING_STATUS:
        package.status = DONE_STATUS
        save_package(folder, package)
    by_item: dict[str, dict[str, str]] = {}
    for entry in data["entries"]:
        if entry["kind"] == "file" and entry.get("item"):
            by_item.setdefault(entry["item"], {})[entry["id"]] = "uploaded"
    for item_id, states in by_item.items():
        runtime.report_upload(item_id, upload_target(states, list(states)), PROVIDER)
    folders = known_folders(settings)
    content_id = drive_folder_name(folder, package)
    link = FOLDER_LINK.format(folders.get(
        f"{platform_folder(package_folder_key(package))}/{content_id}", ""))
    storage = get_storage(settings, provider=PROVIDER)
    lines: list[str] = []
    try:
        entry = tracker_entry(folder, package, catalog, link) | registry_cells(folder)
        lines.append(update_tracker(storage, [entry]))
        table = storage.read_tracker()
    except (StorageError, TrackerError) as error:
        lines.append(f"Tracker row not made ({error}); fix it, then record again.")
        return lines
    header = table[0] if table else []
    column = header.index("Content ID") if "Content ID" in header else 0
    rows = [row for row in table[1:] if len(row) > column and row[column] == content_id]
    calendar_id = folders.get(CALENDAR_FOLDER)
    data["entries"] += [
        {"id": "tracker", "kind": "tracker", "action": "sheet_append",
         "sheet_name": TRACKER_NAME, "parent_folder_id": folders.get("root"),
         "header": header, "rows": rows, "fallback": TRACKER_CSV},
        {"id": TRACKER_CSV, "kind": "tracker_csv", "action": "upload",
         "local_path": settings.tracker_csv_file.resolve().as_posix(),
         "target_folder_id": calendar_id, "target_folder": CALENDAR_FOLDER,
         "target_name": TRACKER_CSV, "replace_existing": True, "only_if_skipped": "tracker"},
    ]
    for path in mark_generated(settings, folder):
        lines.append(f"Calendar {path.stem}: row Generated.")
        data["entries"].append({
            "id": f"calendar:{path.name}", "kind": "calendar", "action": "upload",
            "local_path": path.resolve().as_posix(), "target_folder_id": calendar_id,
            "target_folder": CALENDAR_FOLDER, "target_name": path.name,
            "replace_existing": True,
        })
    data["post_upload_done"] = True
    lines.append("Post-upload entries added: the tracker row (sheet_append, else tracker.csv "
                 "into Calendar/) and the calendar copy; upload them, then record them too.")
    return lines


def pending_manifests(packages_dir: Path) -> list[Path]:
    """Package folders whose manifest still has entries to do ("sync drive")."""
    folders = sorted(path.parent for path in iter_package_files(packages_dir))
    return [folder for folder in folders
            if (data := load_manifest(folder)) is not None and pending(data)]
