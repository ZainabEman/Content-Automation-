"""PRD v6 R3 (T1): the design drift fixes, offline (mock provider, recorded readings)."""

import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.content.design_preview import sample_copy
from content_automation.content.design_variation import (
    Variation,
    apply,
    pick_variation,
    variations,
)
from content_automation.content.designer_prompt import (
    DesignerPromptError,
    check_clean,
    designer_inputs,
    layout_words,
)
from content_automation.content.directions import load_directions
from content_automation.core.config import Settings
from content_automation.workflows import design_check, direction_job, image_workflows
from content_automation.workflows.design_check import check_facts, check_manifest
from content_automation.workflows.design_render import Assets, design_fonts, render_layout
from content_automation.workflows.direction_job import MANIFEST_SUFFIX
from content_automation.workflows.image_check import ReadText, codes, match_text
from content_automation.workflows.image_workflows import WorkflowInputs, run_workflow
from content_automation.workflows.text_reader import MockTextReader

ROOT = Path(__file__).resolve().parents[1]
REJECTED = ROOT / "tests" / "fixtures" / "rejected"
ILLUSTRATION = "a glowing glass chat bubble and a calendar icon floating above a dark pedestal"
_COORDINATE = re.compile(r"\b[xy]\s*\d|\d+\s*%|\d+\s*[-–]\s*\d+")


@pytest.mark.parametrize("sidecar", sorted(REJECTED.glob("*.json")), ids=lambda p: p.stem)
def test_every_rejected_image_fails_with_its_reason(sidecar: Path) -> None:
    """§5 check 1: each image of the rejected sample fails the design checks for its pattern."""
    expected = set(json.loads(sidecar.read_text(encoding="utf-8"))["expect"])
    report = check_facts(sidecar.with_suffix(".jpg"), sidecar)
    assert not report.passed
    assert expected <= codes(report.errors), report.errors


def test_the_rejected_sample_covers_every_pattern() -> None:
    found: set[str] = set()
    for sidecar in REJECTED.glob("*.json"):
        found |= set(json.loads(sidecar.read_text(encoding="utf-8"))["expect"])
    assert {"coordinates", "stray_text", "flat_blue", "light_base", "real_photo", "roman_logo",
            "logo_overlap", "slide_number", "placeholder", "carousel_logo"} <= found
    assert 8 <= len(list(REJECTED.glob("*.jpg"))) <= 12


def test_design_check_cli_fails_the_rejected_sample() -> None:
    result = CliRunner().invoke(app, ["design", "check", str(REJECTED)])
    assert result.exit_code != 0
    assert result.output.count("FAIL") == len(list(REJECTED.glob("*.jpg")))


