"""収集した Win5Event の払戻を win5_results_2026.csv と突合する純粋関数"""


def crosscheck_payouts(events, csv_rows, tol: float = 1.0) -> list[tuple]:
    """日付一致するイベントの payout を CSV と比較し、不一致のみ返す。

    返り値: [(date, event_payout, csv_payout), ...]
    両方 None は一致扱い。片方のみ None、または差が tol 超は不一致。
    """
    csv_by_date = {r["date"]: r["payout_yen"] for r in csv_rows}
    mismatches: list[tuple] = []
    for ev in events:
        d = ev.event_date
        if d not in csv_by_date:
            continue
        csv_pay = csv_by_date[d]
        ev_pay = ev.payout
        if csv_pay is None and ev_pay is None:
            continue
        if csv_pay is None or ev_pay is None:
            mismatches.append((d, ev_pay, csv_pay))
            continue
        if abs(float(ev_pay) - float(csv_pay)) > tol:
            mismatches.append((d, ev_pay, csv_pay))
    return mismatches
