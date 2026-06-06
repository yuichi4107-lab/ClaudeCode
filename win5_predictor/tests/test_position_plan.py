"""傾向ベース買い目提案のテスト。"""

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from popularity.position_plan import (  # noqa: E402
    position_buy_plan,
    position_cum_probs,
    position_frontier,
)


def _df(rows):
    recs = []
    for r in rows:
        recs.append({"date": pd.Timestamp("2026-01-01"),
                     "p1": r[0], "p2": r[1], "p3": r[2], "p4": r[3], "p5": r[4]})
    return pd.DataFrame(recs)


def test_cum_probs_monotone_and_bounded():
    df = _df([[1, 2, 3, 4, 5], [1, 1, 2, 8, 3], [2, 1, 1, 1, 1]])
    cums = position_cum_probs(df, max_rank=18)
    for pos in range(1, 6):
        c = cums[pos]
        assert all(c[i] <= c[i + 1] + 1e-12 for i in range(len(c) - 1))  # 単調非減少
        assert c[-1] == pytest.approx(1.0)


def test_solid_position_gets_fewer_horses():
    # pos1 は常に1番人気が勝つ(堅い)、pos3 は毎回バラバラ(荒れる)
    rows = [
        [1, 1, 1, 1, 1],
        [1, 2, 5, 1, 2],
        [1, 1, 9, 2, 1],
        [1, 3, 7, 1, 2],
    ]
    df = _df(rows)
    plan = position_buy_plan(df, budget_yen=10000)
    # pos1(index0) は1頭で十分(実績100%)、pos3(index2) はより多く買う
    assert plan.k_per_pos[0] == 1
    assert plan.k_per_pos[2] >= plan.k_per_pos[0]


def test_frontier_monotone_and_budget():
    df = _df([[1, 2, 3, 4, 5], [2, 1, 6, 2, 3], [1, 1, 9, 8, 1], [3, 2, 5, 1, 2]])
    fr = position_frontier(df, max_points=2000)
    hits = [p.hit_prob for p in fr]
    pts = [p.points for p in fr]
    assert hits == sorted(hits)
    assert pts == sorted(pts)
    plan = position_buy_plan(df, budget_yen=3000)
    assert plan.cost_yen <= 3000
    assert 0 < plan.hit_prob <= 1


def test_hit_prob_is_product_of_cumprobs():
    df = _df([[1, 2, 3, 4, 5], [2, 1, 6, 2, 3]])
    plan = position_buy_plan(df, budget_yen=5000)
    prod = 1.0
    for c in plan.cum_per_pos:
        prod *= c
    assert plan.hit_prob == pytest.approx(prod)
