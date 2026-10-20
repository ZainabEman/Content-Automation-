"""Phase D step 8: design directions in the existing build (mock provider only, offline)."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from content_automation.content import direction_brief
from content_automation.content.brief import ContentBrief
from content_automation.content.design_preview import sample_copy
from content_automation.content.direction_brief import (
    carousel_template,
    copy_template,
    direction_problems,
    slide_roles,
)
from content_automation.content.directions import load_directions
from content_automation.core.config import Settings
from content_automation.workflows import design_check, direction_job, image_workflows
from content_automation.workflows.direction_job import (
    MANIFEST_SUFFIX,
    DirectionDesign,
)
from content_automation.workflows.image_workflows import (
    WorkflowInputs,
    prepare_workflow,
    run_workflow,
)
from content_automation.workflows.registry import WorkflowError

ILLUSTRATION = "a tidy reception desk with a plant and a closed notebook in soft daylight"


@pytest.fixture
def mock_settings(make_settings: Callable[..., Settings], tmp_path: Path,
                  monkeypatch: pytest.MonkeyPatch) -> Settings:
    logo = Image.new("RGBA", (480, 200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle((10, 40, 470, 160), fill=(0, 75, 160, 255))
    logo_path = tmp_path / "logo.png"
    logo.save(logo_path)
    for module in (direction_job, direction_brief, image_workflows):
        monkeypatch.setattr(module, "logo_file", lambda *_: logo_path)
    official = {hashlib.sha256(logo_path.read_bytes()).hexdigest()}  # the stand-in as official
    monkeypatch.setattr(design_check, "_official_hashes", lambda _: official)
    refs = tmp_path / "refs" / "identity" / "person_01"
    refs.mkdir(parents=True)
    for name in ("2.jpg", "4.jpg"):  # green-screen stand-ins for the approved photos
        photo = Image.new("RGB", (300, 400), (20, 200, 40))
        draw = ImageDraw.Draw(photo)
        draw.ellipse((110, 50, 190, 130), fill=(200, 160, 140))
        draw.rectangle((70, 130, 230, 399), fill=(30, 40, 80))
        photo.save(refs / name)
    (refs / "set.json").write_text(json.dumps({
        "setId": "identity/person_01", "name": "person_01", "type": "identity", "assets": []}),
        encoding="utf-8")
    repo = Path(__file__).resolve().parents[1]
    return make_settings(IMAGE_PROVIDER="mock", REFERENCES_DIR=str(tmp_path / "refs"),
                         BRAND_FILE=str(repo / "config" / "brand.json"),
                         SERVICES_FILE=str(repo / "config" / "services.json"))


def _inputs(direction: str, copy: dict[str, object], **extra: object) -> WorkflowInputs:
    return WorkflowInputs(direction=direction, format_copy=json.dumps(copy),
                          topic="KI-Chatbots für Praxen",
                          **{"direction_platform": "facebook", "count": 1,
                             **extra})  # type: ignore[arg-type]


def _guide_pdf(path: Path) -> None:
    """A stand-in style guide: a PDF whose page is one embedded JPEG (like the real one)."""
    import io

    page = io.BytesIO()
    Image.new("RGB", (400, 560), (240, 240, 240)).save(page, format="JPEG")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n1 0 obj << /Type /XObject /Subtype /Image /Filter /DCTDecode "
                     b"/Length 1 >>\nstream\n" + page.getvalue() + b"\nendstream\n%%EOF")


def test_designer_prompt_keeps_the_designers_six_elements(mock_settings: Settings,
                                                          tmp_path: Path) -> None:
    """R3: role and quality bar, the guide and the logo as inputs, purpose, latitude, format."""
    copy = dict(sample_copy()["LI-2/post"], illustration=ILLUSTRATION)
    prepared = prepare_workflow("social_creative", _inputs("LI-2", copy,
                                                           direction_platform="linkedin"),
                                mock_settings)
    prompt = prepared.request.prompt
    # v6 R3.3/R3.4: the designer's own prompt (brand/designer_prompt.md) adapted to the
    # category, the exact German strings, the look in words, explicit negatives, the format
    for part in ("Be my expert graphic designer and show your skill and generate for me a "
                 "professional, creative, ad style post that I can post on LinkedIn using "
                 "Brandit Genius brand style guide", "motive and aim of Branded Genius",
                 "Must be 3:4", "colour section of the Branded Genius brand style guide",
                 "official Branded Genius logo, for recognition only", "LinkedIn post",
                 "near-black, deep midnight-navy base", ILLUSTRATION,
                 '"EIN SYSTEM FÜR IHREN VERTRIEB" (the words "IHREN VERTRIEB" in light blue)',
                 '"VON DER ERSTEN ANFRAGE BIS ZUM GEBUCHTEN TERMIN."', "Never write coordinates",
                 "no flat bright-blue fill", "(1080x1440)"):
        assert part in prompt, part
    assert "%" not in prompt and "x 6-" not in prompt  # R3.1 pattern 1: zones in words only
    assert prepared.inputs["designMode"] == "designer"
    assert "designerMissing" in prepared.inputs  # mock: no guide/refs in this folder
    composite = prepare_workflow("social_creative", _inputs(
        "LI-2", copy, direction_platform="linkedin", design_mode="composite"), mock_settings)
    assert composite.request.object_refs == [] and composite.request.style_refs == []
    assert "Create only the picture" in composite.request.prompt
    assert "EIN SYSTEM" not in composite.request.prompt  # composite: never the copy
    refs = Path(mock_settings.references_dir)
    _guide_pdf(refs / "brand" / "guidelines" / "Branded Genius Brand Style Guide.pdf")
    for name in ("01.png", "06.png"):  # v6: the logo-masked copies are sent
        target = refs / "creative" / "facebook_ads_masked" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 64), (3, 6, 18)).save(target)
    full = prepare_workflow("social_creative", _inputs("LI-2", copy,
                                                       direction_platform="linkedin"),
                            mock_settings)
    assert [ref.asset_id for ref in full.request.object_refs] == ["brand-style-guide",
                                                                  "brand-logo"]
    assert [ref.asset_id for ref in full.request.style_refs] == ["ref-A01", "ref-A06"]
    assert "designerMissing" not in full.inputs and "Images 3 to 4 are" in full.request.prompt
    # the guide is sent as its colour section, the ads as their logo-masked copies (R3.4)
    assert full.request.object_refs[0].path.name == "brand_style_guide_colours.jpg"
    assert all("facebook_ads_masked" in ref.path.as_posix()
               for ref in full.request.style_refs)


def test_a_paid_job_never_runs_without_the_designer_inputs(mock_settings: Settings) -> None:
    live = mock_settings.model_copy(update={"image_provider": "openrouter"})
    copy = dict(sample_copy()["FB-1/post"], illustration=ILLUSTRATION)
    with pytest.raises(WorkflowError, match="designer prompt needs its inputs"):
        prepare_workflow("social_creative", _inputs("FB-1", copy), live)


def test_illustration_prompt_never_repeats_the_copy(mock_settings: Settings) -> None:
    copy = dict(sample_copy()["FB-1/post"], illustration=ILLUSTRATION)
    prepared = prepare_workflow("social_creative", _inputs("FB-1", copy), mock_settings)
    assert ILLUSTRATION in prepared.request.prompt and prepared.settings is not None
    assert prepared.settings.image_provider == "mock"  # mock stays mock; live: openrouter
    copied = dict(copy, illustration="automatische antworten, terminbuchungen und mehr")
    with pytest.raises(Exception, match="repeats the copy"):
        prepare_workflow("social_creative", _inputs("FB-1", copied), mock_settings)


def test_every_roman_image_is_a_higgsfield_job(mock_settings: Settings) -> None:
    for direction_id, platform, aspect in (("FB-R1", "facebook", "4:5"),
                                           ("FA-R1", "facebook", "4:5"),
                                           ("LI-R1", "linkedin", "3:4")):
        prepared = prepare_workflow(
            "social_creative", _inputs(direction_id, sample_copy()[f"{direction_id}/roman_right"],
                                       direction_platform=platform,
                                       roman_combination="S-R/BG-1/P-1/H-1"), mock_settings)
        assert prepared.person_shown and prepared.request.person
        assert prepared.request.prompt.startswith("@Roman Traenkle")
        assert prepared.request.aspect_ratio == aspect  # the canvas; the provider maps it
        assert not prepared.request.style_refs and not prepared.request.identity_refs
        assert prepared.settings is not None and prepared.settings.image_provider == "mock"
        assert str(prepared.inputs["aiDisclosure"]).startswith("KI-generiertes Bild")
    live = mock_settings.model_copy(update={"image_provider": "openrouter"})
    routed = prepare_workflow("social_creative", _inputs("FB-R1", sample_copy()[
        "FB-R1/roman_left"], roman_combination="S-L/BG-3/P-2/H-2"), live)
    assert routed.settings is not None and routed.settings.image_provider == "higgsfield_soul"
    assert routed.request.person and "Higgsfield character" in str(routed.inputs["identity"])
    assert routed.inputs["layout"] == "roman_left"


def test_founder_variants_are_full_bleed_never_a_photo() -> None:
    for direction in load_directions().directions:
        if direction.roman:
            for layout in direction.layouts.values():
                assert layout.zones["visual"].visual_shape == "full"
            assert direction.visual.subject == "roman_higgsfield"
    design = DirectionDesign(direction="LI-R1", layout="roman_right", copy={})
    picture = Image.new("RGB", (300, 400), (20, 30, 60))
    assert design.picture(picture) is picture  # no cut-out: the generated image as it is


def test_mock_build_renders_and_checks_the_design(mock_settings: Settings) -> None:
    copy = dict(sample_copy()["LI-3/post"], illustration=ILLUSTRATION)
    job = run_workflow("social_creative", _inputs("LI-3", copy, direction_platform="linkedin"),
                       mock_settings)
    assert job.status == "completed", job.error
    image = job.folder / job.outputs[0]
    manifest = json.loads(image.with_suffix(MANIFEST_SUFFIX).read_text(encoding="utf-8"))
    assert manifest["direction"] == "LI-3" and manifest["check"]["errors"] == []
    with Image.open(image) as made:
        assert made.size == (1080, 1440)  # 3:4
    assert any(note.startswith("Design: LI-3") for note in job.notes)
    roman = run_workflow("social_creative", _inputs("LI-R1", sample_copy()["LI-R1/roman_left"],
                                                    direction_platform="linkedin",
                                                    roman_combination="S-L/BG-1/P-2/H-3"),
                         mock_settings)
    assert roman.status == "completed", roman.error
    checks = json.loads((roman.folder / roman.outputs[0]).with_suffix(MANIFEST_SUFFIX)
                        .read_text(encoding="utf-8"))["check"]["romanChecks"]
    assert checks["overlap"] == "passed" and checks["german"] == "passed"
    assert checks["textZoneCalm"].startswith("skipped")  # a mock picture
    ad = run_workflow("social_creative", _inputs("FA-3", dict(sample_copy()["FA-3/post"],
                                                              illustration=ILLUSTRATION)),
                      mock_settings)
    assert ad.status == "completed", ad.error


def test_too_long_copy_fails_the_job_not_silently(mock_settings: Settings) -> None:
    copy = dict(sample_copy()["FB-3/post"], illustration=ILLUSTRATION)
    copy["headline"] = ("Wie viel Potenzial steckt wirklich in Ihren täglichen, wiederkehrenden "
                        "Abläufen im Unternehmen?")
    job = run_workflow("social_creative", _inputs("FB-3", copy), mock_settings)
    assert job.status == "failed" and "shorten it" in str(job.error).lower()


def test_templates_and_brief_checks(mock_settings: Settings) -> None:
    catalog = load_directions()
    template = copy_template(catalog.get("FB-3").layouts["post"])
    assert len(template["features"]) == 3 and len(template["icons"]) == 3
    roles = slide_roles(catalog.get("CS-1"))
    assert roles == ["cover", "point", "point", "point", "cta"]  # 5 slides (R4: 5-6)
    slides = carousel_template(catalog.get("CS-1"))["slides"]
    brief_slides = []
    for slide in slides:
        layout = catalog.get("CS-1").layout_for(role=slide["directionRole"])[0]
        copy = dict(sample_copy()[f"CS-1/{layout}"], illustration=ILLUSTRATION)
        brief_slides.append({"directionRole": slide["directionRole"], "copy": copy,
                             "altText": "Eine Folie über KI-Chatbots"})
    brief = ContentBrief.model_validate(_brief({"format": "carousel", "direction": "CS-1",
                                                "slides": brief_slides}))
    assert direction_problems(brief, catalog, mock_settings) == []
    brief_slides[1]["copy"]["body"] = "Wort " * 80
    brief_slides.pop()
    brief = ContentBrief.model_validate(_brief({"format": "carousel", "direction": "CS-1",
                                                "slides": brief_slides}))
    problems = " | ".join(direction_problems(brief, catalog, mock_settings))
    assert "end with cta" in problems and "shorten it" in problems.lower()


def _brief(carousel: dict[str, object]) -> dict[str, object]:
    return {
        "topic": "AI chatbots for practices", "platform": "instagram", "formats": ["carousel"],
        "service": "AI chatbots", "audience": "practice owners", "objective": "explain",
        "keyPoints": ["a", "b", "c"], "carousel": carousel,
        "caption": {"hook": "h", "takeaways": ["a", "b", "c"], "question": "q?"},
        "cta": "Ask us", "link": "https://brandedgenius.de",
        "hashtags": ["#AI", "#Chatbots", "#BrandedGenius"],
    }
