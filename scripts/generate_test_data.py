#!/usr/bin/env python3
"""
JRA 予想システム パイプライン検証用テストデータ生成スクリプト。

5年分（2021-2025）のリアルなJRAレースデータを SQLite に生成する。
ネットワーク接続不要。
"""

import random
import sqlite3
import sys
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jra_predictor.storage.database import init_db, get_connection
from jra_predictor.config.settings import DB_PATH

random.seed(42)

# --- 定数 ---
VENUES = {
    "05": ("東京", "芝", "左"),
    "06": ("中山", "芝", "右"),
    "09": ("阪神", "芝", "右"),
    "08": ("京都", "芝", "右"),
    "07": ("中京", "芝", "左"),
    "01": ("札幌", "芝", "右"),
    "02": ("函館", "芝", "右"),
    "03": ("福島", "芝", "右"),
    "04": ("新潟", "芝", "左"),
    "10": ("小倉", "芝", "右"),
}

TRACK_TYPES = ["芝", "ダート"]
TRACK_CONDITIONS = ["良", "稍重", "重", "不良"]
TRACK_COND_WEIGHTS = [0.55, 0.25, 0.12, 0.08]
WEATHERS = ["晴", "曇", "雨", "小雨"]
WEATHER_WEIGHTS = [0.45, 0.30, 0.15, 0.10]

DISTANCES_TURF = [1000, 1200, 1400, 1600, 1800, 2000, 2200, 2400, 2500, 3000, 3200, 3600]
DISTANCES_DIRT = [1000, 1150, 1200, 1400, 1600, 1700, 1800, 2100, 2400]

HORSE_SEXES = ["牡", "牝", "セ"]
HORSE_SEX_WEIGHTS = [0.55, 0.35, 0.10]

# 馬名プール（ランダム生成ではなく実際にありそうな名前の要素）
NAME_PREFIXES = [
    "ゴールド", "サンライズ", "ダイワ", "メイショウ", "トーセン",
    "キング", "ロード", "エアー", "マイネル", "タイキ",
    "シンボリ", "テイエム", "サクラ", "マチカネ", "ナリタ",
    "トウカイ", "ミスター", "ケイアイ", "コスモ", "アドマイヤ",
    "タニノ", "ダノン", "エピファ", "キタサン", "サトノ",
    "クロノ", "レイデオ", "グラン", "オルフェ", "ジェンティル",
]
NAME_SUFFIXES = [
    "スター", "エース", "キング", "ブレイブ", "フライト",
    "マジック", "ドリーム", "パワー", "スピード", "チャンプ",
    "ジュエル", "サンダー", "ライト", "ナイト", "ウイング",
    "フェニックス", "レオ", "ブラック", "ホワイト", "ゴールド",
    "グレース", "ルビー", "ノーブル", "プリンス", "レジェンド",
]

JOCKEY_NAMES = [
    "武豊", "横山典弘", "ルメール", "レーン", "モレイラ",
    "福永祐一", "岩田康誠", "池添謙一", "川田将雅", "松山弘平",
    "戸崎圭太", "三浦皇成", "北村友一", "和田竜二", "田辺裕信",
    "横山武史", "坂井瑠星", "吉田隼人", "松岡正海", "内田博幸",
    "石橋脩", "丸山元気", "津村明秀", "大野拓弥", "菱田裕二",
    "藤岡佑介", "浜中俊", "幸英明", "柴田善臣", "蛯名正義",
]

TRAINER_NAMES = [
    "藤沢和雄", "国枝栄", "矢作芳人", "堀宣行", "池江泰寿",
    "木村哲也", "友道康夫", "音無秀孝", "西村真幸", "中内田充正",
    "手塚貴久", "田中博康", "鹿戸雄一", "須貝尚介", "安田隆行",
    "奥村武", "美浦助手", "加藤征弘", "萩原清", "角居勝彦",
]


def generate_horse_id():
    """netkeiba 形式の馬ID: 年 + 場コード + 連番 (10桁)"""
    year = random.randint(2015, 2023)
    num = random.randint(100001, 199999)
    return f"{year}{num}"


def generate_horse_name():
    return random.choice(NAME_PREFIXES) + random.choice(NAME_SUFFIXES)


def generate_jockey_id():
    return f"0{random.randint(1000, 9999)}"


def generate_finish_time(distance, track_type):
    """距離とコース種別からリアルなタイムを生成"""
    if track_type == "芝":
        pace = distance / (random.uniform(15.5, 17.5))  # m/s 換算
    else:
        pace = distance / (random.uniform(14.5, 16.5))
    return round(pace + random.uniform(-1.0, 1.0), 1)


