"""The output folder tree (PRD v6 R8): one place for every output path.

    outputs/
      Instagram/Carousels/<YYYY-MM>/<English Topic Title> <YYYY-MM-DD>/
      Facebook/Posts/<YYYY-MM>/<English Topic Title> <YYYY-MM-DD>/
      Facebook/Ads/<YYYY-MM>/<English Topic Title> <YYYY-MM-DD>/
      LinkedIn/Posts/<YYYY-MM>/<English Topic Title> <YYYY-MM-DD>/
      YouTube Long-Form/<English Topic Title> <YYYY-MM-DD>/Style A|B|C/
      YouTube Short-Form/<English Topic Title> <YYYY-MM-DD>/
      _system/  jobs/  previews/  test-runs/  logs/  drafts/  youtube/  rejected_legacy/

PRD v6 weekly (2026-10-22): every item folder is "<English Topic Title> <YYYY-MM-DD>" (the
item's titleEn, else its topic, then the planned date; " (2)" on a clash). The BG ID lives in
item.json / package.json and the tracker, not in the name. Folders made before keep their name
until `ca outputs rename` (a dry run first).

Each social package holds final/ (publish-ready images only: slide_01.png … for a carousel),
caption_de.txt, package.json and source/ (the raw model or Higgsfield images). The date is the
planned publish date; the slug is short, ASCII and lowercase. _system/ is internal and never
uploaded: drafts/ holds a package until its category and BG ID are known, youtube/ the YouTube
topics' metadata. The Drive upload mirrors the same relative paths.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from datetime import date
from pathlib import Path

OUTPUT_ROOT = Path("outputs")
SYSTEM = "_system"
SYSTEM_DIR = OUTPUT_ROOT / SYSTEM
JOBS_DIR = SYSTEM_DIR / "jobs"
PREVIEWS_DIR = SYSTEM_DIR / "previews"
TEST_RUNS_DIR = SYSTEM_DIR / "test-runs"
LOGS_DIR = SYSTEM_DIR / "logs"
DRAFTS_DIR = SYSTEM_DIR / "drafts"
YOUTUBE_META_DIR = SYSTEM_DIR / "youtube"
REVIEW_DIR = SYSTEM_DIR / "review"  # `ca outputs collect`: copies for quick viewing
REJECTED_LEGACY = "rejected_legacy"
YOUTUBE_DIR = "YouTube Long-Form"
YOUTUBE_SHORT_DIR = "YouTube Short-Form"
ITEM_FILE = "item.json"  # the BG ID, content ID, titleEn and date inside each item folder
TITLE_EN_LENGTH = 60
_DATE_AT_END = re.compile(r"(\d{4}-\d{2}-\d{2})(?: \(\d+\))?$")
# the social category -> its folder under outputs/ (and on Drive)
CATEGORY_DIRS: dict[str, str] = {
    "instagram_carousel": "Instagram/Carousels",
    "facebook_post": "Facebook/Posts",
    "facebook_ad": "Facebook/Ads",
    "linkedin_post": "LinkedIn/Posts",
}
FINAL_DIR = "final"
SOURCE_DIR = "source"
CAPTION_FILE = "caption_de.txt"
SLUG_LENGTH = 40
_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe",
                          "Ü": "ue"})
_WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)),
                     *(f"lpt{n}" for n in range(1, 10))}


def short_slug(text: str, length: int = SLUG_LENGTH) -> str:
    """Short, ASCII, lowercase; umlauts as ae/oe/ue/ss (a folder name, never audience text)."""
    ascii_text = unicodedata.normalize("NFKD", text.translate(_UMLAUTS)).encode(
        "ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return value[:length].rstrip("-") or "thema"


def safe_title(title: str, length: int = 80) -> str:
    """A readable folder name that is safe on Windows and Google Drive: no <>:"/\\|?* or control
    characters, no trailing dot or space, no reserved device name; umlauts are kept."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", unicodedata.normalize("NFC", title))
    cleaned = " ".join(cleaned.split())[:length].rstrip(" .")
    if not cleaned or cleaned.lower().split(".")[0] in _WINDOWS_RESERVED:
        cleaned = f"Thema {cleaned}".strip()
    return cleaned


def category_dir(root: Path, category: str) -> Path:
    found = CATEGORY_DIRS.get(category)
    if found is None:
        raise ValueError(f'unknown category "{category}" ({", ".join(CATEGORY_DIRS)})')
    return root / found


