"""YouTube config, the topic folder (R9.11) and its package.json."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from content_automation.core.files import atomic_write_text

CONFIG_FILE = Path("config/youtube.json")
PACKAGE_FILE = "package.json"
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


def styles() -> dict[str, Style]:
    return {key: Style(key, str(value["folder"]), str(value["name"]), str(value["approach"]))
            for key, value in load_config()["styles"].items()}


def slug(text: str, max_length: int = 48) -> str:
    """A file-safe slug; German umlauts as ae/oe/ue/ss (a file name, never audience text)."""
    value = re.sub(r"[^a-z0-9]+", "-", text.translate(_UMLAUTS).lower()).strip("-")
    return value[:max_length].rstrip("-") or "thema"


def output_root() -> Path:
    return Path(str(load_config().get("outputDir", "outputs/youtube")))


def topic_folder(month: str, bg_id: str, title: str, root: Path | None = None) -> Path:
    return (root or output_root()) / month / f"{bg_id}_{slug(title)}"


def find_folder(bg_id: str, root: Path | None = None) -> Path:
    found = sorted((root or output_root()).glob(f"*/{bg_id}_*/{PACKAGE_FILE}"))
    if not found:
        raise YoutubeError(f"{bg_id}: no YouTube topic folder (plan it first: "
                           "uv run ca youtube plan <YYYY-MM>)")
    return found[0].parent


def read_package(folder: Path) -> dict[str, Any]:
    path = folder / PACKAGE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise YoutubeError(f"{path} is not readable: {error}") from None
    if not isinstance(data, dict):
        raise YoutubeError(f"{path} must be a JSON object")
    return data


def write_package(folder: Path, data: dict[str, Any]) -> None:
    data["updatedAt"] = datetime.now(UTC).isoformat(timespec="seconds")
    folder.mkdir(parents=True, exist_ok=True)
    atomic_write_text(folder / PACKAGE_FILE, json.dumps(data, indent=2, ensure_ascii=False)
                      + "\n")


def research_file(folder: Path) -> Path:
    data = read_package(folder)
    return folder / f"research_{data['slug']}.txt"


def style_dir(folder: Path, key: str) -> Path:
    found = styles().get(key.upper())
    if found is None:
        raise YoutubeError(f'style "{key}": use A, B or C')
    return folder / found.folder


__all__ = ["CONFIG_FILE", "PACKAGE_FILE", "Style", "YoutubeError", "find_folder", "load_config",
           "output_root", "read_package", "research_file", "slug", "style_dir", "styles",
           "topic_folder", "write_package"]
