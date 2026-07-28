"""
単体テスト: BB Mean Reversion + Trend Filter

テストケース:
    1. 正常系: BB下限タッチでロングシグナルが生成される
    2. 正常系: フィルター有効時にSMA200フィルターが機能する
    3. 境界系: データ不足（10本）でemptyシグナルを返す
    4. 境界系: 全NaN closeでも例外なく空シグナルを返す
    5. フィルター系: フィルターON/OFFでシグナル数が異なる
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import sys
import os

# プロジェクトルートをパスに追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from tests.strategies.conftest import make_ohlcv, make_range_ohlcv, make_insufficient_ohlcv

from src.backtest.strategies.bb_reversion import generate_signals, DEFAULT_PARAMS


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------


def make_bb_touch_df(n: int = 200) -> pd.DataFrame:
    """
    BB下限タッチを人工的に作るデータを生成する。

    最後の数本でcloseを大きく下げてBB下限を下回るようにする。
    """
    df = make_range_ohlcv(n)
    # 後半の特定位置を強制的にBB下限付近に下げる
    # BB(20)の下限 ≈ mean - 2*std。rangeデータのstd≈0.3程度なので mean-3.0を割り込ませる
    target_pos = n - 10
    for i in range(target_pos, min(target_pos + 3, n)):
        df.at[i, "close"] = df["close"].iloc[: target_pos].mean() - 3.0
        df.at[i, "low"] = df.at[i, "close"] - 0.1
        df.at[i, "open"] = df.at[i, "close"] + 0.05
        df.at[i, "high"] = df.at[i, "open"] + 0.1
    return df


# ---------------------------------------------------------------------------
# テスト1: 正常系 — シグナルが生成される
# ---------------------------------------------------------------------------


class TestBBReversionNormal:
    """正常系テスト: シグナル生成の基本動作。"""

    def test_returns_dataframe_with_signal_columns(self):
        """generate_signals がシグナルカラムを持つDataFrameを返す。"""
        df = make_range_ohlcv(200)
        result = generate_signals(df, {}, {})

        assert isinstance(result, pd.DataFrame), "戻り値はDataFrameであること"
        assert "signal" in result.columns, "signalカラムが存在すること"
        assert "tp_price" in result.columns, "tp_priceカラムが存在すること"
        assert "sl_price" in result.columns, "sl_priceカラムが存在すること"
        assert "hold_bars" in result.columns, "hold_barsカラムが存在すること"

    def test_signal_values_are_valid(self):
        """signalの値が1/-1/0のみであること。"""
        df = make_range_ohlcv(200)
        result = generate_signals(df, {}, {})

        unique_signals = set(result["signal"].unique())
        assert unique_signals.issubset({-1, 0, 1}), \
            f"signalの値は-1/0/1のみ。実際: {unique_signals}"

    def test_long_signal_generated_on_bb_touch(self):
        """BB下限タッチでロングシグナルが少なくとも1件生成される。"""
        df = make_bb_touch_df(200)
        result = generate_signals(df, {"rsi_oversold": 50.0}, {})  # RSI閾値を緩める

        long_signals = (result["signal"] == 1).sum()
        assert long_signals >= 1, \
            f"BB下限タッチでロングシグナルが1件以上生成されること。実際: {long_signals}"

    def test_tp_sl_consistency_for_long(self):
        """ロングシグナルのTP > entry > SL。"""
        df = make_bb_touch_df(200)
        result = generate_signals(df, {"rsi_oversold": 50.0}, {})

        long_rows = result[result["signal"] == 1]
        if len(long_rows) == 0:
            pytest.skip("ロングシグナルなし（スキップ）")

        for idx, row in long_rows.iterrows():
            entry = df.loc[idx, "close"]
            assert row["tp_price"] > entry, \
                f"ロングのTPはentry価格より高いこと: tp={row['tp_price']:.4f}, entry={entry:.4f}"
            assert row["sl_price"] < entry, \
                f"ロングのSLはentry価格より低いこと: sl={row['sl_price']:.4f}, entry={entry:.4f}"
            assert row["hold_bars"] > 0, "hold_barsは0より大きいこと"


# ---------------------------------------------------------------------------
# テスト2: 正常系 — SMA200フィルター
# ---------------------------------------------------------------------------


class TestBBReversionSMA200Filter:
    """SMA200フィルターの動作テスト。"""

    def test_sma200_filter_reduces_signals(self):
        """SMA200フィルターON時はOFF時より同数以下のシグナルを返す。"""
        df = make_range_ohlcv(300)

        result_no_filter = generate_signals(df, {"rsi_oversold": 50.0}, {"use_sma200": False})
        result_with_filter = generate_signals(df, {"rsi_oversold": 50.0}, {"use_sma200": True})

        signals_no_filter = (result_no_filter["signal"] != 0).sum()
        signals_with_filter = (result_with_filter["signal"] != 0).sum()

        assert signals_with_filter <= signals_no_filter, (
            f"フィルターON({signals_with_filter})はOFF({signals_no_filter})以下のシグナル数であること"
        )

    def test_filter_flags_work_independently(self):
        """各フィルターフラグが独立して動作すること。"""
        df = make_range_ohlcv(300)

        result_none = generate_signals(df, {}, {})
        result_sma = generate_signals(df, {}, {"use_sma200": True})
        result_atr = generate_signals(df, {}, {"use_atr": True})

        # 異なる設定で同一のDataFrame構造を返すこと
        assert result_none.shape == result_sma.shape == result_atr.shape, \
            "フィルター設定によらずDataFrame形状は同一であること"


# ---------------------------------------------------------------------------
# テスト3: 境界系 — データ不足
# ---------------------------------------------------------------------------


class TestBBReversionEdgeCases:
    """境界テスト: データ不足・異常値。"""

    def test_insufficient_data_returns_empty_signals(self):
        """データ不足（10本）でシグナルが全て0になること（例外なし）。"""
        df = make_insufficient_ohlcv(10)
        result = generate_signals(df, {}, {})

        assert isinstance(result, pd.DataFrame), "DataFrameが返ること"
        assert (result["signal"] == 0).all(), \
            "データ不足の場合はシグナルが全て0であること"

    def test_nan_close_handled_gracefully(self):
        """closeにNaNを含むデータで例外なく処理できること。"""
        df = make_range_ohlcv(200)
        df.loc[df.index[100:110], "close"] = np.nan
        df.loc[df.index[100:110], "high"] = np.nan
        df.loc[df.index[100:110], "low"] = np.nan

        # 例外なく実行できること
        try:
            result = generate_signals(df, {}, {})
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"NaN含有データで例外が発生: {e}")

    def test_extreme_values_handled(self):
        """極端に大きい/小さい価格でも例外なく処理できること。"""
        df = make_range_ohlcv(100)
        df.loc[df.index[50], "close"] = 1e6  # 極端な高値
        df.loc[df.index[51], "close"] = 0.001  # 極端な安値

        try:
            result = generate_signals(df, {}, {})
            assert isinstance(result, pd.DataFrame)
        except Exception as e:
            pytest.fail(f"極端な値で例外が発生: {e}")

    def test_single_row_returns_empty(self):
        """1行のデータでも例外なく空シグナルを返すこと。"""
        df = make_ohlcv(n=1)
        result = generate_signals(df, {}, {})
        assert isinstance(result, pd.DataFrame)
        assert (result["signal"] == 0).all()


# ---------------------------------------------------------------------------
# テスト4: パラメータ検証
# ---------------------------------------------------------------------------


class TestBBReversionParams:
    """パラメータ設定の検証テスト。"""

    def test_default_params_work(self):
        """DEFAULT_PARAMSでエラーなく動作すること。"""
        df = make_range_ohlcv(200)
        result = generate_signals(df, DEFAULT_PARAMS, {})
        assert isinstance(result, pd.DataFrame)

    def test_custom_params_override_defaults(self):
        """カスタムパラメータがデフォルトを上書きすること。"""
        df = make_range_ohlcv(200)
        # 非常に緩いRSI閾値（シグナルが増える可能性）
        result_loose = generate_signals(df, {"rsi_oversold": 70.0, "rsi_overbought": 30.0}, {})
        result_strict = generate_signals(df, {"rsi_oversold": 10.0, "rsi_overbought": 90.0}, {})

        signals_loose = (result_loose["signal"] != 0).sum()
        signals_strict = (result_strict["signal"] != 0).sum()

        assert signals_loose >= signals_strict, \
            "緩いRSI閾値ではシグナルが多く出ること"
