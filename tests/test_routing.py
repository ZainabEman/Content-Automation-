"""PRD v5 R6 / §7.8 (2026-10-20): requires_roman → Higgsfield Soul 2.0 (Codex, his saved
character), everything else → OpenRouter (PRD v6 R5: the only two image providers); no silent
fallback; no secret in prompts, job records, manifests or package files (mock only, offline)."""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from content_automation.content import direction_brief
from content_automation.content.design_preview import sample_copy
from content_automation.content.directions import load_directions
from content_automation.content.routing import image_route
from content_automation.core.config import Settings
from content_automation.workflows import design_check, direction_job, image_workflows
from content_automation.workflows.image_workflows import (
    WorkflowInputs,
    prepare_workflow,
    run_workflow,
)
from content_automation.workflows.registry import WorkflowError

OPENROUTER_KEY = "sk-or-v1-fakefakefake0123456789routingtest"
ILLUSTRATION = "a glowing glass chat bubble above a dark pedestal"


@pytest.fixture
def mock_settings(make_settings: Callable[..., Settings], tmp_path: Path,
                  monkeypatch: pytest.MonkeyPatch) -> Settings:
    logo = Image.new("RGBA", (480, 200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle((10, 40, 470, 160), fill=(0, 75, 160, 255))
    logo_path = tmp_path / "logo.png"
    logo.save(logo_path)
    for module in (direction_job, direction_brief, image_workflows):
        monkeypatch.setattr(module, "logo_file", lambda *_: logo_path)
    official = {hashlib.sha256(logo_path.read_bytes()).hexdigest()}
    monkeypatch.setattr(design_check, "_official_hashes", lambda _: official)
    refs = tmp_path / "refs" / "identity" / "person_01"
    refs.mkdir(parents=True)
    (refs / "set.json").write_text(json.dumps({
        "setId": "identity/person_01", "name": "person_01", "type": "identity", "assets": []}),
        encoding="utf-8")
    repo = Path(__file__).resolve().parents[1]
    return make_settings(IMAGE_PROVIDER="mock", REFERENCES_DIR=str(tmp_path / "refs"),
                         BRAND_FILE=str(repo / "config" / "brand.json"),
                         SERVICES_FILE=str(repo / "config" / "services.json"),
                         OPENROUTER_API_KEY=OPENROUTER_KEY)


def _designer_files(refs: Path, direction_id: str) -> None:
    """Stand-ins for the guide (a PDF holding one JPEG) and the variant's references."""
    import io

    page = io.BytesIO()
    Image.new("RGB", (40, 56), (240, 240, 240)).save(page, format="JPEG")
    guide = refs / "brand" / "guidelines" / "Branded Genius Brand Style Guide.pdf"
    guide.parent.mkdir(parents=True, exist_ok=True)
    guide.write_bytes(b"%PDF-1.4 /Filter /DCTDecode /Length 1 >>\nstream\n" + page.getvalue()
                      + b"\nendstream")
    known = json.loads((Path(__file__).resolve().parents[1] / "config" / "brand_refs.json")
                       .read_text(encoding="utf-8"))["refs"]
    for ref_id in load_directions().get(direction_id).reference_ids:
        target = refs / known[ref_id].get("masked", known[ref_id]["file"])  # v6: masked
        target.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (32, 32), (3, 6, 18)).save(target)


def _inputs(direction: str, copy: dict[str, object], **extra: object) -> WorkflowInputs:
    return WorkflowInputs(direction=direction, format_copy=json.dumps(copy), topic="KI im Team",
                          **{"direction_platform": "linkedin", "count": 1,
                             **extra})  # type: ignore[arg-type]


def test_the_route_follows_requires_roman() -> None:
    assert image_route(True) == "higgsfield_soul" and image_route(False) == "codex_builtin"
    assert image_route(True, picture=False) == "template"


def test_roman_never_runs_without_a_combination(mock_settings: Settings) -> None:
    """No other route for Roman: no combination is never a silent swap to another provider."""
    assert all(d.provider in ("openrouter", "higgsfield_soul") for d in load_directions()
               .directions)


def test_roman_goes_to_higgsfield_others_to_openrouter(mock_settings: Settings) -> None:
    live = mock_settings.model_copy(update={"image_provider": "openrouter"})
    roman = prepare_workflow("social_creative", _inputs(
        "LI-R1", sample_copy()["LI-R1/roman_left"], roman_combination="S-L/BG-2/P-3/H-1"), live)
    assert roman.inputs["route"] == "higgsfield_soul" and roman.settings is not None
    assert roman.settings.image_provider == "higgsfield_soul"
    assert roman.inputs["romanCombination"] == "S-L/BG-2/P-3/H-1"
    assert roman.inputs["layout"] == "roman_left"
    assert roman.request.prompt.startswith("@Roman Traenkle 2")
    assert roman.request.aspect_ratio == "3:4" and not roman.request.identity_refs
    assert roman.request.options == {"combination": "S-L/BG-2/P-3/H-1", "side": "S-L"}
    _designer_files(Path(live.references_dir), "LI-1")
    other = prepare_workflow("social_creative", _inputs("LI-1", dict(
        sample_copy()["LI-1/post"], illustration=ILLUSTRATION)), live.model_copy(update={
            "image_provider": "template"}))  # v5b: codex_builtin unless openrouter opts in
    assert other.inputs["route"] == "codex_builtin" and other.settings is not None
    assert other.settings.image_provider == "codex_builtin" and not other.request.person


def test_a_variant_must_match_the_planned_flag(mock_settings: Settings) -> None:
    with pytest.raises(WorkflowError, match="requires_roman=true"):
        prepare_workflow("social_creative", _inputs("LI-1", dict(
            sample_copy()["LI-1/post"], illustration=ILLUSTRATION), requires_roman=True),
            mock_settings)
    with pytest.raises(WorkflowError, match="requires_roman=false"):
        prepare_workflow("social_creative", _inputs("LI-R1", sample_copy()["LI-R1/roman_right"],
                                                    requires_roman=False), mock_settings)


def test_no_secret_in_prompts_job_records_or_manifests(mock_settings: Settings) -> None:
    from pydantic import SecretStr

    keyed = mock_settings.model_copy(update={"openrouter_api_key": SecretStr(OPENROUTER_KEY)})
    texts: list[str] = []
    for direction_id, copy in (("LI-R1", sample_copy()["LI-R1/roman_right"]),
                               ("LI-2", dict(sample_copy()["LI-2/post"],
                                             illustration=ILLUSTRATION))):
        prepared = prepare_workflow("social_creative", _inputs(direction_id, copy), keyed)
        texts += [prepared.request.prompt, json.dumps(prepared.inputs, default=str)]
        job = run_workflow("social_creative", _inputs(direction_id, copy), keyed)
        assert job.status == "completed", job.error
        texts += [path.read_text(encoding="utf-8", errors="ignore")
                  for path in job.folder.rglob("*") if path.suffix in (".json", ".txt", ".md")]
    joined = "\n".join(texts)
    for secret in (OPENROUTER_KEY,):
        assert secret not in joined and secret[-12:] not in joined
