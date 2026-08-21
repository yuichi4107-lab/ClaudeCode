"""
共通フィルターモジュール — FX戦略シグナルフィルタリング

以下の4種類のフィルターを提供する:
1. SMA200 トレンドフィルター: 価格がSMA200より上か下かでロング/ショートを制限
2. ATR ボラティリティフィルター: 低ボラ・高ボラ時のエントリーを除外
3. 時間帯フィルター: 東京セッションや週明け月曜朝を回避
4. 重要指標回避フィルター: FOMC/NFP/日銀発表の前後をスキップ

フィルター関数はすべて pd.Series[bool] を返す（True=エントリー許可、False=スキップ）。

参考:
- QuantifiedStrategies.com: SMA200 タイミングフィルター
- BabyPips: FXセッション別ボリューム分析
- DailyForex: ロンドンセッションフィルター効果
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

try:
    import pandas_ta as ta
except ImportError:
    ta = None  # type: ignore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. SMA200 トレンドフィルター
# ---------------------------------------------------------------------------


def sma200_trend_filter(
    df: pd.DataFrame,
    allow_long: bool = True,
    allow_short: bool = True,
) -> pd.Series:
    """
    SMA(200)トレンドフィルターを適用する。

    価格 > SMA200 の場合にロングを許可、価格 < SMA200 の場合にショートを許可する。
    データが200本未満の場合はすべて True（フィルターなし）を返す。

    Args:
        df: OHLCVデータ（closeカラム必須）
        allow_long: ロング方向のフィルター適用フラグ
        allow_short: ショート方向のフィルター適用フラグ

    Returns:
        pd.Series[bool]: True=エントリー許可
    """
    if len(df) < 200:
        logger.debug("sma200_trend_filter: insufficient rows (%d < 200), skip filter", len(df))
        return pd.Series(True, index=df.index)

    if ta is not None:
        sma200 = ta.sma(df["close"], length=200)
    else:
        sma200 = df["close"].rolling(200).mean()

    above = df["close"] > sma200
    below = df["close"] < sma200

    # ロング許可: SMA200上
    # ショート許可: SMA200下
    # 上記いずれかを満たせばエントリー可
    long_ok = above if allow_long else pd.Series(False, index=df.index)
    short_ok = below if allow_short else pd.Series(False, index=df.index)

    allowed = long_ok | short_ok
    logger.debug(
        "sma200_trend_filter: allowed %d / %d rows",
        int(allowed.sum()),
        len(df),
    )
    return allowed.fillna(False)


def sma200_long_filter(df: pd.DataFrame) -> pd.Series:
    """
    SMA200フィルター: ロング方向のみ許可（close > SMA200）。

    Args:
        df: OHLCVデータ

    Returns:
        pd.Series[bool]
    """
    if len(df) < 200:
        return pd.Series(True, index=df.index)

    if ta is not None:
        sma200 = ta.sma(df["close"], length=200)
    else:
        sma200 = df["close"].rolling(200).mean()

    return (df["close"] > sma200).fillna(False)


def sma200_short_filter(df: pd.DataFrame) -> pd.Series:
    """
    SMA200フィルター: ショート方向のみ許可（close < SMA200）。

    Args:
        df: OHLCVデータ

    Returns:
        pd.Series[bool]
    """
    if len(df) < 200:
        return pd.Series(True, index=df.index)

    if ta is not None:
        sma200 = ta.sma(df["close"], length=200)
    else:
        sma200 = df["close"].rolling(200).mean()

    return (df["close"] < sma200).fillna(False)


# ---------------------------------------------------------------------------
# 2. ATR ボラティリティフィルター
# ---------------------------------------------------------------------------


def atr_volatility_filter(
    df: pd.DataFrame,
    atr_period: int = 14,
    min_atr: Optional[float] = None,
    max_atr: Optional[float] = None,
) -> pd.Series:
    """
    ATR(14)でボラティリティが低すぎる/高すぎる期間をフィルタリングする。

    USDJPY 1h の参考閾値:
        min_atr = 0.10 (10銭)
        max_atr = 0.80 (80銭)

    Args:
        df: OHLCVデータ（high/low/close必須）
        atr_period: ATR期間（デフォルト14）
        min_atr: ATRの最小閾値（未満はスキップ）。Noneなら下限なし
        max_atr: ATRの最大閾値（超過はスキップ）。Noneなら上限なし

    Returns:
        pd.Series[bool]: True=エントリー許可
    """
    if ta is not None:
        atr = ta.atr(df["high"], df["low"], df["close"], length=atr_period)
    else:
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - df["close"].shift(1)).abs(),
                (df["low"] - df["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(atr_period).mean()

    allowed = pd.Series(True, index=df.index)

    if min_atr is not None:
        allowed &= atr >= min_atr

    if max_atr is not None:
        allowed &= atr <= max_atr

    logger.debug(
        "atr_volatility_filter: allowed %d / %d rows (min=%s, max=%s)",
        int(allowed.sum()),
        len(df),
        min_atr,
        max_atr,
    )
    return allowed.fillna(False)


# ---------------------------------------------------------------------------
# 3. 時間帯フィルター
# ---------------------------------------------------------------------------


def session_time_filter(
    df: pd.DataFrame,
    allow_tokyo: bool = False,
    allow_london: bool = True,
    allow_ny: bool = True,
    exclude_monday_asia: bool = True,
) -> pd.Series:
    """
    FXセッション時間帯フィルターを適用する（UTC基準）。

    セッション定義（UTC）:
        東京: 00:00〜07:00
        ロンドン: 08:00〜17:00
        ニューヨーク: 13:00〜22:00

    ロンドン/NYオーバーラップ（13:00〜17:00）は両方に含まれる。

    Args:
        df: DatetimeIndexまたはdatetimeカラムを持つOHLCVデータ
        allow_tokyo: 東京セッションを許可（デフォルトFalse=除外）
        allow_london: ロンドンセッションを許可（デフォルトTrue）
        allow_ny: NYセッションを許可（デフォルトTrue）
        exclude_monday_asia: 月曜の東京時間（00:00〜07:00 UTC）を除外

    Returns:
        pd.Series[bool]: True=エントリー許可
    """
    dt = _get_datetime_series(df)
    if dt is None:
        logger.warning("session_time_filter: no datetime column found, skip filter")
        return pd.Series(True, index=df.index)

    hour = dt.dt.hour
    weekday = dt.dt.weekday  # 0=月曜

    tokyo = (hour >= 0) & (hour < 7)
    london = (hour >= 8) & (hour < 17)
    ny = (hour >= 13) & (hour < 22)

    allowed = pd.Series(False, index=df.index)
    if allow_tokyo:
        allowed |= tokyo
    if allow_london:
        allowed |= london
    if allow_ny:
        allowed |= ny

    if exclude_monday_asia:
        monday_asia = (weekday == 0) & tokyo
        allowed &= ~monday_asia

    logger.debug(
        "session_time_filter: allowed %d / %d rows",
        int(allowed.sum()),
        len(df),
    )
    return allowed.fillna(False)


def london_open_filter(df: pd.DataFrame) -> pd.Series:
    """
    ロンドンオープン時刻（UTC 08:00）のバーのみ True を返す。

    ロンドンブレイクアウト戦略でエントリータイミングを絞るために使用する。

    Args:
        df: OHLCVデータ

    Returns:
        pd.Series[bool]
    """
    dt = _get_datetime_series(df)
    if dt is None:
        return pd.Series(True, index=df.index)

    is_london_open = dt.dt.hour == 8
    return is_london_open.fillna(False)


def _get_datetime_series(df: pd.DataFrame) -> Optional[pd.Series]:
    """
    DataFrameからdatetime型のSeries を取得する（内部ユーティリティ）。

    インデックスがDatetimeIndexの場合はそれを使用し、
    'datetime'カラムがあれば変換して使用する。

    Args:
        df: OHLCVデータ

    Returns:
        Optional[pd.Series]: datetime Series（取得できなければNone）
    """
    if isinstance(df.index, pd.DatetimeIndex):
        return pd.Series(df.index, index=df.index)

    if "datetime" in df.columns:
        return pd.to_datetime(df["datetime"])

    if "timestamp" in df.columns:
        ts = df["timestamp"]
        # Unix milliseconds or seconds を判別
        if ts.max() > 1e12:
            return pd.to_datetime(ts, unit="ms")
        else:
            return pd.to_datetime(ts, unit="s")

    return None


# ---------------------------------------------------------------------------
# 4. 重要指標発表回避フィルター
# ---------------------------------------------------------------------------

# 重要指標の発表日（UTC日付文字列リスト）
# バックテスト期間 2024-04 〜 2026-04 の主要イベント
_MAJOR_EVENT_DATES: list[str] = [
    # FOMC 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12",
    "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    # FOMC 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18",
    "2025-07-30", "2025-09-17", "2025-11-06", "2025-12-17",
    # FOMC 2026
    "2026-01-28", "2026-03-18",
    # NFP 2024 (各月第1金曜)
    "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05",
    "2024-05-03", "2024-06-07", "2024-07-05", "2024-08-02",
    "2024-09-06", "2024-10-04", "2024-11-01", "2024-12-06",
    # NFP 2025
    "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04",
    "2025-05-02", "2025-06-06", "2025-07-03", "2025-08-01",
    "2025-09-05", "2025-10-03", "2025-11-07", "2025-12-05",
    # NFP 2026
    "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-10",
    # 日銀政策決定会合 2024
    "2024-01-23", "2024-03-19", "2024-04-26", "2024-06-14",
    "2024-07-31", "2024-09-20", "2024-10-31", "2024-12-19",
    # 日銀 2025
    "2025-01-24", "2025-03-19", "2025-04-30", "2025-06-17",
    "2025-07-31", "2025-09-19", "2025-10-29", "2025-12-19",
    # 日銀 2026
    "2026-01-23", "2026-03-19",
]


def economic_event_filter(
    df: pd.DataFrame,
    avoid_hours_before: int = 24,
    avoid_hours_after: int = 24,
) -> pd.Series:
    """
    重要指標発表の前後をフィルタリングする。

    対象イベント: FOMC、NFP、日銀政策決定会合

    Args:
        df: OHLCVデータ
        avoid_hours_before: 発表前の回避時間（デフォルト24時間）
        avoid_hours_after: 発表後の回避時間（デフォルト24時間）

    Returns:
        pd.Series[bool]: True=エントリー許可（指標発表から遠い期間）
    """
    dt = _get_datetime_series(df)
    if dt is None:
        logger.warning("economic_event_filter: no datetime column found, skip filter")
        return pd.Series(True, index=df.index)

    dt_utc = pd.to_datetime(dt.values)
    event_dates = pd.to_datetime(_MAJOR_EVENT_DATES)

    # 各バーが指標発表の回避期間内かチェック
    in_blackout = pd.Series(False, index=df.index)

    for event_dt in event_dates:
        event_start = event_dt - pd.Timedelta(hours=avoid_hours_before)
        event_end = event_dt + pd.Timedelta(hours=avoid_hours_after)
        blackout_mask = pd.Series(
            (dt_utc >= event_start) & (dt_utc <= event_end),
            index=df.index,
        )
        in_blackout |= blackout_mask

    allowed = ~in_blackout
    logger.debug(
        "economic_event_filter: allowed %d / %d rows",
        int(allowed.sum()),
        len(df),
    )
    return allowed


# ---------------------------------------------------------------------------
# フィルター組み合わせユーティリティ
# ---------------------------------------------------------------------------


def apply_filters(
    df: pd.DataFrame,
    signal_series: pd.Series,
    filters: dict,
    direction_series: Optional[pd.Series] = None,
) -> pd.Series:
    """
    有効なフィルターをシグナルに一括適用する。

    Args:
        df: OHLCVデータ
        signal_series: シグナル Series（1/-1/0）
        filters: フィルター設定dict（キー=フィルター名、値=bool）
            例: {"use_sma200": True, "use_atr": True, "use_session": False, "use_event": True}
        direction_series: シグナルの方向 Series（1/-1）。Noneなら signal_series から取得

    Returns:
        pd.Series: フィルター適用後のシグナル
    """
    result = signal_series.copy()

    if direction_series is None:
        direction_series = signal_series

    # SMA200フィルター
    if filters.get("use_sma200", False):
        long_filter = sma200_long_filter(df)
        short_filter = sma200_short_filter(df)
        # ロングシグナルはSMA200上のみ許可
        long_mask = (result == SIGNAL_LONG) & ~long_filter
        short_mask = (result == SIGNAL_SHORT) & ~short_filter
        result = result.copy()
        result[long_mask] = 0
        result[short_mask] = 0

    # ATRフィルター
    if filters.get("use_atr", False):
        atr_ok = atr_volatility_filter(df, min_atr=filters.get("atr_min"), max_atr=filters.get("atr_max"))
        result = result.where(atr_ok, other=0)

    # セッション時間フィルター
    if filters.get("use_session", False):
        session_ok = session_time_filter(df)
        result = result.where(session_ok, other=0)

    # 重要指標回避フィルター
    if filters.get("use_event", False):
        event_ok = economic_event_filter(df)
        result = result.where(event_ok, other=0)

    return result


# シグナル定数（他モジュールから参照できるよう再エクスポート）
SIGNAL_LONG = 1
SIGNAL_SHORT = -1
SIGNAL_NONE = 0
