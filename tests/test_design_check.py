"""Phase D step 7: `ca design check` (free, deterministic; a stand-in logo, no provider)."""

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.content.design_preview import sample_copy
from content_automation.content.directions import load_directions
from content_automation.references import load_brand
from content_automation.references.services import load_services
from content_automation.workflows import design_check
from content_automation.workflows.design_check import check_files, check_manifest
from content_automation.workflows.design_render import Assets, design_fonts, render_layout


@pytest.fixture
def logo(tmp_path: Path) -> Path:
    image = Image.new("RGBA", (480, 200), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 40, 470, 160), fill=(0, 75, 160, 255))
    path = tmp_path / "logo.png"
    image.save(path)
    return path


def _manifest(logo: Path, direction_id: str, layout: str) -> dict[str, Any]:
    brand = load_brand()
    catalog = load_directions()
    rendered = render_layout(catalog, catalog.get(direction_id), layout,
                             sample_copy()[f"{direction_id}/{layout}"],
                             Assets(brand=brand, logo_path=logo, fonts=design_fonts(brand)))
    data: dict[str, Any] = json.loads(json.dumps(rendered.manifest(), default=str))
    data["copy"] = sample_copy()[f"{direction_id}/{layout}"]
    return data


def _check(data: dict[str, Any], logo: Path, **extra: Any) -> design_check.Report:
    official = {hashlib.sha256(logo.read_bytes()).hexdigest()}
    return check_manifest(data, catalog=load_directions(), brand=load_brand(),
                          services=load_services(), official=official, **extra)


def test_a_clean_render_passes(logo: Path) -> None:
    report = _check(_manifest(logo, "LI-3", "post"), logo)
    assert report.passed, report.errors


def test_brand_logo_layout_and_contact_errors(logo: Path) -> None:
    good = _manifest(logo, "FB-1", "post")
    bad = copy.deepcopy(good)
    bad["fills"].append(["panel", "#ff0000"])
    bad["logo"]["aspect_error"] = 0.08
    bad["logo"]["width_px"] = 90
    bad["texts"][0]["contrast"] = 1.8
    bad["texts"][0]["font_px"] = 4
    bad["texts"][1]["box"] = good["logo"]["box"]
    errors = " | ".join(_check(bad, logo).errors)
    for expected in ("not a brand token", "logo stretched", "under its minimum",
                     "contrast 1.8:1", "inside the logo's clear space"):
        assert expected in errors
    unofficial = check_manifest(good, catalog=load_directions(), brand=load_brand(),
                                services=load_services(), official={"0" * 64})
    assert any("not the official file" in error for error in unofficial.errors)
    no_logo = dict(good, logo=None)
    assert any("no logo" in error for error in _check(no_logo, logo).errors)


def test_copy_claims_numbers_and_identity(logo: Path) -> None:
    data = _manifest(logo, "FB-1", "post")
    data["copy"]["sub"] = "Unser SEO-Team verdoppelt den Traffic um 40%"
    report = _check(data, logo)
    assert any("does not offer" in error for error in report.errors)
    assert any("a number needs its source" in warning for warning in report.warnings)
    lora = _manifest(logo, "LI-R1", "post")
    assert any("person check must pass" in w for w in _check(lora, logo).warnings)
    assert not _check(lora, logo, person_check="pass").warnings
    real = _manifest(logo, "FB-R1", "post")
    real["photo"] = "C:/photos/2.jpg"
    assert any("never the final image" in e for e in _check(real, logo).errors)


def test_files_and_cli(tmp_path: Path, logo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = tmp_path / "out"
    folder.mkdir()
    data = _manifest(logo, "LI-2", "post")
    (folder / "LI-2_post.json").write_text(json.dumps(data), encoding="utf-8")
    Image.new("RGB", (100, 100)).save(folder / "LI-2_post.png")
    (folder / "other.json").write_text("{}", encoding="utf-8")
    official = {hashlib.sha256(logo.read_bytes()).hexdigest()}
    monkeypatch.setattr(design_check, "_official_hashes", lambda _: official)
    reports = check_files([folder], catalog=load_directions(), brand=load_brand(),
                          services=load_services())
    assert len(reports) == 1 and any("the PNG is (100, 100)" in e for e in reports[0].errors)
    result = CliRunner().invoke(app, ["design", "check", str(folder)])
    assert result.exit_code == 1 and "0 passed, 1 failed" in result.output
    Image.new("RGB", tuple(data["size"])).save(folder / "LI-2_post.png")
    result = CliRunner().invoke(app, ["design", "check", str(folder / "LI-2_post.json")])
    assert result.exit_code == 0, result.output
    missing = CliRunner().invoke(app, ["design", "check", str(tmp_path / "nothing.json")])
    assert missing.exit_code == 1 and "unreadable manifest" in missing.output


def test_v5_category_rules(logo: Path) -> None:
    """R2.7 / R4: carousel logo and website only on the last slide, no counters, LinkedIn's
    logo at a side corner, brand fonts only."""
    assert _check(_manifest(logo, "CS-1", "cta"), logo).passed
    point = _manifest(logo, "CS-1", "point")
    assert _check(point, logo).passed
    with_logo = copy.deepcopy(point)
    with_logo["logo"] = _manifest(logo, "CS-1", "cta")["logo"]
    with_logo["footer"] = ["brandedgenius.de"]
    errors = " | ".join(_check(with_logo, logo).errors)
    assert "logo only on its last slide" in errors and "website only on its last" in errors
    counted = copy.deepcopy(point)
    counted["texts"][0]["text"] = "01/07"
    assert any("counter" in e for e in _check(counted, logo).errors)
    linkedin = _manifest(logo, "LI-2", "post")
    assert _check(linkedin, logo).passed
    middle = copy.deepcopy(linkedin)
    middle["logo"]["box"] = [400, 600, 680, 680]
    assert any("side corner" in e for e in _check(middle, logo).errors)
    font = copy.deepcopy(linkedin)
    font["fonts"] = ["Comic-Sans.ttf"]
    assert any("not a brand font" in e for e in _check(font, logo).errors)
    margin = copy.deepcopy(linkedin)
    margin["texts"][0]["box"] = [10, 200, 500, 300]
    assert any("64 px margin" in e for e in _check(margin, logo).errors)
