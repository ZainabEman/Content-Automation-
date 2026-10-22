"""PRD v6 weekly (docs/PRD-v6-weekly-youtube-drive.md §8): the weekly set, the short/long
YouTube layouts and the "<English Topic Title> <YYYY-MM-DD>" folder names with their rename."""

import json
from collections import Counter
from datetime import date
from pathlib import Path

from content_automation.content.calendar import ROMAN, assign_roman, load_cadence
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
    slots = load_cadence(REPO / "config" / "calendar.json", catalog).slots
    week = Counter(slot.deliverable for slot in slots)
    assert len(slots) == weekly.image_posts == 14 and week["instagram_carousel"] == 2
    rows = [{"Row": str(n), "Planned date": f"2026-11-{n + 1:02d}", "Package": "", "Format": "",
             "Status": "Proposed", "Content type": slot.deliverable,
             "Platform": catalog.deliverables[slot.deliverable].platform or ""}
            for n, slot in enumerate(slots, start=1)]
    assign_roman(rows, "2026-W45", catalog)
    assert sum(row["Format"] == ROMAN for row in rows) >= weekly.roman_min == 2
    assert weekly.youtube == {"youtube_longform": 2, "youtube_shortform": 4}
    assert catalog.monthly_plan is not None
    counts = month_counts(catalog.monthly_plan, weekly)
    assert sum(counts.values()) == 56 and counts["instagram_carousel"] == 8
    eligible = sum(counts[key] for key in catalog.monthly_plan.roman_deliverables)
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
