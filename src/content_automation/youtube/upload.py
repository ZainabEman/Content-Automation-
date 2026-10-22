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

from pathlib import Path

from content_automation.content.tracking import Entry, TrackerError
from content_automation.core.config import Settings
from content_automation.registry import runtime
from content_automation.registry.items import get_item
from content_automation.storage import (
    ROOT_FOLDER,
    Storage,
    StorageError,
    StorageNotSetUpError,
    get_storage,
    item_cells,
    platform_folder,
    update_tracker,
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


def upload_topic(settings: Settings, bg_id: str, *, root: Path | None = None) -> list[str]:
    if settings.storage_provider == "plugin":
        raise YoutubeError("YouTube uploads through the Codex Drive plugin are not built yet: "
                           "use STORAGE_PROVIDER=drive (or mock)")
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


__all__ = ["platform_key", "topic_files", "tracker_row", "upload_topic"]
