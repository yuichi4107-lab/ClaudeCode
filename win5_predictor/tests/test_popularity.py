"""人気分布モデルのユニットテスト。"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from popularity import PopularityModel, uniform_strategies  # noqa: E402
from popularity.backtest import backtest_uniform  # noqa: E402
from popularity.loader import POP_COLS, winning_popularities  # noqa: E402
from popularity.strategy import greedy_budget_frontier  # noqa: E402


def test_model_fit_distribution_sums_to_one():
    pops = [1, 1, 2, 3, 1, 2, 4, 1, 1, 2]
    m = PopularityModel().fit(pops)
    assert m.n_races == 10
    total = sum(m.win_prob(k) for k in range(1, m.max_rank + 1))
    assert total == pytest.approx(1.0)
    # 1番人気が最頻
    assert m.win_prob(1) == pytest.approx(0.5)


def test_cumulative_prob_monotone():
    pops = [1, 2, 3, 4, 5, 1, 2, 3]
    m = PopularityModel().fit(pops)
    cums = [m.cum_win_prob(r) for r in range(1, 6)]
    assert cums == sorted(cums)
    assert m.cum_win_prob(18) == pytest.approx(1.0)


def test_fit_empty_raises():
    with pytest.raises(ValueError):
        PopularityModel().fit([])


def test_uniform_strategy_costs_and_hitprob():
    pops = [1] * 8 + [2, 3]  # 1番人気が 80%
    m = PopularityModel().fit(pops)
    strats = uniform_strategies(m, max_r=3)
    # r=1: 点数1, 費用100
    assert strats[0]["points"] == 1
    assert strats[0]["cost_yen"] == 100
    # r=2: 点数32, 費用3200
    assert strats[1]["points"] == 32
    assert strats[1]["cost_yen"] == 3200
    # 的中率は r が増えると単調増加
    probs = [s["hit_prob"] for s in strats]
    assert probs == sorted(probs)


def test_greedy_frontier_increases_hitprob():
    pops = [1, 1, 2, 2, 3, 4, 5, 1]
    m = PopularityModel().fit(pops)
    fr = greedy_budget_frontier(m, max_points=1000)
    hits = [f["hit_prob"] for f in fr]
    assert hits == sorted(hits)  # 単調非減少
    assert fr[0]["points"] == 1


def _df_from_rounds(rounds):
    rows = []
    for d, pops, payout, tickets in rounds:
        row = {"date": pd.Timestamp(d), "race": "R", "grade": "G1",
               "payout_yen": payout, "hit_tickets": tickets, "pops_verified": True}
        for c, p in zip(POP_COLS, pops):
            row[c] = p
        rows.append(row)
    return pd.DataFrame(rows)


def test_backtest_hit_and_roi():
    # 2回: 1回目は全部1番人気(=r>=1で的中), 2回目は5番人気混じり
    rounds = [
        ("2025-01-01", [1, 1, 1, 1, 1], 10000, 50),
        ("2025-01-08", [1, 2, 1, 5, 1], 200000, 5),
    ]
    df = _df_from_rounds(rounds)
    # r=1: 1回目のみ的中、費用 100*2=200、払戻 10000
    res = backtest_uniform(df, r=1)
    assert res["rounds"] == 2
    assert res["hits"] == 1
    assert res["total_cost_yen"] == 200
    assert res["total_return_yen"] == 10000
    assert res["roi"] == pytest.approx((10000 - 200) / 200)


def test_backtest_skips_missing_pops():
    df = pd.DataFrame([
        {"date": pd.Timestamp("2025-01-01"), "race": "R", "grade": "G1",
         "payout_yen": 1000, "hit_tickets": 10, "pops_verified": False,
         "p1": 1, "p2": 1, "p3": 1, "p4": 1, "p5": None},
    ])
    res = backtest_uniform(df, r=2)
    assert res["rounds"] == 0


def test_winning_popularities_requires_all_five():
    df = pd.DataFrame([
        {"p1": 1, "p2": 2, "p3": 3, "p4": 4, "p5": 5, "pops_verified": True},
        {"p1": 1, "p2": 2, "p3": 3, "p4": 4, "p5": None, "pops_verified": True},
    ])
    pops = winning_popularities(df)
    assert pops == [1, 2, 3, 4, 5]
