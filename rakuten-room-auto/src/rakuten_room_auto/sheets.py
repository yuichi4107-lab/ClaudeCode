from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .config import GoogleConfig, SheetConfig
from .statuses import Statuses


SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


class SheetError(RuntimeError):
    pass


@dataclass(frozen=True)
class SheetRow:
    row_number: int
    header: dict[str, int]
    values: list[str]

    def get_by_header(self, header_name: str) -> str:
        index = self.header.get(header_name)
        if index is None or index >= len(self.values):
            return ""
        return self.values[index].strip()

    def get(self, logical_name: str, columns: dict[str, str]) -> str:
        return self.get_by_header(columns[logical_name])


@dataclass(frozen=True)
class SheetTable:
    header: dict[str, int]
    rows: list[SheetRow]

    @classmethod
    def from_values(cls, values: list[list[Any]], header_row: int = 1) -> "SheetTable":
        if not values or len(values) < header_row:
            raise SheetError("Spreadsheet has no header row.")
        raw_header = [str(item).strip() for item in values[header_row - 1]]
        header = {name: index for index, name in enumerate(raw_header) if name}
        rows: list[SheetRow] = []
        for offset, raw_row in enumerate(values[header_row:], start=header_row + 1):
            row = [str(item) for item in raw_row]
            rows.append(SheetRow(row_number=offset, header=header, values=row))
        return cls(header=header, rows=rows)

    def require_columns(self, columns: Iterable[str]) -> None:
        missing = [name for name in columns if name not in self.header]
        if missing:
            raise SheetError(f"Missing required columns: {', '.join(missing)}")


def column_to_a1(index: int) -> str:
    if index < 0:
        raise ValueError("column index must be non-negative")
    result = ""
    current = index + 1
    while current:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result
    return result


def parse_attempts(value: str) -> int:
    try:
        return int(value.strip() or "0")
    except ValueError:
        return 0


def select_rows(table: SheetTable, sheet_config: SheetConfig, statuses: set[str], limit: int) -> list[SheetRow]:
    columns = sheet_config.columns
    table.require_columns([columns["product_url"], columns["status"]])
    selected: list[SheetRow] = []
    for row in table.rows:
        product_url = row.get("product_url", columns)
        status = row.get("status", columns)
        if product_url and status in statuses:
            selected.append(row)
        if len(selected) >= limit:
            break
    return selected


def build_sheets_service(google_config: GoogleConfig):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_path = google_config.token_json
    if not token_path.exists():
        raise SheetError(f"Google token is missing: {token_path}")
    creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            raise SheetError(
                "Google認証の有効期限が切れているか、取り消されています。"
                "scripts/setup_google_oauth.py を再実行してください。"
            ) from None
        token_path.write_text(creds.to_json(), encoding="utf-8")
    if not creds.valid:
        raise SheetError("Google token is invalid. Run scripts/setup_google_oauth.py again.")
    return build("sheets", "v4", credentials=creds)


class GoogleSheetClient:
    def __init__(self, google_config: GoogleConfig, sheet_config: SheetConfig):
        self.google_config = google_config
        self.sheet_config = sheet_config
        self.service = build_sheets_service(google_config)

    def read_table(self) -> SheetTable:
        if not self.sheet_config.spreadsheet_id:
            raise SheetError("sheet.spreadsheet_id is not configured.")
        range_name = f"{self.sheet_config.worksheet_name}!A:Z"
        result = (
            self.service.spreadsheets()
            .values()
            .get(spreadsheetId=self.sheet_config.spreadsheet_id, range=range_name)
            .execute()
        )
        return SheetTable.from_values(result.get("values", []), header_row=self.sheet_config.header_row)

    def append_row_fields(self, header: dict[str, int], fields: dict[str, str]) -> None:
        """論理列名→値のdictから1行を組み立て、シート末尾に追記する。"""
        values: list[str] = [""] * (max(header.values()) + 1)
        for logical_name, value in fields.items():
            header_name = self.sheet_config.columns[logical_name]
            if header_name not in header:
                raise SheetError(f"Missing column for append: {header_name}")
            values[header[header_name]] = value
        body = {"values": [values]}
        (
            self.service.spreadsheets()
            .values()
            .append(
                spreadsheetId=self.sheet_config.spreadsheet_id,
                range=f"{self.sheet_config.worksheet_name}!A:Z",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute()
        )

    def update_row_fields(self, row: SheetRow, updates: dict[str, str]) -> None:
        data = []
        for logical_name, value in updates.items():
            header_name = self.sheet_config.columns[logical_name]
            if header_name not in row.header:
                raise SheetError(f"Missing column for update: {header_name}")
            col_a1 = column_to_a1(row.header[header_name])
            range_name = f"{self.sheet_config.worksheet_name}!{col_a1}{row.row_number}"
            data.append({"range": range_name, "values": [[value]]})
        if not data:
            return
        body = {"valueInputOption": "USER_ENTERED", "data": data}
        (
            self.service.spreadsheets()
            .values()
            .batchUpdate(spreadsheetId=self.sheet_config.spreadsheet_id, body=body)
            .execute()
        )


def now_jst_iso() -> str:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d %H:%M:%S")
