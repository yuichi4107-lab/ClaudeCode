"""
戦略5: Heikin-Ashi Trend Following + EMA Filter

ロジック:
    1. Heikin-Ashi（HA）ローソク足を計算（通常OHLCからHA-OHLC変換）
    2. HA陽線（HA_close > HA_open）が連続 consecutive_bars 本以上 → ロングエントリー
    3. HA陰線（HA_close < HA_open）が連続 consecutive_bars 本以上 → ショートエントリー
    4. フィルター: 価格がEMA(ema_period)より上ならロング許可、下ならショート許可
    5. エグジット: HA色変化（反対方向の確定）またはTP/SL

HA変換式（決定論的、乱数なし）:
    HA_Close[i] = (O[i] + H[i] + L[i] + C[i]) / 4
    HA_Open[i]  = (HA_Open[i-1] + HA_Close[i-1]) / 2   （初回は(O[0]+C[0])/2）
    HA_High[i]  = max(H[i], HA_Open[i], HA_Close[i])
    HA_Low[i]   = min(L[i], HA_Open[i], HA_Close[i])

期待勝率の根拠:
    - QuantVPS: EMA(50)フィルター追加でAAPL株バックテストで勝率62.7%、PF 1.81
    - EMAフィルター有無の差: 勝率約20%pt向上（QuantVPS実証）
    - USDJPYのトレンド相場（円安・円高サイクル）との相性が良い

参考文献:
    - https://www.quantvps.com/blog/heikin-ashi-strategy-for-trend-trading
    - https://www.quantifiedstrategies.com/heikin-ashi-trading-strategy/
    - https://www.asiaforexmentor.com/heiken-ashi-trading-strategy/
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
    atr_volatility_filter,
    session_time_filter,
    economic_event_filter,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# パラメータ定義
# ---------------------------------------------------------------------------

DEFAULT_PARAMS: Dict[str, Any] = {
    "ema_period": 50,           # EMAフィルター期間
    "consecutive_bars": 3,      # 連続HA同色バー数
    "tp_pct": 0.005,            # 0.5%
    "sl_pct": 0.003,            # 0.3%
    "hold_bars": 20,
}

PARAM_GRID: Dict[str, list] = {
    "ema_period": [30, 50, 100],
    "consecutive_bars": [2, 3, 4],
    "tp_pct": [0.003, 0.005, 0.008],
    "sl_pct": [0.002, 0.003, 0.005],
    "hold_bars": [10, 20, 30],
}

MIN_ROWS = 60


# ---------------------------------------------------------------------------
# HA変換関数
# ---------------------------------------------------------------------------


def calc_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """
    通常のOHLCデータからHeikin-Ashi OHLCを計算する。

    HA変換は決定論的（乱数不使用）。初期値のみ最初のバーのO/Cの平均を使用。

    Args:
        df: OHLCVデータ（open, high, low, close 必須）

    Returns:
        pd.DataFrame: ha_open, ha_high, ha_low, ha_close カラムを持つDataFrame
    """
    close = df["close"].values
    open_ = df["open"].values
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    ha_close = np.zeros(n)
    ha_open = np.zeros(n)
    ha_high = np.zeros(n)
    ha_low = np.zeros(n)

    # HA_Close
    ha_close[:] = (open_ + high + low + close) / 4.0

    # HA_Open（最初のバーはO/Cの平均）
    ha_open[0] = (open_[0] + close[0]) / 2.0
    for i in range(1, n):
        ha_open[i] = (ha_open[i - 1] + ha_close[i - 1]) / 2.0

    # HA_High / HA_Low
    for i in range(n):
        ha_high[i] = max(high[i], ha_open[i], ha_close[i])
        ha_low[i] = min(low[i], ha_open[i], ha_close[i])

    ha_df = pd.DataFrame(
        {
            "ha_open": ha_open,
            "ha_high": ha_high,
            "ha_low": ha_low,
            "ha_close": ha_close,
        },
        index=df.index,
    )

    return ha_df


# ---------------------------------------------------------------------------
# メイン関数
# ---------------------------------------------------------------------------


def generate_signals(
    df: pd.DataFrame,
    params: Dict[str, Any],
    filters: Dict[str, bool],
) -> pd.DataFrame:
    """
    Heikin-Ashiトレンドフォロー + EMAフィルターのシグナルを生成する。

    Args:
        df: OHLCVデータ
        params: 戦略パラメータ（DEFAULT_PARAMSをベースに上書き）
        filters: フィルター有効/無効フラグ
            - use_ema    (bool): EMAトレンドフィルター（最重要）
            - use_atr    (bool): ATRボラティリティフィルター
            - use_session (bool): セッション時間フィルター
            - use_event  (bool): 重要指標回避フィルター

    Returns:
        pd.DataFrame: 元DFに signal / tp_price / sl_price / hold_bars カラムを追加
    """
    p = {**DEFAULT_PARAMS, **params}

    if not validate_dataframe(df, min_rows=MIN_ROWS):
        return empty_signals(df, "HA Trend: data validation failed")

    logger.info(
        "HA Trend: generating signals | rows=%d | ema=%d | consecutive=%d",
        len(df),
        p["ema_period"],
        p["consecutive_bars"],
    )

    result = make_signal_df(df)

    try:
        close = df["close"]

        # HA計算
        ha_df = calc_heikin_ashi(df)
        ha_close = ha_df["ha_close"]
        ha_open = ha_df["ha_open"]

        # HA色: 陽線=True、陰線=False
        ha_bullish = ha_close > ha_open
        ha_bearish = ha_close < ha_open

        # EMA計算
        if ta is not None:
            ema = ta.ema(close, length=p["ema_period"])
        else:
            ema = close.ewm(span=p["ema_period"], adjust=False).mean()

        # フィルター用マスク
        ema_long_ok = (close > ema).fillna(False)
        ema_short_ok = (close < ema).fillna(False)

        atr_ok = (
            atr_volatility_filter(df, min_atr=0.05)
            if filters.get("use_atr", False)
            else pd.Series(True, index=df.index)
        )
        session_ok = (
            session_time_filter(df, allow_tokyo=False)
            if filters.get("use_session", False)
            else pd.Series(True, index=df.index)
        )
        event_ok = (
            economic_event_filter(df)
            if filters.get("use_event", False)
            else pd.Series(True, index=df.index)
        )

        consecutive = p["consecutive_bars"]
        orig_index = df.index.tolist()

        ha_bullish_arr = ha_bullish.values
        ha_bearish_arr = ha_bearish.values

        for pos in range(consecutive, len(df)):
            orig_i = orig_index[pos]

            # フィルターチェック
            if not atr_ok.loc[orig_i] or not session_ok.loc[orig_i] or not event_ok.loc[orig_i]:
                continue

            # 連続HA陽線チェック（ロング条件）
            all_bullish = all(ha_bullish_arr[pos - consecutive : pos])
            # 連続HA陰線チェック（ショート条件）
            all_bearish = all(ha_bearish_arr[pos - consecutive : pos])

            use_ema = filters.get("use_ema", True)

            if all_bullish:
                # EMAフィルター: ロングはEMA上のみ
                if use_ema and not ema_long_ok.iloc[pos]:
                    continue
                entry = float(close.iloc[pos])
                tp, sl = calc_tp_sl(entry, SIGNAL_LONG, p["tp_pct"], p["sl_pct"])
                result.at[orig_i, "signal"] = SIGNAL_LONG
                result.at[orig_i, "tp_price"] = tp
                result.at[orig_i, "sl_price"] = sl
                result.at[orig_i, "hold_bars"] = p["hold_bars"]
                logger.debug(
                    "HA Trend: LONG at pos=%d, entry=%.4f, ha_bullish=%d consecutive",
                    pos, entry, consecutive
                )

            elif all_bearish:
                # EMAフィルター: ショートはEMA下のみ
                if use_ema and not ema_short_ok.iloc[pos]:
                    continue
                entry = float(close.iloc[pos])
                tp, sl = calc_tp_sl(entry, SIGNAL_SHORT, p["tp_pct"], p["sl_pct"])
                result.at[orig_i, "signal"] = SIGNAL_SHORT
                result.at[orig_i, "tp_price"] = tp
                result.at[orig_i, "sl_price"] = sl
                result.at[orig_i, "hold_bars"] = p["hold_bars"]
                logger.debug(
                    "HA Trend: SHORT at pos=%d, entry=%.4f, ha_bearish=%d consecutive",
                    pos, entry, consecutive
                )

    except Exception as exc:
        logger.error("HA Trend: unexpected error: %s", exc, exc_info=True)
        return empty_signals(df, f"HA Trend: error: {exc}")

    long_count = int((result["signal"] == SIGNAL_LONG).sum())
    short_count = int((result["signal"] == SIGNAL_SHORT).sum())
    logger.info(
        "HA Trend: signals generated | long=%d | short=%d | total=%d",
        long_count,
        short_count,
        long_count + short_count,
    )

    return result


# ---------------------------------------------------------------------------
# 戦略クラス
# ---------------------------------------------------------------------------


class HATrendStrategy(BaseStrategy):
    """Heikin-Ashiトレンドフォロー + EMAフィルター戦略。"""

    strategy_id = "ha_trend"
    description = "Heikin-Ashi Trend Following + EMA(50) Filter"
    DEFAULT_PARAMS = DEFAULT_PARAMS

    def generate_signals(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        filters: Dict[str, bool],
    ) -> pd.DataFrame:
        return generate_signals(df, self.get_params(params), filters)
