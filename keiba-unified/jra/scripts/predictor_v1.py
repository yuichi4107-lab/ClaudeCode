#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
競馬予想エンジン - スコアリング + LightGBM統合モデル
Steps 4 (スコアリング), 5 (レース選定), 6 (買い目生成)

使用モデル:
  - "v1": 手動スコアリングモデル
  - "v2": LightGBMモデル（v1スコアとブレンド）
"""

import sqlite3
import os
import math
from datetime import datetime, timedelta
from itertools import combinations

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "keiba_live.db")

# === モデル選択 ===
MODEL_VERSION = "v2"  # "v1" or "v2"
V2_BLEND_WEIGHT = 0.7  # v2の予測確率の重み（v1は1-この値）

# === レース選定 ===
QUALITY_THRESHOLD = 0.80  # 絶対評価閾値（年間~750レース = 約25%）
RACE_BUDGET = 5000  # 1レースあたりの予算

# === スコアリングの重み ===
WEIGHTS = {
    "past_perf": 0.25,
    "jockey": 0.15,
    "course": 0.15,
    "distance": 0.10,
    "class_perf": 0.10,
    "rotation": 0.10,
    "post_position": 0.05,
    "trainer": 0.10,
}

# クラスの数値マッピング
CLASS_LEVEL = {
    "新馬": 1, "未勝利": 2, "1勝": 3, "2勝": 4, "3勝": 5,
    "OP": 6, "G3": 7, "G2": 8, "G1": 9,
}

# 距離バケット
def distance_bucket(d):
    if d <= 1400:
        return "sprint"
    elif d <= 1800:
        return "mile"
    elif d <= 2200:
        return "intermediate"
    else:
        return "long"


def get_conn():
    return sqlite3.connect(DB_PATH)


# ============================================================
# Step 4: スコアリングモデル
# ============================================================

def score_all_horses(conn, race_id):
    """レース内の全馬をスコアリングし、スコア降順で返す"""
    c = conn.cursor()

    # レース情報取得
    c.execute("SELECT * FROM races WHERE race_id = ?", (race_id,))
    race_row = c.fetchone()
    if not race_row:
        return []

    race_info = {
        "race_id": race_row[0], "date": race_row[1], "venue": race_row[2],
        "race_number": race_row[3], "name": race_row[4], "class": race_row[5],
        "distance": race_row[6], "surface": race_row[7], "direction": race_row[8],
        "track_condition": race_row[9], "weather": race_row[10], "head_count": race_row[11],
    }

    # 障害レースはスキップ
    if race_info["surface"] in ("障害", ""):
        return []

    before_date = race_info["date"]

    # 出走馬一覧
    c.execute("""SELECT horse_id, jockey_id, trainer_id, post_position, horse_number,
                        weight_carried, horse_weight, weight_change, odds_win, popularity, sex_age
                 FROM results WHERE race_id = ?""", (race_id,))
    entries = c.fetchall()
    if not entries:
        return []

    # 全馬の過去5走を一括取得
    horse_ids = [e[0] for e in entries]
    past_data = _batch_past_performance(conn, horse_ids, before_date)

    # 騎手成績を一括取得
    jockey_ids = [e[1] for e in entries]
    jockey_stats = _batch_jockey_stats(conn, jockey_ids, race_info["venue"],
                                        race_info["surface"], before_date)

    # 調教師成績を一括取得
    trainer_ids = [e[2] for e in entries]
    trainer_stats = _batch_trainer_stats(conn, trainer_ids, before_date)

    # 枠順統計を一括取得
    post_stats = _batch_post_position_stats(conn, race_info["venue"],
                                             race_info["surface"],
                                             race_info["distance"], before_date)

    scored = []
    for entry in entries:
        horse_id, jockey_id, trainer_id = entry[0], entry[1], entry[2]
        post_position, horse_number = entry[3], entry[4]
        odds_win, popularity = entry[8], entry[9]

        # 各指標スコア計算
        s_past = _calc_past_perf_score(past_data.get(horse_id, []))
        s_jockey = _calc_jockey_score(jockey_stats.get(jockey_id, {}))
        s_course = _calc_course_score(past_data.get(horse_id, []),
                                       race_info["venue"], race_info["surface"],
                                       race_info["distance"])
        s_distance = _calc_distance_score(past_data.get(horse_id, []),
                                           race_info["distance"])
        s_class = _calc_class_score(past_data.get(horse_id, []),
                                     race_info["class"])
        s_rotation = _calc_rotation_score(past_data.get(horse_id, []),
                                           before_date)
        s_post = _calc_post_position_score(post_stats, post_position)
        s_trainer = _calc_trainer_score(trainer_stats.get(trainer_id, {}))

        total = (
            WEIGHTS["past_perf"] * s_past
            + WEIGHTS["jockey"] * s_jockey
            + WEIGHTS["course"] * s_course
            + WEIGHTS["distance"] * s_distance
            + WEIGHTS["class_perf"] * s_class
            + WEIGHTS["rotation"] * s_rotation
            + WEIGHTS["post_position"] * s_post
            + WEIGHTS["trainer"] * s_trainer
        )

        # トラック替わり補正
        track_switch = _calc_track_switch_info(
            past_data.get(horse_id, []),
            race_info["surface"],
            entry[6],   # horse_weight (当日 or None)
        )
        total += track_switch["score_adj"]

        scored.append({
            "horse_id": horse_id,
            "horse_number": horse_number,
            "post_position": post_position,
            "jockey_id": jockey_id,
            "trainer_id": trainer_id,
            "odds_win": odds_win,
            "popularity": popularity,
            "total_score": total,
            "scores": {
                "past_perf": s_past, "jockey": s_jockey, "course": s_course,
                "distance": s_distance, "class_perf": s_class,
                "rotation": s_rotation, "post_position": s_post, "trainer": s_trainer,
            },
            "track_switch": track_switch,
        })

    scored.sort(key=lambda x: x["total_score"], reverse=True)
    return scored


# --- バッチ取得 ---

def _batch_past_performance(conn, horse_ids, before_date):
    """全馬の過去走を一括取得（最大10走）"""
    if not horse_ids:
        return {}
    c = conn.cursor()
    placeholders = ",".join("?" * len(horse_ids))
    c.execute(f"""
        SELECT r.horse_id, ra.date, r.finish_position, r.last_3f, r.odds_win,
               ra.head_count, ra.venue, ra.surface, ra.distance, ra.class,
               r.finish_time, r.passing, ra.race_id, r.horse_weight
        FROM results r
        JOIN races ra ON r.race_id = ra.race_id
        WHERE r.horse_id IN ({placeholders})
          AND ra.date < ?
          AND r.finish_position > 0
          AND ra.surface IN ('芝', 'ダート')
        ORDER BY r.horse_id, ra.date DESC
    """, horse_ids + [before_date])

    result = {}
    counts = {}
    for row in c.fetchall():
        hid = row[0]
        if hid not in result:
            result[hid] = []
            counts[hid] = 0
        if counts[hid] < 10:  # 最大10走保持（コース適性等で使う）
            result[hid].append({
                "date": row[1], "finish_position": row[2], "last_3f": row[3],
                "odds_win": row[4], "head_count": row[5], "venue": row[6],
                "surface": row[7], "distance": row[8], "class": row[9],
                "finish_time": row[10], "passing": row[11], "race_id": row[12],
                "horse_weight": row[13],
            })
            counts[hid] += 1
    return result


def _batch_jockey_stats(conn, jockey_ids, venue, surface, before_date):
    """騎手成績を一括集計"""
    if not jockey_ids:
        return {}
    c = conn.cursor()
    unique_ids = list(set(jid for jid in jockey_ids if jid))
    if not unique_ids:
        return {}
    placeholders = ",".join("?" * len(unique_ids))

    # 全体成績
    c.execute(f"""
        SELECT r.jockey_id,
               COUNT(*) as rides,
               SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END) as top3
        FROM results r
        JOIN races ra ON r.race_id = ra.race_id
        WHERE r.jockey_id IN ({placeholders})
          AND ra.date < ?
          AND r.finish_position > 0
          AND ra.surface IN ('芝', 'ダート')
        GROUP BY r.jockey_id
    """, unique_ids + [before_date])

    stats = {}
    for row in c.fetchall():
        stats[row[0]] = {"rides": row[1], "wins": row[2], "top3": row[3],
                          "venue_rides": 0, "venue_wins": 0, "venue_top3": 0}

    # 場所別成績
    c.execute(f"""
        SELECT r.jockey_id,
               COUNT(*) as rides,
               SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END) as top3
        FROM results r
        JOIN races ra ON r.race_id = ra.race_id
        WHERE r.jockey_id IN ({placeholders})
          AND ra.date < ?
          AND ra.venue = ?
          AND ra.surface = ?
          AND r.finish_position > 0
        GROUP BY r.jockey_id
    """, unique_ids + [before_date, venue, surface])

    for row in c.fetchall():
        if row[0] in stats:
            stats[row[0]].update({
                "venue_rides": row[1], "venue_wins": row[2], "venue_top3": row[3],
            })

    return stats


def _batch_trainer_stats(conn, trainer_ids, before_date):
    """調教師成績を一括集計"""
    if not trainer_ids:
        return {}
    c = conn.cursor()
    unique_ids = list(set(tid for tid in trainer_ids if tid))
    if not unique_ids:
        return {}
    placeholders = ",".join("?" * len(unique_ids))

    c.execute(f"""
        SELECT r.trainer_id,
               COUNT(*) as rides,
               SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END) as top3
        FROM results r
        JOIN races ra ON r.race_id = ra.race_id
        WHERE r.trainer_id IN ({placeholders})
          AND ra.date < ?
          AND r.finish_position > 0
          AND ra.surface IN ('芝', 'ダート')
        GROUP BY r.trainer_id
    """, unique_ids + [before_date])

    stats = {}
    for row in c.fetchall():
        stats[row[0]] = {"rides": row[1], "wins": row[2], "top3": row[3]}
    return stats


def _batch_post_position_stats(conn, venue, surface, distance, before_date):
    """枠順別の成績を集計"""
    c = conn.cursor()
    dist_bucket = distance_bucket(distance)

    if dist_bucket == "sprint":
        dist_min, dist_max = 1000, 1400
    elif dist_bucket == "mile":
        dist_min, dist_max = 1401, 1800
    elif dist_bucket == "intermediate":
        dist_min, dist_max = 1801, 2200
    else:
        dist_min, dist_max = 2201, 4000

    c.execute("""
        SELECT r.post_position,
               COUNT(*) as rides,
               SUM(CASE WHEN r.finish_position = 1 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN r.finish_position <= 3 THEN 1 ELSE 0 END) as top3
        FROM results r
        JOIN races ra ON r.race_id = ra.race_id
        WHERE ra.venue = ?
          AND ra.surface = ?
          AND ra.distance BETWEEN ? AND ?
          AND ra.date < ?
          AND r.finish_position > 0
        GROUP BY r.post_position
    """, (venue, surface, dist_min, dist_max, before_date))

    stats = {}
    for row in c.fetchall():
        stats[row[0]] = {"rides": row[1], "wins": row[2], "top3": row[3]}
    return stats


# --- トラック替わり判定・補正 ---

def _calc_track_switch_info(past_races, current_surface, horse_weight_today=None):
    """トラック替わりの判定とスコア補正値を返す

    バックテスト結果に基づく補正:
    - 芝→ダート: 馬体重480kg以上で加点、440kg未満で減点
    - ダート→芝: キャリア4-7戦で加点
    - 重賞以上のトラック替わりは減点
    """
    result = {
        "is_first_dirt": False,
        "is_first_turf": False,
        "career_count": 0,
        "prev_weight": None,
        "effective_weight": None,  # 朝=前走体重、直前=当日体重
        "score_adj": 0.0,
        "label": "",
    }

    if not past_races or not current_surface:
        return result

    past_surfaces = [r["surface"] for r in past_races if r.get("surface") in ("芝", "ダート")]
    if not past_surfaces:
        return result

    result["career_count"] = len(past_surfaces)

    # 前走馬体重を取得
    for r in past_races:
        hw = r.get("horse_weight")  # keiba_live.db のカラム名
        if not hw:
            # past_dataにはhorse_weightカラムがない場合もある
            # run_today/run_liveのparse_shutuba_entriesで取得済みのケースを考慮
            continue
        if hw and hw > 0:
            result["prev_weight"] = hw
            break

    # 馬体重の決定: 直前予想は当日体重、朝予想は前走体重
    if horse_weight_today and horse_weight_today > 0:
        result["effective_weight"] = horse_weight_today
    else:
        result["effective_weight"] = result["prev_weight"]

    weight = result["effective_weight"]

    # --- 芝→ダート ---
    if current_surface == "ダート" and "ダート" not in past_surfaces:
        result["is_first_dirt"] = True
        result["label"] = "初ダート"

        # 馬体重による補正（バックテスト: 520kg以上→単回収123%、440未満→壊滅）
        if weight:
            if weight >= 520:
                result["score_adj"] = 0.05   # 大型馬ボーナス
            elif weight >= 480:
                result["score_adj"] = 0.02   # 中型馬やや加点
            elif weight < 440:
                result["score_adj"] = -0.05  # 軽量馬ペナルティ

        # キャリア4-15戦のボーナス（バックテスト: 単回収76-77%）
        career = len(past_surfaces)
        if 4 <= career <= 15:
            result["score_adj"] += 0.02

    # --- ダート→芝 ---
    elif current_surface == "芝" and "芝" not in past_surfaces:
        result["is_first_turf"] = True
        result["label"] = "初芝"

        # キャリア4-7戦のボーナス（バックテスト: 単回収72%、複回収66%）
        career = len(past_surfaces)
        if 4 <= career <= 7:
            result["score_adj"] = 0.03

        # 馬体重480kg以上で加点
        if weight and weight >= 480:
            result["score_adj"] += 0.02
        elif weight and weight < 440:
            result["score_adj"] -= 0.03

    return result


# --- 個別スコア計算 ---

def _calc_past_perf_score(past_races):
    """過去成績スコア（直近5走、最近ほど重み大）"""
    if not past_races:
        return 0.3  # データなし→低めのデフォルト

    weights = [0.30, 0.25, 0.20, 0.15, 0.10]
    score = 0.0
    total_weight = 0.0

    for i, race in enumerate(past_races[:5]):
        w = weights[i] if i < len(weights) else 0.05
        hc = race["head_count"] or 14
        fp = race["finish_position"]

        # 着順スコア（1着=1.0, 最下位=0.0）
        if hc > 1:
            pos_score = (hc - fp) / (hc - 1)
        else:
            pos_score = 1.0
        pos_score = max(0.0, min(1.0, pos_score))

        # 上がり3Fボーナス（35秒以下は良い、33秒以下は非常に良い）
        l3f_bonus = 0.0
        if race["last_3f"] and race["last_3f"] > 0:
            if race["last_3f"] <= 33.0:
                l3f_bonus = 0.15
            elif race["last_3f"] <= 34.0:
                l3f_bonus = 0.10
            elif race["last_3f"] <= 35.0:
                l3f_bonus = 0.05

        race_score = min(1.0, pos_score + l3f_bonus)
        score += w * race_score
        total_weight += w

    if total_weight > 0:
        return score / total_weight
    return 0.3


def _calc_jockey_score(stats):
    """騎手スコア"""
    if not stats or stats.get("rides", 0) == 0:
        return 0.3

    rides = stats["rides"]
    win_rate = stats["wins"] / rides
    top3_rate = stats["top3"] / rides

    # ベイズ的な補正（少ないサンプルは全体平均に寄せる）
    # 全体平均: 勝率~8%, 連対率~25%
    prior_rides = 30
    adj_win = (stats["wins"] + prior_rides * 0.08) / (rides + prior_rides)
    adj_top3 = (stats["top3"] + prior_rides * 0.25) / (rides + prior_rides)

    overall = adj_win * 3 + adj_top3  # 勝率を重視

    # 場所別ボーナス
    venue_bonus = 0.0
    if stats.get("venue_rides", 0) >= 10:
        venue_win = stats["venue_wins"] / stats["venue_rides"]
        if venue_win > adj_win:
            venue_bonus = min(0.15, (venue_win - adj_win) * 2)

    score = min(1.0, overall + venue_bonus)
    return score


def _calc_course_score(past_races, venue, surface, distance):
    """コース適性スコア"""
    if not past_races:
        return 0.3

    same_course = []
    same_surface = []
    for r in past_races:
        if r["surface"] == surface:
            same_surface.append(r)
            if r["venue"] == venue and abs(r["distance"] - distance) <= 200:
                same_course.append(r)

    # 同コース同距離帯の成績
    if same_course:
        avg_pos = sum(r["finish_position"] for r in same_course) / len(same_course)
        avg_hc = sum((r["head_count"] or 14) for r in same_course) / len(same_course)
        course_score = max(0, (avg_hc - avg_pos) / (avg_hc - 1)) if avg_hc > 1 else 0.5
        # サンプル数による補正
        confidence = min(1.0, len(same_course) / 5)
        return 0.3 * (1 - confidence) + course_score * confidence
    elif same_surface:
        avg_pos = sum(r["finish_position"] for r in same_surface) / len(same_surface)
        avg_hc = sum((r["head_count"] or 14) for r in same_surface) / len(same_surface)
        surface_score = max(0, (avg_hc - avg_pos) / (avg_hc - 1)) if avg_hc > 1 else 0.5
        confidence = min(1.0, len(same_surface) / 5) * 0.7  # 同コースより信頼度低
        return 0.3 * (1 - confidence) + surface_score * confidence

    return 0.3


def _calc_distance_score(past_races, target_distance):
    """距離適性スコア"""
    if not past_races:
        return 0.3

    target_bucket = distance_bucket(target_distance)
    same_bucket = [r for r in past_races if distance_bucket(r["distance"]) == target_bucket]

    if same_bucket:
        avg_pos = sum(r["finish_position"] for r in same_bucket) / len(same_bucket)
        avg_hc = sum((r["head_count"] or 14) for r in same_bucket) / len(same_bucket)
        score = max(0, (avg_hc - avg_pos) / (avg_hc - 1)) if avg_hc > 1 else 0.5
        confidence = min(1.0, len(same_bucket) / 5)
        return 0.3 * (1 - confidence) + score * confidence

    return 0.3


def _calc_class_score(past_races, target_class):
    """クラス適性スコア"""
    if not past_races:
        return 0.3

    target_level = CLASS_LEVEL.get(target_class, 4)

    # 同クラス以上での成績
    same_or_higher = [r for r in past_races
                       if CLASS_LEVEL.get(r["class"], 4) >= target_level]

    if same_or_higher:
        avg_pos = sum(r["finish_position"] for r in same_or_higher) / len(same_or_higher)
        avg_hc = sum((r["head_count"] or 14) for r in same_or_higher) / len(same_or_higher)
        score = max(0, (avg_hc - avg_pos) / (avg_hc - 1)) if avg_hc > 1 else 0.5
        return score

    # クラスが上がる場合はペナルティ
    if past_races:
        max_past_level = max(CLASS_LEVEL.get(r["class"], 4) for r in past_races)
        if target_level > max_past_level:
            penalty = (target_level - max_past_level) * 0.1
            base = _calc_past_perf_score(past_races[:3])
            return max(0.1, base - penalty)

    return 0.3


def _calc_rotation_score(past_races, target_date):
    """ローテーションスコア"""
    if not past_races:
        return 0.4  # 新馬・長期休養

    last_date_str = past_races[0]["date"]
    try:
        last_date = datetime.strptime(last_date_str, "%Y-%m-%d")
        target = datetime.strptime(target_date, "%Y-%m-%d")
        days = (target - last_date).days
    except (ValueError, TypeError):
        return 0.4

    if 14 <= days <= 35:
        return 1.0
    elif 36 <= days <= 60:
        return 0.85
    elif 61 <= days <= 90:
        return 0.7
    elif 91 <= days <= 180:
        return 0.5
    elif days > 180:
        return 0.35
    elif 7 <= days < 14:
        return 0.7
    else:  # < 7 days (連闘)
        return 0.5


def _calc_post_position_score(post_stats, post_position):
    """枠順スコア"""
    if not post_stats or post_position not in post_stats:
        return 0.5  # データなし→中間

    s = post_stats[post_position]
    if s["rides"] < 20:
        return 0.5  # サンプル不足

    top3_rate = s["top3"] / s["rides"]

    # 全体平均との比較で正規化
    total_rides = sum(v["rides"] for v in post_stats.values())
    total_top3 = sum(v["top3"] for v in post_stats.values())
    avg_rate = total_top3 / total_rides if total_rides > 0 else 0.25

    if avg_rate > 0:
        ratio = top3_rate / avg_rate
        return min(1.0, max(0.0, 0.5 * ratio))

    return 0.5


def _calc_trainer_score(stats):
    """調教師スコア"""
    if not stats or stats.get("rides", 0) == 0:
        return 0.3

    rides = stats["rides"]
    prior_rides = 30
    adj_win = (stats["wins"] + prior_rides * 0.08) / (rides + prior_rides)
    adj_top3 = (stats["top3"] + prior_rides * 0.25) / (rides + prior_rides)

    score = min(1.0, adj_win * 3 + adj_top3)
    return score


# ============================================================
# Step 5: レース選定
# ============================================================

def evaluate_race_quality(conn, race_id, scored_horses, race_info=None):
    """レースの「買いやすさ」を評価してスコアを返す"""
    if len(scored_horses) < 5:
        return {"race_id": race_id, "quality_score": 0, "reasons": ["出走頭数不足"],
                "too_solid": False}

    scores = [h["total_score"] for h in scored_horses]

    # 1. 予測信頼度
    score_spread = (scores[0] - scores[2]) / scores[0] if scores[0] > 0 else 0
    confidence = min(1.0, score_spread * 3)

    # 2. 中穴期待
    has_odds = any((h.get("odds_win") or 0) > 0 for h in scored_horses[:5])
    mid_odds_count = 0
    for h in scored_horses[1:5]:
        odds = h.get("odds_win", 0) or 0
        if 10 <= odds <= 50:
            mid_odds_count += 1
    mid_upset = min(1.0, mid_odds_count / 2) if has_odds else 0.5  # オッズなしは中立

    # 3. 頭数
    hc = len(scored_horses)
    if 10 <= hc <= 14:
        hc_score = 1.0
    elif 8 <= hc <= 16:
        hc_score = 0.7
    else:
        hc_score = 0.3

    # 4. オッズの歪み
    odds_distortion = 0.0
    rank_diffs = []
    for i, h in enumerate(scored_horses[:6]):
        pop = h.get("popularity", 0) or 0
        if pop > 0:
            rank_diffs.append(abs(i + 1 - pop))
    if rank_diffs:
        odds_distortion = min(1.0, sum(rank_diffs) / (len(rank_diffs) * 3))
    elif not has_odds:
        odds_distortion = 0.3  # オッズなしは中立

    # 5. 上位馬のスコア絶対値
    top_score_quality = min(1.0, scores[0] / 0.7)

    # 6. 堅すぎ判定: モデル上位2頭が1-2番人気
    top2_pops = [h.get("popularity", 0) or 0 for h in scored_horses[:2]]
    too_solid = all(p <= 2 for p in top2_pops if p > 0) and has_odds

    quality = (
        0.25 * confidence
        + 0.20 * mid_upset
        + 0.15 * hc_score
        + 0.15 * odds_distortion
        + 0.25 * top_score_quality
    )

    reasons = []
    if confidence > 0.5:
        reasons.append("予測信頼度高")
    if mid_upset > 0.5:
        reasons.append("中穴期待あり")
    if odds_distortion > 0.4:
        reasons.append("オッズ歪みあり")
    if too_solid:
        reasons.append("堅めレース")

    return {
        "race_id": race_id,
        "quality_score": quality,
        "reasons": reasons,
        "too_solid": too_solid,
        "details": {
            "confidence": confidence, "mid_upset": mid_upset,
            "hc_score": hc_score, "odds_distortion": odds_distortion,
            "top_score_quality": top_score_quality,
        },
    }


def select_races(conn, date):
    """指定日の全レースからベスト3-4を選定"""
    c = conn.cursor()
    c.execute("""SELECT race_id FROM races
                 WHERE date = ? AND surface IN ('芝', 'ダート')
                   AND name NOT LIKE '%障害%'
                 ORDER BY race_id""", (date,))
    race_ids = [row[0] for row in c.fetchall()]

    # オッズデータの有無を確認（当日未発表の場合、閾値を調整）
    c.execute("""SELECT COUNT(*) FROM results r
                 JOIN races ra ON r.race_id = ra.race_id
                 WHERE ra.date = ? AND r.odds_win IS NOT NULL AND r.odds_win > 0""", (date,))
    has_odds_data = c.fetchone()[0] > 0
    threshold = QUALITY_THRESHOLD if has_odds_data else 0.70

    # v2モデルの読み込み（使用時のみ）
    v2_model = None
    v2_predictions = {}
    if MODEL_VERSION == "v2":
        try:
            from model_v2 import load_model, build_features_for_date, FEATURE_COLS
            v2_model, _ = load_model()
            # 日付全体の特徴量を一括構築
            import pandas as pd
            df = build_features_for_date(conn, date)
            if not df.empty:
                import numpy as np
                for race_id in race_ids:
                    df_race = df[df["race_id"] == race_id]
                    if df_race.empty:
                        continue
                    X = df_race[FEATURE_COLS].values
                    probs = v2_model.predict(X)
                    v2_predictions[race_id] = dict(
                        zip(df_race["horse_number"].astype(int), probs)
                    )
        except Exception as e:
            print(f"v2モデル読み込み失敗、v1にフォールバック: {e}")
            v2_model = None

    evaluations = []
    for race_id in race_ids:
        scored = score_all_horses(conn, race_id)
        if not scored:
            continue

        # v2ブレンド: v1スコアとv2確率を統合
        if v2_model and race_id in v2_predictions:
            v2_probs = v2_predictions[race_id]
            # v2確率の最大値で正規化してv1と同スケールに
            max_prob = max(v2_probs.values()) if v2_probs else 1.0
            for h in scored:
                hn = h["horse_number"]
                if hn in v2_probs:
                    v2_norm = v2_probs[hn] / max_prob if max_prob > 0 else 0.5
                    h["total_score"] = (
                        V2_BLEND_WEIGHT * v2_norm
                        + (1 - V2_BLEND_WEIGHT) * h["total_score"]
                    )
                    h["v2_prob"] = v2_probs[hn]
            scored.sort(key=lambda x: x["total_score"], reverse=True)

        quality = evaluate_race_quality(conn, race_id, scored)
        evaluations.append({
            "race_id": race_id,
            "scored_horses": scored,
            "quality": quality,
        })

    # 品質スコアで降順ソート
    evaluations.sort(key=lambda x: x["quality"]["quality_score"], reverse=True)

    # 絶対評価: 品質スコアが閾値以上のレースを全て選定
    selected = [ev for ev in evaluations
                if ev["quality"]["quality_score"] >= threshold]

    return selected


# ============================================================
# Step 6: 買い目生成
# ============================================================

def generate_bets(scored_horses, race_info, budget):
    """選定レースの買い目を生成（バリュー戦略）

    戦略: モデル上位5頭を軸に、人気との乖離がある馬を含む組み合わせを優先。
    - モデル上位だが人気薄 → バリューがある（過小評価されている）
    - 軸馬（モデル1-2位）× バリュー馬の組み合わせで中穴を狙う
    """
    if len(scored_horses) < 3:
        return {"bet_type": None, "bets": []}

    scores = [h["total_score"] for h in scored_horses]

    # 馬券種選択: 上位の拮抗度 + 推定配当で判断
    ratio_3rd = scores[2] / scores[0] if scores[0] > 0 else 0

    # 上位2頭の人気を確認（両方が1-2番人気なら馬連は低配当になりやすい）
    top2_pops = [h.get("popularity", 0) or 0 for h in scored_horses[:2]]
    both_top2_popular = all(1 <= p <= 2 for p in top2_pops)

    # 三連複を選ぶ条件:
    # 1. 上位3頭が拮抗 (ratio_3rd >= 0.65)
    # 2. または、上位2頭が1-2番人気で馬連だと低配当が見込まれる場合
    if ratio_3rd >= 0.65 or both_top2_popular:
        return _generate_sanrenpuku(scored_horses, budget)
    else:
        return _generate_umaren(scored_horses, budget)


def _calc_value_score(horse, model_rank):
    """バリュースコア: モデル順位と人気の乖離度"""
    pop = horse.get("popularity", 0) or 0
    odds = horse.get("odds_win", 0) or 0
    if pop <= 0:
        return 0.0

    # モデル順位より人気が低い（過小評価されている）ほどバリューが高い
    rank_gap = pop - model_rank  # 正なら過小評価
    # オッズが高すぎる馬は除外（大穴すぎると当たらない）
    if odds > 60:
        return rank_gap * 0.3  # ペナルティ
    elif odds > 30:
        return rank_gap * 0.7

    return rank_gap


def _estimate_combo_odds(horses, bet_type="umaren"):
    """組み合わせのオッズを推定（単勝オッズから概算）

    馬連: win1 * win2 * 0.4 （経験的係数）
    三連複: win1 * win2 * win3 * 0.1
    """
    odds_list = []
    for h in horses:
        o = h.get("odds_win", 0) or 0
        odds_list.append(max(o, 1.5))  # 最低1.5倍として計算

    if bet_type == "umaren":
        return odds_list[0] * odds_list[1] * 0.4
    else:  # sanrenpuku
        return odds_list[0] * odds_list[1] * odds_list[2] * 0.1


def _allocate_by_odds(combos, budget, bet_type="umaren"):
    """オッズ逆数比例で資金配分（均等回収方式）

    低オッズ（堅い）組み合わせに多く、高オッズ（穴）に少なく配分して
    どの組み合わせが的中しても近い回収額になるようにする。
    """
    # 推定オッズの逆数を配分ウェイトにする
    weights = []
    for c in combos:
        est_odds = c.get("est_odds", 10.0)
        # 逆数（低オッズ＝高ウェイト）
        w = 1.0 / est_odds
        weights.append(w)

    total_w = sum(weights)
    bets = []
    remaining = budget
    for i, (c, w) in enumerate(zip(combos, weights)):
        if i == len(combos) - 1:
            amount = remaining
        else:
            amount = round(budget * w / total_w / 100) * 100
            amount = max(100, amount)
        remaining -= amount
        if remaining < 0:
            amount += remaining
            remaining = 0
        amount = max(100, amount)

        if bet_type == "umaren":
            combo_str = f"{c['horses'][0]} - {c['horses'][1]}"
        else:
            combo_str = f"{c['horses'][0]} - {c['horses'][1]} - {c['horses'][2]}"

        bets.append({
            "combination": combo_str,
            "horses": c["horses"],
            "amount": amount,
            "score": c["combo_score"],
            "est_odds": c.get("est_odds", 0),
        })

    return bets


def _generate_umaren(scored_horses, budget):
    """馬連の買い目を生成（バリュー戦略）

    軸: モデル上位2頭
    相手: モデル上位6頭の中からバリュースコアが高い馬を含む組み合わせを優先
    """
    top_n = min(6, len(scored_horses))

    # 各馬のバリュースコア計算
    for i, h in enumerate(scored_horses[:top_n]):
        h["_value"] = _calc_value_score(h, i + 1)

    combos = []
    for i in range(top_n):
        for j in range(i + 1, top_n):
            h1, h2 = scored_horses[i], scored_horses[j]
            pair = tuple(sorted([h1["horse_number"], h2["horse_number"]]))

            # スコア: モデルスコア + バリューボーナス
            combo_score = h1["total_score"] + h2["total_score"]
            value_bonus = (h1.get("_value", 0) + h2.get("_value", 0)) * 0.05
            ranking_score = combo_score + value_bonus

            # 軸馬（モデル1-2位）を含む組み合わせを優遇
            has_axis = (i <= 1 or j <= 1)
            if has_axis:
                ranking_score += 0.1

            # 推定オッズ
            est_odds = _estimate_combo_odds([h1, h2], "umaren")

            combos.append({
                "horses": pair,
                "combo_score": combo_score,
                "ranking_score": ranking_score,
                "value_bonus": value_bonus,
                "est_odds": est_odds,
            })

    combos.sort(key=lambda x: x["ranking_score"], reverse=True)
    combos = combos[:5]  # 最大5点

    # オッズ逆数比例で資金配分
    bets = _allocate_by_odds(combos, budget, "umaren")

    return {"bet_type": "馬連", "bets": bets}


def _generate_sanrenpuku(scored_horses, budget):
    """三連複の買い目を生成（バリュー戦略）

    軸: モデル上位2頭のうち少なくとも1頭を含む
    相手: モデル上位7頭からバリュースコアを加味して選定
    """
    top_n = min(7, len(scored_horses))

    for i, h in enumerate(scored_horses[:top_n]):
        h["_value"] = _calc_value_score(h, i + 1)

    combos = []
    for i in range(top_n):
        for j in range(i + 1, top_n):
            for k in range(j + 1, top_n):
                h1, h2, h3 = scored_horses[i], scored_horses[j], scored_horses[k]
                triple = tuple(sorted([h1["horse_number"], h2["horse_number"], h3["horse_number"]]))

                combo_score = h1["total_score"] + h2["total_score"] + h3["total_score"]
                value_bonus = (h1.get("_value", 0) + h2.get("_value", 0) + h3.get("_value", 0)) * 0.05
                ranking_score = combo_score + value_bonus

                # 軸馬（モデル1-2位）を含む組み合わせを優遇
                has_axis = (i <= 1 or j <= 1)
                if has_axis:
                    ranking_score += 0.1

                # バリュー馬（人気より2段階以上高い評価）を含むとボーナス
                has_value = any(scored_horses[idx].get("_value", 0) >= 2
                               for idx in [i, j, k])
                if has_value:
                    ranking_score += 0.05

                # 推定オッズ
                est_odds = _estimate_combo_odds([h1, h2, h3], "sanrenpuku")

                combos.append({
                    "horses": triple,
                    "combo_score": combo_score,
                    "ranking_score": ranking_score,
                    "est_odds": est_odds,
                })

    combos.sort(key=lambda x: x["ranking_score"], reverse=True)
    combos = combos[:8]  # 最大8点

    # オッズ逆数比例で資金配分
    bets = _allocate_by_odds(combos, budget, "sanrenpuku")

    return {"bet_type": "三連複", "bets": bets}


def allocate_budget(selected_races, total_budget=10000):
    """レース間の予算配分（品質スコア比例・予算上限厳守）"""
    if not selected_races:
        return {}

    n = len(selected_races)
    total_quality = sum(r["quality"]["quality_score"] for r in selected_races)
    budgets = {}
    remaining = total_budget

    for i, race in enumerate(selected_races):
        if i == n - 1:
            budgets[race["race_id"]] = max(100, remaining)
        else:
            ratio = race["quality"]["quality_score"] / total_quality if total_quality > 0 else 1 / n
            amount = round(total_budget * ratio / 100) * 100
            amount = max(100, min(amount, remaining - (n - i - 1) * 100))
            budgets[race["race_id"]] = amount
            remaining -= amount

    return budgets


# ============================================================
# メインエントリ: 1日分の予測
# ============================================================

def predict_day(conn, date, race_budget=RACE_BUDGET):
    """指定日の予測を生成"""
    selected = select_races(conn, date)
    if not selected:
        return {"date": date, "races": [], "total_bet": 0}

    result_races = []
    total_bet = 0

    for race_ev in selected:
        race_id = race_ev["race_id"]
        budget = race_budget

        # レース情報取得
        c = conn.cursor()
        c.execute("SELECT * FROM races WHERE race_id = ?", (race_id,))
        race_row = c.fetchone()
        race_info = {
            "race_id": race_row[0], "date": race_row[1], "venue": race_row[2],
            "race_number": race_row[3], "name": race_row[4], "class": race_row[5],
            "distance": race_row[6], "surface": race_row[7],
            "track_condition": race_row[9],
        }

        bets = generate_bets(race_ev["scored_horses"], race_info, budget)
        bet_total = sum(b["amount"] for b in bets["bets"])
        total_bet += bet_total

        # 馬名を取得
        horse_names = {}
        horse_ids = [h["horse_id"] for h in race_ev["scored_horses"]]
        if horse_ids:
            phs = ",".join("?" * len(horse_ids))
            c.execute(f"SELECT horse_id, name FROM horses WHERE horse_id IN ({phs})", horse_ids)
            horse_names = dict(c.fetchall())

        result_races.append({
            "race_id": race_id,
            "race_info": race_info,
            "quality": race_ev["quality"],
            "scored_horses": race_ev["scored_horses"],
            "horse_names": horse_names,
            "bets": bets,
            "bet_total": bet_total,
        })

    return {
        "date": date,
        "races": result_races,
        "total_bet": total_bet,
    }
