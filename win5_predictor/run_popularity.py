#!/usr/bin/env python3
"""人気分布ベース WIN5 モデル — レポート出力スクリプト。

使い方:
    python run_popularity.py                       # 既定 CSV を読み込む
    python run_popularity.py data/win5_results_2025.csv

人気（p1..p5）が未入力でも、配当・難易度などのメタ分析は実行する。
人気が入力されている回があれば、人気分布モデル・買い目戦略・ROI バックテストも出す。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from popularity import (  # noqa: E402
    PopularityModel,
    load_results,
    uniform_strategies,
    winning_popularities,
)
from popularity.backtest import backtest_range  # noqa: E402
from popularity.loader import data_coverage  # noqa: E402
from popularity import report  # noqa: E402


def yen(x) -> str:
    if x is None or (isinstance(x, float) and x != x):
        return "-"
    return f"{int(round(x)):,}円"


def hr(title: str = "") -> None:
    print("\n" + "=" * 60)
    if title:
        print(title)
        print("-" * 60)


def main(path: str) -> None:
    df = load_results(path)
    cov = data_coverage(df)

    hr("WIN5 結果データ概要")
    print(f"  対象回数        : {cov['rounds_total']} 回")
    print(f"  期間            : {df['date'].min().date()} 〜 {df['date'].max().date()}")
    print(f"  人気入力済みの回: {cov['rounds_with_pops']} 回（= {cov['races_with_pops']} レース）")
    print(f"  検証済みの回    : {cov['rounds_verified']} 回")

    # ---- メタ分析（人気不要）----
    hr("メタ分析（配当・難易度）")
    ps = report.payout_summary(df)
    ts = report.ticket_summary(df)
    print(f"  払戻金   n={ps['n']:>2}  中央値 {yen(ps['median'])}  平均 {yen(ps['mean'])}  最高 {yen(ps['max'])}  最低 {yen(ps['min'])}")
    print(f"  的中票数 n={ts['n']:>2}  中央値 {int(ts['median']):,}票  平均 {int(ts['mean']):,}票  最少 {int(ts['min']):,}票  最多 {int(ts['max']):,}票")
    dc = report.difficulty_correlation(df)
    print(f"  log(払戻)×log(票数) 相関: {dc['corr_log']:.3f}  （負＝票数が少ない回ほど高配当）")
    print("  グレード内訳:")
    for g, c in report.grade_counts(df).items():
        print(f"     {g}: {c} 回")

    co = report.carryover_rounds(df)
    hr("キャリーオーバー / 不的中の回")
    if len(co):
        for _, r in co.iterrows():
            print(f"  {r['date'].date()}  {r['race']}（{r['grade']}）  払戻 {yen(r['payout_yen'])}  票数 {int(r['hit_tickets']) if r['hit_tickets']==r['hit_tickets'] else 0}")
    else:
        print("  なし")

    # ---- 人気分布モデル（人気が入っていれば）----
    pops = winning_popularities(df)
    hr("人気分布モデル")
    if not pops:
        print("  ⚠ 人気データ（p1..p5）が未入力のため、モデル学習をスキップしました。")
        print("    CSV の p1..p5 を埋めると、勝率分布・買い目戦略・ROI が出力されます。")
        return

    model = PopularityModel().fit(pops)
    print(f"  学習レース数: {model.n_races}")
    print("  人気順位ごとの勝率 / 累積:")
    print("    rank   win%   cum%")
    for row in model.distribution():
        print(f"     {row['rank']:>2}   {row['win_prob']*100:5.1f}  {row['cum_prob']*100:5.1f}")

    hr("買い目戦略（5レース一律に上位 r 番人気を購入）")
    print("    r  per-race  WIN5的中率   点数      費用       損益分岐配当")
    for s in uniform_strategies(model, max_r=6):
        print(
            f"   {s['r']:>2}   {s['per_race_prob']*100:5.1f}%   {s['hit_prob']*100:7.3f}%  {s['points']:>6}  {yen(s['cost_yen']):>10}  {yen(s['breakeven_payout_yen'])}"
        )

    hr("ROI バックテスト（過去結果に当てはめ）")
    print("    r   回数  的中  的中率   費用計        払戻計        ROI")
    for b in backtest_range(df, max_r=6):
        roi_pct = b["roi"] * 100 if b["roi"] == b["roi"] else float("nan")
        print(
            f"   {b['r']:>2}   {b['rounds']:>3}  {b['hits']:>3}  {b['hit_rate']*100:5.1f}%  {yen(b['total_cost_yen']):>11}  {yen(b['total_return_yen']):>12}  {roi_pct:7.1f}%"
        )
    print("\n  ※ 払戻計はキャリーオーバー回（配当不明）の的中を含みません。")


if __name__ == "__main__":
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "data/win5_results_2025.csv"
    main(csv_path)
