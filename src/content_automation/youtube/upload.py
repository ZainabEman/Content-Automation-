"""`ca youtube upload BG-x` (PRD v5 R9.11, R10, R11; v6 R7/R8): a topic folder to Drive and its
tracker row.

Drive layout (v6, new uploads mirror the local tree): Content Automation/YouTube Long-Form/
<Topic Name>/ with research.txt and Style A|B|C/ (script_de_teleprompter.txt,
script_de_en_bilingual.txt, storyboard.txt; the newest version of each). The metadata and the
internal briefs stay local. Existing Drive folders are never renamed, moved or deleted; a
same-name file in the target folder is updated, never duplicated (the storage providers).
Tracker: one row per topic (Content ID = the BG ID) with links to the research file, the scripts
and the storyboards, plus the registry columns. STORAGE_PROVIDER=mock writes the same layout
under outputs/_system/drive-mock/ with fake links; drive uses the Google APIs (only after
setup); plugin (Codex Drive plugin manifests) is not built for YouTube topics yet and says so.

PRD v6 weekly (2026-10-22): Content Automation/YouTube Long-form/ and YouTube Short-form/
(formats.<fmt>.driveFolder); the topic folder "<English Topic Title> <YYYY-MM-DD>" holds the 3
files directly (short) or Style A|B|C/ with the 3 files each (long): teleprompter-de.txt,
script-en-de.md, storyboard.md. research.txt stays local (the references are inline in the
storyboards). Every successful upload upserts the tracker row (BG ID) with the Drive folder link
and the upload status; a failed tracker write is reported, never silent.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from content_automation.content.tracking import Entry, TrackerError
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.registry import runtime
from content_automation.registry.items import get_item
from content_automation.storage import (
    CALENDAR_FOLDER,
    ROOT_FOLDER,
    Storage,
    StorageError,
    StorageNotSetUpError,
    get_storage,
    item_cells,
    platform_folder,
    update_tracker,
)
from content_automation.storage.manifest import (
    FILE_LINK,
    MANIFEST_FILE,
    _remember,
    known_folders,
)
from content_automation.youtube.scripts import BILINGUAL, STORYBOARD, TELEPROMPTER
from content_automation.youtube.topic import (
    LONG,
    YoutubeError,
    find_folder,
    format_config,
    format_of,
    latest,
    read_package,
    styles,
    write_package,
)

PLATFORM_KEY = "youtube_longform"  # Drive: YouTube Long-form/ (v6 R8)
TRACKER_UPLOAD_ID = "youtube:tracker.csv"


def platform_key(fmt: str = LONG) -> str:
    """The Drive folder key of the format: youtube_longform or youtube_shortform."""
    return str(format_config(fmt).get("driveFolder") or PLATFORM_KEY)


def topic_files(folder: Path, fmt: str = LONG) -> list[tuple[Path, str | None, str]]:
    """(file, style subfolder or None, label) of everything that goes to Drive: the 3 files
    of each style (short-form: one style, directly in the topic folder)."""
    found: list[tuple[Path, str | None, str]] = []
    for key, style in styles(fmt).items():
        for name, label in ((TELEPROMPTER, "teleprompter"), (BILINGUAL, "EN-DE script"),
                            (STORYBOARD, "storyboard")):
            path = latest((folder / style.folder if style.folder else folder) / name)
            if path.is_file():
                found.append((path, style.folder or None,
                              f"Style {key} {label}" if style.folder else label.capitalize()))
    return found


def tracker_row(storage: Storage, data: dict[str, object], links: list[str],
                status: str) -> list[str]:
    """Upsert the topic's tracker row (Content ID = the BG ID) with the Drive folder link and
    the upload status; one line, a failed write is reported (never raises)."""
    fmt = format_of(data)
    key = platform_key(fmt)
    content_id = str(data["folder"])
    try:
        link = storage.folder_link(key, content_id)
    except StorageError as error:
        link = f"(no Drive link: {error})"
    entry: Entry = {
        "Content ID": str(data["bgId"]), "Topic": str(data["title"]),
        "Research source": "research:inline storyboard references", "Platform": "YouTube",
        "Content type": str(format_config(fmt)["deliverable"]),
        "Caption": "\n".join([f"Upload: {status}", *links]),
        "Hashtags": "", "Image/video link": link,
    }
    scope = runtime.current()
    try:
        if scope is not None and scope.tracker_columns:
            entry |= item_cells(scope.tracker_columns, [get_item(scope.conn, str(data["bgId"]))],
                                scope.conn)
        return [update_tracker(storage, [entry])]
    except (StorageError, StorageNotSetUpError, TrackerError) as error:
        return [f"Tracker NOT updated for {data['bgId']} ({error}); the files are on Drive, "
                f"run uv run ca youtube upload {data['bgId']} again."]


def _manifest_path(folder: Path) -> Path:
    return folder / MANIFEST_FILE


def _load_youtube_manifest(folder: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(_manifest_path(folder).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _plugin_manifest(settings: Settings, folder: Path, data: dict[str, Any],
                     fmt: str) -> list[str]:
    """Write a plugin manifest for the approved script and storyboard files only."""
    folders = known_folders(settings)
    if "root" not in folders:
        raise YoutubeError(f"{settings.drive_folders_file} has no root folder ID")
    key = platform_key(fmt)
    category = platform_folder(key)
    content_id = folder.name
    old = _load_youtube_manifest(folder) or {}
    entries: list[dict[str, Any]] = [entry for entry in old.get("entries", [])
                                     if entry.get("done")]
    completed = {str(entry.get("id")) for entry in entries}
    targets = topic_files(folder, fmt)
    if not targets:
        raise YoutubeError(f"{data['bgId']}: no scripts or storyboards in {folder} yet")

    wanted_folders: list[str] = []
    file_targets: list[tuple[Path, str]] = []
    for path, sub, _label in targets:
        relative = f"{category}/{content_id}" + (f"/{sub}" if sub else "")
        file_key = f"file:{path.relative_to(folder).as_posix()}"
        uploaded = data.get("uploads", {}).get(path.relative_to(folder).as_posix())
        if file_key in completed or uploaded:
            continue
        parts = relative.split("/")
        for depth in range(1, len(parts) + 1):
            candidate = "/".join(parts[:depth])
            if candidate not in folders and candidate not in wanted_folders:
                wanted_folders.append(candidate)
        file_targets.append((path, relative))

    for key_path in wanted_folders:
        parent = key_path.rpartition("/")[0] or "root"
        entries.append({
            "id": f"folder:{key_path}", "kind": "folder", "action": "create_folder",
            "folder": key_path, "name": key_path.rpartition("/")[2],
            "parent_folder_id": folders.get(parent), "parent_folder": parent,
        })
    for path, target in file_targets:
        entries.append({
            "id": f"file:{path.relative_to(folder).as_posix()}", "kind": "file",
            "action": "upload", "local_path": path.resolve().as_posix(),
            "target_folder_id": folders.get(target), "target_folder": target,
            "target_name": path.name,
        })
    manifest = {
        "kind": "youtube_topic", "bg_id": str(data["bgId"]),
        "package": folder.resolve().as_posix(), "content_id": content_id,
        "format": fmt, "post_upload_done": bool(old.get("post_upload_done")),
        "entries": entries,
    }
    atomic_write_text(_manifest_path(folder), json.dumps(manifest, indent=2, ensure_ascii=False)
                      + "\n")
    files = sum(entry.get("kind") == "file" and not entry.get("done") for entry in entries)
    folders_count = sum(entry.get("kind") == "folder" and not entry.get("done")
                        for entry in entries)
    return [
        f"Drive (plugin): {_manifest_path(folder)}: {folders_count} folder(s) to create, "
        f"{files} file(s) to upload.",
        f'  Next: upload each manifest entry, then: uv run ca youtube record '
        f'{data["bgId"]} --results <results.json>',
    ]


def record_youtube_results(settings: Settings, bg_id: str,
                           results: list[dict[str, Any]], *,
                           root: Path | None = None) -> list[str]:
    """Record plugin folder/file IDs for a YouTube topic and queue its tracker CSV."""
    folder = find_folder(bg_id, root)
    data = read_package(folder)
    manifest = _load_youtube_manifest(folder)
    if manifest is None or manifest.get("kind") != "youtube_topic":
        raise YoutubeError(f"No YouTube {MANIFEST_FILE} in {folder}; run ca youtube upload first.")
    entries: list[dict[str, Any]] = manifest.get("entries", [])
    lines: list[str] = []
    recorded = skipped = 0

    def clear_failure(entry_id: str) -> None:
        lines[:] = [line for line in lines if not line.startswith(f"{entry_id}: failed (")]

    for result in results:
        wanted = str(result.get("id") or "")
        entry = next((item for item in entries if item.get("id") == wanted), None)
        if entry is None:
            lines.append(f"Not in the manifest (ignored): {json.dumps(result)[:120]}")
            continue
        if entry.get("done"):
            skipped += 1
            continue
        if result.get("status") == "failed":
            entry["error"] = str(result.get("error") or "failed")
            lines.append(f"{wanted}: failed ({entry['error']}); stays pending")
            continue
        if entry.get("kind") == "folder":
            folder_id = str(result.get("folder_id") or result.get("file_id") or "")
            if not folder_id:
                lines.append(f"{wanted}: no folder_id in result; stays pending")
                continue
            clear_failure(wanted)
            entry.pop("error", None)
            _remember(settings, str(entry["folder"]), folder_id)
            entry.update(done=True, folder_id=folder_id)
            for other in entries:
                if other.get("parent_folder") == entry["folder"]:
                    other["parent_folder_id"] = folder_id
                if other.get("target_folder") == entry["folder"]:
                    other["target_folder_id"] = folder_id
        elif entry.get("kind") == "file":
            file_id = str(result.get("file_id") or "")
            if not file_id:
                lines.append(f"{wanted}: no file_id in result; stays pending")
                continue
            clear_failure(wanted)
            link = str(result.get("link") or FILE_LINK.format(file_id))
            relative = wanted.removeprefix("file:")
            data.setdefault("uploads", {})[relative] = link
            entry.pop("error", None)
            entry.update(done=True, file_id=file_id, link=link)
        elif entry.get("kind") == "tracker_csv":
            if not result.get("file_id"):
                lines.append(f"{wanted}: no file_id in result; stays pending")
                continue
            clear_failure(wanted)
            entry.pop("error", None)
            entry.update(done=True, file_id=str(result["file_id"]))
        recorded += 1

    write_package(folder, data)
    lines.insert(0, f"Recorded {recorded}, already recorded {skipped}.")
    media_left = [entry for entry in entries
                  if entry.get("kind") in ("folder", "file") and not entry.get("done")]
    if not media_left and not manifest.get("post_upload_done"):
        links = [f"{path}: {link}" for path, link in data.get("uploads", {}).items()]
        tracker_storage = get_storage(settings, provider="plugin")
        tracker_lines = tracker_row(tracker_storage, data, links, "uploaded")
        lines.extend(tracker_lines)
        if any(line.startswith("Tracker NOT updated") for line in tracker_lines):
            atomic_write_text(_manifest_path(folder),
                              json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
            return lines
        drive_folders = known_folders(settings)
        calendar_id = drive_folders.get(CALENDAR_FOLDER)
        if calendar_id is None:
            raise YoutubeError(f"{settings.drive_folders_file} has no {CALENDAR_FOLDER} folder ID")
        entries.append({
            "id": TRACKER_UPLOAD_ID, "kind": "tracker_csv", "action": "upload",
            "local_path": settings.tracker_csv_file.resolve().as_posix(),
            "target_folder_id": calendar_id, "target_folder": CALENDAR_FOLDER,
            "target_name": "tracker.csv", "replace_existing": True,
        })
        manifest["post_upload_done"] = True
        lines.append("Tracker CSV queued for Calendar; upload it and record the result.")

    remaining = sum(not entry.get("done") for entry in entries)
    manifest["status"] = "done" if remaining == 0 else "upload_pending"
    atomic_write_text(_manifest_path(folder), json.dumps(manifest, indent=2, ensure_ascii=False)
                      + "\n")
    lines.append(f"Manifest: {remaining} entr{'y' if remaining == 1 else 'ies'} left" +
                 (" (all done)." if remaining == 0 else "."))
    return lines


def upload_topic(settings: Settings, bg_id: str, *, root: Path | None = None) -> list[str]:
    if settings.storage_provider == "plugin":
        folder = find_folder(bg_id, root)
        data = read_package(folder)
        return _plugin_manifest(settings, folder, data, format_of(data))
    folder = find_folder(bg_id, root)
    data = read_package(folder)
    fmt = format_of(data)
    key = platform_key(fmt)
    content_id = folder.name  # "<English Topic Title> <YYYY-MM-DD>" (v6 weekly §6)
    storage = get_storage(settings)
    links: list[str] = []
    uploads: dict[str, str] = {}
    files = topic_files(folder, fmt)
    if not files:
        raise YoutubeError(f"{bg_id}: no scripts or storyboards in {folder} yet")
    for path, sub, label in files:
        try:
            done = storage.upload(path, key, content_id, sub)
        except StorageError as error:
            raise YoutubeError(f"{path.name}: {error}") from None
        uploads[path.relative_to(folder).as_posix()] = done.link
        links.append(f"{label}: {done.link}")
    data["uploads"] = uploads
    write_package(folder, data)
    lines = [f"Drive ({storage.name}): {ROOT_FOLDER}/{platform_folder(key)}/{content_id}/ — "
             f"{len(uploads)} file(s)"]
    return lines + tracker_row(storage, data, links, "uploaded")


__all__ = ["platform_key", "topic_files", "tracker_row", "upload_topic",
           "record_youtube_results"]
