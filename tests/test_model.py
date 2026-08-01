"""model/(特徴量・ランキング学習・確率化・バックテスト)のテスト。"""

import numpy as np
import pandas as pd
import pytest

from autorace_evaluator.model import backtest as bt
from autorace_evaluator.model import predictor
from autorace_evaluator.model.features import (
    SnapshotStore, build_features, month_start,
)
from tests.conftest import synthetic_league


# ------------------------------------------------------------- relevance

def test_make_relevance_mapping():
    rel = predictor.make_relevance(pd.Series([1, 2, 8, 9, np.nan]))
    assert list(rel) == [7, 6, 0, 0, 0]


# ----------------------------------------------------------- probability

def test_win_probabilities_sum_to_one_per_race():
    entries, _ = synthetic_league(seed=20, n_players=24, n_races=240)
    feats = build_features(entries, store=None)
    model = predictor.train(feats)
    p = model.win_probabilities(feats)
    sums = p.groupby(feats["race_id"]).sum()
    assert np.allclose(sums.to_numpy(), 1.0, atol=1e-9)


def test_exacta_probabilities_harville():
    win = pd.DataFrame({
        "race_id": ["r1"] * 3,
        "car_no": [1, 2, 3],
        "p_win": [0.5, 0.3, 0.2],
    })
    ex = predictor.exacta_probabilities(win)
    row = ex[(ex["first"] == 1) & (ex["second"] == 2)].iloc[0]
    assert abs(row["prob"] - 0.5 * 0.3 / 0.5) < 1e-12  # p1*p2/(1-p1)
    # 全組み合わせの合計は1(Harville近似は正規化される)
    assert abs(ex["prob"].sum() - 1.0) < 1e-9
    # レース内で降順
    probs = ex["prob"].to_numpy()
    assert all(probs[i] >= probs[i + 1] for i in range(len(probs) - 1))


# --------------------------------------------------------------- features

def test_snapshot_store_uses_only_past_data():
    """スナップショットは月初より前のデータだけで計算される(未来リーク防止)。"""
    entries, _ = synthetic_league(seed=21, n_players=24, n_races=360)
    store = SnapshotStore(entries)
    cutoff = "2026-02-01"
    snap = store.get(cutoff)
    past = entries[entries["race_date"] < cutoff]
    future_only_players = (
        set(entries["player_no"]) - set(past["player_no"]))
    if not snap.empty:
        assert not (set(snap["player_no"]) & future_only_players)


def test_build_features_excludes_st_and_finish():
    entries, _ = synthetic_league(seed=22, n_players=16, n_races=60)
    feats = build_features(entries, store=None)
    from autorace_evaluator.model.features import FEATURE_COLS
    assert "st" not in FEATURE_COLS
    assert "finish_pos" not in FEATURE_COLS
    assert "race_time" not in FEATURE_COLS
    # 識別列としての finish_pos は残る(学習の教師に使う)
    assert "finish_pos" in feats.columns


def test_build_features_scratched_excluded():
    entries, _ = synthetic_league(seed=23, n_players=16, n_races=40)
    entries.loc[entries.index[:3], "status"] = "scratched"
    feats = build_features(entries, store=None)
    assert len(feats) == len(entries) - 3


def test_month_start():
    assert month_start("2026-07-15") == "2026-07-01"


# ------------------------------------------------------------ end-to-end

@pytest.mark.slow
def test_walk_forward_beats_random_baseline():
    """真の能力を埋め込んだ合成リーグで、勝率1位の的中率がランダム(1/8)を上回る。"""
    entries, _ = synthetic_league(seed=24, n_players=40, n_races=1200,
                                  attack_sd=0.8)
    months = sorted({d[:7] for d in entries["race_date"]})
    result = bt.walk_forward(entries, payouts_df=pd.DataFrame(),
                             test_months=months[-2:], min_train_races=100)
    summary = result["summary"]
    assert not summary.empty
    overall = summary[summary["block"] == "ALL"].iloc[0]
    assert overall["races"] > 50
    assert overall["win_hit@1"] > 1 / 8 + 0.05  # ランダムより明確に良い
