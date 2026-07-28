# OANDA REST API v20 アダプター設計書

## 1. OANDA REST API v20 仕様まとめ

### 1.1 ベースURL

| 環境 | REST API | Streaming |
|------|----------|-----------|
| デモ | `https://api-fxpractice.oanda.com` | `https://stream-fxpractice.oanda.com` |
| 本番 | `https://api-fxtrade.oanda.com` | `https://stream-fxtrade.oanda.com` |

### 1.2 認証方式

- **Bearer Token認証**
- OANDAアカウント管理ポータル(AMP)で「個人アクセストークン」を生成
- 全リクエストに `Authorization: Bearer <TOKEN>` ヘッダーを付与
- デモと本番で別々のトークンが必要

### 1.3 主要エンドポイント

#### アカウント・残高
| メソッド | パス | 用途 |
|---------|------|------|
| GET | `/v3/accounts` | アカウント一覧 |
| GET | `/v3/accounts/{accountID}/summary` | 残高・証拠金サマリー |
| GET | `/v3/accounts/{accountID}/instruments` | 取引可能銘柄一覧 |

#### ローソク足（OHLCV）
| メソッド | パス | 用途 |
|---------|------|------|
| GET | `/v3/instruments/{instrument}/candles` | ローソク足データ取得 |

主要パラメータ:
- `granularity`: S5, M1, M5, M15, M30, H1, H4, D, W, M
- `count`: 取得本数（最大5000、デフォルト500）
- `price`: M(中値), B(Bid), A(Ask), BA(Bid+Ask)
- `from` / `to`: RFC3339形式の日時指定

#### 現在レート
| メソッド | パス | 用途 |
|---------|------|------|
| GET | `/v3/accounts/{accountID}/pricing?instruments=EUR_USD,USD_JPY` | Bid/Ask取得 |

#### 注文
| メソッド | パス | 用途 |
|---------|------|------|
| POST | `/v3/accounts/{accountID}/orders` | 注文作成 |
| GET | `/v3/accounts/{accountID}/orders` | 注文一覧 |
| GET | `/v3/accounts/{accountID}/pendingOrders` | 未約定注文一覧 |
| PUT | `/v3/accounts/{accountID}/orders/{orderSpecifier}/cancel` | 注文キャンセル |

注文タイプ:
- **MARKET**: 成行注文（`units` 正=買い, 負=売り）
- **LIMIT**: 指値注文
- **STOP**: 逆指値エントリー注文
- **STOP_LOSS**: ストップロス注文（Trade単位で設定）
- **TAKE_PROFIT**: テイクプロフィット注文
- **TRAILING_STOP_LOSS**: トレーリングストップ

#### トレード管理
| メソッド | パス | 用途 |
|---------|------|------|
| GET | `/v3/accounts/{accountID}/openTrades` | オープントレード一覧 |
| PUT | `/v3/accounts/{accountID}/trades/{tradeSpecifier}/close` | トレード決済 |
| PUT | `/v3/accounts/{accountID}/trades/{tradeSpecifier}/orders` | SL/TP設定・変更 |

#### ポジション管理
| メソッド | パス | 用途 |
|---------|------|------|
| GET | `/v3/accounts/{accountID}/openPositions` | オープンポジション一覧 |
| GET | `/v3/accounts/{accountID}/positions/{instrument}` | 銘柄別ポジション |
| PUT | `/v3/accounts/{accountID}/positions/{instrument}/close` | ポジション決済 |

### 1.4 銘柄表記

OANDAでは `EUR_USD`（アンダースコア区切り）。既存システムの `BTC/USDT`（スラッシュ区切り）とは異なる。

### 1.5 レート制限

公式ドキュメントに明示的な記載なし。実運用上の一般的な制限:
- REST API: 約120リクエスト/秒
- Streaming: 1接続あたり最大4価格/秒
- `enableRateLimit` 相当の自前制御を実装する

### 1.6 FX特有の概念

- **units**: 通貨単位（1 unit = 1通貨。ロット制ではない）
- **Bid/Ask**: FXはBid/Askスプレッドで取引。手数料は原則スプレッドに内包
- **pip**: 通常0.0001（JPYクロスは0.01）
- **レバレッジ**: 口座設定のmarginRateで決定（日本では最大25倍）
- **ネッティング**: 同一銘柄のポジションは自動ネッティング（Binanceのスポット取引と同じ）

---

## 2. Pythonライブラリ選択

### 2.1 oandapyV20

| 項目 | 評価 |
|------|------|
| 最新バージョン | 0.7.2（2021年8月） |
| 対応Python | 3.6 - 3.9 |
| メンテナンス | **事実上停止（約5年放置）** |
| Python 3.12対応 | 未保証 |
| 評価 | **非推奨** |

### 2.2 httpx直接呼び出し（推奨）

| 項目 | 評価 |
|------|------|
| 実装量 | 中程度（200-300行） |
| メンテナンス | 自前管理だが、OANDA API自体が安定 |
| Python互換性 | httpxは3.8+対応、最新Python対応 |
| 依存関係 | httpx のみ追加（既存のrequestsでも可） |
| 評価 | **推奨** |

