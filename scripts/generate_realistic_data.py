#!/usr/bin/env python3
"""南関東4場の2025年1年分のリアルな模擬データを生成してDBに投入する。

実際の開催パターン・オッズ分布・着順傾向を再現し、
パイプライン全体（特徴量→学習→予測→評価）を検証する。

Usage:
    python scripts/generate_realistic_data.py
    python scripts/generate_realistic_data.py --year 2025
    python scripts/generate_realistic_data.py --db data/nankan.db
"""

import argparse
import logging
import random
import sys
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from nankan_predictor.storage.database import init_db
from nankan_predictor.storage.repository import Repository
from nankan_predictor.config.settings import DB_PATH

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── 南関東4場の開催パターン（曜日ベース） ─────────────────────────
# 実際は変則的だが、概ね以下のパターン:
#   大井(46): 月〜水中心 + 特開（年100〜120開催日）
#   船橋(45): 月〜水が多い（年40〜50開催日）
#   川崎(47): 月〜水（年40〜50開催日）
#   浦和(44): 火〜木（年35〜45開催日）
VENUE_CONFIG = {
    "46": {"name": "oi",        "jp": "大井",  "races_per_day": 12, "annual_days": 110,
           "weekdays": [0, 1, 2, 3, 4]},  # 月〜金
    "45": {"name": "funabashi", "jp": "船橋",  "races_per_day": 12, "annual_days": 45,
           "weekdays": [0, 1, 2]},
    "47": {"name": "kawasaki",  "jp": "川崎",  "races_per_day": 12, "annual_days": 45,
           "weekdays": [0, 1, 2]},
    "44": {"name": "urawa",     "jp": "浦和",  "races_per_day": 12, "annual_days": 40,
           "weekdays": [1, 2, 3]},
}

# ─── 馬名プール ───────────────────────────────────────────────────
HORSE_PREFIXES = [
    "ゴールド", "シルバー", "ブラック", "ホワイト", "レッド", "ブルー",
    "キング", "クイーン", "プリンス", "ロイヤル", "スター", "ムーン",
    "サン", "ライト", "ファイヤー", "ウィンド", "サンダー", "スノー",
    "ドリーム", "フラッシュ", "スピード", "パワー", "ラッキー", "ハッピー",
    "ナイス", "グレート", "スーパー", "マイティ", "ワイルド", "クール",
    "ビッグ", "リトル", "エース", "トップ", "ノーブル", "ブレイブ",
    "マジック", "ミラクル", "ファイン", "グランド", "シャイン", "フェア",
]
HORSE_SUFFIXES = [
    "キセキ", "マジック", "フラワー", "スター", "ウィング", "ハート",
    "ストーン", "クラウン", "ジュエル", "バード", "フォース", "ローズ",
    "ブレイド", "アロー", "ライダー", "ナイト", "フライト", "ドラゴン",
    "タイガー", "イーグル", "フェニックス", "レオ", "ホーク", "ウルフ",
    "リング", "ボルト", "テンペスト", "ブリッツ", "ストーム", "ウェイブ",
    "オーシャン", "リバー", "フォレスト", "スカイ", "サニー", "ハルカ",
    "ミライ", "ヒカリ", "カゼ", "ツバサ", "イブキ", "タケル",
]

JOCKEY_NAMES = [
    "矢野貴之", "森泰斗", "笹川翼", "本橋孝太", "張田昂", "吉井章",
    "御神本訓史", "真島大輔", "左海誠二", "石崎駿", "中野省吾", "今野忠成",
    "瀧川寿希也", "山崎誠士", "酒井忍", "繁田健一", "藤本現暉", "岡部誠",
    "町田直希", "西啓太", "山林堅", "和田譲治", "松岡正海", "達城龍次",
    "保園翔也", "七夕裕次郎", "仲野光馬", "篠谷葵", "江里口裕輝", "吉原寛人",
]

TRAINER_NAMES = [
    "佐藤賢二", "荒山勝徳", "藤田輝信", "森下淳平", "高月賢一",
    "岡林光浩", "佐々木仁", "水野貴史", "内田勝義", "堀千亜樹",
    "鈴木義久", "齊藤誠", "出川克己", "矢野義幸", "高橋清",
    "池田孝", "小久保智", "渡邉和雄", "山下貴之", "阪本一栄",
]

DISTANCES = [1000, 1200, 1400, 1500, 1600, 1700, 1800, 2000, 2100, 2400]
DIST_WEIGHTS = [0.05, 0.15, 0.15, 0.10, 0.20, 0.10, 0.10, 0.08, 0.05, 0.02]
CONDITIONS = ["良", "稍重", "重", "不良"]
COND_WEIGHTS = [0.55, 0.20, 0.15, 0.10]
WEATHERS = ["晴", "曇", "小雨", "雨"]
WEATHER_WEIGHTS = [0.45, 0.30, 0.15, 0.10]
SEX_OPTIONS = ["牡", "牝", "セ"]
SEX_WEIGHTS = [0.55, 0.25, 0.20]


