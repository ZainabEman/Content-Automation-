"""Phase D step 4: picking and rotating the design direction (offline, no provider called)."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from content_automation.content.deliverables import DeliverableError, load_deliverables
from content_automation.content.direction_pick import (
    direction_format,
    is_direction_id,
    pick_direction,
    recent_directions,
)
from content_automation.content.directions import DirectionError, load_directions
from content_automation.content.package import (
    ContentPackage,
    _choose_direction,
)
from content_automation.core.config import Settings


def test_formats_follow_the_part_and_the_roman_row() -> None:
    assert direction_format("post", "facebook") == "fb_single"
    assert direction_format("post", "linkedin") == "li_single"
    assert direction_format("carousel", "instagram") == "carousel"
    assert direction_format("post", "linkedin", roman=True) == "founder"
    assert direction_format("carousel", "instagram", roman=True) is None
    assert direction_format("ad", "facebook") is None
    assert is_direction_id("fd-2") and not is_direction_id("li_stat") and not is_direction_id(None)


def test_never_the_previous_direction_on_the_platform() -> None:
    catalog = load_directions()
    for seed in range(30):
        chosen, reason = pick_direction(catalog, "fb_single", "facebook", seed=str(seed),
                                        recent=["FB-2"], lora_ok=False)
        assert chosen.id in ("FB-1", "FB-3") and "FB-2" in reason


def test_carousels_skip_the_last_two() -> None:
    catalog = load_directions()
    picks = {pick_direction(catalog, "carousel", "instagram", seed=str(seed),
                            recent=["CS-3", "CS-1"], lora_ok=True)[0].id for seed in range(20)}
    assert picks == {"CS-2"}


def test_seeded_and_spread_without_history() -> None:
    catalog = load_directions()
    first = pick_direction(catalog, "li_single", "linkedin", seed="BG-7", recent=[], lora_ok=True)
    again = pick_direction(catalog, "li_single", "linkedin", seed="BG-7", recent=[], lora_ok=True)
    assert first[0].id == again[0].id and first[1] == "first of its format"
    spread = {pick_direction(catalog, "li_single", "linkedin", seed=str(seed), recent=[],
                             lora_ok=True)[0].id for seed in range(40)}
    assert spread == {"LI-1", "LI-2", "LI-3"}


def test_founder_without_the_lora_is_refused_never_a_real_photo() -> None:
    catalog = load_directions()
    with pytest.raises(DirectionError, match="every founder direction needs Roman's LoRA"):
        pick_direction(catalog, "founder", "linkedin", seed="x", recent=["FD-1"],
                       lora_ok=False)
    chosen, _ = pick_direction(catalog, "founder", "linkedin", seed="x", recent=["FD-1"],
                               lora_ok=True)
    assert chosen.id in ("FD-2", "FD-3")
    with pytest.raises(DirectionError, match="never swapped"):
        pick_direction(catalog, "founder", "facebook", seed="x", recent=[], lora_ok=False,
                       override="FD-2")


def test_override_must_fit_the_format_and_platform() -> None:
    catalog = load_directions()
    chosen, reason = pick_direction(catalog, "li_single", "linkedin", seed="x", recent=["LI-2"],
                                    lora_ok=True, override="li-2")
    assert chosen.id == "LI-2" and reason == "as asked"
    with pytest.raises(DirectionError, match="not fb_single on facebook"):
        pick_direction(catalog, "fb_single", "facebook", seed="x", recent=[], lora_ok=True,
                       override="LI-1")
    with pytest.raises(DirectionError, match="unknown design direction"):
        pick_direction(catalog, "fb_single", "facebook", seed="x", recent=[], lora_ok=True,
                       override="FB-9")


def _package(folder: Path, platform: str, direction: str, created: str) -> None:
    folder.mkdir(parents=True)
    (folder / "package.json").write_text(json.dumps(
        {"platform": platform, "direction": direction, "createdAt": created}), encoding="utf-8")


def test_history_is_per_format_and_platform_newest_first(tmp_path: Path) -> None:
    catalog = load_directions()
    _package(tmp_path / "a", "facebook", "FB-1", "2026-10-01T09:00:00Z")
    _package(tmp_path / "b", "facebook", "FB-3", "2026-10-03T09:00:00Z")
    _package(tmp_path / "c", "linkedin", "LI-2", "2026-10-04T09:00:00Z")
    _package(tmp_path / "d", "facebook", "FD-1", "2026-10-05T09:00:00Z")
    _package(tmp_path / "e", "facebook", "XX-1", "2026-10-06T09:00:00Z")
    assert recent_directions(tmp_path, catalog, "fb_single", "facebook") == ["FB-3", "FB-1"]
    assert recent_directions(tmp_path, catalog, "founder", "facebook") == ["FD-1"]
    assert recent_directions(tmp_path, catalog, "fb_single", "facebook",
                             exclude=tmp_path / "b") == ["FB-1"]


def test_package_gets_a_rotated_direction(make_settings: Callable[..., Settings],
                                          tmp_path: Path) -> None:
    settings = make_settings(IMAGE_PROVIDER="mock", PACKAGES_DIR=str(tmp_path / "content"))
    catalog = load_deliverables(settings.deliverables_file)
    _package(settings.packages_dir / "old", "facebook", "FB-1", "2026-10-01T09:00:00Z")
    folder = settings.packages_dir / "new"
    folder.mkdir()
    package = ContentPackage(package_id="new", topic="AI chatbots", platform="facebook", formats=[],
                             content_id="BG-12")
    items = [catalog.deliverables["facebook_post"]]
    chosen = _choose_direction(folder, package, items, settings, None)
    assert chosen is not None and chosen[0].id in ("FB-2", "FB-3")
    asked = _choose_direction(folder, package, items, settings, "FB-1")
    assert asked is not None and asked[0].id == "FB-1"
    with pytest.raises(DeliverableError, match="not fb_single on facebook"):
        _choose_direction(folder, package, items, settings, "CS-1")
    assert _choose_direction(folder, package, [catalog.deliverables["reel_short"]], settings,
                             None) is None
