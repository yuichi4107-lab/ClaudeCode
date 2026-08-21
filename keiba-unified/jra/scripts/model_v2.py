#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
競馬予想 v2 - LightGBMモデル
特徴量エンジニアリング + LightGBMで3着内確率を予測
"""

import sqlite3
import os
import sys
import pickle
import numpy as np
import pandas as pd
import lightgbm as lgb
from datetime import datetime, timedelta
from sklearn.model_selection import GroupKFold

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "keiba.db")
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "models", "model_v2_live.pkl")

CLASS_LEVEL = {
    "新馬": 1, "未勝利": 2, "1勝": 3, "2勝": 4, "3勝": 5,
    "OP": 6, "G3": 7, "G2": 8, "G1": 9,
}

VENUE_CODE = {
    "札幌": 1, "函館": 2, "福島": 3, "新潟": 4, "東京": 5,
    "中山": 6, "中京": 7, "京都": 8, "阪神": 9, "小倉": 10,
}


def get_conn():
    return sqlite3.connect(DB_PATH)


# ============================================================
# 特徴量エンジニアリング
# ============================================================

def build_features_for_date(conn, target_date):
    """指定日の全出走馬の特徴量を構築（データリーク防止: target_date未満のデータのみ使用）"""
    c = conn.cursor()

    # 対象レース取得
    c.execute("""SELECT race_id, date, venue, race_number, class, distance, surface,
                        direction, track_condition, weather, head_count
                 FROM races
                 WHERE date = ? AND surface IN ('芝', 'ダート')""", (target_date,))
    races = c.fetchall()
    if not races:
        return pd.DataFrame()

    all_rows = []

    for race in races:
        race_id = race[0]
        race_date = race[1]
        venue = race[2]
        race_class = race[4]
        distance = race[5]
        surface = race[6]
        direction = race[7]
        track_condition = race[8]
        weather = race[9]
        head_count = race[10]

        # 出走馬取得
        c.execute("""SELECT horse_id, jockey_id, trainer_id, post_position, horse_number,
                            weight_carried, horse_weight, weight_change, finish_position,
                            odds_win, popularity, sex_age, last_3f
                     FROM results WHERE race_id = ?""", (race_id,))
        entries = c.fetchall()

        # --- レース単位の展開予測特徴量を事前計算 ---
        # 各馬の前走位置取りを集計して先行馬の数を推定
        pace_positions = []
        for entry in entries:
            eid = entry[0]  # horse_id
            c.execute("""
                SELECT r.passing FROM results r JOIN races ra ON r.race_id = ra.race_id
                WHERE r.horse_id = ? AND ra.date < ? AND r.finish_position > 0
                      AND ra.surface IN ('芝', 'ダート')
                ORDER BY ra.date DESC LIMIT 1
            """, (eid, target_date))
            prow = c.fetchone()
            if prow and prow[0]:
                try:
                    pp = int(prow[0].split("-")[0])
                    pace_positions.append(pp)
                except (ValueError, IndexError):
                    pass

        # 先行馬数（前走で3番手以内だった馬の数）
        n_front_runners = sum(1 for p in pace_positions if p <= 3)
        # 先行馬比率
        front_ratio = n_front_runners / len(entries) if entries else 0.3
        # ハイペース予測（先行馬が多い = ハイペース気味）
        pace_pressure = min(1.0, n_front_runners / 4)

        for entry in entries:
            horse_id = entry[0]
            jockey_id = entry[1]
            trainer_id = entry[2]
            post_position = entry[3]
            horse_number = entry[4]
            weight_carried = entry[5]
            horse_weight = entry[6]
            weight_change = entry[7]
            finish_position = entry[8]
            odds_win = entry[9]
            popularity = entry[10]
            sex_age = entry[11] or ""
            last_3f_actual = entry[12]

            # ラベル: 3着以内=1, それ以外=0
            label = 1 if finish_position > 0 and finish_position <= 3 else 0

            # 性別・年齢
            sex = sex_age[0] if sex_age else ""
            try:
                age = int(sex_age[1:]) if len(sex_age) > 1 else 0
            except ValueError:
                age = 0

            # --- 過去成績特徴量 ---
            past_feats = _horse_past_features(c, horse_id, target_date)

            # --- 騎手特徴量 ---
            jockey_feats = _jockey_features(c, jockey_id, venue, surface, target_date)

            # --- 調教師特徴量 ---
            trainer_feats = _trainer_features(c, trainer_id, target_date)

            # --- コース・距離適性 ---
            aptitude_feats = _aptitude_features(c, horse_id, venue, surface, distance, target_date)

            # --- 騎手乗り替わり・前走比較特徴量 ---
            combo_feats = _combo_features(c, horse_id, jockey_id, trainer_id,
                                           distance, surface, weight_carried or 55.0, target_date)

            # --- 騎手直近フォーム ---
            jk_recent = _jockey_recent_form(c, jockey_id, target_date)

            # --- レース特徴量 ---
            race_number = race[3]
            row = {
                "race_id": race_id,
                "horse_id": horse_id,
                "horse_number": horse_number,
                "finish_position": finish_position,
                "label": label,
                # レース情報
                "venue_code": VENUE_CODE.get(venue, 0),
                "class_level": CLASS_LEVEL.get(race_class, 4),
                "distance": distance,
                "surface_turf": 1 if surface == "芝" else 0,
                "direction_right": 1 if direction == "右" else 0,
                "direction_left": 1 if direction == "左" else 0,
                "condition_good": 1 if track_condition == "良" else 0,
                "condition_yielding": 1 if track_condition == "稍重" else 0,
                "condition_heavy": 1 if track_condition in ("重", "不良") else 0,
                "head_count": head_count or 14,
                "race_number": race_number or 6,
                # 馬情報
                "post_position": post_position,
                "weight_carried": weight_carried or 55.0,
                "horse_weight": horse_weight or 470,
                "weight_change": weight_change or 0,
                "sex_male": 1 if sex == "牡" else 0,
                "sex_female": 1 if sex == "牝" else 0,
                "age": age,
                # オッズ（バックテスト時は実オッズ使用、予測時は直前オッズ）
                "odds_win": odds_win or 50.0,
                "popularity": popularity or 10,
                "log_odds": np.log1p(odds_win or 50.0),
            }
            row.update(past_feats)
            row.update(jockey_feats)
            row.update(trainer_feats)
            row.update(aptitude_feats)
            row.update(combo_feats)
            row.update(jk_recent)

            # --- クラス昇降 ---
            last_cls = past_feats.get("last_class_level", 4)
            current_cls = CLASS_LEVEL.get(race_class, 4)
            row["class_change"] = current_cls - last_cls
            row["is_class_up"] = 1 if current_cls > last_cls else 0
            row["is_class_down"] = 1 if current_cls < last_cls else 0

            # --- 展開予測 ---
            row["n_front_runners"] = n_front_runners
            row["front_ratio"] = front_ratio
            row["pace_pressure"] = pace_pressure
            # この馬が先行馬かどうか
            ep = past_feats.get("early_pace", 8.0)
            row["is_front_runner"] = 1 if ep <= 3 else 0
            row["is_closer"] = 1 if ep >= 8 else 0

            all_rows.append(row)

    return pd.DataFrame(all_rows)


def build_features_for_race(conn, target_date, race_id):
    """1レース分の特徴量のみ構築（ライブモード用の軽量版）"""
    c = conn.cursor()
    c.execute("""SELECT race_id, date, venue, race_number, class, distance, surface,
                        direction, track_condition, weather, head_count
                 FROM races WHERE race_id = ? AND surface IN ('芝', 'ダート')""", (race_id,))
    race = c.fetchone()
    if not race:
        return None

    all_rows = []
    race_date = race[1]
    venue = race[2]
    race_class = race[4]
    distance = race[5]
    surface = race[6]
    direction = race[7]
    track_condition = race[8]
    weather = race[9]
    head_count = race[10]

    c.execute("""SELECT horse_id, jockey_id, trainer_id, post_position, horse_number,
                        weight_carried, horse_weight, weight_change, finish_position,
                        odds_win, popularity, sex_age, last_3f
                 FROM results WHERE race_id = ?""", (race_id,))
    entries = c.fetchall()

    pace_positions = []
    for entry in entries:
        eid = entry[0]
        c.execute("""
            SELECT r.passing FROM results r JOIN races ra ON r.race_id = ra.race_id
            WHERE r.horse_id = ? AND ra.date < ? AND r.finish_position > 0
                  AND ra.surface IN ('芝', 'ダート')
            ORDER BY ra.date DESC LIMIT 1
        """, (eid, target_date))
        prow = c.fetchone()
        if prow and prow[0]:
            try:
                pp = int(prow[0].split("-")[0])
                pace_positions.append(pp)
            except (ValueError, IndexError):
                pass

    n_front_runners = sum(1 for p in pace_positions if p <= 3)
    front_ratio = n_front_runners / len(entries) if entries else 0.3
    pace_pressure = min(1.0, n_front_runners / 4)

    for entry in entries:
        horse_id_e = entry[0]
        jockey_id = entry[1]
        trainer_id = entry[2]
        post_position = entry[3]
        horse_number = entry[4]
        weight_carried = entry[5]
        horse_weight = entry[6]
        weight_change = entry[7]
        finish_position = entry[8]
        odds_win = entry[9]
        popularity = entry[10]
        sex_age = entry[11] or ""
        last_3f_actual = entry[12]

        label = 1 if finish_position > 0 and finish_position <= 3 else 0
        sex = sex_age[0] if sex_age else ""
        try:
            age = int(sex_age[1:]) if len(sex_age) > 1 else 0
        except ValueError:
            age = 0

        past_feats = _horse_past_features(c, horse_id_e, target_date)
        jockey_feats = _jockey_features(c, jockey_id, venue, surface, target_date)
        trainer_feats = _trainer_features(c, trainer_id, target_date)
        aptitude_feats = _aptitude_features(c, horse_id_e, venue, surface, distance, target_date)
        combo_feats = _combo_features(c, horse_id_e, jockey_id, trainer_id,
                                       distance, surface, weight_carried or 55.0, target_date)
        jk_recent = _jockey_recent_form(c, jockey_id, target_date)

        race_number = race[3]
        row = {
            "race_id": race_id,
            "horse_id": horse_id_e,
            "horse_number": horse_number,
            "finish_position": finish_position,
            "label": label,
            "venue_code": VENUE_CODE.get(venue, 0),
            "class_level": CLASS_LEVEL.get(race_class, 4),
            "distance": distance,
            "surface_turf": 1 if surface == "芝" else 0,
            "direction_right": 1 if direction == "右" else 0,
            "direction_left": 1 if direction == "左" else 0,
            "condition_good": 1 if track_condition == "良" else 0,
            "condition_yielding": 1 if track_condition == "稍重" else 0,
            "condition_heavy": 1 if track_condition in ("重", "不良") else 0,
            "head_count": head_count or 14,
            "race_number": race_number or 6,
            "post_position": post_position,
            "weight_carried": weight_carried or 55.0,
            "horse_weight": horse_weight or 470,
            "weight_change": weight_change or 0,
            "sex_male": 1 if sex == "牡" else 0,
            "sex_female": 1 if sex == "牝" else 0,
            "age": age,
            "odds_win": odds_win or 50.0,
            "popularity": popularity or 10,
            "log_odds": np.log1p(odds_win or 50.0),
        }
        row.update(past_feats)
        row.update(jockey_feats)
        row.update(trainer_feats)
        row.update(aptitude_feats)
        row.update(combo_feats)
        row.update(jk_recent)

        last_cls = past_feats.get("last_class_level", 4)
        current_cls = CLASS_LEVEL.get(race_class, 4)
        row["class_change"] = current_cls - last_cls
        row["is_class_up"] = 1 if current_cls > last_cls else 0
        row["is_class_down"] = 1 if current_cls < last_cls else 0

        row["n_front_runners"] = n_front_runners
        row["front_ratio"] = front_ratio
        row["pace_pressure"] = pace_pressure
        ep = past_feats.get("early_pace", 8.0)
        row["is_front_runner"] = 1 if ep <= 3 else 0
        row["is_closer"] = 1 if ep >= 8 else 0

        all_rows.append(row)

    return pd.DataFrame(all_rows)


def _horse_past_features(cursor, horse_id, before_date):
    """馬の過去成績から特徴量を生成"""
    cursor.execute("""
        SELECT r.finish_position, r.last_3f, r.odds_win, r.finish_time,
               ra.head_count, ra.distance, ra.surface, ra.class, ra.date,
               r.passing, r.weight_carried, r.margin
        FROM results r
        JOIN races ra ON r.race_id = ra.race_id
        WHERE r.horse_id = ? AND ra.date < ? AND r.finish_position > 0
              AND ra.surface IN ('芝', 'ダート')
        ORDER BY ra.date DESC
        LIMIT 10
    """, (horse_id, before_date))
    rows = cursor.fetchall()

    feats = {}
    if not rows:
        feats["past_runs"] = 0
        feats["avg_finish_rate_5"] = 0.5
        feats["avg_finish_rate_3"] = 0.5
        feats["best_finish_rate"] = 0.5
        feats["avg_last_3f"] = 35.0
        feats["best_last_3f"] = 35.0
        feats["win_count"] = 0
        feats["top3_count"] = 0
        feats["top3_rate"] = 0.0
        feats["win_rate"] = 0.0
        feats["days_since_last"] = 180
        feats["last_finish_rate"] = 0.5
        feats["last_odds"] = 30.0
        feats["avg_speed"] = 0.0
        feats["form_trend"] = 0.0
        feats["early_pace"] = 0.0
        # 新特徴量のデフォルト
        feats["relative_speed_avg"] = 0.0
        feats["pace_position_last"] = 0.0
        feats["late_charge"] = 0.0
        feats["margin_score_avg"] = 0.0
        feats["margin_score_last"] = 0.0
        feats["last_class_level"] = 4
        feats["consistency"] = 0.0
        feats["best_speed"] = 0.0
        feats["last_3f_rank_avg"] = 0.5
        return feats

    feats["past_runs"] = len(rows)

    # 着順を頭数で正規化した着率
    finish_rates = []
    for r in rows:
        hc = r[4] or 14
        fp = r[0]
        rate = (hc - fp) / (hc - 1) if hc > 1 else 0.5
        finish_rates.append(max(0, min(1, rate)))

    feats["avg_finish_rate_5"] = np.mean(finish_rates[:5])
    feats["avg_finish_rate_3"] = np.mean(finish_rates[:3])
    feats["best_finish_rate"] = max(finish_rates)
    feats["last_finish_rate"] = finish_rates[0]

    # 上がり3F
    last_3fs = [r[1] for r in rows if r[1] and r[1] > 0]
    feats["avg_last_3f"] = np.mean(last_3fs) if last_3fs else 35.0
    feats["best_last_3f"] = min(last_3fs) if last_3fs else 35.0

    # 勝率・連対率
    feats["win_count"] = sum(1 for r in rows if r[0] == 1)
    feats["top3_count"] = sum(1 for r in rows if r[0] <= 3)
    feats["top3_rate"] = feats["top3_count"] / len(rows)
    feats["win_rate"] = feats["win_count"] / len(rows)

    # ローテーション
    try:
        last_date = datetime.strptime(rows[0][8], "%Y-%m-%d")
        target = datetime.strptime(before_date, "%Y-%m-%d")
        feats["days_since_last"] = (target - last_date).days
    except (ValueError, TypeError):
        feats["days_since_last"] = 180

    # 前走オッズ
    feats["last_odds"] = rows[0][2] if rows[0][2] else 30.0

    # スピード指数（m/s）
    speeds = []
    for r in rows:
        if r[3] and r[3] > 0 and r[5] and r[5] > 0:
            speed = r[5] / r[3]
            speeds.append(speed)
    feats["avg_speed"] = np.mean(speeds) if speeds else 0.0
    feats["best_speed"] = max(speeds) if speeds else 0.0

    # 調子トレンド
    if len(finish_rates) >= 3:
        feats["form_trend"] = finish_rates[0] - finish_rates[2]
    else:
        feats["form_trend"] = 0.0

    # 位置取り（通過順の平均）
    positions = []
    last_positions = []  # 最終コーナーの位置
    for r in rows[:5]:
        passing = r[9]
        if passing:
            try:
                parts = passing.split("-")
                first_pos = int(parts[0])
                positions.append(first_pos)
                last_pos = int(parts[-1])
                last_positions.append(last_pos)
            except (ValueError, IndexError):
                pass
    feats["early_pace"] = np.mean(positions) if positions else 8.0
    feats["pace_position_last"] = np.mean(last_positions) if last_positions else 8.0

    # ===== 新特徴量 =====

    # 1. 相対スピード指数（同レース内での相対タイム）
    #    各レースの勝ちタイムとの差で正規化
    relative_speeds = []
    for r in rows:
        if r[3] and r[3] > 0 and r[5] and r[5] > 0:
            # 距離で正規化したスピード
            speed = r[5] / r[3]
            relative_speeds.append(speed)
    feats["relative_speed_avg"] = np.mean(relative_speeds) if relative_speeds else 0.0

    # 2. 追い込み力（前半位置→最終着順の改善度）
    charges = []
    for r in rows[:5]:
        passing = r[9]
        fp = r[0]
        hc = r[4] or 14
        if passing:
            try:
                first_pos = int(passing.split("-")[0])
                # 前半位置から着順への改善（正=追い込み、負=先行失速）
                charge = (first_pos - fp) / hc if hc > 0 else 0
                charges.append(charge)
            except (ValueError, IndexError):
                pass
    feats["late_charge"] = np.mean(charges) if charges else 0.0

    # 3. 着差スコア（着順だけでなく「どれだけ負けたか」）
    margin_scores = []
    for r in rows:
        margin = r[11] or ""
        fp = r[0]
        if fp == 1:
            margin_scores.append(1.0)  # 勝ち
        elif margin in ("ハナ", "アタマ"):
            margin_scores.append(0.9)  # 僅差
        elif margin in ("クビ",):
            margin_scores.append(0.85)
        elif margin.replace(".", "").replace("/", "").isdigit() or margin.startswith("1"):
            # 数値着差: 小さいほど良い
            try:
                # "1/2", "1.1/2" 等のパース
                val = margin.replace(" ", "")
                if "/" in val:
                    parts = val.split("/")
                    if "." in parts[0]:
                        # "1.1/2" → 1.5
                        int_frac = parts[0].split(".")
                        num_val = float(int_frac[0]) + float(int_frac[1]) / float(parts[1])
                    else:
                        num_val = float(parts[0]) / float(parts[1])
                else:
                    num_val = float(val)
                margin_scores.append(max(0.3, 0.8 - num_val * 0.1))
            except (ValueError, IndexError):
                margin_scores.append(0.5)
        elif margin in ("大差",):
            margin_scores.append(0.1)
        else:
            margin_scores.append(0.5)

    feats["margin_score_avg"] = np.mean(margin_scores) if margin_scores else 0.5
    feats["margin_score_last"] = margin_scores[0] if margin_scores else 0.5

    # 4. 前走クラスレベル（昇降級判定用）
    feats["last_class_level"] = CLASS_LEVEL.get(rows[0][7], 4)

    # 5. 安定度（着率の標準偏差の逆数 = 安定しているほど高い）
    if len(finish_rates) >= 3:
        std = np.std(finish_rates[:5])
        feats["consistency"] = 1.0 / (1.0 + std * 5)  # 0~1に正規化
    else:
        feats["consistency"] = 0.5

    # 6. 上がり3F順位の平均（レース内の相対的な末脚評価）
    #    上がり3Fそのものはレースのペースに左右されるが、
    #    同レース内の順位なら相対的に末脚を評価できる
    #    → 実際のレース内順位はDBにないので、頭数に対する着順で代用
    feats["last_3f_rank_avg"] = 0.5
    if last_3fs:
        # 上がり3Fが良い（小さい）ほど高スコア
        l3f_scores = [(36.0 - l3f) / 4.0 for l3f in last_3fs]  # 32秒=1.0, 36秒=0.0
        feats["last_3f_rank_avg"] = max(0, min(1, np.mean(l3f_scores)))

    return feats


def _jockey_features(cursor, jockey_id, venue, surface, before_date):
    """騎手の特徴量"""
    feats = {}

    if not jockey_id:
        feats["jk_win_rate"] = 0.08
        feats["jk_top3_rate"] = 0.25
        feats["jk_rides"] = 0
        feats["jk_venue_win_rate"] = 0.08
        feats["jk_venue_top3_rate"] = 0.25
        return feats

    cursor.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END)
        FROM results r JOIN races ra ON r.race_id = ra.race_id
        WHERE r.jockey_id = ? AND ra.date < ? AND r.finish_position > 0
              AND ra.surface IN ('芝', 'ダート')
    """, (jockey_id, before_date))
    row = cursor.fetchone()
    rides = row[0] or 0
    wins = row[1] or 0
    top3 = row[2] or 0

    prior = 50
    feats["jk_rides"] = rides
    feats["jk_win_rate"] = (wins + prior * 0.08) / (rides + prior)
    feats["jk_top3_rate"] = (top3 + prior * 0.25) / (rides + prior)

    # 場所別
    cursor.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END)
        FROM results r JOIN races ra ON r.race_id = ra.race_id
        WHERE r.jockey_id = ? AND ra.date < ? AND ra.venue = ? AND ra.surface = ?
              AND r.finish_position > 0
    """, (jockey_id, before_date, venue, surface))
    row = cursor.fetchone()
    v_rides = row[0] or 0
    v_wins = row[1] or 0
    v_top3 = row[2] or 0

    feats["jk_venue_win_rate"] = (v_wins + 10 * 0.08) / (v_rides + 10)
    feats["jk_venue_top3_rate"] = (v_top3 + 10 * 0.25) / (v_rides + 10)

    return feats


def _trainer_features(cursor, trainer_id, before_date):
    """調教師の特徴量"""
    feats = {}

    if not trainer_id:
        feats["tr_win_rate"] = 0.08
        feats["tr_top3_rate"] = 0.25
        feats["tr_rides"] = 0
        return feats

    cursor.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END)
        FROM results r JOIN races ra ON r.race_id = ra.race_id
        WHERE r.trainer_id = ? AND ra.date < ? AND r.finish_position > 0
              AND ra.surface IN ('芝', 'ダート')
    """, (trainer_id, before_date))
    row = cursor.fetchone()
    rides = row[0] or 0
    wins = row[1] or 0
    top3 = row[2] or 0

    prior = 50
    feats["tr_rides"] = rides
    feats["tr_win_rate"] = (wins + prior * 0.08) / (rides + prior)
    feats["tr_top3_rate"] = (top3 + prior * 0.25) / (rides + prior)

    return feats


