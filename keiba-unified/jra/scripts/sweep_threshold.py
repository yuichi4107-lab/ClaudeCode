#!/usr/bin/env python3
"""閾値を変えてバックテスト結果を比較する"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import predictor
from backtest import run_backtest, get_conn

conn = get_conn()
thresholds = [0.60, 0.65, 0.70, 0.75, 0.80, 0.85]

print(f"{'閾値':>6s} {'レース数':>8s} {'的中率':>6s} {'日勝率':>6s} {'投資':>12s} {'回収':>12s} {'ROI':>6s}")
print("-" * 70)

for t in thresholds:
    predictor.QUALITY_THRESHOLD = t

    c = conn.cursor()
    c.execute("""SELECT DISTINCT date FROM races
                 WHERE date BETWEEN '2025-01-01' AND '2025-12-31'
                   AND surface IN ('芝', 'ダート') ORDER BY date""")
    dates = [row[0] for row in c.fetchall()]

    total_bet = 0
    total_payout = 0
    total_races = 0
    total_hits = 0
    win_days = 0
    total_days = 0

    for date in dates:
        from backtest import run_single_day
        day = run_single_day(conn, date)
        if day is None:
            continue
        total_days += 1
        total_bet += day["total_bet"]
        total_payout += day["total_payout"]
        for race in day["races"]:
            total_races += 1
            if race["hit"]:
                total_hits += 1
        if day["profit"] > 0:
            win_days += 1

    roi = total_payout / total_bet * 100 if total_bet > 0 else 0
    hit_rate = total_hits / total_races * 100 if total_races > 0 else 0
    day_win = win_days / total_days * 100 if total_days > 0 else 0

    print(f"{t:>6.2f} {total_races:>8d} {hit_rate:>5.1f}% {day_win:>5.1f}% "
          f"{total_bet:>11,}円 {total_payout:>11,}円 {roi:>5.1f}%")

conn.close()
