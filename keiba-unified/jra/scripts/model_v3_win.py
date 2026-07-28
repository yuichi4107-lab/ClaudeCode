#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
競馬予想 v3 純粋実力モデル（勝率予測）
オッズ・人気を除外した特徴量で1着確率を予測
"""

import os
import sys
import pickle
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.model_selection import GroupKFold
from sklearn.metrics import log_loss

import sqlite3

sys.path.insert(0, os.path.dirname(__file__))
from model_v2 import (
    build_features_for_date, build_training_data,
    FEATURE_COLS_NO_ODDS,
)

# model_v2.py は keiba.db を参照するが実データは keiba_live.db に格納されているため上書き
# 環境変数 KEIBA_DB_PATH で上書き可能（学習時はローカル優先、Google Drive I/Oエラー回避）
DB_PATH = os.environ.get(
    "KEIBA_DB_PATH",
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data", "keiba_live.db"
    )
)


def get_conn():
    return sqlite3.connect(DB_PATH)

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    "data", "models", "model_v3_win.pkl"
)

FEATURE_COLS = FEATURE_COLS_NO_ODDS


def train_model(conn, train_start="2022-01-01", train_end="2024-12-31"):
    """LightGBMで勝率（1着確率）を予測するモデル学習"""
    print("=" * 60)
    print("v3 純粋実力モデル（勝率予測）学習")
    print("=" * 60)

    # 1. 学習データ構築（model_v2のbuild_training_dataを再利用）
    df = build_training_data(conn, train_start, train_end)
    if df.empty:
        print("学習データがありません")
        return None

    # 2. ラベルを1着=1に変換（build_training_dataは3着内ラベル）
    df["label"] = (df["finish_position"] == 1).astype(int)

    # 3. 学習データ準備
    X = df[FEATURE_COLS].values
    y = df["label"].values
    groups = df["race_id"].values

    pos_rate = y.mean()
    print(f"\n学習データ: {len(X)}行, 正例率（勝率）: {pos_rate:.3f}")

    # 4. クラス不均衡補正（動的算出: neg/pos）
    scale_pos_weight = (1 - pos_rate) / pos_rate
    print(f"scale_pos_weight: {scale_pos_weight:.2f}")

    # 5. LightGBMパラメータ
    params = {
        "objective": "binary",
        "metric": "binary_logloss",
        "boosting_type": "gbdt",
        "num_leaves": 63,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "min_child_samples": 50,
        "lambda_l1": 0.1,
        "lambda_l2": 1.0,
        "scale_pos_weight": scale_pos_weight,
        "verbose": -1,
        "n_jobs": -1,
    }

    # 6. GroupKFoldでCV（race_idで分割）
    unique_races = np.unique(groups)
    race_to_group = {r: i for i, r in enumerate(unique_races)}
    group_ids = np.array([race_to_group[r] for r in groups])

    gkf = GroupKFold(n_splits=5)
    cv_scores = []
    best_iterations = []

    print("\n【GroupKFold CV (5分割)】")
    for fold, (train_idx, val_idx) in enumerate(gkf.split(X, y, group_ids)):
        train_data = lgb.Dataset(X[train_idx], label=y[train_idx])
        val_data = lgb.Dataset(X[val_idx], label=y[val_idx], reference=train_data)
        model = lgb.train(
            params, train_data,
            num_boost_round=1000,
            valid_sets=[val_data],
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
        )
        pred = model.predict(X[val_idx])
        score = log_loss(y[val_idx], pred)
        cv_scores.append(score)
        best_iterations.append(model.best_iteration)
        print(f"  Fold {fold+1}: logloss={score:.4f}, best_iter={model.best_iteration}")

    print(f"\nCV平均 logloss: {np.mean(cv_scores):.4f} (+/- {np.std(cv_scores):.4f})")

    # 7. 最終モデル（全データで学習）
    best_iter_mean = int(np.mean(best_iterations))
    print(f"\n全データで学習中 (num_boost_round={best_iter_mean})...")
    train_data_all = lgb.Dataset(X, label=y)
    final_model = lgb.train(
        params, train_data_all,
        num_boost_round=best_iter_mean,
        callbacks=[lgb.log_evaluation(0)],
    )

    # 8. 特徴量重要度表示
    importance = final_model.feature_importance(importance_type="gain")
    feat_imp = sorted(zip(FEATURE_COLS, importance), key=lambda x: x[1], reverse=True)
    print("\n【特徴量重要度 TOP15】")
    for feat, imp in feat_imp[:15]:
        print(f"  {feat:>30s}: {imp:.1f}")

    # 9. モデル保存
    os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
    model_data = {
        "model": final_model,
        "feature_cols": FEATURE_COLS,
        "train_start": train_start,
        "train_end": train_end,
        "cv_scores": cv_scores,
        "pos_rate": pos_rate,
        "scale_pos_weight": scale_pos_weight,
        "label_type": "win",
    }
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model_data, f)

    file_size_kb = os.path.getsize(MODEL_PATH) / 1024
    print(f"\nモデル保存: {MODEL_PATH}")
    print(f"ファイルサイズ: {file_size_kb:.1f} KB")
    return final_model


def load_model():
    """保存済みモデルを読み込み"""
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)
    return data["model"], data["feature_cols"]


def predict_race(conn, race_id, model=None):
    """1レースの勝率（p_win）を予測"""
    if model is None:
        model, _ = load_model()

    c = conn.cursor()
    c.execute("SELECT date FROM races WHERE race_id = ?", (race_id,))
    row = c.fetchone()
    if not row:
        return []

    df_race = build_features_for_date(conn, row[0])
    df_race = df_race[df_race["race_id"] == race_id]
    if df_race.empty:
        return []

    X = df_race[FEATURE_COLS].values
    probs = model.predict(X)

    results = []
    for i, (_, entry) in enumerate(df_race.iterrows()):
        odds = entry.get("odds_win", None)
        ev_win = float(probs[i]) * float(odds) if odds and odds > 0 else 0.0
        results.append({
            "horse_id": entry["horse_id"],
            "horse_number": int(entry["horse_number"]),
            "prob_win": float(probs[i]),
            "odds_win": float(odds) if odds else None,
            "popularity": int(entry["popularity"]) if entry.get("popularity") else None,
            "ev_win": ev_win,
        })

    results.sort(key=lambda x: x["prob_win"], reverse=True)
    return results


def main():
    import time
    conn = get_conn()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 model_v3_win.py train                        # 学習")
        print("  python3 model_v3_win.py train 2022-01-01 2024-12-31  # 期間指定")
        print("  python3 model_v3_win.py predict 202503020911          # 1レース予測")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "train":
        start = sys.argv[2] if len(sys.argv) > 2 else "2022-01-01"
        end = sys.argv[3] if len(sys.argv) > 3 else "2024-12-31"
        t0 = time.time()
        train_model(conn, start, end)
        elapsed = time.time() - t0
        print(f"\n学習時間: {elapsed:.1f}秒 ({elapsed/60:.1f}分)")

    elif cmd == "predict":
        if len(sys.argv) < 3:
            print("race_idを指定してください")
            sys.exit(1)
        race_id = sys.argv[2]
        results = predict_race(conn, race_id)
        if not results:
            print(f"レース {race_id} のデータが見つかりません")
            sys.exit(1)
        print(f"\n=== {race_id} 勝率予測（純粋実力モデル v3） ===")
        print(f"{'馬番':>4s} {'勝率':>6s} {'オッズ':>6s} {'EV':>6s} {'人気':>4s}")
        for r in results:
            odds_str = f"{r['odds_win']:6.1f}" if r["odds_win"] else "  N/A "
            pop_str = f"{r['popularity']:>4d}" if r["popularity"] else " N/A"
            print(f"  {r['horse_number']:>4d} {r['prob_win']:.3f} {odds_str} {r['ev_win']:6.3f} {pop_str}")

    else:
        print(f"不明なコマンド: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