class HorsePool:
    """馬IDと名前のプール。能力値付き。"""

    def __init__(self, seed: int = 42):
        self.rng = np.random.RandomState(seed)
        self.horses = {}  # horse_id -> {name, ability, age, sex, weight, ...}
        self._id_counter = 0

    def create_horse(self, year: int) -> dict:
        self._id_counter += 1
        horse_id = f"{year - self.rng.randint(2, 6)}{self.rng.randint(100000, 999999)}"
        # 同じIDの衝突を避ける
        while horse_id in self.horses:
            horse_id = f"{year - self.rng.randint(2, 6)}{self.rng.randint(100000, 999999)}"

        name = self.rng.choice(HORSE_PREFIXES) + self.rng.choice(HORSE_SUFFIXES)
        # 能力値: 正規分布。高いほど強い
        ability = self.rng.normal(50, 15)
        age = self.rng.randint(3, 9)
        sex = self.rng.choice(SEX_OPTIONS, p=SEX_WEIGHTS)
        base_weight = int(self.rng.normal(470 if sex == "牡" else 450, 25))

        self.horses[horse_id] = {
            "horse_id": horse_id,
            "horse_name": name,
            "ability": ability,
            "horse_age": age,
            "horse_sex": sex,
            "base_weight": base_weight,
        }
        return self.horses[horse_id]

    def get_or_create(self, year: int) -> dict:
        if len(self.horses) < 200 or self.rng.random() < 0.1:
            return self.create_horse(year)
        return self.rng.choice(list(self.horses.values()))

    def sample_field(self, year: int, field_size: int) -> list[dict]:
        """レースに出走するfield_size頭を抽出。"""
        # 既存馬から70%、新馬30%
        field = []
        used_ids = set()
        for _ in range(field_size):
            if len(self.horses) > 50 and self.rng.random() < 0.7:
                # 既存馬
                candidates = [h for h in self.horses.values() if h["horse_id"] not in used_ids]
                if candidates:
                    horse = self.rng.choice(candidates)
                else:
                    horse = self.create_horse(year)
            else:
                horse = self.create_horse(year)
            field.append(horse)
            used_ids.add(horse["horse_id"])
        return field


def generate_schedule(year: int, rng: np.random.RandomState) -> list[dict]:
    """1年分の開催スケジュールを生成する。"""
    schedule = []
    start = datetime(year, 1, 1)
    end = datetime(year, 12, 31)

    for venue_code, cfg in VENUE_CONFIG.items():
        # 年間の開催日を散らす
        all_days = []
        d = start
        while d <= end:
            if d.weekday() in cfg["weekdays"]:
                all_days.append(d)
            d += timedelta(days=1)

        # 年間開催日数を制限
        target = cfg["annual_days"]
        if len(all_days) > target:
            indices = sorted(rng.choice(len(all_days), target, replace=False))
            all_days = [all_days[i] for i in indices]

        for day in all_days:
            n_races = cfg["races_per_day"]
            schedule.append({
                "date": day,
                "venue_code": venue_code,
                "venue_name": cfg["jp"],
                "n_races": n_races,
            })

    # 同じ日に複数会場が被らないようにする（実際も基本1日1場）
    schedule.sort(key=lambda x: x["date"])
    used_dates = set()
    filtered = []
    for item in schedule:
        date_key = item["date"].strftime("%Y-%m-%d")
        if date_key not in used_dates:
            filtered.append(item)
            used_dates.add(date_key)
        elif rng.random() < 0.15:
            # 15% の確率で同日ダブル開催
            filtered.append(item)

    logger.info("Generated schedule: %d race days for %d", len(filtered), year)
    return filtered


def simulate_race(
    field: list[dict],
    distance: int,
    condition: str,
    rng: np.random.RandomState,
) -> list[dict]:
    """1レースをシミュレーション。能力値ベースでタイム・着順を決定。"""
    n = len(field)

    # 基準タイム (秒) = 距離依存
    base_time = distance / 16.5  # 約16.5m/s

    entries = []
    for i, horse in enumerate(field):
        ability = horse["ability"]
        # ランダム要素（調子）
        form = rng.normal(0, 8)
        # 距離適性（長距離ほどバラつく）
        dist_factor = rng.normal(0, distance / 500)
        # 馬場状態の影響
        cond_penalty = {"良": 0, "稍重": rng.uniform(0, 2), "重": rng.uniform(0, 4), "不良": rng.uniform(0, 6)}
        # 総合スコア（高いほど速い = 良い着順）
        score = ability + form + dist_factor - cond_penalty.get(condition, 0)

        # タイム = 基準タイム - スコア補正
        time_sec = base_time - score * 0.03 + rng.normal(0, 0.5)
        time_sec = max(time_sec, base_time * 0.9)

        entries.append({
            "index": i,
            "horse": horse,
            "score": score,
            "finish_time": round(time_sec, 1),
        })

    # スコア順でソート → 着順決定
    entries.sort(key=lambda x: -x["score"])
    for rank, entry in enumerate(entries, 1):
        entry["finish_position"] = rank

    return entries


