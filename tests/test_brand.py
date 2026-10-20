import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.references import BrandProfileError, load_brand

VALID = {
    "brandName": "Example Brand",
    "status": "draft",
    "colors": [{"name": "Royal Blue", "hex": "#004BA0", "usage": "primary"}],
    "fonts": [{"name": "Futura Bold", "usage": "headings"}],
    "language": "English",
    "tone": "confident",
    "audience": "founders",
    "contentPillars": ["tips"],
    "logoRules": ["keep clear space"],
    "imageStyle": "clean",
    "do": ["use blue"],
    "dont": ["stretch the logo"],
    "needsReview": ["tone: drafted"],
}


def write_brand(root: Path, data: Mapping[str, object]) -> None:
    path = root / "brand" / "brand.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_valid_brand_loads(tmp_path: Path) -> None:
    write_brand(tmp_path, VALID)

    brand = load_brand(tmp_path)

    assert brand.brand_name == "Example Brand"
    assert brand.colors[0].hex == "#004BA0"
    assert brand.content_pillars == ["tips"]


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"colors": [{"name": "Blue", "hex": "blue"}]}, "colors.0.hex"),
        ({"colors": []}, "colors"),
        ({"brandName": ""}, "brandName"),
        ({"colour": "typo"}, "colour"),
    ],
)
def test_invalid_brand_names_the_field(
    tmp_path: Path, change: dict[str, object], field: str
) -> None:
    write_brand(tmp_path, {**VALID, **change})

    with pytest.raises(BrandProfileError, match=field):
        load_brand(tmp_path)


def test_missing_brand_file(tmp_path: Path) -> None:
    with pytest.raises(BrandProfileError, match="not found"):
        load_brand(tmp_path)


def test_brand_show(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_brand(isolated / "refs", VALID)
    monkeypatch.setenv("REFERENCES_DIR", str(isolated / "refs"))

    result = CliRunner().invoke(app, ["brand", "show"])

    assert result.exit_code == 0
    assert "Example Brand (draft)" in result.output
    assert "Royal Blue #004BA0" in result.output
    assert "Language: English" in result.output
    assert "tone: drafted" in result.output


REPO_BRAND = Path(__file__).resolve().parents[1] / "config" / "brand.json"


def _repo_brand() -> dict[str, object]:
    data: dict[str, object] = json.loads(REPO_BRAND.read_text(encoding="utf-8"))
    return data


def test_repo_brand_tokens_are_the_guide_colours(tmp_path: Path) -> None:
    write_brand(tmp_path, _repo_brand())
    brand = load_brand(tmp_path)
    assert brand.tokens is not None and brand.typography is not None
    palette = {color.hex.upper() for color in brand.colors}
    assert palette == {"#004BA0", "#69BFF8", "#969595", "#FFFFFF"}
    sampled = {color.hex.upper(): color.source for color in brand.sampled_colors}
    assert set(brand.tokens.hexes().values()) <= palette | set(sampled)
    # v6 R3.2: the base is the midnight navy sampled from the approved ads, never Royal Blue
    assert brand.tokens.get("bg_dark").hex == "#000514"
    assert "creative/facebook_ads" in sampled["#000514"]
    assert brand.tokens.get("bg_black").hex == "#000000"
    assert all(token.source for token in (brand.tokens.get(role) for role in
                                          ("bg_dark", "accent", "muted", "panel")))
    assert brand.typography.families() == ["Futura", "Jost"]
    assert brand.logo_variant("dark").id == "white"
    assert brand.logo_variant("light").sha256.startswith("ff800645c78e")
    assert brand.social_handles() == {}
    assert brand.website is not None and brand.website.display == "brandedgenius.de"
    assert brand.contact.phone is not None and not brand.contact.phone.on_graphics


def test_a_token_outside_the_guide_is_refused(tmp_path: Path) -> None:
    data = _repo_brand()
    tokens = dict(data["tokens"])  # type: ignore[call-overload]
    tokens["bg_dark"] = {"hex": "#06122E", "source": "old carousel palette"}
    write_brand(tmp_path, {**data, "tokens": tokens})
    with pytest.raises(BrandProfileError, match="tokens"):
        load_brand(tmp_path)


def test_a_logo_file_needs_its_hash(tmp_path: Path) -> None:
    data = _repo_brand()
    data["logoVariants"] = [{"id": "x", "file": "brand/logo/x.png", "backgrounds": ["light"],
                             "source": "test"}]
    write_brand(tmp_path, data)
    with pytest.raises(BrandProfileError, match="logoVariants"):
        load_brand(tmp_path)
