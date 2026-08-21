# -*- coding: utf-8 -*-
# サンタンシャドー (forward-test, 記録のみ・実弾なし):
#   FULLライブモデル × 新馬未勝利・ダート・1400m以下・15頭以上 の三連単1点(モデル予測1-2-3着固定)。
#   2026-07-05 の全券種スイープ(19.4万構成)で唯一二段検証を生き残った構成のフォワード検証。
#   確認期間の利益が1的中依存だったため実弾化はせず、シャドーで証拠を蓄積する。
# source="live_santan" で保存。Telegram/X通知なし。cron 9:35想定（オッズ発表後、旧C3枠）。
# 結果集計は check_results.py が source別に独立表示する。
import sys, os
from datetime import date as _date
sys.path.insert(0, os.path.dirname(__file__))
import predictor_v1
from predictor_v1 import get_conn, select_races
from run_today import scrape_odds, save_predictions
from scraper_legacy import init_db

STAKE = 5000  # 1点flat（記録上の想定賭け金）


def main():
    date_args = [a for a in sys.argv[1:] if len(a) >= 4 and a[:4].isdigit()]
    target = date_args[0] if date_args else _date.today().strftime("%Y-%m-%d")
    print(f"=== santan shadow (source=live_santan): {target} ===")

    conn = get_conn()
    init_db()
    c = conn.cursor()

    c.execute("""SELECT race_id FROM races WHERE date=? AND surface='ダート'
                 AND distance<=1400 AND head_count>=15
                 AND (class LIKE '%未勝利%' OR class LIKE '%新馬%')""", (target,))
    targets = {r[0] for r in c.fetchall()}
    print(f"対象レース(新馬未勝利ダ1400m以下15頭以上): {len(targets)}")
    if not targets:
        conn.close()
        print("DONE (対象レースなし)")
        return

    # オッズ取得（FULLモデルの特徴量に必要。9:30 liveが取得済みでも冪等）
    ok = sum(1 for rid in sorted(targets) if scrape_odds(rid, conn, retries=2, verbose=False))
    print(f"オッズ: {ok}/{len(targets)}レース")

    # FULLライブモデル(デフォルトMODEL_PATH)で全レーススコアリング。品質フィルタは使わない
    predictor_v1.QUALITY_THRESHOLD = 0.0
    races = []
    for ev in select_races(conn, target):
        if ev["race_id"] not in targets:
            continue
        horses = ev["scored_horses"]
        if len(horses) < 3:
            continue
        combo = " - ".join(str(h["horse_number"]) for h in horses[:3])
        races.append({"race_id": ev["race_id"], "quality": ev["quality"],
                      "bets": {"bet_type": "三連単",
                               "bets": [{"combination": combo, "amount": STAKE}]}})
    print(f"記録: {len(races)}レース（三連単1点×{STAKE}円）")
    if races:
        save_predictions({"date": target, "races": races}, conn, source="live_santan")

    conn.close()
    print("DONE (Telegram/X通知なし・記録のみ)")


if __name__ == "__main__":
    main()
