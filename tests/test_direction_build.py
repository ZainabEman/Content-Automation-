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
from content_automation.workflows import design_check, direction_job
from content_automation.workflows.direction_job import MANIFEST_SUFFIX
from content_automation.workflows.image_workflows import (
    WorkflowInputs,
    prepare_workflow,
    run_workflow,
)

ILLUSTRATION = "a tidy reception desk with a plant and a closed notebook in soft daylight"


@pytest.fixture
def mock_settings(make_settings: Callable[..., Settings], tmp_path: Path,
                  monkeypatch: pytest.MonkeyPatch) -> Settings:
    logo = Image.new("RGBA", (480, 200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle((10, 40, 470, 160), fill=(0, 75, 160, 255))
    logo_path = tmp_path / "logo.png"
    logo.save(logo_path)
    for module in (direction_job, direction_brief):
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
                          topic="AI chatbots for practices", direction_platform="facebook",
                          count=1, **extra)  # type: ignore[arg-type]


def test_template_direction_needs_no_picture(mock_settings: Settings) -> None:
    prepared = prepare_workflow("social_creative", _inputs("FB-3", sample_copy()["FB-3/zigzag"]),
                                mock_settings)
    assert prepared.settings is not None and prepared.settings.image_provider == "template"
    assert prepared.design is not None and not prepared.person_shown
    assert "no picture generated" in prepared.request.prompt


def test_illustration_prompt_has_no_copy_and_no_text(mock_settings: Settings) -> None:
    copy = dict(sample_copy()["FB-1/post"], illustration=ILLUSTRATION)
    prepared = prepare_workflow("social_creative", _inputs("FB-1", copy), mock_settings)
    prompt = prepared.request.prompt
    assert ILLUSTRATION in prompt and "no text" in prompt.lower()
    assert "AI chatbot" not in prompt and prepared.settings is not None
    assert prepared.settings.image_provider == "mock"  # mock stays mock; live: openrouter
    copied = dict(copy, illustration="your AI chatbot for every channel on a desk")
    with pytest.raises(Exception, match="repeats the copy"):
        prepare_workflow("social_creative", _inputs("FB-1", copied), mock_settings)


def test_roman_lora_and_real_photo(mock_settings: Settings) -> None:
    lora = prepare_workflow("social_creative", _inputs("FD-2", sample_copy()["FD-2/post"]),
                            mock_settings)
    assert lora.person_shown and lora.request.person
    assert lora.request.prompt.startswith(load_directions().roman.prefix)
    real = prepare_workflow("social_creative", _inputs("FD-1", sample_copy()["FD-1/post"]),
                            mock_settings)
    assert not real.person_shown and real.design is not None
    assert real.inputs["realPhoto"] in ("2.jpg", "4.jpg")
    assert real.settings is not None and real.settings.image_provider == "template"


def test_mock_build_renders_and_checks_the_design(mock_settings: Settings) -> None:
    copy = dict(sample_copy()["LI-3/post"], illustration=ILLUSTRATION)
    job = run_workflow("social_creative", _inputs("LI-3", copy), mock_settings)
    assert job.status == "completed", job.error
    image = job.folder / job.outputs[0]
    manifest = json.loads(image.with_suffix(MANIFEST_SUFFIX).read_text(encoding="utf-8"))
    assert manifest["direction"] == "LI-3" and manifest["check"]["errors"] == []
    with Image.open(image) as made:
        assert made.size == (1080, 1350)
    assert any(note.startswith("Design: LI-3") for note in job.notes)
    cut = run_workflow("social_creative", _inputs("FD-1", sample_copy()["FD-1/post"]),
                       mock_settings)
    assert cut.status == "completed", cut.error


def test_too_long_copy_fails_the_job_not_silently(mock_settings: Settings) -> None:
    copy = dict(sample_copy()["FB-3/zigzag"])
    copy["headline"] = "How we build an AI agent in three very simple steps for every team?"
    job = run_workflow("social_creative", _inputs("FB-3", copy), mock_settings)
    assert job.status == "failed" and "shorten it" in str(job.error).lower()


def test_templates_and_brief_checks(mock_settings: Settings) -> None:
    catalog = load_directions()
    template = copy_template(catalog.get("FB-1").layouts["post"])
    assert len(template["capabilities"]) == 3 and len(template["icons"]) == 3
    roles = slide_roles(catalog.get("CS-1"))
    assert roles[0] == "cover" and roles[-1] == "cta"
    assert catalog.get("CS-1").slide_count[0] <= len(roles)  # type: ignore[index]
    slides = carousel_template(catalog.get("CS-1"))["slides"]
    brief_slides = []
    for slide in slides:
        layout = catalog.get("CS-1").layout_for(role=slide["directionRole"])[0]
        copy = dict(sample_copy()[f"CS-1/{layout}"], illustration=ILLUSTRATION)
        brief_slides.append({"directionRole": slide["directionRole"], "copy": copy,
                             "altText": "A slide about AI chatbots"})
    brief = ContentBrief.model_validate(_brief({"format": "carousel", "direction": "CS-1",
                                                "slides": brief_slides}))
    assert direction_problems(brief, catalog, mock_settings) == []
    brief_slides[1]["copy"]["body"] = "word " * 80
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
