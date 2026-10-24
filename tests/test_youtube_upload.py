"""YouTube Google Drive plugin manifests and their recorded results."""

import json
from pathlib import Path

import pytest

from content_automation.core.config import Settings
from content_automation.youtube import upload


def _settings(tmp_path: Path) -> Settings:
    folders = tmp_path / "drive_folders.json"
    folders.write_text(json.dumps({"root": "root-id", "Calendar": "calendar-id"}),
                       encoding="utf-8")
    return Settings(storage_provider="plugin", state_dir=tmp_path / "state",
                    drive_folders_file=folders, tracker_csv_file=tmp_path / "tracker.csv")


def test_youtube_manifest_lists_scripts_not_research(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    folder = tmp_path / "YouTube Long-Form" / "German AI Topic 2026-10-23"
    for style in ("Style A", "Style B", "Style C"):
        style_folder = folder / style
        style_folder.mkdir(parents=True)
        for filename in ("teleprompter-de.txt", "script-en-de.md", "storyboard.md"):
            (style_folder / filename).write_text("ready", encoding="utf-8")
    (folder / "research.txt").write_text("local research", encoding="utf-8")

    lines = upload._plugin_manifest(settings, folder,
                                    {"bgId": "BG-159", "folder": folder.name}, "long")
    manifest = json.loads((folder / "upload_manifest.json").read_text(encoding="utf-8"))

    files = [entry for entry in manifest["entries"] if entry["kind"] == "file"]
    assert len(files) == 9
    assert all("research.txt" not in entry["local_path"] for entry in files)
    style_a = next(entry for entry in files if entry["id"] ==
                   "file:Style A/teleprompter-de.txt")
    assert style_a["target_folder"] == (
        "YouTube Long-form/German AI Topic 2026-10-23/Style A")
    assert any(entry["folder"] == "YouTube Long-form" for entry in manifest["entries"]
               if entry["kind"] == "folder")
    assert "ca youtube record BG-159" in " ".join(lines)


def test_youtube_short_manifest_targets_topic_folder(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    folder = tmp_path / "YouTube Short-Form" / "AI Music Topic 2026-10-23"
    folder.mkdir(parents=True)
    for filename in ("teleprompter-de.txt", "script-en-de.md", "storyboard.md"):
        (folder / filename).write_text("ready", encoding="utf-8")

    upload._plugin_manifest(settings, folder,
                            {"bgId": "BG-168", "folder": folder.name}, "short")
    manifest = json.loads((folder / "upload_manifest.json").read_text(encoding="utf-8"))
    file_entry = next(entry for entry in manifest["entries"]
                      if entry["id"] == "file:script-en-de.md")

    assert file_entry["target_folder"] == "YouTube Short-form/AI Music Topic 2026-10-23"


def test_youtube_record_queues_then_finishes_tracker_csv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings(tmp_path)
    folder = tmp_path / "YouTube Long-Form" / "German AI Topic 2026-10-23"
    folder.mkdir(parents=True)
    package_data: dict[str, object] = {
        "bgId": "BG-159", "folder": folder.name, "title": "German AI Topic", "format": "long",
    }
    manifest = {
        "kind": "youtube_topic", "bg_id": "BG-159", "package": str(folder),
        "content_id": folder.name, "format": "long", "post_upload_done": False,
        "entries": [
            {"id": "folder:YouTube Long-form/German AI Topic 2026-10-23", "kind": "folder",
             "folder": "YouTube Long-form/German AI Topic 2026-10-23", "done": False},
            {"id": "file:Style A/teleprompter-de.txt", "kind": "file", "done": False},
        ],
    }
    manifest_path = folder / "upload_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(upload, "find_folder", lambda _bg, _root=None: folder)
    monkeypatch.setattr(upload, "read_package", lambda _folder: dict(package_data))
    monkeypatch.setattr(upload, "write_package",
                        lambda _folder, data: package_data.update(data))
    monkeypatch.setattr(upload, "get_storage", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(upload, "tracker_row", lambda *_args: ["Tracker updated."])

    lines = upload.record_youtube_results(settings, "BG-159", [
        {"id": "folder:YouTube Long-form/German AI Topic 2026-10-23", "folder_id": "topic-id"},
        {"id": "file:Style A/teleprompter-de.txt", "status": "failed",
         "error": "temporary network error"},
        {"id": "file:Style A/teleprompter-de.txt", "file_id": "file-id",
         "link": "https://drive.google.com/file/d/file-id/view"},
    ])
    queued = json.loads(manifest_path.read_text(encoding="utf-8"))
    tracker = next(entry for entry in queued["entries"] if entry["kind"] == "tracker_csv")
    assert queued["post_upload_done"] is True
    assert tracker["target_folder_id"] == "calendar-id"
    assert not tracker.get("done")
    assert "Tracker CSV queued" in " ".join(lines)
    assert "failed" not in " ".join(lines)

    done_lines = upload.record_youtube_results(settings, "BG-159", [
        {"id": upload.TRACKER_UPLOAD_ID, "file_id": "tracker-id"},
    ])
    done = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert done["status"] == "done"
    assert "0 entries left (all done)" in " ".join(done_lines)
