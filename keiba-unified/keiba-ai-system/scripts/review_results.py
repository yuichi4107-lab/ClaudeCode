"""予想結果の的中率・回収率を検証するスクリプト

レース結果収集後に実行し、当日の予想と結果を突合して
的中率・回収率を計算し、Telegram に配信する。

使い方:
    PYTHONPATH=. python3 scripts/review_results.py
    PYTHONPATH=. python3 scripts/review_results.py --date 2026-03-14
    PYTHONPATH=. python3 scripts/review_results.py --summary  # 累計成績
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# .envファイルから環境変数を読み込み
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().strip().splitlines():
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

from config.settings import PREDICTIONS_DIR, RAW_DATA_DIR
from scripts.daily_predict import send_telegram

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

REVIEW_DIR = PREDICTIONS_DIR / "reviews"


def review_date(target_date: date) -> dict | None:
    """指定日の予想と結果を突合して成績を返す"""
    date_str = target_date.strftime("%Y-%m-%d")

    # 予想CSVの読み込み
    pred_file = PREDICTIONS_DIR / f"{date_str}.csv"
    if not pred_file.exists():
        logger.info("%s の予想データがありません", date_str)
        return None

    preds = pd.read_csv(pred_file)

    # 結果CSVの読み込み
    raw_file = RAW_DATA_DIR / "race_results.csv"
    if not raw_file.exists():
        logger.info("結果データがありません")
        return None

    results = pd.read_csv(raw_file)
    results_today = results[results["race_date"] == date_str]
    if results_today.empty:
        logger.info("%s の結果データがまだありません", date_str)
        return None

    # race_no を文字列に統一して突合
    preds["race_no"] = preds["race_no"].astype(str)
    preds["horse_number"] = preds["horse_number"].astype(int)
    results_today = results_today.copy()
    results_today["race_no"] = results_today["race_no"].astype(str)
    results_today["horse_number"] = results_today["horse_number"].astype(int)

    # 予想側の重複を除去（race_no + horse_number で一意にする）
    preds = preds.drop_duplicates(subset=["race_no", "horse_number"], keep="first")

    merged = preds.merge(
        results_today[["race_no", "horse_number", "finish_order"]].drop_duplicates(),
        on=["race_no", "horse_number"],
        how="left",
    )

    # === 戦略別の成績計算 ===
    stats = {"date": date_str, "strategies": {}}

    # 戦略1: ◎（本命）単勝
    honmei = merged[merged["pred_rank"] == 1.0]
    stats["strategies"]["◎本命"] = _calc_strategy(honmei)

    # 戦略2: ◎○（本命・対抗）単勝
    honmei_taikou = merged[merged["pred_rank"].isin([1.0, 2.0])]
    stats["strategies"]["◎○上位2頭"] = _calc_strategy(honmei_taikou)

    # 戦略3: ★（期待値>1.0）単勝
    star = merged[
        (merged["odds"].notna()) & (merged["odds"] > 0) &
        (merged["win_prob"] * merged["odds"] > 1.0)
    ]
    stats["strategies"]["★期待値>1.0"] = _calc_strategy(star)

    # 戦略4: 全レース◎〜▲（上位3頭）
    top3 = merged[merged["pred_rank"].isin([1.0, 2.0, 3.0])]
    stats["strategies"]["◎○▲上位3頭"] = _calc_strategy(top3)

    # レースごとの結果
    race_details = []
    for rno in sorted(merged["race_no"].unique(), key=lambda x: int(x)):
        race = merged[merged["race_no"] == rno]
        honmei_row = race[race["pred_rank"] == 1.0]
        if honmei_row.empty:
            continue
        h = honmei_row.iloc[0]
        # 1着馬を結果データから直接取得（予想に含まれない馬が勝つ場合に対応）
        results_race = results_today[results_today["race_no"] == rno]
        winner = results_race[results_race["finish_order"] == 1]
        winner_name = winner.iloc[0]["horse_name"] if not winner.empty else "不明"
        winner_num = int(winner.iloc[0]["horse_number"]) if not winner.empty else 0

        hit = bool(h["finish_order"] == 1)
        race_details.append({
            "race_no": rno,
            "pred_name": h["horse_name"],
            "pred_num": int(h["horse_number"]),
            "pred_rank_result": int(h["finish_order"]) if pd.notna(h["finish_order"]) else None,
            "winner_name": winner_name,
            "winner_num": int(winner_num),
            "hit": hit,
        })
    stats["race_details"] = race_details

    return stats


def _calc_strategy(df: pd.DataFrame) -> dict:
    """DataFrameから戦略の成績を計算する"""
    if df.empty:
        return {"bets": 0, "hits": 0, "hit_rate": 0, "investment": 0,
                "payout": 0, "return_rate": 0, "profit": 0}

    bets = len(df)
    hits = int((df["finish_order"] == 1).sum())
    investment = bets * 100

    # 的中時の払戻金 = 100 * オッズ
    payout = 0
    for _, row in df.iterrows():
        if row["finish_order"] == 1 and pd.notna(row["odds"]) and row["odds"] > 0:
            payout += 100 * row["odds"]

    return {
        "bets": bets,
        "hits": hits,
        "hit_rate": hits / bets if bets > 0 else 0,
        "investment": investment,
        "payout": int(payout),
        "return_rate": payout / investment if investment > 0 else 0,
        "profit": int(payout - investment),
    }


def format_review_text(stats: dict) -> str:
    """検証結果をテキストにフォーマットする"""
    lines = []
    lines.append(f"📊 帯広ばんえい競馬 AI予想 成績")
    lines.append(f"📅 {stats['date']}")
    lines.append("=" * 30)

    # レースごとの結果
    lines.append("")
    lines.append("【レース結果】")
    for r in stats["race_details"]:
        mark = "⭕" if r["hit"] else "❌"
        result_str = f"{r['pred_rank_result']}着" if r["pred_rank_result"] else "?"
        lines.append(
            f"  {r['race_no']:>2}R {mark} "
            f"◎{r['pred_num']:>2} {r['pred_name'][:6]} → {result_str}"
            f"  (1着: {r['winner_num']}番 {r['winner_name'][:6]})"
        )

    # 戦略別成績
    lines.append("")
    lines.append("【戦略別成績】")
    has_odds = any(s["investment"] > 0 and s["payout"] > 0
                   for s in stats["strategies"].values())
    for name, s in stats["strategies"].items():
        if s["bets"] == 0:
            lines.append(f"  {name}: 該当なし")
            continue
        line = f"  {name}: {s['hits']}/{s['bets']}的中 ({s['hit_rate']:.0%})"
        if s["payout"] > 0 or has_odds:
            profit_mark = "+" if s["profit"] >= 0 else ""
            line += (f" 回収率{s['return_rate']:.0%}"
                     f" ({profit_mark}{s['profit']:,}円)")
        lines.append(line)

    lines.append("")
    lines.append("=" * 30)
    return "\n".join(lines)


def get_cumulative_stats() -> str:
    """全開催日の累計成績を計算して返す"""
    review_files = sorted(f for f in REVIEW_DIR.glob("*.json") if not f.name.startswith("._"))
    if not review_files:
        return "累計データがありません。"

    all_strategies = {}
    total_days = 0

    for f in review_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        total_days += 1
        for name, s in data["strategies"].items():
            if name not in all_strategies:
                all_strategies[name] = {
                    "bets": 0, "hits": 0, "investment": 0, "payout": 0,
                }
            all_strategies[name]["bets"] += s["bets"]
            all_strategies[name]["hits"] += s["hits"]
            all_strategies[name]["investment"] += s["investment"]
            all_strategies[name]["payout"] += s["payout"]

    lines = []
    lines.append(f"📊 帯広ばんえい競馬 AI予想 累計成績")
    lines.append(f"📅 集計期間: {total_days}開催日分")
    lines.append("=" * 30)
    lines.append("")

    for name, s in all_strategies.items():
        hit_rate = s["hits"] / s["bets"] if s["bets"] > 0 else 0
        return_rate = s["payout"] / s["investment"] if s["investment"] > 0 else 0
        profit = s["payout"] - s["investment"]
        profit_mark = "+" if profit >= 0 else ""
        lines.append(
            f"  {name}:\n"
            f"    {s['hits']}/{s['bets']}着中 ({hit_rate:.1%})\n"
            f"    投資 {s['investment']:,}円 → 払戻 {s['payout']:,}円\n"
            f"    回収率 {return_rate:.0%} ({profit_mark}{profit:,}円)"
        )
        lines.append("")

    lines.append("=" * 30)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="帯広ばんえい競馬 予想検証")
    parser.add_argument("--date", help="検証日 (YYYY-MM-DD, デフォルト: 本日)")
    parser.add_argument("--summary", action="store_true", help="累計成績を表示")
    args = parser.parse_args()

    if args.summary:
        text = get_cumulative_stats()
        print(text)
        send_telegram(text)
        return

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = date.today()

    stats = review_date(target_date)
    if stats is None:
        logger.info("検証対象なし。終了します。")
        sys.exit(0)

    # JSON保存（累計集計用）
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REVIEW_DIR / f"{stats['date']}.json"
    json_path.write_text(
        json.dumps(stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("検証結果保存: %s", json_path)

    # テキスト表示 & Telegram配信
    text = format_review_text(stats)
    print(text)
    send_telegram(text)

    # 累計成績も配信
    cumulative = get_cumulative_stats()
    print(cumulative)
    send_telegram(cumulative)

    logger.info("検証完了")


if __name__ == "__main__":
    main()