def calculate_odds(entries: list[dict], rng: np.random.RandomState) -> list[dict]:
    """能力に基づいた現実的なオッズを計算する。"""
    scores = np.array([e["score"] for e in entries])
    # softmax的にオッズの逆数（支持率）を計算
    exp_scores = np.exp((scores - scores.max()) / 8)
    probs = exp_scores / exp_scores.sum()

    # オッズ = 1/確率 × 控除率(0.75) + ノイズ
    odds_list = []
    for i, p in enumerate(probs):
        raw_odds = 0.75 / max(p, 0.01)
        noisy_odds = raw_odds * rng.uniform(0.8, 1.2)
        noisy_odds = max(round(noisy_odds, 1), 1.1)
        odds_list.append(noisy_odds)

    # 人気順決定
    indexed_odds = list(enumerate(odds_list))
    indexed_odds.sort(key=lambda x: x[1])
    pop_rank = [0] * len(odds_list)
    for rank, (idx, _) in enumerate(indexed_odds, 1):
        pop_rank[idx] = rank

    for i, entry in enumerate(entries):
        entry["win_odds"] = odds_list[i]
        entry["popularity_rank"] = pop_rank[i]

    return entries


def calculate_exacta_payout(
    entries: list[dict], rng: np.random.RandomState
) -> float | None:
    """1着と2着の馬番から馬単払戻金を計算する（100円あたりの払戻金）。

    実際の馬単オッズ: 人気決着で500〜2000円、中穴で3000〜10000円、大穴で数万円。
    """
    first = [e for e in entries if e["finish_position"] == 1]
    second = [e for e in entries if e["finish_position"] == 2]
    if not first or not second:
        return None

    first_odds = first[0]["win_odds"]
    second_odds = second[0]["win_odds"]
    field_size = len(entries)

    # 馬単倍率 ≈ 1着単勝オッズ × (2着の相対オッズ) × 控除率補正
    # 2着の相対オッズ ≈ second_odds / field_size の補正
    exacta_multiplier = first_odds * (second_odds * 0.8) / (field_size / 10)
    # ノイズを加えてリアリティ
    exacta_multiplier *= rng.uniform(0.6, 1.6)
    # 最低でも1.5倍（150円）
    exacta_multiplier = max(exacta_multiplier, 1.5)

    # 100円あたりの払戻金に変換
    payout = exacta_multiplier * 100
    payout = max(round(payout / 10) * 10, 150)  # 10円単位、最低150円
    return float(payout)


