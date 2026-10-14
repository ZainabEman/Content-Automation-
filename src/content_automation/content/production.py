"""YouTube and podcast production (Phase 8 Step 1).

Production status (youtube and podcast items): not_started -> awaiting_recording (when the
current version's script and production brief checks passed) -> recorded -> editing -> edited
-> final. Going back to editing needs a review revise (a new version). At final the generation
counts as generated, so the review gate opens.

- `ca import BG-x <file> --as recording|edit|final|thumbnail|audio`: a copy goes to
  `versions/v<n>/production/<as>/` (the original is never changed), checked first (it decodes;
  a YouTube final is 16:9 and at least 1080p), registered as an artifact; recording, edit and
  final move the status.
- `ca handoff BG-x --to "<name>"`: a `handoff/` folder for the editor (script.md, brief.md, the
  B-roll list, the assets list, a README) and production -> editing.
"""

import json
import shutil
import sqlite3
from calendar import monthrange
from datetime import date
from pathlib import Path
from typing import Any

from PIL import Image

from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.core.media import MediaError, probe_media
from content_automation.registry.artifacts import (
    ArtifactType,
    add_artifact,
    latest_artifact,
    list_artifacts,
)
from content_automation.registry.db import RegistryError, transaction
from content_automation.registry.items import Item, get_item, list_items, set_status
from content_automation.registry.progress import part_done
from content_automation.registry.versions import start_new_version

PRODUCTION_KINDS = ("youtube", "podcast")
IMPORT_MOVES = {"recording": "recorded", "edit": "edited", "final": "final"}
IMPORT_TYPES = ("recording", "edit", "final", "thumbnail", "audio")


