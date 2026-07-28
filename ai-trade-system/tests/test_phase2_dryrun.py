"""Phase 2 ショート対応の dry-run 統合検証（API Key 不要）"""
import os
import sys
import tempfile
from datetime import datetime, timezone, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)

JST = timezone(timedelta(hours=9))

from src.trading.trader import AutoTrader
from src.trading.position_manager import PositionManager, PositionStatus
from src.trading import simulation_tracker as sim_module
from src.trading.simulation_tracker import SimulationTracker


def test_trader_startup_dryrun():
    """検証1: Futures モード dry-run で AutoTrader が正常起動"""
    print("\n=== 検証1: Futures dry-run 起動 ===")
    trader = AutoTrader(exchange_id="binance_futures_testnet", dry_run=True)
    assert trader.is_futures == True, "is_futures should be True"
    assert trader.quote_currency == "USDT", f"quote_currency should be USDT, got {trader.quote_currency}"
    assert trader.exchange is None, "exchange should be None in dry-run"
    assert trader.MAX_CONCURRENT_SHORT_POSITIONS == 3
    assert trader.DAILY_SHORT_LOSS_LIMIT_PCT == -5.0
    print("  OK: trader startup, is_futures=True, quote=USDT, safety constants confirmed")


def test_safety_max_positions():
    """検証3a: 最大同時建玉数制限"""
    print("\n=== 検証3a: 最大同時ショート建玉数制限（3件） ===")
    tmp = tempfile.mkdtemp()
    trader = AutoTrader(exchange_id="binance_futures_testnet", dry_run=True)
    # PM を一時ファイルに差し替え
    trader.pm = PositionManager(positions_file=os.path.join(tmp, "p.json"), history_file=os.path.join(tmp, "h.json"))

    # 3件ショートポジション作成
    for i, sym in enumerate(["ETH/USDT", "XRP/USDT", "BTC/USDT"]):
        trader.pm.open_position(sym, 100 + i, 1, f"ord{i}", stop_loss=0.03, take_profit=0.05, hold_bars=20, strategy_id=f"s{i}", direction="short")

    count = trader._count_open_short_positions()
    assert count == 3, f"should be 3 short positions, got {count}"
    print(f"  OK: _count_open_short_positions returned {count}")

    # 4件目ロングも追加してカウントに含まれないことを確認
    trader.pm.open_position("SOL/USDT", 100, 1, "long1", stop_loss=0.05, take_profit=0.10, hold_bars=20, strategy_id="l1", direction="long")
    count = trader._count_open_short_positions()
    assert count == 3, f"long position should not be counted in short count, got {count}"
    print(f"  OK: long positions not counted, still {count} shorts")


def test_safety_daily_loss_limit():
    """検証3b: 日次損失 circuit breaker"""
    print("\n=== 検証3b: 日次ショート累計損失-5%でエントリー停止 ===")
    tmp = tempfile.mkdtemp()
    trader = AutoTrader(exchange_id="binance_futures_testnet", dry_run=True)
    trader.pm = PositionManager(positions_file=os.path.join(tmp, "p.json"), history_file=os.path.join(tmp, "h.json"))

    # 閾値未満: 問題なし
    allowed, reason = trader._check_daily_short_loss_limit()
    assert allowed == True, f"should be allowed when no history, got allowed={allowed}"
    print(f"  OK: empty history → allowed={allowed}, {reason}")

    # ショートの損失トレードを当日作成（-3%損失）
    trader.pm.open_position("ETH/USDT", 100, 1, "o1", stop_loss=0.03, take_profit=0.05, hold_bars=20, strategy_id="s1", direction="short")
    trader.pm.close_position("ETH/USDT:s1", 103.0, PositionStatus.CLOSED_SL)  # -3% loss

    allowed, reason = trader._check_daily_short_loss_limit()
    assert allowed == True, f"-3% should still be allowed, got allowed={allowed}"
    print(f"  OK: -3% loss → allowed={allowed}, {reason}")

    # さらに -3% 追加（累計 -6% で閾値超過）
    trader.pm.open_position("XRP/USDT", 1.0, 100, "o2", stop_loss=0.03, take_profit=0.05, hold_bars=20, strategy_id="s2", direction="short")
    trader.pm.close_position("XRP/USDT:s2", 1.03, PositionStatus.CLOSED_SL)  # -3% loss

    allowed, reason = trader._check_daily_short_loss_limit()
    assert allowed == False, f"accumulated -6% should block, got allowed={allowed}"
    print(f"  OK: accumulated -6% → blocked, {reason}")


