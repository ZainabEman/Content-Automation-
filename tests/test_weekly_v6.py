"""PRD v6 weekly (docs/PRD-v6-weekly-youtube-drive.md §8): the weekly set, the short/long
YouTube layouts and the "<English Topic Title> <YYYY-MM-DD>" folder names with their rename."""

import json
from collections import Counter
from datetime import date
from pathlib import Path

from content_automation.content.calendar import ROMAN, assign_roman, week_slots
from content_automation.content.deliverables import load_deliverables
from content_automation.content.folder_rename import plan_lines, plan_renames, titles_path
from content_automation.content.month_plan import month_counts, roman_step
from content_automation.content.package import ContentPackage
from content_automation.core.config import load_settings
from content_automation.core.output_tree import folder_date, item_folder_name, unique_name
from content_automation.youtube.topic import style_dir, topic_folder
from content_automation.youtube.upload import topic_files

REPO = Path(__file__).resolve().parents[1]


def test_weekly_set_and_month_counts() -> None:
    catalog = load_deliverables(REPO / "config" / "deliverables.json")
    weekly = catalog.weekly_set
    split = Counter()
    for week, label in enumerate(("2026-W45", "2026-W46", "2026-W47", "2026-W48")):
        slots = week_slots(REPO / "config" / "calendar.json", catalog, label)
        counts = Counter(slot.deliverable for slot in slots)
        assert len(slots) == 14 and counts["instagram_carousel"] == 2
        days = [{slot.deliverable for slot in slots if slot.weekday == day}
                for day in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")]
        assert all(len(day) == 2 for day in days)  # two a day, never one category twice
        assert not any(name in a and name in b and name in c for name in counts
                       for a, b, c in zip(days, days[1:], days[2:], strict=False))
        rows = [{"Row": str(n), "Planned date": f"2026-11-{n:02d}", "Package": "",
                 "Format": "", "Status": "Proposed", "Content type": slot.deliverable,
                 "Platform": catalog.deliverables[slot.deliverable].platform or ""}
                for n, slot in enumerate(slots, start=1)]
        assign_roman(rows, label, catalog)
        roman = [row for row in rows if row["Format"] == ROMAN]
        assert {row["Content type"] for row in roman} == {"linkedin_post", "facebook_post"}
        week_split = weekly.split_counts(45 + week)
        assert sorted(week_split.values()) == [3, 3, 4]  # 10 split fairly, 4/3/3
        split.update(week_split)
    assert sorted(split.values()) == [13, 13, 14]  # the 4 rotates: a month is 14/13/13
    assert weekly.youtube == {"youtube_longform": 2, "youtube_shortform": 4}
    assert catalog.monthly_plan is not None
    counts = month_counts(catalog.monthly_plan, weekly, 45)
    assert sum(counts.values()) == 56 and counts["instagram_carousel"] == 8
    assert counts["linkedin_post"] + counts["facebook_post"] == 27 + 8  # split + 8 Roman
    eligible = sum(counts[key] for key in weekly.roman_deliverables)
    assert eligible // roman_step(catalog.monthly_plan, weekly, counts) >= 8


def test_short_and_long_folder_layout(tmp_path: Path) -> None:
    root = tmp_path / "outputs" / "YouTube Long-Form"
    short = topic_folder("2026-11", "BG-901", "KI-Betrug am Telefon", root, fmt="short",
                         title_en="AI Phone Fraud", planned=date(2026, 11, 4))
    long = topic_folder("2026-11", "BG-902", "KI-Woche", root, title_en="AI Week in Germany",
                        planned=date(2026, 11, 5))
    assert short == tmp_path / "outputs" / "YouTube Short-Form" / "AI Phone Fraud 2026-11-04"
    assert long == root / "AI Week in Germany 2026-11-05"
    assert style_dir(short, "S", "short") == short  # one style, no subfolder
    assert [style_dir(long, key).name for key in "ABC"] == ["Style A", "Style B", "Style C"]
    for folder, subs in ((short, [""]), (long, ["Style A", "Style B", "Style C"])):
        for sub in subs:
            for name in ("teleprompter-de.txt", "script-en-de.md", "storyboard.md"):
                (folder / sub / name).parent.mkdir(parents=True, exist_ok=True)
                (folder / sub / name).write_text("x", encoding="utf-8")
        (folder / "research.txt").write_text("x", encoding="utf-8")  # local only
    assert [(path.name, sub) for path, sub, _ in topic_files(short, "short")] == [
        ("teleprompter-de.txt", None), ("script-en-de.md", None), ("storyboard.md", None)]
    found = topic_files(long, "long")
    assert len(found) == 9 and {sub for _, sub, _ in found} == {"Style A", "Style B", "Style C"}


def test_folder_names_and_rename_dry_run(isolated: Path) -> None:
    assert item_folder_name("AI: Voice Fraud?", date(2026, 11, 3)) == "AI Voice Fraud 2026-11-03"
    assert unique_name("AI Voice Fraud 2026-11-03", {"ai voice fraud 2026-11-03"}) == (
        "AI Voice Fraud 2026-11-03 (2)")
    assert folder_date("AI Voice Fraud 2026-11-03 (2)") == date(2026, 11, 3)
    assert folder_date("2026-11-03_BG-120_ki") == date(2026, 11, 3)
    settings = load_settings(env_file=None)
    old = settings.packages_dir / "Instagram" / "Carousels" / "2026-11" / "2026-11-03_BG-120_ki"
    old.mkdir(parents=True)
    package = ContentPackage.model_validate({
        "packageId": old.name, "topic": "KI-Stimmenbetrug", "platform": "instagram",
        "formats": [], "category": "instagram_carousel", "plannedDate": "2026-11-03",
        "treePath": f"Instagram/Carousels/2026-11/{old.name}"})
    (old / "package.json").write_text(package.model_dump_json(by_alias=True), encoding="utf-8")
    plan = plan_renames(settings)
    assert plan.missing == {"BG-120": {"topic": "KI-Stimmenbetrug",
                                       "folder": f"Instagram/Carousels/2026-11/{old.name}"}}
    titles_path(settings).parent.mkdir(parents=True, exist_ok=True)
    titles_path(settings).write_text(json.dumps({"BG-120": {"titleEn": "AI Voice Fraud"}}),
                                     encoding="utf-8")
    plan = plan_renames(settings)
    assert [(r.where, r.ref, r.new) for r in plan.renames] == [
        ("local", "BG-120", "AI Voice Fraud 2026-11-03")]
    lines = plan_lines(plan, settings)
    assert lines[0].startswith("Rename plan (dry run, nothing changed): 1 folder(s)")
    assert '"2026-11-03_BG-120_ki" → "AI Voice Fraud 2026-11-03"' in lines[1]
    assert old.is_dir()  # the dry run changes nothing
