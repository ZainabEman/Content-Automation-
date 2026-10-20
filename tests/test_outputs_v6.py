"""PRD v6 R8 (T6): the platform-sorted output tree, the legacy migration and the Drive mirror."""

from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_automation.cli import app
from content_automation.content.outputs_migrate import plan_migration
from content_automation.content.package import ContentPackage
from content_automation.core.config import load_settings
from content_automation.core.output_tree import (
    iter_package_files,
    package_dir,
    short_slug,
)
from content_automation.storage import drive_folder_name, package_folder_key, upload_names


def test_package_dir_follows_the_tree() -> None:
    root = Path("outputs")
    path = package_dir(root, "instagram_carousel", date(2026, 11, 3), "BG-120",
                       "Deepfake-Anrufe: Wenn die Stimme des Chefs gefälscht ist")
    assert path.as_posix() == ("outputs/Instagram/Carousels/2026-11/2026-11-03_BG-120_"
                               "deepfake-anrufe-wenn-die-stimme-des-chef")  # 40 chars
    assert short_slug("Größe & Übermut!") == "groesse-uebermut"
    for category, start in (("facebook_post", "Facebook/Posts"), ("facebook_ad", "Facebook/Ads"),
                            ("linkedin_post", "LinkedIn/Posts")):
        assert package_dir(root, category, date(2026, 11, 3), "BG-1", "x").as_posix().startswith(
            f"outputs/{start}/2026-11/")


def _legacy_outputs(root: Path) -> None:
    for relative in ("content/2026-10-16_topic/package.json", "content/2026-10-16_topic/images/"
                     "post-1.png", "jobs/2026-10-20/0301_x/image-1.png", "design/preview/a.png",
                     "content-tracker.csv"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}" if path.suffix == ".json" else "x", encoding="utf-8")
    (root / "_system" / "previews").mkdir(parents=True)
    (root / "Instagram").mkdir()


def test_migration_is_a_dry_run_by_default_and_never_overwrites(isolated: Path) -> None:
    """§5 check 8 (second half): the dry run lists the moves; --apply moves unchanged into
    _system/rejected_legacy/ keeping relative paths; the new tree is never touched."""
    root = isolated / "outputs"
    _legacy_outputs(root)
    plan = plan_migration(root)
    assert [move.source.name for move in plan.moves] == ["content", "content-tracker.csv",
                                                         "design", "jobs"]
    dry = CliRunner().invoke(app, ["outputs", "migrate"])
    assert dry.exit_code == 0 and dry.output.startswith("DRY RUN (nothing moved")
    assert "content/ -> _system/rejected_legacy/content/ (2 file(s))" in dry.output
    assert (root / "content" / "2026-10-16_topic" / "package.json").is_file()  # nothing moved
    done = CliRunner().invoke(app, ["outputs", "migrate", "--apply"])
    assert done.exit_code == 0, done.output
    legacy = root / "_system" / "rejected_legacy"
    assert (legacy / "content" / "2026-10-16_topic" / "images" / "post-1.png").is_file()
    assert (legacy / "jobs" / "2026-10-20" / "0301_x" / "image-1.png").is_file()
    assert not (root / "content").exists() and (root / "Instagram").is_dir()
    assert (root / "_system" / "previews").is_dir()
    # legacy packages stay known to the duplicate check
    assert any("rejected_legacy" in path.as_posix() for path in iter_package_files(root))
    (root / "content").mkdir()  # a second run: an existing target is skipped, never overwritten
    again = plan_migration(root)
    assert not again.moves and any("exists" in line for line in again.skipped)


def test_old_env_paths_run_with_the_new_tree(isolated: Path,
                                             monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTPUT_DIR", "outputs/jobs")
    monkeypatch.setenv("PACKAGES_DIR", "outputs/content")
    settings = load_settings(env_file=None, require_credentials=False)
    assert settings.output_dir.as_posix() == "outputs/_system/jobs"
    assert settings.packages_dir.as_posix() == "outputs"
    assert len(settings.legacy_paths) == 2
    monkeypatch.setenv("PACKAGES_DIR", "somewhere/else")
    assert load_settings(env_file=None, require_credentials=False).packages_dir.as_posix() == (
        "somewhere/else")  # any other path is used as given


def test_drive_mirrors_the_local_tree(tmp_path: Path) -> None:
    folder = tmp_path / "Instagram" / "Carousels" / "2026-11" / "2026-11-03_BG-120_ki"
    for name in ("final/slide_01.png", "final/slide_02.png", "source/slide_01.png",
                 "caption_de.txt"):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text("x", encoding="utf-8")
    package = ContentPackage.model_validate({
        "packageId": folder.name, "topic": "KI", "platform": "instagram", "formats": [],
        "category": "instagram_carousel", "treePath": "Instagram/Carousels/2026-11/" + folder.name,
        "items": {"carousel": {"status": "done",
                               "files": ["final/slide_01.png", "final/slide_02.png"]}}})
    assert package_folder_key(package) == "instagram"
    assert drive_folder_name(folder, package) == f"Carousels/2026-11/{folder.name}"
    assert upload_names(folder, package) == {
        "final/slide_01.png": "final", "final/slide_02.png": "final",
        "caption_de.txt": None, "source/slide_01.png": "source"}