def item_folder_name(title_en: str, planned: date) -> str:
    """PRD v6 weekly §6: "<English Topic Title> <YYYY-MM-DD>" (safe on Windows and Drive)."""
    return f"{safe_title(title_en, TITLE_EN_LENGTH)} {planned:%Y-%m-%d}"


def unique_name(name: str, taken: set[str]) -> str:
    """The name, or "<name> (2)", "(3)" … when it is taken (case-insensitive)."""
    lowered = {value.lower() for value in taken}
    candidate, number = name, 1
    while candidate.lower() in lowered:
        number += 1
        candidate = f"{name} ({number})"
    return candidate


def folder_date(name: str) -> date | None:
    """The planned date of an item folder: at the end (v6 weekly), or at the start (before)."""
    found = _DATE_AT_END.search(name)
    for text in (found.group(1) if found else "", name[:10]):
        try:
            return date.fromisoformat(text)
        except ValueError:
            continue
    return None


def package_dir(root: Path, category: str, planned: date, bg_id: str, topic: str) -> Path:
    """outputs/<Platform>/<Kind>/<YYYY-MM>/<English Topic Title> <YYYY-MM-DD>/ (`topic`: the
    titleEn, else the topic; the BG ID stays in package.json and item.json)."""
    del bg_id
    return category_dir(root, category) / f"{planned:%Y-%m}" / item_folder_name(topic, planned)


def system_dir(root: Path) -> Path:
    return root / SYSTEM


def iter_package_files(root: Path) -> Iterator[Path]:
    """Every social package.json: the platform tree, the drafts, the old flat outputs/content/
    and the legacy rejected outputs moved by `ca outputs migrate` (so topics stay known)."""
    if not root.is_dir():
        return
    seen: set[Path] = set()
    for pattern in ("*/package.json", "content/*/package.json", "*/*/*/*/package.json",
                    f"{SYSTEM}/drafts/*/package.json",
                    f"{SYSTEM}/{REJECTED_LEGACY}/**/package.json"):
        for path in root.glob(pattern):
            if path not in seen and YOUTUBE_DIR not in path.parts and (
                    YOUTUBE_SHORT_DIR not in path.parts):
                seen.add(path)
                yield path


def collect_final(root: Path, week: str | None = None) -> list[tuple[Path, Path]]:
    """`ca outputs collect`: every passed final image of the platform tree (a package part with
    status done, its final/ files) copied to outputs/_system/review/<YYYY-Www>/<file>, prefixed
    with the package folder name; the week comes from the folder's planned date. Copies only:
    the package keeps its files. Returns (source, copy) pairs."""
    import json
    import shutil

    copied: list[tuple[Path, Path]] = []
    for category in CATEGORY_DIRS.values():
        for package in sorted((root / category).glob("*/*/package.json")):
            folder = package.parent
            planned = folder_date(folder.name)
            try:
                data = json.loads(package.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if planned is None:
                continue
            year, number, _ = planned.isocalendar()
            label = f"{year}-W{number:02d}"
            if week is not None and label != week:
                continue
            items = data.get("items") if isinstance(data, dict) else None
            for item in (items or {}).values():
                if not isinstance(item, dict) or item.get("status") != "done":
                    continue
                for name in item.get("files") or []:
                    source = folder / str(name)
                    if source.parent.name != FINAL_DIR or not source.is_file():
                        continue
                    target = root / SYSTEM / "review" / label / f"{folder.name}_{source.name}"
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    copied.append((source, target))
    return copied


__all__ = ["CAPTION_FILE", "CATEGORY_DIRS", "DRAFTS_DIR", "FINAL_DIR", "ITEM_FILE", "JOBS_DIR",
           "LOGS_DIR", "YOUTUBE_SHORT_DIR", "folder_date", "item_folder_name", "unique_name",
           "OUTPUT_ROOT", "PREVIEWS_DIR", "REJECTED_LEGACY", "SOURCE_DIR", "SYSTEM",
           "REVIEW_DIR", "SYSTEM_DIR", "TEST_RUNS_DIR", "YOUTUBE_DIR", "YOUTUBE_META_DIR",
           "category_dir", "collect_final", "iter_package_files", "package_dir", "safe_title",
           "short_slug", "system_dir"]
