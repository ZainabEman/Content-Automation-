"""config/design_directions.json: the schema rules that keep every design on brand."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from content_automation.content.directions import (
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


def test_the_twelve_directions_load() -> None:
    catalog = load_directions(CONFIG)
    assert [d.id for d in catalog.directions] == [
        "FB-1", "FB-2", "FB-3", "LI-1", "LI-2", "LI-3", "CS-1", "CS-2", "CS-3",
        "FD-1", "FD-2", "FD-3"]
    assert catalog.size(catalog.get("li-2")) == (1080, 1350)
    assert {d.format for d in catalog.directions} == {"fb_single", "li_single", "carousel",
                                                      "founder"}
    for direction in catalog.for_format("carousel"):
        assert not direction.roman
        assert direction.slide_roles[0].role == "cover"
        assert direction.slide_roles[-1].role == "cta"
    assert all(d.roman for d in catalog.for_format("founder"))


def test_layout_variants_by_platform_and_rotation() -> None:
    catalog = load_directions(CONFIG)
    fd3 = catalog.get("FD-3")
    assert fd3.layout_for("facebook")[0] == "cover"
    assert fd3.layout_for("linkedin")[0] == "editorial"
    fb3 = catalog.get("FB-3")
    assert {fb3.layout_for("facebook", seed=f"s{n}")[0] for n in range(20)} == {"zigzag", "cycle"}
    cs1 = catalog.get("CS-1")
    assert cs1.layout_for(role="benefits")[0] == "benefits"
    with pytest.raises(DirectionError, match="no slide role"):
        cs1.layout_for(role="intro")


def test_unknown_direction_is_named() -> None:
    with pytest.raises(DirectionError, match="FB-1, FB-2"):
        load_directions(CONFIG).get("XX-9")


@pytest.mark.parametrize(("change", "message"), [
    (lambda d: _direction(d, "CS-1")["visual"].update(subject="roman_lora"),
     "carousels never show Roman"),
    (lambda d: _direction(d, "FB-1")["layouts"]["post"]["zones"]["headline"].update(
        color="navy"), "headline.color"),
    (lambda d: _direction(d, "FB-1")["layouts"]["post"]["zones"]["sub"].update(
        box=[0.01, 0.305, 0.94, 0.37]), "margin"),
    (lambda d: _direction(d, "FB-1")["layouts"]["post"]["zones"]["sub"].update(
        box=[0.06, 0.25, 0.94, 0.37]), "overlap"),
    (lambda d: _direction(d, "LI-2")["layouts"]["post"]["zones"].pop("card"),
     "without a panel or scrim"),
    (lambda d: _direction(d, "FB-2")["layouts"]["post"]["textLimits"].pop("problem"),
     "no textLimits"),
    (lambda d: _direction(d, "FD-1").update(platforms=["instagram"]),
     "LinkedIn and Facebook"),
    (lambda d: _direction(d, "FB-3")["layouts"]["zigzag"]["zones"].pop("logo"),
     "official logo"),
    (lambda d: _direction(d, "LI-3")["layouts"]["post"]["zones"]["visual"].update(
        box=[0.31, 0.37, 0.69, 0.6]), "square"),
    (lambda d: _direction(d, "FB-1")["visual"].update(prompt="{illustration}, blue"),
     "no text"),
    (lambda d: _direction(d, "CS-3").update(slideCount=[4, 9]), "slideCount"),
])
def test_rules_are_enforced(tmp_path: Path, change: Any, message: str) -> None:
    data = copy.deepcopy(_data())
    change(data)
    with pytest.raises(DirectionError, match=message):
        _load(tmp_path, data)


def test_reference_ids_exist_in_the_reference_map() -> None:
    refs = json.loads((REPO / "config" / "social_refs.json").read_text(encoding="utf-8"))["refs"]
    used = {ref for d in load_directions(CONFIG).directions for ref in d.reference_ids}
    assert used <= set(refs)
    assert len(refs) == 43 and refs["R17"]["use"].count("watermark") == 1
