"""`ca outputs rename [--apply]` (PRD v6 weekly §6): every item folder named
"<English Topic Title> <YYYY-MM-DD>".

The dry run (default, free, nothing changed) lists every local item folder (the platform tree
and both YouTube roots) and every Drive folder made before whose name does not match, with its
new name, plus the YouTube files still under their v6 R7 names. An item without an English
title is listed in outputs/_system/titles_en.json for Codex to fill (titleEn, at most about 6
words; free text, no paid call); the next run uses it.

--apply (only after the user's "ok") stores the English titles on the items, renames the Drive
folders in place (same folder ID, contents unchanged: the Drive API or mock provider directly;
the Codex Drive plugin through outputs/_system/drive_rename_manifest.json), then the local
folders (package.json, item.json, the registry's package paths, the calendar rows and the
YouTube metadata follow), and upserts the tracker row of every renamed Drive folder with its
link. A failed step is reported and the rest goes on.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.output_tree import (
    CATEGORY_DIRS,
    SYSTEM,
    folder_date,
    item_folder_name,
    unique_name,
)

TITLES_FILE = "titles_en.json"  # in outputs/_system/: Codex fills the missing English titles
PLUGIN_MANIFEST = "drive_rename_manifest.json"  # in outputs/_system/: for the Drive plugin
_OLD_BG = re.compile(r"_(BG-\d+)_")
_LEGACY_FILE = re.compile(r"^(script_de_teleprompter|script_de_en_bilingual|storyboard)"
                          r"(_v\d+)?\.txt$")


@dataclass
class Rename:
    where: Literal["local", "drive"]
    kind: Literal["package", "youtube", "top"]
    ref: str  # the BG ID (or the folder key of the Drive top folder)
    old: str  # local: the folder path; drive: "<Platform folder>/<content id>"
    new: str  # the new folder name (the last part only)
    folder: Path | None = None  # the local item folder (packages and YouTube)
    files: list[tuple[str, str]] = field(default_factory=list)  # legacy file names (YouTube)


@dataclass
class RenamePlan:
    renames: list[Rename] = field(default_factory=list)
    missing: dict[str, dict[str, str]] = field(default_factory=dict)  # ref -> topic, folder
    titles: dict[Path, str] = field(default_factory=dict)  # package/meta file -> titleEn

    @property
    def files(self) -> int:
        return sum(len(rename.files) for rename in self.renames if rename.where == "local")


def titles_path(settings: Settings) -> Path:
    return settings.packages_dir / SYSTEM / TITLES_FILE


def _titles(settings: Settings) -> dict[str, str]:
    try:
        data = json.loads(titles_path(settings).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(key): str(value.get("titleEn") or "").strip() for key, value in data.items()
            if isinstance(value, dict) and str(value.get("titleEn") or "").strip()} if (
        isinstance(data, dict)) else {}


def _matches(name: str, wanted: str) -> bool:
    return name == wanted or re.fullmatch(re.escape(wanted) + r" \(\d+\)", name) is not None


def _legacy_files(folder: Path) -> list[tuple[str, str]]:
    from content_automation.youtube.scripts import LEGACY_NAMES

    found: list[tuple[str, str]] = []
    for path in sorted(folder.rglob("*.txt")) if folder.is_dir() else []:
        match = _LEGACY_FILE.match(path.name)
        if match is None:
            continue
        new = LEGACY_NAMES[match.group(1)]
        stem, suffix = new.rsplit(".", 1)
        relative = path.relative_to(folder)
        found.append((relative.as_posix(),
                      relative.with_name(f"{stem}{match.group(2) or ''}.{suffix}").as_posix()))
    return found


def _package_ref(folder: Path, content_id: str | None) -> str:
    from content_automation.registry import runtime

    items = sorted(runtime.package_items(folder).values(), key=lambda bg: int(bg.split("-")[1]))
    if items:
        return items[0]
    match = _OLD_BG.search(folder.name)
    return match.group(1) if match else (content_id or folder.name)


def _planned(conn: sqlite3.Connection | None, bg_id: str) -> date | None:
    if conn is None:
        return None
    from content_automation.registry.db import RegistryError
    from content_automation.registry.items import get_item

    try:
        return get_item(conn, bg_id).planned_date
    except RegistryError:
        return None


def plan_renames(settings: Settings, conn: sqlite3.Connection | None = None) -> RenamePlan:
    """Every folder whose name does not match "<English Topic Title> <YYYY-MM-DD>" (free)."""
    from content_automation.content.package import load_package
    from content_automation.storage import (
        LEGACY_FOLDER_NAMES,
        drive_folder_name,
        package_folder_key,
        platform_folder,
    )

    plan = RenamePlan()
    titles = _titles(settings)
    root = settings.packages_dir
    for old, new in LEGACY_FOLDER_NAMES.items():
        if _drive_knows(settings, old, new):
            plan.renames.append(Rename("drive", "top", old, old, new))
    planned_names: dict[Path, set[str]] = {}
    for category in CATEGORY_DIRS.values():
        for file in sorted((root / category).glob("*/*/package.json")):
            folder = file.parent
            try:
                package = load_package(folder)
            except (OSError, ValueError):
                continue
            ref = _package_ref(folder, package.content_id)
            title = package.title_en or titles.get(ref)
            if title and not package.title_en:
                plan.titles[file] = title
            planned = package.planned_date or folder_date(folder.name)
            if not title:
                plan.missing[ref] = {"topic": package.topic,
                                     "folder": folder.relative_to(root).as_posix()}
                continue
            if planned is None:
                continue
            wanted = item_folder_name(title, planned)
            if _matches(folder.name, wanted):
                continue
            taken = {path.name for path in folder.parent.iterdir() if path != folder}
            taken |= planned_names.setdefault(folder.parent, set())
            new_name = unique_name(wanted, taken)
            planned_names[folder.parent].add(new_name)
            plan.renames.append(Rename("local", "package", ref, folder.as_posix(), new_name,
                                       folder))
            if any(record.status == "uploaded" for record in package.uploads.values()):
                drive = f"{platform_folder(package_folder_key(package))}/" \
                        f"{drive_folder_name(folder, package)}"
                plan.renames.append(Rename("drive", "package", ref, drive, new_name, folder))
    _plan_youtube(settings, conn, plan, titles)
    return plan


def _plan_youtube(settings: Settings, conn: sqlite3.Connection | None, plan: RenamePlan,
                  titles: dict[str, str]) -> None:
    from content_automation.storage import platform_folder
    from content_automation.youtube.topic import format_of, output_root
    from content_automation.youtube.upload import platform_key

    meta = settings.packages_dir / SYSTEM / "youtube"
    planned_names: dict[Path, set[str]] = {}
    for file in sorted(meta.glob("*.json")) if meta.is_dir() else []:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not data.get("folder") or not data.get("bgId"):
            continue
        fmt = format_of(data)
        base = settings.packages_dir / output_root(fmt).name
        folder = base / str(data["folder"])
        ref = str(data["bgId"])
        title = str(data.get("titleEn") or "") or titles.get(ref, "")
        if title and not data.get("titleEn"):
            plan.titles[file] = title
        files = _legacy_files(folder)
        day = (date.fromisoformat(str(data["plannedDate"])) if data.get("plannedDate")
               else _planned(conn, ref))
        if not title:
            plan.missing[ref] = {"topic": str(data.get("title") or ""),
                                 "folder": folder.relative_to(settings.packages_dir).as_posix()}
            if files:
                plan.renames.append(Rename("local", "youtube", ref, folder.as_posix(),
                                           folder.name, folder, files))
            continue
        if day is None:
            day = date.fromisoformat(f"{data.get('month')}-01") if data.get("month") else None
        if day is None:
            continue
        wanted = item_folder_name(title, day)
        if _matches(folder.name, wanted) and not files:
            continue
        new_name = folder.name
        if not _matches(folder.name, wanted):
            taken = {path.name for path in base.iterdir() if path != folder} if (
                base.is_dir()) else set()
            taken |= planned_names.setdefault(base, set())
            new_name = unique_name(wanted, taken)
            planned_names[base].add(new_name)
        plan.renames.append(Rename("local", "youtube", ref, folder.as_posix(), new_name, folder,
                                   files))
        if data.get("uploads") and new_name != folder.name:
            plan.renames.append(Rename(
                "drive", "youtube", ref,
                f"{platform_folder(platform_key(fmt))}/{folder.name}", new_name, folder))


def _drive_knows(settings: Settings, old: str, new: str) -> bool:
    """Whether the storage provider still knows the top folder under its old name."""
    provider = settings.storage_provider
    if provider == "mock":
        from content_automation.storage import ROOT_FOLDER

        return (settings.drive_mock_dir / ROOT_FOLDER / old).is_dir()
    if provider == "plugin":
        done = _plugin_done(settings)
        from content_automation.storage.manifest import known_folders

        folders = known_folders(settings)
        return (old in folders or new in folders) and old not in done
    if provider == "drive":
        from content_automation.storage.providers import drive_api

        state = drive_api._read_state(settings.secrets_dir / drive_api.STATE_FILE)  # noqa: SLF001
        return state is not None and old in state.folders
    return False


def _plugin_done(settings: Settings) -> set[str]:
    try:
        data = json.loads((settings.packages_dir / SYSTEM / PLUGIN_MANIFEST).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(entry.get("old")) for entry in data.get("entries", [])} if isinstance(
        data, dict) else set()


def plan_lines(plan: RenamePlan, settings: Settings, *, applied: bool = False) -> list[str]:
    folders = [rename for rename in plan.renames
               if rename.where == "drive" or Path(rename.old).name != rename.new]
    local = sum(rename.where == "local" for rename in folders)
    lines = [f"Rename {'done' if applied else 'plan (dry run, nothing changed)'}: "
             f"{len(folders)} folder(s) ({local} local, {len(folders) - local} Drive), "
             f"{plan.files} YouTube file name(s); {len(plan.missing)} item(s) without an "
             "English title."]
    for rename in folders:
        old = Path(rename.old).name if rename.where == "local" else rename.old
        where = (rename.old.rsplit("/", 1)[0] if "/" in rename.old else "Content Automation"
                 ) if rename.where == "drive" else Path(rename.old).parent.as_posix()
        old = rename.old.rsplit("/", 1)[-1] if rename.where == "drive" else old
        lines.append(f"- {rename.where} {rename.ref}: {where}/ \"{old}\" → \"{rename.new}\"")
    for rename in plan.renames:
        lines += [f"- file {rename.ref}: {old} → {new}" for old, new in rename.files]
    if plan.missing:
        lines.append(f"No English title yet ({len(plan.missing)}): fill titleEn (at most about "
                     f"6 English words) in {titles_path(settings).as_posix()}, then run the dry "
                     "run again.")
    if not applied and (folders or plan.files):
        lines.append("Real run (only after the user's \"ok\"): uv run ca outputs rename --apply")
    return lines


def write_titles_file(plan: RenamePlan, settings: Settings) -> Path | None:
    """The items without an English title, for Codex to fill (filled ones are kept)."""
    if not plan.missing:
        return None
    path = titles_path(settings)
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    for ref, info in plan.missing.items():
        data.setdefault(ref, {"topic": info["topic"], "folder": info["folder"], "titleEn": ""})
    data["_note"] = ("PRD v6 weekly §6: write titleEn, an English short title of at most about "
                     "6 words, for each item; then: uv run ca outputs rename (dry run)")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


def apply_renames(plan: RenamePlan, settings: Settings,
                  conn: sqlite3.Connection | None = None) -> list[str]:
    """The real run: titles, Drive (top folders first), local folders, then the tracker."""
    from content_automation.storage import get_storage

    lines: list[str] = []
    for file, title in plan.titles.items():
        _store_title(file, title)
    storage = get_storage(settings)
    drive_done: list[Rename] = []
    for rename in sorted((r for r in plan.renames if r.where == "drive"),
                         key=lambda r: r.kind != "top"):
        path = _drive_path(rename, plan)
        try:
            if storage.name == "plugin":
                _plugin_rename(settings, path, rename.new)
                lines.append(f"Drive (plugin) {path} → {rename.new}: in {PLUGIN_MANIFEST} for "
                             "the Drive plugin")
            else:
                renamer = getattr(storage, "rename_folder", None)
                if renamer is None:
                    raise RuntimeError(f"{storage.name} cannot rename folders")
                renamer(path, rename.new)
                lines.append(f"Drive ({storage.name}) {path} → {rename.new}: renamed in place")
            drive_done.append(rename)
        except Exception as error:  # noqa: BLE001 - one failed folder never stops the rest
            lines.append(f"Drive {path}: NOT renamed ({error})")
    moved: dict[str, Path] = {}
    for rename in (r for r in plan.renames if r.where == "local"):
        try:
            moved[rename.ref] = (_rename_package(rename, settings, conn) if rename.kind ==
                                 "package" else _rename_youtube(rename, settings))
            lines.append(f"Local {rename.old} → {moved[rename.ref].name}")
        except (OSError, ValueError) as error:
            lines.append(f"Local {rename.old}: NOT renamed ({error})")
    lines += _tracker(drive_done, moved, settings, storage)
    return lines


def _drive_path(rename: Rename, plan: RenamePlan) -> str:
    """A child's Drive path after its top folder was renamed in this run."""
    for top in plan.renames:
        if top.kind == "top" and rename.kind != "top" and rename.old.startswith(top.old + "/"):
            return top.new + rename.old[len(top.old):]
    return rename.old


