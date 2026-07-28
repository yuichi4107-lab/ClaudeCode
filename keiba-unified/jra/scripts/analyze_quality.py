#!/usr/bin/env python3
"""レース品質スコアの分布を分析し、閾値を決定する"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from predictor import score_all_horses, evaluate_race_quality, get_conn

conn = get_conn()
c = conn.cursor()

# 2025年の全レース
c.execute("""SELECT race_id FROM races
             WHERE date BETWEEN '2025-01-01' AND '2025-12-31'
               AND surface IN ('芝', 'ダート')
             ORDER BY race_id""")
race_ids = [row[0] for row in c.fetchall()]
print(f"2025年 総レース数: {len(race_ids)}")
print(f"目標ベット数 (1/3): {len(race_ids) // 3}")

# v2モデル読み込み
try:
    from model_v2 import load_model, build_features_for_date, FEATURE_COLS
    v2_model, _ = load_model()
    print("v2モデル読み込み済み")
except Exception as e:
    print(f"v2モデル読み込み失敗: {e}")
    v2_model = None

# 日付ごとに処理
c.execute("""SELECT DISTINCT date FROM races
             WHERE date BETWEEN '2025-01-01' AND '2025-12-31'
               AND surface IN ('芝', 'ダート')
             ORDER BY date""")
dates = [row[0] for row in c.fetchall()]

all_scores = []
for i, date in enumerate(dates):
    c.execute("""SELECT race_id FROM races
                 WHERE date = ? AND surface IN ('芝', 'ダート')""", (date,))
    day_race_ids = [row[0] for row in c.fetchall()]

    # v2予測を日単位で一括取得
    v2_predictions = {}
    if v2_model:
        try:
            import pandas as pd, numpy as np
            df = build_features_for_date(conn, date)
            if not df.empty:
                for rid in day_race_ids:
                    df_race = df[df["race_id"] == rid]
                    if df_race.empty:
                        continue
                    X = df_race[FEATURE_COLS].values
                    probs = v2_model.predict(X)
                    v2_predictions[rid] = dict(
                        zip(df_race["horse_number"].astype(int), probs)
                    )
        except Exception:
            pass

    for rid in day_race_ids:
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
                    h["total_score"] = 0.7 * v2_norm + 0.3 * h["total_score"]
                    h["v2_prob"] = v2_probs[hn]
            scored.sort(key=lambda x: x["total_score"], reverse=True)

        quality = evaluate_race_quality(conn, rid, scored)
        all_scores.append(quality["quality_score"])

    if (i + 1) % 20 == 0:
        print(f"  {i+1}/{len(dates)} 日処理完了...")

print(f"\n品質スコア統計:")
import numpy as np
scores = np.array(all_scores)
print(f"  総レース数: {len(scores)}")
print(f"  平均: {scores.mean():.3f}")
print(f"  標準偏差: {scores.std():.3f}")
print(f"  最小: {scores.min():.3f}")
print(f"  最大: {scores.max():.3f}")

# パーセンタイル
for p in [25, 33, 40, 50, 60, 67, 75, 80, 90]:
    val = np.percentile(scores, p)
    count_above = (scores >= val).sum()
    print(f"  {p}%ile: {val:.3f} (これ以上: {count_above}レース = {count_above/len(scores)*100:.1f}%)")

# 閾値候補ごとのレース数
print(f"\n閾値候補:")
for threshold in [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]:
    count = (scores >= threshold).sum()
    print(f"  >= {threshold:.2f}: {count}レース ({count/len(scores)*100:.1f}%)")

conn.close()
