#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def add_src_to_path() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "src"))


def main() -> int:
    add_src_to_path()

    from rakuten_room_auto.config import load_config
    from rakuten_room_auto.sheets import GoogleSheetClient, SheetError, SheetTable

    parser = argparse.ArgumentParser(description="Prepare the Rakuten ROOM Google Sheet.")
    parser.add_argument("--config", help="Path to config.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)
    client = GoogleSheetClient(cfg.google, cfg.sheet)
    metadata = (
        client.service.spreadsheets()
        .get(spreadsheetId=cfg.sheet.spreadsheet_id, includeGridData=False)
        .execute()
    )
    sheet = next(
        (item for item in metadata.get("sheets", []) if item.get("properties", {}).get("title") == cfg.sheet.worksheet_name),
        None,
    )
    if not sheet:
        raise SheetError(f"Sheet tab not found: {cfg.sheet.worksheet_name}")
    sheet_id = sheet["properties"]["sheetId"]
    grid_column_count = sheet["properties"]["gridProperties"].get("columnCount", 26)

    table = client.read_table()
    required_headers = [
        cfg.sheet.columns["product_url"],
        cfg.sheet.columns["description"],
        cfg.sheet.columns["status"],
        cfg.sheet.columns["posted_at"],
        cfg.sheet.columns["error"],
        cfg.sheet.columns["attempts"],
    ]
    existing_by_index = {index: name for name, index in table.header.items()}
    existing_headers = [
        existing_by_index[index]
        for index in range(max(existing_by_index.keys(), default=-1) + 1)
        if existing_by_index.get(index)
    ]
    header_values = list(existing_headers)
    for header in required_headers:
        if header not in header_values:
            header_values.append(header)

    values_body = {"values": [header_values + [""] * max(0, grid_column_count - len(header_values))]}
    (
        client.service.spreadsheets()
        .values()
        .update(
            spreadsheetId=cfg.sheet.spreadsheet_id,
            range=f"{cfg.sheet.worksheet_name}!1:1",
            valueInputOption="USER_ENTERED",
            body=values_body,
        )
        .execute()
    )

    refreshed = client.read_table()
    status_col = refreshed.header[cfg.sheet.columns["status"]]
    end_col = max(refreshed.header.values()) + 1
    requests = [
        {
            "setDataValidation": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 1,
                    "endRowIndex": sheet["properties"]["gridProperties"].get("rowCount", 1000),
                    "startColumnIndex": status_col,
                    "endColumnIndex": status_col + 1,
                },
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [
                            {"userEnteredValue": cfg.statuses.unposted},
                            {"userEnteredValue": cfg.statuses.approval_pending},
                            {"userEnteredValue": cfg.statuses.approved},
                            {"userEnteredValue": cfg.statuses.processing},
                            {"userEnteredValue": cfg.statuses.completed},
                            {"userEnteredValue": cfg.statuses.needs_review},
                            {"userEnteredValue": cfg.statuses.error},
                        ],
                    },
                    "strict": True,
                    "showCustomUi": True,
                },
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": 0,
                    "endRowIndex": 1,
                    "startColumnIndex": 0,
                    "endColumnIndex": end_col,
                },
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold",
            }
        },
        {
            "updateSheetProperties": {
                "properties": {"sheetId": sheet_id, "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount",
            }
        },
    ]
    client.service.spreadsheets().batchUpdate(
        spreadsheetId=cfg.sheet.spreadsheet_id,
        body={"requests": requests},
    ).execute()
    print("Sheet setup complete.")
    print(f"spreadsheet_id: {cfg.sheet.spreadsheet_id}")
    print(f"worksheet_name: {cfg.sheet.worksheet_name}")
    print("headers:", ", ".join(header_values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
