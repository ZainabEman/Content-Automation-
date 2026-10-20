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
from content_automation.youtube.scripts import BILINGUAL, STORYBOARD, TELEPROMPTER
from content_automation.youtube.topic import (
    YoutubeError,
    find_folder,
    latest,
    read_package,
    research_file,
    styles,
    write_package,
)

PLATFORM_KEY = "youtube_longform"  # Drive: YouTube Long-Form/ (v6 R8)


def topic_files(folder: Path) -> list[tuple[Path, str | None, str]]:
    """(file, style subfolder or None, label) of everything that goes to Drive."""
    found: list[tuple[Path, str | None, str]] = [(research_file(folder), None, "Research")]
    for key, style in styles().items():
        for name, label in ((TELEPROMPTER, "teleprompter"), (BILINGUAL, "DE-EN script"),
                            (STORYBOARD, "storyboard")):
            path = latest(folder / style.folder / name)
            if path.is_file():
                found.append((path, style.folder, f"Style {key} {label}"))
    return [item for item in found if item[0].is_file()]


def upload_topic(settings: Settings, bg_id: str, *, root: Path | None = None) -> list[str]:
    if settings.storage_provider == "plugin":
        raise YoutubeError("YouTube uploads through the Codex Drive plugin are not built yet: "
                           "use STORAGE_PROVIDER=drive (or mock)")
    folder = find_folder(bg_id, root)
    data = read_package(folder)
    content_id = folder.name  # the readable topic name (R7)
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
    lines = [f"Drive ({storage.name}): {ROOT_FOLDER}/YouTube Long-Form/{content_id}/ — "
             f"{len(uploads)} "
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
