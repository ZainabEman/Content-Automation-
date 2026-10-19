"""Picking and rotating the layout variant (Phase D step 4, v5 R5; offline, no provider)."""

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


def test_categories_follow_the_part() -> None:
    assert direction_format("post", "facebook") == "fb_single"
    assert direction_format("ad", "facebook") == "fb_ad"
    assert direction_format("post", "linkedin") == "li_single"
    assert direction_format("carousel", "instagram") == "carousel"
    assert direction_format("post", "linkedin", roman=True) == "li_single"  # R4.1: no 5th
    assert direction_format("carousel", "instagram", roman=True) is None
    assert direction_format("video", "instagram") is None
    assert is_direction_id("fa-r1") and is_direction_id("CS-2")
    assert not is_direction_id("fd-2") and not is_direction_id("li_stat")
    assert not is_direction_id(None)


def test_never_the_previous_variant_on_the_platform() -> None:
    catalog = load_directions()
    for seed in range(30):
        chosen, reason = pick_direction(catalog, "fb_single", "facebook", seed=str(seed),
                                        recent=["FB-2"], roman_ok=False)
        assert chosen.id in ("FB-1", "FB-3", "FB-4") and "FB-2" in reason


def test_carousels_skip_the_last_two() -> None:
    catalog = load_directions()
    picks = {pick_direction(catalog, "carousel", "instagram", seed=str(seed),
                            recent=["CS-3", "CS-1"], roman_ok=True)[0].id for seed in range(30)}
    assert picks == {"CS-2", "CS-4"}


def test_seeded_and_spread_without_history() -> None:
    catalog = load_directions()
    first = pick_direction(catalog, "li_single", "linkedin", seed="BG-7", recent=[], roman_ok=True)
    again = pick_direction(catalog, "li_single", "linkedin", seed="BG-7", recent=[], roman_ok=True)
    assert first[0].id == again[0].id and first[1] == "first of its category"
    spread = {pick_direction(catalog, "li_single", "linkedin", seed=str(seed), recent=[],
                             roman_ok=True)[0].id for seed in range(60)}
    assert spread == {"LI-1", "LI-2", "LI-3", "LI-4"}  # Roman only when required


def test_requires_roman_picks_the_founder_variant_never_a_photo() -> None:
    catalog = load_directions()
    with pytest.raises(DirectionError, match="every founder li_single variant needs"):
        pick_direction(catalog, "li_single", "linkedin", seed="x", recent=[], roman_ok=False,
                       roman=True)
    for format_name, platform, wanted in (("li_single", "linkedin", "LI-R1"),
                                          ("fb_single", "facebook", "FB-R1"),
                                          ("fb_ad", "facebook", "FA-R1")):
        chosen, _ = pick_direction(catalog, format_name, platform, seed="x", recent=[],
                                   roman_ok=True, roman=True)
        assert chosen.id == wanted and chosen.provider == "higgsfield_soul"
    with pytest.raises(DirectionError, match="never swapped"):
        pick_direction(catalog, "fb_single", "facebook", seed="x", recent=[], roman_ok=False,
                       override="FB-R1")


def test_no_third_treatment_in_a_row() -> None:
    """R5.3: rotation keys on variant + background treatment."""
    catalog = load_directions()
    # the last two LinkedIn posts both used the dark_panel treatment (LI-2): never a third
    for seed in range(40):
        chosen, reason = pick_direction(catalog, "li_single", "linkedin", seed=str(seed),
                                        recent=["LI-2", "LI-2"], roman_ok=True)
        assert chosen.treatment != "dark_panel" and chosen.id != "LI-2"


def test_override_must_fit_the_category_and_platform() -> None:
    catalog = load_directions()
    chosen, reason = pick_direction(catalog, "li_single", "linkedin", seed="x", recent=["LI-2"],
                                    roman_ok=True, override="li-2")
    assert chosen.id == "LI-2" and reason == "as asked"
    with pytest.raises(DirectionError, match="not fb_single on facebook"):
        pick_direction(catalog, "fb_single", "facebook", seed="x", recent=[], roman_ok=True,
                       override="FA-1")
    with pytest.raises(DirectionError, match="unknown design direction"):
        pick_direction(catalog, "fb_single", "facebook", seed="x", recent=[], roman_ok=True,
                       override="FB-9")


def _package(folder: Path, platform: str, direction: str, created: str) -> None:
    folder.mkdir(parents=True)
    (folder / "package.json").write_text(json.dumps(
        {"platform": platform, "direction": direction, "createdAt": created}), encoding="utf-8")


def test_history_is_per_category_and_platform_newest_first(tmp_path: Path) -> None:
    catalog = load_directions()
    _package(tmp_path / "a", "facebook", "FB-1", "2026-10-01T09:00:00Z")
    _package(tmp_path / "b", "facebook", "FB-3", "2026-10-03T09:00:00Z")
    _package(tmp_path / "c", "linkedin", "LI-2", "2026-10-04T09:00:00Z")
    _package(tmp_path / "d", "facebook", "FA-1", "2026-10-05T09:00:00Z")
    _package(tmp_path / "e", "facebook", "FD-1", "2026-10-06T09:00:00Z")  # archived id
    assert recent_directions(tmp_path, catalog, "fb_single", "facebook") == ["FB-3", "FB-1"]
    assert recent_directions(tmp_path, catalog, "fb_ad", "facebook") == ["FA-1"]
    assert recent_directions(tmp_path, catalog, "fb_single", "facebook",
                             exclude=tmp_path / "b") == ["FB-1"]


def test_package_gets_a_rotated_variant(make_settings: Callable[..., Settings],
                                        tmp_path: Path) -> None:
    settings = make_settings(IMAGE_PROVIDER="mock", PACKAGES_DIR=str(tmp_path / "content"))
    catalog = load_deliverables(settings.deliverables_file)
    _package(settings.packages_dir / "old", "facebook", "FB-1", "2026-10-01T09:00:00Z")
    folder = settings.packages_dir / "new"
    folder.mkdir()
    package = ContentPackage(package_id="new", topic="KI-Chatbots", platform="facebook",
                             formats=[], content_id="BG-12")
    items = [catalog.deliverables["facebook_post"]]
    chosen = _choose_direction(folder, package, items, settings, None)
    assert chosen is not None and chosen[0].id in ("FB-2", "FB-3", "FB-4")
    asked = _choose_direction(folder, package, items, settings, "FB-1")
    assert asked is not None and asked[0].id == "FB-1"
    roman = _choose_direction(folder, package, items, settings, "roman")
    assert roman is not None and roman[0].id == "FB-R1"
    ad = _choose_direction(folder, package, [catalog.deliverables["facebook_ad"]], settings, None)
    assert ad is not None and ad[0].format == "fb_ad"
    with pytest.raises(DeliverableError, match="not fb_single on facebook"):
        _choose_direction(folder, package, items, settings, "CS-1")
    assert _choose_direction(folder, package, [catalog.deliverables["reel_short"]], settings,
                             None) is None
