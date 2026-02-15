"""OANDA REST API v20 クライアント"""

import time
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

from fx_trader.config import settings

logger = logging.getLogger(__name__)


class OandaClient:
    """OANDA v20 REST API ラッパー"""

    def __init__(self, api_key=None, account_id=None, environment=None):
        self.api_key = api_key or settings.OANDA_API_KEY
        self.account_id = account_id or settings.OANDA_ACCOUNT_ID
        env = environment or settings.OANDA_ENVIRONMENT
        self.base_url = settings.OANDA_BASE_URL[env]
        self._last_request_time = 0.0

        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "RFC3339",
        })

    def _rate_limit(self):
        """レート制限を遵守"""
        elapsed = time.time() - self._last_request_time
        if elapsed < settings.API_RATE_LIMIT_SECONDS:
            time.sleep(settings.API_RATE_LIMIT_SECONDS - elapsed)
        self._last_request_time = time.time()

    def _request(self, method: str, path: str, params=None, data=None, max_retries=3) -> dict:
        """HTTP リクエスト（リトライ付き）"""
        url = f"{self.base_url}{path}"

        for attempt in range(max_retries):
            self._rate_limit()
            try:
                resp = self.session.request(method, url, params=params, json=data, timeout=30)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    wait = 2 ** (attempt + 1)
                    logger.warning("API request failed (attempt %d/%d), retrying in %ds: %s", attempt + 1, max_retries, wait, e)
                    time.sleep(wait)
                else:
                    logger.error("API request failed after %d attempts: %s", max_retries, e)
                    raise

    # --- Account ---

    def get_account_summary(self) -> dict:
        """口座サマリーを取得"""
        result = self._request("GET", f"/v3/accounts/{self.account_id}/summary")
        return result["account"]

    def get_account_balance(self) -> float:
        """口座残高を取得"""
        summary = self.get_account_summary()
        return float(summary["balance"])

    # --- Candles (価格データ) ---

    def get_candles(
        self,
        instrument: str,
        granularity: str = "H1",
        count: Optional[int] = None,
        from_time: Optional[str] = None,
        to_time: Optional[str] = None,
    ) -> list[dict]:
        """ローソク足データを取得

        Args:
            instrument: 通貨ペア (例: "USD_JPY")
            granularity: 足の種類 (例: "H1", "D")
            count: 取得本数 (最大5000)
            from_time: 開始時刻 (RFC3339)
            to_time: 終了時刻 (RFC3339)

        Returns:
            list of dict: [{timestamp, open, high, low, close, volume, complete}, ...]
        """
        params = {"granularity": granularity, "price": "M"}  # Mid price

        if count:
            params["count"] = min(count, settings.API_MAX_CANDLES_PER_REQUEST)
        if from_time:
            params["from"] = from_time
        if to_time:
            params["to"] = to_time

        result = self._request("GET", f"/v3/instruments/{instrument}/candles", params=params)

        candles = []
        for c in result.get("candles", []):
            mid = c["mid"]
            candles.append({
                "instrument": instrument,
                "granularity": granularity,
                "timestamp": c["time"],
                "open": float(mid["o"]),
                "high": float(mid["h"]),
                "low": float(mid["l"]),
                "close": float(mid["c"]),
                "volume": int(c["volume"]),
                "complete": 1 if c["complete"] else 0,
            })
        return candles

    def get_candles_range(
        self,
        instrument: str,
        granularity: str,
        from_time: str,
        to_time: str,
    ) -> list[dict]:
        """期間指定でローソク足を分割取得（5000本制限を回避）"""
        all_candles = []
        current_from = from_time

        while current_from < to_time:
            candles = self.get_candles(
                instrument=instrument,
                granularity=granularity,
                from_time=current_from,
                to_time=to_time,
                count=settings.API_MAX_CANDLES_PER_REQUEST,
            )

            if not candles:
                break

            all_candles.extend(candles)
            current_from = candles[-1]["timestamp"]

            # 同じタイムスタンプが返り続ける場合は中断
            if len(candles) <= 1:
                break

            logger.info("Fetched %d candles for %s (%s), total: %d", len(candles), instrument, granularity, len(all_candles))

        return all_candles

    # --- Pricing ---

    def get_current_price(self, instrument: str) -> dict:
        """現在の価格を取得"""
        result = self._request("GET", f"/v3/accounts/{self.account_id}/pricing", params={"instruments": instrument})
        price = result["prices"][0]
        return {
            "instrument": instrument,
            "time": price["time"],
            "bid": float(price["bids"][0]["price"]),
            "ask": float(price["asks"][0]["price"]),
            "spread": float(price["asks"][0]["price"]) - float(price["bids"][0]["price"]),
        }

    # --- Orders ---

    def create_market_order(
        self,
        instrument: str,
        units: int,
        stop_loss_price: Optional[float] = None,
        take_profit_price: Optional[float] = None,
    ) -> dict:
        """成行注文を発注

        Args:
            instrument: 通貨ペア
            units: 数量（正=買い、負=売り）
            stop_loss_price: 損切り価格
            take_profit_price: 利確価格
        """
        order_data = {
            "order": {
                "type": "MARKET",
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "FOK",
            }
        }

        if stop_loss_price:
            order_data["order"]["stopLossOnFill"] = {"price": f"{stop_loss_price:.5f}"}
        if take_profit_price:
            order_data["order"]["takeProfitOnFill"] = {"price": f"{take_profit_price:.5f}"}

        result = self._request("POST", f"/v3/accounts/{self.account_id}/orders", data=order_data)
        return result

    def close_trade(self, trade_id: str, units: Optional[int] = None) -> dict:
        """取引をクローズ"""
        data = {}
        if units:
            data["units"] = str(abs(units))
        result = self._request("PUT", f"/v3/accounts/{self.account_id}/trades/{trade_id}/close", data=data or None)
        return result

    def get_open_trades(self) -> list[dict]:
        """未決済ポジション一覧を取得"""
        result = self._request("GET", f"/v3/accounts/{self.account_id}/openTrades")
        return result.get("trades", [])

    def modify_trade(self, trade_id: str, stop_loss: Optional[float] = None, take_profit: Optional[float] = None) -> dict:
        """取引のSL/TPを変更"""
        data = {}
        if stop_loss is not None:
            data["stopLoss"] = {"price": f"{stop_loss:.5f}"}
        if take_profit is not None:
            data["takeProfit"] = {"price": f"{take_profit:.5f}"}
        return self._request("PUT", f"/v3/accounts/{self.account_id}/trades/{trade_id}/orders", data=data)
