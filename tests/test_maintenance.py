import numpy as np

from autorace_evaluator.metrics.maintenance import (
    build_daily_trials, build_pairs, compute_maintenance,
)
from tests.conftest import make_entries_df

MEETING = {"meeting_id": "kawaguchi_2026-01-01"}


def test_pair_diff_sign_and_value():
    # 2日目に -0.05秒(速化)を仕込む → diff = +0.05 で「上がった」
    entries = make_entries_df([
        dict(MEETING, race_date="2026-01-01", player_no=1, trial_time=3.40),
        dict(MEETING, race_date="2026-01-02", player_no=1, trial_time=3.35),
        dict(MEETING, race_date="2026-01-03", player_no=1, trial_time=3.37),
    ])
    per_player, pairs, overall = compute_maintenance(entries, min_pairs=1)
    assert len(pairs) == 2
    d1 = pairs[pairs["date_cur"] == "2026-01-02"]["diff"].iloc[0]
    d2 = pairs[pairs["date_cur"] == "2026-01-03"]["diff"].iloc[0]
    assert d1 == 0.05      # 前日3.40 → 当日3.35
    assert d2 == -0.02     # 前日3.35 → 当日3.37
    row = per_player.iloc[0]
    assert row["n_pairs"] == 2
    assert row["improved_rate"] == 0.5
    assert row["worsened_rate"] == 0.5
    assert abs(row["mean_diff"] - 0.015) < 1e-9
    assert overall["improved_rate"] == 0.5


def test_wet_track_days_excluded():
    entries = make_entries_df([
        dict(MEETING, race_date="2026-01-01", player_no=1, trial_time=3.40),
        dict(MEETING, race_date="2026-01-02", player_no=1, trial_time=3.20,
             track_status="湿走路"),
        dict(MEETING, race_date="2026-01-03", player_no=1, trial_time=3.35),
    ])
    # 1/2 が湿走路 → (1/1,1/2) も (1/2,1/3) も不成立。(1/1,1/3) は連続日でないので不成立
    _, pairs, _ = compute_maintenance(entries, min_pairs=1)
    assert len(pairs) == 0


def test_meeting_boundary_prevents_pairing():
    # 連続暦日でも節が違えばペアにしない
    entries = make_entries_df([
        dict(race_date="2026-01-01", player_no=1, trial_time=3.40,
             meeting_id="kawaguchi_2025-12-29"),
        dict(race_date="2026-01-02", player_no=1, trial_time=3.35,
             meeting_id="kawaguchi_2026-01-02"),
    ])
    _, pairs, _ = compute_maintenance(entries, min_pairs=1)
    assert len(pairs) == 0


def test_missing_trial_and_scratched_excluded():
    entries = make_entries_df([
        dict(MEETING, race_date="2026-01-01", player_no=1, trial_time=None),
        dict(MEETING, race_date="2026-01-02", player_no=1, trial_time=3.35),
        dict(MEETING, race_date="2026-01-02", player_no=2, trial_time=3.30,
             car_no=2),
        dict(MEETING, race_date="2026-01-03", player_no=2, trial_time=3.28,
             car_no=2, status="scratched"),
    ])
    _, pairs, _ = compute_maintenance(entries, min_pairs=1)
    assert len(pairs) == 0


def test_retrial_day_excluded_by_default():
    entries = make_entries_df([
        dict(MEETING, race_date="2026-01-01", player_no=1, trial_time=3.40),
        dict(MEETING, race_date="2026-01-02", player_no=1, trial_time=3.35,
             is_retrial=1),
    ])
    _, pairs_default, _ = compute_maintenance(entries, min_pairs=1)
    assert len(pairs_default) == 0
    _, pairs_incl, _ = compute_maintenance(entries, include_retrial=True,
                                           min_pairs=1)
    assert len(pairs_incl) == 1


def test_first_race_of_day_used_for_double_start():
    entries = make_entries_df([
        dict(MEETING, race_date="2026-01-01", player_no=1, trial_time=3.40),
        # 同日2走目(通常は無いが防御): レース番号の小さい方を採用
        dict(MEETING, race_date="2026-01-02", race_no=2, player_no=1,
             trial_time=3.30),
        dict(MEETING, race_date="2026-01-02", race_no=8, player_no=1,
             trial_time=3.99),
    ])
    daily = build_daily_trials(entries)
    day2 = daily[daily["race_date"] == "2026-01-02"]
    assert day2["trial_time"].iloc[0] == 3.30
    pairs = build_pairs(daily)
    assert pairs["diff"].iloc[0] == 0.10


def test_min_pairs_gates_score():
    rows = []
    # 選手1: 6日連続(5ペア) → スコアあり / 選手2: 2日(1ペア) → スコアNaN
    for i, d in enumerate(["2026-01-01", "2026-01-02", "2026-01-03",
                           "2026-01-04", "2026-01-05", "2026-01-06"]):
        rows.append(dict(MEETING, race_date=d, player_no=1,
                         trial_time=3.40 - 0.01 * i))
    rows.append(dict(MEETING, race_date="2026-01-01", player_no=2,
                     trial_time=3.30, car_no=2))
    rows.append(dict(MEETING, race_date="2026-01-02", player_no=2,
                     trial_time=3.31, car_no=2))
    per_player, _, _ = compute_maintenance(make_entries_df(rows), min_pairs=5)
    p1 = per_player[per_player["player_no"] == 1].iloc[0]
    p2 = per_player[per_player["player_no"] == 2].iloc[0]
    assert p1["n_pairs"] == 5
    assert p1["improved_rate"] == 1.0
    assert np.isnan(p2["maintenance_score"])
