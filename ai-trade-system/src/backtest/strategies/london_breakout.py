"""
戦略4: London Breakout

ロジック:
    1. 東京セッション（UTC 00:00〜07:00）の高値・安値レンジを確定
    2. UTC 08:00（ロンドン開始）に上値を上抜けでロング、下値を下抜けでショート
    3. SL: ブレイク反対側のレンジ端
    4. TP: レンジ幅 × tp_multiplier
    5. フィルター有効時: 日足SMAトレンドと同方向のブレイクのみ採用

1h足必須: 東京セッション（7バー分）のレンジを計算し、UTC 08:00のバーでシグナル発火。

データ品質注意:
    - タイムスタンプはUTC基準を想定
    - データがJST（UTC+9）の場合は hour のオフセットを調整
    - セッション判定は時刻のみ（日付を跨ぐ場合も対応）

期待勝率の根拠:
    - QuantifiedStrategies: London Breakout戦略のPF 1.5以上（RR=1.5設定）
    - ロンドンセッション前後のスキップで勝率10〜15%向上（DailyForex経験則）
    - USDJPYはロンドン開始時刻のボリュームが最大（全取引量の35%）

参考文献:
    - https://www.quantifiedstrategies.com/london-breakout-strategy/
    - https://www.dailyforex.com/forex-articles/london-breakout-strategy/210474
    - https://duhanicapital.com/blogs/master-the-london-breakout-trading-strategy-for-consistent-forex-success
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
    empty_signals,
)
from .filters import (
    sma200_long_filter,
    sma200_short_filter,
    atr_volatility_filter,
    economic_event_filter,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# パラメータ定義
# ---------------------------------------------------------------------------

DEFAULT_PARAMS: Dict[str, Any] = {
    "tokyo_start_hour": 0,     # 東京セッション開始（UTC時）
    "tokyo_end_hour": 7,       # 東京セッション終了（UTC時、非含）
    "london_open_hour": 8,     # ロンドン開始（UTC時）
    "tp_multiplier": 1.5,      # TP = レンジ幅 × tp_multiplier
    "min_range_pct": 0.001,    # 最小レンジ幅（小さすぎるレンジを除外）
    "hold_bars": 8,            # 最大保有（1h足）
    "exclude_monday": True,    # 月曜日を除外
}

PARAM_GRID: Dict[str, list] = {
    "tp_multiplier": [1.0, 1.5, 2.0, 2.5],
    "min_range_pct": [0.0005, 0.001, 0.002],
    "hold_bars": [4, 8, 12, 16],
}

MIN_ROWS = 30


# ---------------------------------------------------------------------------
# タイムスタンプユーティリティ
# ---------------------------------------------------------------------------


def _get_dt_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """
    DataFrameからUTC datetimeのSeriesを取得する（内部ユーティリティ）。

    Args:
        df: OHLCVデータ

    Returns:
        Optional[pd.Series]: datetime Series
    """
    if isinstance(df.index, pd.DatetimeIndex):
        return pd.Series(df.index, index=df.index)

    if "datetime" in df.columns:
        return pd.to_datetime(df["datetime"])

    if "timestamp" in df.columns:
        ts = df["timestamp"]
        unit = "ms" if ts.max() > 1e12 else "s"
        return pd.to_datetime(ts, unit=unit)

    return None


# ---------------------------------------------------------------------------
# メイン関数
# ---------------------------------------------------------------------------


def generate_signals(
    df: pd.DataFrame,
    params: Dict[str, Any],
    filters: Dict[str, bool],
) -> pd.DataFrame:
    """
    ロンドンブレイクアウト戦略のシグナルを生成する（1h足専用）。

    Args:
        df: 1h足OHLCVデータ（UTC基準のdatetimeが必要）
        params: 戦略パラメータ（DEFAULT_PARAMSをベースに上書き）
        filters: フィルター有効/無効フラグ
            - use_sma200 (bool): 日足SMAトレンドフィルター（SMA200上でロングのみ等）
            - use_atr    (bool): ATRボラティリティフィルター
            - use_event  (bool): 重要指標回避フィルター

    Returns:
        pd.DataFrame: 元DFに signal / tp_price / sl_price / hold_bars カラムを追加
    """
    p = {**DEFAULT_PARAMS, **params}

    if not validate_dataframe(df, min_rows=MIN_ROWS):
        return empty_signals(df, "London Breakout: data validation failed")

    dt = _get_dt_series(df)
    if dt is None:
        return empty_signals(df, "London Breakout: no datetime column found")

    logger.info(
        "London Breakout: generating signals | rows=%d | tp_mult=%.1f",
        len(df),
        p["tp_multiplier"],
    )

    result = make_signal_df(df)

    try:
        dt_series = pd.to_datetime(dt.values)
        close = df["close"].values
        high = df["high"].values
        low = df["low"].values
        orig_index = df.index.tolist()

        # フィルター用マスクを事前計算
        sma200_long_ok = sma200_long_filter(df) if filters.get("use_sma200", False) else None
        sma200_short_ok = sma200_short_filter(df) if filters.get("use_sma200", False) else None
        atr_ok_series = (
            atr_volatility_filter(df, min_atr=0.10, max_atr=1.50)
            if filters.get("use_atr", False)
            else None
        )
        event_ok_series = (
            economic_event_filter(df)
            if filters.get("use_event", False)
            else None
        )

        # 日付ごとにグループ化して東京レンジを計算
        dates = pd.Series(dt_series).dt.date.unique()

        for date in dates:
            # 月曜日除外
            day_of_week = pd.Timestamp(date).weekday()  # 0=月曜
            if p["exclude_monday"] and day_of_week == 0:
                logger.debug("London Breakout: skipping Monday %s", date)
                continue

            # 東京セッションのバーを取得
            tokyo_mask = (
                (pd.Series(dt_series).dt.date == date)
                & (pd.Series(dt_series).dt.hour >= p["tokyo_start_hour"])
                & (pd.Series(dt_series).dt.hour < p["tokyo_end_hour"])
            )
            tokyo_positions = np.where(tokyo_mask.values)[0]

            if len(tokyo_positions) < 3:
                logger.debug(
                    "London Breakout: not enough Tokyo bars on %s (%d bars)",
                    date, len(tokyo_positions)
                )
                continue

            # 東京レンジの高値・安値
            tokyo_high = float(np.max(high[tokyo_positions]))
            tokyo_low = float(np.min(low[tokyo_positions]))
            tokyo_range = tokyo_high - tokyo_low

            # レンジが小さすぎる場合はスキップ
            mid_price = (tokyo_high + tokyo_low) / 2
            if mid_price > 0 and (tokyo_range / mid_price) < p["min_range_pct"]:
                logger.debug(
                    "London Breakout: range too small on %s (%.4f)", date, tokyo_range
                )
                continue

            # ロンドン開始バーを取得（UTC 08:00）
            london_mask = (
                (pd.Series(dt_series).dt.date == date)
                & (pd.Series(dt_series).dt.hour == p["london_open_hour"])
            )
            london_positions = np.where(london_mask.values)[0]

            if len(london_positions) == 0:
                # 土日はロンドンバーがない場合あり
                logger.debug("London Breakout: no London bar on %s", date)
                continue

            london_pos = london_positions[0]
            orig_i = orig_index[london_pos]
            london_close = float(close[london_pos])
            london_high = float(high[london_pos])
            london_low = float(low[london_pos])

            # TP/SL計算
            tp_amount = tokyo_range * p["tp_multiplier"]

            # フィルターチェック
            long_allowed = True
            short_allowed = True

            if sma200_long_ok is not None and not sma200_long_ok.loc[orig_i]:
                long_allowed = False
            if sma200_short_ok is not None and not sma200_short_ok.loc[orig_i]:
                short_allowed = False
            if atr_ok_series is not None and not atr_ok_series.loc[orig_i]:
                long_allowed = False
                short_allowed = False
            if event_ok_series is not None and not event_ok_series.loc[orig_i]:
                long_allowed = False
                short_allowed = False

            # ブレイクアウト判定
            # ロング: ロンドンバーのhighが東京高値を上抜け
            if long_allowed and london_high > tokyo_high:
                entry = tokyo_high  # ブレイクアウト価格
                tp_price = entry + tp_amount
                sl_price = tokyo_low  # 東京レンジ下限をSLに
                result.at[orig_i, "signal"] = SIGNAL_LONG
                result.at[orig_i, "tp_price"] = tp_price
                result.at[orig_i, "sl_price"] = sl_price
                result.at[orig_i, "hold_bars"] = p["hold_bars"]
                logger.debug(
                    "London Breakout: LONG on %s | entry=%.4f, tp=%.4f, sl=%.4f",
                    date, entry, tp_price, sl_price
                )

            # ショート: ロンドンバーのlowが東京安値を下抜け
            elif short_allowed and london_low < tokyo_low:
                entry = tokyo_low  # ブレイクアウト価格
                tp_price = entry - tp_amount
                sl_price = tokyo_high  # 東京レンジ上限をSLに
                result.at[orig_i, "signal"] = SIGNAL_SHORT
                result.at[orig_i, "tp_price"] = tp_price
                result.at[orig_i, "sl_price"] = sl_price
                result.at[orig_i, "hold_bars"] = p["hold_bars"]
                logger.debug(
                    "London Breakout: SHORT on %s | entry=%.4f, tp=%.4f, sl=%.4f",
                    date, entry, tp_price, sl_price
                )

    except Exception as exc:
        logger.error("London Breakout: unexpected error: %s", exc, exc_info=True)
        return empty_signals(df, f"London Breakout: error: {exc}")

    long_count = int((result["signal"] == SIGNAL_LONG).sum())
    short_count = int((result["signal"] == SIGNAL_SHORT).sum())
    logger.info(
        "London Breakout: signals generated | long=%d | short=%d | total=%d",
        long_count,
        short_count,
        long_count + short_count,
    )

    return result


# ---------------------------------------------------------------------------
# 戦略クラス
# ---------------------------------------------------------------------------


class LondonBreakoutStrategy(BaseStrategy):
    """ロンドンセッション開始のレンジブレイクアウト戦略（1h足専用）。"""

    strategy_id = "london_breakout"
    description = "London Breakout: Tokyo session range breakout at London open"
    DEFAULT_PARAMS = DEFAULT_PARAMS

    def generate_signals(
        self,
        df: pd.DataFrame,
        params: Dict[str, Any],
        filters: Dict[str, bool],
    ) -> pd.DataFrame:
        return generate_signals(df, self.get_params(params), filters)
