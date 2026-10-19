"""Phase D step 3: the design-direction renderer, the green-screen cut-out and `ca design preview`
(offline; a drawn stand-in replaces the official logo, which is not in git)."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.content import design_preview
from content_automation.content.design_preview import preview, sample_copy
from content_automation.content.directions import load_directions
from content_automation.references import load_brand
from content_automation.workflows.cutout import CutoutError, cut_out
from content_automation.workflows.design_render import (
    Assets,
    DesignRenderError,
    Rendered,
    design_fonts,
    parse,
    render_layout,
    token_colors,
)


@pytest.fixture
def logo(tmp_path: Path) -> Path:
    image = Image.new("RGBA", (480, 200), (0, 0, 0, 0))
    ImageDraw.Draw(image).rectangle((10, 40, 470, 160), fill=(0, 75, 160, 255))
    path = tmp_path / "logo.png"
    image.save(path)
    return path


@pytest.fixture
def assets(logo: Path) -> Assets:
    brand = load_brand()
    return Assets(brand=brand, logo_path=logo, fonts=design_fonts(brand))


def test_marks_and_touching_punctuation() -> None:
    words = parse("Still chasing *follow-ups*? Start with the *process*, not **two words**.")
    assert [(w.text, w.style, w.glue) for w in words if w.style != "plain"] == [
        ("follow-", "accent", False), ("ups?", "accent", True),  # v5: a break point (R1.5)
        ("process,", "accent", False), ("two", "bold", False), ("words.", "bold", False)]
    pill = parse("How we build [[an AI agent]] in 3 steps?")
    assert {w.group for w in pill if w.style == "pill"} == {0}
    assert pill[-1].text == "steps?" and pill[-1].style == "plain"


def test_every_layout_renders_brand_only(assets: Assets) -> None:
    catalog = load_directions()
    samples = sample_copy()
    tokens = set(token_colors(assets.brand))
    count = 0
    for direction in catalog.directions:
        for name in direction.layouts:
            rendered = render_layout(catalog, direction, name, samples[f"{direction.id}/{name}"],
                                     assets)
            count += 1
            assert rendered.image.size == catalog.size(direction)
            assert {token for _, token in rendered.fills} <= tokens
            for text in rendered.texts:
                assert set(text.tokens) <= tokens
                assert text.font_px >= text.min_font_px and text.lines <= text.max_lines
            if direction.format == "carousel" and name != direction.last_layout():
                assert rendered.logo is None and not rendered.footer  # R4: last slide only
                continue
            assert rendered.logo is not None and rendered.logo.aspect_error < 0.01
            assert rendered.logo.width_px >= rendered.logo.min_width_px
    assert count == 26  # 14 post/ad variants + 4 carousels x 3 slide layouts


def test_light_variant_and_engagement_row_keep_contrast(assets: Assets) -> None:
    catalog = load_directions()
    light = render_layout(catalog, catalog.get("LI-4"), "post", sample_copy()["LI-4/post"],
                          assets)
    assert light.texts and all(t.contrast >= t.needed for t in light.texts)
    closing = render_layout(catalog, catalog.get("CS-2"), "cta", sample_copy()["CS-2/cta"],
                            assets)
    labels = [t.text for t in closing.texts if t.zone == "engage"]
    assert labels == ["Liken", "Teilen", "Speichern"]
    assert closing.footer == ["brandedgenius.de"]  # website: "ja"
    no_site = dict(sample_copy()["CS-2/cta"], website="")
    assert not render_layout(catalog, catalog.get("CS-2"), "cta", no_site, assets).footer


def test_text_that_does_not_fit_is_an_error(assets: Assets) -> None:
    catalog = load_directions()
    copy = dict(sample_copy()["FB-2/post"])
    copy["headline"] = ("Eine Überschrift, die viel zu lang ist, um in die drei kurzen Zeilen "
                        "dieses Panels zu passen")
    with pytest.raises(DesignRenderError, match="Shorten it"):
        render_layout(catalog, catalog.get("FB-2"), "post", copy, assets)
    unbreakable = dict(copy, headline="Datenschutzgrundverordnungskonformitätsprüfung")
    with pytest.raises(DesignRenderError, match="Shorten it"):  # R1.5: never cut mid-word
        render_layout(catalog, catalog.get("FB-2"), "post", unbreakable, assets)
    soft = dict(copy, headline="Datenschutz\u00adgrund\u00adverordnungs\u00adkonformität")
    rendered = render_layout(catalog, catalog.get("FB-2"), "post", soft, assets)
    assert any(line.endswith("-") for line in _lines_of(rendered, "headline"))


def test_unknown_icon_is_refused(assets: Assets) -> None:
    catalog = load_directions()
    copy = dict(sample_copy()["FB-3/post"])
    copy["icons"] = ["robot", "robot", "not-an-icon"]
    with pytest.raises(DesignRenderError, match="not allowed"):
        render_layout(catalog, catalog.get("FB-3"), "post", copy, assets)


def _lines_of(rendered: Rendered, zone: str) -> list[str]:
    """The drawn lines of a text zone (a soft hyphen shows at a line end)."""
    return [line for text in rendered.texts if text.zone == zone for line in text.drawn]


def _green_screen() -> Image.Image:
    image = Image.new("RGB", (200, 300), (20, 200, 40))
    draw = ImageDraw.Draw(image)
    draw.ellipse((70, 40, 130, 100), fill=(200, 160, 140))
    draw.rectangle((50, 100, 150, 299), fill=(30, 40, 80))
    return image


def test_cut_out_keys_the_green_screen() -> None:
    def no_model(_: Image.Image) -> Image.Image:
        raise AssertionError("a clean key needs no model")

    cut, method = cut_out(_green_screen(), segmenter=no_model)
    alpha = np.asarray(cut.getchannel("A"))
    assert method == "key" and cut.mode == "RGBA"
    assert cut.size[0] <= 106 and alpha[-1, cut.size[0] // 2] > 200 and alpha[0, 0] < 30


def test_cut_out_refuses_a_photo_without_green() -> None:
    with pytest.raises(CutoutError, match="no green screen"):
        cut_out(Image.new("RGB", (100, 100), (200, 200, 200)))


def test_preview_writes_png_and_manifest(tmp_path: Path, logo: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(design_preview, "logo_file", lambda *_: logo)
    lines = preview(["fb-1", "LI-R1"], out_dir=tmp_path / "out")
    assert lines[-1].startswith("Preview: 2 rendered, 0 failed")
    assert (tmp_path / "out" / "LI-R1_post.png").is_file()
    assert (tmp_path / "out" / "FB-1_post.json").read_text(encoding="utf-8").count('"texts"') == 1


def test_cli_design_preview(tmp_path: Path, logo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(design_preview, "logo_file", lambda *_: logo)
    result = CliRunner().invoke(app, ["design", "preview", "LI-2", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "1 rendered, 0 failed" in result.output and "no provider called" in result.output
    unknown = CliRunner().invoke(app, ["design", "preview", "XX-1", "--out", str(tmp_path)])
    assert unknown.exit_code == 1
