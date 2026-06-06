"""単勝オッズ WIN5 モデルのテスト。"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from popularity import (  # noqa: E402
    Horse,
    Race,
    best_within_budget,
    combination_fair_odds,
    implied_win_probs,
    optimize_win5,
)


def test_implied_probs_sum_to_one_and_devig():
    # オーバーラウンドのあるオッズ
    odds = [2.0, 3.0, 6.0]  # 1/2+1/3+1/6 = 1.0 ちょうど（控除0の理想）
    p = implied_win_probs(odds)
    assert p.sum() == pytest.approx(1.0)
    # 控除があるケースでも正規化で 1 になる
    p2 = implied_win_probs([1.5, 3.0, 4.0, 10.0])
    assert p2.sum() == pytest.approx(1.0)
    # オッズが低い馬ほど勝率高い
    assert p2[0] > p2[1] > p2[2] > p2[3]


def test_implied_probs_beta_shifts_to_favorite():
    odds = [2.0, 4.0, 8.0]
    base = implied_win_probs(odds, beta=1.0)
    fav = implied_win_probs(odds, beta=1.5)
    assert fav[0] > base[0]  # 本命に寄る
    assert fav.sum() == pytest.approx(1.0)


def test_implied_probs_rejects_bad_odds():
    with pytest.raises(ValueError):
        implied_win_probs([1.0, 2.0])


def _mk_race(odds_list, name="R"):
    horses = [Horse(umaban=i + 1, odds=o) for i, o in enumerate(odds_list)]
    return Race(horses, name=name)


def test_race_sorts_by_prob_and_detects_pop_mismatch():
    horses = [
        Horse(umaban=1, odds=5.0, pop=1),  # 実際は人気下位なのに pop=1 → 不一致
        Horse(umaban=2, odds=1.8, pop=2),
    ]
    r = Race(horses)
    assert r.horses[0].umaban == 2  # オッズ低い方が先頭
    assert r.pop_mismatch  # 不一致を検出


def test_optimize_frontier_monotone_and_budget():
    races = [
        _mk_race([2.0, 4.0, 8.0, 16.0]),
        _mk_race([1.8, 5.0, 9.0]),
        _mk_race([3.0, 3.5, 5.0, 12.0]),
        _mk_race([1.5, 6.0, 10.0]),
        _mk_race([4.0, 4.5, 5.0, 9.0, 20.0]),
    ]
    frontier = optimize_win5(races, max_points=5000)
    hits = [s.hit_prob for s in frontier]
    pts = [s.points for s in frontier]
    assert hits == sorted(hits)  # 的中確率は単調非減少
    assert pts == sorted(pts)
    assert frontier[0].points == 1
    # 予算内で最良を選べる
    best = best_within_budget(races, budget_yen=3000)
    assert best.cost_yen <= 3000
    assert 0 < best.hit_prob <= 1


def test_combination_fair_odds():
    races = [_mk_race([2.0, 4.0]) for _ in range(5)]
    # 各レース本命勝率 = (1/2)/(1/2+1/4) = 2/3
    fair = combination_fair_odds(races)
    assert fair == pytest.approx((1 / ((2 / 3) ** 5)))


def test_hit_prob_equals_product_of_cumprob():
    races = [_mk_race([2.0, 4.0, 8.0]) for _ in range(5)]
    frontier = optimize_win5(races, max_points=300)
    for s in frontier:
        prod = 1.0
        for pr in s.per_race:
            prod *= pr["cum_prob"]
        assert s.hit_prob == pytest.approx(prod)
