#!/usr/bin/env python3
"""オッズによって1-2番人気の信頼性が変わるかを分析する。

1番人気・2番人気のオッズ水準（例: 4倍以下 vs 4倍超）で
勝率・連対率・馬単的中率に差があるかを調べる。

Usage:
    python scripts/odds_reliability_analysis.py
    python scripts/odds_reliability_analysis.py --db path/to/nankan.db
"""

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_race_data(conn: sqlite3.Connection) -> list[dict]:
    """レースごとに1-2番人気の情報をまとめて取得する。"""
    sql = """
    SELECT
        e.race_id,
        r.race_date,
        r.venue_code,
        r.field_size,
        e.popularity_rank,
        e.win_odds,
        e.finish_position,
        e.horse_number
    FROM race_entries e
    JOIN races r ON e.race_id = r.race_id
    WHERE e.popularity_rank IN (1, 2)
      AND e.win_odds IS NOT NULL
      AND e.finish_position IS NOT NULL
    ORDER BY e.race_id, e.popularity_rank
    """
    rows = conn.execute(sql).fetchall()

    # レースIDごとにグルーピング
    races = defaultdict(list)
    for row in rows:
        races[row["race_id"]].append(dict(row))

    # 1番人気と2番人気が両方いるレースだけ返す
    result = []
    for race_id, entries in races.items():
        fav1 = [e for e in entries if e["popularity_rank"] == 1]
        fav2 = [e for e in entries if e["popularity_rank"] == 2]
        if fav1 and fav2:
            result.append({
                "race_id": race_id,
                "race_date": fav1[0]["race_date"],
                "venue_code": fav1[0]["venue_code"],
                "field_size": fav1[0]["field_size"],
                "fav1_odds": fav1[0]["win_odds"],
                "fav1_finish": fav1[0]["finish_position"],
                "fav1_horse_no": fav1[0]["horse_number"],
                "fav2_odds": fav2[0]["win_odds"],
                "fav2_finish": fav2[0]["finish_position"],
                "fav2_horse_no": fav2[0]["horse_number"],
            })
    return result


def classify_odds(odds: float, thresholds: list[float]) -> str:
    """オッズを閾値で分類する。"""
    for t in thresholds:
        if odds <= t:
            return f"~{t:.1f}"
    return f"{thresholds[-1]:.1f}~"


def analyze_by_fav1_odds(races: list[dict]) -> None:
    """1番人気のオッズ帯別に勝率・連対率を分析。"""
    print("\n" + "=" * 80)
    print("■ 分析1: 1番人気のオッズ帯別 勝率・連対率")
    print("=" * 80)

    thresholds = [2.0, 3.0, 4.0, 6.0, 10.0]
    buckets = defaultdict(lambda: {"total": 0, "win": 0, "place12": 0})

    for r in races:
        odds = r["fav1_odds"]
        label = classify_odds(odds, thresholds)
        buckets[label]["total"] += 1
        if r["fav1_finish"] == 1:
            buckets[label]["win"] += 1
        if r["fav1_finish"] <= 2:
            buckets[label]["place12"] += 1

    labels = [f"~{t:.1f}" for t in thresholds] + [f"{thresholds[-1]:.1f}~"]
    print(f"\n  {'オッズ帯':>10} {'レース数':>8} {'勝率':>8} {'連対率':>8}")
    print(f"  {'─' * 44}")
    for label in labels:
        b = buckets[label]
        if b["total"] == 0:
            continue
        win_rate = b["win"] / b["total"] * 100
        place_rate = b["place12"] / b["total"] * 100
        print(f"  {label:>10} {b['total']:>8} {win_rate:>7.1f}% {place_rate:>7.1f}%")