def generate_odds(field_size):
    """出走馬のオッズを生成（対数正規分布に近似）"""
    raw = [random.lognormvariate(1.5, 1.0) for _ in range(field_size)]
    total = sum(raw)
    # 控除率を考慮した調整
    odds = [max(1.1, round(total / r * 0.8, 1)) for r in raw]
    return odds


def generate_race_date_schedule(year):
    """JRA開催スケジュールを近似生成: 年間約290レース日 × 12R = ~3500レース"""
    dates = []
    # JRA は基本的に土日開催
    dt = datetime(year, 1, 1)
    end = datetime(year, 12, 31)
    while dt <= end:
        if dt.weekday() in (5, 6):  # 土日
            # 夏場（7-8月）は開催が少なめ
            if dt.month in (7, 8) and random.random() < 0.3:
                dt += timedelta(days=1)
                continue
            dates.append(dt)
        dt += timedelta(days=1)
    return dates


def pick_active_venues(date):
    """その日の開催場を2-3場選ぶ"""
    venue_codes = list(VENUES.keys())
    month = date.month

    # 季節に応じた開催場の重み
    weights = {
        "01": 1 if month in (6, 7, 8) else 0,   # 札幌: 夏
        "02": 1 if month in (6, 7) else 0,        # 函館: 夏
        "03": 1 if month in (4, 7, 10, 11) else 0,  # 福島
        "04": 1 if month in (5, 7, 8, 10) else 0,   # 新潟
        "05": 1 if month in (1, 2, 4, 5, 6, 10, 11) else 0,  # 東京
        "06": 1 if month in (1, 3, 4, 9, 12) else 0,  # 中山
        "07": 1 if month in (1, 3, 6, 7, 12) else 0,  # 中京
        "08": 1 if month in (1, 2, 4, 5, 10, 11) else 0,  # 京都
        "09": 1 if month in (3, 4, 6, 9, 12) else 0,  # 阪神
        "10": 1 if month in (2, 7, 8) else 0,  # 小倉
    }

    available = [v for v, w in weights.items() if w > 0]
    if len(available) < 2:
        available = random.sample(venue_codes, 3)

    n_venues = random.choice([2, 2, 3])
    return random.sample(available, min(n_venues, len(available)))


# --- 馬のスキル値（一貫性を持たせるためのシード） ---
horse_pool = {}  # horse_id -> {name, skill, track_pref, ...}
jockey_pool = {}  # jockey_id -> {name, skill}


def get_or_create_horse():
    """馬プールから取得 or 新規作成"""
    if horse_pool and random.random() < 0.7:
        # 既存馬を再利用（同じ馬が複数レースに出走）
        hid = random.choice(list(horse_pool.keys()))
        return hid, horse_pool[hid]

    hid = generate_horse_id()
    while hid in horse_pool:
        hid = generate_horse_id()

    horse = {
        "name": generate_horse_name(),
        "skill": random.gauss(50, 15),  # 基礎能力
        "turf_bonus": random.gauss(0, 5),  # 芝適性
        "dirt_bonus": random.gauss(0, 5),  # ダート適性
        "sex": random.choices(HORSE_SEXES, weights=HORSE_SEX_WEIGHTS)[0],
        "birth_year": random.randint(2015, 2023),
    }
    horse_pool[hid] = horse
    return hid, horse


def get_or_create_jockey():
    """騎手プールから取得 or 新規作成"""
    if len(jockey_pool) < len(JOCKEY_NAMES):
        idx = len(jockey_pool)
        jid = f"0{1001 + idx}"
        jockey = {
            "name": JOCKEY_NAMES[idx],
            "skill": random.gauss(50, 10),
        }
        jockey_pool[jid] = jockey
        return jid, jockey

    jid = random.choice(list(jockey_pool.keys()))
    return jid, jockey_pool[jid]


def simulate_race(field_size, track_type, distance, venue_code):
    """レースをシミュレーションして順位を決定"""
    entries = []
    for i in range(field_size):
        hid, horse = get_or_create_horse()
        jid, jockey = get_or_create_jockey()

        # 能力値: 馬の基礎能力 + コース適性 + 騎手スキル + ランダム
        ability = horse["skill"]
        if track_type == "芝":
            ability += horse["turf_bonus"]
        else:
            ability += horse["dirt_bonus"]
        ability += jockey["skill"] * 0.3
        ability += random.gauss(0, 10)  # レース当日のランダム要素

        entries.append({
            "horse_id": hid,
            "horse_name": horse["name"],
            "horse_sex": horse["sex"],
            "horse_age": max(2, 2026 - horse["birth_year"]),
            "jockey_id": jid,
            "jockey_name": jockey["name"],
            "trainer_name": random.choice(TRAINER_NAMES),
            "ability": ability,
            "gate_number": i + 1,
            "horse_number": i + 1,
            "weight_carried": round(random.uniform(51.0, 58.0), 1),
            "horse_weight": random.randint(420, 540),
        })

    # 能力順にソートして順位を決定
    entries.sort(key=lambda x: x["ability"], reverse=True)
    for rank, entry in enumerate(entries, 1):
        entry["finish_position"] = rank

    return entries


