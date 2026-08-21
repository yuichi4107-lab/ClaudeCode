#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Longshot Wide Portfolio 成績トラッカー

Functions:
  save_longshot_predictions(date_str, predictions) - 予測保存
  check_longshot_results(date_str)                 - 結果照合
  generate_monthly_report(year_month)              - 月次サマリー
"""

import os
import sys
import json
import sqlite3
import traceback
from datetime import datetime, date
from typing import List, Dict, Optional

DATA_DIR      = "/opt/keiba-unified/jra/data"
LONGSHOT_DIR  = os.path.join(DATA_DIR, "longshot_wide")
CUMULATIVE_JSON = os.path.join(LONGSHOT_DIR, "cumulative.json")
DB_PATH       = os.path.join(DATA_DIR, "keiba_live.db")

BET_AMOUNT = 100  # 1コンボあたりの賭け金


def _ensure_dir():
    os.makedirs(LONGSHOT_DIR, exist_ok=True)


def _load_cumulative() -> Dict:
    _ensure_dir()
    if os.path.exists(CUMULATIVE_JSON):
        with open(CUMULATIVE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "start_date": date.today().isoformat(),
        "total_bets": 0, "total_hits": 0,
        "total_invested": 0, "total_payout": 0,
        "net_profit": 0, "hit_rate": 0, "roi": 0,
        "daily_history": [],
    }


def _save_cumulative(data: Dict):
    _ensure_dir()
    with open(CUMULATIVE_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_longshot_predictions(date_str: str, predictions: List[Dict], source: str = "morning"):
    """予測を保存。source='morning' は一括上書き、source='live' は追記（重複排除）。

    ファイル構造:
      morning_YYYY-MM-DD.json — 朝予想（全レース一括、上書き）
      live_YYYY-MM-DD.json — 直前予想（1レースずつ追記、書き換え不可）
    """
    _ensure_dir()

    if source == "morning":
        out_path = os.path.join(LONGSHOT_DIR, f"morning_{date_str}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"date": date_str, "source": "morning",
                       "predictions": predictions}, f,
                      ensure_ascii=False, indent=2)
        print(f"[Tracker] モーニング予測保存: {out_path} ({len(predictions)} レース)")

    elif source == "live":
        out_path = os.path.join(LONGSHOT_DIR, f"live_{date_str}.json")
        existing = []
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                existing = data.get("predictions", [])

        existing_ids = {p["race_id"] for p in existing}
        new_preds = [p for p in predictions if p["race_id"] not in existing_ids]
        if not new_preds:
            print(f"[Tracker] 直前予測: 重複のためスキップ")
            return

        combined = existing + new_preds
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"date": date_str, "source": "live",
                       "predictions": combined}, f,
                      ensure_ascii=False, indent=2)
        print(f"[Tracker] 直前予測追記: {out_path} (+{len(new_preds)} → 計{len(combined)} レース)")

    else:
        # 後方互換: 旧形式
        out_path = os.path.join(LONGSHOT_DIR, f"{date_str}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump({"date": date_str, "predictions": predictions}, f,
                      ensure_ascii=False, indent=2)
        print(f"[Tracker] 予測保存: {out_path} ({len(predictions)} レース)")


def check_longshot_results(date_str: str, source: str = "all") -> Optional[Dict]:
    """
    指定日の予測と結果DBを照合し、各コンボのhit/payoutを計算。
    cumulative.json を更新する。

    source: "morning" / "live" / "all" (both)
    """
    _ensure_dir()

    predictions = []
    result_source = source

    if source in ("morning", "all"):
        mp = os.path.join(LONGSHOT_DIR, f"morning_{date_str}.json")
        if os.path.exists(mp):
            with open(mp, "r", encoding="utf-8") as f:
                predictions.extend(json.load(f).get("predictions", []))
            result_source = "morning" if source == "morning" else result_source

    if source in ("live", "all"):
        lp = os.path.join(LONGSHOT_DIR, f"live_{date_str}.json")
        if os.path.exists(lp):
            with open(lp, "r", encoding="utf-8") as f:
                live_preds = json.load(f).get("predictions", [])
            if source == "all":
                existing_ids = {p["race_id"] for p in predictions}
                live_preds = [p for p in live_preds if p["race_id"] not in existing_ids]
            predictions.extend(live_preds)
            result_source = "live" if source == "live" else result_source

    # 後方互換: 旧形式ファイル
    if not predictions:
        old_path = os.path.join(LONGSHOT_DIR, f"{date_str}.json")
        if os.path.exists(old_path):
            with open(old_path, "r", encoding="utf-8") as f:
                predictions = json.load(f).get("predictions", [])

    if not predictions:
        print(f"[Tracker] 予測ファイルなし: {date_str}")
        return None

    conn = sqlite3.connect(DB_PATH)
    c    = conn.cursor()

    day_bets    = 0
    day_hits    = 0
    day_invested = 0
    day_payout  = 0
    detail_races = []

    for pred in predictions:
        race_id = pred["race_id"]
        anchor  = pred["anchor"]
        partners = pred["partners"]

        # 結果確認
        c.execute("""
            SELECT horse_number, finish_position
            FROM results
            WHERE race_id = ? AND finish_position > 0
            ORDER BY finish_position
        """, (race_id,))
        results_rows = c.fetchall()
        if not results_rows:
            print(f"[Tracker] 結果未収録: {race_id}")
            continue

        finish_map = {row[0]: row[1] for row in results_rows}
        top3 = set(hn for hn, pos in finish_map.items() if pos <= 3)

        # 各コンボのhit/payout
        combos_detail = []
        for p in partners:
            combo_nums = sorted([anchor["num"], p["num"]])
            combo_str  = f"{combo_nums[0]}-{combo_nums[1]}"

            # ワイドヒット: 両馬が3着以内
            is_hit = (combo_nums[0] in top3 and combo_nums[1] in top3)

            payout = 0
            if is_hit:
                # DBからワイド払戻を取得
                c.execute("""
                    SELECT payout FROM payouts
                    WHERE race_id = ? AND bet_type = 'ワイド'
                      AND (combination = ? OR combination = ?)
                """, (race_id, combo_str, f"{combo_nums[1]}-{combo_nums[0]}"))
                pay_row = c.fetchone()
                if pay_row:
                    # payoffs.payout は100円あたりの払戻額
                    payout = float(pay_row[0]) / 100 * BET_AMOUNT
                else:
                    # 払い戻しデータなし（推定: 最低300円）
                    payout = 300.0

            day_bets     += 1
            day_invested += BET_AMOUNT
            day_payout   += payout
            if is_hit:
                day_hits += 1

            combos_detail.append({
                "combo": combo_str,
                "hit":   is_hit,
                "payout": payout,
                "profit": payout - BET_AMOUNT,
            })

        detail_races.append({
            "race_id":  race_id,
            "venue":    pred.get("venue",""),
            "race_no":  pred.get("race_no",0),
            "race_name": pred.get("race_name",""),
            "anchor_num": anchor["num"],
            "anchor_name": anchor["name"],
            "combos": combos_detail,
        })

    conn.close()

    if day_bets == 0:
        print("[Tracker] 結果照合できるコンボなし")
        return None

    day_roi    = day_payout / day_invested if day_invested > 0 else 0.0
    day_profit = day_payout - day_invested

    # cumulative 更新
    cum = _load_cumulative()
    cum["total_bets"]     += day_bets
    cum["total_hits"]     += day_hits
    cum["total_invested"] += day_invested
    cum["total_payout"]   += day_payout
    cum["net_profit"]      = cum["total_payout"] - cum["total_invested"]
    cum["hit_rate"]        = cum["total_hits"] / cum["total_bets"] if cum["total_bets"] > 0 else 0
    cum["roi"]             = cum["total_payout"] / cum["total_invested"] if cum["total_invested"] > 0 else 0

    # 既存エントリがあれば上書き
    existing = [e for e in cum["daily_history"] if e["date"] != date_str]
    existing.append({
        "date": date_str, "bets": day_bets, "hits": day_hits,
        "invested": day_invested, "payout": day_payout,
        "profit": day_profit, "roi": day_roi,
    })
    cum["daily_history"] = sorted(existing, key=lambda x: x["date"])
    _save_cumulative(cum)

    result = {
        "date": date_str,
        "bets": day_bets, "hits": day_hits,
        "invested": day_invested, "payout": day_payout,
        "profit": day_profit, "roi": day_roi,
        "races": detail_races,
        "cumulative": cum,
    }

    print(f"[Tracker] {date_str}: {day_bets}コンボ {day_hits}的中 "
          f"ROI={day_roi*100:.1f}% 収支={day_profit:+.0f}円")
    return result


def format_longshot_result_message(result: Dict) -> str:
    """Telegram向け穴予想結果メッセージ"""
    if not result:
        return ""
    cum = result.get("cumulative", {})
    lines = [
        "━━━━━━━━━━",
        "🎯 穴予想 結果速報",
        "",
        f"本日: {result['bets']}コンボ / {result['hits']}的中",
        f"投資: {result['invested']:,}円 → 回収: {result['payout']:,.0f}円",
        f"収支: {result['profit']:+,.0f}円 (ROI: {result['roi']*100:.1f}%)",
    ]

    hit_combos = []
    for race in result.get("races", []):
        for combo in race.get("combos", []):
            if combo["hit"]:
                hit_combos.append(
                    f"  ✅ {race['venue']}{race['race_no']}R "
                    f"{combo['combo']} → {combo['payout']:,.0f}円"
                )
    if hit_combos:
        lines.append("")
        lines.extend(hit_combos)

    lines += [
        "",
        f"【累計】start:{cum.get('start_date','-')}",
        f"{cum.get('total_bets',0)}コンボ / {cum.get('total_hits',0)}的中 "
        f"({cum.get('hit_rate',0)*100:.1f}%)",
        f"累計収支: {cum.get('net_profit',0):+,.0f}円 "
        f"ROI: {cum.get('roi',0)*100:.1f}%",
        "━━━━━━━━━━",
    ]
    return "\n".join(lines)


def generate_monthly_report(year_month: str) -> str:
    """
    月次サマリー生成
    year_month: "YYYY-MM"
    """
    cum = _load_cumulative()
    history = [e for e in cum.get("daily_history", [])
               if e["date"].startswith(year_month)]
    if not history:
        return f"[Tracker] {year_month}: データなし"

    total_bets     = sum(e["bets"] for e in history)
    total_hits     = sum(e["hits"] for e in history)
    total_invested = sum(e["invested"] for e in history)
    total_payout   = sum(e["payout"] for e in history)
    total_profit   = total_payout - total_invested
    roi            = total_payout / total_invested if total_invested > 0 else 0
    hit_rate       = total_hits / total_bets if total_bets > 0 else 0

    lines = [
        f"━━━━━━━━━━",
        f"🎯 穴予想 月次レポート {year_month}",
        f"開催日数: {len(history)}日",
        f"コンボ数: {total_bets} / 的中: {total_hits} ({hit_rate*100:.1f}%)",
        f"投資: {total_invested:,}円 → 回収: {total_payout:,.0f}円",
        f"収支: {total_profit:+,.0f}円 (ROI: {roi*100:.1f}%)",
        "━━━━━━━━━━",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "--monthly":
            ym = sys.argv[2] if len(sys.argv) > 2 else date.today().strftime("%Y-%m")
            print(generate_monthly_report(ym))
        else:
            r = check_longshot_results(sys.argv[1])
            if r:
                print(format_longshot_result_message(r))
