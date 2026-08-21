"""
単体テスト: Heikin-Ashi Trend Following + EMA Filter

テストケース:
    1. 正常系: HA変換が正しく計算される（数式検証）
    2. 正常系: 上昇トレンドで連続陽線バーにロングシグナルが出る
    3. 正常系: EMAフィルターでシグナル数が変化する
    4. 境界系: データ不足で空シグナルを返す
    5. 境界系: 全closeが同値でもHA計算が例外なく完了する
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

from tests.strategies.conftest import make_ohlcv, make_uptrend_ohlcv, make_downtrend_ohlcv, make_range_ohlcv

from src.backtest.strategies.ha_trend import (
    generate_signals,
    calc_heikin_ashi,
    DEFAULT_PARAMS,
    MIN_ROWS,
)


# ---------------------------------------------------------------------------
# HA変換テスト
# ---------------------------------------------------------------------------


class TestHeikinAshiCalculation:
    """HA変換の数式検証テスト。"""

    def test_ha_close_formula(self):
        """HA_Close = (Open + High + Low + Close) / 4 を検証する。"""
        df = make_ohlcv(n=10, trend=0.0, volatility=0.1)
        ha = calc_heikin_ashi(df)

        expected_close_0 = (
            df["open"].iloc[0]
            + df["high"].iloc[0]
            + df["low"].iloc[0]
            + df["close"].iloc[0]
        ) / 4.0

        assert abs(ha["ha_close"].iloc[0] - expected_close_0) < 1e-9, \
            f"HA_Close[0]の計算が正しいこと: expected={expected_close_0:.6f}, got={ha['ha_close'].iloc[0]:.6f}"

    def test_ha_open_initial_value(self):
        """初期HA_Open = (Open[0] + Close[0]) / 2 を検証する。"""
        df = make_ohlcv(n=10)
        ha = calc_heikin_ashi(df)

        expected_open_0 = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0
        assert abs(ha["ha_open"].iloc[0] - expected_open_0) < 1e-9, \
            f"HA_Open[0]の計算が正しいこと: expected={expected_open_0:.6f}"

    def test_ha_open_recursive(self):
        """HA_Open[i] = (HA_Open[i-1] + HA_Close[i-1]) / 2 を検証する。"""
        df = make_ohlcv(n=10)
        ha = calc_heikin_ashi(df)

        for i in range(1, len(ha)):
            expected = (ha["ha_open"].iloc[i - 1] + ha["ha_close"].iloc[i - 1]) / 2.0
            actual = ha["ha_open"].iloc[i]
            assert abs(actual - expected) < 1e-9, \
                f"HA_Open[{i}]の再帰計算が正しいこと: expected={expected:.6f}, got={actual:.6f}"

    def test_ha_high_max_constraint(self):
        """HA_High >= max(HA_Open, HA_Close) を検証する。"""
        df = make_ohlcv(n=50)
        ha = calc_heikin_ashi(df)

        for i in range(len(ha)):
            ha_high = ha["ha_high"].iloc[i]
            min_val = max(ha["ha_open"].iloc[i], ha["ha_close"].iloc[i])
            assert ha_high >= min_val - 1e-9, \
                f"HA_High[{i}] >= max(HA_Open, HA_Close): {ha_high:.4f} vs {min_val:.4f}"

    def test_ha_low_min_constraint(self):
        """HA_Low <= min(HA_Open, HA_Close) を検証する。"""
        df = make_ohlcv(n=50)
        ha = calc_heikin_ashi(df)

        for i in range(len(ha)):
            ha_low = ha["ha_low"].iloc[i]
            max_val = min(ha["ha_open"].iloc[i], ha["ha_close"].iloc[i])
            assert ha_low <= max_val + 1e-9, \
                f"HA_Low[{i}] <= min(HA_Open, HA_Close): {ha_low:.4f} vs {max_val:.4f}"

    def test_ha_columns_returned(self):
        """HA計算結果に必要な全カラムが含まれること。"""
        df = make_ohlcv(n=20)
        ha = calc_heikin_ashi(df)

        for col in ["ha_open", "ha_high", "ha_low", "ha_close"]:
            assert col in ha.columns, f"'{col}'カラムが存在すること"


# ---------------------------------------------------------------------------
# 正常系テスト
# ---------------------------------------------------------------------------


class TestHATrendNormal:
    """正常系テスト。"""

    def test_returns_correct_columns(self):
        """必要なカラムが返ること。"""
        df = make_uptrend_ohlcv(200)
        result = generate_signals(df, {}, {})

        for col in ["signal", "tp_price", "sl_price", "hold_bars"]:
            assert col in result.columns

    def test_uptrend_generates_long_signals(self):
        """上昇トレンドデータでロングシグナルが生成される。"""
        df = make_uptrend_ohlcv(300)
        result = generate_signals(df, {"consecutive_bars": 2}, {"use_ema": False})

        long_signals = (result["signal"] == 1).sum()
        assert long_signals >= 1, \
            f"上昇トレンドでロングシグナルが1件以上。実際: {long_signals}"

    def test_downtrend_generates_short_signals(self):
        """下降トレンドデータでショートシグナルが生成される。"""
        df = make_downtrend_ohlcv(300)
        result = generate_signals(df, {"consecutive_bars": 2}, {"use_ema": False})

        short_signals = (result["signal"] == -1).sum()
        assert short_signals >= 1, \
            f"下降トレンドでショートシグナルが1件以上。実際: {short_signals}"

    def test_signal_values_valid(self):
        """signalは-1/0/1のみ。"""
        df = make_uptrend_ohlcv(200)
        result = generate_signals(df, {}, {})
        unique = set(result["signal"].unique())
        assert unique.issubset({-1, 0, 1})

    def test_tp_sl_long_direction(self):
        """ロングのTP > entry > SL。"""
        df = make_uptrend_ohlcv(300)
        result = generate_signals(df, {"consecutive_bars": 2}, {"use_ema": False})

        long_rows = result[result["signal"] == 1]
        if len(long_rows) == 0:
            pytest.skip("ロングシグナルなし")

        for idx, row in long_rows.iterrows():
            entry = df.loc[idx, "close"]
            assert row["tp_price"] > entry, "TP > entry"
            assert row["sl_price"] < entry, "SL < entry"


# ---------------------------------------------------------------------------
# EMAフィルターテスト
# ---------------------------------------------------------------------------


class TestHATrendEMAFilter:
    """EMAフィルターの動作テスト（最重要フィルター）。"""

    def test_ema_filter_on_reduces_signals(self):
        """EMAフィルターONでシグナル数が同数以下になる。"""
        df = make_range_ohlcv(300)
        params = {"consecutive_bars": 2}

        result_off = generate_signals(df, params, {"use_ema": False})
        result_on = generate_signals(df, params, {"use_ema": True})

        signals_off = (result_off["signal"] != 0).sum()
        signals_on = (result_on["signal"] != 0).sum()

        assert signals_on <= signals_off, \
            f"EMAフィルターON({signals_on})はOFF({signals_off})以下"

    def test_ema_filter_blocks_counter_trend(self):
        """EMAフィルターが逆方向シグナルを除外する。"""
        # 強い上昇トレンドではショートがEMAフィルターで除外される
        df = make_uptrend_ohlcv(300)
        params = {"consecutive_bars": 2}

        result_off = generate_signals(df, params, {"use_ema": False})
        result_on = generate_signals(df, params, {"use_ema": True})

        short_off = (result_off["signal"] == -1).sum()
        short_on = (result_on["signal"] == -1).sum()

        assert short_on <= short_off, \
            f"上昇トレンドでEMAフィルターONはショートを削減: ON={short_on}, OFF={short_off}"


# ---------------------------------------------------------------------------
# 境界系テスト
# ---------------------------------------------------------------------------


class TestHATrendEdgeCases:
    """境界テスト。"""

    def test_insufficient_data_returns_empty(self):
        """データ不足（MIN_ROWS未満）で空シグナル。"""
        df = make_ohlcv(n=MIN_ROWS - 1)
        result = generate_signals(df, {}, {})
        assert (result["signal"] == 0).all()

    def test_constant_price_no_crash(self):
        """全closeが同値でHA計算が例外なく完了する。"""
        n = 100
        df = pd.DataFrame({
            "timestamp": range(n),
            "datetime": pd.date_range("2024-01-01", periods=n, freq="1h"),
            "open": [150.0] * n,
            "high": [150.1] * n,
            "low": [149.9] * n,
            "close": [150.0] * n,
            "volume": [0] * n,
        })
        try:
            result = generate_signals(df, {}, {})
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"定数価格で例外: {e}")

    def test_nan_close_no_exception(self):
        """NaN含有でも例外なし。"""
        df = make_uptrend_ohlcv(200)
        df.loc[df.index[100:105], "close"] = np.nan
        try:
            result = generate_signals(df, {}, {})
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"NaN含有で例外: {e}")

    def test_more_consecutive_bars_fewer_signals(self):
        """consecutive_bars が多いほどシグナルが少ない（またはゼロ）。"""
        df = make_range_ohlcv(300)

        result_2 = generate_signals(df, {"consecutive_bars": 2}, {"use_ema": False})
        result_5 = generate_signals(df, {"consecutive_bars": 5}, {"use_ema": False})

        signals_2 = (result_2["signal"] != 0).sum()
        signals_5 = (result_5["signal"] != 0).sum()

        assert signals_5 <= signals_2, \
            f"consecutive=5({signals_5})はconsecutive=2({signals_2})以下"