def analyze_by_fav2_odds(races: list[dict]) -> None:
    """2番人気のオッズ帯別に勝率・連対率を分析。"""
    print("\n" + "=" * 80)
    print("■ 分析2: 2番人気のオッズ帯別 勝率・連対率")
    print("=" * 80)

    thresholds = [3.0, 5.0, 8.0, 12.0, 20.0]
    buckets = defaultdict(lambda: {"total": 0, "win": 0, "place12": 0})

    for r in races:
        odds = r["fav2_odds"]
        label = classify_odds(odds, thresholds)
        buckets[label]["total"] += 1
        if r["fav2_finish"] == 1:
            buckets[label]["win"] += 1
        if r["fav2_finish"] <= 2:
            buckets[label]["place12"] += 1

    labels = [f"~{t:.1f}" for t in thresholds] + [f"{thresholds[-1]:.1f}~"]
    print(f"\n  {'オッズ帯':>10} {'レース数':>8} {'勝率':>8} {'連対率':>8}")
    print(f"  {'─' * 44}")
    for label in labels:
        b = buckets[label]
        if b["total"] == 0:
            continue
        win_rate = b["win"] / b["total"] * 100
        place_rate = b["place12"] / b["total"] * 100
        print(f"  {label:>10} {b['total']:>8} {win_rate:>7.1f}% {place_rate:>7.1f}%")


def analyze_odds_gap(races: list[dict]) -> None:
    """1番人気と2番人気のオッズ差（支持集中度）別に分析。"""
    print("\n" + "=" * 80)
    print("■ 分析3: 1番人気と2番人気のオッズ差別（支持集中度）")
    print("  → オッズ差が大きい = 1番人気に支持が集中")
    print("=" * 80)

    # オッズ比率 = fav2_odds / fav1_odds
    # 比率が大きい = 1番人気が断然人気
    thresholds = [1.5, 2.0, 3.0, 5.0]
    buckets = defaultdict(lambda: {
        "total": 0,
        "fav1_win": 0, "fav2_win": 0,
        "fav12_exacta": 0, "fav21_exacta": 0,
        "fav1_place12": 0, "fav2_place12": 0,
    })

    for r in races:
        if r["fav1_odds"] <= 0:
            continue
        ratio = r["fav2_odds"] / r["fav1_odds"]
        label = classify_odds(ratio, thresholds)
        b = buckets[label]
        b["total"] += 1
        if r["fav1_finish"] == 1:
            b["fav1_win"] += 1
        if r["fav2_finish"] == 1:
            b["fav2_win"] += 1
        if r["fav1_finish"] <= 2:
            b["fav1_place12"] += 1
        if r["fav2_finish"] <= 2:
            b["fav2_place12"] += 1
        # 馬単 1→2 or 2→1
        if r["fav1_finish"] == 1 and r["fav2_finish"] == 2:
            b["fav12_exacta"] += 1
        if r["fav2_finish"] == 1 and r["fav1_finish"] == 2:
            b["fav21_exacta"] += 1

    labels = [f"~{t:.1f}" for t in thresholds] + [f"{thresholds[-1]:.1f}~"]

    print(f"\n  {'比率':>8} {'レース数':>8} {'1人気勝率':>10} {'2人気勝率':>10} "
          f"{'1人気連対':>10} {'2人気連対':>10} {'1→2率':>8} {'2→1率':>8}")
    print(f"  {'─' * 82}")
    for label in labels:
        b = buckets[label]
        if b["total"] == 0:
            continue
        n = b["total"]
        print(f"  {label:>8} {n:>8} "
              f"{b['fav1_win']/n*100:>9.1f}% {b['fav2_win']/n*100:>9.1f}% "
              f"{b['fav1_place12']/n*100:>9.1f}% {b['fav2_place12']/n*100:>9.1f}% "
              f"{b['fav12_exacta']/n*100:>7.1f}% {b['fav21_exacta']/n*100:>7.1f}%")


