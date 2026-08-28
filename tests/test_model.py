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


# --------------------------------------------------------- EVバックテスト

def _ev_block_fixture():
    """1レース(3車)の合成予測。Harville 確率は手計算できる値にする。

    p_win = 1:0.5, 2:0.3, 3:0.2 → 2連単確率
      1-2=0.30  1-3=0.20  2-1=0.30*0.5/0.7  2-3=0.30*0.2/0.7
      3-1=0.125 3-2=0.075
    着順は 2着車が1着・1着車が2着(= 実際の組み合わせは "2-1")。
    """
    pred = pd.DataFrame({
        "race_id": ["r1"] * 3,
        "car_no": [1, 2, 3],
        "p_win": [0.5, 0.3, 0.2],
        "finish_pos": [2, 1, 3],
        "trial_time": [3.35, 3.36, 3.40],
    })
    # EV = prob × odds。閾値1.2以上は 1-2(1.50)・2-1(1.286)・2-3(1.714)の3点
    odds_map = {"r1": {
        (1, 2): 5.0, (1, 3): 4.0,
        (2, 1): 6.0, (2, 3): 20.0,
        (3, 1): 8.0, (3, 2): 10.0,
    }}
    payout_map = {"r1": {"2-1": 600.0}}
    return pred, odds_map, payout_map


def test_ev_backtest_matches_hand_calculation():
    pred, odds_map, payout_map = _ev_block_fixture()
    row = bt._evaluate_block("T", pred, payout_map, odds_map, ev_threshold=1.2)
    assert row["ev_bets"] == 3            # 1-2, 2-1, 2-3
    assert row["ev_hit_rate"] == 1 / 3    # 的中は 2-1 のみ
    assert row["ev_roi"] == 600.0 / 300   # 払戻600円 ÷ 購入300円


def test_ev_backtest_threshold_filters_bets():
    pred, odds_map, payout_map = _ev_block_fixture()
    # 閾値を上げると 2-3(EV 1.714)のみ購入 → 的中0・回収0
    row = bt._evaluate_block("T", pred, payout_map, odds_map, ev_threshold=1.7)
    assert row["ev_bets"] == 1
    assert row["ev_hit_rate"] == 0.0
    assert row["ev_roi"] == 0.0
    # 到達不能な閾値なら購入0点で NaN
    row = bt._evaluate_block("T", pred, payout_map, odds_map, ev_threshold=99)
    assert row["ev_bets"] == 0
    assert np.isnan(row["ev_hit_rate"])
    assert np.isnan(row["ev_roi"])


def test_ev_columns_absent_without_odds():
    """オッズを渡さない従来の呼び出しでは EV 列を追加しない。"""
    pred, _, payout_map = _ev_block_fixture()
    row = bt._evaluate_block("T", pred, payout_map)
    assert "ev_bets" not in row
    assert "ev_roi" not in row


def test_exacta_odds_map_drops_invalid_odds():
    df = pd.DataFrame({
        "race_id": ["r1", "r1", "r1"],
        "first": [1, 1, 2],
        "second": [2, 3, 1],
        "odds": [5.0, 0.0, None],
    })
    assert bt._exacta_odds_map(df) == {"r1": {(1, 2): 5.0}}
    assert bt._exacta_odds_map(None) is None
    assert bt._exacta_odds_map(pd.DataFrame()) == {}


def test_walk_forward_includes_ev_columns():
    """walk_forward に exacta_odds_df を渡すと summary に EV 指標が入る。"""
    entries, _ = synthetic_league(seed=25, n_players=24, n_races=600)
    months = sorted({d[:7] for d in entries["race_date"]})
    # 全レースの全2連単を一律オッズ10倍とし、払戻も同額(=1000円)にする
    winners = entries[entries["finish_pos"] == 1][["race_id", "car_no"]]
    seconds = entries[entries["finish_pos"] == 2][["race_id", "car_no"]]
    combos = winners.merge(seconds, on="race_id", suffixes=("_1", "_2"))
    payouts = pd.DataFrame({
        "race_id": combos["race_id"],
        "bet_type": "2連単",
        "combination": combos["car_no_1"].astype(str) + "-" + combos["car_no_2"].astype(str),
        "payout": 1000.0,
    })
    odds_rows = []
    for race_id, g in entries.groupby("race_id"):
        cars = list(g["car_no"])
        for i in cars:
            for j in cars:
                if i != j:
                    odds_rows.append({"race_id": race_id, "first": i,
                                      "second": j, "odds": 10.0})
    odds_df = pd.DataFrame(odds_rows)

    result = bt.walk_forward(entries, payouts, test_months=months[-1:],
                             min_train_races=50, exacta_odds_df=odds_df,
                             ev_threshold=1.2)
    summary = result["summary"]
    assert not summary.empty
    overall = summary[summary["block"] == "ALL"].iloc[0]
    assert overall["ev_bets"] > 0
    # 一律10倍・払戻1000円なので ROI = 的中率 × 10
    assert abs(overall["ev_roi"] - overall["ev_hit_rate"] * 10) < 1e-9


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
