"""Scan REFERENCES_DIR in place, write set.json files, and pick references for workflows.

Originals are never moved or deleted. The scanner only writes set.json and the
copies in each set's _resized/ folder.
"""

import hashlib
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from content_automation.ai.image import ReferenceImage
from content_automation.core.config import load_settings
from content_automation.references.models import (
    REF_TYPES,
    RESIZED_DIR,
    SET_FILE,
    RefAsset,
    ReferenceSet,
    RefType,
)

SUPPORTED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp"})
IMAGE_LIKE_SUFFIXES = SUPPORTED_SUFFIXES | {
    ".svg", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".heif", ".avif",
}
VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"})
IGNORED_FILES = frozenset({SET_FILE, "thumbs.db", "desktop.ini", ".ds_store"})
PILLOW_FORMATS = frozenset({"JPEG", "MPO", "PNG", "WEBP"})
MIN_SHORT_SIDE: dict[str, int] = {"brand": 256}
DEFAULT_MIN_SHORT_SIDE = 512
MAX_LONG_SIDE = 1536
PRIMARY_COUNT = 4
_ASSET_ID = re.compile(r"[0-9a-f]{12}")


class ReferenceLibraryError(ValueError):
    """A reference set is missing, ambiguous, or cannot be changed as asked."""


@dataclass
class SkippedFolder:
    path: str
    reason: str


@dataclass
class ScanReport:
    sets: list[ReferenceSet] = field(default_factory=list)
    skipped: list[SkippedFolder] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _root(root: Path | None) -> Path:
    return root if root is not None else load_settings(create_directories=False).references_dir