def _combo_features(cursor, horse_id, jockey_id, trainer_id,
                    distance, surface, weight_carried, before_date):
    """騎手乗り替わり・前走比較・コンビ成績の特徴量"""
    feats = {}

    # 前走情報を取得
    cursor.execute("""
        SELECT r.jockey_id, ra.distance, ra.surface, r.weight_carried
        FROM results r JOIN races ra ON r.race_id = ra.race_id
        WHERE r.horse_id = ? AND ra.date < ? AND r.finish_position > 0
              AND ra.surface IN ('芝', 'ダート')
        ORDER BY ra.date DESC LIMIT 1
    """, (horse_id, before_date))
    last = cursor.fetchone()

    if last:
        feats["jockey_change"] = 0 if last[0] == jockey_id else 1
        feats["distance_change"] = distance - (last[1] or distance)
        feats["surface_change"] = 0 if (last[2] or surface) == surface else 1
        feats["weight_carried_diff"] = weight_carried - (last[3] or weight_carried)
    else:
        feats["jockey_change"] = 0
        feats["distance_change"] = 0
        feats["surface_change"] = 0
        feats["weight_carried_diff"] = 0.0

    # 騎手×馬のコンビ成績
    if jockey_id and horse_id:
        cursor.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END)
            FROM results r JOIN races ra ON r.race_id = ra.race_id
            WHERE r.horse_id = ? AND r.jockey_id = ? AND ra.date < ?
                  AND r.finish_position > 0
        """, (horse_id, jockey_id, before_date))
        row = cursor.fetchone()
        combo_rides = row[0] or 0
        combo_top3 = row[1] or 0
        feats["jk_horse_rides"] = combo_rides
        feats["jk_horse_top3_rate"] = (combo_top3 + 0.25) / (combo_rides + 1)
    else:
        feats["jk_horse_rides"] = 0
        feats["jk_horse_top3_rate"] = 0.25

    # 調教師×騎手のコンビ成績
    if trainer_id and jockey_id:
        cursor.execute("""
            SELECT COUNT(*),
                   SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END)
            FROM results r JOIN races ra ON r.race_id = ra.race_id
            WHERE r.trainer_id = ? AND r.jockey_id = ? AND ra.date < ?
                  AND r.finish_position > 0 AND ra.surface IN ('芝', 'ダート')
        """, (trainer_id, jockey_id, before_date))
        row = cursor.fetchone()
        tj_rides = row[0] or 0
        tj_top3 = row[1] or 0
        feats["trainer_jockey_rides"] = tj_rides
        feats["trainer_jockey_top3_rate"] = (tj_top3 + 5 * 0.25) / (tj_rides + 5)
    else:
        feats["trainer_jockey_rides"] = 0
        feats["trainer_jockey_top3_rate"] = 0.25

    return feats


def _jockey_recent_form(cursor, jockey_id, before_date):
    """騎手の直近30日のフォーム"""
    feats = {}
    if not jockey_id:
        feats["jk_recent_win_rate"] = 0.08
        feats["jk_recent_top3_rate"] = 0.25
        return feats

    try:
        target = datetime.strptime(before_date, "%Y-%m-%d")
        date_30 = (target - timedelta(days=30)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        feats["jk_recent_win_rate"] = 0.08
        feats["jk_recent_top3_rate"] = 0.25
        return feats

    cursor.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END)
        FROM results r JOIN races ra ON r.race_id = ra.race_id
        WHERE r.jockey_id = ? AND ra.date BETWEEN ? AND ?
              AND r.finish_position > 0 AND ra.surface IN ('芝', 'ダート')
    """, (jockey_id, date_30, before_date))
    row = cursor.fetchone()
    rides = row[0] or 0
    wins = row[1] or 0
    top3 = row[2] or 0

    prior = 10
    feats["jk_recent_win_rate"] = (wins + prior * 0.08) / (rides + prior)
    feats["jk_recent_top3_rate"] = (top3 + prior * 0.25) / (rides + prior)

    return feats