def production_config(settings: Settings) -> dict[str, Any]:
    try:
        data = json.loads(settings.production_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def produced_item(conn: sqlite3.Connection, ref: str) -> Item:
    item = get_item(conn, ref)
    if item.kind not in PRODUCTION_KINDS:
        raise RegistryError(f"{item.id} is a {item.kind}: production is for youtube and podcast "
                            "items.")
    return item


def base_dir(settings: Settings, item: Item) -> Path:
    if item.package_path:
        return Path(item.package_path)
    return settings.output_dir / "items" / item.id


def version_dir(settings: Settings, item: Item) -> Path:
    return base_dir(settings, item) / "versions" / f"v{item.current_version}"


def start_if_ready(conn: sqlite3.Connection, ref: str, *, command: str | None = None
                   ) -> str | None:
    """not_started -> awaiting_recording once the script and brief of the current version
    passed their checks; the line to show, or None."""
    item = get_item(conn, ref)
    if item.kind not in PRODUCTION_KINDS or item.production_status != "not_started":
        return None
    checked = [latest_artifact(conn, item.id, kind, item.current_version)
               for kind in ("script", "brief")]
    if not all(found is not None and found.check.get("ok") for found in checked):
        return None
    set_status(conn, item.id, "production", "awaiting_recording", command=command)
    return f"{item.id}: production awaiting_recording (script and brief checked)."


def set_production(conn: sqlite3.Connection, ref: str, target: str, *,
                   command: str | None = None) -> list[str]:
    """`ca production set`: only the legal moves; back to editing needs a review revise."""
    with transaction(conn):
        item = produced_item(conn, ref)
        before = item.production_status
        new_version = False
        if target == "editing" and before in ("edited", "final"):
            if item.review_status != "changes_requested":
                raise RegistryError(f"{item.id}: back to editing needs a revise first: uv run "
                                    f'ca item revise {item.id} "<feedback>"')
            start_new_version(conn, item.id, command=command)
            new_version = True
        item = set_status(conn, item.id, "production", target, new_version=new_version,
                          actor="user", command=command)
        lines = [f"{item.id} production: {before} → {target} (v{item.current_version})"]
        if target == "final" and item.generation_status != "generated":
            part_done(conn, item.id, command=command)
            lines.append(f"{item.id}: final — the review gate is open (ca review show "
                         f"{item.id}).")
        return lines


def production_lines(conn: sqlite3.Connection, settings: Settings, month: str | None
                     ) -> list[str]:
    days: tuple[date, date] | None = None
    if month:
        year, number = (int(part) for part in month.split("-"))
        days = (date(year, number, 1), date(year, number, monthrange(year, number)[1]))
    items = [item for item in list_items(conn) if item.kind in PRODUCTION_KINDS
             and (days is None or (item.planned_date is not None
                                   and days[0] <= item.planned_date <= days[1]))]
    lines = [f"{item.id} {item.kind} v{item.current_version} {item.production_status:<18} "
             f"{item.planned_date or '—'} {item.title}" for item in items]
    targets = production_config(settings).get("targetsPerMonth", {"youtube": 8})
    for kind, target in targets.items():
        finals = sum(item.kind == kind and item.production_status == "final" for item in items)
        lines.append(f"{kind}: {finals} final of {target}" + (f" in {month}" if month else "")
                     + (" — target met" if finals >= int(target) else ""))
    return lines


def _check_media(settings: Settings, item: Item, path: Path, kind: str) -> list[str]:
    if kind == "thumbnail":
        try:
            with Image.open(path) as opened:
                opened.load()
        except OSError as error:
            return [f"not a readable image ({error})"]
        return []
    try:
        info = probe_media(path)
    except MediaError as error:
        return [f"does not decode ({error})"]
    if info.duration_sec is None:
        return ["does not decode (no duration)"]
    if kind == "final" and item.kind == "youtube":
        rules = production_config(settings).get("youtubeFinal", {})
        min_height = int(rules.get("minHeight", 1080))
        width, height = info.width or 0, info.height or 0
        problems = []
        if height < min_height:
            problems.append(f"{width}x{height}: a YouTube final needs at least {min_height}p")
        if height and abs(width / height - 16 / 9) > 0.01:
            problems.append(f"{width}x{height} is not 16:9")
        return problems
    return []


def import_media(conn: sqlite3.Connection, settings: Settings, ref: str, file: Path,
                 kind: str, *, command: str | None = None) -> list[str]:
    if kind not in IMPORT_TYPES:
        raise RegistryError(f"--as must be {', '.join(IMPORT_TYPES)}, not {kind}.")
    if not file.is_file():
        raise RegistryError(f"File not found: {file}")
    item = produced_item(conn, ref)
    target = IMPORT_MOVES.get(kind)
    if target is not None:  # refuse before copying when the move is not allowed
        expected = {"recorded": "awaiting_recording", "edited": "editing",
                    "final": "edited"}[target]
        if item.production_status != expected:
            raise RegistryError(f"{item.id}: production is {item.production_status}; --as {kind} "
                                f"needs {expected}.")
    problems = _check_media(settings, item, file, kind)
    if problems:
        raise RegistryError(f"{file.name} not imported: {'; '.join(problems)}")
    folder = version_dir(settings, item) / "production" / kind
    folder.mkdir(parents=True, exist_ok=True)
    copy = folder / file.name
    shutil.copy2(file, copy)
    add_artifact(conn, item.id, item.current_version, kind_type(kind), copy.as_posix(),
                 {"ok": True, "source": file.resolve().as_posix()}, actor="user",
                 command=command)
    lines = [f"{item.id} v{item.current_version}: {kind} imported to {copy.as_posix()} "
             "(the original is unchanged)"]
    if target is not None:
        lines += set_production(conn, item.id, target, command=command)
    return lines


def kind_type(kind: str) -> ArtifactType:
    found: dict[str, ArtifactType] = {"recording": "recording", "edit": "edit", "final": "final",
                                      "thumbnail": "thumbnail", "audio": "audio"}
    return found[kind]


def handoff(conn: sqlite3.Connection, settings: Settings, ref: str, editor: str, *,
            command: str | None = None) -> list[str]:
    item = produced_item(conn, ref)
    if item.production_status != "recorded":
        raise RegistryError(f"{item.id}: production is {item.production_status}; a handoff "
                            "follows the recording (recorded).")
    folder = version_dir(settings, item) / "handoff"
    folder.mkdir(parents=True, exist_ok=True)
    copied = []
    pairs: tuple[tuple[ArtifactType, str], ...] = (("script", "script.md"), ("brief", "brief.md"))
    for kind, name in pairs:
        found = latest_artifact(conn, item.id, kind, item.current_version)
        source = Path(found.path).with_name(name) if found else None
        if source is not None and source.is_file():
            shutil.copy2(source, folder / name)
            copied.append(name)
    brief: dict[str, Any] = {}
    found_brief = latest_artifact(conn, item.id, "brief", item.current_version)
    if found_brief is not None:
        try:
            brief = json.loads(Path(found_brief.path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            brief = {}
    broll = [f"- {b.get('section')}: {b.get('description')} [{b.get('sourceHint')}]"
             for b in brief.get("bRoll", [])]
    media = [f"- {a.type}: {a.path}" for a in list_artifacts(conn, item.id)
             if a.version == item.current_version and a.type in IMPORT_TYPES]
    assets = [f"- {asset}" for asset in brief.get("assetsNeeded", [])]
    atomic_write_text(folder / "broll.md", "# B-roll\n\n" + ("\n".join(broll) or "none") + "\n")
    atomic_write_text(folder / "assets.md", "# Assets\n\n" + "\n".join(
        [*assets, *media] or ["none"]) + "\n")
    atomic_write_text(folder / "README.md", (
        f"# Handoff: {item.title}\n\n{item.id} v{item.current_version}, for {editor}.\n\n"
        "Files: script.md, brief.md, broll.md (B-roll per section), assets.md (assets needed "
        "and the imported recording).\n\nReturn the edit; it is imported with "
        f"`uv run ca import {item.id} <file> --as edit`.\n"))
    add_artifact(conn, item.id, item.current_version, "handoff", folder.as_posix(),
                 {"ok": True, "to": editor, "files": copied}, actor="user", command=command)
    lines = [f"{item.id}: handoff for {editor} in {folder.as_posix()} "
             f"({', '.join([*copied, 'broll.md', 'assets.md', 'README.md'])})"]
    return lines + set_production(conn, item.id, "editing", command=command)
