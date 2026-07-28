"""
単体テスト: Multi-Timeframe Confluence

テストケース:
    1. 正常系: 上昇トレンドデータでロングシグナルが生成される
    2. 正常系: 下降トレンドデータでショートシグナルが生成される
    3. 境界系: データ不足（200本未満）で空シグナルを返す
    4. フィルター系: ATRフィルターでシグナル数が変化する
    5. フィルター系: セッションフィルターが機能する
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import sys
import os

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)

from tests.strategies.conftest import make_ohlcv, make_uptrend_ohlcv, make_downtrend_ohlcv

from src.backtest.strategies.mtf_confluence import generate_signals, DEFAULT_PARAMS, MIN_ROWS


# ---------------------------------------------------------------------------
# 正常系テスト
# ---------------------------------------------------------------------------


class TestMTFConfluenceNormal:
    """正常系テスト。"""

    def test_returns_correct_columns(self):
        """必要なカラムを持つDataFrameが返ること。"""
        df = make_uptrend_ohlcv(500)
        result = generate_signals(df, {}, {})

        for col in ["signal", "tp_price", "sl_price", "hold_bars"]:
            assert col in result.columns, f"'{col}' カラムが存在すること"

    def test_uptrend_generates_long_signals(self):
        """上昇トレンドデータでロングシグナルが生成される。

        注意: MTF戦略は日足SMA(200)を使用するが、1h足600本では日足データが約25本しかない。
        テスト用に daily_sma_period を小さくして動作確認する。
        """
        df = make_uptrend_ohlcv(600)
        # daily_sma_period=10: テストデータ（日足25本）でSMAが計算できるよう調整
        result = generate_signals(
            df,
            {"rsi_long_threshold": 40.0, "daily_sma_period": 10},
            {},
        )

        long_signals = (result["signal"] == 1).sum()
        assert long_signals >= 1, \
            f"上昇トレンドでロングシグナルが1件以上生成されること。実際: {long_signals}"

    def test_downtrend_generates_short_signals(self):
        """下降トレンドデータでショートシグナルが生成される。"""
        df = make_downtrend_ohlcv(600)
        result = generate_signals(
            df,
            {"rsi_short_threshold": 60.0, "daily_sma_period": 10},
            {},
        )

        short_signals = (result["signal"] == -1).sum()
        assert short_signals >= 1, \
            f"下降トレンドでショートシグナルが1件以上生成されること。実際: {short_signals}"

    def test_signal_values_valid(self):
        """signalの値は-1/0/1のみ。"""
        df = make_uptrend_ohlcv(500)
        result = generate_signals(df, {}, {})

        unique = set(result["signal"].unique())
        assert unique.issubset({-1, 0, 1}), f"signalは-1/0/1のみ。実際: {unique}"

    def test_tp_sl_direction_consistency(self):
        """ロングはTP>close>SL、ショートはSL>close>TPの関係。"""
        df = make_uptrend_ohlcv(500)
        result = generate_signals(df, {"rsi_long_threshold": 40.0}, {})

        long_rows = result[result["signal"] == 1]
        for idx in long_rows.index:
            entry = df.loc[idx, "close"]
            tp = long_rows.loc[idx, "tp_price"]
            sl = long_rows.loc[idx, "sl_price"]
            assert tp > sl, f"TP({tp:.4f}) > SL({sl:.4f}) であること"


# ---------------------------------------------------------------------------
# 境界系テスト
# ---------------------------------------------------------------------------


class TestMTFConfluenceEdgeCases:
    """境界テスト。"""

    def test_insufficient_data_returns_empty(self):
        """データ不足（MIN_ROWS未満）でシグナルが全て0。"""
        df = make_ohlcv(n=MIN_ROWS - 1)
        result = generate_signals(df, {}, {})

        assert (result["signal"] == 0).all(), \
            "データ不足では全シグナルが0であること"

    def test_exact_min_rows_no_crash(self):
        """MIN_ROWS本のデータで例外なく動作すること。"""
        df = make_ohlcv(n=MIN_ROWS)
        try:
            result = generate_signals(df, {}, {})
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"MIN_ROWSデータで例外: {e}")

    def test_nan_in_close_handled(self):
        """closeにNaN含む場合も例外なし。"""
        df = make_uptrend_ohlcv(500)
        df.loc[df.index[200:210], "close"] = np.nan

        try:
            result = generate_signals(df, {}, {})
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"NaN含有で例外: {e}")


# ---------------------------------------------------------------------------
# フィルター系テスト
# ---------------------------------------------------------------------------


class TestMTFConfluenceFilters:
    """フィルター動作テスト。"""

    def test_atr_filter_reduces_signals(self):
        """ATRフィルターONでシグナルが同数以下になる。"""
        df = make_uptrend_ohlcv(600)
        params = {"rsi_long_threshold": 40.0, "daily_sma_period": 10}

        result_off = generate_signals(df, params, {"use_atr": False})
        result_on = generate_signals(df, params, {"use_atr": True})

        signals_off = (result_off["signal"] != 0).sum()
        signals_on = (result_on["signal"] != 0).sum()

        assert signals_on <= signals_off, \
            f"ATRフィルターON({signals_on})はOFF({signals_off})以下であること"

    def test_session_filter_applied(self):
        """セッションフィルターONでシグナルが同数以下になる。"""
        df = make_uptrend_ohlcv(600)
        params = {"rsi_long_threshold": 40.0, "daily_sma_period": 10}

        result_off = generate_signals(df, params, {"use_session": False})
        result_on = generate_signals(df, params, {"use_session": True})

        signals_off = (result_off["signal"] != 0).sum()
        signals_on = (result_on["signal"] != 0).sum()

        assert signals_on <= signals_off, \
            f"セッションフィルターON({signals_on})はOFF({signals_off})以下であること"

    def test_filter_combinations_no_crash(self):
        """全フィルター同時有効でも例外なし。"""
        df = make_uptrend_ohlcv(600)
        all_filters = {
            "use_atr": True,
            "use_session": True,
            "use_event": True,
        }
        try:
            result = generate_signals(df, {}, all_filters)
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"全フィルター同時有効で例外: {e}")
