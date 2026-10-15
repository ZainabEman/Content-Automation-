"""Track L: the Z-Image Turbo LoRA in config, the workflow and the person-prompt rules (offline)."""

import hashlib
import json
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

from content_automation.ai.image.providers.comfyui import (
    PersonPhoto,
    build_graph,
    load_config,
    load_workflow,
    model_file_problems,
    model_sizes,
    person_image_prompt,
    person_photo_prompt,
)
from content_automation.core.config import Settings
from content_automation.lora import LoraError, set_lora

REPO = Path(__file__).resolve().parents[1]


def test_lora_set_records_the_manifest_sha256(isolated: Path,
                                              make_settings: Callable[..., Settings]) -> None:
    (isolated / "config").mkdir()
    for name in ("comfyui.json", "lora.json"):
        shutil.copy(REPO / "config" / name, isolated / "config" / name)
    lora = isolated / "outputs" / "lora" / "zimage" / "r0man_test.safetensors"
    lora.parent.mkdir(parents=True)
    lora.write_bytes(b"fake lora weights")
    sha = hashlib.sha256(b"fake lora weights").hexdigest()
    (lora.parent / "MANIFEST.json").write_text(json.dumps({"sha256": sha}), encoding="utf-8")
    settings = make_settings(comfyui_config_file="config/comfyui.json",
                             lora_config_file="config/lora.json")

    lines = set_lora(settings, "zimage", "outputs/lora/zimage/r0man_test.safetensors")
    assert any(sha in line for line in lines)
    spec = json.loads((isolated / "config" / "comfyui.json").read_text(encoding="utf-8"))
    workflow = spec["workflows"]["z_image_turbo"]
    assert workflow["loraName"] == "r0man_test.safetensors" and workflow["loraSha256"] == sha

    (lora.parent / "MANIFEST.json").write_text(json.dumps({"sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(LoraError, match="does not match"):
        set_lora(settings, "zimage", "outputs/lora/zimage/r0man_test.safetensors")


def test_person_photo_prompt_and_the_workflow() -> None:
    config = load_config(REPO / "config" / "comfyui.json")
    prompt = person_photo_prompt(config)  # the template only: never the post's copy or scene
    assert prompt.startswith("r0man_bg, a man, dark navy blazer, white open-collar shirt, ")
    assert prompt.endswith("nothing written anywhere, no objects")
    assert config.person_photo.size == (1024, 1280)
    with pytest.raises(ValueError, match="no numbers, signs or screen words"):
        PersonPhoto(outfits=["navy blazer with a laptop"])
    assert config.person_image.mode == "scene"  # the default look: a photo scene
    scene = person_image_prompt(config)
    assert scene.startswith("r0man_bg, a man, dark navy blazer, white open-collar shirt, "
                            "standing in a modern bright office, in the right half")
    assert scene.endswith("plain walls, nothing written anywhere")

    workflow = load_workflow(config, "z_image_turbo")
    assert model_file_problems(config, workflow) == []
    assert (workflow.spec.steps, workflow.spec.cfg) == (9, 1.0)
    assert model_sizes(config, workflow.spec)["1:1"] == (1024, 1024)
    lora = workflow.mapping.inputs["lora_name"].node
    graph = build_graph(workflow, config, prompt=prompt, width=1024, height=1024, seed=1,
                        person=True, lora_strength=0.8)
    assert graph[lora]["inputs"]["strength_model"] == 0.8
    assert graph[lora]["inputs"]["lora_name"] == workflow.spec.lora_name
    plain = build_graph(workflow, config, prompt="a laptop", width=1024, height=1024, seed=1,
                        person=False)
    assert lora not in plain  # no person: the LoRA node is bypassed


def test_comfyui_runs_its_own_workflow(make_settings: Callable[..., Settings]) -> None:
    from content_automation.ai.image import model_for

    comfy = make_settings().model_copy(update={
        "image_provider": "comfyui", "image_model": "google/gemini-3.1-flash-image"})
    assert model_for(comfy) == "z_image_turbo"  # an OpenRouter IMAGE_MODEL never blocks it
    assert model_for(comfy.model_copy(update={"image_model": "qwen_image_2512"})) == (
        "qwen_image_2512")
    openrouter = comfy.model_copy(update={"image_provider": "openrouter"})
    assert model_for(openrouter) == "google/gemini-3.1-flash-image"
