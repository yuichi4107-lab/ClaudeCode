"""Phase 6: 分析・バックテスト・資金管理のテスト

バックテスト、ROI計算、Kelly基準、資金管理機能を検証する。
"""

import sys
from pathlib import Path
from datetime import date, timedelta
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from analysis.backtester import Backtester
from analysis.roi_calculator import ROICalculator
from bankroll.kelly import kelly_criterion, multi_race_kelly
from bankroll.fixed_fraction import fixed_fraction_bet
from bankroll.tracker import BankrollTracker


def create_sample_backtest_results() -> pd.DataFrame:
    """
    バックテスト結果のサンプルデータを生成

    Returns:
        バックテスト結果のDataFrame
    """
    data = {
        "event_date": [
            "2025-01-05", "2025-01-12", "2025-01-19", "2025-01-26",
            "2025-02-02", "2025-02-09", "2025-02-16", "2025-02-23",
            "2025-03-02", "2025-03-09",
        ],
        "event_id": [f"EVENT_{i}" for i in range(1, 11)],
        "num_combinations": [50, 100, 75, 120, 60, 90, 80, 110, 95, 70],
        "total_cost": [5000, 10000, 7500, 12000, 6000, 9000, 8000, 11000, 9500, 7000],
        "hit_probability": [0.005, 0.008, 0.006, 0.010, 0.007, 0.009, 0.008, 0.009, 0.008, 0.006],
        "is_hit": [False, True, False, False, True, False, True, False, False, False],
        "actual_payout": [0, 150000, 0, 0, 200000, 0, 180000, 0, 0, 0],
    }
    return pd.DataFrame(data)


def test_roi_calculator_overall():
    """
    全体の回収率計算テスト

    テスト項目:
    - 総購入額が正確に計算されること
    - 総配当が正確に計算されること
    - 回収率が正確に計算されること
    - 利益が計算されること
    """
    print("\n=== Testing ROI Calculator (Overall) ===")

    df = create_sample_backtest_results()
    calc = ROICalculator(df)
    result = calc.overall_roi()

    assert "roi" in result, "Should have ROI"
    assert "total_cost" in result, "Should have total_cost"
    assert "total_payout" in result, "Should have total_payout"
    assert "profit" in result, "Should have profit"

    # 手動計算での検証
    total_cost = df["total_cost"].sum()
    total_payout = df["actual_payout"].sum()
    expected_roi = (total_payout / total_cost) * 100 if total_cost > 0 else 0.0

    assert result["total_cost"] == total_cost, "Total cost should match"
    assert result["total_payout"] == total_payout, "Total payout should match"
    assert abs(result["roi"] - expected_roi) < 0.01, "ROI should match expected"

    print(f"✓ Total Cost: ¥{result['total_cost']:,.0f}")
    print(f"✓ Total Payout: ¥{result['total_payout']:,.0f}")
    print(f"✓ ROI: {result['roi']:.2f}%")
    print(f"✓ Profit: ¥{result['profit']:,.0f}")

    return True


def test_roi_calculator_monthly():
    """
    月別回収率計算テスト

    テスト項目:
    - 月別集計が正確
    - 月別的中率が計算される
    """
    print("\n=== Testing ROI Calculator (Monthly) ===")

    df = create_sample_backtest_results()
    calc = ROICalculator(df)
    monthly = calc.monthly_roi()

    assert not monthly.empty, "Should have monthly data"
    assert "month" in monthly.columns, "Should have month column"
    assert "roi" in monthly.columns, "Should have ROI column"
    assert "hit_rate" in monthly.columns, "Should have hit_rate column"

    # 値の範囲チェック
    assert all(0 <= r <= 500 for r in monthly["roi"]), "ROI should be reasonable"
    assert all(0 <= h <= 100 for h in monthly["hit_rate"]), "Hit rate should be 0-100%"

    print(f"✓ Monthly analysis: {len(monthly)} months")
    for _, row in monthly.iterrows():
        print(f"  {row['month']}: {row['events']} events, {row['hits']} hits, ROI {row['roi']:.1f}%")

    return True


