"""Plugin storage (STORAGE_PROVIDER=plugin): Drive writes by the Codex Google Drive plugin.

`ca` uploads nothing itself: a finished package gets upload_manifest.json (storage/manifest.py)
and the skill uploads each entry with the plugin, then records it with `ca drive record`. The
Content Tracker is kept here as a local CSV (TRACKER_CSV_FILE) with the Sheet's merge rules; its
rows go to Drive as manifest entries too. No Google Cloud project or OAuth client is needed.
"""

from pathlib import Path

from content_automation.content.tracking import COLUMNS, Cell, Table, read_csv_table, table_csv
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.storage import (
    StorageError,
    StorageNotSetUpError,
    Uploaded,
    platform_folder,
)

FOLDER_LINK = "https://drive.google.com/drive/folders/{}"
VIA_MANIFEST = ("STORAGE_PROVIDER=plugin: files go up with the Drive plugin from the package's "
                "upload_manifest.json, then `ca drive record`")


def create_storage(settings: Settings, *, sign_in: bool = False) -> "PluginStorage":
    return PluginStorage(settings)


class PluginStorage:
    name = "plugin"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings  # read by sync_package for the manifest
        self._tracker = settings.tracker_csv_file

    def ensure_folders(self) -> str:
        from content_automation.storage.manifest import known_folders

        folders = known_folders(self.settings)
        if "root" not in folders:
            raise StorageNotSetUpError(f"{self.settings.drive_folders_file} has no root folder ID")
        self.read_tracker()
        return FOLDER_LINK.format(folders["root"])

    def upload(
        self, file: Path, platform: str, content_id: str, subfolder: str | None = None
    ) -> Uploaded:
        raise StorageError(VIA_MANIFEST)

    def upload_calendar(self, file: Path) -> Uploaded:
        raise StorageNotSetUpError("Calendar copy: goes up with the Drive plugin after the next "
                                   "package is recorded (upload_manifest.json)")

    def folder_link(self, platform: str, content_id: str) -> str:
        from content_automation.storage.manifest import known_folders

        found = known_folders(self.settings).get(f"{platform_folder(platform)}/{content_id}")
        if found is None:
            raise StorageError(f"{platform_folder(platform)}/{content_id} is not on Drive yet")
        return FOLDER_LINK.format(found)

    def read_tracker(self) -> Table:
        try:
            if not self._tracker.is_file():
                self._write([list(COLUMNS)])
            return read_csv_table(self._tracker)
        except OSError as error:
            raise StorageError(f"{self._tracker} not readable ({type(error).__name__})") from None

    def write_tracker(self, cells: list[Cell], rows: list[list[str]]) -> None:
        table = self.read_tracker()
        for cell in cells:
            while len(table) <= cell.row:
                table.append([])
            row = table[cell.row]
            row += [""] * (cell.column + 1 - len(row))
            row[cell.column] = cell.value
        try:
            self._write(table + rows)
        except OSError as error:
            raise StorageError(f"{self._tracker} not writable ({type(error).__name__})") from None

    def tracker_link(self) -> str:
        return self._tracker.resolve().as_uri()

    def upload_export(self, file: Path) -> Uploaded:
        raise StorageError(VIA_MANIFEST)

    def _write(self, table: Table) -> None:
        self._tracker.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(self._tracker, table_csv(table))
