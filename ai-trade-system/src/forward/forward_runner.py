"""
FX フォワードテスト メインランナー

portfolio_config.json からパターンCの設定を読み込み、
各戦略の get_latest_signal() を時間足スケジュールで呼び出して
シグナルを JSONL ファイルに記録する。

使い方:
    # dry_run モード（デフォルト）
    python src/forward/forward_runner.py

    # dry_run モードで起動（明示的）
    python src/forward/forward_runner.py --dry-run

    # 引数なし（portfolio_config.json の recommended_pattern を自動使用）
    runner = ForwardRunner()
    runner.run()

    # portfolio_id を明示指定
    runner = ForwardRunner(portfolio_id="pattern_C_growth", dry_run=True)
    runner.run()
"""

import argparse
import json
import logging
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.backtest.portfolio_config_loader import (
    load_portfolio_config,
    get_circuit_breaker_config,
)
from src.backtest.strategies import load_strategy
from src.trading.saxo_client import SaxoAuthError, SaxoClient
from src.forward.scheduler import ForwardScheduler
from src.forward.circuit_breaker import CircuitBreaker
from src.forward.executor import ForwardExecutor

logger = logging.getLogger(__name__)

# ─── ログディレクトリ ───
LOG_DIR = os.path.join(PROJECT_ROOT, "logs", "forward")

# ─── OHLCVフェッチ設定 ───
OHLCV_FETCH_LIMIT = 300   # 戦略のwarm-up期間を十分カバーする本数（mtf_confluenceのMIN_ROWS=250を満たす）
OHLCV_RETRY_COUNT = 3     # リトライ回数
OHLCV_RETRY_BACKOFF = 2.0 # リトライ間隔（秒）

# ─── 戦略ごとのトリガー時間足マッピング ───
# この足が確定したタイミングで当該戦略のシグナルをスキャンする
STRATEGY_TRIGGER_TIMEFRAME: Dict[str, str] = {
    "mtf_confluence": "1h",   # 1h足確定時にスキャン（4h・1d はデータとして渡す）
    "rsi_divergence": "4h",   # 4h足確定時にスキャン
    "bb_reversion": "1d",     # 1d足確定時にスキャン
}

# ─── 戦略ごとの追加データ取得設定（mtf_confluence のサブ足）───
MTF_SUB_TIMEFRAMES: List[str] = ["4h", "1d"]


def _get_recommended_portfolio_id(config_path: Optional[str] = None) -> str:
    """
    portfolio_config.json の recommended_pattern を読み取り、
    実際に存在するポートフォリオIDにフォールバックする。

    recommended_pattern が存在しないIDを指している場合（例: "pattern_C_balanced_growth"）は、
    パターンCの実際のIDを探して返す。

    Args:
        config_path: portfolio_config.json のパス。None でデフォルトパス。

    Returns:
        str: 使用するポートフォリオID
    """
    if config_path is None:
        config_path = os.path.join(
            PROJECT_ROOT, "results", "fx_phase1", "portfolio_config.json"
        )

    if not os.path.exists(config_path):
        logger.warning("portfolio_config.json が見つかりません: %s", config_path)
        return "pattern_C_growth"

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    recommended = raw.get("recommended_pattern", "")
    portfolios = raw.get("portfolios", [])
    portfolio_ids = [p["portfolio_id"] for p in portfolios]

    # recommended_pattern がそのまま使えるか確認
    if recommended in portfolio_ids:
        logger.info("recommended_pattern を使用: %s", recommended)
        return recommended

    # フォールバック: "pattern_C" を含む最初のIDを返す
    for pid in portfolio_ids:
        if "pattern_C" in pid:
            logger.warning(
                "recommended_pattern '%s' が存在しません。フォールバック: '%s'",
                recommended, pid,
            )
            return pid

    # さらにフォールバック: 最後のパターン
    if portfolio_ids:
        logger.warning(
            "pattern_C が見つかりません。最後のパターンを使用: '%s'", portfolio_ids[-1]
        )
        return portfolio_ids[-1]

    return "pattern_C_growth"


