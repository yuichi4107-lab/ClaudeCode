"""
SaxoClient 単体テスト

モックを使って外部 API に依存せずテストする。
実際の Saxo API トークンは不要。
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Any, Dict

# テスト対象のモジュールをインポート
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.trading.saxo_client import SaxoClient, SaxoAPIError, SaxoAuthError, SaxoRateLimitError


# ─── フィクスチャ ───

@pytest.fixture
def mock_client(monkeypatch):
    """
    実際の API 呼び出しをしない SaxoClient インスタンスを返す。
    環境変数をモックして ValueError を回避する。
    """
    monkeypatch.setenv("SAXO_SIM_TOKEN", "test_token_1234567890")
    monkeypatch.setenv("SAXO_SIM_ACCOUNT_KEY", "test_account_key_abc")
    monkeypatch.setenv("SAXO_SIM_ACCOUNT_ID", "test_account_id_xyz")
    monkeypatch.setenv("SAXO_SIM_DEFAULT_CURRENCY", "EUR")

    with patch("httpx.Client") as mock_httpx:
        mock_httpx.return_value = MagicMock()
        client = SaxoClient("saxo_sim")
    return client


# ─── テストケース 1: _get_uic — USDJPY → 42 ───

class TestGetUic:
    def test_known_uic_usdjpy(self, mock_client):
        """USDJPY は既知の UIC キャッシュから 42 が返ること"""
        uic = mock_client._get_uic("USD/JPY")
        assert uic == 42, f"USDJPY の UIC は 42 のはず、実際: {uic}"

    def test_known_uic_eurjpy(self, mock_client):
        """EURJPY は既知の UIC キャッシュから 18 が返ること"""
        uic = mock_client._get_uic("EUR/JPY")
        assert uic == 18, f"EURJPY の UIC は 18 のはず、実際: {uic}"

    def test_uic_with_dash_symbol(self, mock_client):
        """USD-JPY 表記でも 42 が返ること"""
        uic = mock_client._get_uic("USD-JPY")
        assert uic == 42

    def test_unknown_symbol_calls_api(self, mock_client):
        """未知のシンボルは API 検索を呼び出すこと"""
        mock_client._request = MagicMock(return_value={
            "Data": [{"Identifier": 999, "Symbol": "GBPJPY"}]
        })
        uic = mock_client._get_uic("GBP/JPY")
        assert uic == 999
        mock_client._request.assert_called_once()

    def test_unknown_symbol_not_found_raises(self, mock_client):
        """API 検索でシンボルが見つからない場合に SaxoAPIError を送出すること"""
        mock_client._request = MagicMock(return_value={"Data": []})
        with pytest.raises(SaxoAPIError):
            mock_client._get_uic("XYZ/JPY")


# ─── テストケース 2: get_balance — CashBalance が含まれること ───

class TestGetBalance:
    def test_balance_contains_cash_balance(self, mock_client):
        """get_balance の返却辞書に CashBalance が含まれること"""
        mock_response = {
            "CashBalance": 1000000.0,
            "MarginAvailable": 1000000.0,
            "TotalValue": 1000000.0,
            "Currency": "EUR",
            "OpenPositionsCount": 0,
        }
        mock_client._request = MagicMock(return_value=mock_response)

        balance = mock_client.get_balance()

        assert "CashBalance" in balance, "CashBalance キーが存在すること"
        assert balance["CashBalance"] == 1000000.0

    def test_balance_has_exchange_client_keys(self, mock_client):
        """ExchangeClient 互換の free/used/total キーが存在すること"""
        mock_response = {
            "CashBalance": 500000.0,
            "MarginAvailable": 400000.0,
            "TotalValue": 600000.0,
            "Currency": "EUR",
            "OpenPositionsCount": 2,
        }
        mock_client._request = MagicMock(return_value=mock_response)

        balance = mock_client.get_balance()

        assert "free" in balance
        assert "used" in balance
        assert "total" in balance
        assert balance["free"] == 400000.0
        assert balance["total"] == 600000.0

    def test_balance_currency(self, mock_client):
        """Currency フィールドが返却されること"""
        mock_client._request = MagicMock(return_value={
            "CashBalance": 100.0,
            "MarginAvailable": 100.0,
            "TotalValue": 100.0,
            "Currency": "EUR",
            "OpenPositionsCount": 0,
        })
        balance = mock_client.get_balance()
        assert balance["Currency"] == "EUR"


# ─── テストケース 3: get_ticker — bid/ask が取得できること ───

class TestGetTicker:
    def test_ticker_has_bid_and_ask(self, mock_client):
        """get_ticker の返却辞書に bid と ask が含まれること"""
        mock_client._request = MagicMock(return_value={
            "Quote": {
                "Bid": 159.248,
                "Ask": 159.354,
                "Mid": 159.301,
                "MarketState": "Closed",
            },
            "Uic": 42,
        })

        ticker = mock_client.get_ticker("USD/JPY")

        assert ticker["bid"] == 159.248
        assert ticker["ask"] == 159.354
        assert ticker["last"] == 159.301

    def test_ticker_symbol_fields(self, mock_client):
        """symbol と exchange_symbol が正しく設定されること"""
        mock_client._request = MagicMock(return_value={
            "Quote": {"Bid": 159.0, "Ask": 159.1, "Mid": 159.05, "MarketState": "Open"},
            "Uic": 42,
        })

        ticker = mock_client.get_ticker("USD/JPY")

        assert ticker["symbol"] == "USD/JPY"
        assert ticker["exchange_symbol"] == "USDJPY"

    def test_ticker_spread_calculated(self, mock_client):
        """スプレッドが正しく計算されること"""
        mock_client._request = MagicMock(return_value={
            "Quote": {"Bid": 159.000, "Ask": 159.100, "Mid": 159.050, "MarketState": "Open"},
            "Uic": 42,
        })

        ticker = mock_client.get_ticker("USD/JPY")

        assert ticker["spread"] is not None
        assert abs(ticker["spread"] - 0.1) < 0.001


# ─── テストケース 4: fetch_ohlcv — 指定本数の OHLCV が返ること ───

class TestFetchOhlcv:
    def _make_candle(self, i: int) -> Dict[str, Any]:
        """テスト用ローソク足データを生成"""
        return {
            "OpenBid": 159.0 + i * 0.1,
            "HighBid": 160.0 + i * 0.1,
            "LowBid": 158.0 + i * 0.1,
            "CloseBid": 159.5 + i * 0.1,
            "OpenAsk": 159.1 + i * 0.1,
            "HighAsk": 160.1 + i * 0.1,
            "LowAsk": 158.1 + i * 0.1,
            "CloseAsk": 159.6 + i * 0.1,
            "Time": f"2026-03-{i+1:02d}T00:00:00.000000Z",
        }

    def test_ohlcv_returns_correct_count(self, mock_client):
        """指定本数のローソク足が返ること"""
        n = 30
        mock_client._request = MagicMock(return_value={
            "Data": [self._make_candle(i) for i in range(n)]
        })

        ohlcv = mock_client.fetch_ohlcv("USD/JPY", timeframe="1d", limit=n)

        assert len(ohlcv) == n, f"取得本数は {n} 本のはず、実際: {len(ohlcv)}"

    def test_ohlcv_candle_has_required_fields(self, mock_client):
        """各ローソク足に必須フィールドが存在すること"""
        mock_client._request = MagicMock(return_value={
            "Data": [self._make_candle(0)]
        })

        ohlcv = mock_client.fetch_ohlcv("USD/JPY")

        assert len(ohlcv) == 1
        candle = ohlcv[0]
        for field in ("timestamp", "datetime", "open", "high", "low", "close", "volume"):
            assert field in candle, f"フィールド '{field}' が存在すること"

    def test_ohlcv_mid_price_calculation(self, mock_client):
        """Mid 価格が Bid/Ask の平均として計算されること"""
        mock_client._request = MagicMock(return_value={
            "Data": [{
                "OpenBid": 159.0, "OpenAsk": 159.1,
                "HighBid": 160.0, "HighAsk": 160.2,
                "LowBid": 158.0, "LowAsk": 158.2,
                "CloseBid": 159.5, "CloseAsk": 159.7,
                "Time": "2026-03-01T00:00:00.000000Z",
            }]
        })

        ohlcv = mock_client.fetch_ohlcv("USD/JPY", timeframe="1d", limit=1)
        candle = ohlcv[0]

        assert abs(candle["open"] - 159.05) < 0.001  # (159.0 + 159.1) / 2
        assert abs(candle["close"] - 159.6) < 0.001  # (159.5 + 159.7) / 2

    def test_ohlcv_timeframe_mapping(self, mock_client):
        """タイムフレームが Horizon パラメータに正しく変換されること"""
        mock_client._request = MagicMock(return_value={"Data": []})

        mock_client.fetch_ohlcv("USD/JPY", timeframe="1h", limit=10)

        call_args = mock_client._request.call_args
        params = call_args[1].get("params") or call_args[0][2] if len(call_args[0]) > 2 else {}
        # kwargs経由またはpositional引数からparamsを取得
        if hasattr(call_args, 'kwargs'):
            params = call_args.kwargs.get("params", {})
        else:
            params = call_args[1].get("params", {}) if call_args[1] else {}

        assert params.get("Horizon") == 60, f"1h → Horizon=60 のはず、実際: {params}"


# ─── テストケース 5: _request — 401 でカスタム例外発生 ───

class TestRequestErrors:
    def test_401_raises_saxo_auth_error(self, mock_client, monkeypatch):
        """HTTP 401 で SaxoAuthError が送出されること"""
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = '{"ErrorCode": "InvalidToken"}'
        mock_response.content = b'{"ErrorCode": "InvalidToken"}'

        mock_client._client.request = MagicMock(return_value=mock_response)

        with pytest.raises(SaxoAuthError) as exc_info:
            mock_client._request("GET", "/port/v1/balances/me")

        assert exc_info.value.status_code == 401

    def test_500_raises_saxo_api_error(self, mock_client):
        """HTTP 500 で SaxoAPIError が送出されること"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = '{"Message": "Internal Server Error"}'
        mock_response.content = b'{"Message": "Internal Server Error"}'

        mock_client._client.request = MagicMock(return_value=mock_response)

        with pytest.raises(SaxoAPIError) as exc_info:
            mock_client._request("GET", "/port/v1/balances/me")

        assert exc_info.value.status_code == 500

    def test_404_raises_saxo_api_error(self, mock_client):
        """HTTP 404 で SaxoAPIError が送出されること"""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.text = '{"Message": "Not Found"}'
        mock_response.content = b'{"Message": "Not Found"}'

        mock_client._client.request = MagicMock(return_value=mock_response)

        with pytest.raises(SaxoAPIError) as exc_info:
            mock_client._request("GET", "/port/v1/nonexistent")

        assert exc_info.value.status_code == 404

    def test_429_retries_and_raises(self, mock_client):
        """HTTP 429 でリトライ後に SaxoRateLimitError または SaxoAPIError が送出されること"""
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = '{"Message": "Rate Limit"}'
        mock_response.content = b'{"Message": "Rate Limit"}'
        mock_response.headers = {"Retry-After": "0.01"}

        mock_client._client.request = MagicMock(return_value=mock_response)

        with pytest.raises(SaxoAPIError):
            mock_client._request("GET", "/port/v1/balances/me")


