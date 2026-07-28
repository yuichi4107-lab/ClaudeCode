"""Phase 5: Win5最適化のテスト

予算制約下での買い目最適化と期待値計算を検証する。
"""

import sys
from pathlib import Path
from dataclasses import dataclass

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from optimizer.win5_combiner import Win5Combiner, Win5Selection, Win5Combination
from optimizer.budget_optimizer import BudgetOptimizer, BudgetAllocation
from optimizer.expected_value import ExpectedValueCalculator


def create_sample_predictions() -> dict[str, pd.DataFrame]:
    """
    5レース分のサンプル予測結果を生成

    Returns:
        {race_id: DataFrame(horse_number, calibrated_prob, horse_name)}
    """
    predictions = {}

    for race_num in range(1, 6):
        race_id = f"2026021508{race_num:02d}"

        # 各レース 12 頭の予測確率を生成（合計≈1.0）
        n_horses = 12
        raw_probs = np.random.exponential(0.1, n_horses)
        calibrated_probs = raw_probs / raw_probs.sum()

        data = {
            "horse_number": list(range(1, n_horses + 1)),
            "horse_name": [f"馬_{race_num}_{i}" for i in range(1, n_horses + 1)],
            "calibrated_prob": calibrated_probs.tolist(),
            "odds": (1.0 / calibrated_probs * 1.3).tolist(),  # 暗示確率の逆数 × 1.3
        }

        predictions[race_id] = pd.DataFrame(data)

    return predictions


def test_win5_combiner_initialization():
    """
    Win5Combiner の初期化テスト

    テスト項目:
    - 初期化後、5レースが検出されること
    - race_ids が正しく保存されること
    """
    print("\n=== Testing Win5Combiner Initialization ===")

    predictions = create_sample_predictions()
    combiner = Win5Combiner(predictions)

    assert len(combiner.race_ids) == 5, "Should have 5 races"
    assert combiner.predictions == predictions, "Predictions should be stored"

    print(f"✓ Win5Combiner initialized with {len(combiner.race_ids)} races")
    return True


def test_selection_generation():
    """
    各レースの選択馬生成テスト

    テスト項目:
    - generate_selections() で5つの Win5Selection が生成されること
    - 各 Selection の馬数が max_horses_per_race 以下であること
    """
    print("\n=== Testing Selection Generation ===")

    predictions = create_sample_predictions()
    combiner = Win5Combiner(predictions)

    selections = combiner.generate_selections(max_horses_per_race=3)

    assert len(selections) == 5, "Should have 5 selections"

    for i, sel in enumerate(selections):
        assert len(sel.horse_numbers) <= 3, f"Race {i} should have <= 3 horses"
        assert len(sel.horse_numbers) == len(sel.probabilities), "Horse count should match prob count"
        assert sum(sel.probabilities) <= 1.01, "Probabilities should sum to <= 1.0"

    print(f"✓ Selections generated:")
    for sel in selections:
        print(f"  Race {sel.race_number}: {len(sel.horse_numbers)} horses, prob={sum(sel.probabilities):.4f}")

    return True


def test_combination_counting():
    """
    組み合わせ数計算テスト

    テスト項目:
    - count_combinations() で正確な組み合わせ数が計算されること
    - 5レース (3, 3, 3, 3, 3) 選択 -> 3^5 = 243 組
    """
    print("\n=== Testing Combination Counting ===")

    predictions = create_sample_predictions()
    combiner = Win5Combiner(predictions)
    selections = combiner.generate_selections(max_horses_per_race=3)

    n_combos = combiner.count_combinations(selections)

    # 期待値: 3^5 = 243
    expected = 3 ** 5
    assert n_combos == expected, f"Expected {expected} combinations, got {n_combos}"

    print(f"✓ Combination count correct: {n_combos} (3^5)")
    return True