def test_position_short_pnl_flow():
    """検証4: ショートポジションの完全フロー"""
    print("\n=== 検証4: ショートポジシャ決済フロー（SL/TP/Hold全件） ===")
    tmp = tempfile.mkdtemp()
    pm = PositionManager(positions_file=os.path.join(tmp, "p.json"), history_file=os.path.join(tmp, "h.json"))

    # SL テスト
    pm.open_position("ETH/USDT", 100, 1, "sl1", stop_loss=0.005, take_profit=None, hold_bars=15, strategy_id="rally_top", direction="short")
    pos = pm.get_position("ETH/USDT:rally_top")
    assert pos["direction"] == "short"
    assert pos["stop_loss_price"] == 100.5, f"SL price should be 100.5, got {pos['stop_loss_price']}"

    should, reason = pm.check_exit_conditions("ETH/USDT:rally_top", 100.6)
    assert should and reason == PositionStatus.CLOSED_SL
    close = pm.close_position("ETH/USDT:rally_top", 100.5, PositionStatus.CLOSED_SL)
    assert close["pnl_pct"] == -0.5, f"SL pnl should be -0.5%, got {close['pnl_pct']}"
    print(f"  OK: SL case: entry=100, SL=100.5, exit=100.5, PnL={close['pnl_pct']}%")

    # TP テスト
    pm.open_position("XRP/USDT", 1.0, 100, "tp1", stop_loss=None, take_profit=0.02, hold_bars=25, strategy_id="rally_top", direction="short")
    pos = pm.get_position("XRP/USDT:rally_top")
    assert pos["take_profit_price"] == 0.98, f"TP price should be 0.98, got {pos['take_profit_price']}"

    should, reason = pm.check_exit_conditions("XRP/USDT:rally_top", 0.97)
    assert should and reason == PositionStatus.CLOSED_TP
    close = pm.close_position("XRP/USDT:rally_top", 0.98, PositionStatus.CLOSED_TP)
    assert close["pnl_pct"] == 2.0, f"TP pnl should be +2.0%, got {close['pnl_pct']}"
    print(f"  OK: TP case: entry=1.0, TP=0.98, exit=0.98, PnL={close['pnl_pct']}%")

    # Hold テスト: チェック回数ではなく、エントリーからの実経過日数で判定
    pm.open_position("XRP/USDT", 1.0, 100, "h1", stop_loss=None, take_profit=0.01, hold_bars=30, strategy_id="double_top", direction="short")
    pos = pm.get_position("XRP/USDT:double_top")

    # 4時間後の巡回では、30日保有期限に到達しない
    pos["opened_at"] = (pm._now() - timedelta(hours=4)).isoformat()
    pm.increment_bars("XRP/USDT:double_top")
    should, reason = pm.check_exit_conditions("XRP/USDT:double_top", 0.995)
    assert not should, f"4h check should not expire 30-day hold, got reason={reason}"

    # 30日経過で満了
    pos["opened_at"] = (pm._now() - timedelta(days=30)).isoformat()
    should, reason = pm.check_exit_conditions("XRP/USDT:double_top", 0.995)  # TP/SL未達
    assert should and reason == PositionStatus.CLOSED_HOLD
    close = pm.close_position("XRP/USDT:double_top", 0.995, PositionStatus.CLOSED_HOLD)
    assert close["pnl_pct"] == 0.5, f"Hold pnl should be +0.5%, got {close['pnl_pct']}"
    print(f"  OK: Hold case: entry=1.0, exit=0.995, PnL={close['pnl_pct']}%")


