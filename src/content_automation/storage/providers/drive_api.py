"""Google Drive storage (STORAGE_PROVIDER=drive): Drive API v3 and Sheets API v4 with one
OAuth Desktop client.

`ca drive setup` is the only step that opens the browser: one Google sign-in with the
drive.file scope (the app sees only the files it made), the token cached in
<SECRETS_DIR>/google_token.json, then Content Automation/{LinkedIn,Facebook,Instagram,Calendar}
and the "Content Tracker" Google Sheet found or made, and the main folder shared as editor
with DRIVE_SHARE_WITH. The folder, Sheet and copy IDs are kept in
<SECRETS_DIR>/drive_state.json, never in code. Nothing is made public. Every other command only
refreshes the token: no token or no folders = not set up.

Uploads never duplicate: a stored ID is reused, and a file with the same name already in the
target folder (an upload whose ID was not saved) gets the new content instead of a copy.
The tracker gets its header, frozen row, dropdowns and date format once, when the app makes
it; after that only changed workflow cells and new rows are written (Sheets API), so the
manager's statuses, dates and formatting stay as they are.
"""

from importlib.util import find_spec
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError

from content_automation.content.tracking import (
    APPROVAL_STATUSES,
    COLUMNS,
    PUBLISHING_STATUSES,
    TRACKER_NAME,
    Cell,
    Table,
)
from content_automation.core.config import Settings
from content_automation.core.files import CamelModel, atomic_write_text
from content_automation.storage import (
    CALENDAR_FOLDER,
    EXPORT_NAME,
    FOLDERS,
    NOT_SET_UP,
    ROOT_FOLDER,
    StorageError,
    StorageNotSetUpError,
    Uploaded,
    platform_folder,
)

SCOPES = ["https://www.googleapis.com/auth/drive.file"]  # Drive and Sheets: the app's files
CLIENT_FILE = "google_oauth_client.json"
TOKEN_FILE = "google_token.json"
STATE_FILE = "drive_state.json"
FOLDER_MIME = "application/vnd.google-apps.folder"
SHEET_MIME = "application/vnd.google-apps.spreadsheet"
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".csv": "text/csv",
    ".txt": "text/plain",
}
COPY_LOCK = "Read-only copy made by Content Automation; it is replaced on every update."
TRACKER_NOT_SET_UP = "Content Tracker not set up — run ca drive setup"
_LIBRARIES = ("googleapiclient", "google_auth_oauthlib")
_FIELDS = "id, webViewLink"


class DriveState(CamelModel):
    """<SECRETS_DIR>/drive_state.json: the IDs `ca drive setup` and the uploads found or made."""

    root_id: str = ""
    folders: dict[str, str] = Field(default_factory=dict)  # LinkedIn ... Calendar -> ID
    content_folders: dict[str, str] = Field(default_factory=dict)  # "LinkedIn/<Content ID>"
    calendar_files: dict[str, str] = Field(default_factory=dict)  # "2026-W42.csv" -> ID
    tracker_id: str = ""  # the Content Tracker Sheet
    tracker_sheet_id: int | None = None  # its tab (stays right if tabs are added or moved)
    tracker_ready: bool = False  # header and formatting done (only on a Sheet the app made)
    export_id: str = ""  # "Content Tracker.csv"
    shared_with: list[str] = Field(default_factory=list)


class _NotFoundError(StorageError):
    """Google answered 404."""


def create_storage(settings: Settings, *, sign_in: bool = False) -> "DriveStorage":
    return DriveStorage(settings, sign_in=sign_in)


def setup_problem(settings: Settings) -> str | None:
    """What setup still has to do (None: done); local files only, no network call."""
    if any(find_spec(name) is None for name in _LIBRARIES):
        return "Google libraries not installed (run: uv sync)"
    secrets = settings.secrets_dir
    state = _read_state(secrets / STATE_FILE)
    made = state is not None and bool(state.root_id) and bool(state.tracker_id) and (
        state.tracker_ready and all(name in state.folders for name in FOLDERS)
    )
    if (secrets / TOKEN_FILE).is_file() and made:
        return None
    if not (secrets / CLIENT_FILE).is_file():
        return f"no OAuth client at {secrets / CLIENT_FILE}"
    if not (secrets / TOKEN_FILE).is_file():
        return "not signed in yet"
    return "folders or Content Tracker not made"


