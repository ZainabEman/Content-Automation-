"""Post format templates: provider per format, no text in prompts, panels beside the image
slot, theme rotation, Roman once a week, copy rules, the free format sheet. Offline."""

import json
from pathlib import Path

import pytest
from PIL import Image

from content_automation.ai.image import ImageRequest, available_providers, get_provider
from content_automation.content.calendar import assign_roman
from content_automation.content.deliverables import load_deliverables
from content_automation.content.formats import (
    ROMAN,
    FormatCatalog,
    FormatError,
    copy_problems,
    image_prompt,
    load_formats,
    pick_format,
)
from content_automation.core.config import Settings
from content_automation.workflows.design_system import load_design_system
from content_automation.workflows.format_sheet import format_sheet, render_tile
from content_automation.workflows.image_workflows import format_settings

ROOT = Path(__file__).resolve().parents[1]
CATALOG = load_formats(ROOT / "config" / "post_formats.json")


def _raw() -> dict[str, object]:
    data: dict[str, object] = json.loads(
        (ROOT / "config" / "post_formats.json").read_text(encoding="utf-8"))
    return data


def test_every_format_has_a_fixed_provider_and_roman_is_comfyui() -> None:
    for chosen in CATALOG.formats:
        assert chosen.provider == ("comfyui" if chosen.roman else "openrouter"), chosen.id
    roman = [item.id for item in CATALOG.formats if item.roman]
    assert roman == ["roman_quote", "roman_headshot_take", "roman_at_work", "roman_portrait_stat"]
    assert all(set(item.platforms) == {"linkedin", "facebook"} for item in CATALOG.formats
               if item.roman)


def test_text_zone_over_the_image_slot_is_refused_at_load() -> None:
    data = _raw()
    formats = data["formats"]
    assert isinstance(formats, list)
    tip = next(item for item in formats if item["id"] == "fb_tip")
    tip["zones"][0]["box"] = [0.08, 0.40, 0.92, 0.70]  # into the image (top 55%)
    with pytest.raises(ValueError, match="overlaps the image slot"):
        FormatCatalog.model_validate(data)


def test_overlapping_zones_are_refused_at_load() -> None:
    data = _raw()
    formats = data["formats"]
    assert isinstance(formats, list)
    stat = next(item for item in formats if item["id"] == "li_stat")
    stat["zones"][1]["box"] = [0.07, 0.40, 0.93, 0.74]
    with pytest.raises(ValueError, match="zones overlap"):
        FormatCatalog.model_validate(data)


def test_pick_never_repeats_the_previous_format_or_theme_and_no_roman_by_itself() -> None:
    for seed in range(40):
        for previous in ("li_split", "li_framework", "li_quote_card"):
            chosen = pick_format("linkedin", CATALOG, seed=str(seed), recent=[previous],
                                 has_number=True, person_ok=True)
            assert not chosen.roman
            assert chosen.id != previous
            assert chosen.theme != CATALOG.get(previous).theme


def test_the_roman_row_rotates_the_four_roman_formats() -> None:
    for seed in range(40):
        chosen = pick_format("facebook", CATALOG, seed=str(seed), recent=["fb_tip"],
                             has_number=True, person_ok=True, override=ROMAN,
                             last_roman="roman_quote")
        assert chosen.roman and chosen.id != "roman_quote" and chosen.theme != "light"
    with pytest.raises(FormatError, match="never swapped"):
        pick_format("linkedin", CATALOG, seed="1", recent=[], has_number=True,
                    person_ok=False, override=ROMAN)


def test_image_prompts_carry_no_copy_and_end_with_the_no_text_rule() -> None:
    roman = image_prompt(CATALOG.get("roman_at_work"), CATALOG, illustration=None, seed="a")
    assert roman.startswith("r0man_bg, a man, ")
    assert "no screens, no monitors, no signs, no whiteboards" in roman
    for prompt in (roman, image_prompt(CATALOG.get("fb_tip"), CATALOG,
                                       illustration="a cafe counter with a card reader")):
        assert prompt.endswith(f"{CATALOG.no_text}.")
        assert "logo" not in prompt.lower().replace(CATALOG.no_text.lower(), "")
    with pytest.raises(FormatError, match="mentions screen"):
        image_prompt(CATALOG.get("fb_tip"), CATALOG, illustration="a laptop screen")
    with pytest.raises(FormatError, match="repeats the copy"):
        image_prompt(CATALOG.get("fb_tip"), CATALOG, illustration="answer every missed call",
                     copy_texts=["Answer every missed call within five minutes"])


