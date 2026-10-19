"""Roman via Higgsfield Soul 2.0 (2026-10-20): prompts, rotation, the Codex job file, the
person-safe crop and the strict checks. Offline: stand-in pictures, no plugin, no provider."""

import hashlib
import json
import random
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw
from typer.testing import CliRunner

from content_automation.ai.image import ImageAwaitingAgent, ImageProviderError, ImageRequest
from content_automation.ai.image.higgsfield import HiggsfieldSoulProvider, fail, record
from content_automation.ai.image.providers.higgsfield_soul import generation_aspect
from content_automation.cli import app
from content_automation.content import direction_brief
from content_automation.content.design_preview import sample_copy
from content_automation.content.roman_prompt import (
    Combination,
    all_combinations,
    allowed,
    build_prompt,
    is_combination,
    load_guidelines,
    parse_combination,
    pick_combination,
)
from content_automation.content.roman_standin import stand_in
from content_automation.core.config import Settings
from content_automation.core.person_zone import CropError, detect, safe_crop
from content_automation.registry.jobs import load_job_config
from content_automation.workflows import design_check, direction_job, image_job, image_workflows
from content_automation.workflows.image_workflows import WorkflowInputs, run_workflow
from content_automation.workflows.roman_check import (
    calm_problems,
    german_problems,
    overlap_problems,
)

FIXTURES = Path(__file__).parent / "fixtures" / "roman_prompts"
_SPACE = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


# --- prompts ------------------------------------------------------------------------------------


@pytest.mark.parametrize("combination", ["S-R/BG-1/P-1/H-1", "S-R/BG-2/P-2/H-2",
                                         "S-R/BG-3/P-3/H-3"])
def test_golden_prompts(combination: str) -> None:
    expected = (FIXTURES / f"{combination.replace('/', '_')}.txt").read_text(encoding="utf-8")
    made = build_prompt(parse_combination(combination), token="@Roman")
    assert _norm(made) == _norm(expected)


def test_the_character_comes_from_config_never_the_code() -> None:
    config = load_guidelines()["higgsfield"]
    assert build_prompt(parse_combination("S-R/BG-1/P-1/H-1")).startswith(
        "@" + config["characterName"])
    source = (Path(__file__).parents[1] / "src/content_automation/content/roman_prompt.py"
              ).read_text(encoding="utf-8")
    assert config["characterName"] not in source and "Traenkle" not in source


def test_s_l_mirrors_the_words_never_right_edge() -> None:
    for combination in all_combinations():
        prompt = build_prompt(combination)
        if combination.side == "S-L":
            assert "right edge" not in prompt and "rightmost" not in prompt
            assert "confined to the left third of the frame" in prompt
            assert "leftmost 20%" in prompt
        else:
            assert "confined to the right third of the frame" in prompt
            assert "left edge" not in prompt and "leftmost" not in prompt


def test_54_combinations_with_compatible_poses() -> None:
    combinations = all_combinations()
    assert len(combinations) == len({item.id for item in combinations}) == 54
    rules = load_guidelines()
    for item in combinations:  # every pose has its wording for every background (data)
        assert rules["poses"][item.pose]["byBackground"][item.background]


def test_override_parsing() -> None:
    assert parse_combination("use S-L BG-1 P-2 H-3").id == "S-L/BG-1/P-2/H-3"
    assert parse_combination("s-r/bg-2/p-3/h-1").id == "S-R/BG-2/P-3/H-1"
    assert not is_combination("LI-R1") and not is_combination("S-L BG-4 P-1 H-1")
    chosen, why = pick_combination("x", ["S-L/BG-1/P-2/H-3"], override="S-L BG-1 P-2 H-3")
    assert chosen.id == "S-L/BG-1/P-2/H-3" and why == "as asked"


def test_rotation_rules_over_a_long_run() -> None:
    history: list[str] = []
    for number in range(60):
        chosen, _ = pick_combination(f"BG-{number}", history)
        if history:
            last = parse_combination(history[0])
            assert chosen.background != last.background and chosen.pose != last.pose
            assert chosen.hologram != last.hologram
        assert not (len(history) >= 2 and all(
            parse_combination(item).side == chosen.side for item in history[:2]))
        assert chosen.id not in history[:12]
        history.insert(0, chosen.id)
    assert {parse_combination(item).side for item in history} == {"S-R", "S-L"}
    same = Combination("S-R", "BG-1", "P-1", "H-1")
    assert not allowed(Combination("S-R", "BG-2", "P-2", "H-2"),
                       [Combination("S-R", "BG-3", "P-3", "H-3"), same])  # 3rd S-R in a row