def generate_and_insert(year: int, db_path: str) -> None:
    """1年分のデータを生成してDBに挿入する。"""
    init_db(db_path)
    repo = Repository(db_path)
    rng = np.random.RandomState(42)
    horse_pool = HorsePool(seed=42)

    schedule = generate_schedule(year, rng)

    total_races = 0
    total_entries_count = 0
    total_history = 0
    # horse_id -> list of past race records (for horse_history_cache)
    horse_histories = defaultdict(list)

    for day_info in schedule:
        date_obj = day_info["date"]
        date_str = date_obj.strftime("%Y-%m-%d")
        date_compact = date_obj.strftime("%m%d")
        venue_code = day_info["venue_code"]

        for race_num in range(1, day_info["n_races"] + 1):
            race_id = f"{year}{venue_code}{date_compact}{race_num:02d}"

            # レース条件
            distance = int(rng.choice(DISTANCES, p=DIST_WEIGHTS))
            condition = rng.choice(CONDITIONS, p=COND_WEIGHTS)
            weather = rng.choice(WEATHERS, p=WEATHER_WEIGHTS)
            field_size = int(rng.choice(range(8, 15)))

            # 出走馬
            field = horse_pool.sample_field(year, field_size)

            # レースシミュレーション
            sim_results = simulate_race(field, distance, condition, rng)
            sim_results = calculate_odds(sim_results, rng)

            # レース情報をDB
            race_info = {
                "race_id": race_id,
                "venue_code": venue_code,
                "venue_name": day_info["venue_name"],
                "race_date": date_str,
                "race_number": race_num,
                "race_name": f"{day_info['venue_name']}{race_num}R",
                "distance": distance,
                "track_type": "ダート",
                "track_condition": condition,
                "weather": weather,
                "field_size": field_size,
            }
            repo.upsert_race(race_info)

            # 出走馬・騎手を登録
            entries_for_db = []
            for sim in sim_results:
                horse = sim["horse"]
                horse_num = sim["index"] + 1
                jockey = rng.choice(JOCKEY_NAMES)
                jockey_id = f"J{abs(hash(jockey)) % 100000:05d}"
                trainer = rng.choice(TRAINER_NAMES)
                weight_carried = round(rng.choice([54.0, 55.0, 56.0, 57.0]), 1)
                horse_weight = horse["base_weight"] + int(rng.normal(0, 5))
                weight_change = int(rng.normal(0, 4))

                # passing positions (模擬)
                pos = sim["finish_position"]
                passing = f"{min(pos + rng.randint(-2, 3), field_size)}-{min(pos + rng.randint(-1, 2), field_size)}-{pos}"

                # last 3f time
                last_3f = round(rng.normal(38.5, 1.5), 1)

                repo.upsert_horse(horse["horse_id"], horse["horse_name"])
                repo.upsert_jockey(jockey_id, jockey)

                entry = {
                    "race_id": race_id,
                    "horse_id": horse["horse_id"],
                    "jockey_id": jockey_id,
                    "horse_name": horse["horse_name"],
                    "jockey_name": jockey,
                    "trainer_name": trainer,
                    "gate_number": horse_num,
                    "horse_number": horse_num,
                    "weight_carried": weight_carried,
                    "horse_weight": horse_weight,
                    "weight_change": weight_change,
                    "win_odds": sim["win_odds"],
                    "popularity_rank": sim["popularity_rank"],
                    "finish_position": sim["finish_position"],
                    "finish_time": sim["finish_time"],
                    "margin": "",
                    "passing_positions": passing,
                    "last_3f_time": last_3f,
                    "horse_age": horse["horse_age"],
                    "horse_sex": horse["horse_sex"],
                    "is_winner": 1 if sim["finish_position"] == 1 else 0,
                }
                entries_for_db.append(entry)
                total_entries_count += 1

                # 馬の過去成績に追加
                horse_histories[horse["horse_id"]].append({
                    "race_date": date_str,
                    "venue_name": day_info["venue_name"],
                    "race_name": f"{day_info['venue_name']}{race_num}R",
                    "distance": distance,
                    "field_size": field_size,
                    "gate_number": horse_num,
                    "horse_number": horse_num,
                    "popularity_rank": sim["popularity_rank"],
                    "finish_position": sim["finish_position"],
                    "jockey_name": jockey,
                    "weight_carried": weight_carried,
                    "finish_time": sim["finish_time"],
                    "margin": "",
                    "passing_positions": passing,
                    "pace": "",
                    "horse_weight": horse_weight,
                })

            repo.upsert_entries(entries_for_db)

            # 馬単払戻金
            payout = calculate_exacta_payout(sim_results, rng)
            if payout:
                first_entry = [e for e in entries_for_db if e["finish_position"] == 1][0]
                second_entry = [e for e in entries_for_db if e["finish_position"] == 2][0]
                combination = f"{first_entry['horse_number']}-{second_entry['horse_number']}"
                repo.upsert_payout(race_id, "exacta", combination, payout)

                # 単勝払戻も追加
                win_payout = round(first_entry["win_odds"] * 100)
                repo.upsert_payout(race_id, "win", str(first_entry["horse_number"]), float(win_payout))

            total_races += 1

    # horse_history_cache に一括投入
    logger.info("Inserting horse histories...")
    for horse_id, records in horse_histories.items():
        try:
            repo.upsert_horse_history(horse_id, records)
            total_history += len(records)
        except Exception as e:
            logger.warning("Failed to insert history for %s: %s", horse_id, e)

    logger.info(
        "Data generation complete: %d races, %d entries, %d history records, %d horses",
        total_races, total_entries_count, total_history, len(horse_pool.horses),
    )
    print(f"\n{'=' * 60}")
    print(f"データ生成完了")
    print(f"  年度:          {year}")
    print(f"  レース数:      {total_races}")
    print(f"  出走数:        {total_entries_count}")
    print(f"  馬数:          {len(horse_pool.horses)}")
    print(f"  過去成績:      {total_history}")
    print(f"  DB:            {db_path}")
    print(f"{'=' * 60}")


def main():
    parser = argparse.ArgumentParser(description="南関東模擬データ生成")
    parser.add_argument("--year", type=int, default=2025, help="対象年 (default: 2025)")
    parser.add_argument("--db", default=DB_PATH, help="DBパス")
    args = parser.parse_args()

    generate_and_insert(args.year, args.db)


if __name__ == "__main__":
    main()
