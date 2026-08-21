#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
競馬予想 ライブモード
各レースの発走5分前にオッズを取得し、予測→Telegram通知を行う常駐スクリプト

Usage:
  python3 run_live.py              # 今日のレースをライブ監視
  python3 run_live.py 2026-03-15   # 指定日
  python3 run_live.py --dry-run    # 通知せずテスト
"""

import sys
import os
import re
import time
import io
import requests
from datetime import datetime, date, timedelta

# Windows cp932対策: stdoutをUTF-8に
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)

sys.path.insert(0, os.path.dirname(__file__))
from predictor_v1 import get_conn, score_all_horses, evaluate_race_quality, \
    generate_bets, allocate_budget, rank_marks_by_bet_amount, QUALITY_THRESHOLD, V2_BLEND_WEIGHT, MODEL_VERSION
from run_today import get_today_race_ids, scrape_shutuba, parse_shutuba_entries, scrape_odds
from scraper_legacy import HEADERS, REQUEST_INTERVAL, init_db

# Longshot Wide Portfolio (穴予想) モジュール
_LONGSHOT_AVAILABLE = False
try:
    from longshot_wide_predictor import (predict_longshot_wide, format_longshot_message,
                                         init_longshot_model,
                                         predict_single_race as longshot_predict_race)
    _LONGSHOT_AVAILABLE = True
except ImportError as _e:
    print(f"[longshot] モジュール読み込み失敗（スキップ）: {_e}")

# Telegram設定（環境変数優先・2026-05-30 ハードコード除去）
TG_TOKEN = os.environ.get("TG_TOKEN_JRA", os.environ.get("TG_TOKEN", ""))
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "8571447808")

# 発走何分前にオッズ取得・予測するか（オッズ更新ラグを考慮し7分前）
MINUTES_BEFORE = 7

# 1レースあたりの予算
RACE_BUDGET = 5000


# X投稿モジュール
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from shared.x_poster import post_live_to_x
    X_POST_AVAILABLE = True
except ImportError as e:
    print(f"X投稿モジュール読み込み失敗（X投稿無効）: {e}")
    X_POST_AVAILABLE = False

def send_telegram(message):
    """Telegramにメッセージ送信"""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "parse_mode": "Markdown", "text": message},
            timeout=10)
        return r.ok
    except requests.RequestException:
        return False


def load_v2_model(conn, date_str, race_ids):
    """v2モデルのみロード（特徴量構築は各レース処理時に実行）"""
    v2_model = None
    v2_predictions = {}
    if MODEL_VERSION == "v2":
        try:
            from model_v2 import load_model
            v2_model, _ = load_model()
            print("v2モデルロード完了")
        except Exception as e:
            print(f"v2モデル読み込み失敗: {e}")
    return v2_model, v2_predictions


def predict_single_race(conn, race_id, v2_model, v2_predictions):
    """1レースの予測を実行"""
    scored = score_all_horses(conn, race_id)
    if not scored:
        return None

    # v2ブレンド
    if v2_model and race_id in v2_predictions:
        v2_probs = v2_predictions[race_id]
        max_prob = max(v2_probs.values()) if v2_probs else 1.0
        for h in scored:
            hn = h["horse_number"]
            if hn in v2_probs:
                v2_norm = v2_probs[hn] / max_prob if max_prob > 0 else 0.5
                h["total_score"] = (
                    V2_BLEND_WEIGHT * v2_norm
                    + (1 - V2_BLEND_WEIGHT) * h["total_score"]
                )
                h["v2_prob"] = v2_probs[hn]
        scored.sort(key=lambda x: x["total_score"], reverse=True)

    quality = evaluate_race_quality(conn, race_id, scored)
    return {"scored_horses": scored, "quality": quality}


def format_race_notification(race_info, quality, scored_horses, horse_names, bets, bet_total):
    """1レース分のTelegram通知メッセージを生成"""
    ri = race_info
    qi = quality
    bt = bets["bet_type"]

    lines = []
    lines.append(f"🏇 *{ri['venue']} {ri['race_number']}R {ri['name']}*")
    lines.append(f"{ri['surface']}{ri['distance']}m  発走 {ri.get('start_time', '?')}")
    lines.append(f"品質: {qi['quality_score']:.2f}  推奨: {bt}")
    lines.append("")

    # 上位3頭（印は買い目金額順）
    marks = rank_marks_by_bet_amount(bets)
    for j, h in enumerate(scored_horses[:3]):
        hn = h["horse_number"]
        mark = marks.get(hn, "  ")
        name = horse_names.get(h["horse_id"], "???")
        odds = h.get("odds_win")
        odds_str = f"{odds:.1f}" if odds else "-"
        pop = h.get("popularity") or "-"
        lines.append(f"  {mark} {hn:>2d} {name}  {odds_str}倍 ({pop}人気)")
    lines.append("")

    # 買い目
    lines.append("買い目:")
    for bet in bets["bets"]:
        est = bet.get("est_odds", 0)
        odds_info = f" ≈{est:.0f}倍" if est > 0 else ""
        lines.append(f"  {bet['combination']}  {bet['amount']:,}円{odds_info}")
    lines.append(f"投資: {bet_total:,}円")

    return "\n".join(lines)


def format_skip_notification(race_info, quality):
    """見送りレースのTelegram通知"""
    ri = race_info
    return (f"⏭ {ri['venue']} {ri['race_number']}R {ri['name']}  "
            f"発走{ri.get('start_time', '?')}  "
            f"品質{quality['quality_score']:.2f} → 見送り")


def main():
    target_date = date.today()
    dry_run = False

    for arg in sys.argv[1:]:
        if arg == "--dry-run":
            dry_run = True
        elif re.match(r'\d{4}-\d{2}-\d{2}', arg):
            target_date = datetime.strptime(arg, "%Y-%m-%d").date()

    date_str = target_date.strftime("%Y-%m-%d")
    print(f"=== ライブモード: {date_str} ===")
    if dry_run:
        print("(ドライラン: Telegram通知なし)")

    conn = get_conn()
    init_db()
    c = conn.cursor()

    # 出馬表が未取得なら取得
    c.execute("SELECT COUNT(*) FROM races WHERE date = ? AND surface IN ('芝', 'ダート')", (date_str,))
    existing = c.fetchone()[0]

    if existing == 0:
        print("出馬表を取得中...")
        race_ids = get_today_race_ids(target_date)
        jra_ids = [rid for rid in race_ids
                   if len(rid) >= 6 and rid[4:6] in
                   ("01", "02", "03", "04", "05", "06", "07", "08", "09", "10")]
        print(f"JRA中央競馬: {len(jra_ids)} レース")

        for rid in jra_ids:
            print(f"  取得: {rid}", end="")
            race_data = scrape_shutuba(rid, conn)
            if race_data and isinstance(race_data, dict):
                if not race_data["date_str"]:
                    race_data["date_str"] = date_str
                entries = parse_shutuba_entries(race_data, conn)
                print(f" → {len(entries)}頭")
            else:
                print(" SKIP")
            time.sleep(REQUEST_INTERVAL)
    else:
        print(f"DB内に {existing} レースのデータあり")

    # 対象レース一覧（発走時刻順）
    c.execute("""SELECT race_id, venue, race_number, name, surface, distance,
                        track_condition, start_time
                 FROM races WHERE date = ? AND surface IN ('芝', 'ダート')
                   AND name NOT LIKE '%障害%'
                 ORDER BY start_time, race_id""", (date_str,))
    all_races = []
    for row in c.fetchall():
        all_races.append({
            "race_id": row[0], "venue": row[1], "race_number": row[2],
            "name": row[3], "surface": row[4], "distance": row[5],
            "track_condition": row[6], "start_time": row[7] or "",
        })

    if not all_races:
        print("対象レースなし")
        conn.close()
        return

    # 発走時刻がないレースを警告
    no_time = [r for r in all_races if not r["start_time"]]
    if no_time:
        print(f"⚠ 発走時刻不明: {len(no_time)}レース（スキップします）")
        all_races = [r for r in all_races if r["start_time"]]

    print(f"\n対象: {len(all_races)}レース")
    print(f"最初: {all_races[0]['venue']}{all_races[0]['race_number']}R {all_races[0]['start_time']}")
    print(f"最後: {all_races[-1]['venue']}{all_races[-1]['race_number']}R {all_races[-1]['start_time']}")
    print()

    # v2モデルを事前ロード
    race_id_list = [r["race_id"] for r in all_races]
    print("モデルロード中...")
    v2_model, v2_predictions = load_v2_model(conn, date_str, race_id_list)

    # 穴予想 (Longshot Wide) モデル訓練（起動時1回）
    longshot_model = None
    longshot_feature_cols = None
    if _LONGSHOT_AVAILABLE:
        try:
            print("穴予想（Longshot Wide）モデル訓練中...")
            longshot_model, longshot_feature_cols = init_longshot_model(date_str)
            if longshot_model:
                print("穴予想モデル訓練完了（各レース直前に最新オッズで再計算します）")
            else:
                print("穴予想モデル訓練失敗")
        except Exception as _le:
            print(f"[longshot] モデル訓練失敗（スキップ）: {_le}")

    print("準備完了\n")

    # 開始通知
    start_msg = (f"🏇 *ライブモード開始 {date_str}*\n"
                 f"{len(all_races)}レース監視中\n"
                 f"各レースの{MINUTES_BEFORE}分前にオッズ取得→予測→通知します")
    if not dry_run:
        send_telegram(start_msg)
    print(start_msg)
    print()

    # 予測保存用
    from run_today import save_predictions

    processed = set()
    total_bet = 0
    selected_count = 0

    while True:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")

        # 日付が変わったら終了
        if today_str != date_str:
            break

        # 未処理レースを確認
        pending = [r for r in all_races if r["race_id"] not in processed]
        if not pending:
            break

        # 次のレースの発走時刻を確認
        next_race = pending[0]
        try:
            start_dt = datetime.strptime(
                f"{date_str} {next_race['start_time']}", "%Y-%m-%d %H:%M")
        except ValueError:
            print(f"発走時刻パース失敗: {next_race['start_time']}")
            processed.add(next_race["race_id"])
            continue

        # 発走時刻を過ぎたレースはスキップ
        if now > start_dt + timedelta(minutes=1):
            print(f"[{now.strftime('%H:%M')}] {next_race['venue']}{next_race['race_number']}R "
                  f"発走{next_race['start_time']} → 発走済みスキップ")
            processed.add(next_race["race_id"])
            continue

        # MINUTES_BEFORE分前になったら処理
        trigger_time = start_dt - timedelta(minutes=MINUTES_BEFORE)
        if now < trigger_time:
            wait_sec = (trigger_time - now).total_seconds()
            if wait_sec > 60:
                next_str = f"{next_race['venue']}{next_race['race_number']}R {next_race['start_time']}"
                print(f"[{now.strftime('%H:%M')}] 次: {next_str} "
                      f"(あと{int(wait_sec//60)}分{int(wait_sec%60)}秒)")
            time.sleep(min(wait_sec, 30))  # 最大30秒ずつスリープ
            continue

        # === レース処理 ===
        race_id = next_race["race_id"]
        processed.add(race_id)

        print(f"\n[{now.strftime('%H:%M')}] === {next_race['venue']} "
              f"{next_race['race_number']}R {next_race['name']} "
              f"発走{next_race['start_time']} ===")

        # オッズ取得（リトライ付き）
        print("  オッズ取得中...", flush=True)
        if scrape_odds(race_id, conn, retries=5, verbose=True):
            print("  オッズ取得OK", flush=True)
        else:
            print("  オッズ取得失敗（オッズなしで予測続行）", flush=True)

        # v2特徴量を1レース分だけ再構築（オッズ更新後）
        if v2_model:
            try:
                from model_v2 import build_features_for_race, FEATURE_COLS
                df_race = build_features_for_race(conn, date_str, race_id)
                if df_race is not None and not df_race.empty:
                    X = df_race[FEATURE_COLS].values
                    probs = v2_model.predict(X)
                    v2_predictions[race_id] = dict(
                        zip(df_race["horse_number"].astype(int), probs)
                    )
            except Exception as e:
                print(f"  v2再計算失敗: {e}")

        # 予測
        result = predict_single_race(conn, race_id, v2_model, v2_predictions)
        if not result:
            print("  予測失敗")
            continue

        qs = result["quality"]["quality_score"]

        # オッズ取得できたか確認して閾値を調整
        c.execute("""SELECT COUNT(*) FROM results
                     WHERE race_id = ? AND odds_win IS NOT NULL AND odds_win > 0""",
                  (race_id,))
        has_odds = c.fetchone()[0] > 0
        threshold = QUALITY_THRESHOLD if has_odds else 0.80
        print(f"  品質スコア: {qs:.3f} (閾値: {threshold}{'[オッズあり]' if has_odds else '[オッズなし]'})")

        # レース情報
        race_info = next_race.copy()

        if qs >= threshold:
            # 買い目生成
            bets = generate_bets(result["scored_horses"], race_info, RACE_BUDGET)
            bet_total = sum(b["amount"] for b in bets["bets"])
            total_bet += bet_total
            selected_count += 1

            # 馬名取得
            horse_ids = [h["horse_id"] for h in result["scored_horses"]]
            phs = ",".join("?" * len(horse_ids))
            c.execute(f"SELECT horse_id, name FROM horses WHERE horse_id IN ({phs})", horse_ids)
            horse_names = dict(c.fetchall())

            # 予測をDBに保存
            pred_data = {
                "date": date_str,
                "races": [{
                    "race_id": race_id,
                    "quality": result["quality"],
                    "bets": bets,
                }]
            }
            save_predictions(pred_data, conn, source="live")

            # 通知
            msg = format_race_notification(
                race_info, result["quality"], result["scored_horses"],
                horse_names, bets, bet_total)
            print(f"  → 買い ({bets['bet_type']}, {bet_total:,}円)")
            if not dry_run:
                send_telegram(msg)
                # X投稿（直前予想）
                if X_POST_AVAILABLE:
                    try:
                        post_live_to_x(msg, dry_run=False)
                    except Exception as e:
                        print(f"X投稿エラー（Telegram配信には影響なし）: {e}")
            else:
                print(msg)
                # X投稿ドライラン
                if X_POST_AVAILABLE:
                    post_live_to_x(msg, dry_run=True)
        else:
            print(f"  → 見送り")
            # 見送りレースも記録（amount=0）
            skip_data = {
                "date": date_str,
                "races": [{
                    "race_id": race_id,
                    "quality": result["quality"],
                    "bets": {"bet_type": "見送り", "bets": [{"combination": "-", "amount": 0}]},
                }]
            }
            save_predictions(skip_data, conn, source="live")
            if not dry_run:
                send_telegram(format_skip_notification(race_info, result["quality"]))

        # --- Longshot Wide 穴予想配信（直前・最新オッズで再計算）---
        try:
            if _LONGSHOT_AVAILABLE and longshot_model is not None:
                ls_item = longshot_predict_race(race_id, date_str, longshot_model, longshot_feature_cols)
                if ls_item:
                    ls_msg = format_longshot_message([ls_item])
                    ls_msg = ls_msg.replace("今日の穴予想", "穴予想（直前）")
                    anc = ls_item['anchor']
                    pts = [str(p['num']) for p in ls_item['partners']]
                    print(f"  [穴予想] conv={ls_item['conv']} 軸{anc['num']}({anc.get('name','')}) 相手{','.join(pts)} → 配信")
                    if not dry_run:
                        send_telegram(ls_msg)
                        # X投稿（穴予想）
                        try:
                            from shared.x_poster import post_longshot_to_x
                            print(f"  [X投稿-穴] post_longshot_to_x呼び出し開始 (msg {len(ls_msg)}字)")
                            result = post_longshot_to_x(ls_msg, dry_run=False)
                            print(f"  [X投稿-穴] 結果: {result}")
                        except Exception as _xe:
                            print(f"  [X投稿-穴] エラー（Telegram配信には影響なし）: {_xe}")
                    else:
                        print(ls_msg)
                    try:
                        from longshot_wide_tracker import save_longshot_predictions
                        save_longshot_predictions(date_str, [ls_item], source="live")
                    except Exception as _te:
                        print(f"  [longshot] 保存失敗（スキップ）: {_te}")
                else:
                    print(f"  [穴予想] 該当なし")
        except Exception as _le:
            print(f"  [longshot] 直前配信失敗（スキップ）: {_le}")

        time.sleep(1)

    # 終了通知
    end_msg = (f"🏁 *ライブモード終了 {date_str}*\n"
               f"{selected_count}レース選定 / 合計投資: {total_bet:,}円")
    if not dry_run:
        send_telegram(end_msg)
    print(f"\n{end_msg}")

    conn.close()


if __name__ == "__main__":
    main()