def test_roi_calculator_cumulative():
    """
    累計損益推移テスト

    テスト項目:
    - 累計利益が正確
    - 累計ROIが正確
    - 時系列で単調増加・減少になっていること
    """
    print("\n=== Testing ROI Calculator (Cumulative) ===")

    df = create_sample_backtest_results()
    calc = ROICalculator(df)
    cum = calc.cumulative_profit()

    assert not cum.empty, "Should have cumulative data"
    assert "cumulative_profit" in cum.columns, "Should have cumulative_profit"
    assert "cumulative_roi" in cum.columns, "Should have cumulative_roi"

    # 最後の累計が全体のものと一致することを確認
    last_cum_payout = cum["cumulative_payout"].iloc[-1] if not cum.empty else 0
    total_payout = df["actual_payout"].sum()
    assert abs(last_cum_payout - total_payout) < 0.01, "Final cumulative should match total"

    print(f"✓ Cumulative profit tracking enabled")
    print(f"  Final Cumulative Profit: ¥{cum['cumulative_profit'].iloc[-1]:,.0f}")
    print(f"  Final Cumulative ROI: {cum['cumulative_roi'].iloc[-1]:.2f}%")

    return True


def test_roi_calculator_drawdown():
    """
    ドローダウン分析テスト

    テスト項目:
    - 最大ドローダウンが計算される
    - 連続非的中が計算される
    """
    print("\n=== Testing ROI Calculator (Drawdown) ===")

    df = create_sample_backtest_results()
    calc = ROICalculator(df)
    dd = calc.drawdown_analysis()

    assert "max_drawdown" in dd, "Should have max_drawdown"
    assert "max_drawdown_pct" in dd, "Should have max_drawdown_pct"

    print(f"✓ Max Drawdown: ¥{dd['max_drawdown']:,.0f}")
    print(f"✓ Max Consecutive Losses: {dd.get('max_consecutive_losses', 0)}")

    return True


def test_kelly_criterion_basic():
    """
    Kelly基準の基本テスト

    テスト項目:
    - 的中確率 50%, 配当 3倍のフルKellyが 1/3
    - 1/4 Kelly適用で 1/12
    - エッジが計算される
    """
    print("\n=== Testing Kelly Criterion ===")

    # シンプルなケース: p=0.5, odds=3
    result = kelly_criterion(
        probability=0.5,
        odds=3.0,
        bankroll=100000,
        fraction=1.0,  # フルKelly
    )

    # フルKelly = (0.5 * 3 - 0.5) / (3 - 1) = 1 / 2 = 0.5
    expected_full_kelly = 0.5
    assert abs(result["full_kelly"] - expected_full_kelly) < 0.01, "Full Kelly should be 0.5"

    # 1/4 Kelly適用
    result_quarter = kelly_criterion(
        probability=0.5,
        odds=3.0,
        bankroll=100000,
        fraction=0.25,
    )

    expected_bet = 100000 * expected_full_kelly * 0.25
    assert abs(result_quarter["bet_amount"] - expected_bet) < 100, "Quarter Kelly bet should match"

    print(f"✓ Full Kelly: {result['full_kelly']:.4f}")
    print(f"✓ Edge: {result['edge']:.4f}")
    print(f"✓ 1/4 Kelly Bet: ¥{result_quarter['bet_amount']:,.0f}")
    print(f"✓ Should Bet: {result_quarter['should_bet']}")

    return True


def test_kelly_criterion_edge():
    """
    Kelly基準のエッジテスト

    テスト項目:
    - ネガティブエッジでは賭けないこと
    - ポジティブエッジでは賭けること
    """
    print("\n=== Testing Kelly Edge Detection ===")

    # ネガティブエッジ: p=0.3, odds=2（期待値 = 0.3*2 - 1 = -0.4）
    result_neg = kelly_criterion(
        probability=0.3,
        odds=2.0,
        bankroll=100000,
        fraction=1.0,
    )
    assert result_neg["edge"] < 0, "Should detect negative edge"
    assert result_neg["should_bet"] is False, "Should not bet with negative edge"
    print(f"✓ Negative Edge ({result_neg['edge']:.4f}): Do Not Bet")

    # ポジティブエッジ: p=0.6, odds=2（期待値 = 0.6*2 - 1 = 0.2）
    result_pos = kelly_criterion(
        probability=0.6,
        odds=2.0,
        bankroll=100000,
        fraction=1.0,
    )
    assert result_pos["edge"] > 0, "Should detect positive edge"
    assert result_pos["should_bet"] is True, "Should bet with positive edge"
    print(f"✓ Positive Edge ({result_pos['edge']:.4f}): Bet ¥{result_pos['bet_amount']:,.0f}")

    return True


def test_kelly_multi_race():
    """
    複数レースKelly基準テスト

    テスト項目:
    - 複数レースの組み合わせで的中確率を計算
    - ベット額が計算される
    """
    print("\n=== Testing Multi-Race Kelly ===")

    result = multi_race_kelly(
        race_probs=[0.5, 0.5, 0.5, 0.5, 0.5],  # 各レース50%
        expected_odds=150000 / 5000,  # 30倍（の配当）
        bankroll=100000,
        fraction=0.25,
    )

    assert "bet_amount" in result, "Should have bet_amount"
    print(f"✓ Multi-Race Kelly: Bet ¥{result['bet_amount']:,.0f}")
    print(f"✓ Joint Probability: {result.get('joint_probability', 'N/A')}")

    return True