def analyze_combined_odds_level(races: list[dict]) -> None:
    """上位2頭のオッズ水準の組み合わせ別に分析。

    ユーザーの質問の核心:
    「1番人気と2番人気が両方とも低オッズ（堅い）時 vs そうでない時」
    """
    print("\n" + "=" * 80)
    print("■ 分析4: 上位2頭のオッズ水準別 馬単的中率【核心の分析】")
    print("  → 1番人気・2番人気のオッズが両方低い（堅い）時、勝率は上がるか？")
    print("=" * 80)

    # 1番人気を4倍で区切り、2番人気を8倍で区切る
    categories = {
        "1人気≤3倍 & 2人気≤5倍 (超堅)": lambda r: r["fav1_odds"] <= 3.0 and r["fav2_odds"] <= 5.0,
        "1人気≤4倍 & 2人気≤8倍 (堅め)":  lambda r: r["fav1_odds"] <= 4.0 and r["fav2_odds"] <= 8.0,
        "1人気>4倍 or 2人気>8倍 (混戦)":  lambda r: r["fav1_odds"] > 4.0 or r["fav2_odds"] > 8.0,
        "1人気>6倍 (大混戦)":             lambda r: r["fav1_odds"] > 6.0,
    }

    for cat_name, condition in categories.items():
        subset = [r for r in races if condition(r)]
        if not subset:
            continue
        n = len(subset)
        fav1_win = sum(1 for r in subset if r["fav1_finish"] == 1)
        fav2_win = sum(1 for r in subset if r["fav2_finish"] == 1)
        fav12_win = fav1_win + fav2_win
        fav12_exacta = sum(1 for r in subset
                           if (r["fav1_finish"] == 1 and r["fav2_finish"] == 2)
                           or (r["fav2_finish"] == 1 and r["fav1_finish"] == 2))
        non_fav_win = sum(1 for r in subset
                          if r["fav1_finish"] > 2 and r["fav2_finish"] > 2)

        print(f"\n  【{cat_name}】 ({n}レース)")
        print(f"    1-2人気のどちらかが1着: {fav12_win}/{n} = {fav12_win/n*100:.1f}%")
        print(f"      (1人気勝率: {fav1_win/n*100:.1f}%, 2人気勝率: {fav2_win/n*100:.1f}%)")
        print(f"    馬単 1→2 or 2→1: {fav12_exacta}/{n} = {fav12_exacta/n*100:.1f}%")
        print(f"    1-2人気とも3着以下: {non_fav_win}/{n} = {non_fav_win/n*100:.1f}%")


def analyze_fav1_odds_threshold_detail(races: list[dict]) -> None:
    """1番人気のオッズ閾値を細かく変えて、勝率の変化を見る。"""
    print("\n" + "=" * 80)
    print("■ 分析5: 1番人気オッズの閾値別 勝率推移（0.5倍刻み）")
    print("  → オッズ何倍を境に勝率が落ちるか？")
    print("=" * 80)

    print(f"\n  {'1人気オッズ':>12} {'レース数':>8} {'1人気勝率':>10} {'1-2人気1着':>12} {'馬単1↔2':>10}")
    print(f"  {'─' * 58}")

    for low, high in [(1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 3.0),
                      (3.0, 3.5), (3.5, 4.0), (4.0, 5.0), (5.0, 6.0),
                      (6.0, 8.0), (8.0, 15.0)]:
        subset = [r for r in races if low < r["fav1_odds"] <= high]
        if not subset:
            continue
        n = len(subset)
        fav1_win = sum(1 for r in subset if r["fav1_finish"] == 1)
        fav12_win = sum(1 for r in subset if r["fav1_finish"] <= 2 or r["fav2_finish"] <= 2)
        # ↑ 1-2人気のどちらかが1着
        fav12_win_exact = sum(1 for r in subset
                              if r["fav1_finish"] == 1 or r["fav2_finish"] == 1)
        exacta = sum(1 for r in subset
                     if (r["fav1_finish"] == 1 and r["fav2_finish"] == 2)
                     or (r["fav2_finish"] == 1 and r["fav1_finish"] == 2))
        label = f"{low:.1f}-{high:.1f}"
        print(f"  {label:>12} {n:>8} {fav1_win/n*100:>9.1f}% "
              f"{fav12_win_exact/n*100:>11.1f}% {exacta/n*100:>9.1f}%")


