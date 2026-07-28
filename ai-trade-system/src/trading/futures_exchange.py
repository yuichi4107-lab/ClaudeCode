"""
Binance USD-M Futures 取引所インターフェース

ccxt の binanceusdm 経由で Binance Futures API を操作する。
ショート戦略専用。レバ1倍・アイソレーテッドマージン固定。
テストネット / 本番を透過的に切り替え可能。
"""
import os
import ccxt
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))


class FuturesExchangeClient:
    """Binance USD-M Futures 取引所クライアント（ccxt binanceusdm ラッパー）

    ショート戦略用。レバ1倍・アイソレーテッドマージン固定。
    """

    EXCHANGE_CONFIGS = {
        "binance_futures_testnet": {
            "class": "binanceusdm",
            "sandbox": True,
            "api_key_env": "BINANCE_FUTURES_TESTNET_API_KEY",
            "secret_env": "BINANCE_FUTURES_TESTNET_SECRET",
            "quote_currency": "USDT",
        },
        "binance_futures": {
            "class": "binanceusdm",
            "sandbox": False,
            "api_key_env": "BINANCE_FUTURES_API_KEY",
            "secret_env": "BINANCE_FUTURES_SECRET",
            "quote_currency": "USDT",
        },
    }

    def __init__(self, exchange_id="binance_futures_testnet"):
        """
        Args:
            exchange_id: "binance_futures_testnet", "binance_futures"
        """
        if exchange_id not in self.EXCHANGE_CONFIGS:
            raise ValueError(
                f"Unknown exchange: {exchange_id}. Available: {list(self.EXCHANGE_CONFIGS.keys())}"
            )

        config = self.EXCHANGE_CONFIGS[exchange_id]
        self.exchange_id = exchange_id
        self.is_sandbox = config["sandbox"]
        self.quote_currency = config["quote_currency"]

        exchange_class = getattr(ccxt, config["class"])

        api_key = os.getenv(config["api_key_env"], "")
        secret = os.getenv(config["secret_env"], "")

        self.exchange = exchange_class({
            "apiKey": api_key,
            "secret": secret,
            "enableRateLimit": True,
            "options": {
                "adjustForTimeDifference": True,
                "recvWindow": 60000,
            },
        })

        if self.is_sandbox:
            self.exchange.set_sandbox_mode(True)

        self.label = f"{exchange_id}{'(sandbox)' if self.is_sandbox else ''}"

    def convert_symbol(self, symbol):
        """
        strategy_config のシンボル（BTC/USDT等）を Futures パーペチュアル形式に変換する。

        例: BTC/USDT → BTC/USDT:USDT (ccxt perpetual swap 記法)
        """
        base = symbol.split("/")[0]
        return f"{base}/{self.quote_currency}:{self.quote_currency}"

    def set_leverage(self, symbol, leverage=1):
        """レバレッジを設定する。デフォルト1倍。

        Args:
            symbol: 通貨ペア (例: "BTC/USDT")
            leverage: レバレッジ倍率（デフォルト 1）
        """
        ex_symbol = self.convert_symbol(symbol)
        self.exchange.set_leverage(leverage, ex_symbol)

    def set_margin_type(self, symbol, margin_type="ISOLATED"):
        """マージンタイプを設定する。デフォルト ISOLATED。

        既に設定済みの場合の例外（"No need to change"）は無視する。

        Args:
            symbol: 通貨ペア (例: "BTC/USDT")
            margin_type: "ISOLATED" または "CROSSED"
        """
        ex_symbol = self.convert_symbol(symbol)
        try:
            self.exchange.set_margin_mode(margin_type.lower(), ex_symbol)
        except ccxt.ExchangeError as e:
            if "No need to change" in str(e):
                pass  # 既に設定済み — 無視
            else:
                raise

    def open_short(self, symbol, amount):
        """空売り建玉を開く（成行）。

        エントリー前にレバ1倍・アイソレーテッドを設定する。

        Args:
            symbol: 通貨ペア (例: "BTC/USDT")
            amount: 数量（基軸通貨単位）
        Returns:
            dict: 統一フォーマットの注文結果
        """
        self.set_leverage(symbol, 1)
        self.set_margin_type(symbol, "ISOLATED")

        ex_symbol = self.convert_symbol(symbol)
        order = self.exchange.create_market_sell_order(
            ex_symbol, amount, params={"reduceOnly": False}
        )
        return self._format_order(order, original_symbol=symbol)

    def close_short(self, symbol, amount):
        """空売り建玉を決済する（成行 reduceOnly）。

        Args:
            symbol: 通貨ペア (例: "BTC/USDT")
            amount: 数量（基軸通貨単位）
        Returns:
            dict: 統一フォーマットの注文結果
        """
        ex_symbol = self.convert_symbol(symbol)
        order = self.exchange.create_market_buy_order(
            ex_symbol, amount, params={"reduceOnly": True}
        )
        return self._format_order(order, original_symbol=symbol)

    def get_futures_balance(self):
        """Futures ウォレットの USDT 残高を取得する。

        Returns:
            dict: {"free": float, "used": float, "total": float, "positions": list}
                  positions は取得できなければ省略。
        Raises:
            RuntimeError: 残高取得に失敗した場合。
        """
        try:
            balance = self.exchange.fetch_balance()
        except Exception as e:
            raise RuntimeError(f"Futures 残高の取得に失敗しました: {e}") from e

        currency = self.quote_currency
        result = {
            "free": balance.get("free", {}).get(currency, 0),
            "used": balance.get("used", {}).get(currency, 0),
            "total": balance.get("total", {}).get(currency, 0),
        }

        # positions 情報が含まれていれば追加
        if "info" in balance and isinstance(balance["info"], dict):
            positions = balance["info"].get("positions")
            if positions is not None:
                result["positions"] = positions

        return result

    def get_position(self, symbol):
        """指定シンボルの現在建玉を取得する。

        Args:
            symbol: 通貨ペア (例: "BTC/USDT")
        Returns:
            dict: {"symbol", "contracts", "side", "unrealized_pnl", "entry_price"}
                  または None（建玉なし）
        """
        ex_symbol = self.convert_symbol(symbol)
        positions = self.exchange.fetch_positions([ex_symbol])

        for pos in positions:
            contracts = pos.get("contracts", 0) or 0
            if contracts == 0:
                continue

            side_raw = pos.get("side")
            if side_raw == "short":
                side = "short"
            elif side_raw == "long":
                side = "long"
            else:
                side = None

            return {
                "symbol": symbol,
                "contracts": contracts,
                "side": side,
                "unrealized_pnl": pos.get("unrealizedPnl"),
                "entry_price": pos.get("entryPrice"),
            }

        return None  # 建玉なし

    def get_ticker(self, symbol):
        """現在価格を取得する。シンボルは自動変換。

        Args:
            symbol: 通貨ペア (例: "BTC/USDT")
        Returns:
            dict: {"symbol", "exchange_symbol", "last", "bid", "ask", "timestamp"}
        """
        ex_symbol = self.convert_symbol(symbol)
        ticker = self.exchange.fetch_ticker(ex_symbol)
        return {
            "symbol": symbol,
            "exchange_symbol": ex_symbol,
            "last": ticker["last"],
            "bid": ticker["bid"],
            "ask": ticker["ask"],
            "timestamp": ticker["timestamp"],
        }

    def _format_order(self, order, original_symbol=None):
        """注文データを統一フォーマットに変換"""
        return {
            "id": order.get("id"),
            "symbol": original_symbol or order.get("symbol"),
            "exchange_symbol": order.get("symbol"),
            "type": order.get("type"),
            "side": order.get("side"),
            "amount": order.get("amount"),
            "price": order.get("price"),
            "average": order.get("average"),
            "filled": order.get("filled"),
            "remaining": order.get("remaining"),
            "status": order.get("status"),
            "timestamp": order.get("timestamp"),
            "cost": order.get("cost"),
        }

    def __repr__(self):
        return f"FuturesExchangeClient({self.label}, quote={self.quote_currency})"
