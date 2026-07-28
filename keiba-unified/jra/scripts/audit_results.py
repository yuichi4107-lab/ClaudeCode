# -*- coding: utf-8 -*-
"""prediction_results の独立監査（週次cron想定・月曜18:00）

本番の照合ロジック(backtest_legacy.check_hit=払戻行マッチ)とは独立に、
着順(results.finish_position)から的中を再判定し、記録済みの
prediction_results と突合する。不一致があればTelegramへ警告する。

2026-06-20〜07-04の払戻文字化け事故（的中が外れ扱いで1か月過小報告、
2026-07-05修復）は、この監査があれば初週で検知できた。再発防止の要。

使い方:
    python3 audit_results.py            # 直近14日
    python3 audit_results.py --days 30
    python3 audit_results.py --db /path/to/other.db --no-notify
"""
import argparse
import os
import sqlite3
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))

DEFAULT_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "keiba_live.db")

from bet_constants import KNOWN_BET_TYPES

NORM_BT = {"3連複": "三連複", "3連単": "三連単"}


def _nums(combo):
    return [int(x) for x in combo.replace("→", " ").replace("-", " ").split()]


def _finish_order(cur, race_id):
    cur.execute("""SELECT horse_number FROM results
                   WHERE race_id = ? AND finish_position > 0
                   ORDER BY finish_position""", (race_id,))
    return [int(r[0]) for r in cur.fetchall()]


def _hit_by_results(bet_type, nums, top):
    """着順のみから的中を判定（払戻行を一切見ない独立ロジック）"""
    if len(top) < 3:
        return None  # 判定不能
    bt = NORM_BT.get(bet_type, bet_type)
    if bt == "単勝":
        return nums[0] == top[0]
    if bt == "複勝":
        return nums[0] in top[:3]
    if bt == "ワイド":
        return len(set(nums) & set(top[:3])) == 2
    if bt == "馬連":
        return set(nums) == set(top[:2])
    if bt == "馬単":
        return nums == top[:2]
    if bt == "三連複":
        return set(nums) == set(top[:3])
    if bt == "三連単":
        return nums == top[:3]
    return None


def _payout_lookup(cur, race_id, bet_type, nums):
    bt = NORM_BT.get(bet_type, bet_type)
    key = tuple(sorted(nums))
    cur.execute("SELECT combination, payout FROM payouts WHERE race_id = ? AND bet_type = ?",
                (race_id, bt))
    for comb, po in cur.fetchall():
        try:
            if tuple(sorted(_nums(comb))) == key:
                return int(po)
        except ValueError:
            continue
    return 0


def audit(db_path, days, notify):
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = conn.cursor()
    cur2 = conn.cursor()
    since = (date.today() - timedelta(days=days)).strftime("%Y-%m-%d")

    issues = []

    # 0) 期間内の文字化け払戻
    ph = ",".join("?" * len(KNOWN_BET_TYPES))
    cur.execute(f"""SELECT COUNT(*) FROM payouts p JOIN races r ON p.race_id = r.race_id
                    WHERE r.date >= ? AND p.bet_type NOT IN ({ph})""",
                (since, *KNOWN_BET_TYPES))
    garbled = cur.fetchone()[0]
    if garbled:
        issues.append(f"未知の券種名の払戻 {garbled}行（文字化け疑い）")

    # 0.5) 欠落日検知: 買い予測があるのに prediction_results が1行も無い日
    #      （結果取得が失敗したまま再試行されず、累計から静かに抜け落ちるパターン。
    #        2026年に5開催日が該当していた事故の再発検知 2026-07-08追加）
    cur.execute("""SELECT DISTINCT p.date FROM predictions p
                   WHERE p.date >= ? AND p.date < date('now', 'localtime') AND p.amount > 0
                     AND NOT EXISTS (SELECT 1 FROM prediction_results pr WHERE pr.date = p.date)
                   ORDER BY p.date""", (since,))
    missing_days = [r[0] for r in cur.fetchall()]
    if missing_days:
        issues.append(f"未精算の開催日 {len(missing_days)}日: {', '.join(missing_days)}"
                      f"（check_results.py <日付> --no-notify でリプレイ精算を）")

    # 1) prediction_results をレース×ソース単位で独立再計算と突合
    cur.execute("""SELECT date, race_id, source, bet_type, hit, payout
                   FROM prediction_results WHERE date >= ?""", (since,))
    recorded = cur.fetchall()
    checked = mismatch = 0
    details = []
    for d, rid, src, bt_rec, hit_rec, payout_rec in recorded:
        top = _finish_order(cur2, rid)
        if len(top) < 3:
            continue
        cur2.execute("""SELECT bet_type, combination, amount FROM predictions
                        WHERE date = ? AND race_id = ? AND source = ? AND amount > 0""",
                     (d, rid, src))
        bets = cur2.fetchall()
        if not bets:
            continue
        hit2 = 0
        payout2 = 0
        for bt, comb, amt in bets:
            try:
                nums = _nums(comb)
            except ValueError:
                continue
            h = _hit_by_results(bt, nums, top)
            if h:
                hit2 = 1
                payout2 += _payout_lookup(cur2, rid, bt, nums) * (int(amt) // 100)
        checked += 1
        if int(hit_rec) != hit2 or int(payout_rec) != payout2:
            mismatch += 1
            details.append(f"{d} {rid} {src}: 記録 hit={hit_rec}/payout={payout_rec} "
                           f"⇔ 再計算 hit={hit2}/payout={payout2}")
    if mismatch:
        issues.append(f"prediction_results 不一致 {mismatch}/{checked}件")

    print(f"監査期間: {since}〜 / 突合 {checked}件 / 不一致 {mismatch}件 / 文字化け {garbled}行")
    for line in details[:10]:
        print("  " + line)
    if len(details) > 10:
        print(f"  ...他{len(details) - 10}件")

    if issues:
        msg = ("🔍 *JRA結果データ 週次監査: 異常検知*\n"
               + "\n".join("・" + s for s in issues)
               + f"\n(期間 {since}〜、詳細は data/logs/audit.log)")
        print("\n" + msg)
        if notify:
            try:
                from check_results import send_telegram
                send_telegram(msg)
                print("Telegram警告送信済み")
            except Exception as e:
                print(f"Telegram送信失敗: {e}")
        return 1
    print("監査OK: 異常なし")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--no-notify", action="store_true")
    args = ap.parse_args()
    sys.exit(audit(args.db, args.days, not args.no_notify))


if __name__ == "__main__":
    main()