@pytest.fixture
def assets(tmp_path: Path) -> Assets:
    from content_automation.references import load_brand

    brand = load_brand(ROOT / "assets" / "reference")
    logo = Image.new("RGBA", (480, 200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle((10, 40, 470, 160), fill=(0, 75, 160, 255))
    path = tmp_path / "logo.png"
    logo.save(path)
    return Assets(brand=brand, logo_path=path, fonts=design_fonts(brand))


def test_no_image_model_prompt_carries_coordinates(tmp_path: Path) -> None:
    """§5 check 1: zones reach the model in words only, in both modes and every variation."""
    catalog = load_directions()
    samples = sample_copy()
    count = 0
    for direction in catalog.directions:
        if direction.roman:
            continue
        for name, layout in direction.layouts.items():
            copy = dict(samples[f"{direction.id}/{name}"])
            for variation in variations(direction, layout, catalog)[:6]:
                varied = apply(direction, layout, variation, catalog)
                for mode in ("designer", "composite"):
                    made = designer_inputs(direction, varied, catalog, picture=ILLUSTRATION,
                                           topic="KI im Mittelstand", copy=copy,
                                           references_dir=tmp_path, logo_path=None,
                                           cache_dir=tmp_path, mock=True, mode=mode)
                    rest = made.prompt
                    for text in made.texts:
                        rest = rest.replace(text, "")
                    rest = re.sub(r"#[0-9A-F]{6}|\(\d+x\d+\)|\d+:\d+", "", rest)
                    assert not _COORDINATE.search(rest), (direction.id, name, mode,
                                                          _COORDINATE.search(rest))
                    count += 1
    assert count > 100
    with pytest.raises(DesignerPromptError, match="coordinate"):
        check_clean("Keep the headline zone (x 6-34%, y 47-60%) dark.")


def test_layout_words_name_sides_and_corners() -> None:
    catalog = load_directions()
    words = layout_words(catalog.get("FB-1").layouts["post"])
    assert words.logo_corner == "top-left corner" and "left" in words.text_side
    mirrored = apply(catalog.get("FB-1"), catalog.get("FB-1").layouts["post"],
                     Variation("R", "panel", "dots", "arrow"), catalog)
    assert layout_words(mirrored).logo_corner == "top-right corner"


def test_match_text_is_exact_and_names_stray_text() -> None:
    read = [ReadText("WIE VIEL POTENZIAL"), ReadText("x 6-34%"), ReadText("Jetzt prufen")]
    found = match_text(read, ["WIE VIEL POTENZIAL", "Jetzt prüfen"])
    assert found.missing == ["Jetzt prüfen"]  # the umlaut counts
    assert "x" in found.leftover and "6-34%" in found.leftover


@pytest.fixture
def mock_settings(make_settings: Callable[..., Settings], tmp_path: Path,
                  monkeypatch: pytest.MonkeyPatch) -> Settings:
    logo = Image.new("RGBA", (480, 200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle((10, 40, 470, 160), fill=(0, 75, 160, 255))
    logo_path = tmp_path / "logo.png"
    logo.save(logo_path)
    for module in (direction_job, image_workflows):
        monkeypatch.setattr(module, "logo_file", lambda *_: logo_path)
    official = {hashlib.sha256(logo_path.read_bytes()).hexdigest()}
    monkeypatch.setattr(design_check, "_official_hashes", lambda _: official)
    return make_settings(IMAGE_PROVIDER="mock", REFERENCES_DIR=str(tmp_path / "refs"),
                         BRAND_FILE=str(ROOT / "config" / "brand.json"),
                         SERVICES_FILE=str(ROOT / "config" / "services.json"))


def _inputs(direction: str, copy: dict[str, object], **extra: object) -> WorkflowInputs:
    return WorkflowInputs(direction=direction, format_copy=json.dumps(copy),
                          topic="KI-Chatbots für Praxen",
                          **{"direction_platform": "facebook", "count": 1,
                             **extra})  # type: ignore[arg-type]


def test_designer_mode_retries_once_then_composite(mock_settings: Settings,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """R3.4: a failed text check gets one retry, then composite mode draws the text."""
    readings = iter([["x 6-34%", "WENIGER ROUTINE."], ["v-inmleie"]])

    def reader(settings: Settings, image_path: Path | None = None) -> MockTextReader:
        del settings, image_path
        return MockTextReader(next(readings, None))

    monkeypatch.setattr(direction_job, "reader_for", reader)
    copy = dict(sample_copy()["FB-2/post"], illustration=ILLUSTRATION)
    job = run_workflow("social_creative", _inputs("FB-2", copy), mock_settings)
    assert job.status == "completed", job.error
    assert job.inputs["designMode"] == "composite"
    note = next(note for note in job.notes if note.startswith("Designer mode:"))
    assert "designer attempt 1" in note and "designer attempt 2" in note
    assert "[coordinates]" in note and "composite mode used" in note
    manifest = json.loads((job.folder / job.outputs[0]).with_suffix(MANIFEST_SUFFIX)
                          .read_text(encoding="utf-8"))
    assert manifest["check"]["errors"] == [] and manifest["texts"]  # the app drew the text


def test_designer_mode_passes_on_the_exact_text(mock_settings: Settings) -> None:
    copy = dict(sample_copy()["FB-2/post"], illustration=ILLUSTRATION)
    job = run_workflow("social_creative", _inputs("FB-2", copy), mock_settings)
    assert job.status == "completed", job.error
    assert job.inputs["designMode"] == "designer"
    texts = json.loads(str(job.inputs["designerTexts"]))
    assert texts[0] == "WENIGER ROUTINE. MEHR WACHSTUM." and "Beratung buchen" in texts
    manifest = json.loads((job.folder / job.outputs[0]).with_suffix(MANIFEST_SUFFIX)
                          .read_text(encoding="utf-8"))
    assert manifest["logo"] is not None and manifest["texts"] == []  # the app placed the logo


def test_cta_keeps_its_text_clear_of_its_icon(assets: Assets) -> None:
    catalog = load_directions()
    direction = catalog.get("FB-1")
    for variation in (Variation("L", "panel", "none", "arrow"),
                      Variation("R", "open", "chevrons", "calendar"),
                      Variation("L", "panel", "wave", "play")):
        layout = apply(direction, direction.layouts["post"], variation, catalog)
        rendered = render_layout(catalog, direction, "post", sample_copy()["FB-1/post"], assets,
                                 layout=layout)
        cta = rendered.ctas[0]
        assert cta["gapPx"] >= 12, variation
    manifest = rendered.manifest() | {"copy": {}}
    manifest["ctas"][0]["gapPx"] = 3
    from content_automation.references.services import load_services

    report = check_manifest(manifest, catalog=catalog, brand=assets.brand,
                            services=load_services(ROOT / "config" / "services.json"),
                            official={hashlib.sha256(assets.logo_path.read_bytes())
                                      .hexdigest()})
    assert "cta_collision" in codes(report.errors)


def test_variation_rotation_never_repeats_a_near_identical_image() -> None:
    """R3.5: never more than two of four parts shared with the previous image, never one of
    the last three again; a mirrored layout still passes every layout rule."""
    catalog = load_directions()
    direction = catalog.get("LI-2")
    layout = direction.layouts["post"]
    recent: list[str] = []
    for n in range(12):
        chosen, _ = pick_variation(direction, layout, catalog, seed=f"BG-{n}", recent=recent)
        if recent:
            assert chosen.shared(Variation.parse(recent[0])) <= 2
            assert chosen.key not in recent[:3]
        recent.insert(0, chosen.key)
    assert len({key.split("/")[0] for key in recent}) == 2  # both sides used
    carousel = catalog.get("CS-1")
    assert {v.side for v in variations(carousel, carousel.layouts["cover"], catalog)} == {"L"}


def test_carousel_logo_and_website_only_on_the_last_slide(assets: Assets) -> None:
    """§5 check 3: a mock carousel shows its logo and website on the last slide only and no
    slide number anywhere."""
    catalog = load_directions()
    for direction in catalog.for_format("carousel"):
        for role in direction.slide_roles:
            rendered = render_layout(catalog, direction, role.layout,
                                     sample_copy()[f"{direction.id}/{role.layout}"], assets)
            last = role.layout == direction.last_layout()
            assert (rendered.logo is not None) == last and bool(rendered.footer) == last
            assert not any(re.fullmatch(r"0?\d|\d+\s*/\s*\d+", text.text)
                           for text in rendered.texts)
