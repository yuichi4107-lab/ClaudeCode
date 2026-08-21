"""
engine.py のユニットテスト。

エントリー/エグジットロジック（SL/TP/大引け）とスリッページ補正の正確性を検証する。
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
_BACKTEST_DIR = _REPO_ROOT / "jp-daytrade" / "backtest"


def _ensure_modules():
    """engine と screener / config を sys.modules に登録する。"""
    # --- strategy パッケージ ---
    pkg_name = "jpdaytrade_strategy"
    if pkg_name not in sys.modules:
        pkg = types.ModuleType(pkg_name)
        pkg.__path__ = [str(_STRATEGY_DIR)]
        pkg.__package__ = pkg_name
        sys.modules[pkg_name] = pkg

    cfg_name = f"{pkg_name}.config"
    if cfg_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(cfg_name, _STRATEGY_DIR / "config.py")
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = pkg_name
        sys.modules[cfg_name] = mod
        spec.loader.exec_module(mod)

    scr_name = f"{pkg_name}.screener"
    if scr_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(scr_name, _STRATEGY_DIR / "screener.py")
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = pkg_name
        sys.modules[scr_name] = mod
        spec.loader.exec_module(mod)

    # --- backtest パッケージ ---
    bt_pkg = "jpdaytrade_backtest"
    if bt_pkg not in sys.modules:
        pkg = types.ModuleType(bt_pkg)
        pkg.__path__ = [str(_BACKTEST_DIR)]
        pkg.__package__ = bt_pkg
        sys.modules[bt_pkg] = pkg

    eng_name = f"{bt_pkg}.engine"
    if eng_name not in sys.modules:
        spec = importlib.util.spec_from_file_location(eng_name, _BACKTEST_DIR / "engine.py")
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = bt_pkg
        sys.modules[eng_name] = mod
        spec.loader.exec_module(mod)

    return sys.modules[eng_name]


_engine = _ensure_modules()


# ---------------------------------------------------------------------------
# テスト用ヘルパー
# ---------------------------------------------------------------------------

def _make_row(
    code: str = "T001",
    date: str = "2024-01-10",
    open_price: float = 1000.0,
    high: float = 1100.0,
    low: float = 950.0,
    close: float = 1050.0,
    bonus_score: float = 0.0,
) -> pd.Series:
    """テスト用の 1 行 Series を生成する。"""
    return pd.Series({
        "code": code,
        "date": pd.Timestamp(date),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "volume": 2_000_000.0,
        "bonus_score": bonus_score,
    })


_TEST_CFG = {
    "slippage": 0.001,
    "tp1_pct": 0.05,
    "tp1_ratio": 0.5,
    "tp2_pct": 0.10,
    "sl_pct": -0.02,
}
_INVESTED = 300_000.0


# ---------------------------------------------------------------------------
# スリッページテスト
# ---------------------------------------------------------------------------

class TestSlippage:
    def test_buy_slippage_increases_price(self):
        """エントリー（買い）はスリッページで高くなる。"""
        result = _engine._apply_slippage(1000.0, "buy", 0.001)
        assert result == pytest.approx(1001.0)

    def test_sell_slippage_decreases_price(self):
        """エグジット（売り）はスリッページで低くなる。"""
        result = _engine._apply_slippage(1000.0, "sell", 0.001)
        assert result == pytest.approx(999.0)

    def test_zero_slippage(self):
        """スリッページ 0 の場合は価格変化なし。"""
        assert _engine._apply_slippage(1000.0, "buy", 0.0) == pytest.approx(1000.0)
        assert _engine._apply_slippage(1000.0, "sell", 0.0) == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# エグジットロジックテスト
# ---------------------------------------------------------------------------

class TestSimulateTrade:
    def test_sl_hit(self):
        """Low ≤ SL 価格 → 損切（SL 優先）。"""
        # エントリー価格 ≈ 1001（スリッページ後）
        # SL = 1001 * 0.98 ≈ 980.98
        # Low=970 ≤ 980.98 → SL ヒット
        row = _make_row(open_price=1000, high=1050, low=970, close=1020)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "SL"
        assert trade.pnl_pct < 0

    def test_tp1_and_tp2_hit(self):
        """High ≥ TP2 価格（SL未到達）→ TP1+TP2 両方利確。"""
        # エントリー ≈ 1001
        # TP1 = 1001 * 1.05 ≈ 1051.05
        # TP2 = 1001 * 1.10 ≈ 1101.1
        # High=1200 ≥ TP2, Low=990 > SL(≈980.98)
        row = _make_row(open_price=1000, high=1200, low=990, close=1050)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "TP1+TP2"
        assert trade.pnl_pct > 0

    def test_tp1_only_then_close(self):
        """High ≥ TP1（SL未到達）かつ High < TP2 → TP1+Close。"""
        # TP1 ≈ 1051, TP2 ≈ 1101, High=1080（TP1到達, TP2未到達）
        row = _make_row(open_price=1000, high=1080, low=990, close=1050)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "TP1+Close"
        assert trade.pnl_pct > 0

    def test_close_only(self):
        """TP1 未到達かつ SL 未到達 → 大引けクローズ。"""
        # TP1 ≈ 1051, SL ≈ 980, High=1040（TP1未到達）, Low=990（SL未到達）
        row = _make_row(open_price=1000, high=1040, low=990, close=1030)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "Close"

    def test_sl_takes_priority_over_tp(self):
        """Low ≤ SL かつ High ≥ TP1 の場合、SL 優先（保守的評価）。"""
        # Low=970 ≤ SL(≈980.98), High=1200 ≥ TP1(≈1051)
        row = _make_row(open_price=1000, high=1200, low=970, close=1050)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "SL"
        assert trade.pnl_pct < 0

    def test_pnl_abs_proportional_to_invested(self):
        """pnl_abs は invested に比例する。"""
        row = _make_row(open_price=1000, high=1040, low=990, close=1030)
        trade1 = _engine.simulate_trade(row, 100_000.0, _TEST_CFG)
        trade2 = _engine.simulate_trade(row, 200_000.0, _TEST_CFG)
        assert trade2.pnl_abs == pytest.approx(trade1.pnl_abs * 2, rel=1e-3)

    def test_entry_price_has_slippage(self):
        """エントリー価格はスリッページで Open より高い。"""
        row = _make_row(open_price=1000)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.entry_price > trade.open_price

    def test_sl_exit_price_has_slippage(self):
        """損切エグジット価格はスリッページで SL 理論値より低い。"""
        row = _make_row(open_price=1000, high=1050, low=960, close=990)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.exit_reason == "SL"
        sl_theoretical = trade.entry_price * (1 + _TEST_CFG["sl_pct"])
        assert trade.exit_price_full < sl_theoretical


# ---------------------------------------------------------------------------
# 寄り天判定テスト
# ---------------------------------------------------------------------------

class TestYoriTen:
    def test_yori_ten_detected(self):
        """Open == High（寄り付きが高値）の場合は寄り天フラグ True。"""
        row = _make_row(open_price=1000, high=1000, low=950, close=970)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.is_yori_ten is True

    def test_not_yori_ten(self):
        """Open < High（高値は寄り付き後）は寄り天フラグ False。"""
        row = _make_row(open_price=1000, high=1100, low=950, close=1050)
        trade = _engine.simulate_trade(row, _INVESTED, _TEST_CFG)
        assert trade.is_yori_ten is False


# ---------------------------------------------------------------------------
# パフォーマンス指標計算テスト
# ---------------------------------------------------------------------------

class TestComputeMetrics:
    def _make_trade(self, pnl_pct: float, is_yori_ten: bool = False) -> object:
        """ダミー Trade オブジェクトを生成する。"""
        return _engine.Trade(
            date="2024-01-01",
            code="T001",
            open_price=1000.0,
            entry_price=1001.0,
            close_price_day=1050.0,
            high=1100.0,
            low=980.0,
            sl_price=980.98,
            tp1_price=1051.05,
            tp2_price=1101.1,
            exit_price_full=1000.0,
            exit_price_tp1=1000.0,
            exit_price_tp2=1000.0,
            exit_reason="Close",
            pnl_pct=pnl_pct,
            pnl_abs=300_000 * pnl_pct,
            shares=299.7,
            invested=300_000.0,
            bonus_score=0.0,
            is_yori_ten=is_yori_ten,
        )

    def test_win_rate_calculation(self):
        """勝率が正しく計算される。"""
        trades = [
            self._make_trade(0.05),
            self._make_trade(0.05),
            self._make_trade(-0.02),
            self._make_trade(-0.02),
        ]
        daily_pnl_list = [(f"2024-01-{i+1:02d}", t.pnl_abs) for i, t in enumerate(trades)]
        result = _engine._compute_metrics(trades, daily_pnl_list, 1_000_000, 1_000_000)
        assert result.win_rate == pytest.approx(0.5)

    def test_profit_factor_calculation(self):
        """PF = 総利益 / 総損失 が正しく計算される。"""
        trades = [
            self._make_trade(0.10),
            self._make_trade(-0.02),
        ]
        daily_pnl_list = [(f"2024-01-{i+1:02d}", t.pnl_abs) for i, t in enumerate(trades)]
        result = _engine._compute_metrics(trades, daily_pnl_list, 1_000_000, 1_000_000)
        assert result.profit_factor == pytest.approx(0.10 / 0.02, rel=1e-3)

    def test_yori_ten_rate(self):
        """寄り天発生率が正しく計算される（2/4 = 50%）。"""
        trades = [
            self._make_trade(0.05, is_yori_ten=True),
            self._make_trade(0.05, is_yori_ten=True),
            self._make_trade(-0.02, is_yori_ten=False),
            self._make_trade(-0.02, is_yori_ten=False),
        ]
        daily_pnl_list = [(f"2024-01-{i+1:02d}", t.pnl_abs) for i, t in enumerate(trades)]
        result = _engine._compute_metrics(trades, daily_pnl_list, 1_000_000, 1_000_000)
        assert result.yori_ten_rate == pytest.approx(0.5)

    def test_zero_trades(self):
        """取引ゼロの場合はデフォルト値が返る。"""
        result = _engine._compute_metrics([], [], 1_000_000, 1_000_000)
        assert result.total_trades == 0
        assert result.win_rate == 0.0
