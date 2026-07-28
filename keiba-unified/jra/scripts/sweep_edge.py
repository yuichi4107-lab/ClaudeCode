#!/usr/bin/env python3
"""エッジ基準でのレース選定を検証"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import predictor
from backtest import run_single_day, get_conn

conn = get_conn()
c = conn.cursor()

# v2モデル読み込み
from model_v2 import load_model, build_features_for_date, FEATURE_COLS
v2_model, _ = load_model()

c.execute("""SELECT DISTINCT date FROM races
             WHERE date BETWEEN '2025-01-01' AND '2025-12-31'
               AND surface IN ('芝', 'ダート') ORDER BY date""")
dates = [row[0] for row in c.fetchall()]

# 各レースを「エッジ度」で分類
from predictor import score_all_horses, evaluate_race_quality, generate_bets, V2_BLEND_WEIGHT, allocate_budget
from backtest import check_hit
import numpy as np
import pandas as pd

# エッジ条件別に集計
conditions = {
    "top1_pop>=3": {"bet": 0, "payout": 0, "races": 0, "hits": 0},  # 1位馬が3番人気以下
    "top1_pop>=4": {"bet": 0, "payout": 0, "races": 0, "hits": 0},  # 1位馬が4番人気以下
    "top2_any_pop>=4": {"bet": 0, "payout": 0, "races": 0, "hits": 0},  # 上位2頭のいずれかが4番人気以下
    "value_gap>=3": {"bet": 0, "payout": 0, "races": 0, "hits": 0},  # いずれかの馬で乖離3以上
    "mid_odds_in_top3": {"bet": 0, "payout": 0, "races": 0, "hits": 0},  # 上位3頭にオッズ10-30倍
    "all_races": {"bet": 0, "payout": 0, "races": 0, "hits": 0},
}

for i, date in enumerate(dates):
    c.execute("SELECT race_id FROM races WHERE date = ? AND surface IN ('芝', 'ダート')", (date,))
    rids = [row[0] for row in c.fetchall()]

    v2p = {}
    df = build_features_for_date(conn, date)
    if not df.empty:
        for rid in rids:
            dfr = df[df["race_id"] == rid]
            if dfr.empty: continue
            probs = v2_model.predict(dfr[FEATURE_COLS].values)
            v2p[rid] = dict(zip(dfr["horse_number"].astype(int), probs))

    for rid in rids:
        scored = score_all_horses(conn, rid)
        if not scored or len(scored) < 5:
            continue

        if rid in v2p:
            vp = v2p[rid]; mp = max(vp.values()) if vp else 1.0
            for h in scored:
                hn = h["horse_number"]
                if hn in vp:
                    h["total_score"] = 0.7 * (vp[hn]/mp if mp>0 else 0.5) + 0.3*h["total_score"]
                    h["v2_prob"] = vp[hn]
            scored.sort(key=lambda x: x["total_score"], reverse=True)

        bets = generate_bets(scored, {}, 2000)
        if not bets["bets"]:
            continue
        hit = check_hit(conn, rid, bets["bet_type"], bets["bets"])
        bt = sum(b["amount"] for b in bets["bets"])

        # 各条件をチェック
        top1_pop = scored[0].get("popularity", 0) or 0
        top2_pop = scored[1].get("popularity", 0) or 0

        def update(key):
            conditions[key]["bet"] += bt
            conditions[key]["payout"] += hit["total_payout"]
            conditions[key]["races"] += 1
            if hit["hit"]: conditions[key]["hits"] += 1

        update("all_races")

        if top1_pop >= 3:
            update("top1_pop>=3")
        if top1_pop >= 4:
            update("top1_pop>=4")
        if top1_pop >= 4 or top2_pop >= 4:
            update("top2_any_pop>=4")

        max_gap = max((scored[j].get("popularity", 0) or 0) - (j+1) for j in range(min(5, len(scored))))
        if max_gap >= 3:
            update("value_gap>=3")

        has_mid = any(10 <= (scored[j].get("odds_win", 0) or 0) <= 30 for j in range(3))
        if has_mid:
            update("mid_odds_in_top3")

    if (i+1) % 20 == 0:
        print(f"  {i+1}/{len(dates)}...")

print(f"\n{'条件':>20s} {'レース':>6s} {'的中率':>6s} {'投資':>10s} {'回収':>10s} {'ROI':>6s} {'対全体%':>7s}")
print("-" * 75)
total_races = conditions["all_races"]["races"]
for key, v in conditions.items():
    roi = v["payout"] / v["bet"] * 100 if v["bet"] > 0 else 0
    hr = v["hits"] / v["races"] * 100 if v["races"] > 0 else 0
    pct = v["races"] / total_races * 100 if total_races > 0 else 0
    print(f"{key:>20s} {v['races']:>6d} {hr:>5.1f}% {v['bet']:>9,}円 {v['payout']:>9,}円 {roi:>5.1f}% {pct:>6.1f}%")

conn.close()