def calculate_payouts(entries, field_size):
    """レース結果から払戻金を算出"""
    payouts = []

    # 着順で馬番を取得
    sorted_entries = sorted(entries, key=lambda x: x["finish_position"])
    first = sorted_entries[0]["horse_number"]
    second = sorted_entries[1]["horse_number"]
    third = sorted_entries[2]["horse_number"] if len(sorted_entries) >= 3 else None

    # 馬単払戻 (1着→2着)
    # オッズから概算（人気薄ほど高配当）
    first_pop = sorted_entries[0].get("popularity_rank", 1)
    second_pop = sorted_entries[1].get("popularity_rank", 2)
    base_exacta = 200 + first_pop * 300 + second_pop * 400
    exacta_payout = int(base_exacta * random.uniform(0.7, 1.5))
    # 1着が1人気で2着も人気なら低配当
    if first_pop <= 2 and second_pop <= 3:
        exacta_payout = int(random.uniform(300, 2000))
    elif first_pop >= 5 or second_pop >= 5:
        exacta_payout = int(random.uniform(3000, 50000))

    payouts.append({
        "bet_type": "exacta",
        "combination": f"{first}-{second}",
        "payout": exacta_payout,
    })

    # 三連複払戻 (1-2-3着 順不同)
    if third is not None:
        third_pop = sorted_entries[2].get("popularity_rank", 3)
        base_trio = 300 + first_pop * 200 + second_pop * 300 + third_pop * 400
        trio_payout = int(base_trio * random.uniform(0.8, 2.0))
        if max(first_pop, second_pop, third_pop) <= 3:
            trio_payout = int(random.uniform(300, 3000))
        elif max(first_pop, second_pop, third_pop) >= 6:
            trio_payout = int(random.uniform(5000, 100000))

        sorted_nums = sorted([first, second, third])
        payouts.append({
            "bet_type": "trio",
            "combination": f"{sorted_nums[0]}-{sorted_nums[1]}-{sorted_nums[2]}",
            "payout": trio_payout,
        })

    return payouts