def _ohlcv_to_dataframe(candles: List[Dict[str, Any]]) -> pd.DataFrame:
    """
    SaxoClient.fetch_ohlcv() の返り値を pandas DataFrame に変換する。

    Args:
        candles: fetch_ohlcv() が返すリスト

    Returns:
        pd.DataFrame: open/high/low/close/volume カラムを持つ DataFrame
    """
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(candles)
    df = df.rename(columns={
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    })
    # timestamp (ms) をインデックスに設定
    if "timestamp" in df.columns:
        df.index = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df.index.name = "datetime_index"
    return df[["open", "high", "low", "close", "volume"]]


class SignalLogger:
    """
    シグナルを JSONL ファイルに記録するロガー。

    ファイル名: logs/forward/signals_YYYYMMDD.jsonl
    フォーマット: 1行1JSON（JSONL形式）
    """

    def __init__(self, log_dir: str = LOG_DIR):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        logger.info("シグナルログディレクトリ: %s", log_dir)

    def _get_log_path(self) -> str:
        """今日の日付のログファイルパスを返す。"""
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        return os.path.join(self.log_dir, f"signals_{today}.jsonl")

    def write(self, record: Dict[str, Any]) -> None:
        """
        シグナルレコードをJSONLファイルに追記する。

        Args:
            record: シグナルレコード辞書
        """
        log_path = self._get_log_path()
        # nan を null に変換
        sanitized = {
            k: (None if isinstance(v, float) and math.isnan(v) else v)
            for k, v in record.items()
        }
        line = json.dumps(sanitized, ensure_ascii=False)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
        logger.debug("シグナル記録: %s", line)


