import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.core.config import Settings
from content_automation.references import list_sets, load_set, scan, tag_assets
from content_automation.workflows.image_workflows import (
    WorkflowInputs,
    prepare_workflow,
    run_workflow,
)
from content_automation.workflows.registry import WORKFLOWS, WorkflowError

BRAND = {
    "brandName": "Test Brand",
    "colors": [{"name": "Royal Blue", "hex": "#004BA0", "usage": "main"}],
    "language": "English",
    "tone": "Confident and warm",
    "imageStyle": "Bright natural light",
    "dont": ["Don't stretch the logo"],
}
# The texts the "ad" format (the default design) requires.
AD_SUB, AD_CTA = "One system for content and leads.", "Learn more"


def _image(path: Path, index: int, size: tuple[int, int] = (600, 800)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, ((index * 41) % 256, (index * 97) % 256, 150)).save(path)


def _transparent_logo(path: Path) -> None:
    """A logo on a transparent background, as the app pastes it onto designs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    logo = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
    logo.paste((20, 80, 200, 255), (40, 110, 260, 190))
    logo.save(path)


@pytest.fixture
def library(isolated: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = isolated / "refs"
    for i in range(1, 7):
        _image(root / "identity" / "person_01" / f"{i}.jpg", i)
    for i in range(1, 11):
        _image(root / "product" / "mug" / f"mug{i}.jpg", 20 + i)
    for i in range(1, 13):
        _image(root / "creative" / "facebook_ads" / f"ad{i:02d}.jpg", 40 + i)
    _image(root / "brand" / "logo" / "a-mark.jpg", 60, (300, 300))
    _transparent_logo(root / "brand" / "logo" / "logo.png")
    (root / "brand" / "brand.json").write_text(json.dumps(BRAND), encoding="utf-8")
    scan(root)
    style = [a.asset_id for s in list_sets("creative", root) for a in s.ok_assets]
    tag_assets(style, people=False, logo=False, root=root)  # viewed: no people, no logo
    monkeypatch.setenv("REFERENCES_DIR", str(root))
    return root


@pytest.fixture
def settings(make_settings: Callable[..., Settings], library: Path) -> Settings:
    return make_settings()


def _details(folder: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((folder / "details.json").read_text(encoding="utf-8"))
    return data


def _ids(settings: Settings, set_id: str) -> dict[str, str]:
    return {a.file: a.asset_id for a in load_set(set_id, settings.references_dir).assets}


def test_person_lifestyle_end_to_end(settings: Settings) -> None:
    job = run_workflow(
        "person_lifestyle",
        WorkflowInputs(
            prompt="Laughing at a café table", identity_set="person_01",
            style_set="creative/facebook_ads", count=2, request="2 café photos",
        ),
        settings,
    )

    data = _details(job.folder)
    identity = _ids(settings, "identity/person_01")
    assert data["status"] == "completed" and len(data["outputs"]) == 2
    assert (data["workflowId"], data["workflowVersion"]) == ("person_lifestyle", "1")
    assert data["identityAssetIds"] == [identity[f"{i}.jpg"] for i in (1, 2, 3, 4)]
    ads = _ids(settings, "creative/facebook_ads")
    assert data["styleAssetIds"] == [ads["ad03.jpg"], ads["ad07.jpg"], ads["ad11.jpg"]]
    assert data["productAssetIds"] == [] and data["brandAssetIds"] == []
    assert data["request"] == "2 café photos"
    assert data["inputs"]["identitySet"] == "identity/person_01"
    prompt = data["prompt"]
    for expected in (
        "Laughing at a café table", "Images 1-4 - IDENTITY", "Keep this exact person",
        "Images 5-7 - STYLE", "copy only the look and layout", "Confident and warm",
        "Bright natural light", "Royal Blue #004BA0", "must be in English",
        "do not add any text", "the only person allowed", "No readable text in the scene",
    ):
        assert expected in prompt, expected
    # The model never handles the logo, so brand rules about it are left out.
    assert "stretch the logo" not in prompt


def test_person_service_end_to_end(settings: Settings) -> None:
    job = run_workflow(
        "person_service",
        WorkflowInputs(prompt="Advising a client", identity_set="person_01",
                       service="Tax advice for startups"),
        settings,
    )

    data = _details(job.folder)
    assert data["status"] == "completed"
    assert data["productAssetIds"] == []
    assert data["styleAssetIds"] == [] and data["brandAssetIds"] == []
    assert data["inputs"]["service"] == "Tax advice for startups"
    assert "Service: Tax advice for startups" in data["prompt"]
    assert data["params"]["aspectRatio"] == "4:5"


def test_social_creative_ad_with_logo_headline_and_default_style(settings: Settings) -> None:
    job = run_workflow(
        "social_creative",
        WorkflowInputs(
            prompt="Launch announcement", variant="ad", headline="Grow faster with AI",
            logo=True, product_set="mug", aspect_ratio="1:1",
            subheadline=AD_SUB, cta=AD_CTA,
        ),
        settings,
    )

    data = _details(job.folder)
    assert data["status"] == "completed"
    assert data["brandAssetIds"] == [_ids(settings, "brand/logo")["logo.png"]]
    # 10 product/style slots: 3 style leaves 7 for the product; the logo is not sent
    assert len(data["productAssetIds"]) == 7
    assert len(data["styleAssetIds"]) == 3
    assert [ref["role"] for ref in data["references"]] == ["product"] * 7 + ["style"] * 3
    assert data["inputs"]["styleSet"] == "creative/facebook_ads"
    assert data["inputs"]["variant"] == "ad"
    prompt = data["prompt"]
    assert "advertisement" in prompt
    assert '"GROW FASTER WITH AI"' in prompt  # headlines are rendered in capitals
    assert "Images 1-7 - PRODUCT" in prompt
    assert "BRAND LOGO" not in prompt and "Do not draw any logo" in prompt
    assert "Images 8-10 - STYLE" in prompt
    assert data["params"]["aspectRatio"] == "1:1"
    # The app pasted the logo; the model's image without it is kept.
    assert (job.folder / "raw" / "image-1.png").is_file()


@pytest.mark.parametrize(
    ("workflow_id", "inputs", "message"),
    [
        ("person_lifestyle", {}, "needs --set"),
        ("person_service", {"identity_set": "person_01"}, "needs --service"),
        ("person_lifestyle", {"identity_set": "person_01", "logo": True}, "does not use --logo"),
        ("social_creative", {"variant": "story"}, "--variant must be one of"),
        ("social_creative", {"aspect_ratio": "3:2"}, "--aspect must be one of"),
        ("nope", {}, "Unknown workflow"),
    ],
)
def test_bad_inputs_fail_before_any_job(
    settings: Settings, workflow_id: str, inputs: dict[str, Any], message: str
) -> None:
    with pytest.raises(WorkflowError, match=message):
        run_workflow(workflow_id, WorkflowInputs(prompt="x", **inputs), settings)
    assert not list(settings.output_dir.glob("*/*/details.json"))


def test_wrong_set_type_is_rejected(settings: Settings) -> None:
    with pytest.raises(ValueError, match="identity"):
        prepare_workflow(
            "person_lifestyle",
            WorkflowInputs(prompt="x", identity_set="creative/facebook_ads"),
            settings,
        )
    with pytest.raises(ValueError, match="product set is needed"):
        prepare_workflow(
            "social_creative",
            WorkflowInputs(
                prompt="x", product_set="person_01", headline="x", subheadline=AD_SUB,
                cta=AD_CTA,
            ),
            settings,
        )


def test_prompt_without_brand_file(settings: Settings, library: Path) -> None:
    (library / "brand" / "brand.json").unlink()

    prepared = prepare_workflow(
        "person_lifestyle", WorkflowInputs(prompt="x", identity_set="person_01"), settings
    )

    assert "Brand guidelines" not in prepared.request.prompt
    assert len(prepared.request.identity_refs) == 4


def test_registry_defaults() -> None:
    assert set(WORKFLOWS) == {"person_lifestyle", "person_service", "social_creative"}
    assert WORKFLOWS["social_creative"].default_style_set == "creative/facebook_ads"


def test_cli_workflow_mode_and_errors(settings: Settings) -> None:
    runner = CliRunner()

    ok = runner.invoke(app, [
        "image", "--workflow", "person_lifestyle", "--set", "identity/person_01",
        "--prompt", "Walking in a park", "--count", "3",
    ])
    missing = runner.invoke(app, ["image", "--workflow", "person_service", "--prompt", "x"])
    raw_with_set = runner.invoke(app, ["image", "--set", "person_01", "--prompt", "x"])

    assert ok.exit_code == 0, ok.output
    assert _details(Path(ok.stdout.strip()))["workflowId"] == "person_lifestyle"
    assert missing.exit_code == 1 and "needs --set, --service" in missing.output
    assert raw_with_set.exit_code == 1 and "need --workflow" in raw_with_set.output
    assert len(list(settings.output_dir.glob("*/*/details.json"))) == 1


def test_logo_file_from_brand_json_is_preferred(settings: Settings, library: Path) -> None:
    brand_file = library / "brand" / "brand.json"
    brand_file.write_text(json.dumps({**BRAND, "logoFile": "a-mark.jpg"}), encoding="utf-8")
    inputs = WorkflowInputs(
        prompt="x", logo=True, headline="x", subheadline=AD_SUB, cta=AD_CTA
    )

    # A logo without a transparent background cannot be pasted: a clear error, no job.
    with pytest.raises(WorkflowError, match="no transparent background"):
        prepare_workflow("social_creative", inputs, settings)

    brand_file.write_text(json.dumps({**BRAND, "logoFile": "logo.png"}), encoding="utf-8")
    prepared = prepare_workflow("social_creative", inputs, settings)
    assert prepared.brand_asset_ids == [_ids(settings, "brand/logo")["logo.png"]]

    brand_file.write_text(json.dumps({**BRAND, "logoFile": "missing.png"}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing.png"):
        prepare_workflow("social_creative", inputs, settings)


def test_style_count_changes_and_is_capped(settings: Settings) -> None:
    one = prepare_workflow(
        "person_lifestyle",
        WorkflowInputs(prompt="x", identity_set="person_01", style_set="facebook_ads",
                       style_count=1),
        settings,
    )
    many = prepare_workflow(
        "person_lifestyle",
        WorkflowInputs(prompt="x", identity_set="person_01", style_set="facebook_ads",
                       style_count=9),
        settings,
    )

    assert len(one.request.style_refs) == 1
    assert len(many.request.style_refs) == 3  # provider style limit
    with pytest.raises(WorkflowError, match="does not use --style-count"):
        prepare_workflow(
            "person_service",
            WorkflowInputs(prompt="x", identity_set="person_01", service="x",
                           style_count=2),
            settings,
        )


def test_dry_run_with_openrouter_needs_no_key_and_makes_nothing(
    library: Path, isolated: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from content_automation.ai.image.providers import openrouter

    def no_client(*_: object, **__: object) -> Any:
        raise AssertionError("provider client created during dry run")

    monkeypatch.setattr(openrouter.httpx, "Client", no_client)
    monkeypatch.setenv("IMAGE_PROVIDER", "openrouter")
    monkeypatch.setenv("IMAGE_MODEL", "google/gemini-3.1-flash-image")

    result = CliRunner().invoke(app, [
        "image", "--workflow", "person_lifestyle", "--set", "identity/person_01",
        "--style", "creative/facebook_ads", "--prompt", "At a café", "--count", "3",
        "--dry-run",
    ])

    assert result.exit_code == 0, result.output
    for expected in (
        "DRY RUN", "Provider: openrouter", "Provider calls: 3", "Estimated cost: $0.201",
        "identity (4): identity/person_01/1.jpg", "style (3): creative/facebook_ads/ad03.jpg",
        "Images 1-4 - IDENTITY", "Daily limit: 0 of",
    ):
        assert expected in result.output, expected
    assert not (isolated / "outputs").exists()


def test_dry_run_raw_mode_with_mock(library: Path, isolated: Path) -> None:
    result = CliRunner().invoke(
        app, ["image", "--prompt", "Plain prompt", "--count", "2", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert "Provider calls: 1" in result.output and "$0.000" in result.output
    assert "Plain prompt" in result.output
    assert not (isolated / "outputs").exists()
