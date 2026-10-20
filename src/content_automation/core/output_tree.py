"""The output folder tree (PRD v6 R8): one place for every output path.

    outputs/
      Instagram/Carousels/<YYYY-MM>/<YYYY-MM-DD>_<BG-ID>_<short-slug>/
      Facebook/Posts/<YYYY-MM>/<YYYY-MM-DD>_<BG-ID>_<short-slug>/
      Facebook/Ads/<YYYY-MM>/<YYYY-MM-DD>_<BG-ID>_<short-slug>/
      LinkedIn/Posts/<YYYY-MM>/<YYYY-MM-DD>_<BG-ID>_<short-slug>/
      YouTube Long-Form/<Topic Name>/
      _system/  jobs/  previews/  test-runs/  logs/  drafts/  youtube/  rejected_legacy/

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


def package_dir(root: Path, category: str, planned: date, bg_id: str, topic: str) -> Path:
    """outputs/<Platform>/<Kind>/<YYYY-MM>/<YYYY-MM-DD>_<BG-ID>_<short-slug>/"""
    return (category_dir(root, category) / f"{planned:%Y-%m}"
            / f"{planned:%Y-%m-%d}_{bg_id}_{short_slug(topic)}")


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
            if path not in seen and YOUTUBE_DIR not in path.parts:
                seen.add(path)
                yield path


def collect_final(root: Path, week: str | None = None) -> list[tuple[Path, Path]]:
    """`ca outputs collect`: every passed final image of the platform tree (a package part with
    status done, its final/ files) copied to outputs/_system/review/<YYYY-Www>/<file>, prefixed
    with the package folder name; the week comes from the folder's planned date. Copies only:
    the package keeps its files. Returns (source, copy) pairs."""
    import json
    import shutil
    from datetime import date

    copied: list[tuple[Path, Path]] = []
    for category in CATEGORY_DIRS.values():
        for package in sorted((root / category).glob("*/*/package.json")):
            folder = package.parent
            try:
                planned = date.fromisoformat(folder.name[:10])
                data = json.loads(package.read_text(encoding="utf-8"))
            except (OSError, ValueError):
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


__all__ = ["CAPTION_FILE", "CATEGORY_DIRS", "DRAFTS_DIR", "FINAL_DIR", "JOBS_DIR", "LOGS_DIR",
           "OUTPUT_ROOT", "PREVIEWS_DIR", "REJECTED_LEGACY", "SOURCE_DIR", "SYSTEM",
           "REVIEW_DIR", "SYSTEM_DIR", "TEST_RUNS_DIR", "YOUTUBE_DIR", "YOUTUBE_META_DIR",
           "category_dir", "collect_final", "iter_package_files", "package_dir", "safe_title",
           "short_slug", "system_dir"]
