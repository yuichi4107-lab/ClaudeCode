"""metrics/wet.py(湿走路適性)のテスト。"""

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from autorace_evaluator.metrics import wet as wet_mod
from tests.conftest import make_entries_df, synthetic_league


def test_recovers_true_wet_ability():
    entries, truth = synthetic_league(
        seed=7, n_players=40, n_races=1500, wet_share=0.3, wet_sd=0.8)
    per_player, diag = wet_mod.compute_wet(entries)

    merged = per_player.merge(truth, on="player_no")
    valid = merged.dropna(subset=["wet_score", "true_wet"])
    assert len(valid) >= 30
    corr, _ = spearmanr(valid["wet_score"], valid["true_wet"])
    assert corr > 0.5

    # 診断: 両モデルとも学習されており、試走タイム係数の符号が同傾向(正)
    assert diag["wet"]["n_samples"] > 0
    assert diag["good"]["n_samples"] > 0
    assert diag["wet"]["betas"]["trial_time_c"] > 0
    assert diag["good"]["betas"]["trial_time_c"] > 0
    assert diag["wet"]["track_status"] == "湿走路"


def test_wet_gap_reflects_rain_specialists():
    entries, truth = synthetic_league(
        seed=8, n_players=40, n_races=1500, wet_share=0.3, wet_sd=0.8)
    per_player, _ = wet_mod.compute_wet(entries)
    merged = per_player.merge(truth, on="player_no")
    valid = merged.dropna(subset=["wet_gap"])
    # wet_gap は「雨での上振れ」= true_wet と正相関するはず
    corr, _ = spearmanr(valid["wet_gap"], valid["true_wet"])
    assert corr > 0.3


def test_min_wet_threshold_gives_nan():
    entries, _ = synthetic_league(
        seed=9, n_players=30, n_races=300, wet_share=0.1, wet_sd=0.5)
    per_player, _ = wet_mod.compute_wet(entries, min_wet=5)
    few = per_player[per_player["n_wet"].fillna(0) < 5]
    assert few["wet_score"].isna().all()


def test_no_wet_races_returns_nan_scores():
    entries, _ = synthetic_league(seed=10, n_players=20, n_races=100, wet_share=0.0)
    per_player, diag = wet_mod.compute_wet(entries)
    if not per_player.empty:
        assert per_player["wet_score"].isna().all()
    assert not diag["wet"]  # 湿走路サンプルなし → 診断は空


def test_empty_entries():
    entries = pd.DataFrame(
        columns=["race_id", "player_no", "player_name", "track_status", "status",
                 "trial_time", "handicap", "finish_pos", "car_no", "st",
                 "is_flying"])
    per_player, _diag = wet_mod.compute_wet(entries)
    assert per_player.empty


def test_mean_st_wet_column_present():
    entries, _ = synthetic_league(
        seed=11, n_players=20, n_races=400, wet_share=0.3)
    per_player, _ = wet_mod.compute_wet(entries)
    assert "mean_st_wet" in per_player.columns
    assert per_player["mean_st_wet"].notna().any()