# ─── テストケース 6: シンボル変換 ───

class TestSymbolConversion:
    def test_to_saxo_symbol_slash(self, mock_client):
        """USD/JPY → USDJPY"""
        assert mock_client.to_saxo_symbol("USD/JPY") == "USDJPY"

    def test_to_saxo_symbol_dash(self, mock_client):
        """USD-JPY → USDJPY"""
        assert mock_client.to_saxo_symbol("USD-JPY") == "USDJPY"

    def test_from_saxo_symbol(self, mock_client):
        """USDJPY → USD/JPY"""
        assert mock_client.from_saxo_symbol("USDJPY") == "USD/JPY"

    def test_is_symbol_supported_fx(self, mock_client):
        """FX ペアは True"""
        assert mock_client.is_symbol_supported("USD/JPY") is True
        assert mock_client.is_symbol_supported("EUR/JPY") is True

    def test_is_symbol_supported_non_fx(self, mock_client):
        """非 FX ペア（スラッシュなし、4+3 等）は False になること"""
        # is_symbol_supported は 3+3 文字構成チェックのみ行う（OANDA 実装と同仕様）
        # 4 文字以上のベース通貨は False
        assert mock_client.is_symbol_supported("USDT/JPY") is False  # USDT は 4 文字
        assert mock_client.is_symbol_supported("BTCJPY") is False    # スラッシュなし
        assert mock_client.is_symbol_supported("BTC") is False       # ペアでない


