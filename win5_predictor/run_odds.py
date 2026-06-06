#!/usr/bin/env python3
"""単勝オッズ＋人気順だけで WIN5 買い目を組み立てる。

使い方:
    python run_odds.py [odds.csv] [--budget 10000] [--beta 1.0] [--max-points 20000]

odds.csv 列: race(1..5), umaban, odds, horse(任意), pop(任意=人気順)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from popularity import (  # noqa: E402
    best_within_budget,
    combination_fair_odds,
    load_target_races,
    optimize_win5,
)


def yen(x) -> str:
    if x is None or (isinstance(x, float) and (x != x or x == float("inf"))):
        return "-"
    return f"{int(round(x)):,}円"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default="data/sample_target_odds.csv")
    ap.add_argument("--budget", type=int, default=10_000, help="予算（円）")
    ap.add_argument("--beta", type=float, default=1.0, help="人気-穴バイアス補正（>1で本命寄り）")
    ap.add_argument("--max-points", type=int, default=20_000, help="フロンティア探索の上限点数")
    args = ap.parse_args()

    races = load_target_races(args.csv, beta=args.beta)
    if len(races) != 5:
        print(f"⚠ レース数が {len(races)} 件です。WIN5 は 5 レース必要です。")
        return

    print("=" * 64)
    print(f"対象レースのオッズ → 暗黙勝率（beta={args.beta}）")
    print("-" * 64)
    for r in races:
        tops = ", ".join(
            f"{h.umaban}番 {h.prob*100:.1f}%({h.odds:.1f}倍)" for h in r.top(4)
        )
        print(f"  {r.name}: {tops} ...")
        if r.pop_mismatch:
            print(f"      ⚠ 入力人気とオッズ順の不一致: 馬番 {r.pop_mismatch}")

    print("\n" + "=" * 64)
    print("買い目フロンティア（点数 vs 的中確率）")
    print("-" * 64)
    print("   点数     費用       的中率    損益分岐配当   各レース購入頭数")
    for s in optimize_win5(races, max_points=args.max_points):
        ks = "×".join(str(pr["k"]) for pr in s.per_race)
        print(
            f"  {s.points:>5}  {yen(s.cost_yen):>10}  {s.hit_prob*100:6.2f}%  {yen(s.breakeven_payout_yen):>12}   {ks}"
        )

    print("\n" + "=" * 64)
    print(f"推奨買い目（予算 {yen(args.budget)} 以内で的中率最大）")
    print("-" * 64)
    best = best_within_budget(races, budget_yen=args.budget)
    print(f"  点数 {best.points}  費用 {yen(best.cost_yen)}  的中率 {best.hit_prob*100:.2f}%")
    print(f"  損益分岐配当（これ以上の払戻で黒字）: {yen(best.breakeven_payout_yen)}")
    for pr in best.per_race:
        print(f"   {pr['race']}: 馬番 {pr['umaban']}  （上位{pr['k']}頭・的中率{pr['cum_prob']*100:.1f}%）")
    print(f"\n  参考: 本命ライン理論オッズ = {combination_fair_odds(races):,.0f} 倍")


if __name__ == "__main__":
    main()
