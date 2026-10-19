"""Scan REFERENCES_DIR in place, write set.json files, and pick references for workflows.

Originals are never moved or deleted. The scanner only writes set.json and the
copies in each set's _resized/ folder.
"""

import hashlib
import os
import random
import re
import zlib
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps, UnidentifiedImageError

from content_automation.ai.image import ReferenceImage
from content_automation.core.archive import is_archived
from content_automation.core.config import load_settings
from content_automation.references.frames import frame_paths
from content_automation.references.models import (
    FRAMES_DIR,
    REF_TYPES,
    RESIZED_DIR,
    SET_FILE,
    RefAsset,
    ReferenceSet,
    RefType,
)
from content_automation.references.tracked import (
    TrackedReferences,
    TrackedTag,
    load_tracked,
    save_tracked,
    tracked_for,
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
_GENERATED_DIRS = frozenset({RESIZED_DIR, FRAMES_DIR})
_FRAME_FILE = re.compile(rf"{FRAMES_DIR}/(.+)_(\d+)\.[a-z]+")
LOGO_SET = "brand/logo"


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
        if is_archived(child.name):  # the competitor archive is never a reference (PRD v5 R2.2)
            continue
        if child.is_dir() and child.name not in REF_TYPES:
            report.warnings.append(
                f"Folder '{child.name}' ignored: top-level folders must be "
                f"{', '.join(REF_TYPES)}."
            )
        elif child.is_file() and child.name != "brand.json":
            report.warnings.append(f"File '{child.name}' ignored: put it inside a set folder.")

    now = datetime.now(UTC)
    tracked = load_tracked(tracked_for(root))
    for ref_type in REF_TYPES:
        type_dir = root / ref_type
        if not type_dir.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(type_dir):
            dirnames[:] = sorted(
                (d for d in dirnames if d not in _GENERATED_DIRS and not d.startswith(".")
                 and not is_archived(d)),
                key=natural_key,
            )
            folder = Path(dirpath)
            files = sorted((f for f in filenames if _is_candidate(f)), key=natural_key)
            files += _frame_files(folder)
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
            report.sets.append(_scan_set(folder, relative, ref_type, files, now, tracked))
    return report


def _frame_files(folder: Path) -> list[str]:
    """Frames extracted by `ca refs frames` count as assets of the parent set."""
    frames = folder / FRAMES_DIR
    if not frames.is_dir():
        return []
    names = (p.name for p in frames.iterdir() if p.is_file() and _is_candidate(p.name))
    return [f"{FRAMES_DIR}/{name}" for name in sorted(names, key=natural_key)]


def _is_candidate(name: str) -> bool:
    return not name.startswith(".") and name.casefold() not in IGNORED_FILES


def _no_images_reason(files: list[str]) -> str:
    counts = Counter(Path(f).suffix.lower().lstrip(".") or "no extension" for f in files)
    summary = ", ".join(f"{count} {ext}" for ext, count in sorted(counts.items()))
    hint = ""
    if any(Path(f).suffix.lower() in VIDEO_SUFFIXES for f in files):
        hint = "; run `ca refs frames` to use video frames"
    return f"no JPG/PNG/WebP images ({summary}){hint}"


def _load_previous(folder: Path) -> dict[str, RefAsset]:
    set_file = folder / SET_FILE
    if not set_file.is_file():
        return {}
    try:
        previous = ReferenceSet.load(set_file)
    except (OSError, ValueError):
        return {}
    return {asset.asset_id: asset for asset in previous.ok_assets}


def _tracked_tag(
    tracked: TrackedReferences, set_id: str, name: str, asset_id: str
) -> TrackedTag | None:
    """The tracked tag of a file: the same file, or one the tool made (frames, masked copies)."""
    tag = tracked.tags.get(f"{set_id}/{name}")
    if tag is None:
        return None
    made_by_tool = name.startswith(f"{FRAMES_DIR}/") or set_id in tracked.mask_targets()
    return tag if tag.asset_id == asset_id or made_by_tool else None


def _scan_set(
    folder: Path,
    set_id: str,
    ref_type: RefType,
    files: list[str],
    now: datetime,
    tracked: TrackedReferences | None = None,
) -> ReferenceSet:
    tracked = tracked or TrackedReferences()
    previous = _load_previous(folder)
    resized_dir = folder / RESIZED_DIR
    assets: list[RefAsset] = []
    seen: dict[str, str] = {}
    for name in files:
        asset_id = asset_id_for(folder / name)
        if asset_id in seen:
            reason = f"duplicate of {seen[asset_id]}"
            assets.append(RefAsset(asset_id=asset_id, file=name, status="rejected", reason=reason))
            continue
        seen[asset_id] = name
        asset = _check_and_copy(folder, name, asset_id, ref_type)
        old = previous.get(asset_id)
        if asset.status == "ok" and old is not None:
            if ref_type == "identity":
                asset.primary = old.primary
            asset.people, asset.logo = old.people, old.logo  # tags survive a rescan
        tag = _tracked_tag(tracked, set_id, name, asset_id) if asset.status == "ok" else None
        if tag is not None:  # the tracked settings win: another machine gets the same tags
            asset.people, asset.logo = tag.people, tag.logo
        assets.append(asset)

    ok_assets = [asset for asset in assets if asset.status == "ok"]
    chosen = tracked.primary.get(set_id)
    if ref_type == "identity" and chosen:
        for asset in ok_assets:
            asset.primary = asset.file in chosen
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


def _unsupported_reason(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".svg":
        return "SVG (vector) is not supported; export it as PNG"
    if suffix == ".pdf":
        return "PDF is not supported; export the pages as PNG or JPG"
    if suffix in VIDEO_SUFFIXES:
        if all(frame.is_file() for frame in frame_paths(path)):
            return f"video; its frames in {FRAMES_DIR}/ are used instead"
        return "video files are not supported; run `ca refs frames` to use its frames"
    label = suffix.lstrip(".").upper() or "files without an extension"
    return f"{label} is not supported; use JPG, PNG or WebP"


def _check_and_copy(folder: Path, name: str, asset_id: str, ref_type: RefType) -> RefAsset:
    path = folder / name

    def rejected(reason: str, size: tuple[int, int] | None = None) -> RefAsset:
        return RefAsset(
            asset_id=asset_id,
            file=name,
            width=size[0] if size else None,
            height=size[1] if size else None,
            status="rejected",
            reason=reason,
        )

    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return rejected(_unsupported_reason(path))
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
    target = folder / resized
    if not target.is_file():
        try:
            _write_copy(image, target, extension)
        except (OSError, ValueError):
            return rejected("could not be converted to a resized copy", (width, height))
    return RefAsset(
        asset_id=asset_id,
        file=name,
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
        if _GENERATED_DIRS.intersection(set_file.parts) or is_archived(
                set_file.relative_to(root)):
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
    file = tracked_for(root)
    tracked = load_tracked(file)
    tracked.primary[ref_set.set_id] = names
    save_tracked(tracked, file)
    return ref_set


def _as_reference(ref_set: ReferenceSet, asset: RefAsset) -> ReferenceImage:
    path = ref_set.folder / (asset.resized or asset.file)
    return ReferenceImage(
        asset_id=asset.asset_id,
        path=path,
        source=f"{ref_set.set_id}/{asset.file}",
        people=asset.people,
        logo=asset.logo,
    )


def tag_assets(
    asset_ids: Sequence[str],
    *,
    people: bool,
    logo: bool,
    root: Path | None = None,
) -> list[str]:
    """Record what a style image shows (after viewing it); returns "set/file" per asset.

    An asset ID that appears in several sets (the same file copied) is tagged everywhere.
    """
    wanted = {asset_id.strip() for asset_id in asset_ids if asset_id.strip()}
    if not wanted:
        raise ReferenceLibraryError("Give at least one asset ID (see set.json or the dry run).")
    tagged: list[str] = []
    found: set[str] = set()
    file = tracked_for(root)
    tracked = load_tracked(file)
    for ref_set in list_sets(None, root):
        changed = False
        for asset in ref_set.ok_assets:
            if asset.asset_id in wanted:
                asset.people, asset.logo = people, logo
                name = f"{ref_set.set_id}/{asset.file}"
                tagged.append(name)
                tracked.tags[name] = TrackedTag(asset_id=asset.asset_id, people=people, logo=logo)
                found.add(asset.asset_id)
                changed = True
        if changed:
            ref_set.save()
    if found:
        save_tracked(tracked, file)  # kept in git, so another machine gets the same tags
    missing = sorted(wanted - found)
    if missing:
        raise ReferenceLibraryError(
            f"Not a usable reference image: {', '.join(missing)}. Run `uv run ca refs scan`."
        )
    return tagged


def untagged_style_refs(root: Path | None = None) -> list[str]:
    """Creative images not tagged yet ("set/file"); person designs never use them."""
    return [
        f"{ref_set.set_id}/{asset.file} [{asset.asset_id}]"
        for ref_set in list_sets("creative", root)
        for asset in ref_set.untagged_assets
    ]


def _style_tier(asset: RefAsset, person: bool) -> int | None:
    """How well a style image suits a design; lower is better, None = never used.

    The model never draws a logo (the app pastes the real one), so images tagged with a logo
    are never sent. A design that shows the person takes only images tagged free of people
    and logos, so no other face can leak in. Other designs prefer those, then images with
    people, then untagged ones.
    """
    if asset.logo is True:
        return None
    clean = asset.people is False and asset.logo is False
    if person:
        return 0 if clean else None
    if clean:
        return 0
    return 1 if asset.logo is False else 2


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


def select_set_refs(
    set_id: str,
    max_n: int,
    root: Path | None = None,
    *,
    ref_type: RefType | None = None,
) -> list[ReferenceImage]:
    """Usable assets of a set in file order, capped at max_n."""
    ref_set = load_set(set_id, root)
    if ref_type is not None and ref_set.type != ref_type:
        raise ReferenceLibraryError(
            f"{ref_set.set_id} is a {ref_set.type} set; a {ref_type} set is needed here."
        )
    if not ref_set.ok_assets:
        raise ReferenceLibraryError(f"{ref_set.set_id} has no usable images.")
    ordered = sorted(ref_set.ok_assets, key=lambda a: natural_key(a.file))
    return [_as_reference(ref_set, asset) for asset in ordered[: max(max_n, 0)]]


def _source_key(file: str) -> str:
    """Frames of one video share a source; every other file is its own source."""
    match = _FRAME_FILE.fullmatch(file)
    return match.group(1) if match else file


def _frame_preference(file: str) -> int:
    """Middle frame (_2) first, then the others."""
    match = _FRAME_FILE.fullmatch(file)
    return abs(int(match.group(2)) - 2) if match else 0


def spread_indices(total: int, wanted: int) -> list[int]:
    """`wanted` distinct indices spread evenly over range(total)."""
    wanted = min(wanted, total)
    return [int((i + 0.5) * total / wanted) for i in range(wanted)]


def select_style_refs(
    set_id: str, max_n: int, root: Path | None = None, *, person: bool = False
) -> list[ReferenceImage]:
    """Pick up to max_n style images from different videos/files, spread across the set.

    person: the image shows the person, so only images tagged free of people and logos
    (possibly none); logo images are never used (see _style_tier).
    """
    ref_set = load_set(set_id, root)
    if ref_set.type != "creative":
        raise ReferenceLibraryError(
            f"{ref_set.set_id} is a {ref_set.type} set; a creative set is needed for style."
        )
    if not ref_set.ok_assets:
        raise ReferenceLibraryError(f"{ref_set.set_id} has no usable images.")
    usable = [a for a in ref_set.ok_assets if _style_tier(a, person) is not None]
    groups: dict[str, list[RefAsset]] = {}
    for asset in sorted(usable, key=lambda a: natural_key(a.file)):
        groups.setdefault(_source_key(asset.file), []).append(asset)
    queues = [
        sorted(items, key=lambda a: (_frame_preference(a.file), natural_key(a.file)))
        for items in groups.values()
    ]
    picked: list[RefAsset] = []
    while len(picked) < max_n and any(queues):
        open_queues = [queue for queue in queues if queue]
        for index in spread_indices(len(open_queues), max_n - len(picked)):
            picked.append(open_queues[index].pop(0))
    return [_as_reference(ref_set, asset) for asset in picked]


def creative_sets(
    names: Sequence[str], root: Path | None = None, *, strict: bool = False
) -> list[ReferenceSet]:
    """Creative sets named by set ID or by a folder of sets (creative/carousels).

    strict: a name that matches nothing is looked up like any set name and fails clearly.
    """
    sets = list_sets("creative", root)
    found: dict[str, ReferenceSet] = {}
    for name in names:
        wanted = name.strip("/")
        matches = [s for s in sets if s.set_id == wanted or s.set_id.startswith(f"{wanted}/")]
        if not matches and strict:
            match = load_set(wanted, root)
            if match.type != "creative":
                raise ReferenceLibraryError(
                    f"{match.set_id} is a {match.type} set; a creative set is needed for style."
                )
            matches = [match]
        for match in matches:
            found[match.set_id] = match
    return list(found.values())


def _slide_role(position: int, total: int) -> str:
    if position == 0:
        return "hook"
    return "cta" if position == total - 1 else "tip"


def select_rotating_style_refs(
    names: Sequence[str],
    max_n: int,
    root: Path | None = None,
    *,
    avoid: Sequence[str] = (),
    seed: str = "",
    strict: bool = False,
    role: str | None = None,
    person: bool = False,
) -> tuple[list[ReferenceImage], list[str]]:
    """Up to max_n style images from the named creative sets, and the set IDs they came from.

    One image per video/file. Asset IDs in ``avoid`` (newest first) are used only when too
    few others remain, the one used longest ago first. The rest is shuffled by ``seed`` and
    taken from different sets where possible, so the same inputs give the same images.

    role: carousel examples only for that slide role. Within a set the videos/files in name
    order are the slides: the first is the "hook", the last the "cta", the rest "tip".
    person: the design shows the person, so only images tagged free of people and logos are
    used (possibly none); otherwise those come first (see _style_tier).
    """
    if max_n <= 0:
        return [], []
    candidates: list[tuple[int, ReferenceSet, RefAsset]] = []
    for ref_set in creative_sets(names, root, strict=strict):
        groups: dict[str, list[RefAsset]] = {}
        for asset in sorted(ref_set.ok_assets, key=lambda a: natural_key(a.file)):
            groups.setdefault(_source_key(asset.file), []).append(asset)
        ordered = sorted(groups, key=natural_key)
        for position, key in enumerate(ordered):
            if role is not None and _slide_role(position, len(ordered)) != role:
                continue
            usable = [
                (tier, asset)
                for asset in groups[key]
                if (tier := _style_tier(asset, person)) is not None
            ]
            if not usable:
                continue
            tier, best = min(
                usable,
                key=lambda item: (
                    item[0], _frame_preference(item[1].file), natural_key(item[1].file)
                ),
            )
            candidates.append((tier, ref_set, best))
    last_used: dict[str, int] = {}
    for position, asset_id in enumerate(avoid):
        last_used.setdefault(asset_id, position)
    rng = random.Random(zlib.crc32(seed.encode("utf-8")))
    pools: list[tuple[list[tuple[ReferenceSet, RefAsset]], bool]] = []
    for level in sorted({tier for tier, _, _ in candidates}):
        in_tier = [(ref_set, asset) for tier, ref_set, asset in candidates if tier == level]
        fresh = [item for item in in_tier if item[1].asset_id not in last_used]
        rng.shuffle(fresh)
        stale = sorted(
            (item for item in in_tier if item[1].asset_id in last_used),
            key=lambda item: -last_used[item[1].asset_id],
        )
        pools += [(fresh, True), (fresh, False), (stale, False)]
    picked: list[tuple[ReferenceSet, RefAsset]] = []
    for pool, one_per_set in pools:
        for ref_set, asset in pool:
            if len(picked) >= max_n:
                break
            taken = any(asset.asset_id == other.asset_id for _, other in picked)
            same_set = any(ref_set.set_id == other.set_id for other, _ in picked)
            if not taken and not (one_per_set and same_set):
                picked.append((ref_set, asset))
    refs = [_as_reference(ref_set, asset) for ref_set, asset in picked]
    return refs, sorted({ref_set.set_id for ref_set, _ in picked})


def select_logo_ref(
    root: Path | None = None, set_id: str = LOGO_SET, preferred: str | None = None
) -> ReferenceImage:
    """The brand logo file (the original, full size), pasted onto designs by the app.

    The preferred file (brand.json logoFile) if given; otherwise file names containing
    "logo" first, PNG before other formats.
    """
    ref_set = load_set(set_id, root)
    if ref_set.type != "brand" or not ref_set.ok_assets:
        raise ReferenceLibraryError(f"No usable logo found in {set_id}.")
    if preferred:
        match = next((a for a in ref_set.ok_assets if a.file == preferred), None)
        if match is None:
            raise ReferenceLibraryError(
                f"logoFile '{preferred}' is not a usable image in {ref_set.set_id}."
            )
    else:
        match = min(
            ref_set.ok_assets,
            key=lambda a: (
                "logo" not in a.file.casefold(),
                not a.file.casefold().endswith(".png"),
                natural_key(a.file),
            ),
        )
    return ReferenceImage(
        asset_id=match.asset_id,
        path=ref_set.folder / match.file,
        source=f"{ref_set.set_id}/{match.file}",
    )


def _cover(image: Image.Image, box: list[float]) -> None:
    """Fill one box with a smooth patch blended from its border, so the area underneath (a
    logo) is gone and the background flows through."""
    width, height = image.size
    left, top = max(1, round(box[0] * width)), max(1, round(box[1] * height))
    right, bottom = min(width - 1, round(box[2] * width)), min(height - 1, round(box[3] * height))
    if right - left < 2 or bottom - top < 2:
        return
    smooth = image.filter(ImageFilter.GaussianBlur(3))  # border samples without noise

    def px(x: int, y: int) -> tuple[int, int, int]:
        value = smooth.getpixel((x, y))
        assert isinstance(value, tuple)
        return int(value[0]), int(value[1]), int(value[2])

    span_x, span_y = right - left, bottom - top
    upper = [px(x, top - 1) for x in range(left, right)]
    lower = [px(x, bottom) for x in range(left, right)]
    side_l = [px(left - 1, y) for y in range(top, bottom)]
    side_r = [px(right, y) for y in range(top, bottom)]
    c00, c10 = px(left - 1, top - 1), px(right, top - 1)
    c01, c11 = px(left - 1, bottom), px(right, bottom)
    patch = Image.new("RGB", (span_x, span_y))
    for j in range(span_y):
        v = (j + 0.5) / span_y
        for i in range(span_x):
            u = (i + 0.5) / span_x
            patch.putpixel((i, j), tuple(
                round(
                    (1 - v) * upper[i][c] + v * lower[i][c] + (1 - u) * side_l[j][c]
                    + u * side_r[j][c]
                    - ((1 - u) * (1 - v) * c00[c] + u * (1 - v) * c10[c]
                       + (1 - u) * v * c01[c] + u * v * c11[c])
                )
                for c in range(3)
            ))
    image.paste(patch.filter(ImageFilter.GaussianBlur(1)), (left, top))


def mask_copies(root: Path | None = None) -> list[str]:
    """Make the masked copies listed in the tracked settings (logos covered); returns their
    "<set ID>/<file>" names. Run `scan` afterwards to register them."""
    root = _root(root)
    file = tracked_for(root)
    tracked = load_tracked(file)
    made: list[str] = []
    for spec in tracked.masks:
        source = load_set(spec.source, root)
        target = root / spec.target
        target.mkdir(parents=True, exist_ok=True)
        by_file = {asset.file: asset for asset in source.ok_assets}
        for name, boxes in spec.files.items():
            original = by_file.get(name)
            if original is None:
                raise ReferenceLibraryError(f"{spec.source}/{name} is not a usable image.")
            with Image.open(source.folder / name) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
            for box in boxes:
                _cover(image, box)
            copy = target / f"{Path(name).stem}.png"
            image.save(copy, format="PNG", optimize=True)
            key = f"{spec.target}/{copy.name}"
            people = original.people if original.people is not None else True
            tracked.tags[key] = TrackedTag(asset_id=asset_id_for(copy), people=people, logo=False)
            made.append(key)
    save_tracked(tracked, file)
    return made


def assets_by_type(root: Path | None = None) -> dict[RefType, list[ReferenceImage]]:
    """All usable assets, grouped by reference type."""
    grouped: dict[RefType, list[ReferenceImage]] = {ref_type: [] for ref_type in REF_TYPES}
    for ref_set in list_sets(root=root):
        grouped[ref_set.type].extend(_as_reference(ref_set, a) for a in ref_set.ok_assets)
    return grouped
