#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
競馬予想 バックテスト + レポート出力
Steps 7 (バックテスト), 8 (レポート)
"""

import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from predictor_v1 import get_conn


def _normalize_combo(combo):
    """組合せ文字列を正規化 (スペース除去・矢印統一: '4 - 15'/'4 → 15' → '4-15')

    馬単・三連単はdb.netkeiba経路が「a → b」、当日ライブ経路が「a - b」(順序保持)で
    保存されるため、区切りを統一しないと的中判定が経路依存で失敗する。
    """
    return combo.replace(" ", "").replace("→", "-")


def check_hit(conn, race_id, bet_type, bets):
    """的中判定: 買い目が当たったか確認し、払戻金を返す"""
    c = conn.cursor()
    c.execute("SELECT combination, payout FROM payouts WHERE race_id = ? AND bet_type = ?",
              (race_id, bet_type))
    winning = {}
    for row in c.fetchall():
        winning[_normalize_combo(row[0])] = row[1]

    total_payout = 0
    hit_details = []
    for bet in bets:
        combo = _normalize_combo(bet["combination"])
        if combo in winning:
            # 払戻は100円単位の金額なので、賭け金に応じて計算
            payout_per_100 = winning[combo]
            units = bet["amount"] // 100
            payout = payout_per_100 * units
            total_payout += payout
            hit_details.append({
                "combination": combo,
                "amount": bet["amount"],
                "payout": payout,
                "payout_per_100": payout_per_100,
            })

    return {
        "hit": len(hit_details) > 0,
        "total_payout": total_payout,
        "hit_details": hit_details,
        "winning_combo": winning,
    }


def run_single_day(conn, date):
    """1日分のバックテスト"""
    prediction = predict_day(conn, date)
    if not prediction["races"]:
        return None

    day_result = {
        "date": date,
        "races": [],
        "total_bet": 0,
        "total_payout": 0,
    }

    for race in prediction["races"]:
        race_id = race["race_id"]
        bets = race["bets"]
        bet_type = bets["bet_type"]
        bet_list = bets["bets"]

        if not bet_list or not bet_type:
            continue

        hit_result = check_hit(conn, race_id, bet_type, bet_list)
        bet_total = sum(b["amount"] for b in bet_list)

        race_result = {
            "race_id": race_id,
            "race_info": race["race_info"],
            "quality": race["quality"],
            "bet_type": bet_type,
            "bets": bet_list,
            "bet_total": bet_total,
            "hit": hit_result["hit"],
            "payout": hit_result["total_payout"],
            "hit_details": hit_result["hit_details"],
            "winning_combo": hit_result["winning_combo"],
            "scored_horses": race["scored_horses"][:5],
            "horse_names": race["horse_names"],
        }

        day_result["races"].append(race_result)
        day_result["total_bet"] += bet_total
        day_result["total_payout"] += hit_result["total_payout"]

    day_result["roi"] = (day_result["total_payout"] / day_result["total_bet"]
                          if day_result["total_bet"] > 0 else 0)
    day_result["profit"] = day_result["total_payout"] - day_result["total_bet"]

    return day_result


def format_day_report(day_result, conn):
    """1日分のレポートをフォーマット"""
    lines = []
    date = day_result["date"]
    lines.append(f"=== {date} 競馬予想レポート ===")
    lines.append("")

    total_races_today = 0
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM races WHERE date = ? AND surface IN ('芝', 'ダート')", (date,))
    total_races_today = c.fetchone()[0]

    lines.append(f"【選定レース: {len(day_result['races'])}レース / 全{total_races_today}レース中】")
    lines.append("")

    for race in day_result["races"]:
        ri = race["race_info"]
        q = race["quality"]

        venue = ri["venue"]
        r_num = ri["race_number"]
        name = ri["name"]
        surface = ri["surface"]
        distance = ri["distance"]
        condition = ri["track_condition"]
        cls = ri["class"]

        lines.append(f"■ {venue} {r_num}R {name} ({cls}) {surface}{distance}m {condition}")

        reasons = ", ".join(q["reasons"]) if q["reasons"] else "総合評価"
        lines.append(f"  選定理由: 品質スコア {q['quality_score']:.2f} ({reasons})")
        lines.append("")

        # 上位5頭
        lines.append("  【スコア上位5頭】")
        for i, h in enumerate(race.get("scored_horses", [])[:5]):
            hname = race["horse_names"].get(h["horse_id"], "???")
            lines.append(f"    {i+1}. {h['horse_number']:2d}番 {hname:<10s} "
                          f"スコア:{h['total_score']:.3f} "
                          f"オッズ:{h['odds_win'] or 0:.1f}")
        lines.append("")

        # 買い目
        lines.append(f"  推奨: {race['bet_type']}")
        lines.append("  買い目:")
        for bet in race["bets"]:
            lines.append(f"    {bet['combination']:>12s}  {bet['amount']:>5,}円")

        # 的中結果
        if race["hit"]:
            lines.append(f"  ★ 的中！ 払戻: {race['payout']:,}円")
            for hd in race["hit_details"]:
                lines.append(f"    {hd['combination']} → {hd['payout_per_100']:,}円 × {hd['amount']//100}枚 = {hd['payout']:,}円")
        else:
            winning = race.get("winning_combo", {})
            if winning:
                win_str = ", ".join(f"{k}({v:,}円)" for k, v in winning.items())
                lines.append(f"  × ハズレ（実際: {win_str}）")
            else:
                lines.append("  × ハズレ")

        lines.append(f"  小計: 投資{race['bet_total']:,}円 → 回収{race['payout']:,}円")
        lines.append("")

    lines.append("=" * 40)
    lines.append(f"本日合計: 投資 {day_result['total_bet']:,}円")
    lines.append(f"本日回収: {day_result['total_payout']:,}円")
    lines.append(f"本日収支: {day_result['profit']:+,}円")
    lines.append(f"本日回収率: {day_result['roi']*100:.1f}%")
    lines.append("=" * 40)

    return "\n".join(lines)


def run_backtest(conn, start_date, end_date):
    """期間指定のバックテスト"""
    c = conn.cursor()
    c.execute("""SELECT DISTINCT date FROM races
                 WHERE date BETWEEN ? AND ?
                   AND surface IN ('芝', 'ダート')
                 ORDER BY date""", (start_date, end_date))
    dates = [row[0] for row in c.fetchall()]

    print(f"バックテスト期間: {start_date} 〜 {end_date}")
    print(f"開催日数: {len(dates)}")
    print("=" * 60)

    results = []
    total_bet = 0
    total_payout = 0
    win_days = 0
    total_days = 0
    total_races_bet = 0
    total_races_hit = 0

    for i, date in enumerate(dates):
        day = run_single_day(conn, date)
        if day is None:
            continue

        total_days += 1
        total_bet += day["total_bet"]
        total_payout += day["total_payout"]

        for race in day["races"]:
            total_races_bet += 1
            if race["hit"]:
                total_races_hit += 1

        if day["profit"] > 0:
            win_days += 1

        results.append(day)

        # 進捗表示
        roi_so_far = (total_payout / total_bet * 100) if total_bet > 0 else 0
        mark = "○" if day["profit"] > 0 else "×"
        print(f"  {date} {mark} 投資:{day['total_bet']:>6,}円 "
              f"回収:{day['total_payout']:>7,}円 "
              f"収支:{day['profit']:>+7,}円 "
              f"(累計ROI:{roi_so_far:.1f}%)")

    # サマリー
    print()
    print("=" * 60)
    print("【バックテスト結果サマリー】")
    print("=" * 60)
    print(f"期間: {start_date} 〜 {end_date}")
    print(f"開催日数: {total_days}")
    print(f"ベットレース数: {total_races_bet}")
    print(f"的中レース数: {total_races_hit}")
    print(f"レース的中率: {total_races_hit/total_races_bet*100:.1f}%" if total_races_bet > 0 else "N/A")
    print(f"日単位勝率: {win_days/total_days*100:.1f}% ({win_days}/{total_days})" if total_days > 0 else "N/A")
    print(f"総投資額: {total_bet:,}円")
    print(f"総回収額: {total_payout:,}円")
    print(f"総収支: {total_payout - total_bet:+,}円")
    print(f"回収率: {total_payout/total_bet*100:.1f}%" if total_bet > 0 else "N/A")
    print("=" * 60)

    # 月別集計
    if results:
        print()
        print("【月別集計】")
        monthly = {}
        for day in results:
            month = day["date"][:7]
            if month not in monthly:
                monthly[month] = {"bet": 0, "payout": 0, "days": 0, "win_days": 0}
            monthly[month]["bet"] += day["total_bet"]
            monthly[month]["payout"] += day["total_payout"]
            monthly[month]["days"] += 1
            if day["profit"] > 0:
                monthly[month]["win_days"] += 1

        print(f"{'月':>8s} {'投資':>9s} {'回収':>9s} {'収支':>9s} {'ROI':>6s} {'勝率':>6s}")
        for month in sorted(monthly.keys()):
            m = monthly[month]
            roi = m["payout"] / m["bet"] * 100 if m["bet"] > 0 else 0
            wr = m["win_days"] / m["days"] * 100 if m["days"] > 0 else 0
            print(f"{month:>8s} {m['bet']:>8,}円 {m['payout']:>8,}円 "
                  f"{m['payout']-m['bet']:>+8,}円 {roi:>5.1f}% {wr:>5.1f}%")

    return results


def main():
    conn = get_conn()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 backtest.py 2025                    # 2025年のバックテスト")
        print("  python3 backtest.py 2025-01-01 2025-06-30   # 期間指定バックテスト")
        print("  python3 backtest.py report 2025-03-08       # 特定日のレポート")
        sys.exit(1)

    if sys.argv[1] == "report":
        date = sys.argv[2]
        day = run_single_day(conn, date)
        if day:
            print(format_day_report(day, conn))
        else:
            print(f"{date} のデータがありません")
        conn.close()
        return

    if len(sys.argv) >= 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
    else:
        year = sys.argv[1]
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31"

    run_backtest(conn, start_date, end_date)
    conn.close()


if __name__ == "__main__":
    main()
