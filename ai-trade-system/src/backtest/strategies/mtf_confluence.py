"""
戦略2: Multi-Timeframe Confluence (MTF)

ロジック:
    - 日足: SMA(200)上位 → 上昇トレンド確認
    - 4h足: 直近高値更新または20EMAバウンス
    - 1h足: RSI(14) > 50 かつ価格が4h足サポートに接触でロングエントリー
    - ショート方向: 日足SMA200以下、4h安値更新、RSI < 50

エグジット:
    - TP: RR=2.0 相当の価格
    - SL: エントリー価格から sl_pct 分
    - 最大保有: hold_bars バー

実装注意:
    - MTF戦略は複数時間足のデータを必要とする
    - 本モジュールは1h足データで完結する「疑似MTF」実装
      （日足・4h足データを1h足にリサンプリングして再現）
    - 本番運用では複数DataFrameを渡す拡張を推奨

期待勝率の根拠:
    - SignalWavesAI: 全時間足一致で成功確率70〜80%
    - LiteFinance: 単時間足比較で30〜40%の勝率向上
    - backtesting.py公式のMTF実装例

参考文献:
    - https://signalwavesai.com/articles/multi-timeframe-analysis
    - https://www.litefinance.org/blog/for-beginners/technical-analysis/multiple-time-frame-analysis/
    - https://kernc.github.io/backtesting.py/doc/examples/Multiple%20Time%20Frames.html
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
except ImportError:
    ta = None  # type: ignore

from .base import (
    BaseStrategy,
    SIGNAL_LONG,
    SIGNAL_SHORT,
    SIGNAL_NONE,
    validate_dataframe,
    make_signal_df,
    calc_tp_sl,
    empty_signals,
)
from .filters import (
    sma200_long_filter,
    sma200_short_filter,
    atr_volatility_filter,
    session_time_filter,
    economic_event_filter,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# パラメータ定義
# ---------------------------------------------------------------------------

DEFAULT_PARAMS: Dict[str, Any] = {
    "daily_sma_period": 200,       # 日足トレンドフィルター（1h足にリサンプリング）
    "h4_ema_period": 20,           # 4h足EMAバウンス
    "h1_rsi_period": 14,           # 1h足RSI
    "rsi_long_threshold": 50.0,    # ロングはRSI > 50
    "rsi_short_threshold": 50.0,   # ショートはRSI < 50
    "rr_ratio": 2.0,               # TP = SL * rr_ratio
    "sl_pct": 0.005,               # SL幅（エントリー価格比）
    "hold_bars": 24,               # 最大保有（1h足換算）
    "require_all_timeframes": True, # 全時間足一致必須
}

PARAM_GRID: Dict[str, list] = {
    "daily_sma_period": [100, 200],
    "h4_ema_period": [15, 20, 25],
    "h1_rsi_period": [10, 14],
    "rsi_long_threshold": [45.0, 50.0, 55.0],
    "rr_ratio": [1.5, 2.0, 2.5],
    "sl_pct": [0.003, 0.005, 0.007],
    "hold_bars": [12, 24, 48],
}

MIN_ROWS = 250  # 日足SMA200の計算に1h足で約200日分必要

# リアルタイムシグナル生成に必要な最低バー数（時間足別）
# daily_sma_period(最大200)が最大要件
MIN_BARS_1H: int = 100    # 1h足: RSI計算 + エントリー判定
MIN_BARS_4H: int = 60     # 4h足: EMA(最大25) + マージン
MIN_BARS_DAILY: int = 100 # 日足: SMA(最大200)の計算に必要（省メモリ版は100を基準）
# 後方互換のための代表値（1h足基準で複合使用時の最大値）
MIN_BARS: int = MIN_BARS_1H


# ---------------------------------------------------------------------------
# リサンプリングユーティリティ
# ---------------------------------------------------------------------------


def _resample_to_higher_tf(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    1h足データを指定ルールでリサンプリングする（4h, 1D等）。

    Args:
        df: 1h足OHLCVデータ（DatetimeIndexまたはdatetimeカラム）
        rule: pandas resample rule（例: "4h", "1D"）

    Returns:
        pd.DataFrame: リサンプリングされたOHLCV
    """
    if isinstance(df.index, pd.DatetimeIndex):
        df_dt = df.copy()
    elif "datetime" in df.columns:
        df_dt = df.set_index(pd.to_datetime(df["datetime"]))
    elif "timestamp" in df.columns:
        ts = df["timestamp"]
        if ts.max() > 1e12:
            df_dt = df.set_index(pd.to_datetime(ts, unit="ms"))
        else:
            df_dt = df.set_index(pd.to_datetime(ts, unit="s"))
    else:
        logger.warning("_resample_to_higher_tf: no datetime index found")
        return pd.DataFrame()

    resampled = df_dt[["open", "high", "low", "close"]].resample(rule).agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}
    ).dropna()

    return resampled


