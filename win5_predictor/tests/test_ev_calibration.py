"""EV 最大化と β 較正のテスト。"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from popularity import Horse, Race, enumerate_ev_lines, optimize_win5_ev  # noqa: E402
from popularity.calibration import fit_beta  # noqa: E402


def _mk_race(odds_list, beta=1.0):
    return Race([Horse(umaban=i + 1, odds=o) for i, o in enumerate(odds_list)], beta=beta)


def test_market_and_corrected_probs_set():
    r = _mk_race([2.0, 4.0, 8.0], beta=1.5)
    # 市場確率と補正確率は別物（β≠1）
    assert r.horses[0].prob != pytest.approx(r.horses[0].prob_market)
    assert sum(h.prob for h in r.horses) == pytest.approx(1.0)
    assert sum(h.prob_market for h in r.horses) == pytest.approx(1.0)


def test_ev_zero_when_beta_one_all_negative():
    # β=1 では全ライン EV = -unit*takeout
    races = [_mk_race([2.0, 4.0, 8.0], beta=1.0) for _ in range(5)]
    lines = enumerate_ev_lines(races, takeout=0.30, unit_yen=100, max_per_race=3)
    for l in lines:
        assert l.ev_yen == pytest.approx(-30.0, abs=1e-6)
    # positive_only なら見送り
    plan = optimize_win5_ev(races, budget_yen=100000, takeout=0.30, positive_only=True)
    assert plan.points == 0


def test_ev_positive_lines_appear_with_beta_gt_1():
    # 本命に寄せる β>1 だと本命ラインの EV が正になりうる
    races = [_mk_race([1.5, 6.0, 12.0, 30.0], beta=2.0) for _ in range(5)]
    plan = optimize_win5_ev(races, budget_yen=100000, takeout=0.30, positive_only=True, max_per_race=4)
    assert plan.points >= 1
    assert plan.total_ev_yen > 0
    # 採用ラインは全て EV>0
    assert all(l.ev_yen > 0 for l in plan.lines)


def test_ev_budget_limits_points():
    races = [_mk_race([1.4, 5.0, 9.0], beta=2.5) for _ in range(5)]
    plan = optimize_win5_ev(races, budget_yen=300, takeout=0.30, positive_only=False, max_per_race=3)
    assert plan.cost_yen <= 300
    assert plan.points <= 3


def test_fit_beta_recovers_known_value():
    # 既知の β0 で勝ち馬を生成し、推定が β0 に近いか
    rng = np.random.default_rng(42)
    beta0 = 1.6
    races = []
    for _ in range(4000):
        n = rng.integers(6, 16)
        odds = np.round(rng.uniform(1.5, 60.0, size=n), 1)
        inv = 1.0 / odds
        q = inv / inv.sum()
        p = np.power(q, beta0)
        p = p / p.sum()
        winner = rng.choice(n, p=p)
        races.append((odds.tolist(), int(winner)))
    res = fit_beta(races)
    assert res["beta"] == pytest.approx(beta0, abs=0.15)
    # 較正した方が対数尤度は改善（nll 減少）
    assert res["nll"] <= res["baseline_nll"]


def test_fit_beta_empty_raises():
    with pytest.raises(ValueError):
        fit_beta([])