def test_hit_probability_calculation():
    """
    的中確率計算テスト

    テスト項目:
    - calculate_hit_probability() で正確な確率が計算されること
    - 各レースの選択馬の確率合計の積が返されること
    """
    print("\n=== Testing Hit Probability Calculation ===")

    # 手動で構築した簡単な例
    selections = [
        Win5Selection(
            race_id="R1",
            race_number=1,
            horse_numbers=[1, 2],
            horse_names=["A", "B"],
            probabilities=[0.4, 0.3],  # 合計 0.7
        ),
        Win5Selection(
            race_id="R2",
            race_number=2,
            horse_numbers=[1, 2],
            horse_names=["C", "D"],
            probabilities=[0.5, 0.2],  # 合計 0.7
        ),
        Win5Selection(
            race_id="R3",
            race_number=3,
            horse_numbers=[1],
            horse_names=["E"],
            probabilities=[0.8],  # 合計 0.8
        ),
        Win5Selection(
            race_id="R4",
            race_number=4,
            horse_numbers=[1, 2],
            horse_names=["F", "G"],
            probabilities=[0.6, 0.1],  # 合計 0.7
        ),
        Win5Selection(
            race_id="R5",
            race_number=5,
            horse_numbers=[1],
            horse_names=["H"],
            probabilities=[0.9],  # 合計 0.9
        ),
    ]

    predictions_dummy = {f"R{i}": pd.DataFrame() for i in range(1, 6)}
    combiner = Win5Combiner(predictions_dummy)

    hit_prob = combiner.calculate_hit_probability(selections)

    # 期待値: 0.7 * 0.7 * 0.8 * 0.7 * 0.9 = 0.24696
    expected = 0.7 * 0.7 * 0.8 * 0.7 * 0.9
    assert abs(hit_prob - expected) < 1e-6, f"Expected {expected}, got {hit_prob}"

    print(f"✓ Hit probability calculated correctly: {hit_prob:.6f}")
    return True


def test_budget_optimizer_allocation():
    """
    予算最適化テスト

    テスト項目:
    - find_optimal_allocation() が BudgetAllocation を返すこと
    - 的中確率を最大化する配置が選択されること
    - 予算制約を満たすこと（組み合わせ数 × 100 <= budget）
    """
    print("\n=== Testing Budget Optimizer ===")

    predictions = create_sample_predictions()
    combiner = Win5Combiner(predictions)

    budget = 10000  # 100 組 = 10,000円
    optimizer = BudgetOptimizer(combiner, budget=budget)

    alloc = optimizer.find_optimal_allocation(max_per_race=8)

    assert alloc is not None, "Should find optimal allocation"
    assert alloc.total_cost <= budget, f"Cost {alloc.total_cost} should be <= budget {budget}"
    assert alloc.num_combinations == np.prod(alloc.allocation), "Combo count should match allocation"

    print(f"✓ Optimal allocation found:")
    print(f"  Allocation: {alloc.allocation}")
    print(f"  Combinations: {alloc.num_combinations}")
    print(f"  Cost: ¥{alloc.total_cost}")
    print(f"  Hit Probability: {alloc.hit_probability:.4%}")

    return True


def test_top_allocations():
    """
    上位N個の配置取得テスト

    テスト項目:
    - find_top_allocations() で複数の候補が返されること
    - 的中確率でソートされていること
    """
    print("\n=== Testing Top Allocations ===")

    predictions = create_sample_predictions()
    combiner = Win5Combiner(predictions)
    optimizer = BudgetOptimizer(combiner, budget=30000)

    top_allocs = optimizer.find_top_allocations(max_per_race=5, top_n=5)

    assert len(top_allocs) > 0, "Should find allocations"
    assert len(top_allocs) <= 5, "Should return top 5"

    # 的中確率でソートされているか確認
    probs = [a.hit_probability for a in top_allocs]
    assert all(probs[i] >= probs[i+1] for i in range(len(probs)-1)), "Should be sorted by probability"

    print(f"✓ Top {len(top_allocs)} allocations found (sorted by probability)")
    for i, alloc in enumerate(top_allocs):
        print(f"  {i+1}. {alloc.allocation} -> {alloc.hit_probability:.4%}")

    return True


def test_expected_value_calculation():
    """
    期待値計算テスト

    テスト項目:
    - calculate_ev() が期待値を正確に計算すること
    - ROI が正確に計算されること
    """
    print("\n=== Testing Expected Value Calculation ===")

    from optimizer.win5_combiner import Win5Ticket

    ticket = Win5Ticket(
        selections=[],
        num_combinations=100,
        total_cost=10000,
        total_hit_probability=0.01,  # 1%
    )

    calc = ExpectedValueCalculator(estimated_pool=5_000_000_000, carryover=0)
    ev = calc.calculate_ev(ticket)

    assert "expected_value" in ev, "Should have expected_value"
    assert "roi_percent" in ev, "Should have ROI"
    assert ev["hit_probability"] == 0.01, "Hit probability should match"
    assert ev["cost"] == 10000, "Cost should match"

    print(f"✓ Expected value calculated:")
    print(f"  Hit Probability: {ev['hit_probability']:.4%}")
    print(f"  Estimated Payout: ¥{ev['estimated_payout']:,.0f}")
    print(f"  Cost: ¥{ev['cost']:,.0f}")
    print(f"  Expected Value: ¥{ev['expected_value']:,.0f}")
    print(f"  ROI: {ev['roi_percent']:.2f}%")

    return True


