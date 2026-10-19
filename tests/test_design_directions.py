"""config/design_directions.json (v5 layout variants): the rules that keep every design on brand."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from content_automation.content.directions import (
    CATEGORY,
    DirectionError,
    load_directions,
)

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config" / "design_directions.json"


def _data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CONFIG.read_text(encoding="utf-8"))
    return data


def _load(tmp_path: Path, data: dict[str, Any]) -> None:
    path = tmp_path / "design_directions.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    load_directions(path)


def _direction(data: dict[str, Any], direction_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(d for d in data["directions"] if d["id"] == direction_id)
    return found


def test_three_to_five_variants_per_category() -> None:
    catalog = load_directions(CONFIG)
    for format_name, category in CATEGORY.items():
        variants = catalog.for_format(format_name)
        assert 3 <= len(variants) <= 5, category
        assert all(v.category == category for v in variants)
    assert catalog.size(catalog.get("li-2")) == (1080, 1440)  # 3:4 (designer's prompt)
    assert catalog.size(catalog.get("CS-1")) == (1080, 1080)  # 1:1 (company carousels)
    assert catalog.size(catalog.get("FA-1")) == catalog.size(catalog.get("FB-1")) == (1080, 1350)
    for direction in catalog.for_format("carousel"):
        assert not direction.roman
        assert direction.slide_count == (5, 6)
        assert direction.slide_roles[0].role == "cover"
        assert direction.slide_roles[-1].role == "cta"
    founders = [d for d in catalog.directions if d.roman]
    assert {d.format for d in founders} == {"fb_single", "fb_ad", "li_single"}  # R4.1
    assert all("-R" in d.id and d.provider == "higgsfield_soul" and d.pick == "side"
               for d in founders)  # 2026-10-20: Roman via Higgsfield, mirrored layouts


def test_every_variant_names_a_treatment_and_approved_references() -> None:
    catalog = load_directions(CONFIG)
    refs = json.loads((REPO / "config" / "brand_refs.json").read_text(encoding="utf-8"))["refs"]
    for direction in catalog.directions:
        assert direction.treatment
        assert direction.reference_ids and set(direction.reference_ids) <= set(refs)
    pairs = [(d.format, d.treatment) for d in catalog.directions]
    assert len(pairs) == len(set(pairs))  # one treatment per variant within a category


def test_unknown_direction_is_named() -> None:
    with pytest.raises(DirectionError, match="FB-1, FB-2"):
        load_directions(CONFIG).get("XX-9")


@pytest.mark.parametrize(("change", "message"), [
    (lambda d: _direction(d, "CS-1")["visual"].update(subject="roman_lora"),
     "carousels never show Roman"),
    (lambda d: _direction(d, "FB-1")["layouts"]["post"]["zones"]["headline"].update(
        color="navy"), "headline.color"),
    (lambda d: _direction(d, "FB-1")["layouts"]["post"]["zones"]["sub"].update(
        box=[0.01, 0.55, 0.56, 0.74]), "margin"),
    (lambda d: _direction(d, "FB-1")["layouts"]["post"]["zones"]["sub"].update(
        box=[0.09, 0.4, 0.56, 0.74]), "overlap"),
    (lambda d: _direction(d, "FB-1")["layouts"]["post"]["zones"].pop("scrim"),
     "without a panel or scrim"),
    (lambda d: _direction(d, "FB-3")["layouts"]["post"]["textLimits"].pop("features"),
     "no textLimits"),
    (lambda d: _direction(d, "FB-1").update(platforms=["instagram"]), "facebook only"),
    (lambda d: _direction(d, "FB-2")["layouts"]["post"]["zones"].pop("logo"),
     "official logo"),
    (lambda d: _direction(d, "FB-1")["visual"].update(prompt="{illustration}, blue"),
     "no text"),
    (lambda d: _direction(d, "CS-3").update(slideCount=[5, 7], slideRoles=[
        {"role": "cover", "layout": "cover"}, {"role": "point", "layout": "point",
                                               "repeat": [3, 5]},
        {"role": "cta", "layout": "cta"}]), "5-6 slides"),
    (lambda d: _direction(d, "LI-1").update(canvas="4:5"), "linkedin_post is 3:4"),
    (lambda d: _direction(d, "CS-2")["layouts"]["point"]["zones"].update(
        logo={"kind": "logo", "box": [0.7, 0.06, 0.94, 0.16]}), "only on its last slide"),
    (lambda d: _direction(d, "LI-2")["layouts"]["post"]["zones"]["logo"].update(
        box=[0.38, 0.44, 0.62, 0.52]), "side corner"),
    (lambda d: _direction(d, "LI-1").update(id="LI-9", visual=_direction(d, "LI-R1")["visual"],
                                            provider="comfyui"), "id with R"),
    (lambda d: (_direction(d, "CS-2")["layouts"]["point"]["zones"]["number"].update(
        field="counter"), _direction(d, "CS-2")["layouts"]["point"]["fields"].update(
        counter="01/05"), _direction(d, "CS-2")["layouts"]["point"]["fields"].pop("number"),
        _direction(d, "CS-2")["layouts"]["point"]["textLimits"].update(
            counter=_direction(d, "CS-2")["layouts"]["point"]["textLimits"]["number"])),
     "counters"),
])
def test_rules_are_enforced(tmp_path: Path, change: Any, message: str) -> None:
    data = copy.deepcopy(_data())
    change(data)
    with pytest.raises(DirectionError, match=message):
        _load(tmp_path, data)


def test_no_competitor_reference_is_active() -> None:
    """R2.2: the Phase D ids (R01-R36, C1-C7) live only in the archive."""
    active = CONFIG.read_text(encoding="utf-8")
    archived = json.loads((REPO / "config" / "_archive" / "social_refs_competitor.json")
                          .read_text(encoding="utf-8"))["refs"]
    assert len(archived) == 43
    used = {ref for d in load_directions(CONFIG).directions for ref in d.reference_ids}
    assert not used & set(archived)
    assert "R17" not in active and '"C1"' not in active
