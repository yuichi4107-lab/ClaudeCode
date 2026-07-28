#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
競馬予想 モーニングレポート（朝7時版）
開催日の朝7時に全レースの予想を生成してTelegram配信する

目的:
  - 朝時点の予想と直前オッズ予想の変化を比較分析
  - 将来の有料情報配信のベース

Usage:
  python3 run_morning.py               # 今日のレースを予測
  python3 run_morning.py 2026-03-22    # 指定日
  python3 run_morning.py --dry-run     # 通知せずテスト
"""

import sys
import os
import re
import io
import time
import requests
from datetime import datetime, date

# Windows cp932対策
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)

sys.path.insert(0, os.path.dirname(__file__))
from predictor_v1 import (get_conn, score_all_horses, evaluate_race_quality,
                           generate_bets,
                           QUALITY_THRESHOLD, V2_BLEND_WEIGHT, MODEL_VERSION)
from run_today import (get_today_race_ids, scrape_shutuba, parse_shutuba_entries,
                        scrape_odds, save_predictions, generate_report)
from scraper_legacy import HEADERS, REQUEST_INTERVAL, init_db

# X投稿モジュール
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
    from shared.x_poster import post_morning_to_x, post_longshot_to_x
    X_POST_AVAILABLE = True
except ImportError as e:
    print(f"X投稿モジュール読み込み失敗（X投稿無効）: {e}")
    X_POST_AVAILABLE = False

# Telegram設定（環境変数優先・2026-05-30 ハードコード除去）
TG_TOKEN = os.environ.get("TG_TOKEN_JRA", os.environ.get("TG_TOKEN", ""))
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "8571447808")

# オッズありなら通常閾値(0.80)、なしなら低め(0.65)
MORNING_THRESHOLD_WITH_ODDS = QUALITY_THRESHOLD  # 0.80
MORNING_THRESHOLD_NO_ODDS = 0.80  # オッズなしでも品質基準は維持
RACE_BUDGET = 5000  # 1レースあたりの予算（直前予想と統一）


def send_telegram(message, parse_mode="Markdown"):
    """Telegramにメッセージ送信"""
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT_ID, "parse_mode": parse_mode, "text": message},
            timeout=10)
        return r.ok
    except requests.RequestException:
        return False


def predict_all_races(conn, date_str):
    """全レースをスコアリングして予想データを生成（品質スコア順）"""
    c = conn.cursor()
    c.execute("""SELECT race_id, venue, race_number, name, surface, distance,
                        track_condition, start_time, class
                 FROM races WHERE date = ? AND surface IN ('芝', 'ダート')
                   AND name NOT LIKE '%障害%'
                 ORDER BY start_time, race_id""", (date_str,))
    all_races = []
    for row in c.fetchall():
        all_races.append({
            "race_id": row[0], "venue": row[1], "race_number": row[2],
            "name": row[3], "surface": row[4], "distance": row[5],
            "track_condition": row[6], "start_time": row[7] or "",
            "class": row[8] or "",
        })

    if not all_races:
        return []

    # v2モデルロード
    v2_model = None
    if MODEL_VERSION == "v2":
        try:
            from model_v2 import load_model
            v2_model, _ = load_model()
        except Exception as e:
            print(f"v2モデル読み込み失敗: {e}")

    results = []
    for race_info in all_races:
        race_id = race_info["race_id"]

        # スコアリング
        scored = score_all_horses(conn, race_id)
        if not scored:
            continue

        # v2ブレンド（モデルがあれば1レースずつ特徴量構築）
        if v2_model:
            try:
                from model_v2 import build_features_for_race, FEATURE_COLS
                df_race = build_features_for_race(conn, date_str, race_id)
                if df_race is not None and not df_race.empty:
                    X = df_race[FEATURE_COLS].values
                    probs = v2_model.predict(X)
                    v2_probs = dict(zip(df_race["horse_number"].astype(int), probs))
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
            except Exception as e:
                print(f"  v2計算失敗({race_id}): {e}")

        quality = evaluate_race_quality(conn, race_id, scored)

        # 馬名取得
        horse_ids = [h["horse_id"] for h in scored]
        phs = ",".join("?" * len(horse_ids))
        c.execute(f"SELECT horse_id, name FROM horses WHERE horse_id IN ({phs})", horse_ids)
        horse_names = dict(c.fetchall())

        results.append({
            "race_id": race_id,
            "race_info": race_info,
            "quality": quality,
            "scored_horses": scored,
            "horse_names": horse_names,
        })

    # 品質スコア順にソート
    results.sort(key=lambda x: x["quality"]["quality_score"], reverse=True)
    return results


def format_morning_report(date_str, all_results, threshold=MORNING_THRESHOLD_WITH_ODDS):
    """朝版レポートを生成（全レース概要 + 注目レース詳細）"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
        header_date = f"{dt.year}年{dt.month}月{dt.day}日（{weekday}）"
    except ValueError:
        header_date = date_str

    lines = []
    lines.append(f"{'=' * 50}")
    lines.append(f"  {header_date} モーニング予想")
    lines.append(f"  配信時刻: {datetime.now().strftime('%H:%M')}")
    lines.append(f"{'=' * 50}")
    lines.append("")

    if not all_results:
        lines.append("本日の対象レースがありません。")
        return "\n".join(lines)

    # オッズ有無
    has_odds = any(
        (h.get("odds_win") or 0) > 0
        for r in all_results
        for h in r["scored_horses"][:3]
    )

    # 注目レース（閾値以上）
    selected = [r for r in all_results
                if r["quality"]["quality_score"] >= threshold]

    lines.append(f"全{len(all_results)}レース分析 → "
                 f"注目 {len(selected)}レース（品質{threshold:.2f}以上）")
    if not has_odds:
        lines.append("※ 朝時点オッズ未反映の暫定予想")
    lines.append("")

    # === 全レース一覧（品質スコア順） ===
    lines.append("【全レース 品質スコアランキング】")
    lines.append(f"{'─' * 50}")
    for i, r in enumerate(all_results):
        ri = r["race_info"]
        qs = r["quality"]["quality_score"]
        top_horse = r["scored_horses"][0] if r["scored_horses"] else None
        top_name = r["horse_names"].get(top_horse["horse_id"], "???") if top_horse else "?"
        mark = "★" if qs >= threshold else "  "
        odds_str = ""
        if top_horse and top_horse.get("odds_win"):
            odds_str = f" {top_horse['odds_win']:.1f}倍"
        lines.append(f" {mark} {qs:.3f}  {ri['venue']}{ri['race_number']:>2d}R "
                     f"{ri['start_time']:>5s}  {ri['name'][:10]:<10s}  "
                     f"◎{top_name[:6]}{odds_str}")
    lines.append("")

    # === 注目レース詳細 ===
    if not selected:
        lines.append("注目レースなし（全レースが品質基準未満）")
        return "\n".join(lines)

    # 予算: 1レース5,000円固定
    budgets = {r["race_id"]: RACE_BUDGET for r in selected}

    lines.append(f"{'=' * 50}")
    lines.append(f"【注目レース詳細】")
    lines.append(f"{'=' * 50}")

    total_bet = 0
    for r in selected:
        ri = r["race_info"]
        qi = r["quality"]
        scored = r["scored_horses"]
        horse_names = r["horse_names"]
        budget = budgets.get(r["race_id"], RACE_BUDGET)

        lines.append("")
        lines.append(f"■ {ri['venue']} {ri['race_number']}R {ri['name']}  "
                     f"{ri['surface']}{ri['distance']}m  発走{ri['start_time']}")
        reasons = ", ".join(qi["reasons"]) if qi["reasons"] else "総合評価"
        lines.append(f"  品質: {qi['quality_score']:.3f}  [{reasons}]")
        lines.append("")

        # 上位5頭
        lines.append(f"  順位  馬番  馬名              スコア   オッズ")
        lines.append(f"  {'─' * 48}")
        for j, h in enumerate(scored[:5]):
            hn = h["horse_number"]
            name = horse_names.get(h["horse_id"], "???")
            name_disp = name[:8]
            name_pad = 16 - len(name_disp.encode('utf-8', errors='replace')) + len(name_disp)
            odds = h.get("odds_win")
            odds_str = f"{odds:.1f}" if odds else "-"
            pop = h.get("popularity") or "-"
            lines.append(f"  {j+1:>4d}  {hn:>4d}  {name_disp:<{name_pad}s} "
                        f"{h['total_score']:.4f}  {odds_str:>6s}({pop}人気)")

        # 買い目
        bets = generate_bets(scored, ri, budget)
        bet_total = sum(b["amount"] for b in bets["bets"])
        total_bet += bet_total
        lines.append("")
        lines.append(f"  推奨: {bets['bet_type']}")
        for bet in bets["bets"]:
            est = bet.get("est_odds", 0)
            odds_info = f"  (約{est:.1f}倍)" if est > 0 else ""
            lines.append(f"    {bet['combination']:>12s}  {bet['amount']:>5,}円{odds_info}")
        lines.append(f"  小計: {bet_total:,}円")

    lines.append("")
    lines.append(f"{'=' * 50}")
    lines.append(f"合計投資目安: {total_bet:,}円")
    lines.append(f"{'=' * 50}")
    lines.append("")
    lines.append("※ 朝時点の予想です。発走直前のライブ予想で最終判断します。")
    lines.append("※ オッズ変動により選定レース・買い目は変更される場合があります。")

    return "\n".join(lines)