# ─── テストケース 7: 初期化エラー ───

class TestInitialization:
    def test_unknown_exchange_id_raises(self):
        """不明な exchange_id で ValueError が送出されること"""
        with pytest.raises(ValueError, match="Unknown Saxo config"):
            SaxoClient("unknown_exchange")

    def test_missing_token_raises(self, monkeypatch):
        """Token 未設定で ValueError が送出されること"""
        monkeypatch.delenv("SAXO_SIM_TOKEN", raising=False)
        monkeypatch.setenv("SAXO_SIM_ACCOUNT_KEY", "test_key")

        with patch("httpx.Client"):
            with pytest.raises(ValueError, match="token"):
                SaxoClient("saxo_sim")

    def test_missing_account_key_raises(self, monkeypatch):
        """Account Key 未設定で ValueError が送出されること"""
        monkeypatch.setenv("SAXO_SIM_TOKEN", "test_token_1234567890")
        monkeypatch.delenv("SAXO_SIM_ACCOUNT_KEY", raising=False)

        with patch("httpx.Client"):
            with pytest.raises(ValueError, match="account key"):
                SaxoClient("saxo_sim")


# ─── テストケース 8: 注文フォーマット ───

class TestOrderFormatting:
    def test_market_buy_response_format(self, mock_client):
        """market_buy のレスポンスに必須フィールドが存在すること"""
        mock_client._request = MagicMock(return_value={"OrderId": "12345"})

        result = mock_client.market_buy("USD/JPY", amount=1000)

        assert "id" in result
        assert result["id"] == "12345"
        assert result["side"] == "buy"
        assert result["symbol"] == "USD/JPY"
        assert result["amount"] == 1000

    def test_market_sell_response_format(self, mock_client):
        """market_sell のレスポンスに必須フィールドが存在すること"""
        mock_client._request = MagicMock(return_value={"OrderId": "67890"})

        result = mock_client.market_sell("USD/JPY", amount=1000)

        assert result["id"] == "67890"
        assert result["side"] == "sell"

    def test_cancel_order_response(self, mock_client):
        """cancel_order のレスポンスに id と status が含まれること"""
        mock_client._request = MagicMock(return_value={})

        result = mock_client.cancel_order("99999", "USD/JPY")

        assert result["id"] == "99999"
        assert result["status"] == "cancelled"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