def _store_title(file: Path, title: str) -> None:
    data = json.loads(file.read_text(encoding="utf-8"))
    data["titleEn"] = title  # package.json and the YouTube metadata (both camelCase)
    atomic_write_text(file, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def _plugin_rename(settings: Settings, path: str, new_name: str) -> None:
    """The Drive plugin renames by folder ID (Codex); the known folder paths follow now."""
    from content_automation.storage.manifest import CREATED_FILE, known_folders

    folders = known_folders(settings)
    parent = path.rpartition("/")[0]
    new_path = f"{parent}/{new_name}" if parent else new_name
    folder_id = folders.get(path) or folders.get(new_path)
    if not folder_id:
        raise ValueError(f"no Drive folder ID known for {path}")
    target = settings.packages_dir / SYSTEM / PLUGIN_MANIFEST
    try:
        data: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"_note": "Rename each folder by its ID with the Google Drive plugin (same ID, "
                         "contents unchanged).", "entries": []}
    data["entries"].append({"action": "rename_folder", "folder_id": folder_id, "old": path,
                            "new_name": new_name, "done": False})
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    state = settings.state_dir / CREATED_FILE
    try:
        known: dict[str, str] = json.loads(state.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    renamed = {(new_path + key[len(path):] if key == path or key.startswith(path + "/")
                else key): value for key, value in known.items()}
    atomic_write_text(state, json.dumps(renamed, indent=2, ensure_ascii=False) + "\n")


def _rename_package(rename: Rename, settings: Settings,
                    conn: sqlite3.Connection | None) -> Path:
    from content_automation.content.calendar import read_calendar, write_calendar
    from content_automation.content.package import load_package, save_package, write_item_file
    from content_automation.registry import runtime
    from content_automation.registry.db import transaction
    from content_automation.registry.items import set_package_path

    folder = Path(rename.old)
    target = folder.with_name(rename.new)
    if target.exists():
        raise ValueError(f"{target} exists")
    owners = list(runtime.package_items(folder).values())
    folder.rename(target)
    package = load_package(target)
    package.package_id = target.name
    if package.tree_path:
        package.tree_path = f"{package.tree_path.rpartition('/')[0]}/{target.name}"
    save_package(target, package)
    write_item_file(target, package, rename.ref if rename.ref.startswith("BG-") else None)
    old, new = folder.as_posix(), target.as_posix()
    if conn is not None:
        for item_id in owners:
            set_package_path(conn, item_id, new)
        with transaction(conn):
            conn.execute("UPDATE versions SET package_path = ? WHERE package_path = ?",
                         (new, old))
    for path in sorted(settings.calendar_dir.glob("*.csv")):
        rows = read_calendar(path)
        if any(row.get("Package") in (old, str(folder)) for row in rows):
            for row in rows:
                if row.get("Package") in (old, str(folder)):
                    row["Package"] = new
            write_calendar(path, rows, force=True)
    drafts = settings.packages_dir / SYSTEM / "drafts"
    for marker in sorted(drafts.glob("*.moved.txt")) if drafts.is_dir() else []:
        if Path(marker.read_text(encoding="utf-8").strip()).as_posix() == old:
            atomic_write_text(marker, new + "\n")
    return target


def _rename_youtube(rename: Rename, settings: Settings) -> Path:
    from content_automation.youtube.topic import read_package, write_package

    folder = Path(rename.old)
    data = read_package(folder)
    target = folder.with_name(rename.new)
    if target != folder:
        if target.exists():
            raise ValueError(f"{target} exists")
        folder.rename(target)
    for old, new in rename.files:
        (target / old).rename(target / new)
    if rename.files:
        text = json.dumps(data, ensure_ascii=False)
        for old, new in rename.files:
            text = text.replace(json.dumps(old, ensure_ascii=False)[1:-1],
                                json.dumps(new, ensure_ascii=False)[1:-1])
        data = json.loads(text)
    write_package(target, data)  # the metadata names the new folder
    return target


def _tracker(drive: list[Rename], moved: dict[str, Path], settings: Settings,
             storage: Any) -> list[str]:
    """The tracker row of every renamed Drive item, with its link (failures reported)."""
    from content_automation.content.deliverables import load_deliverables
    from content_automation.content.package import load_package
    from content_automation.content.tracking import TrackerError, tracker_entry
    from content_automation.storage import (
        StorageError,
        StorageNotSetUpError,
        drive_folder_name,
        package_folder_key,
        registry_cells,
        update_tracker,
    )
    from content_automation.youtube.topic import read_package
    from content_automation.youtube.upload import tracker_row

    lines: list[str] = []
    catalog = load_deliverables(settings.deliverables_file)
    for rename in drive:
        if rename.kind == "top":
            continue
        folder = moved.get(rename.ref, rename.folder or Path(rename.old))
        try:
            if rename.kind == "youtube":
                data = read_package(folder)
                links = [f"{name}: {link}" for name, link in (data.get("uploads") or {}).items()]
                lines += tracker_row(storage, data, links, "uploaded (folder renamed)")
                continue
            package = load_package(folder)
            link = storage.folder_link(package_folder_key(package),
                                       drive_folder_name(folder, package))
            entry = tracker_entry(folder, package, catalog, link) | registry_cells(folder)
            lines.append(update_tracker(storage, [entry]))
        except (StorageError, StorageNotSetUpError, TrackerError, OSError, ValueError) as error:
            lines.append(f"Tracker NOT updated for {rename.ref} ({error})")
    return lines


def rename_on_copy(folder: Path, title_en: str, settings: Settings) -> Path:
    """The copy approval stored a new English title: a package not on Drive yet follows it
    right away (else `ca outputs rename` does it, Drive included)."""
    from content_automation.content.package import load_package, save_package
    from content_automation.registry import runtime

    package = load_package(folder)
    if package.title_en == title_en:
        return folder
    package.title_en = title_en
    save_package(folder, package)
    planned = package.planned_date or folder_date(folder.name)
    uploaded = any(record.status == "uploaded" for record in package.uploads.values())
    if not package.tree_path or planned is None or uploaded:
        return folder
    wanted = item_folder_name(title_en, planned)
    if _matches(folder.name, wanted):
        return folder
    taken = {path.name for path in folder.parent.iterdir() if path != folder}
    scope = runtime.current()
    rename = Rename("local", "package", _package_ref(folder, package.content_id),
                    folder.as_posix(), unique_name(wanted, taken), folder)
    return _rename_package(rename, settings, scope.conn if scope is not None else None)


__all__ = ["PLUGIN_MANIFEST", "TITLES_FILE", "Rename", "RenamePlan", "apply_renames",
           "plan_lines", "plan_renames", "rename_on_copy", "titles_path", "write_titles_file"]