class ForwardRunner:
    """
    フォワードテストのメインランナー。

    1. portfolio_config.json からパターンCの設定を読み込む
    2. 各戦略の get_latest_signal() を時間足スケジュールで呼び出す
    3. SaxoSim から OHLCV を取得してシグナル生成
    4. シグナルを JSONL ファイルに記録
    5. dry_run=True なら注文は出さない（現在は常に dry_run）

    Args:
        portfolio_id: ポートフォリオID。None の場合は portfolio_config.json の
                      recommended_pattern から自動取得する。
        exchange_id:  取引所ID（デフォルト: "saxo_sim"）
        dry_run:      True なら注文しない（デフォルト: True）
        config_path:  portfolio_config.json のパス（None でデフォルトパス）
    """

    def __init__(
        self,
        portfolio_id: Optional[str] = None,
        exchange_id: str = "saxo_sim",
        dry_run: bool = True,
        config_path: Optional[str] = None,
    ):
        self.exchange_id = exchange_id
        self.dry_run = dry_run
        self.config_path = config_path

        # portfolio_id の解決
        if portfolio_id is None:
            self.portfolio_id = _get_recommended_portfolio_id(config_path)
        else:
            self.portfolio_id = portfolio_id

        # ポートフォリオ設定を読み込む
        logger.info("ポートフォリオ設定を読み込み: %s", self.portfolio_id)
        self.portfolio = load_portfolio_config(
            config_path=config_path,
            portfolio_id=self.portfolio_id,
        )

        # 戦略インスタンスを事前ロード
        self._strategies: Dict[str, Any] = {}
        for entry in self.portfolio["strategies"]:
            sid = entry["strategy_id"]
            if sid not in self._strategies:
                self._strategies[sid] = load_strategy(sid)
                logger.info("戦略ロード: %s", sid)

        # SaxoClient の初期化（トークンチェック込み）
        self.saxo: Optional[SaxoClient] = None
        self._init_saxo_client()

        # シグナルロガー
        self.signal_logger = SignalLogger()

        # サーキットブレーカー
        cb_config = get_circuit_breaker_config(self.portfolio)
        self.circuit_breaker = CircuitBreaker(cb_config)

        # 注文執行モジュール（dry_run=True の場合も初期化するが注文は出さない）
        self.executor = ForwardExecutor(
            saxo_client=self.saxo,
            portfolio_config=self.portfolio,
            circuit_breaker=self.circuit_breaker,
            dry_run=self.dry_run,
        )

        # スケジューラ
        self.scheduler = ForwardScheduler()
        self._setup_scheduler()

        logger.info(
            "ForwardRunner 初期化完了: portfolio=%s, exchange=%s, dry_run=%s",
            self.portfolio_id, self.exchange_id, self.dry_run,
        )

    def _init_saxo_client(self) -> None:
        """
        SaxoClient を初期化する。

        トークン未設定・失効時は WARNING を出力して self.saxo = None にする。
        """
        try:
            self.saxo = SaxoClient(self.exchange_id)
            # トークン疎通チェック（残高取得で401を早期検知）
            try:
                self.saxo.get_balance()
                logger.info("SaxoClient 疎通チェック OK")
            except SaxoAuthError:
                logger.warning(
                    "WARNING: Saxo API 401 Unauthorized。"
                    "PAT トークンが失効している可能性があります。"
                    "Developer Portal でトークンを再発行し、.env の SAXO_SIM_TOKEN を更新してください。"
                    " フォワードテストはデータ取得できないためシグナル生成はスキップされます。"
                )
                self.saxo = None
            except Exception as exc:
                logger.warning(
                    "WARNING: SaxoClient 疎通チェックで予期しないエラー: %s", exc
                )
                # 疎通エラーは警告のみ。API は使い続ける（一時的なネットワーク障害の可能性）
        except ValueError as exc:
            logger.warning(
                "WARNING: SaxoClient 初期化エラー（トークン未設定の可能性）: %s", exc
            )
            self.saxo = None

    def _fetch_ohlcv_with_retry(
        self, symbol: str, timeframe: str, limit: int = OHLCV_FETCH_LIMIT
    ) -> Optional[pd.DataFrame]:
        """
        OHLCV を取得する（リトライ3回、失敗時は None を返す）。

        Args:
            symbol:    通貨ペア（例: "USDJPY"）
            timeframe: 時間足（"1h", "4h", "1d"）
            limit:     取得本数

        Returns:
            pd.DataFrame または None（全リトライ失敗時）
        """
        if self.saxo is None:
            logger.warning(
                "SaxoClient が利用不可のため OHLCV 取得をスキップ: %s %s",
                symbol, timeframe,
            )
            return None

        # Saxo API では "USDJPY" 形式でもスラッシュ付き "USD/JPY" でも受け付ける
        # SaxoClient.to_saxo_symbol() が内部で正規化するためそのまま渡す
        for attempt in range(1, OHLCV_RETRY_COUNT + 1):
            try:
                candles = self.saxo.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
                df = _ohlcv_to_dataframe(candles)
                logger.info(
                    "OHLCV 取得成功: %s %s, %d本 (attempt=%d)",
                    symbol, timeframe, len(df), attempt,
                )
                return df
            except SaxoAuthError:
                logger.warning(
                    "WARNING: Saxo API 401 - %s %s 取得時にトークン失効を検知 (attempt=%d)",
                    symbol, timeframe, attempt,
                )
                # 認証エラーはリトライしても無意味
                return None
            except Exception as exc:
                logger.warning(
                    "OHLCV 取得失敗: %s %s (attempt=%d/%d): %s",
                    symbol, timeframe, attempt, OHLCV_RETRY_COUNT, exc,
                )
                if attempt < OHLCV_RETRY_COUNT:
                    time.sleep(OHLCV_RETRY_BACKOFF * attempt)

        logger.error(
            "OHLCV 取得: %d回全てリトライ失敗のためスキップ: %s %s",
            OHLCV_RETRY_COUNT, symbol, timeframe,
        )
        return None

    def _scan_strategy(self, entry: Dict[str, Any], triggered_timeframe: str) -> None:
        """
        1つの戦略エントリに対してシグナルスキャンを実行し、結果を記録する。

        Args:
            entry:               portfolio_config の strategies リストの1要素
            triggered_timeframe: トリガーされた時間足
        """
        strategy_id = entry["strategy_id"]
        symbol = entry["symbol"]  # "USDJPY", "EURJPY" 等
        timeframe = entry["timeframe"]
        params = dict(entry["params"])
        params["symbol"] = symbol
        params["timeframe"] = timeframe

        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info(
            "[%s] シグナルスキャン開始: %s %s %s",
            ts_str, strategy_id, symbol, timeframe,
        )

        strategy = self._strategies.get(strategy_id)
        if strategy is None:
            logger.error("戦略インスタンスが見つかりません: %s", strategy_id)
            return

        # シグナル生成
        signal_result: Optional[Dict[str, Any]] = None

        if strategy_id == "mtf_confluence":
            # MTF戦略: 1h・4h・1d の3時間足が必要
            ohlcv_1h = self._fetch_ohlcv_with_retry(symbol, "1h")
            if ohlcv_1h is None:
                logger.warning(
                    "mtf_confluence: 1h OHLCV 取得失敗のためスキップ: %s", symbol
                )
                self._write_flat_signal(ts_str, strategy_id, symbol, timeframe)
                return

            ohlcv_dict = {"1h": ohlcv_1h}

            # 4h・1d はオプション（取得失敗してもリサンプリングでフォールバック）
            for sub_tf in MTF_SUB_TIMEFRAMES:
                sub_df = self._fetch_ohlcv_with_retry(symbol, sub_tf)
                if sub_df is not None:
                    ohlcv_dict[sub_tf] = sub_df
                else:
                    logger.info(
                        "mtf_confluence: %s OHLCV 取得失敗、リサンプリングにフォールバック: %s",
                        sub_tf, symbol,
                    )

            signal_result = strategy.get_latest_signal(ohlcv_dict, params)

        else:
            # bb_reversion, rsi_divergence: 単一時間足
            ohlcv = self._fetch_ohlcv_with_retry(symbol, timeframe)
            if ohlcv is None:
                logger.warning(
                    "%s: OHLCV 取得失敗のためスキップ: %s %s",
                    strategy_id, symbol, timeframe,
                )
                self._write_flat_signal(ts_str, strategy_id, symbol, timeframe)
                return

            signal_result = strategy.get_latest_signal(ohlcv, params)

        if signal_result is None:
            signal_result = {
                "signal": "FLAT",
                "price": float("nan"),
                "sl": float("nan"),
                "tp": float("nan"),
            }

        # シグナルをログに記録
        self._write_signal(ts_str, strategy_id, symbol, timeframe, signal_result)

    def _write_signal(
        self,
        timestamp: str,
        strategy_id: str,
        symbol: str,
        timeframe: str,
        result: Dict[str, Any],
    ) -> None:
        """
        シグナル結果を JSONL に記録する。

        Args:
            timestamp:   ISO8601 タイムスタンプ文字列
            strategy_id: 戦略ID
            symbol:      通貨ペア
            timeframe:   時間足
            result:      get_latest_signal() の返り値
        """
        signal = result.get("signal", "FLAT")
        price = result.get("price", float("nan"))
        sl = result.get("sl", float("nan"))
        tp = result.get("tp", float("nan"))

        record = {
            "timestamp": timestamp,
            "strategy": strategy_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "signal": signal,
            "price": price,
            "sl": sl,
            "tp": tp,
            "dry_run": self.dry_run,
        }

        self.signal_logger.write(record)

        signal_label = signal
        price_str = f"{price:.5f}" if not (isinstance(price, float) and math.isnan(price)) else "N/A"
        logger.info(
            "[%s] %s %s %s -> %s @ %s",
            timestamp, strategy_id, symbol, timeframe, signal_label, price_str,
        )
        print(
            f"  [{timestamp}] {strategy_id} {symbol} {timeframe} -> "
            f"{signal_label} @ {price_str}"
        )

        # ─── Executor フック: BUY/SELL シグナルの場合のみ注文執行 ───
        if signal in ("BUY", "SELL"):
            exec_signal = {
                "strategy": strategy_id,
                "symbol": symbol,
                "timeframe": timeframe,
                "signal": signal,
                "price": price,
                "sl": sl,
                "tp": tp,
            }
            try:
                exec_result = self.executor.execute_signal(exec_signal)
                status = exec_result.get("status", "unknown")
                order_id = exec_result.get("order_id")
                reason = exec_result.get("reason", "")
                logger.info(
                    "[Executor] %s %s %s %s -> status=%s order_id=%s reason=%s",
                    strategy_id, symbol, timeframe, signal,
                    status, order_id, reason,
                )
                print(
                    f"    -> 注文: status={status}"
                    + (f" order_id={order_id}" if order_id else "")
                    + (f" ({reason})" if reason and reason not in ("ok", "dry_run") else "")
                )
            except Exception as exc:
                logger.error(
                    "[Executor] 注文執行で予期しないエラー: %s %s %s: %s",
                    strategy_id, symbol, timeframe, exc,
                    exc_info=True,
                )

    def _write_flat_signal(
        self,
        timestamp: str,
        strategy_id: str,
        symbol: str,
        timeframe: str,
    ) -> None:
        """
        OHLCV取得失敗時のFLATシグナルをログに記録する。

        Args:
            timestamp:   ISO8601 タイムスタンプ文字列
            strategy_id: 戦略ID
            symbol:      通貨ペア
            timeframe:   時間足
        """
        flat_result = {
            "signal": "FLAT",
            "price": float("nan"),
            "sl": float("nan"),
            "tp": float("nan"),
        }
        self._write_signal(timestamp, strategy_id, symbol, timeframe, flat_result)

    def _get_strategies_for_timeframe(self, timeframe: str) -> List[Dict[str, Any]]:
        """
        指定時間足でスキャンすべき戦略エントリの一覧を返す。

        Args:
            timeframe: トリガーされた時間足（"1h", "4h", "1d"）

        Returns:
            List[Dict]: スキャン対象の strategies エントリのリスト
        """
        result = []
        for entry in self.portfolio["strategies"]:
            sid = entry["strategy_id"]
            trigger_tf = STRATEGY_TRIGGER_TIMEFRAME.get(sid)
            if trigger_tf is None:
                logger.warning(
                    "戦略 %s は STRATEGY_TRIGGER_TIMEFRAME に未登録。スキップします。",
                    sid,
                )
                continue
            if trigger_tf == timeframe:
                result.append(entry)
        return result

    def _on_timeframe_trigger(self, timeframe: str) -> None:
        """
        スケジューラからのコールバック。
        指定時間足でスキャンすべき全戦略を実行する。

        Args:
            timeframe: トリガーされた時間足
        """
        now_utc = datetime.now(timezone.utc)
        ts_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
        strategies = self._get_strategies_for_timeframe(timeframe)

        if not strategies:
            logger.debug("[%s] %s: スキャン対象戦略なし", ts_str, timeframe)
            return

        print(
            f"\n[{ts_str}] {timeframe} 足確定 -> "
            f"{len(strategies)} 戦略をスキャン"
        )

        for entry in strategies:
            try:
                self._scan_strategy(entry, timeframe)
            except Exception as exc:
                logger.error(
                    "[%s] 戦略スキャンでエラー: %s %s %s: %s",
                    ts_str,
                    entry.get("strategy_id", "?"),
                    entry.get("symbol", "?"),
                    entry.get("timeframe", "?"),
                    exc,
                    exc_info=True,
                )

    def _setup_scheduler(self) -> None:
        """スケジューラにコールバックを登録する。"""
        self.scheduler.add_callback("1h", self._on_timeframe_trigger)
        self.scheduler.add_callback("4h", self._on_timeframe_trigger)
        self.scheduler.add_callback("1d", self._on_timeframe_trigger)
        logger.info("スケジューラ設定完了（1h/4h/1d コールバック登録）")

    def run_once(self, timeframe: Optional[str] = None) -> None:
        """
        テスト用: 全時間足（または指定時間足）のシグナルスキャンを1回だけ即時実行する。

        Args:
            timeframe: 実行する時間足。None の場合は全時間足（1h/4h/1d）を実行。
        """
        timeframes = [timeframe] if timeframe else ["1d", "4h", "1h"]
        for tf in timeframes:
            self._on_timeframe_trigger(tf)

    def run(self, stop_event=None) -> None:
        """
        フォワードテストのメインループを開始する。

        スケジューラが各時間足の確定タイミングでシグナルスキャンをトリガーする。
        Ctrl+C または stop_event.set() で停止。

        Args:
            stop_event: threading.Event。セットされたらループを終了する。
        """
        now_utc = datetime.now(timezone.utc)
        print(f"\n{'='*60}")
        print(f"  FX Phase1 Forward Runner 起動")
        print(f"  ポートフォリオ: {self.portfolio_id}")
        print(f"  取引所: {self.exchange_id}")
        print(f"  モード: {'DRY RUN (注文なし)' if self.dry_run else 'LIVE'}")
        print(f"  起動時刻: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  シグナルログ: {LOG_DIR}")
        print(f"{'='*60}")

        strategies = self.portfolio.get("strategies", [])
        print(f"\n  監視戦略 ({len(strategies)}件):")
        for entry in strategies:
            trigger_tf = STRATEGY_TRIGGER_TIMEFRAME.get(entry["strategy_id"], "?")
            print(
                f"    - {entry['strategy_id']} {entry['symbol']} "
                f"{entry['timeframe']} (トリガー: {trigger_tf})"
            )

        print(f"\n  スケジュール (UTC):")
        print(f"    1h足: 毎時 :05")
        print(f"    4h足: 00:05, 04:05, 08:05, 12:05, 16:05, 20:05")
        print(f"    1d足: 毎日 00:05")
        print(f"\n  スケジューラ開始 (Ctrl+C で停止)\n")

        self.scheduler.run(stop_event=stop_event)


