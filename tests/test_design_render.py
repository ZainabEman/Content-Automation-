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
    plain,
    render_layout,
    token_colors,
)
from content_automation.workflows.line_breaks import Piece, wrap
from content_automation.workflows.roman_check import calm_problems, overlap_problems


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
            if direction.roman:  # v6 R4.6: no logo and no website on a Roman creative
                assert rendered.logo is None and not rendered.footer
                continue
            assert rendered.logo is not None and rendered.logo.aspect_error < 0.01
            assert rendered.logo.width_px >= rendered.logo.min_width_px
    assert count == 29  # 14 post/ad variants (3 founders x 2 sides) + 4 carousels x 3


def test_sweep_variant_and_engagement_row_keep_contrast(assets: Assets) -> None:
    catalog = load_directions()
    light = render_layout(catalog, catalog.get("LI-4"), "post", sample_copy()["LI-4/post"],
                          assets)
    assert light.texts and all(t.contrast >= t.needed for t in light.texts)
    closing = render_layout(catalog, catalog.get("CS-2"), "cta", sample_copy()["CS-2/cta"],
                            assets)
    labels = [t.text for t in closing.texts if t.zone == "engage"]
    assert labels == ["LIKEN", "wenn du zustimmst", "TEILEN", "mit deinem Netzwerk",
                      "SPEICHERN", "für später"]  # v6 R3.2: the engagement bar
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
    assert lines[-1].startswith("Preview: 3 rendered, 0 failed")
    assert (tmp_path / "out" / "LI-R1_roman_left.png").is_file()
    assert (tmp_path / "out" / "FB-1_post.json").read_text(encoding="utf-8").count('"texts"') == 1


def test_cli_design_preview(tmp_path: Path, logo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(design_preview, "logo_file", lambda *_: logo)
    result = CliRunner().invoke(app, ["design", "preview", "LI-2", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "1 rendered, 0 failed" in result.output and "no provider called" in result.output
    unknown = CliRunner().invoke(app, ["design", "preview", "XX-1", "--out", str(tmp_path)])
    assert unknown.exit_code == 1


def _wrapped(text: str, width: float, *, headline: bool = False, hyphenate: bool = False,
             max_lines: int = 4) -> list[str] | None:
    pieces = [Piece(w.text, 10.0 * len(w.text), w.glue, w.soft or w.text.endswith("-"),
                    10.0 if w.soft else 0.0) for w in parse(text)]
    ranges = wrap(pieces, width, 10.0, max_lines, headline=headline, hyphenate=hyphenate)
    return None if ranges is None else [
        "".join(("" if index == start or pieces[index].glue else " ") + pieces[index].text
                for index in range(start, end)) for start, end in ranges]


def test_german_line_breaks_keep_phrases_and_avoid_one_word_lines() -> None:
    """Phase 3 (P3-R3): never after an article, a preposition or a number; no one-word last
    line in a headline (a stack is fine); KI- compounds never split; hyphens only as the last
    resort in body text."""
    assert _wrapped("Ihre Daten bleiben bei Ihnen", 130) == ["Ihre Daten", "bleiben",
                                                              "bei Ihnen"]
    assert _wrapped("Über 30 Prozent sparen", 160) == ["Über 30 Prozent", "sparen"]
    assert _wrapped("Über 30 Prozent sparen", 120) is None  # never "Über 30 / Prozent"
    headline = "KI-ZITATE BRAUCHEN QUELLENPRÜFUNG"
    assert _wrapped(headline, 240, headline=True) == ["KI-ZITATE", "BRAUCHEN QUELLENPRÜFUNG"]
    assert _wrapped(headline, 190, headline=True) == ["KI-ZITATE", "BRAUCHEN", "QUELLENPRÜFUNG"]
    assert _wrapped(headline, 190, headline=True, max_lines=2) is None  # not "… / QUELLEN…"
    assert _wrapped("KI-Agenten", 80, hyphenate=True) is None
    assert _wrapped("Daten-Schutz", 70) is None
    assert _wrapped("Daten-Schutz", 70, hyphenate=True) == ["Daten-", "Schutz"]


def test_founder_overlay_floor_text_too_long_and_calm_as_drawn(assets: Assets) -> None:
    """Phase 3 (P3-R1/R2/R4/R6, audit row 18): the body stays at the 28 px floor, too much copy
    is "text too long" (never clipped), the text keeps 48 px from a hologram beside it, and the
    calm check reads the backdrop as drawn (under the scrim), not the busy raw scene."""
    catalog = load_directions()
    direction = catalog.get("LI-R1")
    picture = Image.new("RGB", catalog.size(direction), (8, 12, 30))
    draw = ImageDraw.Draw(picture)
    for x in range(0, 640, 16):  # a busy text side: the raw scene fails the calm check
        draw.line((x, 0, x, 1440), fill=(70, 80, 110), width=6)
    draw.ellipse((590, 300, 640, 350), outline=(80, 200, 255), width=6)  # an icon on his side
    copy = dict(sample_copy()["LI-R1/roman_right"])
    rendered = render_layout(catalog, direction, "roman_right", copy, assets, picture=picture)
    texts = {text.zone: text for text in rendered.texts}
    assert texts["sub"].font_px >= 28 and texts["sub"].min_font_px == 28
    assert texts["headline"].text == plain(str(copy["headline"]))  # the approved copy exactly
    manifest = rendered.manifest()
    assert rendered.holograms and overlap_problems(manifest, "S-R", share=0.3334,
                                                   min_gap_px=48) == []
    assert calm_problems(picture, manifest, max_std=30, max_detail=12) == []
    raw = dict(manifest, texts=[{key: value for key, value in text.items()
                                 if not key.startswith("backdrop_")}
                                for text in manifest["texts"]])
    assert calm_problems(picture, raw, max_std=30, max_detail=12)  # the old measurement
    long = dict(copy, sub="Öffnen Sie vor jeder Veröffentlichung die Originalseite, prüfen Sie "
                          "das Datum, den Autor und die Quelle, und vergleichen Sie jede Zahl "
                          "mit der Studie, bevor Ihr Team den Beitrag freigibt.")
    with pytest.raises(DesignRenderError, match="text too long"):
        render_layout(catalog, direction, "roman_right", long, assets, picture=picture)