# --- the provider: job file, attempts, crop ------------------------------------------------------


def _request(aspect: str = "4:5", combination: str = "S-R/BG-1/P-1/H-1") -> ImageRequest:
    found = parse_combination(combination)
    return ImageRequest(prompt=build_prompt(found), aspect_ratio=aspect, person=True,  # type: ignore[arg-type]
                        options={"combination": found.id, "side": found.side})


def _provider(make_settings: Callable[..., Settings], tmp_path: Path) -> HiggsfieldSoulProvider:
    return HiggsfieldSoulProvider(make_settings(OUTPUT_DIR=str(tmp_path / "outputs" / "jobs")))


def _deliver(provider: HiggsfieldSoulProvider, request: ImageRequest, picture: Image.Image,
             tmp_path: Path, credits: float | None = 4.0) -> str:
    job_file = provider.waiting(request)
    assert job_file is not None
    data = json.loads(job_file.read_text(encoding="utf-8"))
    made = tmp_path / f"made-{len(data['attempts'])}.png"
    picture.save(made)
    record(provider.root(), data["key"], made, credits)
    return str(data["key"])


def test_job_file_has_everything_codex_needs(make_settings: Callable[..., Settings],
                                             tmp_path: Path) -> None:
    provider = _provider(make_settings, tmp_path)
    request = _request()
    with pytest.raises(ImageAwaitingAgent) as waiting:
        provider.generate(request, "soul")
    data = json.loads(waiting.value.job_file.read_text(encoding="utf-8"))
    assert data["prompt"] == request.prompt and data["model"] == "Soul 2.0"
    assert data["characterName"] == "Roman Traenkle" and data["aspectRatio"] == "3:4"
    assert data["targetAspect"] == "4:5" and data["cropToTarget"] and data["images"] == 1
    assert data["maxAttempts"] == 2 and data["estimate"]["creditsPerImage"] > 0
    assert data["expectedOutput"].endswith("attempt-1.png")
    assert any("ca higgsfield record" in line for line in data["instructions"])


@pytest.mark.parametrize(("target", "wanted"), [("4:5", "3:4"), ("3:4", "3:4"), ("1:1", "1:1"),
                                                ("9:16", "9:16"), ("16:9", "16:9")])
def test_soul_aspects(target: str, wanted: str) -> None:
    assert generation_aspect(target) == wanted
    assert generation_aspect(target) in load_guidelines()["higgsfield"]["aspectRatios"]


def test_person_right_passes_and_the_4_5_crop_keeps_head_and_hands(
        make_settings: Callable[..., Settings], tmp_path: Path) -> None:
    provider = _provider(make_settings, tmp_path)
    request = _request()
    _deliver(provider, request, stand_in((1080, 1440), "S-R", "P-1"), tmp_path)
    result = provider.generate(request, "soul")
    with Image.open(__import__("io").BytesIO(result.images[0].data)) as made:
        assert made.size == (1080, 1350)  # 3:4 -> 4:5: 90 px of height, never upscaled
        zone = detect(made.convert("RGB"))
    original = detect(stand_in((1080, 1440), "S-R", "P-1"))
    assert zone.head_top is not None and original.head_top is not None
    assert zone.head_top == original.head_top  # taken from the bottom
    assert result.cost_usd is not None and result.metrics["credits"] == 4.0


def test_person_left_is_rejected_then_fails_after_two(
        make_settings: Callable[..., Settings], tmp_path: Path) -> None:
    provider = _provider(make_settings, tmp_path)
    request = _request("3:4")
    wrong = stand_in((1080, 1440), "S-L", "P-2")  # planned S-R, delivered on the left
    _deliver(provider, request, wrong, tmp_path)
    with pytest.raises(ImageAwaitingAgent, match="attempt rejected"):
        provider.generate(request, "soul")
    _deliver(provider, request, wrong, tmp_path, credits=None)  # unreported: the estimate
    with pytest.raises(ImageProviderError, match="no fallback") as failed:
        provider.generate(request, "soul")
    estimate = load_guidelines()["higgsfield"]["estimatedCreditsPerImage"]
    usd = load_guidelines()["higgsfield"]["usdPerCredit"]
    assert failed.value.cost_usd == round((4.0 + estimate) * usd, 4)  # every attempt counted


