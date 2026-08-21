"""
J-Quants V2 クライアントのテスト

外部 API は呼ばず、unittest.mock でリクエストをモックする。
"""

import os
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.jquants_client import (
    JQuantsAPIError,
    JQuantsAuthError,
    JQuantsClient,
    JQuantsConfigError,
    init_db,
    load_schema,
    normalize_code,
)


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_dbs(tmp_path):
    return {
        "prices": str(tmp_path / "daily_prices.db"),
        "master": str(tmp_path / "stocks_master.db"),
    }


@pytest.fixture
def client_with_key(tmp_dbs, monkeypatch):
    monkeypatch.setenv("JQUANTS_API_KEY", "dummy_api_key")
    return JQuantsClient(
        prices_db=tmp_dbs["prices"],
        master_db=tmp_dbs["master"],
    )


# ---------------------------------------------------------------------------
# コード正規化
# ---------------------------------------------------------------------------

class TestNormalizeCode:
    def test_4digit_to_5digit(self):
        assert normalize_code("7203") == "72030"

    def test_5digit_passthrough(self):
        assert normalize_code("72030") == "72030"

    def test_non_digit_passthrough(self):
        assert normalize_code("ABC") == "ABC"

    def test_empty_passthrough(self):
        assert normalize_code("") == ""


# ---------------------------------------------------------------------------
# 設定・認証エラー
# ---------------------------------------------------------------------------

class TestJQuantsConfigError:
    def test_raises_when_no_key(self, monkeypatch):
        monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
        with pytest.raises(JQuantsConfigError) as exc_info:
            JQuantsClient(api_key=None)
        assert "JQUANTS_API_KEY" in str(exc_info.value)

    def test_explicit_key_ok(self, tmp_dbs):
        client = JQuantsClient(
            api_key="test_key",
            prices_db=tmp_dbs["prices"],
            master_db=tmp_dbs["master"],
        )
        assert client is not None

    def test_error_mentions_free_plan(self, monkeypatch):
        monkeypatch.delenv("JQUANTS_API_KEY", raising=False)
        with pytest.raises(JQuantsConfigError) as exc_info:
            JQuantsClient(api_key=None)
        assert "Free" in str(exc_info.value) or "プラン" in str(exc_info.value)


# ---------------------------------------------------------------------------
# ヘッダー・リクエスト
# ---------------------------------------------------------------------------

class TestHeaders:
    def test_x_api_key_header(self, client_with_key):
        headers = client_with_key._headers()
        assert headers == {"x-api-key": "dummy_api_key"}


class TestAuthError:
    def test_401_raises_auth_error(self, client_with_key):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.text = '{"message":"The incoming api key is invalid or expired."}'
        with patch.object(client_with_key._session, "get", return_value=mock_resp):
            with pytest.raises(JQuantsAuthError):
                client_with_key._get("/equities/master")

    def test_403_raises_auth_error(self, client_with_key):
        mock_resp = MagicMock()
        mock_resp.status_code = 403
        mock_resp.text = '{"message":"Forbidden"}'
        with patch.object(client_with_key._session, "get", return_value=mock_resp):
            with pytest.raises(JQuantsAuthError):
                client_with_key._get("/equities/master")


# ---------------------------------------------------------------------------
# ページネーション
# ---------------------------------------------------------------------------

class TestPagination:
    def test_paginated_two_pages(self, client_with_key):
        page1 = MagicMock()
        page1.status_code = 200
        page1.json.return_value = {"data": [{"Code": "13010"}], "pagination_key": "next"}
        page1.raise_for_status = MagicMock()

        page2 = MagicMock()
        page2.status_code = 200
        page2.json.return_value = {"data": [{"Code": "13050"}]}
        page2.raise_for_status = MagicMock()

        with patch.object(client_with_key._session, "get", side_effect=[page1, page2]):
            merged = client_with_key._get_paginated("/equities/master")

        assert len(merged) == 2
        assert [r["Code"] for r in merged] == ["13010", "13050"]


# ---------------------------------------------------------------------------
# 銘柄マスター
# ---------------------------------------------------------------------------

class TestGetListedInfo:
    def test_returns_data_list(self, client_with_key):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": [
                {"Code": "72030", "CoName": "トヨタ自動車", "MktNm": "プライム"},
                {"Code": "24130", "CoName": "エムスリー", "MktNm": "グロース"},
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client_with_key._session, "get", return_value=mock_resp):
            result = client_with_key.get_listed_info()

        assert len(result) == 2
        assert result[0]["Code"] == "72030"
        assert result[1]["MktNm"] == "グロース"

    def test_save_listed_info_to_db(self, client_with_key, tmp_dbs):
        sample = [
            {"Code": "72030", "CoName": "トヨタ自動車", "MktNm": "プライム"},
            {"Code": "24130", "CoName": "エムスリー", "MktNm": "グロース"},
        ]
        with patch.object(client_with_key, "get_listed_info", return_value=sample):
            n = client_with_key.save_listed_info_to_db()

        assert n == 2

        with sqlite3.connect(tmp_dbs["master"]) as conn:
            rows = conn.execute("SELECT code, name, market FROM stocks_master ORDER BY code").fetchall()
        assert rows[0] == ("24130", "エムスリー", "グロース")
        assert rows[1] == ("72030", "トヨタ自動車", "プライム")


# ---------------------------------------------------------------------------
# 日足データ
# ---------------------------------------------------------------------------

class TestDailyPrices:
    def test_get_daily_prices_normalizes_code(self, client_with_key):
        """4桁コードが5桁に正規化されて params に載ること"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"data": []}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(client_with_key._session, "get", return_value=mock_resp) as mg:
            client_with_key.get_daily_prices("7203", "2024-02-01", "2024-02-29")

        called_params = mg.call_args.kwargs["params"]
        assert called_params["code"] == "72030"
        assert called_params["from"] == "2024-02-01"
        assert called_params["to"] == "2024-02-29"

    def test_save_daily_prices_maps_v2_fields(self, client_with_key, tmp_dbs):
        """V2スキーマ（O/H/L/C/Vo/Va）がDBカラム（open/high/low/close/volume/turnover）にマップされること"""
        prices = [
            {
                "Code": "72030", "Date": "2024-02-01",
                "O": 2940.5, "H": 2960.0, "L": 2931.0, "C": 2945.0,
                "Vo": 29852200.0, "Va": 87969217550.0, "AdjFactor": 1.0,
            },
        ]
        n = client_with_key.save_daily_prices_to_db(prices)
        assert n == 1

        with sqlite3.connect(tmp_dbs["prices"]) as conn:
            row = conn.execute(
                "SELECT code, date, open, high, low, close, volume, turnover FROM daily_prices"
            ).fetchone()
        assert row == ("72030", "2024-02-01", 2940.5, 2960.0, 2931.0, 2945.0, 29852200.0, 87969217550.0)

    def test_save_daily_prices_no_duplicate(self, client_with_key, tmp_dbs):
        prices = [{
            "Code": "72030", "Date": "2024-02-01",
            "O": 2940.5, "H": 2960.0, "L": 2931.0, "C": 2945.0,
            "Vo": 29852200.0, "Va": 87969217550.0, "AdjFactor": 1.0,
        }]
        client_with_key.save_daily_prices_to_db(prices)
        client_with_key.save_daily_prices_to_db(prices)

        with sqlite3.connect(tmp_dbs["prices"]) as conn:
            count = conn.execute("SELECT COUNT(*) FROM daily_prices").fetchone()[0]
        assert count == 1

    def test_save_daily_prices_empty(self, client_with_key):
        assert client_with_key.save_daily_prices_to_db([]) == 0
