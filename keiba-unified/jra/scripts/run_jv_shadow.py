# -*- coding: utf-8 -*-
# JV調教特徴量モデルのシャドー運用 (forward-test, 記録のみ・実弾なし):
#   デプロイ候補 model_jv_no_odds.pkl（現行C5b特徴量76＋調教8、学習≤2026-07-11）を
#   本番と同一のC5b構成（generate_bets_c5b + 品質no_odds + 閾値0.92）で走らせ、
#   source="morning_jv" として保存する。Telegram/X通知なし。cron 土日7:06想定。
# 判定: 2週末分の並走記録で現行morningと比較し、差し替え可否を最終決定（2026-07-26頃）。
# OOS実績: 3/14-15除外・@0.92でROI 94.4%（現行相当88.1%）、@0.94で100.7%（2026-07-12検証）
import os
import sys
from datetime import date as _date

sys.path.insert(0, os.path.dirname(__file__))
import model_v2
import model_v2_jv
import predictor_v1
from predictor_v1 import get_conn, select_races, generate_bets_c5b
from run_today import save_predictions
from scraper_legacy import init_db

RACE_BUDGET = 5000
THRESHOLD = 0.92
MODEL_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "data", "models", "model_jv_no_odds.pkl")


def jvdata_freshness_warning():
    """jvdata.sqlite（毎朝6:05更新）の鮮度チェック。3日以上古ければ警告"""
    import sqlite3
    try:
        c = sqlite3.connect(f"file:{model_v2_jv.JV_DB}?mode=ro", uri=True)
        latest = c.execute("SELECT MAX(train_date) FROM hanro").fetchone()[0]
        c.close()
        stale = True
        if latest:
            d = _date(int(latest[:4]), int(latest[4:6]), int(latest[6:8]))
            stale = (_date.today() - d).days > 3
        if stale:
            print(f"⚠ jvdata鮮度警告: hanro最新={latest}（調教特徴量が古い可能性。6:05の更新タスクを確認）")
            return False
    except Exception as e:
        print(f"⚠ jvdata読み込み不可: {e}")
        return False
    return True


def main():
    date_args = [a for a in sys.argv[1:] if len(a) >= 4 and a[:4].isdigit()]
    target = date_args[0] if date_args else _date.today().strftime("%Y-%m-%d")
    print(f"=== JV調教モデル shadow (source=morning_jv): {target} ===")
    jvdata_freshness_warning()

    conn = get_conn()
    init_db()

    # 調教特徴量込みのビルダーとJVモデルに差し替え（このプロセス内のみ）
    model_v2.build_features_for_date = model_v2_jv.build_features_for_date
    model_v2.MODEL_PATH = MODEL_PATH
    model_v2.FEATURE_COLS = model_v2_jv.FEATURE_COLS_NO_ODDS
    predictor_v1.QUALITY_THRESHOLD = 0.0
    predictor_v1.evaluate_race_quality = predictor_v1.evaluate_race_quality_no_odds

    all_races = select_races(conn, target)
    buy = [r for r in all_races if r["quality"]["quality_score"] >= THRESHOLD]
    skip = [r for r in all_races if r["quality"]["quality_score"] < THRESHOLD]
    print(f"JVモデル選定: 買い{len(buy)} / 見送り{len(skip)}")

    if buy:
        pred = {"date": target, "races": [
            {"race_id": r["race_id"], "quality": r["quality"],
             "bets": generate_bets_c5b(r["scored_horses"], {"race_id": r["race_id"]}, RACE_BUDGET)}
            for r in buy]}
        save_predictions(pred, conn, source="morning_jv")
    if skip:
        skipd = {"date": target, "races": [
            {"race_id": r["race_id"], "quality": r["quality"],
             "bets": {"bet_type": "見送り", "bets": [{"combination": "-", "amount": 0}]}}
            for r in skip]}
        save_predictions(skipd, conn, source="morning_jv")

    conn.close()
    print("DONE (Telegram/X通知なし・記録のみ)")


if __name__ == "__main__":
    main()