def test_payout_estimation():
    """
    配当推定テスト

    テスト項目:
    - estimate_payout() で配当が正確に計算されること
    - 制御率 30% が反映されること
    """
    print("\n=== Testing Payout Estimation ===")

    calc = ExpectedValueCalculator(estimated_pool=5_000_000_000, carryover=0)

    # シンプルなケース: 的中確率 0.1% (1/1000)
    hit_prob = 0.001
    payout = calc.estimate_payout(hit_prob)

    # 計算式:
    # net_pool = 5B × 0.7 = 3.5B
    # total_tickets = 5B / 100 = 50M
    # estimated_winners = 50M × 0.001 = 50k
    # payout = 3.5B / 50k = 70,000
    expected_payout = (5_000_000_000 * 0.7) / (5_000_000_000 / 100 * hit_prob)

    assert abs(payout - expected_payout) < 1, f"Expected {expected_payout}, got {payout}"

    print(f"✓ Payout estimated correctly: ¥{payout:,.0f}")
    return True


def test_edge_analysis():
    """
    エッジ分析テスト

    テスト項目:
    - edge_analysis() でモデル予測とオッズの乖離を計算すること
    - 正のエッジを持つ馬が識別されること
    """
    print("\n=== Testing Edge Analysis ===")

    calc = ExpectedValueCalculator()

    model_probs = [0.20, 0.15, 0.12, 0.10, 0.08]   # モデル予測
    market_probs = [0.15, 0.18, 0.14, 0.12, 0.10]  # オッズ暗示確率

    edges = calc.edge_analysis(model_probs, market_probs)

    assert len(edges) == 5, "Should have 5 edges"
    assert all("edge" in e for e in edges), "Should have edge field"
    assert edges[0]["edge"] >= edges[-1]["edge"], "Should be sorted by edge descending"

    print(f"✓ Edge analysis completed:")
    positive_edges = [e for e in edges if e["has_value"]]
    print(f"  Horses with positive edge (>2%): {len(positive_edges)}")
    for e in edges[:3]:
        print(f"    Horse {e['index']}: Model={e['model_prob']:.1%}, Market={e['market_prob']:.1%}, Edge={e['edge']:.1%}")

    return True


def test_budget_constraint_adherence():
    """
    予算制約の遵守テスト

    テスト項目:
    - 多くの予算値 (5000, 10000, 30000, 50000) で制約を遵守すること
    """
    print("\n=== Testing Budget Constraint Adherence ===")

    predictions = create_sample_predictions()
    combiner = Win5Combiner(predictions)

    budgets = [5000, 10000, 30000, 50000, 100000]

    for budget in budgets:
        optimizer = BudgetOptimizer(combiner, budget=budget)
        ticket = optimizer.optimize(max_per_race=8)

        if ticket:
            assert ticket.total_cost <= budget, f"Cost {ticket.total_cost} exceeds budget {budget}"
            print(f"✓ Budget ¥{budget:6d}: {ticket.num_combinations:3d} combos, cost ¥{ticket.total_cost:6d}")

    return True


def run_all_phase5_tests():
    """
    Phase 5 の全テストを実行
    """
    print("\n" + "=" * 70)
    print("Phase 5: Win5 Optimization - Test Suite")
    print("=" * 70)

    tests = [
        ("Win5Combiner Initialization", test_win5_combiner_initialization),
        ("Selection Generation", test_selection_generation),
        ("Combination Counting", test_combination_counting),
        ("Hit Probability Calculation", test_hit_probability_calculation),
        ("Budget Optimizer Allocation", test_budget_optimizer_allocation),
        ("Top Allocations", test_top_allocations),
        ("Expected Value Calculation", test_expected_value_calculation),
        ("Payout Estimation", test_payout_estimation),
        ("Edge Analysis", test_edge_analysis),
        ("Budget Constraint Adherence", test_budget_constraint_adherence),
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
    success = run_all_phase5_tests()
    sys.exit(0 if success else 1)
