"""
戦略1: BB Mean Reversion + Trend Filter

ロジック:
    - ボリンジャーバンド(20, 2.0)の下限タッチでロングエントリー
    - BB上限タッチでショートエントリー
    - RSI(14) < rsi_oversold でロング過売り確認
    - RSI(14) > rsi_overbought でショート過買い確認
    - フィルター有効時: SMA(200)でトレンド方向を制限

エグジット:
    - TP: BB中線（SMA20）到達
    - SL: エントリー価格から sl_pct 分
    - 最大保有: hold_bars バー

期待勝率の根拠:
    - QuantifiedStrategies.com: MACD + Bollinger Bands組合せで勝率78%、平均1.4%/trade
    - BB下限bounce戦略: 60%超の勝率（レンジ相場）
    - SMA200フィルター追加でDD削減と勝率向上が実証済み

参考文献:
    - https://www.quantifiedstrategies.com/macd-and-bollinger-bands-strategy/
    - https://www.quantifiedstrategies.com/bollinger-bands-trading-strategy/
    - https://tradecodelabs.com/indicators/tcl-boll-bands-trader/
"""

from __future__ import annotations

import logging
from typing import Any, Dict

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
    "bb_period": 20,
    "bb_std": 2.0,
    "rsi_period": 14,
    "rsi_oversold": 40.0,
    "rsi_overbought": 60.0,
    "tp_pct": 0.003,       # 0.3%
    "sl_pct": 0.005,       # 0.5%
    "hold_bars": 20,
}

PARAM_GRID: Dict[str, list] = {
    "bb_period": [15, 20, 25],
    "bb_std": [1.8, 2.0, 2.2],
    "rsi_period": [10, 14],
    "rsi_oversold": [35.0, 40.0, 45.0],
    "rsi_overbought": [55.0, 60.0, 65.0],
    "tp_pct": [0.002, 0.003, 0.005],
    "sl_pct": [0.003, 0.005, 0.007],
    "hold_bars": [10, 20, 30],
}

MIN_ROWS = 50

# リアルタイムシグナル生成に必要な最低バー数
# BB period(最大25) + RSI period(最大14) + マージン → 50本
MIN_BARS = 50


# ---------------------------------------------------------------------------
# メイン関数
# ---------------------------------------------------------------------------


def generate_signals(
    df: pd.DataFrame,
    params: Dict[str, Any],
    filters: Dict[str, bool],
) -> pd.DataFrame:
    """
    BBMean Reversionのシグナルを生成する。

    Args:
        df: OHLCVデータ（timestamp/datetime, open, high, low, close, volume）
        params: 戦略パラメータ（DEFAULT_PARAMSをベースに上書き）
        filters: フィルター有効/無効フラグ
            - use_sma200 (bool): SMA200トレンドフィルター
            - use_atr    (bool): ATRボラティリティフィルター
            - use_session (bool): セッション時間フィルター
            - use_event  (bool): 重要指標回避フィルター

    Returns:
        pd.DataFrame: 元DFに signal / tp_price / sl_price / hold_bars カラムを追加
    """
    # パラメータマージ
    p = {**DEFAULT_PARAMS, **params}

    # データ検証
    if not validate_dataframe(df, min_rows=MIN_ROWS):
        return empty_signals(df, "BB Reversion: data validation failed")

    logger.info(
        "BB Reversion: generating signals | rows=%d | params=%s | filters=%s",
        len(df),
        {k: v for k, v in p.items()},
        filters,
    )

    result = make_signal_df(df)

    try:
        close = df["close"]
        high = df["high"]
        low = df["low"]

        # BB計算
        if ta is not None:
            bbands = ta.bbands(close, length=p["bb_period"], std=p["bb_std"])
            if bbands is None or bbands.empty:
                return empty_signals(df, "BB Reversion: bbands calculation failed")
            # pandas_ta の列名: BBL, BBM, BBU
            bb_lower = bbands.filter(like="BBL").iloc[:, 0]
            bb_middle = bbands.filter(like="BBM").iloc[:, 0]
            bb_upper = bbands.filter(like="BBU").iloc[:, 0]
        else:
            sma = close.rolling(p["bb_period"]).mean()
            std = close.rolling(p["bb_period"]).std(ddof=0)
            bb_lower = sma - p["bb_std"] * std
            bb_middle = sma
            bb_upper = sma + p["bb_std"] * std

        # RSI計算
        if ta is not None:
            rsi = ta.rsi(close, length=p["rsi_period"])
        else:
            delta = close.diff()
            gain = delta.clip(lower=0).rolling(p["rsi_period"]).mean()
            loss = (-delta.clip(upper=0)).rolling(p["rsi_period"]).mean()
            rs = gain / loss.replace(0, np.nan)
            rsi = 100 - (100 / (1 + rs))

        # シグナル条件
        # ロング: closeがBB下限以下 かつ RSIが過売り
        long_cond = (close <= bb_lower) & (rsi < p["rsi_oversold"])
        # ショート: closeがBB上限以上 かつ RSIが過買い
        short_cond = (close >= bb_upper) & (rsi > p["rsi_overbought"])

        # フィルター適用
        if filters.get("use_sma200", False):
            long_ok = sma200_long_filter(df)
            short_ok = sma200_short_filter(df)
            long_cond = long_cond & long_ok
            short_cond = short_cond & short_ok

        if filters.get("use_atr", False):
            atr_ok = atr_volatility_filter(df, min_atr=0.10, max_atr=0.80)
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

        # TP/SLをBB中線基準で計算（pct_fallbackあり）
        for i in result.index[long_cond.reindex(result.index, fill_value=False)]:
            entry = close.loc[i]
            # TPはBB中線（ATRフォールバックとしてtp_pct）
            bb_mid_val = float(bb_middle.loc[i]) if not pd.isna(bb_middle.loc[i]) else entry * (1 + p["tp_pct"])
            tp = max(bb_mid_val, entry)
            sl = entry * (1 - p["sl_pct"])
            result.at[i, "signal"] = SIGNAL_LONG
            result.at[i, "tp_price"] = tp
            result.at[i, "sl_price"] = sl
            result.at[i, "hold_bars"] = p["hold_bars"]

        for i in result.index[short_cond.reindex(result.index, fill_value=False)]:
            entry = close.loc[i]
            bb_mid_val = float(bb_middle.loc[i]) if not pd.isna(bb_middle.loc[i]) else entry * (1 - p["tp_pct"])
            tp = min(bb_mid_val, entry)
            sl = entry * (1 + p["sl_pct"])
            result.at[i, "signal"] = SIGNAL_SHORT
            result.at[i, "tp_price"] = tp
            result.at[i, "sl_price"] = sl
            result.at[i, "hold_bars"] = p["hold_bars"]

    except Exception as exc:
        logger.error("BB Reversion: unexpected error: %s", exc, exc_info=True)
        return empty_signals(df, f"BB Reversion: error: {exc}")

    long_count = int((result["signal"] == SIGNAL_LONG).sum())
    short_count = int((result["signal"] == SIGNAL_SHORT).sum())
    logger.info(
        "BB Reversion: signals generated | long=%d | short=%d | total=%d",
        long_count,
        short_count,
        long_count + short_count,
    )

    return result


