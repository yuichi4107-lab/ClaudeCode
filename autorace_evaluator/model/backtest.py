"""ウォークフォワードバックテスト。

月単位で「その月より前の全データで学習 → その月を予測」を繰り返す。
特徴量の能力指標は features.SnapshotStore(月初時点・過去365日)なので、
学習・予測とも未来リークはない。

評価:
- win_hit@1: 勝率1位の車が実際に1着になった率(ベースラインは
  試走タイム最速車の1着率を併記)
- exacta_hit@N: 2連単確率上位N点のフラット買い(各100円)の的中率
- exacta_roi@N: 同・回収率(payouts テーブルの2連単払戻で精算)
- ev_bets / ev_hit_rate / ev_roi: exacta_odds(最終オッズ)が与えられたとき、
  「model_prob × odds ≥ ev_threshold の組み合わせを全て100円ずつ買う」戦略の
  総購入点数・購入点数あたり的中率・回収率
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from autorace_evaluator.model import predictor
from autorace_evaluator.model.features import SnapshotStore, build_features

logger = logging.getLogger(__name__)

BET_UNITS = (1, 2, 3)  # 2連単の買い目点数


def _exacta_payout_map(payouts_df: pd.DataFrame) -> dict:
    """{race_id: {"i-j": 払戻(100円あたり)}} を作る。"""
    out: dict[str, dict] = {}
    if payouts_df is None or payouts_df.empty:
        return out
    ex = payouts_df[payouts_df["bet_type"] == "2連単"]
    for r in ex.itertuples(index=False):
        out.setdefault(r.race_id, {})[r.combination] = float(r.payout)
    return out


def _exacta_odds_map(exacta_odds_df: pd.DataFrame | None) -> dict | None:
    """{race_id: {(first, second): 最終オッズ}} を作る。None 入力は None を返す。"""
    if exacta_odds_df is None:
        return None
    out: dict[str, dict] = {}
    if exacta_odds_df.empty:
        return out
    for r in exacta_odds_df.itertuples(index=False):
        odds = float(r.odds) if r.odds is not None and not pd.isna(r.odds) else None
        if odds is None or odds <= 0:
            continue
        out.setdefault(r.race_id, {})[(int(r.first), int(r.second))] = odds
    return out


def walk_forward(entries_df: pd.DataFrame,
                 payouts_df: pd.DataFrame,
                 test_months: list[str],
                 min_train_races: int = 500,
                 exacta_odds_df: pd.DataFrame | None = None,
                 ev_threshold: float = 1.2) -> dict:
    """test_months(['2026-02', ...])を月次ウォークフォワードで評価する。

    exacta_odds_df(列 race_id/first/second/odds)を渡すと、期待値ベット戦略
    (model_prob × odds ≥ ev_threshold の組み合わせを全て100円ずつ購入)の
    ev_bets / ev_hit_rate / ev_roi を summary に追加する。

    返り値: {"summary": DataFrame(月別+全体), "predictions": DataFrame}
    """
    store = SnapshotStore(entries_df)
    feats = build_features(entries_df, store=store)
    payout_map = _exacta_payout_map(payouts_df)
    odds_map = _exacta_odds_map(exacta_odds_df)

    month = feats["race_date"].str[:7]
    all_rows = []
    monthly = []

    for m in test_months:
        train_df = feats[month < m]
        test_df = feats[month == m]
        if test_df.empty or train_df["race_id"].nunique() < min_train_races:
            logger.warning("skip month %s (train races=%d, test rows=%d)",
                           m, train_df["race_id"].nunique(), len(test_df))
            continue

        model = predictor.train(train_df)
        test_df = test_df.copy()
        test_df["p_win"] = model.win_probabilities(test_df)
        all_rows.append(test_df)
        monthly.append((m, test_df))
        logger.info("month %s: trained on %d races, predicted %d races",
                    m, train_df["race_id"].nunique(), test_df["race_id"].nunique())

    if not all_rows:
        return {"summary": pd.DataFrame(), "predictions": pd.DataFrame()}

    summary_rows = [
        _evaluate_block(m, df, payout_map, odds_map, ev_threshold)
        for m, df in monthly
    ]
    all_df = pd.concat(all_rows, ignore_index=True)
    summary_rows.append(
        _evaluate_block("ALL", all_df, payout_map, odds_map, ev_threshold))

    return {
        "summary": pd.DataFrame(summary_rows),
        "predictions": all_df,
    }


def _evaluate_block(label: str, pred_df: pd.DataFrame, payout_map: dict,
                    odds_map: dict | None = None,
                    ev_threshold: float = 1.2) -> dict:
    """1ブロック(月 or 全体)の的中率・ROIを計算する。

    odds_map が None でなければ期待値ベット戦略の指標も併せて計算する。
    """
    races = 0
    win_hits = 0
    trial_baseline_hits = 0
    exacta_hits = {n: 0 for n in BET_UNITS}
    exacta_return = {n: 0.0 for n in BET_UNITS}
    races_with_payout = 0
    ev_bets = 0
    ev_hits = 0
    ev_return = 0.0

    exacta = predictor.exacta_probabilities(
        pred_df[["race_id", "car_no", "p_win"]])
    exacta_by_race = dict(tuple(exacta.groupby("race_id"))) if not exacta.empty else {}

    for race_id, g in pred_df.groupby("race_id"):
        winner = g.loc[pd.to_numeric(g["finish_pos"], errors="coerce") == 1, "car_no"]
        if winner.empty:
            continue
        races += 1
        winner = int(winner.iloc[0])

        if int(g.loc[g["p_win"].idxmax(), "car_no"]) == winner:
            win_hits += 1
        # ベースライン: 試走タイム最速(欠測は除外)
        gt = g.dropna(subset=["trial_time"])
        if not gt.empty and int(gt.loc[gt["trial_time"].idxmin(), "car_no"]) == winner:
            trial_baseline_hits += 1

        second = g.loc[pd.to_numeric(g["finish_pos"], errors="coerce") == 2, "car_no"]
        actual_combo = f"{winner}-{int(second.iloc[0])}" if not second.empty else None

        ex = exacta_by_race.get(race_id)
        pay = payout_map.get(race_id, {})
        if ex is not None and actual_combo is not None and pay:
            races_with_payout += 1
            for n in BET_UNITS:
                top = ex.head(n)
                combos = [f"{r.first}-{r.second}" for r in top.itertuples(index=False)]
                if actual_combo in combos:
                    exacta_hits[n] += 1
                    exacta_return[n] += pay.get(actual_combo, 0.0)

            if odds_map is not None:
                race_odds = odds_map.get(race_id, {})
                for r in ex.itertuples(index=False):
                    odds = race_odds.get((int(r.first), int(r.second)))
                    if odds is None or r.prob * odds < ev_threshold:
                        continue
                    ev_bets += 1
                    if f"{int(r.first)}-{int(r.second)}" == actual_combo:
                        ev_hits += 1
                        ev_return += pay.get(actual_combo, 0.0)

    row = {
        "block": label,
        "races": races,
        "win_hit@1": win_hits / races if races else np.nan,
        "trial_baseline@1": trial_baseline_hits / races if races else np.nan,
        "races_with_payout": races_with_payout,
    }
    for n in BET_UNITS:
        cost = races_with_payout * n * 100
        row[f"exacta_hit@{n}"] = (
            exacta_hits[n] / races_with_payout if races_with_payout else np.nan)
        row[f"exacta_roi@{n}"] = (
            exacta_return[n] / cost if cost else np.nan)

    if odds_map is not None:
        row["ev_bets"] = ev_bets
        row["ev_hit_rate"] = ev_hits / ev_bets if ev_bets else np.nan
        row["ev_roi"] = ev_return / (ev_bets * 100) if ev_bets else np.nan
    return row