def test_figure_in_the_middle_fails_the_zone(make_settings: Callable[..., Settings],
                                             tmp_path: Path) -> None:
    provider = _provider(make_settings, tmp_path)
    request = _request("1:1")
    _deliver(provider, request, stand_in((1080, 1080), "S-R", "P-3", offset=0.45), tmp_path)
    with pytest.raises(ImageAwaitingAgent):
        provider.generate(request, "soul")


def test_wrong_aspect_and_plugin_failure(make_settings: Callable[..., Settings],
                                         tmp_path: Path) -> None:
    provider = _provider(make_settings, tmp_path)
    request = _request()
    job_file = provider.waiting(request)
    assert job_file is not None
    key = json.loads(job_file.read_text(encoding="utf-8"))["key"]
    square = tmp_path / "square.png"
    Image.new("RGB", (512, 512)).save(square)
    with pytest.raises(Exception, match="not 3:4"):
        record(provider.root(), key, square, 4)
    assert fail(provider.root(), key, "plugin missing").data["status"] == "pending"
    assert fail(provider.root(), key, "again").data["status"] == "failed"


def test_no_safe_crop_fails() -> None:
    tall = stand_in((1080, 1440), "S-R", "P-1")
    zone = detect(tall)
    with pytest.raises(CropError):
        safe_crop(tall, (3, 1), zone)  # a 3:1 strip cannot hold head and hands


# --- the strict checks after the overlay ---------------------------------------------------------


def _manifest(boxes: dict[str, tuple[int, int, int, int]]) -> dict[str, object]:
    return {"size": [1080, 1440], "texts": [
        {"zone": zone, "text": "Text", "box": list(box)} for zone, box in boxes.items()]}


def test_overlap_fixture_fails_and_the_layouts_pass() -> None:
    good = _manifest({"headline": (65, 288, 626, 720)})
    assert overlap_problems(good, "S-R", share=0.3334, min_gap_px=48) == []
    near = _manifest({"cta": (65, 1210, 700, 1310)})  # 20 px from Roman's third
    assert "needs 48 px" in overlap_problems(near, "S-R", share=0.3334, min_gap_px=48)[0]
    into = _manifest({"headline": (200, 288, 1000, 720)})  # mirrored side: into his third
    assert "overlaps" in overlap_problems(into, "S-L", share=0.3334, min_gap_px=48)[0]


def test_busy_text_zone_fixture_fails() -> None:
    calm = stand_in((1080, 1440), "S-R", "P-1")
    boxes = _manifest({"headline": (65, 288, 626, 720)})
    assert calm_problems(calm, boxes, max_std=30, max_detail=12) == []
    busy = calm.copy()
    draw = ImageDraw.Draw(busy)
    for x in range(65, 626, 12):  # a striped, high-detail backdrop behind the headline
        draw.rectangle((x, 288, x + 5, 720), fill=(240, 240, 240))
    assert "busy background" in calm_problems(busy, boxes, max_std=30, max_detail=12)[0]
    noise = np.random.default_rng(1).integers(0, 255, (1440, 1080, 3), dtype=np.uint8)
    assert calm_problems(Image.fromarray(noise), boxes, max_std=30, max_detail=12)


def test_misspelled_german_fixture_fails() -> None:
    good, how = german_problems([("headline", "Erst der Prozess, dann das Tool"),
                                 ("sub", "Sie übernimmt Routinen, damit Ihr Team Zeit hat.")])
    assert good == [] and how.startswith("Spelling:")
    bad, _ = german_problems([("headline", "Die Vorraussetzung für KI"),
                              ("sub", "Wir planen die umsetzung mit Ihnen"),
                              ("cta", "Mass- nahme anfragen"),
                              ("sub2", "Mehr erfahren und Massnahmen planen")])
    joined = " | ".join(bad)
    assert "Voraussetzung" in joined and '"Umsetzung"' in joined
    assert "hyphenation" in joined and "Maßnahmen" in joined


# --- the whole job: waits for Codex, then draws and checks ----------------------------------


