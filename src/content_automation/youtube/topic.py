"""YouTube config, the topic folder (R9.11) and its package.json.

PRD v6 weekly (2026-10-22): two formats (config/youtube.json formats): "long" (Roman only, 3
styles, one subfolder each) and "short" (HOST + ROMAN dialogue, one style, the files directly in
the topic folder). Topic folders are "<English Topic Title> <YYYY-MM-DD>" under the format's
outputDir; the metadata (format, titleEn, plannedDate, BG ID) stays in _system/youtube/."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from content_automation.core.files import atomic_write_text
from content_automation.core.output_tree import SYSTEM, item_folder_name, unique_name

CONFIG_FILE = Path("config/youtube.json")
LONG, SHORT = "long", "short"  # the two script pipelines (formats)
PACKAGE_FILE = "package.json"  # legacy (v5): the metadata now lives in _system/youtube/
RESEARCH_FILE = "research.txt"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe",
                          "Ü": "ue"})


class YoutubeError(ValueError):
    """A YouTube step cannot run (a missing file, a failed check, a bad reference)."""


@dataclass(frozen=True)
class Style:
    key: str
    folder: str
    name: str
    approach: str


@lru_cache(maxsize=4)
def load_config(path: Path = CONFIG_FILE) -> dict[str, Any]:
    found = path if path.is_file() else _PROJECT_ROOT / path
    data = json.loads(found.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise YoutubeError(f"{path} must be a JSON object")
    return data


def format_config(fmt: str = LONG) -> dict[str, Any]:
    """formats.long|short of config/youtube.json (prompt, word target, presenter, styles)."""
    found = load_config().get("formats", {}).get(fmt)
    if not isinstance(found, dict):
        raise YoutubeError(f'format "{fmt}": use short or long (config/youtube.json formats)')
    return found


def format_of(data: dict[str, Any]) -> str:
    """The topic's format from its metadata; topics made before v6 weekly are long-form."""
    return str(data.get("format") or LONG)


def styles(fmt: str = LONG) -> dict[str, Style]:
    keys = [str(key) for key in format_config(fmt).get("styles", ["A", "B", "C"])]
    return {key: Style(key, str(value["folder"]), str(value["name"]), str(value["approach"]))
            for key, value in load_config()["styles"].items() if key in keys}


def slug(text: str, max_length: int = 48) -> str:
    """A file-safe slug; German umlauts as ae/oe/ue/ss (a file name, never audience text)."""
    value = re.sub(r"[^a-z0-9]+", "-", text.translate(_UMLAUTS).lower()).strip("-")
    return value[:max_length].rstrip("-") or "thema"


def output_root(fmt: str = LONG) -> Path:
    found = format_config(fmt).get("outputDir") if fmt != LONG else (
        format_config(fmt).get("outputDir") or load_config().get("outputDir"))
    return Path(str(found or "outputs/YouTube Long-Form"))


def _base(fmt: str, root: Path | None) -> Path:
    """The format's topic root; `root` (tests) names the long-form root, the short one is its
    sibling."""
    if root is None:
        return output_root(fmt)
    return root if fmt == LONG else root.parent / output_root(fmt).name


def meta_dir(root: Path | None = None) -> Path:
    """Where the topics' metadata lives (outside the visible tree): <outputs>/_system/youtube/."""
    return (root or output_root()).parent / SYSTEM / "youtube"


def _meta_file(bg_id: str, root: Path | None = None) -> Path:
    return meta_dir(root) / f"{bg_id}.json"


