"""Phase D step 6: Roman's identity rules (offline: drawn stand-in photos, no provider called)."""

from pathlib import Path

import pytest
from PIL import Image

from content_automation.content.directions import load_directions
from content_automation.content.roman import (
    RomanError,
    approved_photos,
    check_strength,
    identity_sheet,
    pick_real_photo,
    prompt_problems,
    roman_prompt,
    text_side,
)


def _photos(folder: Path, names: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        Image.new("RGB", (120, 160), (90, 90, 90)).save(folder / name)


def test_every_pool_combination_passes_the_rules() -> None:
    catalog = load_directions()
    for direction_id in ("FD-2", "FD-3"):
        direction = catalog.get(direction_id)
        for name in direction.layouts:
            layout = direction.layouts[name]
            prompts = {roman_prompt(direction, layout, catalog.roman, seed=str(seed))
                       for seed in range(120)}
            assert len(prompts) > 10
            for prompt in prompts:
                assert prompt.startswith(catalog.roman.prefix) and prompt.endswith("no text")
    assert roman_prompt(catalog.get("FD-3"), catalog.get("FD-3").layouts["editorial"],
                        catalog.roman, seed="BG-4") == roman_prompt(
        catalog.get("FD-3"), catalog.get("FD-3").layouts["editorial"], catalog.roman,
        seed="BG-4")


def test_real_photo_directions_never_get_a_lora_prompt() -> None:
    catalog = load_directions()
    direction = catalog.get("FD-1")
    with pytest.raises(RomanError, match="does not use Roman's LoRA"):
        roman_prompt(direction, direction.layouts["post"], catalog.roman, seed="x")


def test_blocked_props_and_missing_rules_are_refused() -> None:
    rules = load_directions().roman
    bad = f"{rules.prefix}, on a yacht at sunset, holding champagne"
    problems = prompt_problems(bad, rules)
    assert any("yacht" in p for p in problems) and any("champagne" in p for p in problems)
    assert any("alone" in p for p in problems) and any("no text" in p for p in problems)
    assert any("trigger" in p for p in prompt_problems("a man, no text", rules))
    assert not prompt_problems(f"{rules.prefix}, office, {rules.alone}, no text", rules)


def test_lora_strength_range() -> None:
    rules = load_directions().roman
    check_strength(0.9, rules)
    with pytest.raises(RomanError, match="outside"):
        check_strength(1.2, rules)


def test_approved_real_photos_rotate_and_ai_looking_ones_are_never_used(tmp_path: Path) -> None:
    rules = load_directions().roman
    _photos(tmp_path, ["1.jpg", "2.jpg", "4.jpg", "10.jpeg"])
    found = [path.name for path in approved_photos(rules, tmp_path)]
    assert found == ["2.jpg", "4.jpg"]  # 1.jpg is not approved, 10.jpeg looks AI-generated
    for seed in range(20):
        chosen = pick_real_photo(rules, tmp_path, seed=str(seed), previous="2.jpg")
        assert chosen is not None and chosen.name == "4.jpg"
    assert pick_real_photo(rules, tmp_path, seed="x", portrait=True) is None  # FD-2: the LoRA
    with pytest.raises(RomanError, match="none of the approved photos"):
        approved_photos(rules, tmp_path / "empty")


def test_text_side_follows_the_layout() -> None:
    catalog = load_directions()
    fd3 = catalog.get("FD-3")
    assert text_side(fd3.layouts["cover"]) in ("in the upper part of the frame",
                                               "on the left side of the frame",
                                               "in the lower part of the frame",
                                               "on the right side of the frame")


def test_identity_sheet_puts_the_image_beside_real_photos(tmp_path: Path) -> None:
    _photos(tmp_path / "set", ["2.jpg", "4.jpg"])
    generated = tmp_path / "raw.png"
    Image.new("RGB", (800, 1000), (10, 60, 140)).save(generated)
    sheet = identity_sheet(generated, [tmp_path / "set" / "2.jpg", tmp_path / "set" / "4.jpg"],
                           tmp_path / "job" / "identity_sheet_raw.png")
    with Image.open(sheet) as image:
        assert image.height > 900 and image.width > 3 * 600
