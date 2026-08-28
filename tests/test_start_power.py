import numpy as np
import pandas as pd

from autorace_evaluator.metrics.start_power import (
    compute_st_stats, compute_start_power, expected_corner_order, fit_dash_model,
)
from tests.conftest import make_entries_df


def test_st_stats_basic():
    entries = make_entries_df([
        dict(player_no=1, st=0.10),
        dict(player_no=1, st=0.20, race_no=2),
        dict(player_no=1, st=None, is_flying=1, race_no=3),
        dict(player_no=2, st=0.05, car_no=2),
        dict(player_no=2, st=0.07, car_no=2, race_no=2, status="scratched"),
    ])
    stats = compute_st_stats(entries).set_index("player_no")
    assert stats.loc[1, "n_st"] == 2
    assert abs(stats.loc[1, "mean_st"] - 0.15) < 1e-9
    assert abs(stats.loc[1, "flying_rate"] - 1 / 3) < 1e-9
    # 欠車はST統計に入らない
    assert stats.loc[2, "n_st"] == 1


def test_expected_corner_order():
    race = make_entries_df([
        dict(car_no=1, handicap=0, st=0.10, trial_time=3.40),
        dict(car_no=2, handicap=0, st=0.05, trial_time=3.40),   # 同ライン最速ST
        dict(car_no=3, handicap=10, st=0.01, trial_time=3.30),  # 後ろのライン
        dict(car_no=4, handicap=0, st=0.10, trial_time=3.35),   # 同ST・試走で前
    ])
    order = expected_corner_order(race)
    assert list(order) == [3, 1, 4, 2]


def test_dash_model_recovers_true_ability(league):
    entries, truth = league
    per_player, diagnostics = compute_start_power(entries, min_races=10)
    merged = per_player.merge(truth, on="player_no")
    rho = merged[["dash", "true_dash"]].corr(method="spearman").iloc[0, 1]
    assert rho > 0.7, f"spearman={rho:.3f}"
    # ST係数は正(ST遅れ→序盤ロス増)であるべき
    assert diagnostics["beta_st_positive"]


def test_shrinkage_pulls_small_samples_toward_zero():
    entries, _ = __import__("tests.conftest", fromlist=["synthetic_league"]) \
        .synthetic_league(seed=1, n_players=30, n_races=200)
    sample, _ = fit_dash_model(entries)
    grouped = sample.groupby("player_no")["dash_residual"]
    raw = -grouped.mean()
    from autorace_evaluator.metrics.common import shrink
    shrunk = shrink(raw, grouped.size(), k=10)
    # 縮約後は絶対値が縮む(rawが0でない全選手で)
    nonzero = raw[raw.abs() > 1e-12]
    assert (shrunk[nonzero.index].abs() <= nonzero.abs() + 1e-12).all()


def test_dash_model_skips_thin_races():
    # 有効車数2のレースはサンプルから除外される
    entries = make_entries_df([
        dict(player_no=1, race_time=3.70, last_lap_time=3.35),
        dict(player_no=2, car_no=2, race_time=3.72, last_lap_time=3.36),
    ])
    sample, diagnostics = fit_dash_model(entries)
    assert sample.empty


def test_start_score_requires_min_races():
    entries = make_entries_df([
        dict(player_no=1, st=0.10, race_time=3.70, last_lap_time=3.35),
        dict(player_no=2, car_no=2, st=0.12, race_time=3.72, last_lap_time=3.36),
        dict(player_no=3, car_no=3, st=0.08, race_time=3.69, last_lap_time=3.34),
    ])
    per_player, _ = compute_start_power(entries, min_races=10)
    assert per_player["start_score"].isna().all()