# ---------------------------------------------------------------------------
# 戦略クラス（StrategyRegistryで使用）
# ---------------------------------------------------------------------------


class BBReversionStrategy(BaseStrategy):
    """ボリンジャーバンド逆張り + トレンドフィルター戦略。"""

    strategy_id = "bb_reversion"
    description = "Bollinger Band Mean Reversion + SMA200 Trend Filter"
    DEFAULT_PARAMS = DEFAULT_PARAMS

    # リアルタイムシグナル生成に必要な最低バー数
    MIN_BARS: int = MIN_BARS

    def generate_signals(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        filters: Dict[str, bool],
    ) -> pd.DataFrame:
        return generate_signals(df, self.get_params(params), filters)

    def get_latest_signal(
        self,
        ohlcv: pd.DataFrame,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        最新のOHLCVデータから直近のシグナルを1件返す。

        warm-up期間（MIN_BARS本）を含む最新N本のOHLCVを受け取り、
        最後のバーに対応するシグナルを返す。
        データ不足時は例外を投げず FLAT を返す。

        Args:
            ohlcv: 最新N本のOHLCVデータ（MIN_BARS本以上推奨）。
                   カラム: open, high, low, close（volume任意）
            params: 戦略パラメータ（portfolio_config.jsonのparams）

        Returns:
            dict: {
                "signal": "BUY" | "SELL" | "FLAT",
                "price": float,   # 現在の終値
                "sl": float,      # ストップロス価格
                "tp": float,      # テイクプロフィット価格
                "strategy": str,  # 戦略ID
                "symbol": str,    # 通貨ペア（paramsに"symbol"キーがある場合）
                "timeframe": str, # 時間足（paramsに"timeframe"キーがある場合）
                "timestamp": str  # ISOフォーマットのタイムスタンプ（最終バー）
            }
        """
        _flat_base: Dict[str, Any] = {
            "signal": "FLAT",
            "price": float("nan"),
            "sl": float("nan"),
            "tp": float("nan"),
            "strategy": self.strategy_id,
            "symbol": params.get("symbol", ""),
            "timeframe": params.get("timeframe", ""),
            "timestamp": "",
        }

        # warm-up期間チェック
        if ohlcv is None or len(ohlcv) < self.MIN_BARS:
            logger.warning(
                "BB Reversion get_latest_signal: insufficient bars %d (need %d)",
                0 if ohlcv is None else len(ohlcv),
                self.MIN_BARS,
            )
            return _flat_base

        try:
            merged_params = self.get_params(params)
            # フィルターはforward-test文脈では無効化（引数で制御可能にするため空dict）
            filters: Dict[str, bool] = {}
            signals_df = generate_signals(ohlcv, merged_params, filters)

            # 最終行のシグナルを取得
            last_row = signals_df.iloc[-1]
            last_bar = ohlcv.iloc[-1]
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
            elif "datetime" in ohlcv.columns:
                ts_str = str(ohlcv["datetime"].iloc[-1])
            elif "timestamp" in ohlcv.columns:
                ts_str = str(ohlcv["timestamp"].iloc[-1])

            return {
                "signal": signal_str,
                "price": float(last_bar["close"]),
                "sl": float(last_row["sl_price"]) if not pd.isna(last_row["sl_price"]) else float("nan"),
                "tp": float(last_row["tp_price"]) if not pd.isna(last_row["tp_price"]) else float("nan"),
                "strategy": self.strategy_id,
                "symbol": params.get("symbol", ""),
                "timeframe": params.get("timeframe", ""),
                "timestamp": ts_str,
            }

        except Exception as exc:
            logger.error(
                "BB Reversion get_latest_signal: unexpected error: %s", exc, exc_info=True
            )
            return _flat_base