def analyze_venue_comparison(races: list[dict]) -> None:
    """会場別にオッズの傾向を比較。"""
    print("\n" + "=" * 80)
    print("■ 分析6: 会場別 オッズと勝率の傾向")
    print("=" * 80)

    venue_names = {"44": "浦和", "45": "船橋", "46": "大井", "47": "川崎"}
    buckets = defaultdict(lambda: {
        "total": 0, "fav1_win": 0, "fav2_win": 0,
        "exacta": 0, "fav1_odds_sum": 0, "fav2_odds_sum": 0,
    })

    for r in races:
        vc = r["venue_code"]
        b = buckets[vc]
        b["total"] += 1
        b["fav1_odds_sum"] += r["fav1_odds"]
        b["fav2_odds_sum"] += r["fav2_odds"]
        if r["fav1_finish"] == 1:
            b["fav1_win"] += 1
        if r["fav2_finish"] == 1:
            b["fav2_win"] += 1
        if (r["fav1_finish"] == 1 and r["fav2_finish"] == 2) or \
           (r["fav2_finish"] == 1 and r["fav1_finish"] == 2):
            b["exacta"] += 1

    print(f"\n  {'会場':>6} {'レース数':>8} {'1人気平均':>10} {'2人気平均':>10} "
          f"{'1人気勝率':>10} {'2人気勝率':>10} {'馬単1↔2':>10}")
    print(f"  {'─' * 72}")
    for vc in sorted(buckets.keys()):
        b = buckets[vc]
        if b["total"] == 0:
            continue
        n = b["total"]
        name = venue_names.get(vc, vc)
        print(f"  {name:>6} {n:>8} {b['fav1_odds_sum']/n:>9.1f}倍 {b['fav2_odds_sum']/n:>9.1f}倍 "
              f"{b['fav1_win']/n*100:>9.1f}% {b['fav2_win']/n*100:>9.1f}% "
              f"{b['exacta']/n*100:>9.1f}%")


def print_summary(races: list[dict]) -> None:
    """結論をまとめる。"""
    print("\n" + "=" * 80)
    print("■ まとめ: オッズと1-2番人気の信頼性の関係")
    print("=" * 80)

    # 堅い vs 混戦
    tight = [r for r in races if r["fav1_odds"] <= 3.0 and r["fav2_odds"] <= 5.0]
    mixed = [r for r in races if r["fav1_odds"] > 4.0 or r["fav2_odds"] > 8.0]

    if tight and mixed:
        t_n = len(tight)
        m_n = len(mixed)
        t_fav_win = sum(1 for r in tight if r["fav1_finish"] == 1 or r["fav2_finish"] == 1)
        m_fav_win = sum(1 for r in mixed if r["fav1_finish"] == 1 or r["fav2_finish"] == 1)
        t_exacta = sum(1 for r in tight
                       if (r["fav1_finish"] == 1 and r["fav2_finish"] == 2)
                       or (r["fav2_finish"] == 1 and r["fav1_finish"] == 2))
        m_exacta = sum(1 for r in mixed
                       if (r["fav1_finish"] == 1 and r["fav2_finish"] == 2)
                       or (r["fav2_finish"] == 1 and r["fav1_finish"] == 2))

        print(f"""
  ┌──────────────────────────────────────────────────────────────┐
  │ 【堅いレース】 1人気≤3倍 & 2人気≤5倍  ({t_n}レース)           │
  │   1-2人気のどちらかが1着: {t_fav_win/t_n*100:.1f}%                       │
  │   馬単 1→2 or 2→1: {t_exacta/t_n*100:.1f}%                            │
  │                                                              │
  │ 【混戦レース】 1人気>4倍 or 2人気>8倍  ({m_n}レース)           │
  │   1-2人気のどちらかが1着: {m_fav_win/m_n*100:.1f}%                       │
  │   馬単 1→2 or 2→1: {m_exacta/m_n*100:.1f}%                            │
  │                                                              │
  │ → 堅いレースでは1-2人気が信頼できる                            │
  │ → 混戦レースでは荒れやすい → 裏目買い（X→1）を厚めに           │
  └──────────────────────────────────────────────────────────────┘
""")
    else:
        print("\n  ※データ不足のため比較できません\n")


def main():
    parser = argparse.ArgumentParser(description="オッズ別 人気馬信頼性分析")
    parser.add_argument("--db", default="data/nankan.db",
                        help="nankan.db のパス (default: data/nankan.db)")
    args = parser.parse_args()

    db_path = args.db
    if not Path(db_path).exists():
        print(f"ERROR: {db_path} が見つかりません。")
        print(f"Usage: python scripts/odds_reliability_analysis.py --db /path/to/nankan.db")
        return

    conn = get_connection(db_path)
    races = fetch_race_data(conn)
    conn.close()

    print(f"対象レース数: {len(races)}")
    if not races:
        print("データがありません。scrape を先に実行してください。")
        return

    # 各分析を実行
    analyze_by_fav1_odds(races)
    analyze_by_fav2_odds(races)
    analyze_odds_gap(races)
    analyze_combined_odds_level(races)
    analyze_fav1_odds_threshold_detail(races)
    analyze_venue_comparison(races)
    print_summary(races)


if __name__ == "__main__":
    main()
