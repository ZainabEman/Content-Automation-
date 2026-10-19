"""PRD v5 R10-R11 (code only, mock): new Drive folders, category routing, nested YouTube
folders, the new tracker columns at the end; nothing renamed, nothing at Google."""

from pathlib import Path
from typing import Any

from content_automation.content.package import ContentPackage
from content_automation.content.tracking import (
    DEFAULT_REGISTRY_COLUMNS,
    REGISTRY_KEYS,
    load_registry_columns,
    plan_upsert,
)
from content_automation.storage import (
    FOLDERS,
    Uploaded,
    package_folder_key,
    platform_folder,
)
from content_automation.storage.providers.drive_api import DriveState, DriveStorage

REPO = Path(__file__).resolve().parents[1]
OLD_FOLDERS = ("LinkedIn", "Facebook", "Instagram", "YouTube", "Calendar", "Facebook Ads")


def test_new_folders_are_added_and_old_ones_stay() -> None:
    assert set(OLD_FOLDERS) <= set(FOLDERS)  # nothing renamed (R10.3)
    assert {"Instagram Carousels", "Facebook Posts", "Facebook Ads", "LinkedIn",
            "YouTube"} <= set(FOLDERS)


def test_v5_packages_go_to_their_category_folder() -> None:
    def package(category: str | None, platform: str) -> ContentPackage:
        return ContentPackage(package_id="p", topic="t", platform=platform, formats=[],
                              category=category)

    assert platform_folder(package_folder_key(package("instagram_carousel", "instagram"))) == (
        "Instagram Carousels")
    assert platform_folder(package_folder_key(package("facebook_post", "facebook"))) == (
        "Facebook Posts")
    assert platform_folder(package_folder_key(package("facebook_ad", "facebook"))) == (
        "Facebook Ads")  # separate from Facebook posts (§7.5)
    assert platform_folder(package_folder_key(package("linkedin_post", "linkedin"))) == (
        "LinkedIn")
    assert platform_folder(package_folder_key(package(None, "facebook"))) == "Facebook"  # old


def test_drive_upload_makes_nested_youtube_folders(monkeypatch: Any) -> None:
    storage = DriveStorage.__new__(DriveStorage)
    storage._state = DriveState(root_id="root", folders={"YouTube": "yt"})
    made: list[tuple[str, str]] = []

    def folder(known: str, name: str, parent: str | None) -> str:
        made.append((name, str(parent)))
        return known or f"{parent}>{name}"

    monkeypatch.setattr(storage, "_folder", folder)
    monkeypatch.setattr(storage, "_save_state", lambda: None)
    monkeypatch.setattr(storage, "_find", lambda *_args, **_kw: None)
    monkeypatch.setattr(storage, "_put", lambda file, parent, known: Uploaded(
        file_id="f", link=f"https://drive/{parent}/{file.name}"))
    done = storage.upload(Path("teleprompter_DE.txt"), "youtube", "2026-11/BG-1_thema",
                          "style-A_investigativ")
    assert made == [("2026-11", "yt"), ("BG-1_thema", "yt>2026-11"),
                    ("style-A_investigativ", "yt>2026-11>BG-1_thema")]
    assert done.link.endswith("yt>2026-11>BG-1_thema>style-A_investigativ/teleprompter_DE.txt")
    assert "YouTube/2026-11/BG-1_thema" in storage._state.content_folders


def test_new_tracker_columns_go_at_the_end_and_never_touch_manager_fields() -> None:
    names = load_registry_columns(REPO / "config" / "tracker.json")
    new = [names[key] for key in ("category", "language", "layout_variant", "requires_roman",
                                  "script_style")]
    assert new == ["Category", "Language", "Layout Variant", "Requires Roman",
                   "Selected Script Style"]
    assert list(DEFAULT_REGISTRY_COLUMNS) == list(REGISTRY_KEYS)
    header = ["Content ID", "Topic", "Research source", "Platform", "Content type", "Caption",
              "Hashtags", "Image/video link", "Approval status", "Publishing status",
              "Publication date", "Manager note"]
    row = ["BG-7", "t", "s", "LinkedIn", "linkedin_post", "c", "#a", "l", "Approved", "Posted",
           "2026-11-02", "keep me"]
    entry = {"Content ID": "BG-7", "Topic": "t", "Research source": "s", "Platform": "LinkedIn",
             "Content type": "linkedin_post", "Caption": "c", "Hashtags": "#a",
             "Image/video link": "l", "Category": "LinkedIn", "Language": "de",
             "Layout Variant": "LI-2", "Requires Roman": "no", "Selected Script Style": "—"}
    plan = plan_upsert([header, row], [entry], {}, tuple(new))
    added = [cell for cell in plan.cells if cell.row == 0]
    assert [cell.value for cell in added] == new
    assert [cell.column for cell in added] == list(range(len(header), len(header) + 5))
    manager = {header.index(name) for name in ("Approval status", "Publishing status",
                                               "Publication date", "Manager note")}
    assert not [cell for cell in plan.cells if cell.row == 1 and cell.column in manager]
    assert {cell.value for cell in plan.cells if cell.row == 1} >= {"LI-2", "de", "LinkedIn"}
