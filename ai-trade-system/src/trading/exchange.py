"""
取引所インターフェース

ccxt経由で取引所APIを操作する。
Binanceテストネット / Coincheck本番を透過的に切り替え可能。
通貨ペアの変換（USDT↔JPY）を自動で行う。
"""
import os
import ccxt
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))


class ExchangeClient:
    """取引所クライアント（ccxtラッパー）"""

    EXCHANGE_CONFIGS = {
        "binance_testnet": {
            "class": "binance",
            "sandbox": True,
            "api_key_env": "BINANCE_TESTNET_API_KEY",
            "secret_env": "BINANCE_TESTNET_SECRET",
            "quote_currency": "USDT",
        },
        "binance": {
            "class": "binance",
            "sandbox": False,
            "api_key_env": "BINANCE_API_KEY",
            "secret_env": "BINANCE_SECRET",
            "quote_currency": "USDT",
        },
        "coincheck": {
            "class": "coincheck",
            "sandbox": False,
            "api_key_env": "COINCHECK_API_KEY",
            "secret_env": "COINCHECK_SECRET",
            "quote_currency": "JPY",
            "supported_base_currencies": ["BTC"],  # ccxt経由ではBTC/JPYのみ対応
        },
    }

    def __init__(self, exchange_id="binance_testnet"):
        """
        Args:
            exchange_id: "binance_testnet", "binance", "coincheck"
        """
        if exchange_id not in self.EXCHANGE_CONFIGS:
            raise ValueError(f"Unknown exchange: {exchange_id}. Available: {list(self.EXCHANGE_CONFIGS.keys())}")

        config = self.EXCHANGE_CONFIGS[exchange_id]
        self.exchange_id = exchange_id
        self.is_sandbox = config["sandbox"]
        self.quote_currency = config["quote_currency"]
        self.supported_base_currencies = config.get("supported_base_currencies", None)

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

    def is_symbol_supported(self, symbol):
        """通貨ペアがこの取引所でサポートされているか確認する"""
        if self.supported_base_currencies is None:
            return True
        base = symbol.split("/")[0]
        return base in self.supported_base_currencies

    def convert_symbol(self, symbol):
        """
        strategy_config のシンボル（BTC/USDT等）を取引所のシンボルに変換する。

        例: BTC/USDT → BTC/JPY (Coincheck)
            BTC/USDT → BTC/USDT (Binance)
        """
        base = symbol.split("/")[0]
        return f"{base}/{self.quote_currency}"

    def get_balance(self, currency=None):
        """残高を取得する。currency省略時はquote_currency。"""
        if currency is None:
            currency = self.quote_currency
        balance = self.exchange.fetch_balance()
        free = balance.get("free", {}).get(currency, 0)
        used = balance.get("used", {}).get(currency, 0)
        total = balance.get("total", {}).get(currency, 0)
        return {"free": free, "used": used, "total": total}

    def get_ticker(self, symbol):
        """現在価格を取得する。シンボルは自動変換。"""
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

    def fetch_base_balance(self, symbol):
        """
        基軸通貨（BTC等）の実残高を取得する。

        案A: 買付後の実BTC残高確認に使用。
        案B: 売却前の安全網として実残高確認に使用。

        Args:
            symbol: 通貨ペア (例: "BTC/USDT") — 基軸通貨を自動抽出
        Returns:
            float: freeな基軸通貨残高。取得失敗時は None を返す
        """
        base = symbol.split("/")[0]
        try:
            balance = self.exchange.fetch_balance()
            free = balance.get("free", {}).get(base, 0) or 0
            return float(free)
        except Exception as e:
            print(f"    [fetch_base_balance] Failed to fetch {base} balance: {e}")
            return None

    def market_buy(self, symbol, amount, quote_amount=None):
        """
        成行買い注文

        Args:
            symbol: 通貨ペア (例: "BTC/USDT" — 自動変換される)
            amount: 購入数量（基軸通貨単位）
            quote_amount: 購入金額（建て通貨単位）。Coincheckでは必須（JPY金額指定）
        Returns:
            dict: 注文結果
        """
        ex_symbol = self.convert_symbol(symbol)
        if self.exchange_id == "coincheck":
            # Coincheckは金額指定（JPY）で注文する仕様
            buy_jpy = quote_amount if quote_amount is not None else 5000
            order = self.exchange.create_order(
                ex_symbol, "market", "buy", None, None,
                params={"market_buy_amount": buy_jpy}
            )
        else:
            order = self.exchange.create_market_buy_order(ex_symbol, amount)
        return self._format_order(order, original_symbol=symbol)

    def market_sell(self, symbol, amount):
        """成行売り注文"""
        ex_symbol = self.convert_symbol(symbol)
        order = self.exchange.create_market_sell_order(ex_symbol, amount)
        return self._format_order(order, original_symbol=symbol)

    def stop_loss_order(self, symbol, amount, stop_price):
        """
        逆指値（ストップロス）注文

        取引所によって対応が異なるため、複数の方法でフォールバック。
        Coincheckは逆指値非対応（通常の指値売りとして即約定するリスクあり）のため
        常に自前監視にフォールバックする。
        """
        # Coincheckは逆指値注文を正しくサポートしていないため、
        # 取引所SLは使わず自前監視（_manage_positions）で対応する
        if self.exchange_id == "coincheck":
            return None

        ex_symbol = self.convert_symbol(symbol)
        limit_price = stop_price * 0.995

        methods = [
            # Binance Spot: STOP_LOSS_LIMIT
            lambda: self.exchange.create_order(
                symbol=ex_symbol, type="STOP_LOSS_LIMIT", side="sell",
                amount=amount, price=limit_price,
                params={"stopPrice": stop_price, "timeInForce": "GTC"},
            ),
            # 汎用: stop_limit
            lambda: self.exchange.create_order(
                symbol=ex_symbol, type="stop_limit", side="sell",
                amount=amount, price=limit_price,
                params={"stopPrice": stop_price},
            ),
        ]

        for method in methods:
            try:
                order = method()
                return self._format_order(order, original_symbol=symbol)
            except (ccxt.NotSupported, ccxt.InvalidOrder, ccxt.BadRequest):
                continue
            except Exception:
                continue

        # 全て失敗 → 自前監視にフォールバック
        return None

    def cancel_order(self, order_id, symbol):
        """注文をキャンセルする"""
        ex_symbol = self.convert_symbol(symbol)
        return self.exchange.cancel_order(order_id, ex_symbol)

    def fetch_open_orders(self, symbol=None):
        """未約定の注文を取得する"""
        ex_symbol = self.convert_symbol(symbol) if symbol else None
        orders = self.exchange.fetch_open_orders(ex_symbol)
        return [self._format_order(o) for o in orders]

    def fetch_order(self, order_id, symbol):
        """注文状態を取得する"""
        ex_symbol = self.convert_symbol(symbol)
        order = self.exchange.fetch_order(order_id, ex_symbol)
        return self._format_order(order, original_symbol=symbol)

    def fetch_ohlcv(self, symbol, timeframe="1d", limit=60):
        """OHLCVデータを取得する（シグナル判定用）"""
        ex_symbol = self.convert_symbol(symbol)
        ohlcv = self.exchange.fetch_ohlcv(ex_symbol, timeframe, limit=limit)
        candles = []
        for row in ohlcv:
            from datetime import datetime, timezone
            candles.append({
                "timestamp": row[0],
                "datetime": datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": row[5],
            })
        return candles

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
        return f"ExchangeClient({self.label}, quote={self.quote_currency})"
