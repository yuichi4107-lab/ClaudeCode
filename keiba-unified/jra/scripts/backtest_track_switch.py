"""トラック替わり（初ダート・初芝）のバックテスト分析

DB修復後に実行。芝→ダート、ダート→芝の替わり馬の成績・回収率を分析する。
"""

import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, ".")

DB_PATH = "data/keiba.db"


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def analyze_track_switches():
    """全レースを走査し、トラック替わり馬の成績を集計する"""
    conn = get_connection()
    c = conn.cursor()

    # 全レース取得（障害を除く、race_type/distanceがある物のみ）
    c.execute("""
        SELECT race_id, race_date, race_type, distance, grade, venue_name,
               horse_count, track_condition
        FROM races
        WHERE race_type IN ('芝', 'ダート')
          AND distance IS NOT NULL
        ORDER BY race_date
    """)
    races = [dict(r) for r in c.fetchall()]
    print(f"対象レース: {len(races):,}")

    # 結果カテゴリ
    categories = {
        "芝→ダート": defaultdict(list),  # 初ダート
        "ダート→芝": defaultdict(list),  # 初芝
        "同馬場継続": defaultdict(list),  # 比較用ベースライン
        "初出走": defaultdict(list),      # 初出走（新馬含む）
    }

    # 詳細分析用
    detail_records = []

    processed = 0
    for race in races:
        race_id = race["race_id"]
        race_date = race["race_date"]
        race_type = race["race_type"]
        grade = race["grade"] or ""

        # このレースの出走馬を取得
        c.execute("""
            SELECT horse_id, horse_number, finish_order, odds, popularity, horse_weight
            FROM race_results
            WHERE race_id = ?
              AND finish_order IS NOT NULL
        """, (race_id,))
        runners = [dict(r) for r in c.fetchall()]

        # このレースの複勝払戻を取得
        c.execute("""
            SELECT combination, payout FROM payoffs
            WHERE race_id = ? AND bet_type = '複勝'
        """, (race_id,))
        fukusho_payoffs = {}
        for row in c.fetchall():
            fukusho_payoffs[row["combination"].strip()] = row["payout"]

        # 単勝払戻を取得
        c.execute("""
            SELECT combination, payout FROM payoffs
            WHERE race_id = ? AND bet_type = '単勝'
        """, (race_id,))
        tansho_payoffs = {}
        for row in c.fetchall():
            tansho_payoffs[row["combination"].strip()] = row["payout"]

        for runner in runners:
            horse_id = runner["horse_id"]
            if not horse_id:
                continue

            # この馬の過去走をチェック（race_typeが分かるもののみ）
            c.execute("""
                SELECT r.race_type
                FROM race_results rr
                JOIN races r ON rr.race_id = r.race_id
                WHERE rr.horse_id = ?
                  AND r.race_date < ?
                  AND r.race_type IS NOT NULL
                ORDER BY r.race_date
            """, (horse_id, race_date))
            past_types = [row["race_type"] for row in c.fetchall()]

            # カテゴリ判定
            if len(past_types) == 0:
                category = "初出走"
            elif race_type not in past_types:
                # 今回の馬場で走ったことがない
                if race_type == "ダート":
                    category = "芝→ダート"
                else:
                    category = "ダート→芝"
            else:
                category = "同馬場継続"

            finish = runner["finish_order"]
            odds = runner["odds"]
            popularity = runner["popularity"]
            horse_number = str(runner["horse_number"])
            horse_weight = runner["horse_weight"]

            is_win = finish == 1
            is_top3 = finish <= 3

            # 払戻計算
            tansho_payout = tansho_payoffs.get(horse_number, 0) if is_win else 0
            fukusho_payout = fukusho_payoffs.get(horse_number, 0) if is_top3 else 0

            record = {
                "category": category,
                "race_id": race_id,
                "race_date": race_date,
                "race_type": race_type,
                "grade": grade,
                "horse_id": horse_id,
                "finish": finish,
                "odds": odds,
                "popularity": popularity,
                "horse_weight": horse_weight,
                "is_win": is_win,
                "is_top3": is_top3,
                "tansho_payout": tansho_payout,
                "fukusho_payout": fukusho_payout,
                "career_count": len(past_types),
                "past_types": past_types,
            }

            categories[category]["all"].append(record)
            detail_records.append(record)

        processed += 1
        if processed % 2000 == 0:
            print(f"  処理中... {processed}/{len(races)}")

    conn.close()

    # === 結果出力 ===
    print("\n" + "=" * 80)
    print("トラック替わりバックテスト分析結果")
    print("=" * 80)

    for cat_name in ["芝→ダート", "ダート→芝", "同馬場継続", "初出走"]:
        records = categories[cat_name]["all"]
        if not records:
            continue

        n = len(records)
        wins = sum(1 for r in records if r["is_win"])
        top3 = sum(1 for r in records if r["is_top3"])

        # 回収率計算（100円均一馬券）
        tansho_invest = n * 100
        tansho_return = sum(r["tansho_payout"] for r in records)
        fukusho_invest = n * 100
        fukusho_return = sum(r["fukusho_payout"] for r in records)

        avg_odds = sum(r["odds"] for r in records if r["odds"]) / max(
            sum(1 for r in records if r["odds"]), 1
        )
        avg_pop = sum(r["popularity"] for r in records if r["popularity"]) / max(
            sum(1 for r in records if r["popularity"]), 1
        )

        print(f"\n--- {cat_name} ({n:,}頭) ---")
        print(f"  勝率:     {wins/n*100:5.1f}% ({wins:,}/{n:,})")
        print(f"  複勝率:   {top3/n*100:5.1f}% ({top3:,}/{n:,})")
        print(f"  単勝回収率: {tansho_return/tansho_invest*100:5.1f}%")
        print(f"  複勝回収率: {fukusho_return/fukusho_invest*100:5.1f}%")
        print(f"  平均オッズ: {avg_odds:.1f}倍  平均人気: {avg_pop:.1f}")

    # === 細分化分析 ===
    print("\n" + "=" * 80)
    print("細分化分析")
    print("=" * 80)

    for switch_type in ["芝→ダート", "ダート→芝"]:
        records = categories[switch_type]["all"]
        if not records:
            continue

        print(f"\n{'='*40}")
        print(f"  {switch_type} 詳細分析")
        print(f"{'='*40}")

        # --- グレード別 ---
        print(f"\n  [グレード別]")
        grade_groups = defaultdict(list)
        for r in records:
            g = r["grade"]
            if g in ("G1", "G2", "G3"):
                grade_groups["重賞"].append(r)
            elif g in ("オープン", "リステッド"):
                grade_groups["OP/L"].append(r)
            else:
                grade_groups["条件戦"].append(r)

        for g_name in ["条件戦", "OP/L", "重賞"]:
            grp = grade_groups.get(g_name, [])
            if not grp:
                continue
            n = len(grp)
            top3 = sum(1 for r in grp if r["is_top3"])
            fuku_ret = sum(r["fukusho_payout"] for r in grp)
            tan_ret = sum(r["tansho_payout"] for r in grp)
            print(f"    {g_name:8s}: {n:5d}頭  複勝率{top3/n*100:5.1f}%  "
                  f"単回収{tan_ret/(n*100)*100:5.1f}%  複回収{fuku_ret/(n*100)*100:5.1f}%")

        # --- キャリア数別 ---
        print(f"\n  [キャリア数別（前走までの出走数）]")
        career_groups = defaultdict(list)
        for r in records:
            cc = r["career_count"]
            if cc <= 3:
                career_groups["1-3戦"].append(r)
            elif cc <= 7:
                career_groups["4-7戦"].append(r)
            elif cc <= 15:
                career_groups["8-15戦"].append(r)
            else:
                career_groups["16戦以上"].append(r)

        for label in ["1-3戦", "4-7戦", "8-15戦", "16戦以上"]:
            grp = career_groups.get(label, [])
            if not grp:
                continue
            n = len(grp)
            top3 = sum(1 for r in grp if r["is_top3"])
            fuku_ret = sum(r["fukusho_payout"] for r in grp)
            tan_ret = sum(r["tansho_payout"] for r in grp)
            print(f"    {label:8s}: {n:5d}頭  複勝率{top3/n*100:5.1f}%  "
                  f"単回収{tan_ret/(n*100)*100:5.1f}%  複回収{fuku_ret/(n*100)*100:5.1f}%")

        # --- 人気別 ---
        print(f"\n  [人気別]")
        pop_groups = defaultdict(list)
        for r in records:
            p = r["popularity"]
            if p and p <= 3:
                pop_groups["1-3人気"].append(r)
            elif p and p <= 6:
                pop_groups["4-6人気"].append(r)
            elif p and p <= 9:
                pop_groups["7-9人気"].append(r)
            elif p:
                pop_groups["10人気以下"].append(r)

        for label in ["1-3人気", "4-6人気", "7-9人気", "10人気以下"]:
            grp = pop_groups.get(label, [])
            if not grp:
                continue
            n = len(grp)
            top3 = sum(1 for r in grp if r["is_top3"])
            fuku_ret = sum(r["fukusho_payout"] for r in grp)
            tan_ret = sum(r["tansho_payout"] for r in grp)
            print(f"    {label:8s}: {n:5d}頭  複勝率{top3/n*100:5.1f}%  "
                  f"単回収{tan_ret/(n*100)*100:5.1f}%  複回収{fuku_ret/(n*100)*100:5.1f}%")

        # --- 馬体重別 ---
        print(f"\n  [馬体重別]")
        weight_groups = defaultdict(list)
        for r in records:
            w = r["horse_weight"]
            if not w:
                continue
            if w < 440:
                weight_groups["440kg未満"].append(r)
            elif w < 480:
                weight_groups["440-479kg"].append(r)
            elif w < 520:
                weight_groups["480-519kg"].append(r)
            else:
                weight_groups["520kg以上"].append(r)

        for label in ["440kg未満", "440-479kg", "480-519kg", "520kg以上"]:
            grp = weight_groups.get(label, [])
            if not grp:
                continue
            n = len(grp)
            top3 = sum(1 for r in grp if r["is_top3"])
            fuku_ret = sum(r["fukusho_payout"] for r in grp)
            tan_ret = sum(r["tansho_payout"] for r in grp)
            print(f"    {label:8s}: {n:5d}頭  複勝率{top3/n*100:5.1f}%  "
                  f"単回収{tan_ret/(n*100)*100:5.1f}%  複回収{fuku_ret/(n*100)*100:5.1f}%")

        # --- 年別推移 ---
        print(f"\n  [年別推移]")
        year_groups = defaultdict(list)
        for r in records:
            year = r["race_date"][:4]
            year_groups[year].append(r)

        for year in sorted(year_groups.keys()):
            grp = year_groups[year]
            n = len(grp)
            top3 = sum(1 for r in grp if r["is_top3"])
            fuku_ret = sum(r["fukusho_payout"] for r in grp)
            tan_ret = sum(r["tansho_payout"] for r in grp)
            print(f"    {year}: {n:5d}頭  複勝率{top3/n*100:5.1f}%  "
                  f"単回収{tan_ret/(n*100)*100:5.1f}%  複回収{fuku_ret/(n*100)*100:5.1f}%")

    # === 馬券への影響シミュレーション ===
    print("\n" + "=" * 80)
    print("馬券影響分析: トラック替わり馬が3着以内に来たレース")
    print("=" * 80)

    for switch_type in ["芝→ダート", "ダート→芝"]:
        records = categories[switch_type]["all"]
        hit_records = [r for r in records if r["is_top3"]]
        print(f"\n--- {switch_type} で3着以内 ({len(hit_records)}件) ---")

        # 人気分布
        pop_dist = defaultdict(int)
        for r in hit_records:
            p = r["popularity"]
            if p and p <= 3:
                pop_dist["1-3人気"] += 1
            elif p and p <= 6:
                pop_dist["4-6人気"] += 1
            elif p and p <= 9:
                pop_dist["7-9人気"] += 1
            elif p:
                pop_dist["10人気以下"] += 1

        for label in ["1-3人気", "4-6人気", "7-9人気", "10人気以下"]:
            cnt = pop_dist.get(label, 0)
            pct = cnt / len(hit_records) * 100 if hit_records else 0
            print(f"  {label}: {cnt}件 ({pct:.1f}%)")

        # 穴馬（6人気以下）の好走
        upset_hits = [r for r in hit_records if r["popularity"] and r["popularity"] >= 6]
        print(f"\n  穴馬（6人気以下）好走: {len(upset_hits)}件")
        if upset_hits:
            avg_odds_upset = sum(r["odds"] for r in upset_hits if r["odds"]) / len(upset_hits)
            print(f"  平均オッズ: {avg_odds_upset:.1f}倍")


if __name__ == "__main__":
    analyze_track_switches()