def test_copy_rules_word_limits_banned_words_and_icons() -> None:
    chosen = CATALOG.get("fb_tip")
    copy = {"headline": "How SME marketers can leverage automation for growth today now",
            "subline": "Send the link within 5 minutes.", "illustration": "a counter"}
    problems = " | ".join(copy_problems(chosen, copy, "post"))
    assert "at most 8 words" in problems and '"SME marketers" is banned' in problems
    assert '"leverage" is banned' in problems
    body = {"headline": "Reply in five minutes", "line": "Use WhatsApp.", "icon": "rocket"}
    assert any("one of check" in problem for problem in copy_problems(
        CATALOG.get("ig_steps"), body, "slide", slide_type="body"))


def test_provider_routing_and_the_free_template() -> None:
    assert "template" in available_providers()
    settings = Settings(image_provider="comfyui", image_model="z_image_turbo")
    routed = format_settings(CATALOG.get("fb_tip"), settings)
    assert routed.image_provider == "openrouter"
    assert routed.image_model == settings.carousel_image_model
    assert format_settings(CATALOG.get("roman_quote"), settings).image_provider == "comfyui"
    assert format_settings(CATALOG.get("li_stat"), settings).image_provider == "template"
    assert format_settings(CATALOG.get("ig_steps"), settings, "body").image_provider == "template"
    template = get_provider("template", settings)
    assert template.capabilities.est_cost_usd_per_image["1K"] == 0.0
    result = template.generate(ImageRequest(prompt="x", aspect_ratio="4:5"), "template")
    assert len(result.images) == 1


def test_roman_exactly_once_a_week_alternating_platforms() -> None:
    catalog = load_deliverables(ROOT / "config" / "deliverables.json")

    def week(label: str) -> list[dict[str, str]]:
        rows = []
        for number, (day, kind, platform) in enumerate(
                [("13", "linkedin_post", "linkedin"), ("14", "facebook_post", "facebook"),
                 ("15", "linkedin_post", "linkedin"), ("17", "instagram_carousel",
                                                       "instagram")], start=1):
            rows.append({"Row": str(number), "Planned date": f"2026-10-{day}",
                         "Platform": platform, "Content type": kind, "Status": "Proposed",
                         "Package": "", "Format": ""})
        assign_roman(rows, label, catalog)
        return rows

    platforms = []
    for label in ("2026-W43", "2026-W44"):
        rows = week(label)
        marked = [row for row in rows if row["Format"] == ROMAN]
        assert len(marked) == 1 and marked[0]["Platform"] != "instagram"
        platforms.append(marked[0]["Platform"])
        assert assign_roman(rows, label, catalog) is None  # never a second one
    assert platforms[0] != platforms[1]


def test_template_keeps_text_off_the_picture() -> None:
    system = load_design_system(ROOT / "config" / "design_system.json")
    chosen = CATALOG.get("fb_tip")
    tile = render_tile(chosen, CATALOG, system, None, 1, None)
    assert tile.size == (1080, 1350)
    panel = (0xF2, 0xF2, 0xF2)
    assert tile.getpixel((5, 5)) != panel and tile.getpixel((1075, 700)) != panel  # the picture
    assert tile.getpixel((5, 1340)) == panel and tile.getpixel((1075, 760)) == panel  # solid


def test_format_sheet_renders_every_format(tmp_path: Path) -> None:
    settings = Settings(post_formats_file=ROOT / "config" / "post_formats.json",
                        design_system_file=ROOT / "config" / "design_system.json",
                        references_dir=tmp_path / "refs")
    path, count = format_sheet(settings, tmp_path / "sheet.png")
    assert count == 11 + 3 * 4
    with Image.open(path) as image:
        assert image.width > 1000
