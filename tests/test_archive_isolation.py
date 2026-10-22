"""PRD v5 R2.2 / §7.2: the generator never loads anything from the competitor archive.

Two checks. Static: no source file, active config file or skill names an archive path (only
core/archive.py knows the prefix). Runtime: a Python audit hook records every file opened while
the directions load, every format picks, every layout renders (the preview path the build uses),
the illustration prompts are built, the brand loads and the reference library scans a folder that
holds an archive; none of those files may lie under an `_archive*` folder.
"""

import contextlib
import hashlib
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from content_automation.content import directions as directions_module
from content_automation.content.design_preview import preview, sample_copy
from content_automation.content.direction_pick import pick_direction
from content_automation.content.directions import FORMATS, load_directions
from content_automation.core.archive import ASSET_ARCHIVE_NAME, is_archived
from content_automation.references import load_brand
from content_automation.references.library import list_sets, scan
from content_automation.workflows.direction_job import DirectionJobError, illustration_prompt

REPO = Path(__file__).resolve().parents[1]
_ARCHIVE_PATH = re.compile(r"_archive(?:_competitor)?[\/\"']|competitor\.json")
_OPENED: list[str] = []
_ACTIVE: list[bool] = [False]


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if _ACTIVE[0] and event == "open" and args and isinstance(args[0], (str, Path)):
        _OPENED.append(str(args[0]))


sys.addaudithook(_hook)  # audit hooks cannot be removed; _ACTIVE gates it to these tests


@pytest.fixture
def opened() -> Iterator[list[str]]:
    _OPENED.clear()
    _ACTIVE[0] = True
    try:
        yield _OPENED
    finally:
        _ACTIVE[0] = False


def _references(root: Path) -> Path:
    """A references folder with a stand-in logo, one approved set and an archived set."""
    brand = json.loads((REPO / "config" / "brand.json").read_text(encoding="utf-8"))
    logo = root / brand["logoVariants"][0]["file"]  # the logo file brand.json names
    logo.parent.mkdir(parents=True)
    Image.new("RGBA", (600, 400), (0, 75, 160, 255)).save(logo)
    brand["logoVariants"][0]["sha256"] = hashlib.sha256(logo.read_bytes()).hexdigest()
    (root / "brand" / "brand.json").write_text(json.dumps(brand), encoding="utf-8")
    approved = root / "creative" / "facebook_ads"
    approved.mkdir(parents=True)
    Image.new("RGB", (64, 64), (0, 75, 160)).save(approved / "01.png")
    archived = root / ASSET_ARCHIVE_NAME / "social_refs"
    archived.mkdir(parents=True)
    Image.new("RGB", (64, 64), (200, 0, 0)).save(archived / "R01.png")
    (archived / "set.json").write_text(json.dumps({"setId": "x"}), encoding="utf-8")
    return root


def test_no_active_file_names_the_archive() -> None:
    allowed = {REPO / "src" / "content_automation" / "core" / "archive.py"}
    files = [*REPO.joinpath("src").rglob("*.py"), *REPO.joinpath("config").glob("*.json"),
             *REPO.joinpath(".agents", "skills").rglob("*.md")]
    hits = [path.relative_to(REPO).as_posix() for path in files
            if path not in allowed and not is_archived(path.relative_to(REPO))
            and _ARCHIVE_PATH.search(path.read_text(encoding="utf-8"))]
    assert hits == []


def test_generation_opens_nothing_from_the_archive(opened: list[str], tmp_path: Path) -> None:
    references = _references(tmp_path / "reference")
    opened.clear()  # only what the app opens from here on counts
    directions_module._load.cache_clear()
    catalog = load_directions()
    for format_name in FORMATS:
        for direction in catalog.for_format(format_name):
            for platform in direction.platforms:
                pick_direction(catalog, format_name, platform, seed="x", recent=[],
                               roman_ok=True)
    samples = sample_copy()
    for direction in catalog.directions:
        if direction.visual.subject != "illustration":
            continue
        for layout_name in direction.layouts:
            copy = dict(samples.get(f"{direction.id}/{layout_name}", {}))
            with contextlib.suppress(DirectionJobError):  # a refusal reads only active config
                illustration_prompt(direction, catalog, copy, "a glass cube on a desk")
    lines = preview(references_dir=references, out_dir=tmp_path / "out")
    assert lines[-1].startswith("Preview:")
    load_brand(references)
    report = scan(references)
    sets = list_sets(root=references)
    assert all(not is_archived(found.set_id) for found in sets)
    assert all(ASSET_ARCHIVE_NAME not in warning for warning in report.warnings)
    leaked = sorted({path for path in opened if is_archived(path)})
    assert leaked == []
    assert any("design_directions.json" in path for path in opened)  # the hook did record


def test_is_archived() -> None:
    assert is_archived("config/_archive/design_directions.json")
    assert is_archived(Path("assets/reference/_archive_competitor/R01.jpeg"))
    assert not is_archived("config/design_directions.json")
