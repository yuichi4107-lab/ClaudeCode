"""指標計算の共通ユーティリティ。"""

import numpy as np
import pandas as pd

from autorace_evaluator.config import settings


def zscore(series: pd.Series) -> pd.Series:
    """NaN を無視した標準化。標準偏差0や有効数1以下のときは全NaN。"""
    s = pd.to_numeric(series, errors="coerce")
    std = s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(np.nan, index=series.index)
    return (s - s.mean()) / std


def shrink(value, n, k: int = settings.SHRINKAGE_K, center: float = 0.0):
    """経験ベイズ縮約: center に向けて n/(n+k) で縮める。"""
    weight = n / (n + k)
    return center + weight * (value - center)


def to_per100m(value, distance, time_format: str = None):
    """タイム掲載値を per-100m 換算に正規化する。

    metrics からタイム値を使うときは必ずこの関数を経由すること
    (掲載単位が総時間だった場合は settings.TIME_FORMAT を 'total' に
    変えるだけで全指標が追随する)。
    """
    fmt = time_format or settings.TIME_FORMAT
    if fmt == "per100m":
        return value
    if fmt == "total":
        if distance is None or not np.all(np.isfinite(np.atleast_1d(distance))):
            return np.nan
        return value / (np.asarray(distance) / 100.0)
    raise ValueError(f"unknown TIME_FORMAT: {fmt}")


def center_within_race(df: pd.DataFrame, cols: list, race_col: str = "race_id") -> pd.DataFrame:
    """指定列をレース内センタリング(レース固定効果の除去と同値)した列
    `<col>_c` を追加して返す。"""
    out = df.copy()
    grouped = out.groupby(race_col)
    for col in cols:
        out[f"{col}_c"] = out[col] - grouped[col].transform("mean")
    return out