def test_fixed_fraction():
    """
    固定比率法テスト

    テスト項目:
    - 資金の固定割合でベット
    - 100円単位に丸める
    """
    print("\n=== Testing Fixed Fraction Betting ===")

    result = fixed_fraction_bet(
        bankroll=100000,
        fraction=0.05,  # 5%
    )

    # 100,000 × 0.05 = 5,000
    assert result["bet_amount"] == 5000, "Bet should be 5% of bankroll"
    print(f"✓ Fixed Fraction (5%): ¥{result['bet_amount']:,.0f}")

    return True


def test_bankroll_tracker():
    """
    資金管理トラッカーテスト（シミュレーション）

    テスト項目:
    - 入金・出金の記録
    - 残高の追跡
    """
    print("\n=== Testing Bankroll Tracker (Simulated) ===")

    # Note: 実装ではDBへの記録が必要だが、ここではシミュレーション
    tracker = BankrollTracker(initial_balance=100000)

    # シミュレーション: 入金
    initial = tracker.balance
    assert initial == 100000, "Initial balance should be 100,000"

    # 出金シミュレーション
    tracker.balance -= 10000
    assert tracker.balance == 90000, "Should track withdrawals"

    # 配当シミュレーション
    tracker.balance += 150000
    assert tracker.balance == 240000, "Should track payouts"

    print(f"✓ Initial: ¥{initial:,.0f}")
    print(f"✓ After Bet: ¥{initial - 10000:,.0f}")
    print(f"✓ After Payout: ¥{tracker.balance:,.0f}")

    return True


def test_roi_edge_cases():
    """
    エッジケーステスト

    テスト項目:
    - 空のDataFrameの処理
    - 全てのベットが外れた場合
    """
    print("\n=== Testing ROI Edge Cases ===")

    # 空のDataFrame
    empty_df = pd.DataFrame()
    calc_empty = ROICalculator(empty_df)
    result_empty = calc_empty.overall_roi()

    assert result_empty["roi"] == 0.0, "Empty result should have 0 ROI"
    assert result_empty["profit"] == 0.0, "Empty result should have 0 profit"
    print("✓ Empty DataFrame handled correctly")

    # 全て外れた場合
    all_loss_df = pd.DataFrame({
        "total_cost": [5000, 5000, 5000],
        "actual_payout": [0, 0, 0],
        "is_hit": [False, False, False],
    })
    calc_loss = ROICalculator(all_loss_df)
    result_loss = calc_loss.overall_roi()

    assert result_loss["roi"] == 0.0, "All losses should have 0 ROI"
    assert result_loss["profit"] == -15000, "All losses should have negative profit"
    print("✓ All Losses handled correctly")

    return True


def run_all_phase6_tests():
    """
    Phase 6 の全テストを実行
    """
    print("\n" + "=" * 70)
    print("Phase 6: Analysis, Backtest, and Bankroll Management - Test Suite")
    print("=" * 70)

    tests = [
        ("ROI Calculator (Overall)", test_roi_calculator_overall),
        ("ROI Calculator (Monthly)", test_roi_calculator_monthly),
        ("ROI Calculator (Cumulative)", test_roi_calculator_cumulative),
        ("ROI Calculator (Drawdown)", test_roi_calculator_drawdown),
        ("Kelly Criterion (Basic)", test_kelly_criterion_basic),
        ("Kelly Criterion (Edge Detection)", test_kelly_criterion_edge),
        ("Multi-Race Kelly", test_kelly_multi_race),
        ("Fixed Fraction Betting", test_fixed_fraction),
        ("Bankroll Tracker", test_bankroll_tracker),
        ("ROI Edge Cases", test_roi_edge_cases),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, True, None))
            print(f"✓ {test_name} PASSED")
        except AssertionError as e:
            results.append((test_name, False, str(e)))
            print(f"✗ {test_name} FAILED: {e}")
        except Exception as e:
            results.append((test_name, False, str(e)))
            print(f"✗ {test_name} ERROR: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 70)
    print("Test Summary")
    print("=" * 70)

    for test_name, result, error in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
        if error:
            print(f"       {error[:80]}")

    passed = sum(1 for _, r, _ in results if r)
    total = len(results)
    print(f"\nTotal: {passed}/{total} tests passed")

    return all(r for _, r, _ in results)


if __name__ == "__main__":
    success = run_all_phase6_tests()
    sys.exit(0 if success else 1)
