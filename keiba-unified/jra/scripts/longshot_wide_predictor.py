#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Longshot Wide Portfolio 予測モジュール v3
人気薄軸×ワイド3点流し 5戦略conv>=2フィルタ

訓練カットオフ設計:
  - TRAIN_CUTOFF_MONTHS=18 (デフォルト): 当日から18ヶ月前〜当日前日で訓練
  - これによりモデルの確率スケールをバックテストと近い水準に保つ
  - 固定値: 少なくとも最低1万行のデータが必要
"""

import os
import sys
import sqlite3
import time
import traceback
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
from typing import List, Dict, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

DATA_DIR     = "/opt/keiba-unified/jra/data"
FEATURES_PKL = os.path.join(DATA_DIR, "features_all.pkl")
DB_PATH      = os.path.join(DATA_DIR, "keiba.db")

MODEL_PARAMS = {
    "n_estimators": 500, "max_depth": 5, "learning_rate": 0.03,
    "num_leaves": 24, "min_child_samples": 50, "subsample": 0.7,
    "colsample_bytree": 0.6, "reg_alpha": 0.5, "reg_lambda": 2.0,
    "verbose": -1,
}

# 訓練ウィンドウ: 当日から TRAIN_CUTOFF_MONTHS ヶ月前
TRAIN_CUTOFF_MONTHS = 18
TRAIN_MIN_ROWS = 10000  # 最低訓練行数（不足時は全過去データ使用）

# 5戦略定義
STRATEGIES = {
    "baseline": dict(anchor_pop=7, anchor_prob=0.25, anchor_minodds=0,
                     anchor_maxodds=80, anchor_edge=0.0,
                     partner_prob=0.35, partner_count=3),
    "A1":       dict(anchor_pop=7, anchor_prob=0.28, anchor_minodds=0,
                     anchor_maxodds=80, anchor_edge=0.0,
                     partner_prob=0.35, partner_count=3),
    "C2":       dict(anchor_pop=7, anchor_prob=0.25, anchor_minodds=0,
                     anchor_maxodds=80, anchor_edge=0.0,
                     partner_prob=0.45, partner_count=3),
    "E1":       dict(anchor_pop=7, anchor_prob=0.28, anchor_minodds=10,
                     anchor_maxodds=40, anchor_edge=0.0,
                     partner_prob=0.40, partner_count=3),
    "D2":       dict(anchor_pop=7, anchor_prob=0.25, anchor_minodds=0,
                     anchor_maxodds=80, anchor_edge=0.20,
                     partner_prob=0.35, partner_count=3),
}

MIN_CONV   = 2
MIN_HORSES = 10


def _build_today_features(date_str: str, conn: sqlite3.Connection) -> Optional[pd.DataFrame]:
    """当日データをDBから読み込んで特徴量DataFrameを生成。
    keiba_live.db のスキーマに対応（races.date, results テーブル）。"""
    # keiba_live.db に接続（当日データはこちらにある）
    live_db = os.path.join(os.path.dirname(DB_PATH), "keiba_live.db")
    if os.path.exists(live_db):
        live_conn = sqlite3.connect(live_db)
    else:
        live_conn = conn
    c = live_conn.cursor()

    c.execute("""
        SELECT race_id, venue, race_number, name, surface, distance,
               track_condition, start_time, class, head_count
        FROM races
        WHERE date = ?
          AND surface IN ('芝','ダート')
          AND (name IS NULL OR name NOT LIKE '%%障害%%')
        ORDER BY race_id
    """, (date_str,))
    races = c.fetchall()
    if not races:
        if live_conn != conn:
            live_conn.close()
        return None

    rows = []
    for race_row in races:
        (race_id, venue, race_no, race_name, surface, distance,
         track_cond, start_time, race_class, horse_count) = race_row

        c.execute("""
            SELECT r.horse_id, r.horse_number, r.post_position,
                   r.horse_weight, r.weight_change, r.jockey_id,
                   COALESCE(h.name, ''), COALESCE(r.sex_age, ''),
                   r.odds_win, r.popularity
            FROM results r
            LEFT JOIN horses h ON r.horse_id = h.horse_id
            WHERE r.race_id = ?
            ORDER BY r.horse_number
        """, (race_id,))
        entries = c.fetchall()
        if not entries:
            continue

        odds_list  = [float(ent[8] or 0) for ent in entries]
        valid_odds = [o for o in odds_list if o > 0]
        total_imp  = sum(1.0/o for o in valid_odds) if valid_odds else 1.0
        sorted_odds = sorted(valid_odds)
        odds_gap   = (sorted_odds[1] / sorted_odds[0]) if len(sorted_odds) >= 2 else 1.0
        fav_strength = (1.0/sorted_odds[0] / total_imp) if sorted_odds else 0.0
        imps       = [1.0/o / total_imp for o in valid_odds] if valid_odds else []
        odds_conc  = sum(p**2 for p in imps) if imps else 0.0

        for ent in entries:
            (horse_id, horse_num, frame_num, hw, hw_change,
             jockey_id, horse_name, sex_age,
             odds_win, popularity) = ent
            try:
                age = int(''.join(c for c in str(sex_age) if c.isdigit())) if sex_age else 4
                sex = sex_age[0] if sex_age else ''
            except Exception:
                age, sex = 4, ''

            odds_win   = float(odds_win or 0)
            popularity = int(popularity or 0)
            log_odds   = float(np.log(odds_win)) if odds_win > 1 else 0.0
            implied_prob = (1.0 / odds_win) if odds_win > 0 else 0.0

            c.execute("""
                SELECT
                    AVG(CASE WHEN r.finish_position=1 THEN 1.0 ELSE 0.0 END),
                    AVG(CASE WHEN r.finish_position<=3 THEN 1.0 ELSE 0.0 END),
                    AVG(r.finish_position),
                    COUNT(*),
                    0.0, 0.0, 0.0
                FROM results r
                WHERE r.horse_id=?
            """, (horse_id,))
            hr = c.fetchone()
            win_rate_all  = float(hr[0] or 0) if hr else 0.0
            top3_rate_all = float(hr[1] or 0) if hr else 0.0
            avg_fin_pos   = float(hr[2] or 8) if hr else 8.0
            career_races  = int(hr[3] or 0) if hr else 0
            distance_wins = float(hr[4] or 0) if hr else 0.0
            surface_wins  = float(hr[5] or 0) if hr else 0.0
            venue_wins    = float(hr[6] or 0) if hr else 0.0

            c.execute("""
                SELECT AVG(CASE WHEN r.finish_position=1 THEN 1.0 ELSE 0.0 END),
                       AVG(CASE WHEN r.finish_position<=3 THEN 1.0 ELSE 0.0 END)
                FROM results r
                WHERE r.jockey_id=?
            """, (jockey_id,))
            jr = c.fetchone()
            jockey_win_rate  = float(jr[0] or 0) if jr else 0.0
            jockey_top3_rate = float(jr[1] or 0) if jr else 0.0

            surface_type = 1 if surface == "芝" else 2
            track_map = {"良":1,"稍重":2,"重":3,"不良":4}
            track_code = track_map.get(track_cond or "良", 1)
            venue_map = {"東京":5,"中山":6,"京都":7,"阪神":8,"中京":9,
                         "小倉":10,"福島":1,"新潟":2,"札幌":3,"函館":4}
            venue_code = venue_map.get(venue, 0)
            dist_cat = 1 if (distance or 1600)<1400 else 2 if (distance or 1600)<1800 else 3 if (distance or 1600)<2200 else 4
            sex_map = {"牡":1,"牝":2,"セ":3}
            sex_code = sex_map.get(sex or "", 1)
            dt = datetime.strptime(date_str, "%Y-%m-%d")

            rows.append({
                "race_id": race_id, "race_date": date_str,
                "horse_id": horse_id, "horse_name": horse_name or "",
                "horse_number": horse_num, "finish_order": 0,
                "speed_index_last3":0.0, "speed_index_best3":0.0, "speed_index_std":0.0,
                "pace_index_last3":0.0, "running_style":0.0,
                "win_rate_all": win_rate_all, "top3_rate_all": top3_rate_all,
                "win_rate_recent5": win_rate_all, "top3_rate_recent5": top3_rate_all,
                "avg_finish_position": avg_fin_pos,
                "final_3f_avg":0.0, "final_3f_best":0.0,
                "horse_weight": float(hw or 480), "weight_change": float(hw_change or 0),
                "days_since_last_race":14.0, "age": int(age or 3),
                "sex_code": sex_code, "career_races": career_races,
                "distance_wins": distance_wins, "surface_wins": surface_wins,
                "venue_wins": venue_wins, "condition_perf":0.0, "class_level":0.0,
                "corner_position_avg":0.0, "weight_carry_diff":0.0,
                "jockey_win_rate_1y": jockey_win_rate, "jockey_top3_rate_1y": jockey_top3_rate,
                "jockey_venue_rate": jockey_win_rate, "jockey_surface_rate": jockey_win_rate,
                "jockey_distance_rate": jockey_win_rate,
                "jockey_trainer_combo":0.0, "jockey_horse_combo":0.0,
                "jockey_avg_odds_win":0.0, "jockey_change_flag":0, "jockey_weight_range":0.0,
                "horse_count": int(horse_count or len(entries)),
                "distance": int(distance or 1600), "distance_category": dist_cat,
                "surface_type": surface_type, "track_condition_code": track_code,
                "venue_code": venue_code, "direction_code":0, "grade_code":0,
                "month": dt.month,
                "is_special_race": 1 if race_name and race_name.strip() else 0,
                "frame_number": int(frame_num or horse_num), "post_position_bias":0.0,
                "field_quality":0.0,
                "odds": odds_win, "log_odds": log_odds, "popularity": popularity,
                "implied_probability": implied_prob,
                "odds_gap_1st_2nd": odds_gap, "favorite_strength": fav_strength,
                "odds_concentration": odds_conc, "model_vs_market":1.0, "expected_value":1.0,
            })

    if live_conn != conn:
        live_conn.close()
    return pd.DataFrame(rows) if rows else None


def _run_strategy(race_df: pd.DataFrame, cfg: dict) -> List[Dict]:
    """1戦略のコンボ候補を返す（raw pred_proba で条件評価）"""
    results = []
    for race_id, grp in race_df.groupby("race_id"):
        if len(grp) < MIN_HORSES:
            continue
        horses = []
        for _, row in grp.iterrows():
            odds = float(row.get("odds", 0) or 0)
            pop  = int(row.get("popularity", 0) or 0)
            prob = float(row.get("pred_proba", 0) or 0)
            hnum = int(row.get("horse_number", 0))
            hname = str(row.get("horse_name", ""))
            imp  = float(row.get("implied_probability", 0) or 0)
            ev   = (prob / imp) if imp > 0 else 0.0
            if odds <= 0 or pop <= 0:
                continue
            horses.append({"num":hnum,"name":hname,"prob":prob,"odds":odds,"pop":pop,"ev":ev})

        if not horses:
            continue

        anchors = [h for h in horses
                   if h["pop"] >= cfg["anchor_pop"]
                   and h["prob"] >= cfg["anchor_prob"]
                   and (cfg["anchor_minodds"] == 0 or h["odds"] >= cfg["anchor_minodds"])
                   and h["odds"] <= cfg["anchor_maxodds"]
                   and h["ev"] >= cfg["anchor_edge"]]
        if not anchors:
            continue
        anchors.sort(key=lambda x: x["prob"], reverse=True)
        anchor = anchors[0]

        others = [h for h in horses
                  if h["num"] != anchor["num"] and h["prob"] >= cfg["partner_prob"]]
        others.sort(key=lambda x: x["prob"], reverse=True)
        partners = others[:cfg["partner_count"]]
        if len(partners) < cfg["partner_count"]:
            continue

        for p in partners:
            combo = tuple(sorted([anchor["num"], p["num"]]))
            results.append({
                "race_id": race_id, "combo": combo,
                "anchor_num": anchor["num"], "anchor_name": anchor["name"],
                "anchor_pop": anchor["pop"], "anchor_prob": anchor["prob"], "partners": partners,
            })
    return results


def init_longshot_model(date_str: str):
    """モデルを訓練して返す（起動時1回だけ呼ぶ）"""
    print(f"[LongshotWide] モデル初期化: {date_str}")
    base_df = pd.read_pickle(FEATURES_PKL)
    base_df["target"] = (base_df["finish_order"] <= 3).astype(int)

    try:
        target_dt = datetime.strptime(date_str, "%Y-%m-%d")
        window_start = (target_dt - relativedelta(months=TRAIN_CUTOFF_MONTHS)).strftime("%Y-%m-%d")
    except Exception:
        window_start = "2023-01-01"

    dates = pd.to_datetime(base_df["race_date"])
    train_mask = (dates >= window_start) & (dates < pd.Timestamp(date_str))
    train_df = base_df[train_mask]
    if len(train_df) < TRAIN_MIN_ROWS:
        train_df = base_df[dates < pd.Timestamp(date_str)]
    if len(train_df) == 0:
        return None, None

    meta_cols = {"race_id","race_date","horse_id","horse_name",
                 "horse_number","finish_order","target","pred_proba"}
    feature_cols = [c for c in base_df.columns if c not in meta_cols]

    from src.models.lgbm_model import LGBMModel
    model = LGBMModel(params=MODEL_PARAMS)
    model.fit(train_df[feature_cols].fillna(0), train_df["target"])
    print(f"[LongshotWide] モデル訓練完了: {len(train_df)} rows, {len(feature_cols)} cols")
    return model, feature_cols


def predict_single_race(race_id: str, date_str: str, model, feature_cols: list) -> Optional[Dict]:
    """1レースの穴予想を最新オッズで再計算する"""
    conn = sqlite3.connect(DB_PATH)
    try:
        live_db = os.path.join(os.path.dirname(DB_PATH), "keiba_live.db")
        live_conn = sqlite3.connect(live_db) if os.path.exists(live_db) else conn
        c = live_conn.cursor()

        # そのレースの馬データを取得
        c.execute("""
            SELECT r.horse_id, r.horse_number, r.post_position,
                   r.horse_weight, r.weight_change, r.jockey_id,
                   COALESCE(h.name, ''), COALESCE(r.sex_age, ''),
                   r.odds_win, r.popularity
            FROM results r
            LEFT JOIN horses h ON r.horse_id = h.horse_id
            WHERE r.race_id = ?
            ORDER BY r.horse_number
        """, (race_id,))
        entries = c.fetchall()
        if not entries or len(entries) < MIN_HORSES:
            if live_conn != conn: live_conn.close()
            conn.close()
            return None

        # レース情報
        c.execute("SELECT venue,race_number,name,surface,distance,track_condition,start_time,head_count FROM races WHERE race_id=?",
                  (race_id,))
        race_row = c.fetchone()
        if not race_row:
            if live_conn != conn: live_conn.close()
            conn.close()
            return None
        venue, race_no, race_name, surface, distance, track_cond, start_time, horse_count = race_row

        # 特徴量構築（_build_today_features と同じロジック、1レース分）
        odds_list = [float(e[8] or 0) for e in entries]
        valid_odds = [o for o in odds_list if o > 0]
        total_imp = sum(1.0/o for o in valid_odds) if valid_odds else 1.0
        sorted_odds = sorted(valid_odds) if valid_odds else [1.0]
        odds_gap = (sorted_odds[1] / sorted_odds[0]) if len(sorted_odds) >= 2 else 1.0
        fav_strength = (1.0/sorted_odds[0] / total_imp) if sorted_odds else 0.0
        imps = [1.0/o / total_imp for o in valid_odds] if valid_odds else []
        odds_conc = sum(p**2 for p in imps) if imps else 0.0
        venue_map = {"東京":5,"中山":6,"京都":7,"阪神":8,"中京":9,"福島":10,"小倉":11,"新潟":12,"札幌":13,"函館":14}

        rows = []
        for ent in entries:
            (horse_id, horse_num, frame_num, hw, hw_change,
             jockey_id, horse_name, sex_age, odds_win, popularity) = ent
            try:
                age = int(''.join(ch for ch in str(sex_age) if ch.isdigit())) if sex_age else 4
            except: age = 4
            odds_win = float(odds_win or 0)
            popularity = int(popularity or 0)
            log_odds = float(np.log(odds_win)) if odds_win > 1 else 0.0
            implied_prob = (1.0 / odds_win) if odds_win > 0 else 0.0
            model_vs_market = 0.0
            expected_value = 0.0

            # 馬の過去成績（簡易）
            c2 = live_conn.cursor()
            c2.execute("SELECT AVG(CASE WHEN finish_position=1 THEN 1.0 ELSE 0.0 END), AVG(CASE WHEN finish_position<=3 THEN 1.0 ELSE 0.0 END), AVG(finish_position), COUNT(*) FROM results WHERE horse_id=?", (horse_id,))
            hr = c2.fetchone()
            win_rate_all = float(hr[0] or 0) if hr else 0.0
            top3_rate_all = float(hr[1] or 0) if hr else 0.0
            avg_fin_pos = float(hr[2] or 8) if hr else 8.0
            career_races = int(hr[3] or 0) if hr else 0

            c2.execute("SELECT AVG(CASE WHEN finish_position=1 THEN 1.0 ELSE 0.0 END), AVG(CASE WHEN finish_position<=3 THEN 1.0 ELSE 0.0 END) FROM results WHERE jockey_id=?", (jockey_id,))
            jr = c2.fetchone()
            jockey_win_rate = float(jr[0] or 0) if jr else 0.0
            jockey_top3_rate = float(jr[1] or 0) if jr else 0.0

            surface_type = 1 if surface == "芝" else 2
            track_map = {"良":1,"稍重":2,"重":3,"不良":4}
            distance_val = int(distance) if distance else 1600

            row = {
                "race_id": race_id, "race_date": date_str,
                "horse_id": horse_id, "horse_name": horse_name,
                "horse_number": int(horse_num), "finish_order": 0,
                "speed_index_last3":0, "speed_index_best3":0, "speed_index_std":0,
                "pace_index_last3":0, "running_style":0,
                "win_rate_all": win_rate_all, "top3_rate_all": top3_rate_all,
                "win_rate_recent5": win_rate_all, "top3_rate_recent5": top3_rate_all,
                "avg_finish_position": avg_fin_pos, "final_3f_avg":0, "final_3f_best":0,
                "horse_weight": float(hw or 0), "weight_change": float(hw_change or 0),
                "days_since_last_race":30, "age": age, "sex_code": 0,
                "career_races": career_races, "distance_wins":0, "surface_wins":0,
                "venue_wins":0, "condition_perf":0, "class_level":0,
                "corner_position_avg":0, "weight_carry_diff":0,
                "jockey_win_rate_1y": jockey_win_rate, "jockey_top3_rate_1y": jockey_top3_rate,
                "jockey_venue_rate": jockey_win_rate, "jockey_surface_rate": jockey_win_rate,
                "jockey_distance_rate": jockey_win_rate, "jockey_trainer_combo":0,
                "jockey_horse_combo":0, "jockey_avg_odds_win":0, "jockey_change_flag":0,
                "jockey_weight_range":0,
                "horse_count": int(horse_count or len(entries)),
                "distance": distance_val, "distance_category": distance_val // 400,
                "surface_type": surface_type,
                "track_condition_code": track_map.get(track_cond, 0),
                "venue_code": venue_map.get(venue, 0), "direction_code":0, "grade_code":0,
                "month": int(date_str[5:7]), "is_special_race":0,
                "frame_number": int(frame_num or 0), "post_position_bias":0, "field_quality":0,
                "odds": odds_win, "log_odds": log_odds, "popularity": popularity,
                "implied_probability": implied_prob,
                "odds_gap_1st_2nd": odds_gap, "favorite_strength": fav_strength,
                "odds_concentration": odds_conc,
                "model_vs_market": model_vs_market, "expected_value": expected_value,
            }
            rows.append(row)

        if live_conn != conn: live_conn.close()

        race_df = pd.DataFrame(rows)
        for col in feature_cols:
            if col not in race_df.columns:
                race_df[col] = 0
        X = race_df[feature_cols].fillna(0)
        race_df["pred_proba"] = model.predict_proba(X)

        # 5戦略フィルタ（このレースだけ）
        combo_conv = {}
        for strat_name, cfg in STRATEGIES.items():
            candidates = _run_strategy(race_df, cfg)
            for cand in candidates:
                key = (cand["race_id"], cand["combo"])
                if key not in combo_conv:
                    combo_conv[key] = {"conv": 0, "anchor_num": cand["anchor_num"],
                                       "anchor_name": cand["anchor_name"],
                                       "anchor_pop": cand["anchor_pop"], "anchor_prob": cand.get("anchor_prob",0),
                                       "partners": cand["partners"]}
                combo_conv[key]["conv"] += 1

        qualified = {k: v for k, v in combo_conv.items() if v["conv"] >= MIN_CONV}
        if not qualified:
            conn.close()
            return None

        # 最大convのコンボを採用
        best = max(qualified.values(), key=lambda x: x["conv"])
        pnums = sorted(set(p["num"] for p in best["partners"]))
        result = {
            "race_id": race_id, "venue": venue or "", "race_no": race_no or 0,
            "race_name": race_name or "", "start_time": start_time or "",
            "anchor": {"num": best["anchor_num"], "name": best["anchor_name"],
                       "popularity": best["anchor_pop"], "prob": best.get("anchor_prob",0)},
            "partners": [{"num": n, "name": ""} for n in pnums[:3]],
            "conv": best["conv"],
        }
        # パートナー名を付与
        for p in result["partners"]:
            for pp in best["partners"]:
                if pp["num"] == p["num"]:
                    p["name"] = pp["name"]
                    break

        conn.close()
        return result
    except Exception as e:
        print(f"[LongshotWide] predict_single_race error: {e}")
        conn.close()
        return None


def predict_longshot_wide(date_str: str) -> List[Dict]:
    """Longshot Wide Portfolio (conv>=2) の予測を実行する。"""
    print(f"[LongshotWide] 予測開始: {date_str}")
    conn = sqlite3.connect(DB_PATH)
    try:
        print("[LongshotWide] features_all.pkl 読み込み中...")
        base_df = pd.read_pickle(FEATURES_PKL)
        base_df["target"] = (base_df["finish_order"] <= 3).astype(int)
        print(f"[LongshotWide] features shape: {base_df.shape}")

        # 訓練ウィンドウ: [date_str - 18months, date_str)
        try:
            target_dt = datetime.strptime(date_str, "%Y-%m-%d")
            window_start = (target_dt - relativedelta(months=TRAIN_CUTOFF_MONTHS)).strftime("%Y-%m-%d")
        except Exception:
            window_start = "2023-01-01"

        dates = pd.to_datetime(base_df["race_date"])
        train_mask = (dates >= window_start) & (dates < pd.Timestamp(date_str))
        train_df   = base_df[train_mask]

        # 最低行数チェック: 不足時は全過去データを使用
        if len(train_df) < TRAIN_MIN_ROWS:
            print(f"[LongshotWide] 訓練データ不足({len(train_df)}行)、全過去データで訓練")
            train_df = base_df[dates < pd.Timestamp(date_str)]

        if len(train_df) == 0:
            print("[LongshotWide] 訓練データなし")
            conn.close()
            return []

        meta_cols = {"race_id","race_date","horse_id","horse_name",
                     "horse_number","finish_order","target","pred_proba"}
        feature_cols = [c for c in base_df.columns if c not in meta_cols]

        X_train = train_df[feature_cols].fillna(0)
        y_train = train_df["target"]
        print(f"[LongshotWide] 訓練: {len(X_train)} rows [{window_start} ~ {date_str}), {len(feature_cols)} cols")

        t0 = time.time()
        from src.models.lgbm_model import LGBMModel
        model = LGBMModel(params=MODEL_PARAMS)
        model.fit(X_train, y_train)
        print(f"[LongshotWide] 訓練完了: {time.time()-t0:.1f}s")

        # 当日データ: pklに含まれなければDBから生成
        today_in_pkl = base_df[base_df["race_date"] == date_str]
        if len(today_in_pkl) > 0:
            print(f"[LongshotWide] pkl内の当日データ使用: {len(today_in_pkl)} rows")
            today_df = today_in_pkl.copy()
        else:
            print("[LongshotWide] DBから当日特徴量生成中...")
            today_df = _build_today_features(date_str, conn)
            if today_df is None or len(today_df) == 0:
                print("[LongshotWide] 当日レースデータなし")
                conn.close()
                return []
            print(f"[LongshotWide] 生成完了: {len(today_df)} rows")

        # 障害レース除外（DBから判定）
        c_filter = conn.cursor()
        c_filter.execute(
            "SELECT race_id FROM races WHERE race_date=? AND race_name LIKE '%障害%'",
            (date_str,)
        )
        hando_ids = {r[0] for r in c_filter.fetchall()}
        if hando_ids:
            today_df = today_df[~today_df["race_id"].isin(hando_ids)]
            print(f"[LongshotWide] 障害レース除外: {len(hando_ids)} レース")

        for col in feature_cols:
            if col not in today_df.columns:
                today_df[col] = 0

        X_today = today_df[feature_cols].fillna(0)
        probas  = model.predict_proba(X_today)
        today_df = today_df.copy()
        today_df["pred_proba"] = probas
        # raw pred_proba で戦略条件を評価 (正規化しない)

        print(f"[LongshotWide] 予測完了: {today_df['race_id'].nunique()} レース")
        print(f"[LongshotWide] pred_proba max={probas.max():.4f} mean={probas.mean():.4f}")

        # 5戦略フィルタ
        combo_conv: Dict = {}
        for strat_name, cfg in STRATEGIES.items():
            candidates = _run_strategy(today_df, cfg)
            for cand in candidates:
                key = (cand["race_id"], cand["combo"])
                if key not in combo_conv:
                    combo_conv[key] = {
                        "race_id": cand["race_id"], "combo": cand["combo"],
                        "anchor_num": cand["anchor_num"], "anchor_name": cand["anchor_name"],
                        "anchor_pop": cand["anchor_pop"], "anchor_prob": cand.get("anchor_prob",0), "anchor_prob": cand.get("anchor_prob",0), "partners": cand["partners"],
                        "conv": 0, "strategies": [],
                    }
                combo_conv[key]["conv"] += 1
                combo_conv[key]["strategies"].append(strat_name)
            print(f"  [{strat_name}] candidates: {len(candidates)}")

        qualified = {k: v for k, v in combo_conv.items() if v["conv"] >= MIN_CONV}
        print(f"[LongshotWide] conv>={MIN_CONV}: {len(qualified)} / 全{len(combo_conv)}")

        # レースごとに集約
        race_combos: Dict = {}
        for (race_id, combo), info in qualified.items():
            if race_id not in race_combos:
                race_combos[race_id] = {
                    "race_id": race_id,
                    "anchor_num": info["anchor_num"], "anchor_name": info["anchor_name"],
                    "anchor_pop": info["anchor_pop"], "anchor_prob": info.get("anchor_prob",0),
                    "partner_nums": set(), "partner_names": {}, "conv": info["conv"],
                }
            elif info["conv"] > race_combos[race_id]["conv"]:
                race_combos[race_id]["conv"] = info["conv"]
            for p in info["partners"]:
                race_combos[race_id]["partner_nums"].add(p["num"])
                race_combos[race_id]["partner_names"][p["num"]] = p["name"]

        # レース情報付与（keiba_live.db から取得）
        output = []
        live_db = os.path.join(os.path.dirname(DB_PATH), "keiba_live.db")
        live_conn2 = sqlite3.connect(live_db) if os.path.exists(live_db) else conn
        c = live_conn2.cursor()
        for race_id, rc in race_combos.items():
            # keiba_live.db schema: venue, race_number, name, start_time
            c.execute("SELECT venue,race_number,name,start_time FROM races WHERE race_id=?",
                      (race_id,))
            row = c.fetchone()
            if not row:
                # fallback: keiba.db schema
                c2 = conn.cursor()
                c2.execute("SELECT venue_name,race_number,race_name FROM races WHERE race_id=?",
                           (race_id,))
                row2 = c2.fetchone()
                venue, race_no, race_name, start_time = (
                    (row2[0] or "", row2[1] or 0, row2[2] or "", "") if row2 else ("",0,"","")
                )
            else:
                venue, race_no, race_name, start_time = (
                    row[0] or "", row[1] or 0, row[2] or "", row[3] or ""
                )
            pnums = sorted(rc["partner_nums"])
            output.append({
                "race_id": race_id, "venue": venue or "",
                "race_no": race_no or 0, "race_name": race_name or "",
                "start_time": start_time or "",
                "anchor": {"num": rc["anchor_num"], "name": rc["anchor_name"],
                           "popularity": rc["anchor_pop"], "prob": rc.get("anchor_prob",0)},
                "partners": [{"num":n,"name":rc["partner_names"].get(n,"")} for n in pnums],
                "conv": rc["conv"],
            })

        if live_conn2 != conn:
            live_conn2.close()

        output.sort(key=lambda x: (x["start_time"], x["race_id"]))
        print(f"[LongshotWide] 出力: {len(output)} レース")
        for item in output:
            pn = [str(p["num"]) for p in item["partners"]]
            print(f"  {item['venue']}{item['race_no']}R 軸:{item['anchor']['num']} "
                  f"相手:{','.join(pn)} conv={item['conv']}")

        conn.close()
        return output

    except Exception as e:
        print(f"[LongshotWide] エラー: {e}")
        traceback.print_exc()
        conn.close()
        return []


def _num_to_circle(n: int) -> str:
    circles = ["①","②","③","④","⑤","⑥","⑦","⑧","⑨","⑩",
               "⑪","⑫","⑬","⑭","⑮","⑯","⑰","⑱"]
    return circles[n-1] if 1 <= n <= 18 else str(n)


def format_longshot_message(longshot: List[Dict]) -> str:
    lines = ["━━━━━━━━━━", "🎯 今日の穴予想", "※人気薄軸のワイド3点流し", ""]
    for item in longshot:
        venue, race_no = item["venue"], item["race_no"]
        name, stime    = item.get("race_name",""), item.get("start_time","")
        anchor         = item["anchor"]
        partners       = item["partners"]
        header = f"【{venue}{race_no}R {name}】{stime}" if name else f"【{venue}{race_no}R】{stime}"
        lines.append(header)
        prob_str = f" p={anchor.get('prob',0):.2f}" if anchor.get('prob') else ""
        lines.append(f"軸: {_num_to_circle(anchor['num'])}{anchor['name']} ({anchor['popularity']}番人気{prob_str})")
        p_strs = "".join(_num_to_circle(p["num"]) for p in partners)
        lines.append(f"相手: {p_strs}")
        lines.append("")
    lines.append("━━━━━━━━━━")
    return "\n".join(lines)


if __name__ == "__main__":
    date_arg = sys.argv[1] if len(sys.argv) > 1 else date.today().strftime("%Y-%m-%d")
    result = predict_longshot_wide(date_arg)
    if result:
        print("\n" + format_longshot_message(result))
    else:
        print("穴予想なし")
