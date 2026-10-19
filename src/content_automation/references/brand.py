"""Brand profile: BRAND_FILE (default config/brand.json, tracked in git).

Older setups keep it at REFERENCES_DIR/brand/brand.json (git-ignored); that file is used only
when the tracked one does not exist.
"""

from pathlib import Path
from typing import Literal

from pydantic import ConfigDict, Field, ValidationError, model_validator

from content_automation.core.config import load_settings
from content_automation.core.files import CamelModel

BRAND_FILE = Path("brand") / "brand.json"  # the old place, inside REFERENCES_DIR


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


class BrandCarousel(_BrandModel):
    language: str = "de"  # v5 (PRD R1.4): German by default; "en" stays possible


HEX = r"^#[0-9A-Fa-f]{6}$"
TOKEN_ROLES = ("bg_dark", "bg_light", "primary", "accent", "highlight", "text_on_dark",
               "text_on_light", "muted")
TokenRole = Literal["bg_dark", "bg_light", "primary", "accent", "highlight", "text_on_dark",
                    "text_on_light", "muted"]


class Sourced(_BrandModel):
    source: str = Field(min_length=1)  # file plus page or section, or a checked URL


class BrandToken(Sourced):
    hex: str = Field(pattern=HEX)


class BrandTokens(_BrandModel):
    """Colour roles of app-rendered designs; each one is a guide colour (checked below)."""

    note: str = Field(default="", alias="_note")
    bg_dark: BrandToken
    bg_light: BrandToken
    primary: BrandToken
    accent: BrandToken
    highlight: BrandToken
    text_on_dark: BrandToken
    text_on_light: BrandToken
    muted: BrandToken

    def get(self, role: str) -> BrandToken:
        if role not in TOKEN_ROLES:
            raise KeyError(f"unknown colour token {role!r} (brand.json tokens: "
                           f"{', '.join(TOKEN_ROLES)})")
        token: BrandToken = getattr(self, role)
        return token

    def hexes(self) -> dict[str, str]:
        return {role: self.get(role).hex.upper() for role in TOKEN_ROLES}


class BrandGradient(Sourced):
    from_: TokenRole = Field(alias="from")
    to: TokenRole


class FontRole(Sourced):
    family: str = Field(min_length=1)
    weight: str = ""


class FallbackFont(Sourced):
    family: str = Field(min_length=1)
    licence: str = Field(min_length=1)


class Typography(_BrandModel):
    headline: FontRole
    body: FontRole
    logo_only: FontRole | None = None
    fallback: FallbackFont | None = None
    licence: str = ""
    max_families: int = Field(default=2, ge=1, le=2)

    def families(self) -> list[str]:
        """Font families in priority order: the brand family, then the fallback."""
        names = [self.headline.family]
        if self.body.family not in names:
            names.append(self.body.family)
        if self.fallback is not None and self.fallback.family not in names:
            names.append(self.fallback.family)
        return names


class LogoVariant(Sourced):
    id: str = Field(min_length=1)
    file: str = ""  # relative to REFERENCES_DIR
    sha256: str = Field(default="", pattern=r"^([0-9a-f]{64})?$")
    derived_from: str = ""
    backgrounds: list[Literal["light", "dark", "photo"]] = Field(min_length=1)

    @model_validator(mode="after")
    def _file_or_derived(self) -> "LogoVariant":
        if bool(self.file) == bool(self.derived_from):
            raise ValueError(f"logo variant {self.id}: give either file (+ sha256) or "
                             "derivedFrom")
        if self.file and not self.sha256:
            raise ValueError(f"logo variant {self.id}: a file needs its sha256")
        return self


class LogoSpec(Sourced):
    min_width_px: int = Field(gt=0)
    clear_space_ratio: float = Field(ge=0, le=1)


class Website(Sourced):
    url: str = Field(pattern=r"^https://")
    display: str = Field(min_length=1)