### 決定: httpxで直接REST呼び出し

理由:
1. oandapyV20はPython 3.12非対応・5年間メンテなし
2. OANDA REST API v20は設計がシンプルで直接呼び出しが容易
3. エンドポイント数が限定的（実際に使うのは8-10程度）
4. 既存のExchangeClientのインターフェースに合わせた薄いラッパーで十分

---

## 3. 統合設計

### 3.1 アーキテクチャ方針

**別クラス `OandaClient` を作成し、ExchangeClientと同じインターフェースを提供する。**

理由:
- ExchangeClientはccxtに強く依存しており、ccxtはFXに対応していない
- OANDAのTrade/Position概念は暗号資産取引所と微妙に異なる（ネッティング、units制）
- 共通インターフェースを合わせることで、AutoTraderからは透過的に使える

```
                 ┌─────────────┐
                 │  AutoTrader  │
                 └──────┬──────┘
                        │
              ┌─────────┴─────────┐
              │                   │
     ┌────────┴────────┐  ┌──────┴───────┐
     │ ExchangeClient  │  │ OandaClient  │
     │  (ccxt wrapper)  │  │ (httpx直接)   │
     └────────┬────────┘  └──────┬───────┘
              │                   │
        ┌─────┴─────┐     ┌─────┴──────┐
        │  Binance   │     │  OANDA     │
        │  Coincheck │     │  REST v20  │
        └───────────┘     └────────────┘
```

### 3.2 OandaClient 実装案

```python
"""
OANDAアダプター

OANDA REST API v20を直接呼び出し、ExchangeClientと同じインターフェースを提供する。
FX通貨ペアの売買を既存のAutoTraderから透過的に利用可能にする。
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
        # FXペアは3文字+3文字（例: USD/JPY, EUR/USD）
        parts = symbol.replace("-", "/").split("/")
        if len(parts) != 2:
            return False
        return len(parts[0]) == 3 and len(parts[1]) == 3

    def convert_symbol(self, symbol):
        """ExchangeClient互換: シンボル変換（そのまま返す）"""
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

        # Bid/Askの最良値を取得
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
        """成行買い注文（ExchangeClient互換）"""
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
                return int(quote_amount / price) if "JPY" in symbol else int(quote_amount * price)

        return amount or 0

    @staticmethod
    def _pip_precision(symbol):
        """pip精度を返す（JPYクロスは3桁、その他は5桁）"""
        if "JPY" in symbol.upper():
            return 3
        return 5

    def _format_order_response(self, data, symbol, side):
        """OANDA注文レスポンスをExchangeClient互換フォーマットに変換"""
        # 約定情報を取得
        fill = data.get("orderFillTransaction", {})
        order_create = data.get("orderCreateTransaction", {})

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
```

### 3.3 AutoTraderとの統合

#### trader.py の変更点

```python
# 変更1: import追加
from src.trading.oanda_client import OandaClient

# 変更2: exchange_id の選択肢に oanda を追加
EXCHANGE_CONFIGS_ALL = {
    **ExchangeClient.EXCHANGE_CONFIGS,
    **OandaClient.CONFIGS,
}

DEFAULT_ORDER_AMOUNTS = {
    "USDT": 20,
    "JPY": 15000,   # 暗号資産（Coincheck）
    "JPY_FX": 10000, # FX（OANDA）: 1万通貨単位
}

# 変更3: AutoTrader.__init__ でクライアント分岐
def __init__(self, exchange_id="binance_testnet", ...):
    ...
    if exchange_id.startswith("oanda"):
        self.exchange = OandaClient(exchange_id)
    else:
        self.exchange = ExchangeClient(exchange_id)
    ...

# 変更4: argparse の choices に追加
parser.add_argument(
    "--exchange", default="binance_testnet",
    choices=["binance_testnet", "binance", "coincheck", "oanda_demo", "oanda"],
)
```

#### scanner.py の変更点

```python
# FX通貨ペアのデータ取得はOANDA APIから直接取得する
def fetch_latest_candles(symbol, timeframe="1d", limit=60, exchange_id="binance"):
    """取引所から最新のOHLCVデータを取得する"""

    # FX通貨ペアの判定（3文字/3文字）
    parts = symbol.replace("-", "/").split("/")
    is_fx = len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 3

    if is_fx:
        # OANDAから取得（認証不要のcandles APIを使用）
        from src.trading.oanda_client import OandaClient
        client = OandaClient("oanda_demo")  # ローソク足取得のみ
        return client.fetch_ohlcv(symbol, timeframe, limit)
    else:
        # 既存のccxt経由（Binance）
        exchange_class = getattr(ccxt, exchange_id)
        exchange = exchange_class({"enableRateLimit": True})
        ...
```

### 3.4 strategy_config.json へのFX通貨ペア追加

