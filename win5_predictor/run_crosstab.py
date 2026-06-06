#!/usr/bin/env python3
"""WIN5 当選馬の傾向クロス集計（レース順 × 人気/オッズ）。

使い方:
    python run_crosstab.py [data/win5_results_2026.csv]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from popularity.loader import load_results  # noqa: E402
from popularity import crosstab as ct  # noqa: E402


def _print_df(df, pct=False):
    fmt = (lambda v: f"{v:5.1f}") if pct else (lambda v: f"{int(v):4d}")
    cols = list(df.columns)
    print("           " + "".join(f"{c:>9}" for c in cols))
    for idx, row in df.iterrows():
        print(f"  {str(idx):>7}  " + "".join(f"{fmt(row[c]):>9}" for c in cols))


def main(path: str):
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


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data/win5_results_2026.csv")
