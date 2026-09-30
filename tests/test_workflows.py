import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PIL import Image
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.core.config import Settings
from content_automation.references import load_set, scan
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


def _image(path: Path, index: int, size: tuple[int, int] = (600, 800)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, ((index * 41) % 256, (index * 97) % 256, 150)).save(path)


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
    _image(root / "brand" / "logo" / "logo.png", 61, (300, 300))
    (root / "brand" / "brand.json").write_text(json.dumps(BRAND), encoding="utf-8")
    scan(root)
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
    assert len(data["styleAssetIds"]) == 10  # mock cap
    assert data["productAssetIds"] == [] and data["brandAssetIds"] == []
    assert data["request"] == "2 café photos"
    assert data["inputs"]["identitySet"] == "identity/person_01"
    prompt = data["prompt"]
    for expected in (
        "Laughing at a café table", "Images 1-4 - IDENTITY", "Keep this exact person",
        "Images 5-14 - STYLE", "copy only the look and layout", "Confident and warm",
        "Bright natural light", "Royal Blue #004BA0", "Avoid: Don't stretch the logo.",
        "must be in English", "do not add any text",
    ):
        assert expected in prompt, expected


def test_person_product_end_to_end(settings: Settings) -> None:
    job = run_workflow(
        "person_product",
        WorkflowInputs(prompt="Holding the mug", identity_set="person_01", product_set="mug"),
        settings,
    )

    data = _details(job.folder)
    assert data["status"] == "completed"
    assert data["productAssetIds"] == list(_ids(settings, "product/mug").values())
    assert data["styleAssetIds"] == [] and data["brandAssetIds"] == []
    assert "Images 5-14 - PRODUCT: include this exact product" in data["prompt"]
    assert data["params"]["aspectRatio"] == "4:5"


def test_social_creative_ad_with_logo_headline_and_default_style(settings: Settings) -> None:
    job = run_workflow(
        "social_creative",
        WorkflowInputs(
            prompt="Launch announcement", variant="ad", headline="Grow faster with AI",
            logo=True, product_set="mug", aspect_ratio="1:1",
        ),
        settings,
    )

    data = _details(job.folder)
    assert data["status"] == "completed"
    assert data["brandAssetIds"] == [_ids(settings, "brand/logo")["logo.png"]]
    assert len(data["productAssetIds"]) == 9  # one object slot kept for the logo
    assert len(data["styleAssetIds"]) == 10
    assert data["inputs"]["styleSet"] == "creative/facebook_ads"
    assert data["inputs"]["variant"] == "ad"
    prompt = data["prompt"]
    assert "advertisement" in prompt
    assert '"Grow faster with AI"' in prompt
    assert "Images 1-9 - PRODUCT" in prompt
    assert "Image 10 - BRAND LOGO" in prompt
    assert "Images 11-20 - STYLE" in prompt
    assert data["params"]["aspectRatio"] == "1:1"


@pytest.mark.parametrize(
    ("workflow_id", "inputs", "message"),
    [
        ("person_lifestyle", {}, "needs --set"),
        ("person_product", {"identity_set": "person_01"}, "needs --product"),
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
            "person_product",
            WorkflowInputs(prompt="x", identity_set="person_01", product_set="person_01"),
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
    assert set(WORKFLOWS) == {"person_lifestyle", "person_product", "social_creative"}
    assert WORKFLOWS["social_creative"].default_style_set == "creative/facebook_ads"


def test_cli_workflow_mode_and_errors(settings: Settings) -> None:
    runner = CliRunner()

    ok = runner.invoke(app, [
        "image", "--workflow", "person_lifestyle", "--set", "identity/person_01",
        "--prompt", "Walking in a park", "--count", "3",
    ])
    missing = runner.invoke(app, ["image", "--workflow", "person_product", "--prompt", "x"])
    raw_with_set = runner.invoke(app, ["image", "--set", "person_01", "--prompt", "x"])

    assert ok.exit_code == 0, ok.output
    assert _details(Path(ok.stdout.strip()))["workflowId"] == "person_lifestyle"
    assert missing.exit_code == 1 and "needs --set, --product" in missing.output
    assert raw_with_set.exit_code == 1 and "need --workflow" in raw_with_set.output
    assert len(list(settings.output_dir.glob("*/*/details.json"))) == 1


def test_logo_file_from_brand_json_is_preferred(settings: Settings, library: Path) -> None:
    brand_file = library / "brand" / "brand.json"
    brand_file.write_text(json.dumps({**BRAND, "logoFile": "a-mark.jpg"}), encoding="utf-8")
    inputs = WorkflowInputs(prompt="x", logo=True)

    prepared = prepare_workflow("social_creative", inputs, settings)
    assert prepared.brand_asset_ids == [_ids(settings, "brand/logo")["a-mark.jpg"]]

    brand_file.write_text(json.dumps({**BRAND, "logoFile": "missing.png"}), encoding="utf-8")
    with pytest.raises(ValueError, match="missing.png"):
        prepare_workflow("social_creative", inputs, settings)
