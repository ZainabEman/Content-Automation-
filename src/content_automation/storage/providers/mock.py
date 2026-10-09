"""Mock storage (STORAGE_PROVIDER=mock, the default): the Drive layout in a local folder.

Files are copied to <DRIVE_MOCK_DIR>/Content Automation/<Platform>/<Content ID>/ and the
calendar to .../Calendar/ (read-only, replaced in place); links are fake (mock://drive/...).
The Content Tracker is .../tracking.csv with the same merge rules as the Google Sheet.
Nothing needs a Google account, so builds and syncs work before `ca drive setup`.
"""

import hashlib
import shutil
import stat
from pathlib import Path

from content_automation.content.tracking import (
    COLUMNS,
    Cell,
    Table,
    read_csv_table,
    table_csv,
)
from content_automation.core.config import Settings
from content_automation.core.files import atomic_write_text
from content_automation.storage import (
    CALENDAR_FOLDER,
    EXPORT_NAME,
    FOLDERS,
    ROOT_FOLDER,
    StorageError,
    Uploaded,
    platform_folder,
)

TRACKER_FILE = "tracking.csv"


def create_storage(settings: Settings, *, sign_in: bool = False) -> "MockStorage":
    return MockStorage(settings.drive_mock_dir / ROOT_FOLDER)


class MockStorage:
    name = "mock"

    def __init__(self, root: Path) -> None:
        self._root = root

    def ensure_folders(self) -> str:
        try:
            for name in FOLDERS:
                (self._root / name).mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise StorageError(f"mock folder not writable ({type(error).__name__})") from None
        self.read_tracker()  # makes tracking.csv with its header
        return self._root.resolve().as_uri()

    def upload(self, file: Path, platform: str, content_id: str) -> Uploaded:
        return self._copy(file, self._root / platform_folder(platform) / content_id / file.name)

    def upload_calendar(self, file: Path) -> Uploaded:
        return self._copy(file, self._root / CALENDAR_FOLDER / file.name, read_only=True)

    def folder_link(self, platform: str, content_id: str) -> str:
        return f"mock://drive/{platform_folder(platform)}/{content_id}/"

    def read_tracker(self) -> Table:
        path = self._root / TRACKER_FILE
        try:
            if not path.is_file():
                self._write(path, [list(COLUMNS)])
            return read_csv_table(path)
        except OSError as error:
            raise StorageError(f"{TRACKER_FILE} not readable ({type(error).__name__})") from None

    def write_tracker(self, cells: list[Cell], rows: list[list[str]]) -> None:
        table = self.read_tracker()
        for cell in cells:
            while len(table) <= cell.row:
                table.append([])
            row = table[cell.row]
            row += [""] * (cell.column + 1 - len(row))
            row[cell.column] = cell.value
        try:
            self._write(self._root / TRACKER_FILE, table + rows)
        except OSError as error:
            raise StorageError(f"{TRACKER_FILE} not writable ({type(error).__name__})") from None

    def tracker_link(self) -> str:
        return (self._root / TRACKER_FILE).resolve().as_uri()

    def upload_export(self, file: Path) -> Uploaded:
        return self._copy(file, self._root / EXPORT_NAME, read_only=True)

    def _write(self, path: Path, table: Table) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, table_csv(table))

    def _copy(self, file: Path, target: Path, *, read_only: bool = False) -> Uploaded:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():  # a read-only copy is replaced in place
                target.chmod(stat.S_IREAD | stat.S_IWRITE)
            shutil.copyfile(file, target)
            if read_only:
                target.chmod(stat.S_IREAD)
        except OSError as error:
            raise StorageError(f"mock copy failed ({type(error).__name__})") from None
        relative = target.relative_to(self._root).as_posix()
        file_id = "mock-" + hashlib.sha1(relative.encode("utf-8")).hexdigest()[:16]
        return Uploaded(file_id, f"mock://drive/{relative}")
