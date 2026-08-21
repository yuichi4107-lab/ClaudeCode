"""
kabu PUSH 気配保存スクリプトのテスト

モックケーバー経由で SQLite への書き込みを検証する。
外部 HTTP 接続は unittest.mock でモックし、実際の kabu API は呼ばない。
"""

import json
import os
import sqlite3
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from data.kabu_push_recorder import (
    KabuAPIError,
    KabuHTTPClient,
    KabuPushRecorder,
    init_quotes_db,
    save_snapshot,
)


# ---------------------------------------------------------------------------
# フィクスチャ
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    db = str(tmp_path / "quotes_live.db")
    init_quotes_db(db)
    return db


@pytest.fixture
def sample_board():
    """公式形式のサンプル板データ"""
    board = {
        "Symbol": "7203",
        "SymbolName": "トヨタ自動車",
        "Exchange": 1,
        "CurrentPrice": 2500,
        "CalcPrice": 2515,
        "AskSign": "0101",
        "BidSign": "0101",
        "OverSell": 5000,
        "UnderBuy": 8000,
        "TradingVolume": 0,
        "_recorded_at": "2026-04-15T08:45:00",
    }
    for i in range(1, 11):
        board[f"Sell{i}"] = {"Price": 2500 + i, "Qty": 1000 * i, "Sign": "0101" if i == 1 else None}
        board[f"Buy{i}"]  = {"Price": 2500 - i, "Qty": 800  * i, "Sign": "0101" if i == 1 else None}
    return board


# ---------------------------------------------------------------------------
# DB 初期化
# ---------------------------------------------------------------------------

class TestInitQuotesDB:
    def test_creates_table(self, tmp_path):
        db = str(tmp_path / "test.db")
        init_quotes_db(db)
        with sqlite3.connect(db) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        table_names = [t[0] for t in tables]
        assert "quotes_snapshot" in table_names

    def test_creates_index(self, tmp_path):
        db = str(tmp_path / "test.db")
        init_quotes_db(db)
        with sqlite3.connect(db) as conn:
            indexes = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        index_names = [i[0] for i in indexes]
        assert any("symbol" in n.lower() for n in index_names)


# ---------------------------------------------------------------------------
# スナップショット保存
# ---------------------------------------------------------------------------

