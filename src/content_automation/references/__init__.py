"""Reference library: identity, product, brand and creative sets kept separate.

Types come from the first folder under REFERENCES_DIR; a set is any folder
inside it that contains images. Creative sets are style references only.
"""

from content_automation.references.brand import (
    BrandColor,
    BrandFont,
    BrandProfile,
    BrandProfileError,
    brand_path,
    load_brand,
)
from content_automation.references.frames import FramesReport, extract_frames
from content_automation.references.library import (
    PRIMARY_COUNT,
    ReferenceLibraryError,
    ScanReport,
    SkippedFolder,
    asset_id_for,
    assets_by_type,
    list_sets,
    load_set,
    scan,
    select_identity_refs,
    select_logo_ref,
    select_set_refs,
    select_style_refs,
    set_primary,
)
from content_automation.references.models import (
    REF_TYPES,
    RefAsset,
    ReferenceSet,
    RefType,
)

__all__ = [
    "PRIMARY_COUNT",
    "REF_TYPES",
    "BrandColor",
    "BrandFont",
    "BrandProfile",
    "BrandProfileError",
    "FramesReport",
    "RefAsset",
    "RefType",
    "ReferenceLibraryError",
    "ReferenceSet",
    "ScanReport",
    "SkippedFolder",
    "asset_id_for",
    "assets_by_type",
    "brand_path",
    "extract_frames",
    "list_sets",
    "load_brand",
    "load_set",
    "scan",
    "select_identity_refs",
    "select_logo_ref",
    "select_set_refs",
    "select_style_refs",
    "set_primary",
]
