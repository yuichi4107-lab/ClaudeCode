import numpy as np

from autorace_evaluator.metrics.attack import (
    add_front_cars, compute_attack, compute_overtakes,
)
from tests.conftest import make_entries_df


def _race(rows, race_no=1):
    return [dict(r, race_no=race_no) for r in rows]


def test_front_cars_counting():
    entries = make_entries_df([
        dict(car_no=1, player_no=1, handicap=0),
        dict(car_no=2, player_no=2, handicap=0),    # 同ハンデは「前」に含めない
        dict(car_no=3, player_no=3, handicap=10),
        dict(car_no=4, player_no=4, handicap=20),
        dict(car_no=5, player_no=5, handicap=0, status="scratched"),  # 欠車除外
    ])
    df = add_front_cars(entries).set_index("car_no")
    assert df.loc[1, "front_cars"] == 0
    assert df.loc[2, "front_cars"] == 0
    assert df.loc[3, "front_cars"] == 2
    assert df.loc[4, "front_cars"] == 3
    assert np.isnan(df.loc[5, "front_cars"])


def test_overtakes_exact_values():
    # 20mハンデの選手4: 前に3車、2着 → 先着1車 → passed = 3 - 1 = 2
    entries = make_entries_df([
        dict(car_no=1, player_no=1, handicap=0, finish_pos=1),
        dict(car_no=2, player_no=2, handicap=0, finish_pos=3),
        dict(car_no=3, player_no=3, handicap=10, finish_pos=4),
        dict(car_no=4, player_no=4, handicap=20, finish_pos=2),
    ])
    ot = compute_overtakes(entries).set_index("player_no")
    assert ot.loc[4, "passed"] == 2
    assert abs(ot.loc[4, "pass_ratio"] - 2 / 3) < 1e-9
    # 最前列(front_cars=0)の選手1・2は対象外
    assert 1 not in ot.index and 2 not in ot.index
    # 選手3: 前に2車、4着(3車に先着される) → passed = 2 - 3 = -1(差されるとマイナス)
    assert ot.loc[3, "passed"] == -1


def test_overtakes_ties_not_counted_as_ahead():
    entries = make_entries_df([
        dict(car_no=1, player_no=1, handicap=0, finish_pos=1),
        dict(car_no=2, player_no=2, handicap=10, finish_pos=1),  # 同着
        dict(car_no=3, player_no=3, handicap=10, finish_pos=3),
    ])
    ot = compute_overtakes(entries).set_index("player_no")
    # 同着は「先着された」に数えない → passed = 1 - 0 = 1
    assert ot.loc[2, "passed"] == 1


def test_unfinished_rider_excluded_from_overtakes():
    entries = make_entries_df([
        dict(car_no=1, player_no=1, handicap=0, finish_pos=1),
        dict(car_no=2, player_no=2, handicap=10, finish_pos=None,
             status="accident"),
        dict(car_no=3, player_no=3, handicap=10, finish_pos=2),
    ])
    ot = compute_overtakes(entries)
    assert 2 not in set(ot["player_no"])


def test_accident_and_violation_rates():
    entries = make_entries_df([
        dict(player_no=1, race_no=1, status="finished"),
        dict(player_no=1, race_no=2, status="accident", finish_pos=None),
        dict(player_no=1, race_no=3, status="violation", finish_pos=None),
        dict(player_no=1, race_no=4, status="scratched", finish_pos=None),
    ])
    per_player, _ = compute_attack(entries, min_races=99)
    row = per_player.set_index("player_no").loc[1]
    # 欠車は分母に入らない → 3走中1事故・1違反
    assert row["n_races"] == 3
    assert abs(row["accident_rate"] - 1 / 3) < 1e-9
    assert abs(row["violation_rate"] - 1 / 3) < 1e-9


def test_attack_recovers_true_ability(league):
    entries, truth = league
    per_player, _ = compute_attack(entries, min_races=10)
    merged = per_player.merge(truth, on="player_no")
    rho = merged[["attack_a", "true_attack"]].corr(method="spearman").iloc[0, 1]
    assert rho > 0.5, f"spearman={rho:.3f}"
    # スコアも真の能力と正の相関を持つ
    rho_score = merged[["attack_score", "true_attack"]].corr(
        method="spearman").iloc[0, 1]
    assert rho_score > 0.4, f"spearman={rho_score:.3f}"
