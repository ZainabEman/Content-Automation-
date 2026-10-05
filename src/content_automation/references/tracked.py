"""Non-private reference settings kept in git (REFERENCES_FILE, default config/references.json).

The photos stay in the git-ignored REFERENCES_DIR. What was decided about them is tracked so
another machine gets it with `uv run ca refs scan`: the style tags (people, logo), the primary
photos of each identity set, and the areas `ca refs mask` covers in the past ads.

Tags are keyed by "<set ID>/<file>". A scan applies a tag when the file is the same (asset ID)
or is made by the tool (video frames, masked copies), whose bytes can differ between machines.

The file belongs to the configured REFERENCES_DIR only: work on any other folder (a test, a
second library) neither reads nor writes it.
"""

from pathlib import Path

from pydantic import Field

from content_automation.core.config import load_settings
from content_automation.core.files import CamelModel, atomic_write_text

ABOUT = (
    "Tracked reference settings: style tags (people, logo; set by viewing each image with "
    "`ca refs tag`), primary identity photos (`ca refs primary`) and the logo areas `ca refs "
    "mask` covers. The photos themselves stay in the git-ignored assets/reference/."
)


class TrackedTag(CamelModel):
    asset_id: str
    people: bool
    logo: bool


class MaskSpec(CamelModel):
    """Masked copies: every listed file of `source` with its boxes covered, saved in `target`."""

    source: str  # creative set ID, e.g. creative/facebook_ads
    target: str  # creative set ID of the copies, e.g. creative/facebook_ads_masked
    # file -> boxes as fractions of the image: [left, top, right, bottom]
    files: dict[str, list[list[float]]] = Field(default_factory=dict)


class TrackedReferences(CamelModel):
    about: str = ABOUT
    primary: dict[str, list[str]] = Field(default_factory=dict)  # identity set -> files
    tags: dict[str, TrackedTag] = Field(default_factory=dict)  # "<set ID>/<file>" -> tag
    masks: list[MaskSpec] = Field(default_factory=list)

    def mask_targets(self) -> set[str]:
        return {spec.target for spec in self.masks}


def tracked_for(root: Path | None) -> Path | None:
    """The tracked file for a references folder: only the configured REFERENCES_DIR has one."""
    settings = load_settings(create_directories=False, require_credentials=False)
    if root is not None and root.resolve() != settings.references_dir.resolve():
        return None
    return settings.references_file


def load_tracked(path: Path | None) -> TrackedReferences:
    """The tracked settings; empty when there is no file (or none for this folder)."""
    if path is None or not path.is_file():
        return TrackedReferences()
    return TrackedReferences.model_validate_json(path.read_text(encoding="utf-8"))


def save_tracked(data: TrackedReferences, path: Path | None) -> None:
    if path is None:
        return  # not the configured references folder: nothing is tracked
    file = path
    file.parent.mkdir(parents=True, exist_ok=True)
    data.tags = dict(sorted(data.tags.items()))
    atomic_write_text(file, data.model_dump_json(by_alias=True, indent=2) + "\n")