```json
{
  "currencies": {
    "BTC-USDT": { ... },
    "ETH-USDT": { ... },

    "USD-JPY": {
      "asset_class": "fx",
      "exchange": "oanda",
      "strategies": [
        {
          "id": "double_bottom",
          "pattern": "double_bottom_v3_neckline",
          "direction": "long",
          "take_profit": 0.005,
          "stop_loss": 0.003,
          "hold_bars": 10,
          "trend_filter": true,
          "note": "FX: TP/SLは暗号資産より小さい値に設定（ボラティリティが低いため）"
        }
      ]
    },
    "EUR-USD": {
      "asset_class": "fx",
      "exchange": "oanda",
      "strategies": [
        {
          "id": "double_bottom",
          "pattern": "double_bottom_v3_neckline",
          "direction": "long",
          "take_profit": 0.004,
          "stop_loss": 0.002,
          "hold_bars": 10,
          "trend_filter": true
        }
      ]
    },
    "EUR-JPY": {
      "asset_class": "fx",
      "exchange": "oanda",
      "strategies": [
        {
          "id": "double_bottom",
          "pattern": "double_bottom_v3_neckline",
          "direction": "long",
          "take_profit": 0.005,
          "stop_loss": 0.003,
          "hold_bars": 10,
          "trend_filter": true
        }
      ]
    },
    "GBP-JPY": {
      "asset_class": "fx",
      "exchange": "oanda",
      "strategies": [
        {
          "id": "double_bottom",
          "pattern": "double_bottom_v3_neckline",
          "direction": "long",
          "take_profit": 0.006,
          "stop_loss": 0.004,
          "hold_bars": 10,
          "trend_filter": true
        }
      ]
    }
  }
}
```

### 3.5 .env への追加項目

```env
# OANDA Demo
OANDA_DEMO_TOKEN=your_oanda_demo_token_here
OANDA_DEMO_ACCOUNT_ID=your_oanda_demo_account_id_here

# OANDA Live
OANDA_TOKEN=your_oanda_live_token_here
OANDA_ACCOUNT_ID=your_oanda_live_account_id_here
```

---

## 4. FX特有の考慮点

### 4.1 スプレッド

- FXはスプレッド（Bid-Ask差）が実質コスト。手数料率ではない
- USD/JPY: 約0.3-0.5pips、EUR/USD: 約0.5-1.0pips
- 暗号資産の `fee_rate: 0.001` に相当する概念が異なる
- バックテスト時はスプレッドコストを別途計算する必要あり

```python
# スプレッドコスト計算（バックテスト用）
TYPICAL_SPREADS = {
    "USD/JPY": 0.003,   # 0.3 pips = 0.003円
    "EUR/USD": 0.00008,  # 0.8 pips = 0.00008
    "EUR/JPY": 0.005,    # 0.5 pips = 0.005円
    "GBP/JPY": 0.01,     # 1.0 pip  = 0.01円
}
```

### 4.2 ロット計算（units計算）

OANDAは「通貨単位（units）」制。1 unit = 1通貨。

```python
def calculate_fx_units(symbol, quote_amount_jpy, current_price, leverage=25):
    """
    FX注文数量を計算する。

    例: USD/JPY, 10,000円の証拠金, レバレッジ25倍
    → 10,000 * 25 / 150 = 1,666 units
    """
    if "JPY" in symbol.split("/")[1]:
        # クォート通貨がJPY: units = JPY金額 / 現在価格
        units = int(quote_amount_jpy / current_price)
    else:
        # クォート通貨が非JPY（例: EUR/USD）:
        # まずJPY→USD換算が必要
        units = int(quote_amount_jpy / current_price)

    return units
```

### 4.3 pip計算

```python
def pip_value(symbol, units):
    """1 pipあたりの損益額（JPY）を計算する"""
    if "JPY" in symbol:
        # JPYクロス: 1pip = 0.01
        return units * 0.01
    else:
        # 非JPY: 1pip = 0.0001（USD換算後にJPY変換が必要）
        return units * 0.0001  # USD建て、JPY変換は別途
```

### 4.4 取引時間

- FXは月曜早朝～土曜早朝（日本時間）の24時間取引
- 暗号資産と異なり土日は市場クローズ → 週末にギャップリスクあり
- AutoTraderのdaemonモードで土日スキップロジックを追加すべき

---

## 5. 実装ロードマップ

### Phase 1: 基盤（最優先）
1. `src/trading/oanda_client.py` 作成（本設計書のコード）
2. `.env.example` にOANDA項目追加
3. デモ口座で接続テスト（残高取得、ローソク足取得）

### Phase 2: データ統合
4. `scanner.py` のFX対応（fetch_latest_candles分岐）
5. `strategy_config.json` にFXペア追加（USD/JPY, EUR/USDの2ペアから開始）
6. FXペアでのシグナルスキャン動作確認

### Phase 3: トレード統合
7. `trader.py` のOandaClient分岐実装
8. デモ口座でのドライラン→実注文テスト
9. SL/TP設定のテスト

### Phase 4: 本番移行
10. バックテストでFXペアのTP/SL/Hold最適化
11. 本番口座トークン設定
12. 小ロットで本番運用開始

---

## 6. 依存関係の追加

```
# requirements.txt に追加
httpx>=0.27.0
```

既存の `ccxt`, `pandas`, `requests` には影響なし。
