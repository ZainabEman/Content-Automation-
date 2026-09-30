"""Brand profile stored at REFERENCES_DIR/brand/brand.json."""

from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError

from content_automation.core.config import load_settings
from content_automation.core.files import CamelModel

BRAND_FILE = Path("brand") / "brand.json"


class BrandProfileError(ValueError):
    """brand.json is missing or invalid."""


class _BrandModel(CamelModel):
    model_config = ConfigDict(extra="forbid")


class BrandColor(_BrandModel):
    name: str = Field(min_length=1)
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    usage: str = ""


class BrandFont(_BrandModel):
    name: str = Field(min_length=1)
    usage: str = ""


class BrandProfile(_BrandModel):
    brand_name: str = Field(min_length=1)
    status: Literal["draft", "approved"] = "draft"
    sources: list[str] = Field(default_factory=list)
    colors: list[BrandColor] = Field(min_length=1)
    fonts: list[BrandFont] = Field(default_factory=list)
    language: str = ""
    tone: str = ""
    audience: str = ""
    content_pillars: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)  # what the company offers
    logo_file: str | None = None  # file in brand/logo used by --logo
    logo_rules: list[str] = Field(default_factory=list)
    image_style: str = ""
    do: list[str] = Field(default_factory=list)
    dont: list[str] = Field(default_factory=list)
    needs_review: list[str] = Field(default_factory=list)


def brand_path(root: Path | None = None) -> Path:
    base = root if root is not None else load_settings(create_directories=False).references_dir
    return base / BRAND_FILE


def load_brand(root: Path | None = None) -> BrandProfile:
    path = brand_path(root)
    if not path.is_file():
        raise BrandProfileError(f"brand.json not found at {path}.")
    try:
        return BrandProfile.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        fields = sorted({".".join(str(p) for p in issue["loc"]) for issue in error.errors()})
        raise BrandProfileError(f"brand.json is invalid; check: {', '.join(fields)}.") from None
