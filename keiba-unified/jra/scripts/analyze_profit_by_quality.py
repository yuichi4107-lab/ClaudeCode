#!/usr/bin/env python3
"""品質スコア帯ごとの回収率を分析 → 真に利益が出るスコア帯を特定"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from predictor import score_all_horses, evaluate_race_quality, generate_bets, get_conn, V2_BLEND_WEIGHT
from backtest import check_hit

conn = get_conn()
c = conn.cursor()

# v2モデル読み込み
from model_v2 import load_model, build_features_for_date, FEATURE_COLS
v2_model, _ = load_model()

c.execute("""SELECT DISTINCT date FROM races
             WHERE date BETWEEN '2025-01-01' AND '2025-12-31'
               AND surface IN ('芝', 'ダート')
             ORDER BY date""")
dates = [row[0] for row in c.fetchall()]

# スコア帯ごとの集計
bins = {}  # {bin_label: {bet: int, payout: int, count: int, hits: int}}

for i, date in enumerate(dates):
    c.execute("""SELECT race_id FROM races WHERE date = ? AND surface IN ('芝', 'ダート')""", (date,))
    race_ids = [row[0] for row in c.fetchall()]

    # v2予測一括取得
    import pandas as pd, numpy as np
    v2_predictions = {}
    df = build_features_for_date(conn, date)
    if not df.empty:
        for rid in race_ids:
            df_race = df[df["race_id"] == rid]
            if df_race.empty:
                continue
            X = df_race[FEATURE_COLS].values
            probs = v2_model.predict(X)
            v2_predictions[rid] = dict(zip(df_race["horse_number"].astype(int), probs))

    for rid in race_ids:
        scored = score_all_horses(conn, rid)
        if not scored:
            continue

        # v2ブレンド
        if rid in v2_predictions:
            v2_probs = v2_predictions[rid]
            max_prob = max(v2_probs.values()) if v2_probs else 1.0
            for h in scored:
                hn = h["horse_number"]
                if hn in v2_probs:
                    v2_norm = v2_probs[hn] / max_prob if max_prob > 0 else 0.5
                    h["total_score"] = V2_BLEND_WEIGHT * v2_norm + (1 - V2_BLEND_WEIGHT) * h["total_score"]
                    h["v2_prob"] = v2_probs[hn]
            scored.sort(key=lambda x: x["total_score"], reverse=True)

        quality = evaluate_race_quality(conn, rid, scored)
        qs = quality["quality_score"]

        # 買い目を生成して的中チェック
        bets = generate_bets(scored, {}, 2000)
        if not bets["bets"]:
            continue

        hit_result = check_hit(conn, rid, bets["bet_type"], bets["bets"])
        bet_total = sum(b["amount"] for b in bets["bets"])

        # 品質スコアの詳細も記録
        details = quality.get("details", {})

        # スコア帯に分類（0.05刻み）
        bin_val = round(qs * 20) / 20  # 0.05刻み
        bin_label = f"{bin_val:.2f}"
        if bin_label not in bins:
            bins[bin_label] = {"bet": 0, "payout": 0, "count": 0, "hits": 0,
                               "confidence": [], "mid_upset": [], "odds_distortion": []}

        bins[bin_label]["bet"] += bet_total
        bins[bin_label]["payout"] += hit_result["total_payout"]
        bins[bin_label]["count"] += 1
        if hit_result["hit"]:
            bins[bin_label]["hits"] += 1
        bins[bin_label]["confidence"].append(details.get("confidence", 0))
        bins[bin_label]["mid_upset"].append(details.get("mid_upset", 0))
        bins[bin_label]["odds_distortion"].append(details.get("odds_distortion", 0))

    if (i + 1) % 20 == 0:
        print(f"  {i+1}/{len(dates)} 日完了...")

print(f"\n{'スコア帯':>8s} {'レース数':>7s} {'的中率':>6s} {'投資':>10s} {'回収':>10s} {'ROI':>6s} {'信頼度':>6s} {'中穴':>6s} {'歪み':>6s}")
print("-" * 80)

cumulative_bet = 0
cumulative_payout = 0
for label in sorted(bins.keys(), reverse=True):
    b = bins[label]
    roi = b["payout"] / b["bet"] * 100 if b["bet"] > 0 else 0
    hit_rate = b["hits"] / b["count"] * 100 if b["count"] > 0 else 0
    avg_conf = np.mean(b["confidence"]) if b["confidence"] else 0
    avg_upset = np.mean(b["mid_upset"]) if b["mid_upset"] else 0
    avg_dist = np.mean(b["odds_distortion"]) if b["odds_distortion"] else 0

    cumulative_bet += b["bet"]
    cumulative_payout += b["payout"]
    cum_roi = cumulative_payout / cumulative_bet * 100 if cumulative_bet > 0 else 0

    print(f"{label:>8s} {b['count']:>7d} {hit_rate:>5.1f}% {b['bet']:>9,}円 {b['payout']:>9,}円 "
          f"{roi:>5.1f}% {avg_conf:>5.2f} {avg_upset:>5.2f} {avg_dist:>5.2f}  (累計ROI:{cum_roi:.1f}%)")

conn.close()
