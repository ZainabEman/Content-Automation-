"""Upload after the review approval (Phase 7 Step 2).

config/storage.json `upload.requireReview` (default true): a build no longer uploads by itself;
`ca item approve BG-x` on the review gate uploads the approved version to
`<Folder>/<Content ID or BG ID>/v<n>/`. With STORAGE_PROVIDER=plugin, a package's files go into
its upload_manifest.json (storage/manifest.py: the Drive plugin uploads, `ca drive record
<package> --results`); a file without a package (a YouTube final) is one upload request
(state/uploads/<job>.json, a queued `upload` job) recorded with `ca drive record <job> --file-id
--link`.
"""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from content_automation.content.review import package_part
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.registry.artifacts import latest_artifact
from content_automation.registry.items import Item, get_item
from content_automation.registry.jobs import get_job, list_jobs, load_job_config, open_job
from content_automation.registry.jobs import succeed_job as _succeed
from content_automation.registry.progress import set_upload

REQUESTS_DIR = "uploads"
PLUGIN_PROVIDER = "drive"  # free: the Drive plugin uploads, `ca drive record` records


@dataclass(frozen=True)
class StorageConfig:
    require_review: bool = True


def load_storage_config(path: Path) -> StorageConfig:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return StorageConfig()
    upload = data.get("upload", {}) if isinstance(data, dict) else {}
    return StorageConfig(require_review=bool(upload.get("requireReview", True)))


def folder_key(item: Item) -> str:
    """The Drive folder of an item: v5 by its layout variant's category, Facebook Ads and
    Shorts by kind, else its platform."""
    from content_automation.storage import VARIANT_FOLDERS

    if item.layout_variant and item.layout_variant.split("-")[0] in VARIANT_FOLDERS:
        return VARIANT_FOLDERS[item.layout_variant.split("-")[0]]
    if item.deliverable == "facebook_ad" or item.kind == "ad":
        return "facebook_ads"
    if item.kind == "short":
        return "tiktok" if "tiktok" in item.platforms else "shorts"
    return item.platforms[0] if item.platforms else "instagram"


def _target(conn: sqlite3.Connection, settings: Settings, item: Item
            ) -> tuple[Path, list[Path], str] | None:
    if item.kind in ("youtube", "podcast"):  # Phase 8: the approved final (+ thumbnail, audio)
        version = item.approved_version or item.current_version
        media = [Path(saved.path) for kind in ("final", "thumbnail", "audio")
                 if (saved := latest_artifact(conn, item.id, kind, version)) is not None]
        return (media[0].parent if media else Path("."), [p for p in media if p.is_file()],
                item.id)
    found = package_part(settings, item)
    if found is None:
        return None
    folder, _, entry = found
    files = [folder / name for name in entry.files if (folder / name).is_file()]
    content_id = item.id
    try:
        data = json.loads((folder / "package.json").read_text(encoding="utf-8"))
        content_id = str(data.get("contentId") or item.id)
    except (OSError, ValueError):
        pass
    return folder, files, content_id


def upload_approved(conn: sqlite3.Connection, settings: Settings, ref: str, *,
                    files: list[Path] | None = None, subfolder: str | None = None,
                    command: str | None = None) -> list[str]:
    """The approved version's files (or `files`, e.g. prepared platform variants, into
    v<n>/`subfolder`): uploaded now (mock, drive) or queued for the plugin."""
    from content_automation.storage import (
        StorageError,
        StorageNotSetUpError,
        get_storage,
        platform_folder,
    )

    item = get_item(conn, ref)
    target = _target(conn, settings, item)
    if files is None:
        if target is None or not target[1]:
            return []  # nothing made by the app (e.g. an idea-only item): nothing to upload
        files = target[1]
    content_id = target[2] if target is not None else item.id
    version = item.approved_version or item.current_version
    subfolder = f"v{version}" + (f"/{subfolder}" if subfolder else "")
    where = f"{platform_folder(folder_key(item))}/{content_id}/{subfolder}/"
    package = target[0] if target is not None and (target[0] / "package.json").is_file() else None
    if settings.storage_provider == "plugin" and package is not None:
        from content_automation.storage.manifest import Target, write_manifest

        targets = [Target(f"{subfolder}/{_relative(file, package)}", file, where.rstrip("/"),
                          item.id) for file in files]
        try:
            return write_manifest(package, settings, targets)
        except (StorageError, OSError, ValueError) as error:
            return [f"{item.id}: upload manifest not written ({error}); later: uv run ca drive "
                    "sync"]
    if settings.storage_provider == "plugin":  # no package (e.g. a YouTube final): requests
        lines = [queue_upload(conn, settings, item.id, file, where, command=command)
                 for file in files]
        lines.append("Next: the upload skill uploads each request with the Drive plugin, then "
                     "uv run ca drive record <job> --file-id <id> --link <url>.")
        return lines
    try:
        storage = get_storage(settings)
        for file in files:
            storage.upload(file, folder_key(item), content_id, subfolder)
    except (StorageError, StorageNotSetUpError, OSError) as error:
        return [f"{item.id}: upload not done ({error}); later: uv run ca drive sync"]
    set_upload(conn, item.id, "uploaded", storage.name, command=command)
    label = " (mock)" if storage.name == "mock" else ""
    return [f"{item.id} v{version}: {len(files)} file(s) uploaded{label} to {where}"]


def _relative(file: Path, folder: Path) -> str:
    try:
        return file.resolve().relative_to(folder.resolve()).as_posix()
    except ValueError:
        return file.name


def queue_upload(conn: sqlite3.Connection, settings: Settings, item_id: str, file: Path,
                 where: str, *, command: str | None = None) -> str:
    """One queued `upload` job and its request file (state/uploads/<job>.json) for the upload
    skill; `ca jobs resume --all` re-queues a stale or failed upload with it."""
    opened = open_job(conn, item_id=item_id, job_type="upload", provider=PLUGIN_PROVIDER,
                      inputs={"file": file.as_posix(), "folder": where},
                      config=load_job_config(settings.jobs_file), command=command)
    request = settings.state_dir / REQUESTS_DIR / f"{opened.job.id}.json"
    request.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(request, json.dumps({
        "jobId": opened.job.id, "item": item_id, "file": file.resolve().as_posix(),
        "folder": f"Content Automation/{where}"}, indent=2) + "\n")
    return f"Upload request #{opened.job.id}: {file.name} -> {where} ({request})"


def record_plugin_upload(conn: sqlite3.Connection, job_id: int, file_id: str, link: str, *,
                         command: str | None = None) -> list[str]:
    """`ca drive record`: the Drive plugin uploaded the request's file."""
    job = _succeed(conn, job_id, result_path=link, command=command)
    lines = [f"Upload #{job.id} recorded: {file_id} {link}"]
    if job.item_id is None:
        return lines
    uploads = [j for j in list_jobs(conn, item_id=job.item_id, job_types=["upload"])
               if j.version == get_job(conn, job.id).version]
    if all(j.status == "succeeded" for j in uploads):
        set_upload(conn, job.item_id, "uploaded", PLUGIN_PROVIDER, command=command)
        lines.append(f"{job.item_id}: every file uploaded (Drive plugin).")
    return lines