class DriveStorage:
    name = "drive"

    def __init__(self, settings: Settings, *, sign_in: bool = False) -> None:
        if any(find_spec(name) is None for name in _LIBRARIES):
            raise StorageError("Google libraries not installed (run: uv sync)")
        self._secrets = settings.secrets_dir
        self._share_with = [
            email.strip() for email in settings.drive_share_with.split(",") if email.strip()
        ]
        state = _read_state(self._secrets / STATE_FILE)
        if state is None and not sign_in:
            raise StorageNotSetUpError(NOT_SET_UP)
        self._state = state or DriveState()
        self._checked: set[str] = set()  # IDs seen in Drive during this command
        self._creds = _credentials(self._secrets, sign_in=sign_in)
        self._service = _service(self._creds, "drive", "v3")
        self._sheets_service: Any = None
        self._tab_cache: dict[str, Any] | None = None
        self._rows_read: int | None = None  # rows in the tracker at the last read

    # ------------------------------------------------------------------ interface

    def ensure_folders(self) -> str:
        state = self._state
        root = self._folder(state.root_id, ROOT_FOLDER, parent=None)
        if root != state.root_id:  # a new main folder: the old IDs belonged to the old one
            self._state = state = DriveState(root_id=root)
        for name in FOLDERS:
            state.folders[name] = self._folder(state.folders.get(name, ""), name, parent=root)
        self._save_state()
        self._ensure_tracker(root)
        for email in self._share_with:  # editor access only; never "anyone with the link"
            if email in state.shared_with:
                continue
            self._run(self._service.permissions().create(
                fileId=root,
                body={"type": "user", "role": "writer", "emailAddress": email},
                sendNotificationEmail=True,
                fields="id",
            ))
            state.shared_with.append(email)
            self._save_state()
        meta = self._run(self._service.files().get(fileId=root, fields="webViewLink"))
        return str(meta["webViewLink"])

    def upload(
        self, file: Path, platform: str, content_id: str, subfolder: str | None = None
    ) -> Uploaded:
        name = platform_folder(platform)
        parent = self._state.folders.get(name)
        if not parent and self._state.root_id and self._state.folders:
            # v6 (R8): a top folder added after setup (YouTube Long-Form) is created once under
            # the main folder; nothing that exists is moved or renamed
            parent = self._folder("", name, parent=self._state.root_id)
            self._state.folders[name] = parent
            self._save_state()
        if not parent:
            raise StorageNotSetUpError(NOT_SET_UP)
        key, folder = name, parent
        for part in content_id.split("/"):  # v5: YouTube/<YYYY-MM>/<BG-ID>_<slug> is nested
            key = f"{key}/{part}"
            folder = self._content_folder(key, part, folder)
        if subfolder:
            folder = self._content_folder(f"{key}/{subfolder}", subfolder, folder)
        return self._put(file, folder, self._find(file.name, folder))

    def _content_folder(self, key: str, name: str, parent: str) -> str:
        """A content folder (or its subfolder), remembered in drive_state.json by key."""
        folder = self._folder(self._state.content_folders.get(key, ""), name, parent)
        if self._state.content_folders.get(key) != folder:
            self._state.content_folders[key] = folder
            self._save_state()
        return folder

    def upload_calendar(self, file: Path) -> Uploaded:
        parent = self._state.folders.get(CALENDAR_FOLDER)
        if not parent:
            raise StorageNotSetUpError(NOT_SET_UP)
        known = self._state.calendar_files.get(file.name, "")
        uploaded = self._replace_copy(file, parent, known, file.name)
        if known != uploaded.file_id:
            self._state.calendar_files[file.name] = uploaded.file_id
            self._save_state()
        return uploaded

    def folder_link(self, platform: str, content_id: str) -> str:
        name = platform_folder(platform)
        folder = self._state.content_folders.get(f"{name}/{content_id}")
        parent = self._state.folders.get(name)
        if not folder and parent:
            folder = self._find(content_id, parent, mime=FOLDER_MIME)
        if not folder:
            raise StorageError(f"no Drive folder {name}/{content_id} yet")
        return f"https://drive.google.com/drive/folders/{folder}"

    def read_tracker(self) -> Table:
        tab = self._tab()
        result = self._run(self._sheets().spreadsheets().values().get(
            spreadsheetId=self._tracker_id(), range=_a1_title(tab["title"]),
            valueRenderOption="FORMATTED_VALUE",
        ))
        table = [[str(value) for value in row] for row in result.get("values", [])]
        self._rows_read = len(table)
        return table

    def write_tracker(self, cells: list[Cell], rows: list[list[str]]) -> None:
        if self._rows_read is None:
            self.read_tracker()
        tab = self._tab()
        title = _a1_title(tab["title"])
        data = [{"range": f"{title}!{_a1_cell(cell.row, cell.column)}", "values": [[cell.value]]}
                for cell in cells]
        needed = max([cell.column + 1 for cell in cells] + [len(row) for row in rows] + [0])
        columns = int(tab.get("gridProperties", {}).get("columnCount", 26))
        if needed > columns:  # registry columns appended after the existing ones: widen first
            self._run(self._sheets().spreadsheets().batchUpdate(
                spreadsheetId=self._tracker_id(),
                body={"requests": [{"appendDimension": {
                    "sheetId": int(tab.get("sheetId", 0)), "dimension": "COLUMNS",
                    "length": needed - columns,
                }}]},
            ))
            self._tab_cache = None
        if rows:
            start = self._rows_read or 1  # 0-based index of the first new row
            grid = int(tab.get("gridProperties", {}).get("rowCount", 0))
            if start + len(rows) > grid:  # the Sheet is full: add rows at the end first
                self._run(self._sheets().spreadsheets().batchUpdate(
                    spreadsheetId=self._tracker_id(),
                    body={"requests": [{"appendDimension": {
                        "sheetId": int(tab.get("sheetId", 0)), "dimension": "ROWS",
                        "length": start + len(rows) - grid,
                    }}]},
                ))
                self._tab_cache = None
            data.append({"range": f"{title}!A{start + 1}", "values": rows})
            self._rows_read = start + len(rows)
        if data:
            self._run(self._sheets().spreadsheets().values().batchUpdate(
                spreadsheetId=self._tracker_id(),
                body={"valueInputOption": "RAW", "data": data},
            ))

    def tracker_link(self) -> str:
        return f"https://docs.google.com/spreadsheets/d/{self._tracker_id()}/edit"

    def upload_export(self, file: Path) -> Uploaded:
        if not self._state.root_id:
            raise StorageNotSetUpError(NOT_SET_UP)
        uploaded = self._replace_copy(file, self._state.root_id, self._state.export_id,
                                      EXPORT_NAME)
        if self._state.export_id != uploaded.file_id:
            self._state.export_id = uploaded.file_id
            self._save_state()
        return uploaded

    # ------------------------------------------------------------------ tracker

    def _ensure_tracker(self, root: str) -> None:
        """Find or make the Content Tracker; only a Sheet the app made gets formatted."""
        state = self._state
        if not (state.tracker_id and self._exists(state.tracker_id)):
            found = self._find(TRACKER_NAME, root, mime=SHEET_MIME)
            if found:  # e.g. the state file was lost: keep the manager's Sheet as it is
                state.tracker_id, state.tracker_sheet_id, state.tracker_ready = found, None, True
            else:
                created = self._run(self._service.files().create(
                    body={"name": TRACKER_NAME, "mimeType": SHEET_MIME, "parents": [root]},
                    fields="id",
                ))
                state.tracker_id, state.tracker_sheet_id = str(created["id"]), None
                state.tracker_ready = False
            self._save_state()  # saved before formatting: a failure never makes a 2nd Sheet
        tab = self._tab()
        if not state.tracker_ready:
            self._format_tracker(int(tab.get("sheetId", 0)), str(tab["title"]))
            state.tracker_ready = True
            self._save_state()

    def _format_tracker(self, sheet_id: int, title: str) -> None:
        """Header, frozen and bold; status dropdowns; Publication date as a date."""
        self._run(self._sheets().spreadsheets().values().update(
            spreadsheetId=self._tracker_id(), range=f"{_a1_title(title)}!A1",
            valueInputOption="RAW", body={"values": [list(COLUMNS)]},
        ))
        column = {name: number for number, name in enumerate(COLUMNS)}
        approval = _below_header(sheet_id, column["Approval status"])
        publishing = _below_header(sheet_id, column["Publishing status"])
        date = _below_header(sheet_id, column["Publication date"])
        requests: list[dict[str, Any]] = [
            {"updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }},
            {"repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }},
            {"setDataValidation": {"range": approval, "rule": _one_of(APPROVAL_STATUSES)}},
            {"setDataValidation": {"range": publishing, "rule": _one_of(PUBLISHING_STATUSES)}},
            {"setDataValidation": {"range": date, "rule": {
                "condition": {"type": "DATE_IS_VALID"}, "strict": True,
            }}},
            {"repeatCell": {
                "range": date,
                "cell": {"userEnteredFormat": {
                    "numberFormat": {"type": "DATE", "pattern": "yyyy-mm-dd"},
                }},
                "fields": "userEnteredFormat.numberFormat",
            }},
            {"repeatCell": {
                "range": _below_header(sheet_id, column["Caption"]),
                "cell": {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                "fields": "userEnteredFormat.wrapStrategy",
            }},
        ]
        self._run(self._sheets().spreadsheets().batchUpdate(
            spreadsheetId=self._tracker_id(), body={"requests": requests}
        ))

    def _tab(self) -> dict[str, Any]:
        """The tracker tab's properties: the stored tab, else the first one."""
        if self._tab_cache is not None:
            return self._tab_cache
        meta = self._run(self._sheets().spreadsheets().get(
            spreadsheetId=self._tracker_id(),
            fields="sheets.properties(sheetId,title,gridProperties.rowCount,"
                   "gridProperties.columnCount)",
        ))
        tabs = [sheet["properties"] for sheet in meta.get("sheets", [])]
        if not tabs:
            raise StorageError(f"{TRACKER_NAME} has no tab")
        wanted = self._state.tracker_sheet_id
        tab: dict[str, Any] = next((t for t in tabs if t.get("sheetId", 0) == wanted), tabs[0])
        if wanted != tab.get("sheetId", 0):
            self._state.tracker_sheet_id = int(tab.get("sheetId", 0))
            self._save_state()
        self._tab_cache = tab
        return tab

    def _tracker_id(self) -> str:
        if not self._state.tracker_id:
            raise StorageNotSetUpError(TRACKER_NOT_SET_UP)
        return self._state.tracker_id

    def _sheets(self) -> Any:
        if self._sheets_service is None:
            self._sheets_service = _service(self._creds, "sheets", "v4")
        return self._sheets_service

    # ------------------------------------------------------------------ Drive calls

    def _folder(self, known: str, name: str, parent: str | None) -> str:
        """The known folder if it still exists, else one found by name, else a new one."""
        if known and self._exists(known):
            return known
        found = self._find(name, parent, mime=FOLDER_MIME)
        if found:
            return found
        body: dict[str, Any] = {"name": name, "mimeType": FOLDER_MIME}
        if parent:
            body["parents"] = [parent]
        created = str(self._run(self._service.files().create(body=body, fields="id"))["id"])
        self._checked.add(created)
        return created

    def _exists(self, file_id: str) -> bool:
        if file_id in self._checked:
            return True
        try:
            meta = self._run(self._service.files().get(fileId=file_id, fields="id, trashed"))
        except _NotFoundError:
            return False
        if meta.get("trashed"):
            return False
        self._checked.add(file_id)
        return True

    def _find(self, name: str, parent: str | None, *, mime: str | None = None) -> str | None:
        """An app-made item with this name (drive.file sees only the app's files); without
        mime: any file that is not a folder."""
        quoted = name.replace("\\", "\\\\").replace("'", "\\'")
        kind = f"mimeType = '{mime}'" if mime else f"mimeType != '{FOLDER_MIME}'"
        terms = [f"name = '{quoted}'", "trashed = false", kind]
        if parent:
            terms.append(f"'{parent}' in parents")
        found = self._run(self._service.files().list(
            q=" and ".join(terms), spaces="drive", fields="files(id)", pageSize=1
        ))
        files = found.get("files") or []
        return str(files[0]["id"]) if files else None

    def _put(
        self, file: Path, parent: str, existing: str | None, name: str | None = None
    ) -> Uploaded:
        from googleapiclient.http import MediaFileUpload

        try:
            media = MediaFileUpload(
                str(file),
                mimetype=MIME_TYPES.get(file.suffix.lower(), "application/octet-stream"),
                resumable=True,
            )
        except OSError as error:
            raise StorageError(f"cannot read {file.name} ({type(error).__name__})") from None
        files = self._service.files()
        if existing:  # same name already there: new content, same file
            request = files.update(fileId=existing, media_body=media, fields=_FIELDS)
        else:
            request = files.create(
                body={"name": name or file.name, "parents": [parent]},
                media_body=media,
                fields=_FIELDS,
            )
        result = self._run(request)
        self._checked.add(str(result["id"]))
        return Uploaded(str(result["id"]), str(result["webViewLink"]))

    def _replace_copy(self, file: Path, parent: str, known: str, name: str) -> Uploaded:
        """A read-only copy replaced in place: unlocked, new content, locked again."""
        existing = known if known and self._exists(known) else self._find(name, parent)
        if existing:
            self._lock(existing, read_only=False)  # a read-only file takes no new content
        uploaded = self._put(file, parent, existing, name=name)
        self._lock(uploaded.file_id, read_only=True)
        return uploaded

    def _lock(self, file_id: str, *, read_only: bool) -> None:
        restriction: dict[str, Any] = {"readOnly": read_only}
        if read_only:
            restriction["reason"] = COPY_LOCK
        self._run(self._service.files().update(
            fileId=file_id, body={"contentRestrictions": [restriction]}, fields="id"
        ))

    def _run(self, request: Any) -> dict[str, Any]:
        """Execute one Google request; errors become StorageError (no key or token shown)."""
        from google.auth.exceptions import RefreshError, TransportError
        from googleapiclient.errors import Error as ApiError
        from googleapiclient.errors import HttpError
        from httplib2 import HttpLib2Error

        try:
            result: dict[str, Any] = request.execute()
        except RefreshError:  # the sign-in was revoked or expired for good
            raise StorageNotSetUpError(NOT_SET_UP) from None
        except HttpError as error:
            status = int(error.resp.status)
            if status == 404:
                raise _NotFoundError(
                    "Google HTTP 404: a folder, file or Sheet is gone (run ca drive setup)"
                ) from None
            raise StorageError(f"Google HTTP {status}: {error.reason or 'error'}") from None
        except (ApiError, TransportError, HttpLib2Error, OSError) as error:
            raise StorageError(f"Google not reachable ({type(error).__name__})") from None
        return result

    def _save_state(self) -> None:
        self._secrets.mkdir(parents=True, exist_ok=True)
        text = self._state.model_dump_json(by_alias=True, indent=2) + "\n"
        atomic_write_text(self._secrets / STATE_FILE, text)


def _below_header(sheet_id: int, column: int) -> dict[str, int]:
    """One whole column from row 2 down (new rows included)."""
    return {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": column,
            "endColumnIndex": column + 1}


def _one_of(values: tuple[str, ...]) -> dict[str, Any]:
    return {
        "condition": {"type": "ONE_OF_LIST",
                      "values": [{"userEnteredValue": value} for value in values]},
        "strict": True,
        "showCustomUi": True,
    }


def _a1_title(title: str) -> str:
    return "'" + title.replace("'", "''") + "'"


def _a1_cell(row: int, column: int) -> str:
    """0-based row and column -> "F12"."""
    letters = ""
    column += 1
    while column:
        column, rest = divmod(column - 1, 26)
        letters = chr(ord("A") + rest) + letters
    return f"{letters}{row + 1}"


def _read_state(path: Path) -> DriveState | None:
    try:
        return DriveState.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError):
        return None  # setup finds the folders again by name


def _credentials(secrets: Path, *, sign_in: bool) -> Any:
    """The cached token, refreshed when expired; only sign_in opens the browser."""
    from google.auth.exceptions import GoogleAuthError, RefreshError, TransportError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    token = secrets / TOKEN_FILE
    creds: Any = None
    if token.is_file():
        try:
            creds = Credentials.from_authorized_user_file(  # type: ignore[no-untyped-call]
                str(token), SCOPES
            )
        except (OSError, ValueError):
            creds = None  # unreadable: sign in again
    if creds is not None and not creds.valid and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            creds = None  # revoked: sign in again
        except TransportError:
            raise StorageError("Google not reachable (no connection)") from None
        else:
            _save_token(token, creds)
    if creds is not None and creds.valid:
        return creds
    if not sign_in:
        raise StorageNotSetUpError(NOT_SET_UP)
    client = secrets / CLIENT_FILE
    if not client.is_file():
        raise StorageError(
            f"No OAuth client at {client}: download the Desktop app client JSON from Google "
            "Cloud and save it there."
        )
    from google_auth_oauthlib.flow import InstalledAppFlow
    from oauthlib.oauth2.rfc6749.errors import OAuth2Error

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(client), SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True)
    except (OSError, ValueError, GoogleAuthError, OAuth2Error) as error:
        raise StorageError(f"Google sign-in failed ({type(error).__name__}).") from None
    _save_token(token, creds)
    return creds


def _save_token(path: Path, creds: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, str(creds.to_json()))


def _service(creds: Any, api: str, version: str) -> Any:
    from googleapiclient.discovery import build
    from googleapiclient.errors import Error as ApiError

    try:
        return build(api, version, credentials=creds, cache_discovery=False)
    except (ApiError, OSError) as error:
        raise StorageError(f"Google not reachable ({type(error).__name__})") from None
