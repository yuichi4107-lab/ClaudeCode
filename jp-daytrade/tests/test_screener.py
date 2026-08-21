"""
screener.py のユニットテスト。

各フィルターの正確性を個別に検証する。
先読みバイアスのないことを確認するテストも含む。
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# パッケージルート設定
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_STRATEGY_DIR = _REPO_ROOT / "jp-daytrade" / "strategy"


def _ensure_strategy_package() -> types.ModuleType:
    """
    strategy パッケージと config / screener モジュールを sys.modules に登録する。

    ハイフン入りディレクトリのためパッケージ名は `jpdaytrade_strategy` で登録する。
    """
    pkg_name = "jpdaytrade_strategy"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_STRATEGY_DIR)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg

    # config
    cfg_name = f"{pkg_name}.config"
    if cfg_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            cfg_name, _STRATEGY_DIR / "config.py",
            submodule_search_locations=[],
        )
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = pkg_name
        sys.modules[cfg_name] = mod
        spec.loader.exec_module(mod)
        # screener.py が `from .config import` できるよう、親パッケージ属性に設定
        sys.modules[pkg_name].config = mod

    # screener（config より後）
    scr_name = f"{pkg_name}.screener"
    if scr_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            scr_name, _STRATEGY_DIR / "screener.py",
            submodule_search_locations=[],
        )
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = pkg_name
        sys.modules[scr_name] = mod
        spec.loader.exec_module(mod)
        sys.modules[pkg_name].screener = mod

    return sys.modules[f"{pkg_name}.screener"]


# モジュールを一度だけロード
_screener = _ensure_strategy_package()


# ---------------------------------------------------------------------------
# テスト用サンプルデータ生成ヘルパー
# ---------------------------------------------------------------------------

def _make_prices(rows: list[dict]) -> pd.DataFrame:
    """テスト用の日足 DataFrame を生成する。"""
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume", "turnover"]:
        if col not in df.columns:
            df[col] = 0.0
    df["adjustment_factor"] = 1.0
    return df.sort_values(["code", "date"]).reset_index(drop=True)


def _make_master(rows: list[dict]) -> pd.DataFrame:
    """テスト用の stocks_master DataFrame を生成する。"""
    df = pd.DataFrame(rows)
    if "is_value_stock" not in df.columns:
        # is_value_stock を計算（stocks_master の STORED 列を模倣）
        unit_shares = df.get("unit_shares", pd.Series([100] * len(df)))
        df["is_value_stock"] = (
            (df["last_price"] > 3000) |
            (df["last_price"] * unit_shares > 300000)
        ).astype(int)
    return df


# ---------------------------------------------------------------------------
# F1: 株価フィルターテスト
# ---------------------------------------------------------------------------

class TestF1Price:
    def test_excludes_high_price_stocks(self):
        """3,000円超の銘柄は除外される。"""
        master = _make_master([
            {"code": "A001", "name": "安い", "market": "グロース", "last_price": 500.0, "unit_shares": 100},
            {"code": "A002", "name": "高い", "market": "グロース", "last_price": 3001.0, "unit_shares": 100},
        ])
        result = _screener.apply_f1_price(master)
        assert "A001" in result["code"].values
        assert "A002" not in result["code"].values

    def test_includes_exactly_3000(self):
        """3,000円ちょうどは通過する。"""
        master = _make_master([
            {"code": "A003", "name": "境界", "market": "グロース", "last_price": 3000.0, "unit_shares": 100},
        ])
        result = _screener.apply_f1_price(master)
        assert "A003" in result["code"].values

    def test_excludes_high_unit_price(self):
        """単元代金 > 30万円は除外される（例: 3,100円 × 100株 = 310,000円）。"""
        master = _make_master([
            {"code": "A004", "name": "高単元", "market": "グロース", "last_price": 3100.0, "unit_shares": 100},
        ])
        result = _screener.apply_f1_price(master)
        assert "A004" not in result["code"].values

    def test_all_eligible(self):
        """全銘柄が条件を満たす場合、全件返す。"""
        master = _make_master([
            {"code": "A005", "name": "A", "market": "グロース", "last_price": 500.0, "unit_shares": 100},
            {"code": "A006", "name": "B", "market": "グロース", "last_price": 1500.0, "unit_shares": 100},
        ])
        result = _screener.apply_f1_price(master)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# F3: 日中値幅率テスト
# ---------------------------------------------------------------------------

class TestF3IntradayRange:
    def _build_data_with_range(self, high_low_ratio: float, days: int = 7) -> pd.DataFrame:
        """指定した値幅率を持つ日足データを生成する。"""
        rows = []
        base_close = 1000.0
        for i in range(days):
            close = base_close
            high = close * (1 + high_low_ratio / 2)
            low = close * (1 - high_low_ratio / 2)
            rows.append({
                "code": "T001",
                "date": f"2024-01-{i+1:02d}",
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 2_000_000.0,
            })
        return _make_prices(rows)

    def test_high_range_passes(self):
        """値幅率 10%（≥5%）は通過する。"""
        prices = self._build_data_with_range(0.10, days=8)
        prices = _screener.compute_intraday_range(prices, days=5)
        valid = prices.dropna(subset=["intraday_range_avg"])
        result = _screener.apply_f3_intraday_range(valid)
        assert len(result) > 0

    def test_low_range_fails(self):
        """値幅率 2%（<5%）は除外される。"""
        prices = self._build_data_with_range(0.02, days=8)
        prices = _screener.compute_intraday_range(prices, days=5)
        valid = prices.dropna(subset=["intraday_range_avg"])
        result = _screener.apply_f3_intraday_range(valid)
        assert len(result) == 0

    def test_no_lookahead_bias(self):
        """当日データが intraday_range_avg に含まれないこと（先読みバイアスなし）。"""
        rows = []
        for i in range(6):
            ratio = 0.01 if i < 5 else 0.20  # 6日目だけ高値幅
            close = 1000.0
            high = close * (1 + ratio / 2)
            low = close * (1 - ratio / 2)
            rows.append({
                "code": "T002",
                "date": f"2024-01-{i+1:02d}",
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 2_000_000.0,
            })
        prices = _make_prices(rows)
        prices = _screener.compute_intraday_range(prices, days=5)

        # 6 日目の intraday_range_avg は「前日まで」の 5 日平均 → 低値幅のはず
        last_row = prices[prices["code"] == "T002"].iloc[-1]
        assert last_row["intraday_range_avg"] < 0.05, (
            f"先読みバイアスを検出: intraday_range_avg={last_row['intraday_range_avg']:.4f}"
        )


# ---------------------------------------------------------------------------
# F4: 前日出来高テスト
# ---------------------------------------------------------------------------

class TestF4Volume:
    def test_high_volume_passes(self):
        """前日出来高 200万株（≥100万株）は通過する。"""
        rows = [
            {"code": "V001", "date": "2024-01-01", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 2_000_000.0},
            {"code": "V001", "date": "2024-01-02", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 1_500_000.0},
        ]
        prices = _make_prices(rows)
        prices = _screener.compute_prev_volume(prices)
        result = _screener.apply_f4_volume(prices)
        assert len(result[result["code"] == "V001"]) == 1

    def test_low_volume_fails(self):
        """前日出来高 50万株（<100万株）は除外される。"""
        rows = [
            {"code": "V002", "date": "2024-01-01", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 500_000.0},
            {"code": "V002", "date": "2024-01-02", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 800_000.0},
        ]
        prices = _make_prices(rows)
        prices = _screener.compute_prev_volume(prices)
        result = _screener.apply_f4_volume(prices)
        assert len(result[result["code"] == "V002"]) == 0

    def test_no_lookahead_bias(self):
        """volume_prev が当日の前日分を指しているか確認。"""
        rows = [
            {"code": "V003", "date": "2024-01-01", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 500_000.0},
            {"code": "V003", "date": "2024-01-02", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 5_000_000.0},
        ]
        prices = _make_prices(rows)
        prices = _screener.compute_prev_volume(prices)
        row2 = prices[prices["date"] == pd.Timestamp("2024-01-02")].iloc[0]
        assert row2["volume_prev"] == 500_000.0


# ---------------------------------------------------------------------------
# F5: GAP率テスト（プロキシ）
# ---------------------------------------------------------------------------

class TestF5GapRate:
    def test_gap_up_passes(self):
        """+5% GAP（≥+3%）は通過する。"""
        rows = [
            {"code": "G001", "date": "2024-01-01", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
            {"code": "G001", "date": "2024-01-02", "open": 1050, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
        ]
        prices = _make_prices(rows)
        prices = _screener.compute_gap_rate(prices)
        result = _screener.apply_f5_gap_rate(prices)
        assert len(result[result["code"] == "G001"]) == 1

    def test_small_gap_fails(self):
        """+1% GAP（<+3%）は除外される。"""
        rows = [
            {"code": "G002", "date": "2024-01-01", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
            {"code": "G002", "date": "2024-01-02", "open": 1010, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
        ]
        prices = _make_prices(rows)
        prices = _screener.compute_gap_rate(prices)
        result = _screener.apply_f5_gap_rate(prices)
        assert len(result[result["code"] == "G002"]) == 0

    def test_no_lookahead_bias(self):
        """prev_close が当日の前日終値を参照していること。"""
        rows = [
            {"code": "G003", "date": "2024-01-01", "open": 1000, "high": 1100, "low": 900, "close": 900, "volume": 1_000_000},
            {"code": "G003", "date": "2024-01-02", "open": 960, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
        ]
        prices = _make_prices(rows)
        prices = _screener.compute_gap_rate(prices)
        row2 = prices[prices["date"] == pd.Timestamp("2024-01-02")].iloc[0]
        expected_gap = 960 / 900 - 1
        assert abs(row2["gap_rate"] - expected_gap) < 1e-6

    def test_gap_down_fails(self):
        """マイナス GAP は除外される。"""
        rows = [
            {"code": "G004", "date": "2024-01-01", "open": 1000, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
            {"code": "G004", "date": "2024-01-02", "open": 950, "high": 1100, "low": 900, "close": 1000, "volume": 1_000_000},
        ]
        prices = _make_prices(rows)
        prices = _screener.compute_gap_rate(prices)
        result = _screener.apply_f5_gap_rate(prices)
        assert len(result[result["code"] == "G004"]) == 0


# ---------------------------------------------------------------------------
# 加点3: 前週同日比出来高テスト
# ---------------------------------------------------------------------------

class TestBonusVolumeRatio:
    def test_high_ratio_gets_bonus(self):
        """前週同日比 300%（≥200%）は加点される。"""
        rows = []
        for i in range(8):
            vol = 3_000_000.0 if i == 6 else 1_000_000.0  # 7日目（i=6）: 前日分
            rows.append({
                "code": "B001",
                "date": f"2024-01-{i+1:02d}",
                "open": 1000, "high": 1100, "low": 900, "close": 1000,
                "volume": vol,
            })
        prices = _make_prices(rows)
        prices = _screener.compute_prev_volume(prices)
        prices = _screener.compute_volume_ratio_week_ago(prices)
        prices = _screener.compute_bonus_score(prices)
        last = prices.iloc[-1]
        assert last["bonus_volume_ratio"] == 1

    def test_low_ratio_no_bonus(self):
        """前週同日比 150%（<200%）は加点されない。"""
        rows = []
        for i in range(8):
            vol = 1_500_000.0 if i == 6 else 1_000_000.0
            rows.append({
                "code": "B002",
                "date": f"2024-01-{i+1:02d}",
                "open": 1000, "high": 1100, "low": 900, "close": 1000,
                "volume": vol,
            })
        prices = _make_prices(rows)
        prices = _screener.compute_prev_volume(prices)
        prices = _screener.compute_volume_ratio_week_ago(prices)
        prices = _screener.compute_bonus_score(prices)
        last = prices.iloc[-1]
        assert last["bonus_volume_ratio"] == 0


# ---------------------------------------------------------------------------
# F2 スキップ・ライブ専用フィルターテスト
# ---------------------------------------------------------------------------

class TestSkippedFilters:
    def test_f2_emits_warning(self):
        """F2 呼び出し時に UserWarning が発生すること。"""
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            _screener.apply_f2_market_cap_skip()
            assert len(w) == 1
            assert issubclass(w[0].category, UserWarning)
            assert "F2" in str(w[0].message)

    def test_f6_live_only_no_error(self):
        """F6（ライブ専用）はバックテスト時にエラーなく動作する。"""
        _screener.apply_f6_presale_ratio_live_only(is_backtest=True)

    def test_f7_live_only_no_error(self):
        """F7（ライブ専用）はバックテスト時にエラーなく動作する。"""
        _screener.apply_f7_board_depth_live_only(is_backtest=True)