class ContactField(Sourced):
    value: str = Field(min_length=1)
    on_graphics: bool = False


class Contact(_BrandModel):
    email: ContactField | None = None
    phone: ContactField | None = None


class Footer(Sourced):
    elements: list[Literal["website", "email", "phone", "handles"]] = Field(min_length=1)
    optional: list[Literal["website", "email", "phone", "handles"]] = Field(default_factory=list)


class Tagline(Sourced):
    text: str = Field(min_length=1)
    lang: str = Field(min_length=2)


class BrandProfile(_BrandModel):
    brand_name: str = Field(min_length=1)
    status: Literal["draft", "approved"] = "draft"
    sources: list[str] = Field(default_factory=list)
    colors: list[BrandColor] = Field(min_length=1)
    fonts: list[BrandFont] = Field(default_factory=list)
    language: str = "de"  # v5 (PRD R1.4)
    carousel: BrandCarousel = Field(default_factory=BrandCarousel)
    tone: str = ""
    audience: str = ""
    content_pillars: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)  # old files only: see services_file
    services_file: str = ""  # config/services.json (Phase D)
    logo_file: str | None = None  # file in brand/logo used by --logo
    logo_rules: list[str] = Field(default_factory=list)
    image_style: str = ""
    do: list[str] = Field(default_factory=list)
    dont: list[str] = Field(default_factory=list)
    needs_review: list[str] = Field(default_factory=list)
    # Phase D design tokens (optional so older brand files still load)
    tokens: BrandTokens | None = None
    gradients: dict[str, BrandGradient] = Field(default_factory=dict)
    typography: Typography | None = None
    logo_variants: list[LogoVariant] = Field(default_factory=list)
    logo_spec: LogoSpec | None = None
    website: Website | None = None
    contact: Contact = Field(default_factory=Contact)
    handles: dict[str, str] = Field(default_factory=dict)  # "_note" plus platform -> handle
    footer: Footer | None = None
    taglines: list[Tagline] = Field(default_factory=list)

    @model_validator(mode="after")
    def _tokens_are_guide_colours(self) -> "BrandProfile":
        """Never a colour outside the guide: every token is one of the brand colours."""
        if self.tokens is None:
            return self
        palette = {color.hex.upper() for color in self.colors}
        for role, value in self.tokens.hexes().items():
            if value not in palette:
                raise ValueError(f"tokens.{role} {value} is not a brand colour "
                                 f"({', '.join(sorted(palette))})")
        return self

    def social_handles(self) -> dict[str, str]:
        return {name: value for name, value in self.handles.items() if not name.startswith("_")}

    def logo_variant(self, background: Literal["light", "dark", "photo"]) -> LogoVariant:
        """The approved logo version for a background kind."""
        for variant in self.logo_variants:
            if background in variant.backgrounds:
                return variant
        raise BrandProfileError(f"brand.json logoVariants has no version for a {background} "
                                "background")


def brand_path(root: Path | None = None) -> Path:
    """The tracked brand file if it exists, else the old one inside the references folder.

    The tracked file belongs to the configured REFERENCES_DIR; another folder (a test, a second
    library) uses its own brand/brand.json.
    """
    settings = load_settings(create_directories=False, require_credentials=False)
    configured = root is None or root.resolve() == settings.references_dir.resolve()
    if configured and settings.brand_file.is_file():
        return settings.brand_file
    base = root if root is not None else settings.references_dir
    return base / BRAND_FILE


def load_brand(root: Path | None = None) -> BrandProfile:
    path = brand_path(root)
    if not path.is_file():
        raise BrandProfileError(f"brand.json not found at {path}.")
    try:
        return BrandProfile.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as error:
        fields = sorted({".".join(str(p) for p in issue["loc"]) or
                         str(issue["msg"]).removeprefix("Value error, ")
                         for issue in error.errors()})
        raise BrandProfileError(f"brand.json is invalid; check: {', '.join(fields)}.") from None