def test_long_noregression():
    """検証5: ロング戦略への影響なし"""
    print("\n=== 検証5: ロング戦略の非破壊確認 ===")
    tmp = tempfile.mkdtemp()
    pm = PositionManager(positions_file=os.path.join(tmp, "p.json"), history_file=os.path.join(tmp, "h.json"))

    # ロング（direction省略）
    pm.open_position("BTC/USDT", 100, 1, "l1", stop_loss=0.05, take_profit=0.10, hold_bars=20, strategy_id="double_bottom")
    pos = pm.get_position("BTC/USDT:double_bottom")
    assert pos["direction"] == "long"
    assert pos["stop_loss_price"] == 95.0
    assert pos["take_profit_price"] == 110.0

    # ロング SL
    should, reason = pm.check_exit_conditions("BTC/USDT:double_bottom", 94)
    assert should and reason == PositionStatus.CLOSED_SL
    close = pm.close_position("BTC/USDT:double_bottom", 95, PositionStatus.CLOSED_SL)
    assert close["pnl_pct"] == -5.0
    print(f"  OK: long SL: entry=100, exit=95, PnL={close['pnl_pct']}% (expected -5.0%)")


def test_hold_period_uses_elapsed_days_for_live_and_sim():
    """検証6: 4時間巡�nでも5日/10日の保有期間として扱う"""
    print("\n=== 検証6: 保有期間はチェック回数ではなく実経過日数 ===")
    tmp = tempfile.mkdtemp()

    pm = PositionManager(positions_file=os.path.join(tmp, "p.json"), history_file=os.path.join(tmp, "h.json"))
    pm.open_position("BTC/USDT", 100, 1, "h5", stop_loss=None, take_profit=None, hold_bars=5, strategy_id="hold5")
    pos = pm.get_position("BTC/USDT:hold5")
    pos["opened_at"] = (pm._now() - timedelta(days=4, hours=23)).isoformat()
    pm.increment_bars("BTC/USDT:hold5")
    should, reason = pm.check_exit_conditions("BTC/USDT:hold5", 100)
    assert not should, f"4d23h should not expire 5-day hold, got reason={reason}"

    pos["opened_at"] = (pm._now() - timedelta(days=5)).isoformat()
    should, reason = pm.check_exit_conditions("BTC/USDT:hold5", 100)
    assert should and reason == PositionStatus.CLOSED_HOLD

    sim_module.SIM_DIR = tmp
    sim_module.SIM_POSITIONS_FILE = os.path.join(tmp, "sim_positions.json")
    sim_module.SIM_HISTORY_FILE = os.path.join(tmp, "sim_history.json")
    sim_module.SIM_REPORTS_DIR = os.path.join(tmp, "reports")
    sim = SimulationTracker()
    sim_pos = sim.record_signal("ETH/USDT", "hold10", 100, None, None, 10)
    sim_pos["opened_at"] = (sim._now() - timedelta(days=9, hours=23)).isoformat()
    sim.update_positions(lambda symbol: 101)
    assert sim.positions, "9d23h should keep sim position open"

    key = next(iter(sim.positions))
    sim.positions[key]["opened_at"] = (sim._now() - timedelta(days=10)).isoformat()
    sim.update_positions(lambda symbol: 101)
    assert not sim.positions, "10d elapsed should close sim position"
    assert sim.history[-1]["close_reason"] == "hold_expired"
    print("  OK: live and simulation hold periods use elapsed days")


if __name__ == "__main__":
    test_trader_startup_dryrun()
    test_safety_max_positions()
    test_safety_daily_loss_limit()
    test_position_short_pnl_flow()
    test_long_noregression()
    test_hold_period_uses_elapsed_days_for_live_and_sim()
    print("\n\n========== ALL 6 TESTS PASSED ==========")
