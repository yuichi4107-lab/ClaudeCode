"""
共通テストフィクスチャ — 戦略テスト用サンプルデータ生成

各テストファイルから import して使用する。
"""

from __future__ import annotations

import pandas as pd
import numpy as np
import pytest


def make_ohlcv(
    n: int = 300,
    start: str = "2024-01-01",
    freq: str = "1h",
    base_price: float = 150.0,
    trend: float = 0.0,
    volatility: float = 0.3,
) -> pd.DataFrame:
    """
    テスト用OHLCVデータを生成する（決定論的、乱数seed固定）。

    Args:
        n: バー数
        start: 開始日時
        freq: pandas频率文字列
        base_price: 基準価格
        trend: 1バーあたりのトレンド（例: 0.01=上昇、-0.01=下降）
        volatility: 1バーあたりのボラ（標準偏差）

    Returns:
        pd.DataFrame: timestamp, datetime, open, high, low, close, volume
    """
    rng = np.random.default_rng(42)  # seed固定で再現性確保
    dt_index = pd.date_range(start=start, periods=n, freq=freq)

    # 価格系列生成
    returns = rng.normal(trend, volatility, n)
    close = base_price + np.cumsum(returns)
    close = np.maximum(close, base_price * 0.5)  # 価格がマイナスにならないよう制限

    noise = rng.uniform(0, 0.2, n)
    open_ = close - rng.uniform(-0.1, 0.1, n)
    high = np.maximum(close, open_) + noise
    low = np.minimum(close, open_) - noise

    # OHLC整合性保証
    high = np.maximum(high, np.maximum(close, open_))
    low = np.minimum(low, np.minimum(close, open_))

    timestamps = dt_index.astype(np.int64) // 10**6  # milliseconds

    df = pd.DataFrame(
        {
            "timestamp": timestamps,
            "datetime": dt_index,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": np.zeros(n),
        }
    )
    return df


def make_uptrend_ohlcv(n: int = 300) -> pd.DataFrame:
    """上昇トレンドのOHLCVデータを生成する。"""
    return make_ohlcv(n=n, base_price=150.0, trend=0.05, volatility=0.1)


def make_downtrend_ohlcv(n: int = 300) -> pd.DataFrame:
    """下降トレンドのOHLCVデータを生成する。"""
    return make_ohlcv(n=n, base_price=155.0, trend=-0.05, volatility=0.1)


def make_range_ohlcv(n: int = 300) -> pd.DataFrame:
    """レンジ相場のOHLCVデータを生成する（BBリバーション向け）。"""
    return make_ohlcv(n=n, base_price=150.0, trend=0.0, volatility=0.2)


def make_insufficient_ohlcv(n: int = 10) -> pd.DataFrame:
    """データ不足のOHLCVデータを生成する（境界ケース用）。"""
    return make_ohlcv(n=n, base_price=150.0)


@pytest.fixture
def flat_df():
    """300本のフラット価格データ（信号なし用）。"""
    return make_ohlcv(n=300, trend=0.0, volatility=0.05)


@pytest.fixture
def uptrend_df():
    """300本の上昇トレンドデータ。"""
    return make_uptrend_ohlcv(300)


@pytest.fixture
def downtrend_df():
    """300本の下降トレンドデータ。"""
    return make_downtrend_ohlcv(300)


@pytest.fixture
def range_df():
    """300本のレンジデータ。"""
    return make_range_ohlcv(300)


@pytest.fixture
def small_df():
    """10本のデータ不足DF（境界テスト用）。"""
    return make_insufficient_ohlcv(10)