def calc_bet_ev(bets, scored_horses):
    """買い目リストとスコアリング済み馬リストからレース全体EV（金額加重平均）を返す。

    EV計算ロジック:
      1. 勝率正規化: p_i = total_score_i / Σtotal_score
      2. 的中確率: 馬連 2*pA*pB、三連複 6*pA*pB*pC
      3. 買い目EV: hit_prob * est_odds
      4. レース全体EV: Σ(EV_i * amount_i) / Σamount_i
    """
    if not scored_horses:
        return 0.0

    # 勝率正規化
    total_score = sum(h.get("total_score", 0) for h in scored_horses)
    if total_score <= 0:
        return 0.0

    # 馬番→正規化スコアのマップ
    prob_map = {}
    for h in scored_horses:
        hn = h["horse_number"]
        prob_map[hn] = h.get("total_score", 0) / total_score

    bet_list = bets.get("bets", [])
    if not bet_list:
        return 0.0

    total_amount = sum(b.get("amount", 0) for b in bet_list)
    if total_amount <= 0:
        return 0.0

    weighted_ev = 0.0
    for bet in bet_list:
        est_odds = bet.get("est_odds", 0) or 0
        if est_odds <= 0:
            continue
        amount = bet.get("amount", 0) or 0
        if amount <= 0:
            continue

        horses = bet.get("horses", [])
        bet_type = bets.get("bet_type", "")

        if bet_type == "馬連" and len(horses) >= 2:
            pA = prob_map.get(horses[0], 0)
            pB = prob_map.get(horses[1], 0)
            hit_prob = 2 * pA * pB
        elif bet_type == "三連複" and len(horses) >= 3:
            pA = prob_map.get(horses[0], 0)
            pB = prob_map.get(horses[1], 0)
            pC = prob_map.get(horses[2], 0)
            hit_prob = 6 * pA * pB * pC
        else:
            hit_prob = 0.0

        ev_i = hit_prob * est_odds
        weighted_ev += ev_i * amount

    return weighted_ev / total_amount