@pytest.fixture
def live(make_settings: Callable[..., Settings], tmp_path: Path,
         monkeypatch: pytest.MonkeyPatch) -> Settings:
    logo = Image.new("RGBA", (480, 200), (0, 0, 0, 0))
    ImageDraw.Draw(logo).rectangle((10, 40, 470, 160), fill=(0, 75, 160, 255))
    logo_path = tmp_path / "logo.png"
    logo.save(logo_path)
    for module in (direction_job, direction_brief, image_workflows):
        monkeypatch.setattr(module, "logo_file", lambda *_: logo_path)
    official = {hashlib.sha256(logo_path.read_bytes()).hexdigest()}
    monkeypatch.setattr(design_check, "_official_hashes", lambda _: official)
    free = replace(load_job_config(), free_providers=("mock", "template", "higgsfield_soul"))
    monkeypatch.setattr(image_job, "load_job_config", lambda *_: free)  # no registry here
    repo = Path(__file__).resolve().parents[1]
    return make_settings(IMAGE_PROVIDER="openrouter", OPENROUTER_API_KEY="sk-or-v1-test",
                         REFERENCES_DIR=str(tmp_path / "refs"),
                         OUTPUT_DIR=str(tmp_path / "outputs" / "jobs"),
                         BRAND_FILE=str(repo / "config" / "brand.json"),
                         SERVICES_FILE=str(repo / "config" / "services.json"))


def _inputs(layout: str, combination: str) -> WorkflowInputs:
    return WorkflowInputs(direction="FB-R1", direction_platform="facebook", count=1,
                          topic="KI im Team", roman_combination=combination,
                          format_copy=json.dumps(sample_copy()[f"FB-R1/{layout}"]))


def test_job_waits_for_codex_then_draws_and_checks(live: Settings, tmp_path: Path) -> None:
    inputs = _inputs("roman_left", "S-L/BG-2/P-2/H-2")
    with pytest.raises(ImageAwaitingAgent) as waiting:
        run_workflow("social_creative", inputs, live)
    assert not list((tmp_path / "outputs" / "jobs").glob("*/*/details.json"))  # no job yet
    data = json.loads(waiting.value.job_file.read_text(encoding="utf-8"))
    assert data["combination"] == "S-L/BG-2/P-2/H-2" and data["aspectRatio"] == "3:4"
    made = tmp_path / "soul.png"
    stand_in((1080, 1440), "S-L", "P-2").save(made)
    result = CliRunner().invoke(app, ["higgsfield", "record", data["key"], "--file", str(made),
                                      "--credits", "4"], env={
                                          "OUTPUT_DIR": str(tmp_path / "outputs" / "jobs")})
    assert result.exit_code == 0, result.output
    job = run_workflow("social_creative", inputs, live)
    assert job.status == "completed", job.error
    assert job.provider == "higgsfield_soul" and job.actual_cost_usd
    manifest = json.loads((job.folder / "image-1.design.json").read_text(encoding="utf-8"))
    checks = manifest["check"]["romanChecks"]
    assert all(checks[name] == "passed" for name in ("personZone", "overlap", "textZoneCalm",
                                                     "german")), checks
    assert manifest["check"]["errors"] == [] and manifest["layout"] == "roman_left"
    with Image.open(job.folder / "image-1.png") as final:
        assert final.size == (1080, 1350)
    assert any(note.startswith("Roman checks:") for note in job.notes)
    assert str(job.inputs["aiDisclosure"]).startswith("KI-generiertes Bild")


def test_the_paid_route_waits_for_the_ok(live: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(image_job, "load_job_config", lambda *_: load_job_config())
    with pytest.raises(Exception, match="authorization"):
        run_workflow("social_creative", _inputs("roman_right", "S-R/BG-1/P-1/H-1"), live)


def test_visual_review_needs_four_answers(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["job", "review", str(tmp_path), "--visual", "text=yes"])
    assert result.exit_code == 2 and "overlap, logo, german" in result.output


def test_random_seeds_spread_over_all_parts() -> None:
    seen = {pick_combination(str(random.Random(n).random()), [])[0] for n in range(200)}
    assert {item.background for item in seen} == {"BG-1", "BG-2", "BG-3"}
    assert {item.pose for item in seen} == {"P-1", "P-2", "P-3"}
    assert {item.hologram for item in seen} == {"H-1", "H-2", "H-3"}
