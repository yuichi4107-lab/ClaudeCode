"""
Saxo Bank OpenAPI アダプター

Saxo Bank OpenAPI を直接呼び出し、ExchangeClient と同じインターフェースを提供する。
FX 通貨ペア（USD/JPY, EUR/JPY 等）の売買を既存の AutoTrader から透過的に利用可能にする。

ライブラリ選定:
    saxo-openapi (hootnot/saxo_openapi v0.6.0) は Python 3.12 で動作するが、
    エンドポイント定義クラスが提供されておらず、APIRequest の自前定義が必要となる。
    OANDA 実装時の oandapyV20 問題と同様の不便を避けるため、httpx 直接呼び出しを採用した。
    saxo-openapi ライブラリは不使用（インストール済みであっても利用しない）。

認証:
    Personal Access Token（PAT）による Bearer 認証。
    PAT は Saxo Developer Portal で発行（有効期限 24 時間）。

TODO: OAuth 2.0 Authorization Code Flow + refresh_token フロー実装ポイント
    工程 2b として別途実装予定。以下の差し替えポイントを参照:
        - __init__ の headers 設定箇所（Bearer トークンの注入部分）
        - _refresh_token() メソッド（現在は NotImplemented の stub を用意）
    本番運用では PAT ではなく OAuth refresh_token を使用すること。
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../../.env"))

logger = logging.getLogger(__name__)


class SaxoAPIError(Exception):
    """Saxo API エラー基底クラス"""
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class SaxoAuthError(SaxoAPIError):
    """認証エラー（Token 失効・未設定）"""
    pass


class SaxoRateLimitError(SaxoAPIError):
    """レート制限エラー（429）"""
    pass


class SaxoClient:
    """
    Saxo Bank OpenAPI クライアント（ExchangeClient 互換インターフェース）

    Sim 環境および Live 環境の両方に対応する。
    環境変数で認証情報を切り替える（.env 経由で注入）。

    Args:
        exchange_id: "saxo_sim"（Sim 環境）または "saxo"（Live 環境）

    Example:
        client = SaxoClient("saxo_sim")
        balance = client.get_balance()
        ticker = client.get_ticker("USD/JPY")
        ohlcv = client.fetch_ohlcv("USD/JPY", timeframe="1d", limit=30)
    """

    CONFIGS: Dict[str, Dict[str, Any]] = {
        "saxo_sim": {
            "base_url": "https://gateway.saxobank.com/sim/openapi",
            "token_env": "SAXO_SIM_TOKEN",
            "client_key_env": "SAXO_SIM_CLIENT_KEY",
            "account_key_env": "SAXO_SIM_ACCOUNT_KEY",
            "account_id_env": "SAXO_SIM_ACCOUNT_ID",
            "default_currency_env": "SAXO_SIM_DEFAULT_CURRENCY",
            "sandbox": True,
        },
        "saxo": {
            # Live 環境（工程 4 完了・Live 移行判断後に設定）
            # SAXO_LIVE_TOKEN, SAXO_LIVE_BASE_URL 等を .env に追加すること
            "base_url": "https://gateway.saxobank.com/openapi",
            "token_env": "SAXO_TOKEN",
            "client_key_env": "SAXO_CLIENT_KEY",
            "account_key_env": "SAXO_ACCOUNT_KEY",
            "account_id_env": "SAXO_ACCOUNT_ID",
            "default_currency_env": "SAXO_DEFAULT_CURRENCY",
            "sandbox": False,
        },
    }

    # タイムフレーム → Saxo Horizon（分）マッピング
    TIMEFRAME_MAP: Dict[str, int] = {
        "1m": 1,
        "5m": 5,
        "15m": 15,
        "30m": 30,
        "1h": 60,
        "4h": 240,
        "1d": 1440,
        "1w": 10080,
    }

    # 既知の UIC（FxSpot）- キャッシュのシード値
    KNOWN_UICS: Dict[str, int] = {
        "USDJPY": 42,
        "EURJPY": 18,
    }

    # レート制限: 最低リクエスト間隔（秒）
    MIN_REQUEST_INTERVAL: float = 0.1  # 10 req/s（保守的）

    # リトライ設定
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_BASE: float = 1.0  # 指数バックオフの基底（秒）

    def __init__(
        self,
        exchange_id: str = "saxo_sim",
        token: Optional[str] = None,
        account_key: Optional[str] = None,
        account_id: Optional[str] = None,
        base_url: Optional[str] = None,
        default_currency: Optional[str] = None,
    ):
        """
        SaxoClient を初期化する。

        Args:
            exchange_id: "saxo_sim" または "saxo"
            token: Bearer トークン（省略時は環境変数から読み込む）
            account_key: 口座キー（省略時は環境変数から読み込む）
            account_id: 口座 ID（省略時は環境変数から読み込む）
            base_url: API ベース URL（省略時は CONFIGS から取得）
            default_currency: デフォルト通貨（省略時は環境変数から読み込む）

        Raises:
            ValueError: exchange_id が不正 or 認証情報が未設定
        """
        if exchange_id not in self.CONFIGS:
            raise ValueError(
                f"Unknown Saxo config: {exchange_id}. Available: {list(self.CONFIGS.keys())}"
            )

        config = self.CONFIGS[exchange_id]
        self.exchange_id = exchange_id
        self.is_sandbox = config["sandbox"]

        # ベース URL
        self.base_url = base_url or config["base_url"]

        # 認証情報: 引数 > 環境変数
        self.token = token or os.getenv(config["token_env"], "")
        self.account_key = account_key or os.getenv(config["account_key_env"], "")
        self.account_id = account_id or os.getenv(config["account_id_env"], "")
        self.default_currency = default_currency or os.getenv(
            config["default_currency_env"], "JPY"
        )

        # 認証情報の必須チェック
        if not self.token:
            raise ValueError(
                f"Saxo token not set. Set {config['token_env']} in .env or pass token= argument.\n"
                f"TODO (工程 2b): OAuth refresh_token フローを実装すれば自動更新可能になる。"
            )
        if not self.account_key:
            raise ValueError(
                f"Saxo account key not set. Set {config['account_key_env']} in .env or pass account_key= argument."
            )

        # UIC キャッシュ（シンボル → UIC の変換結果を記憶）
        self._uic_cache: Dict[str, int] = dict(self.KNOWN_UICS)

        # httpx クライアント初期化
        # TODO (工程 2b): OAuth refresh_token フロー実装ポイント
        #   ここで Bearer トークンをセットする。
        #   refresh_token フロー実装後は、トークン期限切れ（401）時に
        #   _refresh_token() を呼び出してトークンを自動更新する設計とする。
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": f"Bearer {self._mask_token(self.token, visible=False)}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        # 実際の Authorization ヘッダーを設定（マスクなし）
        self._client.headers["Authorization"] = f"Bearer {self.token}"

        self._last_request_time: float = 0.0
        self.label = f"{exchange_id}{'(sim)' if self.is_sandbox else '(live)'}"
        self.quote_currency = self.default_currency  # ExchangeClient 互換

        logger.info(
            "SaxoClient initialized: %s, base_url=%s, account_key=%s...",
            self.label,
            self.base_url,
            self.account_key[:8] if len(self.account_key) > 8 else "****",
        )

    # ─── OAuth フロー差し替えポイント（工程 2b） ───

    def _refresh_token(self) -> None:
        """
        OAuth 2.0 refresh_token フローでトークンを更新する。

        TODO (工程 2b): 実装が必要。
            1. refresh_token を使って新しい access_token を取得
            2. self.token を更新
            3. self._client.headers["Authorization"] を更新
            現在は NotImplementedError を送出する（PAT 使用中は呼ばれない）。
        """
        raise NotImplementedError(
            "OAuth refresh_token フローは工程 2b で実装予定。"
            "現在は Personal Access Token（PAT）認証のみ対応。"
            "PAT の有効期限（24 時間）が切れた場合は Developer Portal で再発行してください。"
        )

    # ─── レート制限 ───

    def _throttle(self) -> None:
        """レート制限のための簡易スロットリング"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.time()

    # ─── 共通 HTTP リクエスト ───

    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        API リクエスト共通処理。

        Bearer 認証・エラーハンドリング・リトライ（指数バックオフ）を統合する。

        Args:
            method: HTTP メソッド（"GET", "POST", "DELETE" 等）
            path: API パス（ベース URL 以降、例: "/port/v1/balances/me"）
            params: クエリパラメータ
            json_body: リクエストボディ（JSON）

        Returns:
            レスポンス JSON（dict または list）

        Raises:
            SaxoAuthError: 401 エラー（Token 失効）
            SaxoRateLimitError: 429 エラー（レート制限）
            SaxoAPIError: その他の API エラー（4xx/5xx）
        """
        last_error: Optional[Exception] = None

        for attempt in range(self.MAX_RETRIES):
            self._throttle()
            try:
                resp = self._client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                )

                # 認証エラー（Token 失効）
                if resp.status_code == 401:
                    logger.warning(
                        "Saxo API 401 Unauthorized: Token が失効している可能性があります。"
                        " PAT の有効期限（24 時間）を確認し、Developer Portal で再発行してください。"
                        " TODO (工程 2b): OAuth refresh_token フローで自動更新予定。"
                        " path=%s",
                        path,
                    )
                    raise SaxoAuthError(
                        f"Saxo API 401: Token 失効または不正。path={path}",
                        status_code=401,
                        response_body=resp.text,
                    )

                # レート制限（429）
                if resp.status_code == 429:
                    retry_after = float(resp.headers.get("Retry-After", self.RETRY_BACKOFF_BASE * (2 ** attempt)))
                    logger.warning(
                        "Saxo API 429 Rate Limit: %d 秒後にリトライ (attempt=%d/%d)",
                        retry_after,
                        attempt + 1,
                        self.MAX_RETRIES,
                    )
                    time.sleep(retry_after)
                    last_error = SaxoRateLimitError(
                        f"Saxo API 429: レート制限。path={path}",
                        status_code=429,
                        response_body=resp.text,
                    )
                    continue

                # その他の HTTP エラー（4xx/5xx）
                if resp.status_code >= 400:
                    logger.error(
                        "Saxo API HTTP Error: status=%d, path=%s, body=%s",
                        resp.status_code,
                        path,
                        resp.text[:500],
                    )
                    raise SaxoAPIError(
                        f"Saxo API {resp.status_code}: {resp.text[:200]}",
                        status_code=resp.status_code,
                        response_body=resp.text,
                    )

                # 成功（204 No Content は空 dict）
                if resp.status_code == 204 or not resp.content:
                    return {}

                return resp.json()

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                backoff = self.RETRY_BACKOFF_BASE * (2 ** attempt)
                logger.warning(
                    "Saxo API ネットワークエラー: %s (attempt=%d/%d, backoff=%.1fs)",
                    e,
                    attempt + 1,
                    self.MAX_RETRIES,
                    backoff,
                )
                last_error = e
                time.sleep(backoff)

            except (SaxoAuthError, SaxoAPIError):
                # 認証エラーとその他の API エラーはリトライしない
                raise

        # リトライ上限超過
        raise SaxoAPIError(
            f"Saxo API リトライ上限（{self.MAX_RETRIES}回）超過: path={path}, last_error={last_error}"
        ) from last_error

    # ─── シンボル変換 ───

    @staticmethod
    def to_saxo_symbol(symbol: str) -> str:
        """
        内部シンボル → Saxo API シンボルに変換する。

        Args:
            symbol: 内部シンボル（例: "USD/JPY", "USD-JPY"）

        Returns:
            Saxo シンボル（例: "USDJPY"）
        """
        return symbol.replace("/", "").replace("-", "").upper()

    @staticmethod
    def from_saxo_symbol(saxo_symbol: str) -> str:
        """
        Saxo API シンボル → 内部シンボルに変換する。

        Args:
            saxo_symbol: Saxo シンボル（例: "USDJPY"）

        Returns:
            内部シンボル（例: "USD/JPY"）
        """
        # 6 文字の通貨ペアを 3+3 に分割
        s = saxo_symbol.upper()
        if len(s) == 6:
            return f"{s[:3]}/{s[3:]}"
        return saxo_symbol

    def is_symbol_supported(self, symbol: str) -> bool:
        """
        FX 通貨ペアかどうかを確認する（ExchangeClient 互換）。

        Args:
            symbol: 通貨ペア（例: "USD/JPY"）

        Returns:
            bool: FX ペア（3+3 文字構成）なら True
        """
        parts = symbol.replace("-", "/").split("/")
        if len(parts) != 2:
            return False
        return len(parts[0]) == 3 and len(parts[1]) == 3

    def convert_symbol(self, symbol: str) -> str:
        """
        ExchangeClient 互換: シンボル変換（FX はそのまま返す）。

        Args:
            symbol: 通貨ペア

        Returns:
            str: 変換後のシンボル（FX は変換なし）
        """
        return symbol

    # ─── UIC 変換 ───

    def _get_uic(self, symbol: str) -> int:
        """
        シンボル（例: "USD/JPY"）を Saxo UIC（Unique Instrument Code）に変換する。

        既知の UIC はキャッシュから即返却する。
        未知のシンボルは /ref/v1/instruments で検索する。

        Args:
            symbol: 内部シンボル（例: "USD/JPY"）

        Returns:
            int: UIC

        Raises:
            SaxoAPIError: シンボルが見つからない場合
        """
        saxo_sym = self.to_saxo_symbol(symbol)

        if saxo_sym in self._uic_cache:
            return self._uic_cache[saxo_sym]

        logger.info("UIC キャッシュミス: %s → API 検索中", saxo_sym)
        data = self._request(
            "GET",
            "/ref/v1/instruments",
            params={"Keywords": saxo_sym, "AssetTypes": "FxSpot"},
        )

        instruments = data.get("Data", [])
        if not instruments:
            raise SaxoAPIError(f"シンボルが見つかりません: {symbol} (Saxo: {saxo_sym})")

        uic = int(instruments[0]["Identifier"])
        self._uic_cache[saxo_sym] = uic
        logger.info("UIC キャッシュに追加: %s → %d", saxo_sym, uic)
        return uic

    # ─── 残高 ───

    def get_balance(self, currency: Optional[str] = None) -> Dict[str, Any]:
        """
        残高を取得する（ExchangeClient 互換）。

        Args:
            currency: 通貨（省略時は default_currency）

        Returns:
            dict: {
                "free": 利用可能証拠金,
                "used": 使用中証拠金,
                "total": 純資産（TotalValue）,
                "CashBalance": 現金残高,
                "MarginAvailable": 利用可能証拠金,
                "TotalValue": 口座総額,
                "Currency": 通貨,
                "OpenPositionsCount": オープンポジション数
            }
        """
        data = self._request("GET", "/port/v1/balances/me")
        cash_balance = float(data.get("CashBalance", 0))
        margin_available = float(data.get("MarginAvailable", cash_balance))
        total_value = float(data.get("TotalValue", cash_balance))
        margin_used = total_value - margin_available

        result = {
            # ExchangeClient 互換フィールド
            "free": margin_available,
            "used": margin_used,
            "total": total_value,
            # Saxo 固有フィールド（生値も返す）
            "CashBalance": cash_balance,
            "MarginAvailable": margin_available,
            "TotalValue": total_value,
            "Currency": data.get("Currency", self.default_currency),
            "OpenPositionsCount": data.get("OpenPositionsCount", 0),
        }
        logger.info("残高取得: %s", {k: v for k, v in result.items() if k in ("free", "total", "Currency")})
        return result

    # ─── 現在価格 ───

    def get_ticker(self, symbol: str) -> Dict[str, Any]:
        """
        現在価格を取得する（ExchangeClient 互換）。

        Args:
            symbol: 通貨ペア（例: "USD/JPY"）

        Returns:
            dict: {
                "symbol": 内部シンボル,
                "exchange_symbol": Saxo シンボル,
                "last": Mid 価格,
                "bid": Bid 価格,
                "ask": Ask 価格,
                "spread": スプレッド,
                "market_state": 市場状態（"Open", "Closed" 等）,
                "timestamp": UNIXタイムスタンプ（ms）
            }
        """
        uic = self._get_uic(symbol)
        saxo_sym = self.to_saxo_symbol(symbol)

        data = self._request(
            "GET",
            "/trade/v1/infoprices",
            params={"AssetType": "FxSpot", "Uic": uic},
        )

        quote = data.get("Quote", {})
        bid = float(quote["Bid"]) if quote.get("Bid") is not None else None
        ask = float(quote["Ask"]) if quote.get("Ask") is not None else None
        mid = float(quote["Mid"]) if quote.get("Mid") is not None else (
            (bid + ask) / 2 if bid and ask else None
        )

        result = {
            "symbol": symbol,
            "exchange_symbol": saxo_sym,
            "last": mid,
            "bid": bid,
            "ask": ask,
            "spread": round(ask - bid, 5) if ask and bid else None,
            "market_state": quote.get("MarketState", "Unknown"),
            "timestamp": int(time.time() * 1000),
        }
        logger.info("Ticker: %s bid=%s ask=%s", symbol, bid, ask)
        return result

    # ─── OHLCV ───

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        OHLCV データを取得する（ExchangeClient 互換）。

        Saxo chart/v3/charts エンドポイントを使用する（v1 ではなく v3 が必須）。
        各ローソク足は Bid 側と Ask 側の両方があるため、Mid（平均）を使用する。

        Args:
            symbol: 通貨ペア（例: "USD/JPY"）
            timeframe: タイムフレーム（"1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"）
            limit: 取得本数（最大 1200）

        Returns:
            list of dict: [
                {
                    "timestamp": ms,
                    "datetime": "YYYY-MM-DD HH:MM:SS",
                    "open": float,
                    "high": float,
                    "low": float,
                    "close": float,
                    "volume": 0  # Saxo はボリューム非提供
                },
                ...
            ]
        """
        uic = self._get_uic(symbol)
        horizon = self.TIMEFRAME_MAP.get(timeframe, 1440)  # デフォルト: 1d

        data = self._request(
            "GET",
            "/chart/v3/charts",
            params={
                "AssetType": "FxSpot",
                "Uic": uic,
                "Horizon": horizon,
                "Count": min(limit, 1200),
            },
        )

        candles = []
        for c in data.get("Data", []):
            # Mid = (Bid + Ask) / 2 で計算
            open_mid = (c.get("OpenBid", 0) + c.get("OpenAsk", 0)) / 2
            high_mid = (c.get("HighBid", 0) + c.get("HighAsk", 0)) / 2
            low_mid = (c.get("LowBid", 0) + c.get("LowAsk", 0)) / 2
            close_mid = (c.get("CloseBid", 0) + c.get("CloseAsk", 0)) / 2

            # タイムスタンプ変換（"2026-03-30T00:00:00.000000Z" → ms）
            time_str = c.get("Time", "")
            try:
                dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
                ts = int(dt.timestamp() * 1000)
                dt_str = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, AttributeError):
                ts = 0
                dt_str = time_str

            candles.append({
                "timestamp": ts,
                "datetime": dt_str,
                "open": round(open_mid, 5),
                "high": round(high_mid, 5),
                "low": round(low_mid, 5),
                "close": round(close_mid, 5),
                "volume": 0,  # Saxo FxSpot はボリューム非提供
            })

        logger.info(
            "OHLCV: %s, timeframe=%s, 取得本数=%d",
            symbol, timeframe, len(candles)
        )
        return candles

    # ─── 注文 ───

    def market_buy(
        self,
        symbol: str,
        amount: float,
        quote_amount: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        成行買い注文（ExchangeClient 互換）。

        FX では amount = 通貨単位数（units）で注文する。
        quote_amount（JPY 金額）が指定された場合、現在レートから逆算する。

        Args:
            symbol: 通貨ペア（例: "USD/JPY"）
            amount: 購入数量（基軸通貨の units、例: 1000 = 1,000 USD）
            quote_amount: 購入金額（建て通貨単位）。指定時は amount を上書き

        Returns:
            dict: 注文結果（ExchangeClient 互換フォーマット）
        """
        units = self._calculate_units(symbol, amount, quote_amount, side="buy")
        uic = self._get_uic(symbol)
        saxo_sym = self.to_saxo_symbol(symbol)

        body = {
            "AssetType": "FxSpot",
            "Uic": uic,
            "BuySell": "Buy",
            "Amount": units,
            "OrderType": "Market",
            "ManualOrder": False,
            "ExternalReference": f"saxo_client_{int(time.time())}",
        }

        logger.info("市場買い注文: %s, units=%d", symbol, units)
        data = self._request("POST", "/trade/v2/orders", json_body=body)
        return self._format_order_response(data, symbol, "buy", units)

    def market_sell(self, symbol: str, amount: float) -> Dict[str, Any]:
        """
        成行売り注文（ExchangeClient 互換）。

        Args:
            symbol: 通貨ペア（例: "USD/JPY"）
            amount: 売却数量（units）

        Returns:
            dict: 注文結果（ExchangeClient 互換フォーマット）
        """
        units = int(amount)
        uic = self._get_uic(symbol)
        saxo_sym = self.to_saxo_symbol(symbol)

        body = {
            "AssetType": "FxSpot",
            "Uic": uic,
            "BuySell": "Sell",
            "Amount": units,
            "OrderType": "Market",
            "ManualOrder": False,
            "ExternalReference": f"saxo_client_{int(time.time())}",
        }

        logger.info("市場売り注文: %s, units=%d", symbol, units)
        data = self._request("POST", "/trade/v2/orders", json_body=body)
        return self._format_order_response(data, symbol, "sell", units)

    def stop_loss_order(
        self,
        symbol: str,
        amount: float,
        stop_price: float,
    ) -> Dict[str, Any]:
        """
        ストップロス注文を発注する。

        Saxo は OCO（One-Cancels-Other）注文をネイティブサポートするが、
        ここでは Stop 注文（指値なし逆指値）を使用する。

        Args:
            symbol: 通貨ペア（例: "USD/JPY"）
            amount: 注文数量（units）
            stop_price: ストップ価格

        Returns:
            dict: 注文結果
        """
        uic = self._get_uic(symbol)
        pip_precision = self._pip_precision(symbol)

        body = {
            "AssetType": "FxSpot",
            "Uic": uic,
            "BuySell": "Sell",  # ロングポジションのストップロス = 売り
            "Amount": int(amount),
            "OrderType": "Stop",
            "StopOrderType": "Stop",
            "OrderPrice": round(stop_price, pip_precision),
            "OrderDuration": {"DurationType": "GoodTillCancel"},
            "ManualOrder": False,
        }

        logger.info("ストップロス注文: %s, stop_price=%s, units=%d", symbol, stop_price, int(amount))
        data = self._request("POST", "/trade/v2/orders", json_body=body)
        return self._format_order_response(data, symbol, "sell", int(amount), order_type="stop")

    def cancel_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        注文をキャンセルする（ExchangeClient 互換）。

        Args:
            order_id: Saxo 注文 ID
            symbol: 通貨ペア（Saxo では不要だが互換性のため受け付ける）

        Returns:
            dict: キャンセル結果
        """
        logger.info("注文キャンセル: order_id=%s", order_id)
        data = self._request(
            "DELETE",
            f"/trade/v2/orders/{order_id}",
            params={"AccountKey": self.account_key},
        )
        return {
            "id": order_id,
            "symbol": symbol,
            "status": "cancelled",
            "raw": data,
        }

    def fetch_open_orders(self, symbol: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        未約定の注文一覧を取得する（ExchangeClient 互換）。

        Args:
            symbol: 通貨ペア（指定時はフィルタリング）

        Returns:
            list of dict: 未約定注文の一覧
        """
        data = self._request("GET", "/port/v1/orders/me")
        orders = []
        for o in data.get("Data", []):
            sym = self.from_saxo_symbol(o.get("DisplayAndFormat", {}).get("Symbol", ""))
            if symbol and sym and sym != symbol:
                continue
            orders.append(self._format_open_order(o))
        return orders

    def fetch_order(self, order_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        注文状態を取得する（ExchangeClient 互換）。

        Args:
            order_id: Saxo 注文 ID
            symbol: 通貨ペア（互換性のため受け付ける）

        Returns:
            dict: 注文情報
        """
        data = self._request("GET", "/port/v1/orders/me")
        for o in data.get("Data", []):
            if str(o.get("OrderId")) == str(order_id):
                return self._format_open_order(o)
        return {"id": order_id, "status": "not_found", "symbol": symbol}

    def fetch_positions(self) -> List[Dict[str, Any]]:
        """
        ポジション一覧を取得する。

        Returns:
            list of dict: ポジション一覧
        """
        data = self._request("GET", "/port/v1/positions/me")
        positions = []
        for p in data.get("Data", []):
            pd = p.get("PositionBase", {})
            pv = p.get("PositionView", {})
            sym = self.from_saxo_symbol(
                p.get("DisplayAndFormat", {}).get("Symbol", "")
            )
            positions.append({
                "id": pd.get("PositionId"),
                "symbol": sym,
                "side": "buy" if pd.get("BuySell") == "Buy" else "sell",
                "amount": float(pd.get("Amount", 0)),
                "open_price": float(pd.get("OpenPrice", 0)),
                "current_price": float(pv.get("CurrentPrice", 0)),
                "unrealized_pnl": float(pv.get("ProfitLossOnTrade", 0)),
                "open_time": pd.get("ValueDate"),
            })
        return positions

    # ─── 内部ユーティリティ ───

    def _calculate_units(
        self,
        symbol: str,
        amount: Optional[float] = None,
        quote_amount: Optional[float] = None,
        side: str = "buy",
    ) -> int:
        """
        注文数量（units）を計算する。

        Args:
            symbol: 通貨ペア
            amount: 基軸通貨の数量（units）
            quote_amount: 建て通貨の金額（指定時は現在レートから逆算）
            side: "buy" または "sell"

        Returns:
            int: 注文数量（units）
        """
        if amount and not quote_amount:
            return int(amount)

        if quote_amount:
            ticker = self.get_ticker(symbol)
            price = ticker["ask"] if side == "buy" else ticker["bid"]
            if price:
                base, quote = symbol.replace("-", "/").split("/")
                if quote == "JPY":
                    return int(quote_amount / price)
                else:
                    return int(quote_amount / price)

        return int(amount or 0)

    @staticmethod
    def _pip_precision(symbol: str) -> int:
        """
        pip 精度を返す（JPY クロスは 3 桁、その他は 5 桁）。

        Args:
            symbol: 通貨ペア

        Returns:
            int: 小数点桁数
        """
        if "JPY" in symbol.upper():
            return 3
        return 5

    def _format_order_response(
        self,
        data: Dict[str, Any],
        symbol: str,
        side: str,
        amount: int,
        order_type: str = "market",
    ) -> Dict[str, Any]:
        """
        Saxo 注文レスポンスを ExchangeClient 互換フォーマットに変換する。

        Args:
            data: Saxo API レスポンス
            symbol: 内部シンボル
            side: "buy" または "sell"
            amount: 注文数量
            order_type: 注文種別

        Returns:
            dict: 統一フォーマットの注文情報
        """
        order_id = data.get("OrderId") or data.get("orderId") or ""
        return {
            "id": str(order_id),
            "symbol": symbol,
            "exchange_symbol": self.to_saxo_symbol(symbol),
            "type": order_type,
            "side": side,
            "amount": amount,
            "price": None,     # Market 注文は約定後に確定
            "average": None,
            "filled": amount,  # Market 注文は即約定と仮定
            "remaining": 0,
            "status": "closed" if order_type == "market" else "open",
            "timestamp": int(time.time() * 1000),
            "cost": None,
        }

    def _format_open_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Saxo 未約定注文を ExchangeClient 互換フォーマットに変換する。

        Args:
            order: Saxo API の注文データ

        Returns:
            dict: 統一フォーマットの注文情報
        """
        sym = self.from_saxo_symbol(
            order.get("DisplayAndFormat", {}).get("Symbol", "")
        )
        buy_sell = order.get("BuySell", "Buy")
        amount = float(order.get("Amount", 0))
        return {
            "id": str(order.get("OrderId", "")),
            "symbol": sym,
            "exchange_symbol": order.get("DisplayAndFormat", {}).get("Symbol", ""),
            "type": order.get("OrderType", "").lower(),
            "side": "buy" if buy_sell == "Buy" else "sell",
            "amount": amount,
            "price": float(order["Price"]) if order.get("Price") else None,
            "average": None,
            "filled": 0,
            "remaining": amount,
            "status": order.get("Status", "").lower(),
            "timestamp": None,
            "cost": None,
        }

    @staticmethod
    def _mask_token(token: str, visible: bool = True) -> str:
        """
        Token をマスクする（ログ出力用）。

        Args:
            token: 元のトークン
            visible: True の場合、先頭 8 文字のみ表示

        Returns:
            str: マスクされたトークン
        """
        if not token:
            return "****"
        if visible and len(token) > 8:
            return f"{token[:8]}...****"
        return "****"

    def __repr__(self) -> str:
        return f"SaxoClient({self.label}, account_key={self.account_key[:8] if len(self.account_key) > 8 else '****'}...)"
