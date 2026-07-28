#!/usr/bin/env python3
"""的中馬券の配当帯と収支の関係を分析"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from predictor import get_conn
from backtest import run_single_day

conn = get_conn()
c = conn.cursor()

c.execute("""SELECT DISTINCT date FROM races
             WHERE date BETWEEN '2025-01-01' AND '2025-12-31'
               AND surface IN ('芝', 'ダート') ORDER BY date""")
dates = [row[0] for row in c.fetchall()]

# 馬券種別・配当帯別の集計
stats = {
    "馬連": {"bins": {}, "total_bet": 0, "total_payout": 0, "races": 0, "hits": 0},
    "三連複": {"bins": {}, "total_bet": 0, "total_payout": 0, "races": 0, "hits": 0},
}

# 配当帯の定義
def payout_bin(payout_per_100):
    if payout_per_100 < 300:
        return "~300"
    elif payout_per_100 < 500:
        return "300-500"
    elif payout_per_100 < 1000:
        return "500-1K"
    elif payout_per_100 < 3000:
        return "1K-3K"
    elif payout_per_100 < 5000:
        return "3K-5K"
    elif payout_per_100 < 10000:
        return "5K-10K"
    else:
        return "10K+"

for i, date in enumerate(dates):
    day = run_single_day(conn, date)
    if not day:
        continue

    for race in day["races"]:
        bt = race["bet_type"]
        if bt not in stats:
            continue

        s = stats[bt]
        s["races"] += 1
        s["total_bet"] += race["bet_total"]
        s["total_payout"] += race["payout"]
        if race["hit"]:
            s["hits"] += 1

        # 的中時の配当帯を記録
        if race["hit"]:
            for hd in race["hit_details"]:
                p100 = hd["payout_per_100"]
                bname = payout_bin(p100)
                if bname not in s["bins"]:
                    s["bins"][bname] = {"count": 0, "bet": 0, "payout": 0}
                s["bins"][bname]["count"] += 1
                s["bins"][bname]["bet"] += hd["amount"]
                s["bins"][bname]["payout"] += hd["payout"]

    if (i + 1) % 30 == 0:
        print(f"  {i+1}/{len(dates)}...")

print()
for bt, s in stats.items():
    roi = s["total_payout"] / s["total_bet"] * 100 if s["total_bet"] > 0 else 0
    hr = s["hits"] / s["races"] * 100 if s["races"] > 0 else 0
    print(f"=== {bt} ===")
    print(f"  レース数: {s['races']}, 的中: {s['hits']} ({hr:.1f}%)")
    print(f"  投資: {s['total_bet']:,}円, 回収: {s['total_payout']:,}円, ROI: {roi:.1f}%")

    if s["bins"]:
        print(f"  {'配当帯':>10s} {'的中数':>6s} {'投資':>10s} {'回収':>10s} {'ROI':>6s}")
        bin_order = ["~300", "300-500", "500-1K", "1K-3K", "3K-5K", "5K-10K", "10K+"]
        for bname in bin_order:
            if bname in s["bins"]:
                b = s["bins"][bname]
                broi = b["payout"] / b["bet"] * 100 if b["bet"] > 0 else 0
                print(f"  {bname:>10s} {b['count']:>6d} {b['bet']:>9,}円 {b['payout']:>9,}円 {broi:>5.1f}%")
    print()

# 不的中レースの分析：当たっていたらどの配当帯だったか
print("=== 不的中レースの実際の配当 ===")
c2 = conn.cursor()
miss_payouts = {"馬連": [], "三連複": []}
for i, date in enumerate(dates):
    day = run_single_day(conn, date)
    if not day:
        continue
    for race in day["races"]:
        if not race["hit"] and race["bet_type"] in miss_payouts:
            # 実際の配当を取得
            wc = race.get("winning_combo", {})
            for combo, p in wc.items():
                miss_payouts[race["bet_type"]].append(p)

for bt, payouts in miss_payouts.items():
    if payouts:
        import numpy as np
        arr = np.array(payouts)
        print(f"{bt} 不的中時の実際配当: 中央値{int(np.median(arr)):,}円, "
              f"平均{int(np.mean(arr)):,}円, "
              f"1K未満{(arr < 1000).sum()}/{len(arr)} ({(arr < 1000).sum()/len(arr)*100:.0f}%)")

conn.close()