def topic_folder(month: str, bg_id: str, title: str, root: Path | None = None, *,
                 fmt: str = LONG, title_en: str | None = None,
                 planned: date | None = None) -> Path:
    """The topic's folder "<English Topic Title> <YYYY-MM-DD>" (PRD v6 weekly §6), safe for
    Windows and Drive, under the format's root. A re-run for the same BG ID gets its own folder
    back; another topic with the same name gets "<name> (2)"."""
    base = _base(fmt, root)
    known = _meta_file(bg_id, root)
    if known.is_file():
        data = json.loads(known.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("folder"):
            return _base(format_of(data), root) / str(data["folder"])
    name = item_folder_name(title_en or title, planned or date.fromisoformat(f"{month}-01"))
    taken = {str(json.loads(path.read_text(encoding="utf-8")).get("folder", ""))
             for path in meta_dir(root).glob("*.json")} if meta_dir(root).is_dir() else set()
    taken |= {path.name for path in base.iterdir()} if base.is_dir() else set()
    return base / unique_name(name, taken)


def find_folder(bg_id: str, root: Path | None = None) -> Path:
    path = _meta_file(bg_id, root)
    if not path.is_file():
        raise YoutubeError(f"{bg_id}: no YouTube topic folder (plan it first: "
                           "uv run ca youtube plan <YYYY-MM>)")
    data = json.loads(path.read_text(encoding="utf-8"))
    return _base(format_of(data), root) / str(data["folder"])


def _meta_for(folder: Path) -> Path:
    """The metadata file of a topic folder (it names its folder)."""
    for path in sorted(meta_dir(folder.parent).glob("*.json")) if meta_dir(
            folder.parent).is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("folder") == folder.name and (
                output_root(format_of(data)).name == folder.parent.name):
            return path
    raise YoutubeError(f"{folder}: no metadata in {meta_dir(folder.parent)} (plan the topic "
                       "first)")


def read_package(folder: Path) -> dict[str, Any]:
    path = _meta_for(folder)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise YoutubeError(f"{path} is not readable: {error}") from None
    if not isinstance(data, dict):
        raise YoutubeError(f"{path} must be a JSON object")
    return data


def write_package(folder: Path, data: dict[str, Any]) -> None:
    data["updatedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
    data["folder"] = folder.name
    folder.mkdir(parents=True, exist_ok=True)
    target = _meta_file(str(data["bgId"]), folder.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def briefs_dir(folder: Path) -> Path:
    """The writer's internal style briefs: in the metadata folder, never in the topic tree."""
    return meta_dir(folder.parent) / str(read_package(folder)["bgId"]) / "briefs"


def research_file(folder: Path) -> Path:
    return folder / RESEARCH_FILE


def versions(path: Path) -> list[Path]:
    """The file and its later versions (<name>_v2.txt …) that exist, oldest first."""
    found = [path] if path.exists() else []
    number = 2
    while (candidate := path.with_name(f"{path.stem}_v{number}{path.suffix}")).exists():
        found.append(candidate)
        number += 1
    return found


def latest(path: Path) -> Path:
    """The newest version of a file (the file itself when there is no other)."""
    found = versions(path)
    return found[-1] if found else path


def write_versioned(path: Path, text: str) -> tuple[Path, str]:
    """Write a new file, keep an unchanged one, and never overwrite a changed one: the new text
    goes to the next <name>_vN file (R7: re-runs never overwrite silently)."""
    current = latest(path)
    if not current.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, text)
        return path, "written"
    if current.read_text(encoding="utf-8") == text:
        return current, "unchanged"
    number = len(versions(path)) + 1
    target = path.with_name(f"{path.stem}_v{number}{path.suffix}")
    atomic_write_text(target, text)
    return target, f"new version (the earlier {current.name} is kept)"


def style_dir(folder: Path, key: str, fmt: str = LONG) -> Path:
    """The style's folder; short-form has one style whose files sit in the topic folder."""
    found = styles(fmt).get(key.upper())
    if found is None:
        raise YoutubeError(f'style "{key}": use {", ".join(styles(fmt))}')
    return folder / found.folder if found.folder else folder


__all__ = ["CONFIG_FILE", "LONG", "PACKAGE_FILE", "RESEARCH_FILE", "SHORT", "Style", "YoutubeError",
           "briefs_dir", "find_folder", "format_config", "format_of", "latest", "load_config",
           "meta_dir", "output_root", "read_package",
           "research_file", "slug", "style_dir", "styles", "topic_folder", "versions",
           "write_package", "write_versioned"]
