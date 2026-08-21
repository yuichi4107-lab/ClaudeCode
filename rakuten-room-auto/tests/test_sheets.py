from __future__ import annotations

from pathlib import Path

import pytest
from google.auth.exceptions import RefreshError

from rakuten_room_auto.config import GoogleConfig, SheetConfig
from rakuten_room_auto.sheets import (
    SheetError,
    SheetTable,
    build_sheets_service,
    column_to_a1,
    parse_attempts,
    select_rows,
)
from rakuten_room_auto.statuses import Statuses


def test_column_to_a1():
    assert column_to_a1(0) == "A"
    assert column_to_a1(25) == "Z"
    assert column_to_a1(26) == "AA"
    assert column_to_a1(27) == "AB"


def test_select_rows_by_status():
    values = [
        ["商品URL", "説明文", "ステータス"],
        ["https://item.rakuten.co.jp/example/a", "desc", "承認済"],
        ["https://item.rakuten.co.jp/example/b", "desc", "完了"],
        ["", "desc", "承認済"],
    ]
    table = SheetTable.from_values(values)
    cfg = SheetConfig(
        spreadsheet_id="sheet",
        worksheet_name="items",
        columns={"product_url": "商品URL", "description": "説明文", "status": "ステータス"},
    )
    rows = select_rows(table, cfg, Statuses().run_candidates, 10)
    assert [row.row_number for row in rows] == [2]


def test_parse_attempts_is_tolerant():
    assert parse_attempts("3") == 3
    assert parse_attempts("") == 0
    assert parse_attempts("x") == 0


def test_build_sheets_service_wraps_refresh_error_without_secret(tmp_path, monkeypatch):
    token_path = tmp_path / "google-token.json"
    token_path.write_text("{}", encoding="utf-8")
    leaked_detail = "invalid_grant secret-refresh-token"

    class ExpiredCredentials:
        expired = True
        refresh_token = "present"
        valid = False

        def refresh(self, request):
            raise RefreshError(leaked_detail)

    monkeypatch.setattr(
        "google.oauth2.credentials.Credentials.from_authorized_user_file",
        lambda *args, **kwargs: ExpiredCredentials(),
    )
    config = GoogleConfig(client_secret_json=Path("unused"), token_json=token_path)

    with pytest.raises(SheetError) as exc_info:
        build_sheets_service(config)

    message = str(exc_info.value)
    assert "scripts/setup_google_oauth.py" in message
    assert "invalid_grant" not in message
    assert "secret-refresh-token" not in message
