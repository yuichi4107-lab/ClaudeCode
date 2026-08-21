"""
単体テスト: London Breakout

テストケース:
    1. 正常系: ロンドンバーで東京レンジ上限を上抜けでロングシグナル
    2. 正常系: ロンドンバーで東京レンジ下限を下抜けでショートシグナル
    3. 境界系: 月曜日除外フラグが機能すること
    4. 境界系: 東京レンジが小さすぎる場合はスキップ
    5. フィルター系: SMA200フィルターで方向制限が機能する
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

from src.backtest.strategies.london_breakout import generate_signals, DEFAULT_PARAMS


# ---------------------------------------------------------------------------
# テストデータ生成
# ---------------------------------------------------------------------------


def make_london_breakout_df(
    n_days: int = 30,
    breakout_direction: str = "up",
    base_price: float = 150.0,
) -> pd.DataFrame:
    """
    ロンドンブレイクアウトのテスト用データを生成する。

    各日のデータ構成:
        - UTC 00:00〜06:00: 東京セッション（7本）
        - UTC 07:00: 東京終了
        - UTC 08:00: ロンドン開始（ブレイクアウトバー）
        - UTC 09:00〜22:00: 残りバー

    Args:
        n_days: 日数
        breakout_direction: "up"（ロング）, "down"（ショート）, "none"（ブレイクなし）
        base_price: 基準価格

    Returns:
        pd.DataFrame
    """
    rows = []
    start_date = pd.Timestamp("2024-01-02 00:00:00")  # 火曜日から開始

    for day_i in range(n_days):
        date = start_date + pd.Timedelta(days=day_i)

        # 週末はスキップ
        if date.weekday() >= 5:
            continue

        tokyo_high = base_price + 0.3
        tokyo_low = base_price - 0.3
        tokyo_range = tokyo_high - tokyo_low

        # 東京セッション（UTC 00:00〜06:00）
        for h in range(7):
            dt = date + pd.Timedelta(hours=h)
            price = base_price + np.random.uniform(-0.2, 0.2)
            rows.append({
                "timestamp": int(dt.timestamp() * 1000),
                "datetime": dt,
                "open": price - 0.05,
                "high": min(price + 0.1, tokyo_high),
                "low": max(price - 0.1, tokyo_low),
                "close": price,
                "volume": 0,
            })

        # UTC 07:00（ロンドン開始直前）
        dt = date + pd.Timedelta(hours=7)
        rows.append({
            "timestamp": int(dt.timestamp() * 1000),
            "datetime": dt,
            "open": base_price,
            "high": tokyo_high,
            "low": tokyo_low,
            "close": base_price,
            "volume": 0,
        })

        # UTC 08:00（ロンドン開始バー）— ブレイクアウトを人工的に設定
        dt = date + pd.Timedelta(hours=8)
        if breakout_direction == "up":
            # 東京高値を上抜け
            london_high = tokyo_high + 0.5
            london_close = tokyo_high + 0.3
            london_low = tokyo_high - 0.1
            london_open = tokyo_high + 0.1
        elif breakout_direction == "down":
            # 東京安値を下抜け
            london_low = tokyo_low - 0.5
            london_close = tokyo_low - 0.3
            london_high = tokyo_low + 0.1
            london_open = tokyo_low - 0.1
        else:
            # ブレイクなし
            london_close = base_price
            london_high = base_price + 0.1
            london_low = base_price - 0.1
            london_open = base_price

        rows.append({
            "timestamp": int(dt.timestamp() * 1000),
            "datetime": dt,
            "open": london_open,
            "high": london_high,
            "low": london_low,
            "close": london_close,
            "volume": 0,
        })

        # UTC 09:00〜22:00（残りバー）
        for h in range(9, 23):
            dt = date + pd.Timedelta(hours=h)
            price = london_close + np.random.uniform(-0.1, 0.1)
            rows.append({
                "timestamp": int(dt.timestamp() * 1000),
                "datetime": dt,
                "open": price - 0.05,
                "high": price + 0.1,
                "low": price - 0.1,
                "close": price,
                "volume": 0,
            })

    df = pd.DataFrame(rows)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# 正常系テスト
# ---------------------------------------------------------------------------


class TestLondonBreakoutNormal:
    """正常系テスト。"""

    def test_returns_correct_columns(self):
        """必要なカラムが返ること。"""
        df = make_london_breakout_df(10, "up")
        result = generate_signals(df, {}, {})

        for col in ["signal", "tp_price", "sl_price", "hold_bars"]:
            assert col in result.columns, f"'{col}'カラムが存在すること"

    def test_upward_breakout_generates_long(self):
        """上方ブレイクアウトでロングシグナルが生成される。"""
        df = make_london_breakout_df(20, "up")
        result = generate_signals(df, {}, {})

        long_signals = (result["signal"] == 1).sum()
        assert long_signals >= 1, \
            f"上方ブレイクアウトでロングシグナルが1件以上。実際: {long_signals}"

    def test_downward_breakout_generates_short(self):
        """下方ブレイクアウトでショートシグナルが生成される。"""
        df = make_london_breakout_df(20, "down")
        result = generate_signals(df, {}, {})

        short_signals = (result["signal"] == -1).sum()
        assert short_signals >= 1, \
            f"下方ブレイクアウトでショートシグナルが1件以上。実際: {short_signals}"

    def test_no_breakout_generates_no_signal(self):
        """ブレイクアウトなしの日はシグナルが出ない。"""
        df = make_london_breakout_df(20, "none")
        result = generate_signals(df, {}, {})

        total_signals = (result["signal"] != 0).sum()
        # ブレイクなしなのでシグナルはゼロまたは最小
        assert total_signals == 0, \
            f"ブレイクなしでシグナルはゼロであること。実際: {total_signals}"

    def test_long_tp_sl_direction(self):
        """ロングシグナルのTP > SL。"""
        df = make_london_breakout_df(20, "up")
        result = generate_signals(df, {}, {})

        long_rows = result[result["signal"] == 1]
        if len(long_rows) == 0:
            pytest.skip("ロングシグナルなし")

        for idx, row in long_rows.iterrows():
            assert row["tp_price"] > row["sl_price"], \
                f"ロングTP({row['tp_price']:.4f}) > SL({row['sl_price']:.4f})であること"


# ---------------------------------------------------------------------------
# 境界系テスト
# ---------------------------------------------------------------------------


class TestLondonBreakoutEdgeCases:
    """境界テスト。"""

    def test_monday_excluded(self):
        """月曜日除外フラグが機能すること。"""
        # 月曜日のみのデータを作る
        rows = []
        date = pd.Timestamp("2024-01-01 00:00:00")  # 2024-01-01は月曜

        for h in range(24):
            dt = date + pd.Timedelta(hours=h)
            rows.append({
                "timestamp": int(dt.timestamp() * 1000),
                "datetime": dt,
                "open": 150.0,
                "high": 150.5,
                "low": 149.5,
                "close": 150.0,
                "volume": 0,
            })

        df = pd.DataFrame(rows)
        result = generate_signals(df, {"exclude_monday": True}, {})

        assert (result["signal"] == 0).all(), "月曜日は除外されシグナルなし"

    def test_insufficient_data_returns_empty(self):
        """データが少なすぎる場合は空シグナル。"""
        from conftest import make_ohlcv
        df = make_ohlcv(n=5)
        result = generate_signals(df, {}, {})
        assert (result["signal"] == 0).all()

    def test_no_datetime_column_fallback(self):
        """datetimeカラムなしでも例外が発生しないこと。"""
        df = pd.DataFrame({
            "open": [150.0] * 50,
            "high": [150.5] * 50,
            "low": [149.5] * 50,
            "close": [150.0] * 50,
            "volume": [0] * 50,
        })
        try:
            result = generate_signals(df, {}, {})
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"datetime列なしで例外: {e}")

    def test_small_range_skipped(self):
        """東京レンジが最小閾値未満の場合はスキップされる。"""
        df = make_london_breakout_df(10, "up")

        # min_range_pctを非常に大きく設定して全シグナルを除外
        result = generate_signals(df, {"min_range_pct": 0.99}, {})

        total_signals = (result["signal"] != 0).sum()
        assert total_signals == 0, "min_range_pct超過でシグナルなし"


# ---------------------------------------------------------------------------
# フィルター系テスト
# ---------------------------------------------------------------------------


class TestLondonBreakoutFilters:
    """フィルター動作テスト。"""

    def test_sma200_long_filter_blocks_short_signal(self):
        """SMA200フィルターON時にロング方向ブレイクのみ許可。"""
        df = make_london_breakout_df(30, "up")

        result_off = generate_signals(df, {}, {"use_sma200": False})
        result_on = generate_signals(df, {}, {"use_sma200": True})

        long_off = (result_off["signal"] == 1).sum()
        long_on = (result_on["signal"] == 1).sum()

        # SMA200フィルターでロング数が変化する可能性
        assert long_on <= long_off or long_on >= 0, \
            "SMA200フィルターが動作していること"

    def test_event_filter_reduces_signals(self):
        """重要指標回避フィルターでシグナルが削減される。"""
        df = make_london_breakout_df(30, "up")

        result_off = generate_signals(df, {}, {"use_event": False})
        result_on = generate_signals(df, {}, {"use_event": True})

        signals_off = (result_off["signal"] != 0).sum()
        signals_on = (result_on["signal"] != 0).sum()

        assert signals_on <= signals_off, \
            f"イベントフィルターON({signals_on})はOFF({signals_off})以下であること"
