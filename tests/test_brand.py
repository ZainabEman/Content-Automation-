import json
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
    "tone": "confident",
    "audience": "founders",
    "contentPillars": ["tips"],
    "logoRules": ["keep clear space"],
    "imageStyle": "clean",
    "do": ["use blue"],
    "dont": ["stretch the logo"],
    "needsReview": ["tone: drafted"],
}


def write_brand(root: Path, data: dict[str, object]) -> None:
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
    assert "tone: drafted" in result.output