def format_telegram_morning_ev(date_str, all_results, threshold=MORNING_THRESHOLD_WITH_ODDS):
    """Telegram向け全レース期待値一覧メッセージを生成する。

    出力フォーマット:
      🎯 モーニング期待値 4/12(日)
      全24R分析

      【阪神】
        1R  品質0.65  EV 0.82  ◎ホースA(4.2倍)
      ★ 11R 品質0.85  EV 1.23  ◎ホースC(3.5倍)

      ★=注目レース（買い目対象）
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
        header = f"{dt.month}/{dt.day}({weekday})"
    except ValueError:
        header = date_str

    lines = []
    lines.append(f"🎯 *モーニング期待値 {header}*")
    lines.append(f"全{len(all_results)}R分析")

    if not all_results:
        return "\n".join(lines)

    # 競馬場昇順 → レース番号昇順にソート
    sorted_results = sorted(
        all_results,
        key=lambda x: (x["race_info"]["venue"], x["race_info"]["race_number"])
    )

    # 競馬場ごとにグループ化
    venues_order = []
    venue_map = {}
    for r in sorted_results:
        v = r["race_info"]["venue"]
        if v not in venue_map:
            venue_map[v] = []
            venues_order.append(v)
        venue_map[v].append(r)

    for venue in venues_order:
        lines.append("")
        lines.append(f"【{venue}】")
        for r in venue_map[venue]:
            ri = r["race_info"]
            qs = r["quality"]["quality_score"]
            scored = r["scored_horses"]

            # EV計算: 品質閾値未満でも仮買い目生成
            bets = generate_bets(scored, ri, RACE_BUDGET)
            ev = calc_bet_ev(bets, scored)

            # ◎馬名とオッズ
            top_horse = scored[0] if scored else None
            if top_horse:
                top_name = r["horse_names"].get(top_horse["horse_id"], "???")[:6]
                odds_win = top_horse.get("odds_win") or 0
                odds_str = f"{odds_win:.1f}倍" if odds_win > 0 else "-"
            else:
                top_name = "?"
                odds_str = "-"

            mark = "★" if qs >= threshold else "　"
            lines.append(
                f"{mark}{ri['race_number']:>3d}R  "
                f"品質{qs:.2f}  EV {ev:.2f}  "
                f"◎{top_name}({odds_str})"
            )

    lines.append("")
    lines.append("★=注目レース（買い目対象）")
    lines.append("EV=推奨買い目の期待値（1.0超で理論プラス）")

    return "\n".join(lines)


def format_telegram_morning(date_str, all_results, threshold=MORNING_THRESHOLD_WITH_ODDS):
    """Telegram向けの簡潔なモーニングメッセージ"""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = ["月", "火", "水", "木", "金", "土", "日"][dt.weekday()]
        header = f"{dt.month}/{dt.day}({weekday})"
    except ValueError:
        header = date_str

    selected = [r for r in all_results
                if r["quality"]["quality_score"] >= threshold]

    lines = []
    lines.append(f"🌅 *モーニング予想 {header}*")
    lines.append(f"全{len(all_results)}R分析 → 注目{len(selected)}R")
    lines.append("")

    if not selected:
        lines.append("注目レースなし")
        return "\n".join(lines)

    for r in selected:
        ri = r["race_info"]
        qs = r["quality"]["quality_score"]
        top3 = r["scored_horses"][:3]
        names = r["horse_names"]

        lines.append(f"*{ri['venue']}{ri['race_number']}R {ri['name']}* "
                     f"({ri['start_time']}) 品質{qs:.2f}")
        for j, h in enumerate(top3):
            mark = ["◎", "○", "▲"][j]
            name = names.get(h["horse_id"], "???")[:6]
            odds = h.get("odds_win")
            odds_str = f" {odds:.1f}倍" if odds else ""
            lines.append(f"  {mark} {h['horse_number']:>2d} {name}{odds_str}")

        # 買い目
        budget = RACE_BUDGET
        bets = generate_bets(r["scored_horses"], ri, budget)
        lines.append(f"  {bets['bet_type']}:")
        for bet in bets["bets"]:
            est = bet.get("est_odds", 0)
            odds_info = f" ≈{est:.0f}倍" if est > 0 else ""
            lines.append(f"    {bet['combination']} {bet['amount']:,}円{odds_info}")
        lines.append("")

    lines.append("_直前ライブ予想で最終判断_")
    return "\n".join(lines)


def main():
    target_date = date.today()
    dry_run = False

    for arg in sys.argv[1:]:
        if arg == "--dry-run":
            dry_run = True
        elif re.match(r'\d{4}-\d{2}-\d{2}', arg):
            target_date = datetime.strptime(arg, "%Y-%m-%d").date()

    date_str = target_date.strftime("%Y-%m-%d")
    print(f"=== モーニング予想: {date_str} ===")
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
            print(f"  取得: {rid}", end="", flush=True)
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

    # オッズ取得（JRA公式 → netkeiba）
    print("\nオッズ取得中...")
    c.execute("""SELECT race_id FROM races WHERE date = ? AND surface IN ('芝', 'ダート')
                 AND name NOT LIKE '%障害%' ORDER BY start_time""", (date_str,))
    race_ids = [row[0] for row in c.fetchall()]

    odds_ok = 0
    for rid in race_ids:
        if scrape_odds(rid, conn, retries=2, verbose=False):
            odds_ok += 1
        time.sleep(0.5)
    print(f"オッズ取得: {odds_ok}/{len(race_ids)}レース")

    # 閾値決定（オッズ取得できたかで切り替え）
    has_odds = odds_ok > len(race_ids) * 0.5
    threshold = MORNING_THRESHOLD_WITH_ODDS if has_odds else MORNING_THRESHOLD_NO_ODDS
    print(f"閾値: {threshold:.2f} ({'オッズあり' if has_odds else 'オッズなし'})")

    # 全レース予想
    print("\n予想実行中...")
    all_results = predict_all_races(conn, date_str)
    print(f"スコアリング完了: {len(all_results)}レース")

    selected = [r for r in all_results
                if r["quality"]["quality_score"] >= threshold]
    print(f"注目レース: {len(selected)}レース")

    # レポート生成
    report = format_morning_report(date_str, all_results, threshold)
    print("\n" + report)

    # レポート保存
    report_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
    os.makedirs(report_dir, exist_ok=True)
    report_file = os.path.join(report_dir, f"morning_{date_str}.txt")
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nレポート保存: {report_file}")

    # 予測データをDBに保存
    # 推奨レース（買い目あり）
    if selected:
        pred_data = {
            "date": date_str,
            "races": [{
                "race_id": r["race_id"],
                "quality": r["quality"],
                "bets": generate_bets(r["scored_horses"], r["race_info"], RACE_BUDGET),
            } for r in selected]
        }
        save_predictions(pred_data, conn, source="morning")

    # 見送りレース（amount=0で記録）
    skipped = [r for r in all_results
               if r["quality"]["quality_score"] < threshold]
    if skipped:
        skip_data = {
            "date": date_str,
            "races": [{
                "race_id": r["race_id"],
                "quality": r["quality"],
                "bets": {"bet_type": "見送り", "bets": [{"combination": "-", "amount": 0}]},
            } for r in skipped]
        }
        save_predictions(skip_data, conn, source="morning")

    # Telegram送信
    tg_msg = format_telegram_morning(date_str, all_results, threshold)
    if not dry_run:
        # 長いメッセージは分割送信
        if len(tg_msg) > 4000:
            parts = tg_msg.split("\n\n")
            buf = ""
            for part in parts:
                if len(buf) + len(part) > 3800:
                    send_telegram(buf)
                    time.sleep(0.5)
                    buf = part
                else:
                    buf = buf + "\n\n" + part if buf else part
            if buf:
                send_telegram(buf)
        else:
            send_telegram(tg_msg)
        print("Telegram送信完了")

        # 500ms待機してEV一覧を追加送信
        time.sleep(0.5)
        ev_msg = format_telegram_morning_ev(date_str, all_results, threshold)
        if len(ev_msg) > 4000:
            parts = ev_msg.split("\n\n")
            buf = ""
            for part in parts:
                if len(buf) + len(part) > 3800:
                    send_telegram(buf)
                    time.sleep(0.5)
                    buf = part
                else:
                    buf = buf + "\n\n" + part if buf else part
            if buf:
                send_telegram(buf)
        else:
            send_telegram(ev_msg)
        print("Telegram EV一覧送信完了")

        # X投稿（モーニング予想 → Geminiリライト → スレッド投稿）
        if X_POST_AVAILABLE:
            try:
                time.sleep(0.5)
                ok = post_morning_to_x(tg_msg, dry_run=False)
                print("X投稿完了（モーニング）" if ok else "X投稿失敗（モーニング）")
            except Exception as e:
                print(f"X投稿エラー（Telegram配信には影響なし）: {e}")
    else:
        print("\n--- Telegram メッセージ ---")
        print(tg_msg)
        print("--- ここまで ---")

        # dry-run時もEV一覧を表示
        ev_msg = format_telegram_morning_ev(date_str, all_results, threshold)
        print("\n--- Telegram EV一覧メッセージ ---")
        print(ev_msg)
        print("--- ここまで ---")

        # X投稿ドライラン
        if X_POST_AVAILABLE:
            try:
                post_morning_to_x(tg_msg, dry_run=True)
            except Exception as e:
                print(f"X投稿ドライランエラー: {e}")


    # ====================================================
    # --- 穴予想（Longshot Wide Portfolio）---
    # ====================================================
    try:
        import sys as _sys_ls
        _sys_ls.path.insert(0, os.path.dirname(__file__))
        from longshot_wide_predictor import predict_longshot_wide, format_longshot_message
        from longshot_wide_tracker import save_longshot_predictions

        print("\n穴予想（Longshot Wide）実行中...")
        longshot = predict_longshot_wide(date_str)

        if longshot:
            ls_msg = format_longshot_message(longshot)
            print("\n--- 穴予想メッセージ ---")
            print(ls_msg)
            print("--- ここまで ---")

            if not dry_run:
                time.sleep(0.5)
                send_telegram(ls_msg)
                print("穴予想 Telegram送信完了")

                # X投稿（穴予想 — chunk分割の単発連投）
                if X_POST_AVAILABLE:
                    try:
                        time.sleep(0.5)
                        ok = post_longshot_to_x(ls_msg, dry_run=False)
                        print("X投稿完了（穴予想・モーニング）" if ok
                              else "X投稿失敗（穴予想・モーニング）")
                    except Exception as _xe:
                        print(f"穴予想X投稿エラー（Telegram配信には影響なし）: {_xe}")
            else:
                # dry-run時もX投稿ドライラン出力
                if X_POST_AVAILABLE:
                    try:
                        post_longshot_to_x(ls_msg, dry_run=True)
                    except Exception as _xe:
                        print(f"穴予想X投稿ドライランエラー: {_xe}")

            save_longshot_predictions(date_str, longshot, source="morning")
            print(f"穴予想保存完了: {len(longshot)} レース")
        else:
            print("穴予想: 該当なし")

    except Exception as _ls_e:
        import traceback as _tb
        print(f"穴予想エラー（既存配信には影響なし）: {_ls_e}")
        _tb.print_exc()

    conn.close()
    print("\n完了")


if __name__ == "__main__":
    main()