def natural_key(name: str) -> list[int | str]:
    """Sort 2.jpg before 10.jpg."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", name.casefold())]


def asset_id_for(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def scan(root: Path | None = None) -> ScanReport:
    """Register every set folder under REFERENCES_DIR and refresh its set.json."""
    root = _root(root)
    if not root.is_dir():
        raise ReferenceLibraryError(f"REFERENCES_DIR folder not found: {root}")
    report = ScanReport()
    for child in sorted(root.iterdir(), key=lambda p: natural_key(p.name)):
        if child.name.startswith(".") or child.name.casefold() in IGNORED_FILES:
            continue
        if child.is_dir() and child.name not in REF_TYPES:
            report.warnings.append(
                f"Folder '{child.name}' ignored: top-level folders must be "
                f"{', '.join(REF_TYPES)}."
            )
        elif child.is_file() and child.name != "brand.json":
            report.warnings.append(f"File '{child.name}' ignored: put it inside a set folder.")

    now = datetime.now(UTC)
    for ref_type in REF_TYPES:
        type_dir = root / ref_type
        if not type_dir.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(type_dir):
            dirnames[:] = sorted(
                (d for d in dirnames if d != RESIZED_DIR and not d.startswith(".")),
                key=natural_key,
            )
            folder = Path(dirpath)
            files = sorted((f for f in filenames if _is_candidate(f)), key=natural_key)
            has_images = any(Path(f).suffix.lower() in IMAGE_LIKE_SUFFIXES for f in files)
            relative = folder.relative_to(root).as_posix()
            if folder == type_dir:
                if has_images:
                    report.warnings.append(
                        f"Images directly in {ref_type}/ are ignored; "
                        f"move them into a set folder such as {ref_type}/<name>/."
                    )
                continue
            if not has_images:
                if files:
                    report.skipped.append(SkippedFolder(relative, _no_images_reason(files)))
                stale = folder / SET_FILE
                if stale.is_file():
                    stale.unlink()
                    report.warnings.append(f"{relative}: no images left, old set.json removed.")
                continue
            report.sets.append(_scan_set(folder, relative, ref_type, files, now))
    return report


def _is_candidate(name: str) -> bool:
    return not name.startswith(".") and name.casefold() not in IGNORED_FILES


def _no_images_reason(files: list[str]) -> str:
    counts = Counter(Path(f).suffix.lower().lstrip(".") or "no extension" for f in files)
    summary = ", ".join(f"{count} {ext}" for ext, count in sorted(counts.items()))
    return f"no JPG/PNG/WebP images ({summary})"


def _load_previous(folder: Path) -> dict[str, RefAsset]:
    set_file = folder / SET_FILE
    if not set_file.is_file():
        return {}
    try:
        previous = ReferenceSet.load(set_file)
    except (OSError, ValueError):
        return {}
    return {asset.asset_id: asset for asset in previous.ok_assets}


def _scan_set(
    folder: Path, set_id: str, ref_type: RefType, files: list[str], now: datetime
) -> ReferenceSet:
    previous = _load_previous(folder)
    resized_dir = folder / RESIZED_DIR
    assets: list[RefAsset] = []
    seen: dict[str, str] = {}
    for name in files:
        path = folder / name
        asset_id = asset_id_for(path)
        if asset_id in seen:
            reason = f"duplicate of {seen[asset_id]}"
            assets.append(RefAsset(asset_id=asset_id, file=name, status="rejected", reason=reason))
            continue
        seen[asset_id] = name
        asset = _check_and_copy(path, asset_id, ref_type, resized_dir)
        old = previous.get(asset_id)
        if ref_type == "identity" and asset.status == "ok" and old is not None:
            asset.primary = old.primary
        assets.append(asset)

    ok_assets = [asset for asset in assets if asset.status == "ok"]
    if ref_type == "identity" and not any(asset.primary for asset in ok_assets):
        for asset in ok_assets[:PRIMARY_COUNT]:
            asset.primary = True

    _remove_orphan_copies(resized_dir, {asset.resized for asset in ok_assets if asset.resized})
    ref_set = ReferenceSet(
        set_id=set_id, name=folder.name, type=ref_type, scanned_at=now, assets=assets
    )
    ref_set._folder = folder
    ref_set.save()
    return ref_set


def _unsupported_reason(suffix: str) -> str:
    if suffix == ".svg":
        return "SVG (vector) is not supported; export it as PNG"
    if suffix == ".pdf":
        return "PDF is not supported; export the pages as PNG or JPG"
    if suffix in VIDEO_SUFFIXES:
        return "video files are not supported"
    label = suffix.lstrip(".").upper() or "files without an extension"
    return f"{label} is not supported; use JPG, PNG or WebP"


def _check_and_copy(path: Path, asset_id: str, ref_type: RefType, resized_dir: Path) -> RefAsset:
    def rejected(reason: str, size: tuple[int, int] | None = None) -> RefAsset:
        return RefAsset(
            asset_id=asset_id,
            file=path.name,
            width=size[0] if size else None,
            height=size[1] if size else None,
            status="rejected",
            reason=reason,
        )

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        return rejected(_unsupported_reason(suffix))
    try:
        with Image.open(path) as source:
            image_format = source.format or "unknown"
            if image_format not in PILLOW_FORMATS:
                return rejected(f"file content is {image_format}, not JPG/PNG/WebP")
            image = ImageOps.exif_transpose(source)
            image.load()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
        return rejected("cannot be read as an image (damaged or not really an image)")

    width, height = image.size
    min_side = MIN_SHORT_SIDE.get(ref_type, DEFAULT_MIN_SHORT_SIDE)
    if min(width, height) < min_side:
        return rejected(
            f"too small: {width}x{height}px (short side must be at least {min_side}px)",
            (width, height),
        )

    has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
    extension = "png" if image_format == "PNG" or has_alpha else "jpg"
    resized = f"{RESIZED_DIR}/{asset_id}.{extension}"
    target = path.parent / resized
    if not target.is_file():
        try:
            _write_copy(image, target, extension)
        except (OSError, ValueError):
            return rejected("could not be converted to a resized copy", (width, height))
    return RefAsset(
        asset_id=asset_id,
        file=path.name,
        resized=resized,
        width=width,
        height=height,
        status="ok",
    )


def _write_copy(image: Image.Image, target: Path, extension: str) -> None:
    copy = image.copy()
    if max(copy.size) > MAX_LONG_SIDE:
        copy.thumbnail((MAX_LONG_SIDE, MAX_LONG_SIDE), Image.Resampling.LANCZOS)
    target.parent.mkdir(exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    try:
        if extension == "jpg":
            copy.convert("RGB").save(temporary, format="JPEG", quality=90, optimize=True)
        else:
            if copy.mode not in ("RGB", "RGBA", "L", "LA", "P"):
                copy = copy.convert("RGBA")
            copy.save(temporary, format="PNG", optimize=True)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _remove_orphan_copies(resized_dir: Path, keep: set[str]) -> None:
    """Delete generated copies whose original is gone (only files named <assetId>.<ext>)."""
    if not resized_dir.is_dir():
        return
    for copy in resized_dir.iterdir():
        if _ASSET_ID.fullmatch(copy.stem) and f"{RESIZED_DIR}/{copy.name}" not in keep:
            copy.unlink()


def list_sets(ref_type: RefType | None = None, root: Path | None = None) -> list[ReferenceSet]:
    """Return scanned sets (from set.json files), optionally of one type."""
    root = _root(root)
    if not root.is_dir():
        return []
    sets = []
    for set_file in root.rglob(SET_FILE):
        if RESIZED_DIR in set_file.parts:
            continue
        try:
            ref_set = ReferenceSet.load(set_file)
        except (OSError, ValueError):
            continue
        if ref_type is None or ref_set.type == ref_type:
            sets.append(ref_set)
    return sorted(sets, key=lambda s: (REF_TYPES.index(s.type), natural_key(s.set_id)))


def load_set(set_id: str, root: Path | None = None) -> ReferenceSet:
    """Find a set by full ID (identity/person_01) or by its unique folder name (person_01)."""
    sets = list_sets(root=root)
    wanted = set_id.strip("/")
    for ref_set in sets:
        if ref_set.set_id == wanted:
            return ref_set
    matches = [s for s in sets if s.name == wanted or s.set_id.endswith(f"/{wanted}")]
    if len(matches) == 1:
        return matches[0]
    if matches:
        options = ", ".join(s.set_id for s in matches)
        raise ReferenceLibraryError(f"Set '{set_id}' is ambiguous; use one of: {options}.")
    raise ReferenceLibraryError(
        f"Set '{set_id}' not found. Run `ca refs scan`, then `ca refs list` to see set IDs."
    )


def set_primary(set_id: str, files: list[str], root: Path | None = None) -> ReferenceSet:
    """Make exactly these files the primary identity photos of a set (1 to 4 files)."""
    ref_set = load_set(set_id, root)
    if ref_set.type != "identity":
        raise ReferenceLibraryError(
            f"Primary photos apply to identity sets only; {ref_set.set_id} is {ref_set.type}."
        )
    names = [name.strip() for name in files if name.strip()]
    if not 1 <= len(names) <= PRIMARY_COUNT:
        raise ReferenceLibraryError(f"Choose 1 to {PRIMARY_COUNT} primary photos.")
    if len(set(names)) != len(names):
        raise ReferenceLibraryError("The same file is listed twice.")
    by_file = {asset.file: asset for asset in ref_set.assets}
    unknown = [name for name in names if name not in by_file]
    if unknown:
        raise ReferenceLibraryError(f"Not in {ref_set.set_id}: {', '.join(unknown)}.")
    unusable = [name for name in names if by_file[name].status != "ok"]
    if unusable:
        raise ReferenceLibraryError(f"Rejected files cannot be primary: {', '.join(unusable)}.")
    for asset in ref_set.assets:
        asset.primary = asset.file in names
    ref_set.save()
    return ref_set


def _as_reference(ref_set: ReferenceSet, asset: RefAsset) -> ReferenceImage:
    path = ref_set.folder / (asset.resized or asset.file)
    return ReferenceImage(asset_id=asset.asset_id, path=path)


def select_identity_refs(
    set_id: str, max_n: int = PRIMARY_COUNT, root: Path | None = None
) -> list[ReferenceImage]:
    """Primary photos first, then the others in file order, capped at max_n."""
    ref_set = load_set(set_id, root)
    if ref_set.type != "identity":
        raise ReferenceLibraryError(f"{ref_set.set_id} is a {ref_set.type} set, not identity.")
    ordered = sorted(
        ref_set.ok_assets, key=lambda a: (not a.primary, natural_key(a.file))
    )
    return [_as_reference(ref_set, asset) for asset in ordered[: max(max_n, 0)]]


def assets_by_type(root: Path | None = None) -> dict[RefType, list[ReferenceImage]]:
    """All usable assets, grouped by reference type."""
    grouped: dict[RefType, list[ReferenceImage]] = {ref_type: [] for ref_type in REF_TYPES}
    for ref_set in list_sets(root=root):
        grouped[ref_set.type].extend(_as_reference(ref_set, a) for a in ref_set.ok_assets)
    return grouped
