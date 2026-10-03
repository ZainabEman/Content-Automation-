"""Data stored in each set's set.json."""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, PrivateAttr

from content_automation.core.files import CamelModel, atomic_write_text

RefType = Literal["identity", "brand", "creative", "product"]
REF_TYPES: tuple[RefType, ...] = ("identity", "brand", "creative", "product")
AssetStatus = Literal["ok", "rejected"]
SET_FILE = "set.json"
RESIZED_DIR = "_resized"
FRAMES_DIR = "_frames"


class RefAsset(CamelModel):
    asset_id: str
    file: str
    resized: str | None = None
    width: int | None = None
    height: int | None = None
    primary: bool = False
    status: AssetStatus
    reason: str | None = None
    # Style tags, set once by viewing the image (`ca refs tag`); None = not tagged yet.
    people: bool | None = None  # shows a person, face, hand or human figure
    logo: bool | None = None  # shows a logo, wordmark or brand mark


TAG_FIELDS = ("people", "logo")


class ReferenceSet(CamelModel):
    set_id: str
    name: str
    type: RefType
    scanned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    assets: list[RefAsset] = Field(default_factory=list)

    _folder: Path | None = PrivateAttr(default=None)

    @property
    def folder(self) -> Path:
        if self._folder is None:
            raise ValueError(f"Set {self.set_id} has no folder.")
        return self._folder

    @property
    def ok_assets(self) -> list[RefAsset]:
        return [asset for asset in self.assets if asset.status == "ok"]

    @property
    def rejected_assets(self) -> list[RefAsset]:
        return [asset for asset in self.assets if asset.status == "rejected"]

    @property
    def primary_assets(self) -> list[RefAsset]:
        return [asset for asset in self.ok_assets if asset.primary]

    @classmethod
    def load(cls, set_file: Path) -> "ReferenceSet":
        ref_set = cls.model_validate_json(set_file.read_text(encoding="utf-8"))
        ref_set._folder = set_file.parent
        return ref_set

    @property
    def untagged_assets(self) -> list[RefAsset]:
        return [a for a in self.ok_assets if a.people is None or a.logo is None]

    def save(self) -> None:
        data = self.model_dump(mode="json", by_alias=True)
        for asset in data["assets"]:  # untagged sets keep their old file layout
            for name in TAG_FIELDS:
                if asset.get(name) is None:
                    asset.pop(name, None)
        atomic_write_text(self.folder / SET_FILE, json.dumps(data, indent=2) + "\n")
