"""WIN5 キャリーオーバー構造のEV分析。

予測スキルではなく配当構造でのエッジを検証する。
WIN5は払戻率70%（売上の70%が当選プールへ）。的中者0の週は全プールが翌週へ繰越(CO)。
そのため「繰越が大きい週」だけ買えば、当週プール = 0.70×売上 + 繰越 となり
集団的な期待回収率 = 0.70 + 繰越/売上 が 1.0 を超え得る（構造的+EV）。

このスクリプトは win5_events から各週の「繰越流入(carried_in)」を再構成し、
carried_in/売上 のしきい値ごとに「その週だけ買った場合の回収率」を集計する。

使い方:
  PYTHONPATH=src python scripts/analyze_carryover_ev.py
"""

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def load_events(db_path: str):
    c = sqlite3.connect(db_path)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT event_date, payout, carryover, num_winners, total_sales "
        "FROM win5_events ORDER BY event_date"
    ).fetchall()
    c.close()
    return [dict(r) for r in rows]


def reconstruct(events):
    """各週の carried_in（前週までの繰越流入）を再構成して付与する。"""
    carry = 0.0
    out = []
    for e in events:
        sales = e["total_sales"] or 0.0
        nwin = e["num_winners"] or 0
        payout = e["payout"]
        hit = (payout is not None) and (nwin and nwin > 0)
        rec = dict(e)
        rec["carried_in"] = carry
        rec["hit"] = hit
        rec["sales"] = sales
        # 当週に当選者が払い戻した総額（円）
        rec["paid_out"] = (payout or 0.0) * nwin if hit else 0.0
        rec["co_ratio"] = (carry / sales) if sales else 0.0
        rec["return_ratio"] = (rec["paid_out"] / sales) if sales else 0.0
        if hit:
            carry = 0.0
        else:
            # 当週プール(0.70×売上)+流入 が翌週へ。COフィールドがあればそれを採用
            carry = e["carryover"] if e["carryover"] is not None else carry + 0.70 * sales
        out.append(rec)
    return out


def summarize(recs, thresholds):
    print(f"総イベント数={len(recs)}  的中週={sum(r['hit'] for r in recs)}  "
          f"繰越週={sum(not r['hit'] for r in recs)}")
    print(f"全期間: 総売上={sum(r['sales'] for r in recs):,.0f}  "
          f"総払戻={sum(r['paid_out'] for r in recs):,.0f}  "
          f"全週回収率={sum(r['paid_out'] for r in recs)/max(1,sum(r['sales'] for r in recs)):.3f}")
    print("\n=== 戦略: carried_in/売上 >= しきい値 の週だけ均等basketで買う ===")
    print(f"{'閾値':>6} {'対象週':>5} {'内的中':>5} {'投下(売上和)':>16} {'回収(払戻和)':>16} {'回収率':>7}")
    for th in thresholds:
        sel = [r for r in recs if r["co_ratio"] >= th]
        bet = sum(r["sales"] for r in sel)
        ret = sum(r["paid_out"] for r in sel)
        nhit = sum(r["hit"] for r in sel)
        rr = ret / bet if bet else 0.0
        print(f"{th:>6.2f} {len(sel):>5} {nhit:>5} {bet:>16,.0f} {ret:>16,.0f} {rr:>7.3f}")
    print("\n=== 繰越が乗った的中週（carried_in>0 で hit）= 構造的にプールが膨らんだ週 ===")
    boosted = [r for r in recs if r["hit"] and r["carried_in"] > 0]
    if not boosted:
        print("  なし（2021-2026で繰越流入後に的中した週は未収集 or 0）")
    for r in sorted(boosted, key=lambda x: -x["co_ratio"]):
        print(f"  {r['event_date']}: carried_in={r['carried_in']:,.0f} sales={r['sales']:,.0f} "
              f"co_ratio={r['co_ratio']:.2f} return_ratio={r['return_ratio']:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--win5-db", default="data/win5.db")
    args = ap.parse_args()
    recs = reconstruct(load_events(args.win5_db))
    summarize(recs, thresholds=[0.0, 0.10, 0.20, 0.30, 0.40, 0.50])
    print("\n注: 回収率>1.0 が構造的+EVの目安（払戻率0.70がベースライン）。")
    print("ただし個人が捕捉するには的中が必要で分散は極大（多くの週は外れる）。")


if __name__ == "__main__":
    main()