class TestSaveSnapshot:
    def test_save_returns_rowid(self, tmp_db, sample_board):
        rowid = save_snapshot(tmp_db, sample_board)
        assert isinstance(rowid, int)
        assert rowid > 0

    def test_save_all_fields(self, tmp_db, sample_board):
        """全フィールドが正しく保存されること"""
        save_snapshot(tmp_db, sample_board)
        with sqlite3.connect(tmp_db) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM quotes_snapshot LIMIT 1").fetchone()

        assert row["symbol"] == "7203"
        assert row["ask_sign"] == "0101"
        assert row["current_price"] == 2500
        assert row["calc_price"] == 2515
        assert row["over_sell"] == 5000
        assert row["under_buy"] == 8000

    def test_save_sell_levels_json(self, tmp_db, sample_board):
        """売り板JSON が保存されること"""
        save_snapshot(tmp_db, sample_board)
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT sell_levels_json FROM quotes_snapshot LIMIT 1").fetchone()

        levels = json.loads(row[0])
        assert isinstance(levels, list)
        assert len(levels) == 10
        assert "price" in levels[0]
        assert "qty" in levels[0]

    def test_save_buy_levels_json(self, tmp_db, sample_board):
        """買い板JSON が保存されること"""
        save_snapshot(tmp_db, sample_board)
        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT buy_levels_json FROM quotes_snapshot LIMIT 1").fetchone()

        levels = json.loads(row[0])
        assert len(levels) == 10

    def test_save_multiple_snapshots(self, tmp_db, sample_board):
        """複数スナップショットが正しく積み上がること（1分足シミュレーション）"""
        for minute in range(60):  # 60件（1時間分）
            snap = dict(sample_board)
            snap["_recorded_at"] = f"2026-04-15T08:{minute:02d}:00"
            save_snapshot(tmp_db, snap)

        with sqlite3.connect(tmp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM quotes_snapshot").fetchone()[0]
        assert count == 60

    def test_save_timestamp_stored(self, tmp_db, sample_board):
        """タイムスタンプが保存されること"""
        ts = "2026-04-15T08:45:30.123456"
        sample_board["_recorded_at"] = ts
        save_snapshot(tmp_db, sample_board)

        with sqlite3.connect(tmp_db) as conn:
            row = conn.execute("SELECT timestamp FROM quotes_snapshot LIMIT 1").fetchone()
        assert row[0] == ts


# ---------------------------------------------------------------------------
# HTTP クライアント
# ---------------------------------------------------------------------------

class TestKabuHTTPClient:
    def test_get_token_success(self):
        """トークン取得が正常に動作すること"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"Token": "test_api_token"}
        mock_resp.raise_for_status = MagicMock()

        client = KabuHTTPClient("http://localhost:18081", "pw")

        with patch.object(client._session, "post", return_value=mock_resp):
            token = client._get_token()

        assert token == "test_api_token"

    def test_get_board_success(self):
        """板情報取得が正常に動作すること"""
        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"Token": "api_token_xyz"}
        mock_token_resp.raise_for_status = MagicMock()

        mock_board_resp = MagicMock()
        mock_board_resp.status_code = 200
        mock_board_resp.json.return_value = {
            "Symbol": "7203",
            "AskSign": "0101",
            "CurrentPrice": 2500,
        }
        mock_board_resp.raise_for_status = MagicMock()

        client = KabuHTTPClient("http://localhost:18081", "pw")

        with patch.object(client._session, "post", return_value=mock_token_resp):
            with patch.object(client._session, "get", return_value=mock_board_resp):
                board = client.get_board("7203")

        assert board["Symbol"] == "7203"

    def test_get_board_http_error_raises(self):
        """HTTP エラー時に KabuAPIError が送出されること"""
        import requests

        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.json.return_value = {"Token": "api_token"}
        mock_token_resp.raise_for_status = MagicMock()

        mock_err_resp = MagicMock()
        mock_err_resp.status_code = 500
        mock_err_resp.text = "Internal Server Error"
        mock_err_resp.raise_for_status.side_effect = requests.HTTPError("500")

        client = KabuHTTPClient("http://localhost:18081", "pw")

        with patch.object(client._session, "post", return_value=mock_token_resp):
            with patch.object(client._session, "get", return_value=mock_err_resp):
                with pytest.raises(KabuAPIError):
                    client.get_board("7203")


# ---------------------------------------------------------------------------
# レコーダー統合テスト（モック使用）
# ---------------------------------------------------------------------------

class TestKabuPushRecorder:
    def test_record_snapshot_with_mock_board(self, tmp_db):
        """モック経由でスナップショット取得→DB保存が成功すること"""
        sample_board = {
            "Symbol": "7203",
            "AskSign": "0101",
            "BidSign": "0101",
            "CurrentPrice": 2500,
            "CalcPrice": 2510,
            "OverSell": 3000,
            "UnderBuy": 6000,
            "TradingVolume": 0,
        }
        for i in range(1, 11):
            sample_board[f"Sell{i}"] = {"Price": 2500 + i, "Qty": 500 * i}
            sample_board[f"Buy{i}"]  = {"Price": 2500 - i, "Qty": 400 * i}

        recorder = KabuPushRecorder(db_path=tmp_db)

        with patch.object(recorder._client, "get_board", return_value=sample_board):
            rowid = recorder.record_snapshot("7203")

        assert rowid > 0

        with sqlite3.connect(tmp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM quotes_snapshot").fetchone()[0]
        assert count == 1

    def test_run_polling_single_iteration(self, tmp_db):
        """ポーリングが 1 イテレーション実行されること（time_window=False）"""
        sample_board = {
            "Symbol": "9984",
            "AskSign": "0101",
            "BidSign": "0101",
            "CurrentPrice": 8000,
            "CalcPrice": 8050,
            "OverSell": 1000,
            "UnderBuy": 2000,
            "TradingVolume": 0,
        }
        for i in range(1, 11):
            sample_board[f"Sell{i}"] = {"Price": 8000 + i * 10, "Qty": 200}
            sample_board[f"Buy{i}"]  = {"Price": 8000 - i * 10, "Qty": 200}

        recorder = KabuPushRecorder(db_path=tmp_db, interval=0.01)
        recorder.init_db()

        call_count = [0]
        original_record = recorder.record_snapshot

        def mock_record(symbol, exchange=1):
            call_count[0] += 1
            rowid = save_snapshot(tmp_db, {**sample_board, "_recorded_at": datetime.now().isoformat()})
            if call_count[0] >= 2:
                raise SystemExit(0)
            return rowid

        with patch.object(recorder, "record_snapshot", side_effect=mock_record):
            with pytest.raises(SystemExit):
                recorder.run_polling(["9984"], check_time_window=False)

        with sqlite3.connect(tmp_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM quotes_snapshot").fetchone()[0]
        assert count >= 1

    def test_record_snapshot_api_error_propagates(self, tmp_db):
        """API エラーが KabuAPIError として伝播すること"""
        recorder = KabuPushRecorder(db_path=tmp_db)

        with patch.object(recorder._client, "get_board", side_effect=KabuAPIError("接続失敗")):
            with pytest.raises(KabuAPIError):
                recorder.record_snapshot("7203")