def generate_all_data():
    """5年分のデータを生成"""
    init_db()
    conn = get_connection()

    total_races = 0
    total_entries = 0
    total_horses_history = 0

    for year in range(2021, 2026):
        dates = generate_race_date_schedule(year)
        year_races = 0

        for date in dates:
            active_venues = pick_active_venues(date)

            for venue_code in active_venues:
                venue_name, default_track, direction = VENUES[venue_code]
                n_races = random.randint(10, 12)

                for race_num in range(1, n_races + 1):
                    track_type = random.choices(
                        TRACK_TYPES, weights=[0.55, 0.45]
                    )[0]
                    if track_type == "芝":
                        distance = random.choice(DISTANCES_TURF)
                        course_dir = direction
                    else:
                        distance = random.choice(DISTANCES_DIRT)
                        course_dir = direction

                    track_condition = random.choices(
                        TRACK_CONDITIONS, weights=TRACK_COND_WEIGHTS
                    )[0]
                    weather = random.choices(
                        WEATHERS, weights=WEATHER_WEIGHTS
                    )[0]

                    field_size = random.randint(8, 18)

                    date_str = date.strftime("%Y-%m-%d")
                    mmdd = date.strftime("%m%d")
                    race_id = f"{year}{venue_code}{mmdd}{race_num:02d}"

                    # レース情報を挿入
                    conn.execute(
                        """INSERT OR REPLACE INTO races
                        (race_id, venue_code, venue_name, race_date, race_number,
                         race_name, distance, track_type, track_condition,
                         course_direction, weather, field_size, scraped_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            race_id, venue_code, venue_name, date_str, race_num,
                            f"{venue_name}{race_num}R", distance, track_type,
                            track_condition, course_dir, weather, field_size,
                            datetime.now().isoformat(),
                        ),
                    )

                    # レースをシミュレーション
                    entries = simulate_race(field_size, track_type, distance, venue_code)

                    # オッズと人気順を設定
                    odds = generate_odds(field_size)
                    odds_sorted_idx = sorted(range(field_size), key=lambda i: odds[i])
                    for pop_rank, idx in enumerate(odds_sorted_idx, 1):
                        entries[idx]["win_odds"] = odds[idx]
                        entries[idx]["popularity_rank"] = pop_rank

                    # 着差
                    margins = ["", "クビ", "ハナ", "アタマ", "1/2", "3/4", "1", "1.1/2", "2", "3", "大差"]

                    for entry in entries:
                        pos = entry["finish_position"]
                        finish_time = generate_finish_time(distance, track_type)
                        # 着順が遅いほどタイムが長い
                        finish_time += (pos - 1) * random.uniform(0.1, 0.3)
                        weight_change = random.choice([-8, -6, -4, -2, 0, 0, 2, 4, 6, 8])

                        # 馬・騎手レコードを先に挿入（外部キー制約）
                        conn.execute(
                            """INSERT OR IGNORE INTO horses (horse_id, horse_name, updated_at)
                            VALUES (?, ?, ?)""",
                            (entry["horse_id"], entry["horse_name"], datetime.now().isoformat()),
                        )
                        conn.execute(
                            """INSERT OR IGNORE INTO jockeys (jockey_id, jockey_name, updated_at)
                            VALUES (?, ?, ?)""",
                            (entry["jockey_id"], entry["jockey_name"], datetime.now().isoformat()),
                        )

                        entry_id = f"{race_id}_{entry['horse_number']:02d}"
                        conn.execute(
                            """INSERT OR REPLACE INTO race_entries
                            (entry_id, race_id, horse_id, jockey_id, horse_name,
                             jockey_name, trainer_name, gate_number, horse_number,
                             weight_carried, horse_weight, weight_change, win_odds,
                             popularity_rank, finish_position, finish_time, margin,
                             passing_positions, last_3f_time, horse_age, horse_sex,
                             is_winner)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                entry_id, race_id, entry["horse_id"], entry["jockey_id"],
                                entry["horse_name"], entry["jockey_name"], entry["trainer_name"],
                                entry["gate_number"], entry["horse_number"],
                                entry["weight_carried"], entry["horse_weight"], weight_change,
                                entry["win_odds"], entry["popularity_rank"],
                                pos, round(finish_time, 1),
                                random.choice(margins) if pos > 1 else "",
                                f"{random.randint(1, field_size)}-{random.randint(1, field_size)}-{random.randint(1, field_size)}",
                                round(random.uniform(33.0, 38.0), 1),
                                entry["horse_age"], entry["horse_sex"],
                                1 if pos == 1 else 0,
                            ),
                        )

                        total_entries += 1

                    # 払戻金
                    payouts = calculate_payouts(entries, field_size)
                    for p in payouts:
                        conn.execute(
                            """INSERT OR REPLACE INTO race_payouts
                            (race_id, bet_type, combination, payout)
                            VALUES (?, ?, ?, ?)""",
                            (race_id, p["bet_type"], p["combination"], p["payout"]),
                        )

                    total_races += 1
                    year_races += 1

        print(f"  {year}: {year_races} レース生成完了")
        conn.commit()

    # --- 馬の過去成績データ (horse_history_cache) ---
    print("馬の過去成績データを生成中...")

    # race_entries からデータを引いて horse_history_cache を構築
    cursor = conn.execute("""
        SELECT e.horse_id, r.race_date, r.venue_name, r.race_name, r.distance,
               r.track_type, r.field_size, e.gate_number, e.horse_number,
               e.popularity_rank, e.finish_position, e.jockey_name,
               e.weight_carried, e.finish_time, e.horse_weight
        FROM race_entries e
        JOIN races r ON e.race_id = r.race_id
        ORDER BY e.horse_id, r.race_date
    """)

    batch = []
    for row in cursor:
        batch.append((
            row[0], row[1], row[2], row[3], row[4],
            row[5], row[6], row[7], row[8], row[9],
            row[10], row[11], row[12], row[13],
            "", "",  # margin, passing_positions
            "",  # pace
            row[14],  # horse_weight
        ))
        if len(batch) >= 5000:
            conn.executemany(
                """INSERT OR IGNORE INTO horse_history_cache
                (horse_id, race_date, venue_name, race_name, distance,
                 track_type, field_size, gate_number, horse_number,
                 popularity_rank, finish_position, jockey_name,
                 weight_carried, finish_time,
                 margin, passing_positions, pace, horse_weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                batch,
            )
            total_horses_history += len(batch)
            batch = []

    if batch:
        conn.executemany(
            """INSERT OR IGNORE INTO horse_history_cache
            (horse_id, race_date, venue_name, race_name, distance,
             track_type, field_size, gate_number, horse_number,
             popularity_rank, finish_position, jockey_name,
             weight_carried, finish_time,
             margin, passing_positions, pace, horse_weight)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            batch,
        )
        total_horses_history += len(batch)

    conn.commit()
    conn.close()

    print(f"\n=== データ生成完了 ===")
    print(f"レース数:     {total_races:,}")
    print(f"出走レコード: {total_entries:,}")
    print(f"馬成績レコード: {total_horses_history:,}")
    print(f"DB: {DB_PATH}")


if __name__ == "__main__":
    print("JRA テストデータ生成中（2021-2025 の5年分）...")
    generate_all_data()