def _aptitude_features(cursor, horse_id, venue, surface, distance, before_date):
    """コース・距離適性の特徴量"""
    feats = {}

    # 同コース（場所+馬場）での成績
    cursor.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END),
               AVG(CASE WHEN ra.head_count > 1
                   THEN CAST(ra.head_count - r.finish_position AS REAL) / (ra.head_count - 1)
                   ELSE 0.5 END)
        FROM results r JOIN races ra ON r.race_id = ra.race_id
        WHERE r.horse_id = ? AND ra.date < ? AND ra.venue = ? AND ra.surface = ?
              AND r.finish_position > 0
    """, (horse_id, before_date, venue, surface))
    row = cursor.fetchone()
    feats["course_runs"] = row[0] or 0
    feats["course_top3"] = row[1] or 0
    feats["course_avg_rate"] = row[2] if row[2] is not None else 0.5

    # 同距離帯（±200m）での成績
    cursor.execute("""
        SELECT COUNT(*),
               SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END),
               AVG(CASE WHEN ra.head_count > 1
                   THEN CAST(ra.head_count - r.finish_position AS REAL) / (ra.head_count - 1)
                   ELSE 0.5 END)
        FROM results r JOIN races ra ON r.race_id = ra.race_id
        WHERE r.horse_id = ? AND ra.date < ? AND ra.surface = ?
              AND ABS(ra.distance - ?) <= 200
              AND r.finish_position > 0
    """, (horse_id, before_date, surface, distance))
    row = cursor.fetchone()
    feats["dist_runs"] = row[0] or 0
    feats["dist_top3"] = row[1] or 0
    feats["dist_avg_rate"] = row[2] if row[2] is not None else 0.5

    # 同馬場状態での成績（芝/ダート × 良/稍重/重不良）
    cursor.execute("""
        SELECT COUNT(*),
               AVG(CASE WHEN ra.head_count > 1
                   THEN CAST(ra.head_count - r.finish_position AS REAL) / (ra.head_count - 1)
                   ELSE 0.5 END)
        FROM results r JOIN races ra ON r.race_id = ra.race_id
        WHERE r.horse_id = ? AND ra.date < ? AND ra.surface = ?
              AND r.finish_position > 0
    """, (horse_id, before_date, surface))
    row = cursor.fetchone()
    feats["surface_runs"] = row[0] or 0
    feats["surface_avg_rate"] = row[1] if row[1] is not None else 0.5

    return feats


# ============================================================
# 学習データ構築
# ============================================================

def build_training_data(conn, start_date, end_date):
    """学習データを日付ごとに構築"""
    c = conn.cursor()
    c.execute("""SELECT DISTINCT date FROM races
                 WHERE date BETWEEN ? AND ? AND surface IN ('芝', 'ダート')
                 ORDER BY date""", (start_date, end_date))
    dates = [row[0] for row in c.fetchall()]

    print(f"学習データ構築: {start_date} 〜 {end_date} ({len(dates)}日)")
    all_dfs = []

    for i, date in enumerate(dates):
        df = build_features_for_date(conn, date)
        if not df.empty:
            all_dfs.append(df)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(dates)} 完了...")

    if not all_dfs:
        return pd.DataFrame()

    result = pd.concat(all_dfs, ignore_index=True)
    print(f"  合計: {len(result)}行, {len(result.columns)}列")
    return result


# ============================================================
# モデル学習
# ============================================================

# オッズ・人気を含むフル特徴量（市場追従型）
FEATURE_COLS_FULL = [
    "venue_code", "class_level", "distance", "surface_turf",
    "direction_right", "direction_left",
    "condition_good", "condition_yielding", "condition_heavy",
    "head_count", "race_number", "post_position", "weight_carried",
    "horse_weight", "weight_change",
    "sex_male", "sex_female", "age",
    "odds_win", "popularity", "log_odds",
    # 馬の過去成績
    "past_runs", "avg_finish_rate_5", "avg_finish_rate_3",
    "best_finish_rate", "last_finish_rate",
    "avg_last_3f", "best_last_3f",
    "win_count", "top3_count", "top3_rate", "win_rate",
    "days_since_last", "last_odds",
    "avg_speed", "form_trend", "early_pace",
    # スピード・末脚・着差
    "best_speed", "relative_speed_avg",
    "pace_position_last", "late_charge",
    "margin_score_avg", "margin_score_last",
    "last_3f_rank_avg", "consistency",
    # クラス昇降
    "last_class_level", "class_change", "is_class_up", "is_class_down",
    # 展開予測
    "n_front_runners", "front_ratio", "pace_pressure",
    "is_front_runner", "is_closer",
    # 騎手乗り替わり・前走比較
    "jockey_change", "distance_change", "surface_change", "weight_carried_diff",
    # 騎手×馬・調教師×騎手コンビ
    "jk_horse_rides", "jk_horse_top3_rate",
    "trainer_jockey_rides", "trainer_jockey_top3_rate",
    # 騎手直近フォーム
    "jk_recent_win_rate", "jk_recent_top3_rate",
    # 騎手
    "jk_win_rate", "jk_top3_rate", "jk_rides",
    "jk_venue_win_rate", "jk_venue_top3_rate",
    # 調教師
    "tr_win_rate", "tr_top3_rate", "tr_rides",
    # 適性
    "course_runs", "course_top3", "course_avg_rate",
    "dist_runs", "dist_top3", "dist_avg_rate",
    "surface_runs", "surface_avg_rate",
]

# オッズ・人気を除外した特徴量（独自評価型 - 市場の歪みを発見する）
FEATURE_COLS_NO_ODDS = [
    "venue_code", "class_level", "distance", "surface_turf",
    "direction_right", "direction_left",
    "condition_good", "condition_yielding", "condition_heavy",
    "head_count", "race_number", "post_position", "weight_carried",
    "horse_weight", "weight_change",
    "sex_male", "sex_female", "age",
    # 馬の過去成績（前走オッズも除外）
    "past_runs", "avg_finish_rate_5", "avg_finish_rate_3",
    "best_finish_rate", "last_finish_rate",
    "avg_last_3f", "best_last_3f",
    "win_count", "top3_count", "top3_rate", "win_rate",
    "days_since_last",
    "avg_speed", "form_trend", "early_pace",
    # スピード・末脚・着差
    "best_speed", "relative_speed_avg",
    "pace_position_last", "late_charge",
    "margin_score_avg", "margin_score_last",
    "last_3f_rank_avg", "consistency",
    "last_class_level", "class_change", "is_class_up", "is_class_down",
    "n_front_runners", "front_ratio", "pace_pressure",
    "is_front_runner", "is_closer",
    # 騎手乗り替わり・前走比較
    "jockey_change", "distance_change", "surface_change", "weight_carried_diff",
    # 騎手×馬・調教師×騎手コンビ
    "jk_horse_rides", "jk_horse_top3_rate",
    "trainer_jockey_rides", "trainer_jockey_top3_rate",
    # 騎手直近フォーム
    "jk_recent_win_rate", "jk_recent_top3_rate",
    # 騎手
    "jk_win_rate", "jk_top3_rate", "jk_rides",
    "jk_venue_win_rate", "jk_venue_top3_rate",
    # 調教師
    "tr_win_rate", "tr_top3_rate", "tr_rides",
    # 適性
    "course_runs", "course_top3", "course_avg_rate",
    "dist_runs", "dist_top3", "dist_avg_rate",
    "surface_runs", "surface_avg_rate",
]

# デフォルト: フル特徴量を使用（予測精度重視）
# バリュー発見はpredictor側でモデル順位vs人気の乖離を使う
FEATURE_COLS = FEATURE_COLS_FULL


def train_model(conn, train_start="2022-01-01", train_end="2024-12-31"):
    """LightGBMモデルを学習"""
    print("=" * 60)
    print("v2 LightGBMモデル学習")
    print("=" * 60)

    # 学習データ構築
    df = build_training_data(conn, train_start, train_end)
    if df.empty:
        print("学習データがありません")
        return None

    X = df[FEATURE_COLS].values
    y = df["label"].values
    groups = df["race_id"].values

    print(f"\n学習データ: {len(X)}行, 正例率: {y.mean():.3f}")

    # LightGBMパラメータ
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
        "verbose": -1,
        "n_jobs": -1,
    }

    # GroupKFoldで検証（同一レースが分割されないように）
    unique_races = np.unique(groups)
    race_to_group = {r: i for i, r in enumerate(unique_races)}
    group_ids = np.array([race_to_group[r] for r in groups])

    gkf = GroupKFold(n_splits=5)
    cv_scores = []

    print("\nクロスバリデーション中...")
    for fold, (train_idx, val_idx) in enumerate(gkf.split(X, y, group_ids)):
        X_tr, X_val = X[train_idx], X[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]

        dtrain = lgb.Dataset(X_tr, label=y_tr)
        dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)

        model = lgb.train(
            params, dtrain,
            num_boost_round=500,
            valid_sets=[dval],
            callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
        )

        val_pred = model.predict(X_val)

        # レース単位での評価: 3着以内的中率
        val_races = groups[val_idx]
        unique_val_races = np.unique(val_races)
        hits = 0
        total = 0
        for race_id in unique_val_races:
            mask = val_races == race_id
            preds = val_pred[mask]
            labels = y_val[mask]
            if len(preds) < 3 or labels.sum() == 0:
                continue
            # 上位3頭に実際の3着内馬が何頭いるか
            top3_idx = np.argsort(preds)[-3:]
            hits += labels[top3_idx].sum()
            total += min(3, int(labels.sum()))

        accuracy = hits / total if total > 0 else 0
        cv_scores.append(accuracy)
        print(f"  Fold {fold+1}: 3着内的中率 {accuracy:.3f} (best_iter: {model.best_iteration})")

    print(f"\n  CV平均 3着内的中率: {np.mean(cv_scores):.3f} ± {np.std(cv_scores):.3f}")

    # 全データで最終モデル学習
    print("\n最終モデル学習中...")
    dtrain_full = lgb.Dataset(X, label=y)
    final_model = lgb.train(
        params, dtrain_full,
        num_boost_round=400,
    )

    # 特徴量重要度
    importance = final_model.feature_importance(importance_type="gain")
    feat_imp = sorted(zip(FEATURE_COLS, importance), key=lambda x: x[1], reverse=True)
    print("\n【特徴量重要度 TOP15】")
    for feat, imp in feat_imp[:15]:
        print(f"  {feat:>25s}: {imp:.1f}")

    # モデル保存
    model_data = {
        "model": final_model,
        "feature_cols": FEATURE_COLS,
        "train_start": train_start,
        "train_end": train_end,
        "cv_scores": cv_scores,
    }
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(model_data, f)
    print(f"\nモデル保存: {MODEL_PATH}")

    return final_model


def load_model():
    """保存済みモデルを読み込み"""
    with open(MODEL_PATH, "rb") as f:
        data = pickle.load(f)
    return data["model"], data["feature_cols"]


# ============================================================
# 予測（predictor.pyとの統合用）
# ============================================================

def predict_race(conn, race_id, model=None):
    """1レースの3着内確率を予測"""
    if model is None:
        model, _ = load_model()

    c = conn.cursor()
    c.execute("SELECT date FROM races WHERE race_id = ?", (race_id,))
    row = c.fetchone()
    if not row:
        return []

    race_date = row[0]
    df = build_features_for_date(conn, race_date)
    if df.empty:
        return []

    df_race = df[df["race_id"] == race_id].copy()
    if df_race.empty:
        return []

    X = df_race[FEATURE_COLS].values
    probs = model.predict(X)

    results = []
    for i, (_, row) in enumerate(df_race.iterrows()):
        results.append({
            "horse_id": row["horse_id"],
            "horse_number": int(row["horse_number"]),
            "prob_top3": probs[i],
            "odds_win": row["odds_win"],
            "popularity": int(row["popularity"]),
        })

    results.sort(key=lambda x: x["prob_top3"], reverse=True)
    return results


def main():
    conn = get_conn()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 model_v2.py train                        # モデル学習 (2022-2024)")
        print("  python3 model_v2.py train 2022-01-01 2024-12-31  # 期間指定学習")
        print("  python3 model_v2.py predict 202503020911          # 1レース予測")
        print("  python3 model_v2.py importance                    # 特徴量重要度表示")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "train":
        start = sys.argv[2] if len(sys.argv) > 2 else "2022-01-01"
        end = sys.argv[3] if len(sys.argv) > 3 else "2024-12-31"
        train_model(conn, start, end)

    elif cmd == "predict":
        race_id = sys.argv[2]
        results = predict_race(conn, race_id)
        c = conn.cursor()
        print(f"{'順位':>4s} {'馬番':>4s} {'馬名':>12s} {'予測確率':>8s} {'オッズ':>6s}")
        for i, r in enumerate(results):
            c.execute("SELECT name FROM horses WHERE horse_id = ?", (r["horse_id"],))
            name = c.fetchone()
            name = name[0] if name else "???"
            print(f"{i+1:>4d} {r['horse_number']:>4d} {name:>12s} "
                  f"{r['prob_top3']:>8.3f} {r['odds_win']:>6.1f}")

    elif cmd == "importance":
        model, feat_cols = load_model()
        importance = model.feature_importance(importance_type="gain")
        feat_imp = sorted(zip(feat_cols, importance), key=lambda x: x[1], reverse=True)
        for feat, imp in feat_imp:
            bar = "█" * int(imp / max(importance) * 40)
            print(f"  {feat:>25s}: {imp:>8.1f} {bar}")

    conn.close()


if __name__ == "__main__":
    main()