def main():
    """CLI エントリポイント。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="FX Phase1 フォワードテスト ランナー"
    )
    parser.add_argument(
        "--portfolio-id", default=None,
        help="ポートフォリオID（省略時は portfolio_config.json の recommended_pattern を使用）"
    )
    parser.add_argument(
        "--exchange", default="saxo_sim",
        choices=["saxo_sim", "saxo"],
        help="取引所ID（デフォルト: saxo_sim）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        dest="dry_run",
        help="ドライランモード（注文しない）。デフォルト ON"
    )
    parser.add_argument(
        "--no-dry-run", action="store_false", dest="dry_run",
        help="ライブモード（実際に注文を発注する）"
    )
    parser.add_argument(
        "--run-once", action="store_true",
        help="スケジューラを起動せず、全時間足のシグナルスキャンを1回だけ実行して終了"
    )
    parser.add_argument(
        "--timeframe", default=None,
        choices=["1h", "4h", "1d"],
        help="--run-once 時に特定の時間足のみ実行（省略時は全足）"
    )
    args = parser.parse_args()

    runner = ForwardRunner(
        portfolio_id=args.portfolio_id,
        exchange_id=args.exchange,
        dry_run=args.dry_run,
    )

    if args.run_once:
        runner.run_once(timeframe=args.timeframe)
    else:
        runner.run()


if __name__ == "__main__":
    main()
