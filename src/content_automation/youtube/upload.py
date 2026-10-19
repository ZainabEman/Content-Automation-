"""`ca youtube upload BG-x` (PRD v5 R9.11, R10, R11): a topic folder to Drive and its tracker row.

Drive layout: Content Automation/YouTube/<YYYY-MM>/<BG-ID>_<slug>/ with the research file, the
storyboard and one subfolder per style (teleprompter_DE.txt, script_DE-EN.txt); the internal
briefs (.briefs/) stay local. Existing Drive folders are never renamed or moved (the
restructuring spec is PENDING, R10.3); a same-name file in the target folder is updated, never
duplicated (the storage providers). Tracker: one row per topic (Content ID = the BG ID) with
links to the research file, the six scripts and the storyboard, plus the registry columns
(Category YouTube, Language, Selected Script Style …). STORAGE_PROVIDER=mock writes the same
layout under outputs/drive/ with fake links; drive uses the Google APIs (only after setup);
plugin (Codex Drive plugin manifests) is not built for YouTube topics yet and says so.
"""

from __future__ import annotations

from pathlib import Path

from content_automation.content.tracking import Entry
from content_automation.core.config import Settings
from content_automation.registry import runtime
from content_automation.registry.items import get_item
from content_automation.storage import (
    ROOT_FOLDER,
    StorageError,
    get_storage,
    item_cells,
    update_tracker,
)
from content_automation.youtube.scripts import BILINGUAL, TELEPROMPTER
from content_automation.youtube.topic import (
    YoutubeError,
    find_folder,
    read_package,
    research_file,
    styles,
    write_package,
)

PLATFORM_KEY = "youtube"


def topic_files(folder: Path) -> list[tuple[Path, str | None, str]]:
    """(file, style subfolder or None, label) of everything that goes to Drive."""
    found: list[tuple[Path, str | None, str]] = [(research_file(folder), None, "Research")]
    for key, style in styles().items():
        for name, label in ((TELEPROMPTER, "teleprompter"), (BILINGUAL, "DE-EN script")):
            path = folder / style.folder / name
            if path.is_file():
                found.append((path, style.folder, f"Style {key} {label}"))
    data = read_package(folder)
    if data.get("storyboard"):
        found.append((folder / str(data["storyboard"]), None, "Storyboard"))
    return [item for item in found if item[0].is_file()]


def upload_topic(settings: Settings, bg_id: str, *, root: Path | None = None) -> list[str]:
    if settings.storage_provider == "plugin":
        raise YoutubeError("YouTube uploads through the Codex Drive plugin are not built yet: "
                           "use STORAGE_PROVIDER=drive (or mock)")
    folder = find_folder(bg_id, root)
    data = read_package(folder)
    content_id = f"{data['month']}/{folder.name}"
    storage = get_storage(settings)
    links: list[str] = []
    uploads: dict[str, str] = {}
    for path, sub, label in topic_files(folder):
        try:
            done = storage.upload(path, PLATFORM_KEY, content_id, sub)
        except StorageError as error:
            raise YoutubeError(f"{path.name}: {error}") from None
        uploads[path.relative_to(folder).as_posix()] = done.link
        links.append(f"{label}: {done.link}")
    data["uploads"] = uploads
    write_package(folder, data)
    lines = [f"Drive ({storage.name}): {ROOT_FOLDER}/YouTube/{content_id}/ — {len(uploads)} "
             "file(s)"]
    entry: Entry = {
        "Content ID": data["bgId"], "Topic": data["title"],
        "Research source": f"research:{research_file(folder).name}", "Platform": "YouTube",
        "Content type": "youtube_longform", "Caption": "\n".join(links),
        "Hashtags": "", "Image/video link": storage.folder_link(PLATFORM_KEY, content_id),
    }
    scope = runtime.current()
    if scope is not None and scope.tracker_columns:
        entry |= item_cells(scope.tracker_columns, [get_item(scope.conn, data["bgId"])],
                            scope.conn)
    lines.append(update_tracker(storage, [entry]))
    return lines


__all__ = ["topic_files", "upload_topic"]
