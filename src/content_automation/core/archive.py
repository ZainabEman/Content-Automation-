"""The competitor archive (PRD v5 R2.2): material moved out of the active pipeline.

Competitor-derived references, design directions and prompt rules are moved (never deleted) to
folders whose name starts with ``_archive`` (``config/_archive/``,
``assets/reference/_archive_competitor/``). Nothing that generates, selects or prompts reads
them: the reference library skips them, and tests/test_archive_isolation.py fails when a file
under such a folder is opened during a build, a pick, a render or a reference scan.
"""

from pathlib import Path

ARCHIVE_PREFIX = "_archive"
CONFIG_ARCHIVE = Path("config/_archive")
ASSET_ARCHIVE_NAME = "_archive_competitor"  # under REFERENCES_DIR


def is_archived(path: Path | str) -> bool:
    """True when any part of the path is an archive folder."""
    return any(part.startswith(ARCHIVE_PREFIX) for part in Path(path).parts)


__all__ = ["ARCHIVE_PREFIX", "ASSET_ARCHIVE_NAME", "CONFIG_ARCHIVE", "is_archived"]