def _align_higher_tf_to_1h(
    df_1h: pd.DataFrame,
    df_higher: pd.DataFrame,
    col: str,
) -> pd.Series:
    """
    上位足のデータを1h足のインデックスにforward-fillで整合させる。

    Args:
        df_1h: 1h足DataFrame（DatetimeIndexを持つ）
        df_higher: 上位足DataFrame（DatetimeIndexを持つ）
        col: 取得するカラム名

    Returns:
        pd.Series: 1h足インデックスにアライメントされた上位足データ
    """
    series_higher = df_higher[col].reindex(df_1h.index, method="ffill")
    return series_higher


# ---------------------------------------------------------------------------
# メイン関数
# ---------------------------------------------------------------------------


def generate_signals(
    df: pd.DataFrame,
    params: Dict[str, Any],
    filters: Dict[str, bool],
    df_4h: Optional[pd.DataFrame] = None,
    df_1d: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    マルチタイムフレーム・コンフルエンスのシグナルを生成する。

    Args:
        df: 1h足OHLCVデータ（主要入力）
        params: 戦略パラメータ（DEFAULT_PARAMSをベースに上書き）
        filters: フィルター有効/無効フラグ
            - use_sma200 (bool): SMA200トレンドフィルター
            - use_atr    (bool): ATRボラティリティフィルター
            - use_session (bool): セッション時間フィルター
            - use_event  (bool): 重要指標回避フィルター
        df_4h: 4h足データ（Noneなら1h足からリサンプリング）
        df_1d: 日足データ（Noneなら1h足からリサンプリング）

    Returns:
        pd.DataFrame: 元DFに signal / tp_price / sl_price / hold_bars カラムを追加
    """
    p = {**DEFAULT_PARAMS, **params}

    if not validate_dataframe(df, min_rows=MIN_ROWS):
        return empty_signals(df, "MTF Confluence: data validation failed")

    logger.info(
        "MTF Confluence: generating signals | rows=%d | params=%s",
        len(df),
        {k: v for k, v in p.items()},
    )

    df_orig = df  # 例外時のempty_signals用に元dfを保存

    try:
        # DatetimeIndexへの変換（make_signal_df の前に行い、インデックスを統一する）
        if not isinstance(df.index, pd.DatetimeIndex):
            if "datetime" in df.columns:
                df = df.set_index(pd.to_datetime(df["datetime"]))
            elif "timestamp" in df.columns:
                ts = df["timestamp"]
                unit = "ms" if ts.max() > 1e12 else "s"
                df = df.set_index(pd.to_datetime(ts, unit=unit))

        result = make_signal_df(df)
        close_1h = df["close"]

        # 4h足データ準備
        if df_4h is None:
            df_4h_rs = _resample_to_higher_tf(df, "4h")
        else:
            df_4h_rs = df_4h

        # 日足データ準備
        if df_1d is None:
            df_1d_rs = _resample_to_higher_tf(df, "1D")
        else:
            df_1d_rs = df_1d

        # --- 日足: SMA(200)トレンド ---
        if ta is not None:
            daily_sma = ta.sma(df_1d_rs["close"], length=p["daily_sma_period"])
        else:
            daily_sma = df_1d_rs["close"].rolling(p["daily_sma_period"]).mean()

        daily_trend_up = df_1d_rs["close"] > daily_sma     # 上昇トレンド
        daily_trend_down = df_1d_rs["close"] < daily_sma   # 下降トレンド

        # 1h足インデックスにアライメント
        daily_trend_up_1h = _align_higher_tf_to_1h(df, daily_trend_up.to_frame("v"), "v")
        daily_trend_down_1h = _align_higher_tf_to_1h(df, daily_trend_down.to_frame("v"), "v")

        # --- 4h足: EMA(20)バウンス ---
        if ta is not None:
            h4_ema = ta.ema(df_4h_rs["close"], length=p["h4_ema_period"])
        else:
            h4_ema = df_4h_rs["close"].ewm(span=p["h4_ema_period"], adjust=False).mean()

        # 4h足: closeがEMAに接触（close < EMAからEMA以上になった＝バウンス）
        h4_above_ema = df_4h_rs["close"] > h4_ema
        h4_below_ema = df_4h_rs["close"] < h4_ema

        h4_above_1h = _align_higher_tf_to_1h(df, h4_above_ema.to_frame("v"), "v")
        h4_below_1h = _align_higher_tf_to_1h(df, h4_below_ema.to_frame("v"), "v")

        # --- 1h足: RSI ---
        if ta is not None:
            rsi_1h = ta.rsi(close_1h, length=p["h1_rsi_period"])
        else:
            delta = close_1h.diff()
            gain = delta.clip(lower=0).rolling(p["h1_rsi_period"]).mean()
            loss = (-delta.clip(upper=0)).rolling(p["h1_rsi_period"]).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi_1h = 100 - (100 / (1 + rs))

        rsi_long_ok = rsi_1h > p["rsi_long_threshold"]
        rsi_short_ok = rsi_1h < p["rsi_short_threshold"]

        # --- シグナル条件 ---
        # ロング: 日足上昇 + 4h EMA上 + 1h RSI>50
        long_cond = (
            daily_trend_up_1h.fillna(False)
            & h4_above_1h.fillna(False)
            & rsi_long_ok.fillna(False)
        )

        # ショート: 日足下降 + 4h EMA下 + 1h RSI<50
        short_cond = (
            daily_trend_down_1h.fillna(False)
            & h4_below_1h.fillna(False)
            & rsi_short_ok.fillna(False)
        )

        # --- オプショナルフィルター ---
        if filters.get("use_atr", False):
            atr_ok = atr_volatility_filter(df, min_atr=0.10)
            long_cond = long_cond & atr_ok
            short_cond = short_cond & atr_ok

        if filters.get("use_session", False):
            session_ok = session_time_filter(df, allow_tokyo=False)
            long_cond = long_cond & session_ok
            short_cond = short_cond & session_ok

        if filters.get("use_event", False):
            event_ok = economic_event_filter(df)
            long_cond = long_cond & event_ok
            short_cond = short_cond & event_ok

        # --- TP/SL設定 ---
        tp_pct = p["sl_pct"] * p["rr_ratio"]
        sl_pct = p["sl_pct"]

        for i in result.index[long_cond.reindex(result.index, fill_value=False)]:
            entry = close_1h.loc[i]
            tp, sl = calc_tp_sl(entry, SIGNAL_LONG, tp_pct, sl_pct)
            result.at[i, "signal"] = SIGNAL_LONG
            result.at[i, "tp_price"] = tp
            result.at[i, "sl_price"] = sl
            result.at[i, "hold_bars"] = p["hold_bars"]

        for i in result.index[short_cond.reindex(result.index, fill_value=False)]:
            entry = close_1h.loc[i]
            tp, sl = calc_tp_sl(entry, SIGNAL_SHORT, tp_pct, sl_pct)
            result.at[i, "signal"] = SIGNAL_SHORT
            result.at[i, "tp_price"] = tp
            result.at[i, "sl_price"] = sl
            result.at[i, "hold_bars"] = p["hold_bars"]

    except Exception as exc:
        logger.error("MTF Confluence: unexpected error: %s", exc, exc_info=True)
        return empty_signals(df_orig, f"MTF Confluence: error: {exc}")


    long_count = int((result["signal"] == SIGNAL_LONG).sum())
    short_count = int((result["signal"] == SIGNAL_SHORT).sum())
    logger.info(
        "MTF Confluence: signals generated | long=%d | short=%d | total=%d",
        long_count,
        short_count,
        long_count + short_count,
    )

    return result


# ---------------------------------------------------------------------------
# 戦略クラス
# ---------------------------------------------------------------------------


class MTFConfluenceStrategy(BaseStrategy):
    """マルチタイムフレーム・コンフルエンス戦略。"""

    strategy_id = "mtf_confluence"
    description = "Multi-Timeframe Confluence: Daily trend + 4h EMA + 1h RSI"
    DEFAULT_PARAMS = DEFAULT_PARAMS

    # リアルタイムシグナル生成に必要な最低バー数（時間足別）
    MIN_BARS: int = MIN_BARS
    MIN_BARS_1H: int = MIN_BARS_1H
    MIN_BARS_4H: int = MIN_BARS_4H
    MIN_BARS_DAILY: int = MIN_BARS_DAILY

    def generate_signals(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        filters: Dict[str, bool],
    ) -> pd.DataFrame:
        return generate_signals(df, self.get_params(params), filters)

    def get_latest_signal(
        self,
        ohlcv_dict: Dict[str, pd.DataFrame],
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        最新のOHLCVデータ（複数時間足）から直近のシグナルを1件返す。

        MTF戦略は日足・4h足・1h足の3時間足を使用する。
        各時間足のデータをohlcv_dictに渡す。1h足のみ渡した場合は
        内部リサンプリングで4h足・日足を生成する（バックテスト互換）。

        warm-up期間不足時は例外を投げず FLAT を返す。

        Args:
            ohlcv_dict: 時間足をキーとするDataFrameの辞書。
                {
                    "1h": pd.DataFrame,   # 必須: 1h足OHLCV（MIN_BARS_1H本以上）
                    "4h": pd.DataFrame,   # 任意: 4h足OHLCV（MIN_BARS_4H本以上）
                    "1d": pd.DataFrame,   # 任意: 日足OHLCV（MIN_BARS_DAILY本以上）
                }
                "4h"/"1d"が省略された場合は1h足からリサンプリングして使用する。
            params: 戦略パラメータ（portfolio_config.jsonのparams）

        Returns:
            dict: {
                "signal": "BUY" | "SELL" | "FLAT",
                "price": float,   # 現在の終値（1h足の最終バー）
                "sl": float,      # ストップロス価格
                "tp": float,      # テイクプロフィット価格
                "strategy": str,  # 戦略ID
                "symbol": str,    # 通貨ペア（paramsに"symbol"キーがある場合）
                "timeframe": str, # 時間足（"1h"固定）
                "timestamp": str  # ISOフォーマットのタイムスタンプ（1h足最終バー）
            }
        """
        _flat_base: Dict[str, Any] = {
            "signal": "FLAT",
            "price": float("nan"),
            "sl": float("nan"),
            "tp": float("nan"),
            "strategy": self.strategy_id,
            "symbol": params.get("symbol", ""),
            "timeframe": "1h",
            "timestamp": "",
        }

        # 1h足データの必須チェック
        ohlcv_1h = ohlcv_dict.get("1h") if ohlcv_dict else None
        if ohlcv_1h is None or len(ohlcv_1h) < self.MIN_BARS_1H:
            logger.warning(
                "MTF Confluence get_latest_signal: insufficient 1h bars %d (need %d)",
                0 if ohlcv_1h is None else len(ohlcv_1h),
                self.MIN_BARS_1H,
            )
            return _flat_base

        # 4h足・日足データの取得（省略時はNoneのままにしてgenerate_signals内でリサンプリング）
        ohlcv_4h: Optional[pd.DataFrame] = ohlcv_dict.get("4h")
        ohlcv_1d: Optional[pd.DataFrame] = ohlcv_dict.get("1d")

        # 4h足が渡された場合の最低バー数チェック
        if ohlcv_4h is not None and len(ohlcv_4h) < self.MIN_BARS_4H:
            logger.warning(
                "MTF Confluence get_latest_signal: insufficient 4h bars %d (need %d), "
                "falling back to resample from 1h",
                len(ohlcv_4h),
                self.MIN_BARS_4H,
            )
            ohlcv_4h = None  # リサンプリングにフォールバック

        # 日足が渡された場合の最低バー数チェック
        if ohlcv_1d is not None and len(ohlcv_1d) < self.MIN_BARS_DAILY:
            logger.warning(
                "MTF Confluence get_latest_signal: insufficient daily bars %d (need %d), "
                "falling back to resample from 1h",
                len(ohlcv_1d),
                self.MIN_BARS_DAILY,
            )
            ohlcv_1d = None  # リサンプリングにフォールバック

        try:
            merged_params = self.get_params(params)
            filters: Dict[str, bool] = {}
            signals_df = generate_signals(
                ohlcv_1h, merged_params, filters,
                df_4h=ohlcv_4h,
                df_1d=ohlcv_1d,
            )

            # 最終行のシグナルを取得
            last_row = signals_df.iloc[-1]
            last_bar = ohlcv_1h.iloc[-1]
            sig_val = int(last_row["signal"])

            if sig_val == SIGNAL_LONG:
                signal_str = "BUY"
            elif sig_val == SIGNAL_SHORT:
                signal_str = "SELL"
            else:
                signal_str = "FLAT"

            # タイムスタンプ取得（インデックスまたはカラムから）
            ts_str = ""
            last_index = signals_df.index[-1]
            if isinstance(last_index, pd.Timestamp):
                ts_str = last_index.isoformat()
            elif "datetime" in ohlcv_1h.columns:
                ts_str = str(ohlcv_1h["datetime"].iloc[-1])
            elif "timestamp" in ohlcv_1h.columns:
                ts_str = str(ohlcv_1h["timestamp"].iloc[-1])

            return {
                "signal": signal_str,
                "price": float(last_bar["close"]),
                "sl": float(last_row["sl_price"]) if not pd.isna(last_row["sl_price"]) else float("nan"),
                "tp": float(last_row["tp_price"]) if not pd.isna(last_row["tp_price"]) else float("nan"),
                "strategy": self.strategy_id,
                "symbol": params.get("symbol", ""),
                "timeframe": "1h",
                "timestamp": ts_str,
            }

        except Exception as exc:
            logger.error(
                "MTF Confluence get_latest_signal: unexpected error: %s", exc, exc_info=True
            )
            return _flat_base
