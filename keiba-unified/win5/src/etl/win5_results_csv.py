"""win5_results_2026.csv（手動転記の実WIN5払戻）を読み込む。突合検算に使う。"""

import csv
from datetime import date


def load_win5_results(csv_path) -> list[dict]:
    """先頭の # コメント行を除外し、date と payout_yen を取り出す。

    payout_yen が空欄（キャリーオーバー/不的中）の場合は None。
    """
    with open(csv_path, encoding="utf-8") as f:
        lines = [ln for ln in f if not ln.lstrip().startswith("#")]
    reader = csv.DictReader(lines)
    out: list[dict] = []
    for r in reader:
        d = (r.get("date") or "").strip()
        if not d:
            continue
        pay = (r.get("payout_yen") or "").strip()
        out.append(
            {
                "date": date.fromisoformat(d),
                "payout_yen": float(pay) if pay else None,
            }
        )
    return out
