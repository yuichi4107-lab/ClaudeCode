"""
OANDAアダプター

OANDA REST API v20を直接呼び出し、ExchangeClientと同じインターフェースを提供する。
FX通貨ペアの売買を既存のAutoTraderから透過的に利用可能にする。

ccxtはOANDA非対応のため、httpxで直接REST呼び出しを行う。
（oandapyV20は2021年以降メンテ停止・Python 3.12非対応のため不採用）
"""
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))


class OandaClient:
    """OANDA REST API v20 クライアント（ExchangeClient互換インターフェース）"""

    CONFIGS = {
        "oanda_demo": {
            "base_url": "https://api-fxpractice.oanda.com",
            "token_env": "OANDA_DEMO_TOKEN",
            "account_env": "OANDA_DEMO_ACCOUNT_ID",
            "quote_currency": "JPY",
            "sandbox": True,
        },
        "oanda": {
            "base_url": "https://api-fxtrade.oanda.com",
            "token_env": "OANDA_TOKEN",
            "account_env": "OANDA_ACCOUNT_ID",
            "quote_currency": "JPY",
            "sandbox": False,
        },
    }

    # granularity マッピング（既存timeframe → OANDA形式）
    TIMEFRAME_MAP = {
        "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
        "1h": "H1", "4h": "H4", "1d": "D", "1w": "W", "1M": "M",
    }

    # レート制限: 最低間隔（秒）
    MIN_REQUEST_INTERVAL = 0.1  # 10 req/s（保守的）

    def __init__(self, exchange_id="oanda_demo"):
        if exchange_id not in self.CONFIGS:
            raise ValueError(f"Unknown OANDA config: {exchange_id}. Available: {list(self.CONFIGS.keys())}")

        config = self.CONFIGS[exchange_id]
        self.exchange_id = exchange_id
        self.is_sandbox = config["sandbox"]
        self.quote_currency = config["quote_currency"]
        self.base_url = config["base_url"]

        self.token = os.getenv(config["token_env"], "")
        self.account_id = os.getenv(config["account_env"], "")

        if not self.token:
            raise ValueError(f"OANDA token not set: {config['token_env']}")
        if not self.account_id:
            raise ValueError(f"OANDA account ID not set: {config['account_env']}")

        self.client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept-Datetime-Format": "UNIX",
            },
            timeout=30.0,
        )

        self._last_request_time = 0
        self.label = f"{exchange_id}{'(demo)' if self.is_sandbox else ''}"

    # ─── レート制限 ───

    def _throttle(self):
        """レート制限のための簡易スロットリング"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    def _request(self, method, path, **kwargs):
        """API リクエスト共通処理"""
        self._throttle()
        resp = self.client.request(method, path, **kwargs)
        resp.raise_for_status()
        return resp.json()

    # ─── シンボル変換 ───

    @staticmethod
    def to_oanda_symbol(symbol):
        """'USD/JPY' or 'USD-JPY' → 'USD_JPY'"""
        return symbol.replace("/", "_").replace("-", "_")

    @staticmethod
    def from_oanda_symbol(oanda_symbol):
        """'USD_JPY' → 'USD/JPY'"""
        return oanda_symbol.replace("_", "/")

    def is_symbol_supported(self, symbol):
        """FX通貨ペアかどうか（暗号資産シンボルはFalse）"""
        parts = symbol.replace("-", "/").split("/")
        if len(parts) != 2:
            return False
        # FXペアは3文字+3文字（例: USD/JPY, EUR/USD）
        return len(parts[0]) == 3 and len(parts[1]) == 3

    def convert_symbol(self, symbol):
        """ExchangeClient互換: シンボル変換（FXはそのまま返す）"""
        return symbol

    # ─── アカウント・残高 ───

    def get_balance(self, currency=None):
        """残高を取得する（ExchangeClient互換）"""
        data = self._request("GET", f"/v3/accounts/{self.account_id}/summary")
        account = data["account"]
        balance = float(account["balance"])
        unrealized_pl = float(account["unrealizedPL"])
        margin_used = float(account["marginUsed"])
        nav = float(account["NAV"])

        return {
            "free": nav - margin_used,   # 利用可能証拠金
            "used": margin_used,          # 使用中証拠金
            "total": nav,                 # 純資産
            "balance": balance,           # 残高（確定分）
            "unrealized_pl": unrealized_pl,
            "margin_available": float(account.get("marginAvailable", 0)),
        }

    # ─── 現在価格 ───

    def get_ticker(self, symbol):
        """現在価格を取得する（ExchangeClient互換）"""
        oanda_sym = self.to_oanda_symbol(symbol)
        data = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/pricing",
            params={"instruments": oanda_sym},
        )
        price = data["prices"][0]

        best_bid = float(price["bids"][0]["price"]) if price.get("bids") else None
        best_ask = float(price["asks"][0]["price"]) if price.get("asks") else None
        mid = (best_bid + best_ask) / 2 if best_bid and best_ask else None

        return {
            "symbol": symbol,
            "exchange_symbol": oanda_sym,
            "last": mid,
            "bid": best_bid,
            "ask": best_ask,
            "spread": best_ask - best_bid if best_bid and best_ask else None,
            "timestamp": int(float(price.get("time", 0)) * 1000),
        }

    # ─── OHLCV ───

    def fetch_ohlcv(self, symbol, timeframe="1d", limit=60):
        """OHLCVデータを取得する（ExchangeClient互換）"""
        oanda_sym = self.to_oanda_symbol(symbol)
        granularity = self.TIMEFRAME_MAP.get(timeframe, "D")

        data = self._request(
            "GET",
            f"/v3/instruments/{oanda_sym}/candles",
            params={
                "granularity": granularity,
                "count": min(limit, 5000),
                "price": "M",  # Mid price
            },
        )

        candles = []
        for c in data.get("candles", []):
            if not c.get("complete", False):
                continue  # 未確定のローソク足はスキップ
            mid = c["mid"]
            ts = int(float(c["time"]) * 1000)
            candles.append({
                "timestamp": ts,
                "datetime": datetime.fromtimestamp(
                    float(c["time"]), tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S"),
                "open": float(mid["o"]),
                "high": float(mid["h"]),
                "low": float(mid["l"]),
                "close": float(mid["c"]),
                "volume": c.get("volume", 0),
            })
        return candles

    # ─── 注文 ───

    def market_buy(self, symbol, amount, quote_amount=None):
        """
        成行買い注文（ExchangeClient互換）

        FXではunits（通貨単位数）で注文する。
        quote_amount（JPY金額）が指定された場合、現在レートから逆算する。
        """
        oanda_sym = self.to_oanda_symbol(symbol)
        units = self._calculate_units(symbol, amount, quote_amount, side="buy")

        data = self._request(
            "POST",
            f"/v3/accounts/{self.account_id}/orders",
            json={
                "order": {
                    "type": "MARKET",
                    "instrument": oanda_sym,
                    "units": str(int(units)),  # 正の値 = 買い
                    "timeInForce": "FOK",
                    "positionFill": "DEFAULT",
                }
            },
        )
        return self._format_order_response(data, symbol, "buy")

    def market_sell(self, symbol, amount):
        """成行売り注文（ExchangeClient互換）"""
        oanda_sym = self.to_oanda_symbol(symbol)

        data = self._request(
            "POST",
            f"/v3/accounts/{self.account_id}/orders",
            json={
                "order": {
                    "type": "MARKET",
                    "instrument": oanda_sym,
                    "units": str(-int(amount)),  # 負の値 = 売り
                    "timeInForce": "FOK",
                    "positionFill": "DEFAULT",
                }
            },
        )
        return self._format_order_response(data, symbol, "sell")

    def stop_loss_order(self, symbol, amount, stop_price):
        """
        ストップロスをトレードに設定する。

        OANDAではSLはTrade単位で設定するため、
        最新のオープントレードにSLを紐づける。
        """
        oanda_sym = self.to_oanda_symbol(symbol)

        # 最新のオープントレードを取得
        trades_data = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/openTrades",
        )
        # 該当銘柄の最新トレードを見つける
        target_trade = None
        for trade in reversed(trades_data.get("trades", [])):
            if trade["instrument"] == oanda_sym:
                target_trade = trade
                break

        if not target_trade:
            return None

        # SLを設定
        pip_precision = self._pip_precision(symbol)
        data = self._request(
            "PUT",
            f"/v3/accounts/{self.account_id}/trades/{target_trade['id']}/orders",
            json={
                "stopLoss": {
                    "price": f"{stop_price:.{pip_precision}f}",
                    "timeInForce": "GTC",
                }
            },
        )
        return {
            "id": target_trade["id"],
            "symbol": symbol,
            "type": "STOP_LOSS",
            "side": "sell",
            "price": stop_price,
            "status": "open",
        }

    def cancel_order(self, order_id, symbol):
        """注文をキャンセルする"""
        return self._request(
            "PUT",
            f"/v3/accounts/{self.account_id}/orders/{order_id}/cancel",
        )

    def fetch_open_orders(self, symbol=None):
        """未約定の注文を取得する"""
        data = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/pendingOrders",
        )
        orders = []
        for o in data.get("orders", []):
            sym = self.from_oanda_symbol(o.get("instrument", ""))
            if symbol and sym != symbol:
                continue
            orders.append(self._format_pending_order(o))
        return orders

    def fetch_order(self, order_id, symbol):
        """注文状態を取得する"""
        data = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/orders/{order_id}",
        )
        return self._format_pending_order(data.get("order", {}), original_symbol=symbol)

    # ─── ポジション（OANDA Trade = 既存のポジション概念） ───

    def get_open_trades(self):
        """オープントレード（ポジション）一覧"""
        data = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/openTrades",
        )
        return data.get("trades", [])

    def close_trade(self, trade_id, units="ALL"):
        """トレードを決済する"""
        return self._request(
            "PUT",
            f"/v3/accounts/{self.account_id}/trades/{trade_id}/close",
            json={"units": str(units)},
        )

    # ─── 内部ユーティリティ ───

    def _calculate_units(self, symbol, amount=None, quote_amount=None, side="buy"):
        """
        注文数量を計算する。

        FXでは units = 通貨単位数。
        quote_amount（JPY金額）が指定された場合、現在レートから逆算する。
        """
        if amount and not quote_amount:
            return amount

        if quote_amount:
            ticker = self.get_ticker(symbol)
            price = ticker["ask"] if side == "buy" else ticker["bid"]
            if price:
                # USD/JPY の場合: units = JPY金額 / 価格（= USD数量）
                # EUR/USD の場合: units = USD金額 * EUR/USD価格 → 別途JPY→USD変換必要
                # 簡易実装: quote通貨がJPYなら直接割り算
                base, quote = symbol.replace("-", "/").split("/")
                if quote == "JPY":
                    return int(quote_amount / price)
                else:
                    # 非JPYクォートの場合（EUR/USDなど）、JPY→クォート通貨変換が必要
                    # 簡易: レバレッジ考慮せず金額をそのまま使う
                    return int(quote_amount / price)

        return amount or 0

    @staticmethod
    def _pip_precision(symbol):
        """pip精度を返す（JPYクロスは3桁、その他は5桁）"""
        if "JPY" in symbol.upper():
            return 3
        return 5

    def _format_order_response(self, data, symbol, side):
        """OANDA注文レスポンスをExchangeClient互換フォーマットに変換"""
        fill = data.get("orderFillTransaction", {})

        trade_opened = fill.get("tradeOpened", {})
        trade_id = trade_opened.get("tradeID") or fill.get("id", "")

        price = float(fill.get("price", 0)) if fill.get("price") else None
        units = abs(int(float(fill.get("units", 0)))) if fill.get("units") else None

        return {
            "id": trade_id,
            "symbol": symbol,
            "exchange_symbol": self.to_oanda_symbol(symbol),
            "type": "market",
            "side": side,
            "amount": units,
            "price": price,
            "average": price,
            "filled": units,
            "remaining": 0,
            "status": "closed",  # 成行は即約定
            "timestamp": int(float(fill.get("time", 0)) * 1000) if fill.get("time") else None,
            "cost": abs(float(fill.get("pl", 0))) if fill.get("pl") else None,
        }

    def _format_pending_order(self, order, original_symbol=None):
        """未約定注文をExchangeClient互換フォーマットに変換"""
        sym = original_symbol or self.from_oanda_symbol(order.get("instrument", ""))
        units = int(float(order.get("units", 0))) if order.get("units") else 0
        return {
            "id": order.get("id"),
            "symbol": sym,
            "exchange_symbol": order.get("instrument"),
            "type": order.get("type", "").lower(),
            "side": "buy" if units > 0 else "sell",
            "amount": abs(units),
            "price": float(order["price"]) if order.get("price") else None,
            "average": None,
            "filled": 0,
            "remaining": abs(units),
            "status": order.get("state", "").lower(),
            "timestamp": int(float(order.get("createTime", 0)) * 1000) if order.get("createTime") else None,
            "cost": None,
        }

    def __repr__(self):
        return f"OandaClient({self.label}, quote={self.quote_currency})"
