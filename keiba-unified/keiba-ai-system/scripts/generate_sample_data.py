"""テスト用サンプルデータ生成スクリプト

スクレイピングが使えない環境でパイプラインを検証するための
サンプルレース結果データを生成する。
"""

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from config.settings import RAW_DATA_DIR

# ばんえい競馬の馬名サンプル
HORSE_NAMES = [
    "キタノユウジロウ", "メムロボブサップ", "アオノブラック", "コマサンエース",
    "マツカゼウンカイ", "ゴールドハンター", "インビクタ", "オレノココロ",
    "センゴクエース", "カイセドクター", "ミソギホマレ", "コウシュハウンカイ",
    "ホクショウマサル", "キンツルモリウチ", "マルミゴウカイ", "ナカゼンガキタ",
    "ゴールデンフウジン", "メジロゴーリキ", "シンエイボブ", "アアモンドグンシン",
    "カネサブラック", "ニシキダイジン", "コマサンブラック", "ハクタイホウ",
    "ミノルシャープ", "ジェイエース", "オーシャンウイナー", "プレジデント",
    "フジダイビクトリー", "キサラキク",
]

JOCKEYS = [
    "鈴木恵介", "阿部武臣", "藤本匠", "松田道明", "西謙一",
    "菊池一樹", "渡来心路", "島津新", "船山蔵人", "赤塚健仁",
]

TRAINERS = [
    "坂本東一", "服部義幸", "槻舘重人", "平田義弘", "松井浩文",
    "岩本利春", "金田勇", "大友栄人", "久田守", "西弘美",
]

SEX_OPTIONS = ["牡", "牝", "セ"]


def _assign_horse_profiles(horse_names, jockeys, trainers, sex_options):
    """各馬に固有プロフィール（能力・体重・性齢・騎手・調教師）を割り当てる"""
    profiles = {}
    for name in horse_names:
        profiles[name] = {
            "base_ability": random.gauss(50, 12),
            "horse_weight": random.randint(930, 1080),
            "sex": random.choice(sex_options),
            "base_age": random.randint(3, 7),
            "jockey": random.choice(jockeys),
            "trainer": random.choice(trainers),
        }
    return profiles


def generate_sample_data(
    start_date: date = date(2025, 1, 1),
    end_date: date = date(2025, 12, 31),
    races_per_day: int = 12,
    race_interval_days: int = 3,
) -> pd.DataFrame:
    """サンプルレースデータを生成

    各馬に固有の能力値を持たせ、レースごとのランダム変動を加えて
    着順を決定する。枠番・馬番はランダムに割り当てる。
    """
    random.seed(42)
    records = []

    # 馬ごとの固有プロフィールを生成
    profiles = _assign_horse_profiles(HORSE_NAMES, JOCKEYS, TRAINERS, SEX_OPTIONS)

    current = start_date
    while current <= end_date:
        for race_no in range(1, races_per_day + 1):
            num_horses = random.randint(6, 10)
            distance = 200  # ばんえいは200m

            # 出走馬を選択
            horses = random.sample(HORSE_NAMES, num_horses)

            # 枠番・馬番をランダムに割り当て（着順とは無関係）
            positions = list(range(1, num_horses + 1))
            random.shuffle(positions)
            horse_positions = {h: pos for h, pos in zip(horses, positions)}

            # 負担重量をランダムに割り当て
            carry_options = [560, 570, 580, 590, 600, 610, 620,
                             630, 640, 650, 660, 670, 680, 690, 700]
            horse_carries = {h: random.choice(carry_options) for h in horses}

            # 各馬のレース能力 = 固有能力 + ランダム変動 - 負担重量の影響
            race_abilities = {}
            for h in horses:
                p = profiles[h]
                variation = random.gauss(0, 10)  # 当日の調子
                carry_penalty = (horse_carries[h] - 620) * 0.05
                race_abilities[h] = p["base_ability"] + variation - carry_penalty

            # 能力順にソート → 着順
            sorted_horses = sorted(horses, key=lambda h: -race_abilities[h])

            for finish_order, horse_name in enumerate(sorted_horses, 1):
                p = profiles[horse_name]
                # 馬体重に当日変動を加える
                hw = p["horse_weight"] + random.randint(-10, 10)
                # 年齢は開催日に応じて加算
                years_passed = (current - start_date).days // 365
                age = p["base_age"] + years_passed

                # タイム生成（着順が早いほど速い）
                base_time = 120 + random.gauss(0, 8)
                time_seconds = base_time + (finish_order - 1) * random.uniform(1, 4)
                minutes = int(time_seconds) // 60
                secs = time_seconds - minutes * 60
                time_str = f"{minutes}:{secs:04.1f}"

                # オッズ（能力が高い馬は低オッズ + ノイズ）
                odds = max(1.1, 20 - p["base_ability"] / 5 + random.gauss(0, 4))

                # 人気順（オッズ順に後で付ける用に一時保管）
                records.append({
                    "race_date": current.strftime("%Y-%m-%d"),
                    "race_no": str(race_no),
                    "race_name": f"第{race_no}レース",
                    "distance": distance,
                    "finish_order": finish_order,
                    "post_position": horse_positions[horse_name],
                    "horse_number": horse_positions[horse_name],
                    "horse_name": horse_name,
                    "sex_age": f"{p['sex']}{age}",
                    "horse_weight": hw,
                    "jockey": p["jockey"],
                    "time": time_str,
                    "weight_carry": horse_carries[horse_name],
                    "trainer": p["trainer"],
                    "odds": round(odds, 1),
                    "popularity": 0,  # 後で設定
                })

        current += timedelta(days=race_interval_days)

    df = pd.DataFrame(records)

    # 人気順をオッズ順で付与
    df["popularity"] = df.groupby(["race_date", "race_no"])["odds"].rank(
        method="min"
    ).astype(int)

    return df


def main():
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)

    df = generate_sample_data()
    output_path = RAW_DATA_DIR / "race_results.csv"
    df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"サンプルデータ生成完了: {output_path}")
    print(f"  レコード数: {len(df):,}")
    print(f"  期間: {df['race_date'].min()} 〜 {df['race_date'].max()}")
    print(f"  レース数: {df.groupby(['race_date', 'race_no']).ngroups}")


if __name__ == "__main__":
    main()
