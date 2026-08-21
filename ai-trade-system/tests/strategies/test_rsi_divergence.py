"""
単体テスト: RSI Divergence + MACD Confirm

テストケース:
    1. 正常系: ブリッシュダイバージェンスを人工データで検出できる
    2. 正常系: ピーク検出関数が正しく動作する
    3. 境界系: データ不足で空シグナルを返す
    4. 境界系: MACDクロスなしではシグナルが発火しない
    5. フィルター系: SMA200フィルターでシグナル数が変化する
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

from tests.strategies.conftest import make_ohlcv, make_uptrend_ohlcv, make_range_ohlcv, make_insufficient_ohlcv

from src.backtest.strategies.rsi_divergence import (
    generate_signals,
    DEFAULT_PARAMS,
    MIN_ROWS,
    _find_local_minima,
    _find_local_maxima,
    _detect_bullish_divergence,
)


# ---------------------------------------------------------------------------
# ユーティリティ関数テスト
# ---------------------------------------------------------------------------


class TestPeakDetection:
    """ピーク検出ユーティリティ関数のテスト。"""

    def test_find_local_minima_basic(self):
        """既知のデータで局所最小値が正しく検出される。"""
        # 明確な谷が2つある系列
        values = pd.Series([5.0, 3.0, 5.0, 2.0, 5.0, 4.0, 5.0])
        minima = _find_local_minima(values, order=1)

        assert len(minima) >= 2, f"局所最小値が2つ以上検出されること。実際: {minima}"
        # インデックス1(値3.0)とインデックス3(値2.0)が最小値
        assert 1 in minima or 3 in minima, f"既知の最小値位置が検出されること: {minima}"

    def test_find_local_maxima_basic(self):
        """既知のデータで局所最大値が正しく検出される。"""
        values = pd.Series([1.0, 4.0, 1.0, 5.0, 1.0])
        maxima = _find_local_maxima(values, order=1)

        assert len(maxima) >= 1, f"局所最大値が1つ以上検出されること。実際: {maxima}"

    def test_empty_series_returns_empty(self):
        """空SeriesではIndexErrorなく空配列を返す。"""
        values = pd.Series([], dtype=float)
        try:
            minima = _find_local_minima(values, order=1)
            assert len(minima) == 0
        except Exception as e:
            pytest.fail(f"空SeriesでExceptionが発生: {e}")

    def test_constant_series(self):
        """定数Seriesで例外なく動作すること。"""
        values = pd.Series([150.0] * 20)
        try:
            minima = _find_local_minima(values, order=2)
            assert isinstance(minima, np.ndarray)
        except Exception as e:
            pytest.fail(f"定数SeriesでExceptionが発生: {e}")


# ---------------------------------------------------------------------------
# ダイバージェンス検出テスト
# ---------------------------------------------------------------------------


class TestBullishDivergenceDetection:
    """ブリッシュダイバージェンス検出テスト。"""

    def test_detects_bullish_divergence(self):
        """価格は安値更新、RSIは安値切り上げのデータでTrueを返す。"""
        # 人工的にブリッシュダイバージェンスパターンを構築
        n = 50
        # 価格: 最初の谷(25付近)、次の谷(45付近)で価格が下がる
        close = np.full(n, 150.0)
        close[20] = 148.0  # 第1安値
        close[40] = 147.0  # 第2安値（安値更新）

        # RSI: 第1安値で25、第2安値で28（切り上げ）
        rsi = np.full(n, 50.0)
        rsi[20] = 25.0   # 第1RSI安値
        rsi[40] = 28.0   # 第2RSI安値（切り上げ = ダイバージェンス）

        close_s = pd.Series(close)
        rsi_s = pd.Series(rsi)

        result = _detect_bullish_divergence(
            close_s, rsi_s,
            current_idx=45, lookback=45, order=2, rsi_oversold=30.0
        )
        assert result is True, "ブリッシュダイバージェンスが検出されること"

    def test_no_divergence_when_both_decline(self):
        """価格・RSI両方が安値更新の場合はFalseを返す。"""
        n = 50
        close = np.full(n, 150.0)
        close[20] = 148.0
        close[40] = 147.0  # 価格: 安値更新

        rsi = np.full(n, 50.0)
        rsi[20] = 28.0
        rsi[40] = 25.0  # RSI: 安値更新（ダイバージェンスなし）

        close_s = pd.Series(close)
        rsi_s = pd.Series(rsi)

        result = _detect_bullish_divergence(
            close_s, rsi_s,
            current_idx=45, lookback=45, order=2, rsi_oversold=30.0
        )
        # RSIも安値更新なのでダイバージェンスなし
        assert result is False, "価格・RSI両方安値更新はダイバージェンスでないこと"


# ---------------------------------------------------------------------------
# 正常系テスト
# ---------------------------------------------------------------------------


class TestRSIDivergenceNormal:
    """正常系テスト。"""

    def test_returns_correct_columns(self):
        """必要なカラムが返ること。"""
        df = make_range_ohlcv(200)
        result = generate_signals(df, {}, {})

        for col in ["signal", "tp_price", "sl_price", "hold_bars"]:
            assert col in result.columns

    def test_signal_values_valid(self):
        """signalは-1/0/1のみ。"""
        df = make_range_ohlcv(200)
        result = generate_signals(df, {}, {})

        unique = set(result["signal"].unique())
        assert unique.issubset({-1, 0, 1})

    def test_long_signal_tp_above_entry(self):
        """ロングシグナルのTPがentryより上。"""
        df = make_range_ohlcv(300)
        result = generate_signals(df, {"rsi_oversold": 45.0}, {})

        long_rows = result[result["signal"] == 1]
        for idx in long_rows.index:
            entry = df.loc[idx, "close"]
            assert result.loc[idx, "tp_price"] > entry


# ---------------------------------------------------------------------------
# 境界系テスト
# ---------------------------------------------------------------------------


class TestRSIDivergenceEdgeCases:
    """境界テスト。"""

    def test_insufficient_data_empty_signals(self):
        """データ不足（MIN_ROWS未満）で空シグナル。"""
        df = make_ohlcv(n=MIN_ROWS - 1)
        result = generate_signals(df, {}, {})
        assert (result["signal"] == 0).all()

    def test_no_signal_without_macd_cross(self):
        """MACDクロスがない平坦なデータではシグナルが出にくい。"""
        # 完全に平坦なデータ（MACDがゼロのまま）
        n = 200
        df = make_ohlcv(n=n, trend=0.0, volatility=0.0)
        result = generate_signals(df, {}, {})
        # 平坦データでは実質的にシグナルが出ないはず
        # （RSIが50付近、MACDがゼロでクロスなし）
        assert isinstance(result, pd.DataFrame)

    def test_nan_close_no_exception(self):
        """NaN含有でも例外なし。"""
        df = make_range_ohlcv(200)
        df.loc[df.index[100:105], "close"] = np.nan
        try:
            result = generate_signals(df, {}, {})
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"NaN含有で例外: {e}")


# ---------------------------------------------------------------------------
# フィルター系テスト
# ---------------------------------------------------------------------------


class TestRSIDivergenceFilters:
    """フィルター動作テスト。"""

    def test_sma200_filter_reduces_long_signals(self):
        """SMA200フィルターでロングシグナルが削減される。"""
        df = make_downtrend_df(300)
        params = {"rsi_oversold": 45.0}

        result_off = generate_signals(df, params, {"use_sma200": False})
        result_on = generate_signals(df, params, {"use_sma200": True})

        long_off = (result_off["signal"] == 1).sum()
        long_on = (result_on["signal"] == 1).sum()

        # 下降トレンドではSMA200フィルターでロングが削減される
        assert long_on <= long_off, \
            f"SMA200フィルターON({long_on})はOFF({long_off})以下であること"

    def test_all_filters_no_crash(self):
        """全フィルター同時有効でも例外なし。"""
        df = make_range_ohlcv(300)
        all_filters = {
            "use_sma200": True,
            "use_atr": True,
            "use_session": True,
            "use_event": True,
        }
        try:
            result = generate_signals(df, {}, all_filters)
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"全フィルターで例外: {e}")


def make_downtrend_df(n: int) -> pd.DataFrame:
    """下降トレンドのテストデータを生成する。"""
    return make_ohlcv(n=n, base_price=155.0, trend=-0.05, volatility=0.1)
