#!/usr/bin/env python3
"""WIN5 当選馬の傾向クロス集計（レース順 × 人気/オッズ）。

使い方:
    python run_crosstab.py [data/win5_results_2026.csv]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from popularity.loader import load_results  # noqa: E402
from popularity import crosstab as ct  # noqa: E402
from popularity.position_plan import position_buy_plan, position_frontier  # noqa: E402


def _print_df(df, pct=False):
    fmt = (lambda v: f"{v:5.1f}") if pct else (lambda v: f"{int(v):4d}")
    cols = list(df.columns)
    print("           " + "".join(f"{c:>9}" for c in cols))
    for idx, row in df.iterrows():
        print(f"  {str(idx):>7}  " + "".join(f"{fmt(row[c]):>9}" for c in cols))


def _yen(x):
    if x is None or (isinstance(x, float) and (x != x or x == float("inf"))):
        return "-"
    return f"{int(round(x)):,}円"


def main(path: str, budget: int = 10000):
    df = load_results(path)
    n = df[["p1", "p2", "p3", "p4", "p5"]].notna().all(axis=1).sum()
    print("=" * 60)
    print(f"WIN5 傾向クロス集計  対象 {n} 回（{df['date'].min().date()}〜{df['date'].max().date()}）")

    print("\n■ レース順 × 人気バケット（件数）")
    print("-" * 60)
    _print_df(ct.position_by_popbucket(df))

    print("\n■ レース順 × 人気バケット（行方向 %）")
    print("-" * 60)
    _print_df(ct.position_by_popbucket(df, normalize=True), pct=True)

    print("\n■ レース順ごとの堅さ指標（1-3人気%が高い＝堅い）")
    print("-" * 60)
    ps = ct.position_summary(df).sort_values("1-3人気%", ascending=False)
    print("   レース順   n   1-3人気%   平均人気  中央人気  最大人気")
    for _, r in ps.iterrows():
        print(
            f"    {r['レース順']:>5}  {int(r['n']):>3}   {r['1-3人気%']:6.1f}    {r['平均人気']:6.2f}   {r['中央人気']:5.1f}    {int(r['最大人気']):>4}"
        )
    solid = ps.iloc[0]["レース順"]
    rough = ps.iloc[-1]["レース順"]
    print(f"\n  → 最も堅い: {solid}　最も荒れやすい: {rough}")

    print("\n■ 1回(5R)あたり 3番人気以内の勝ち馬が何頭出たか")
    print("-" * 60)
    fpw = ct.favorites_per_week(df)
    total = fpw.sum()
    for idx, v in fpw.items():
        bar = "█" * int(v)
        print(f"   {idx:>3}: {int(v):>2}回 {bar}")
    print(f"   （平均 {sum(int(k[0])*v for k,v in fpw.items())/total:.2f} 頭/回）")

    print("\n■ オッズ × 人気 2次元マップ")
    print("-" * 60)
    om = ct.odds_by_pop_crosstab(df)
    if om is None:
        print("  ⚠ 当選馬の単勝オッズ列(o1..o5)が無いため未集計。")
        print("    CSV に o1..o5（各レース当選馬の単勝オッズ倍率）を足すと表示されます。")
    else:
        _print_df(om)

    # ---- 傾向ベースの買い目提案 ----
    print("\n■ 傾向ベース買い目提案（予算 " + _yen(budget) + " 内で的中率最大の頭数配分）")
    print("-" * 60)
    print("   実績の『上位k番人気以内で決まる割合』から、堅い回は絞り荒れる回は厚く配分")
    plan = position_buy_plan(df, budget_yen=budget)
    print(f"\n   合計 {plan.points}点 / {_yen(plan.cost_yen)} / 的中率 {plan.hit_prob*100:.1f}% / 損益分岐配当 {_yen(plan.breakeven_payout_yen)}")
    for pp in plan.per_pos:
        bar = "■" * pp["k"]
        print(f"    {pp['pos']}: 上位{pp['k']}番人気まで購入  (この回が決まる実績 {pp['cum_prob']*100:.0f}%)  {bar}")
    print("\n   ※『上位k番人気』は当日の人気順で買う。n=28の実績ベースで傾向は暫定。")
    print("   フロンティア（点数→的中率）:")
    for p in position_frontier(df, max_points=min(budget // 100, 5000)):
        ks = "×".join(str(x) for x in p.k_per_pos)
        print(f"     {p.points:>4}点 {_yen(p.cost_yen):>9}  的中{p.hit_prob*100:5.1f}%  配分 {ks}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default="data/win5_results_2026.csv")
    ap.add_argument("--budget", type=int, default=10000, help="予算（円）")
    args = ap.parse_args()
    main(args.csv, budget=args.budget)
