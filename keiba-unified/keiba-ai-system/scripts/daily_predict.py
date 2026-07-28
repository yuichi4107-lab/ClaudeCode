"""開催日の自動予想スクリプト

開催日の1R発走1時間前にcronで実行し、
予想結果をファイル保存 + Telegram配信する。

使い方:
    PYTHONPATH=. python3 scripts/daily_predict.py
    PYTHONPATH=. python3 scripts/daily_predict.py --date 2026-03-14
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
import requests

# .envファイルから環境変数を読み込み
_env_file = Path(__file__).resolve().parent.parent / ".env"
if _env_file.exists():
    for line in _env_file.read_text().strip().splitlines():
        if "=" in line and not line.startswith("#"):
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

from config.settings import (
    PREDICTIONS_DIR,
    RAW_DATA_DIR,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
)
from src.features.feature_engineering import FeatureEngineer
from src.model.predictor import BaneiPredictor
from src.scraper.banei_scraper import BaneiScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_prediction(target_date: date) -> pd.DataFrame | None:
    """指定日の予測を実行してDataFrameで返す"""
    predictor = BaneiPredictor()
    try:
        predictor.load()
    except FileNotFoundError:
        logger.error("学習済みモデルが見つかりません")
        return None

    # 当日のレースデータを取得
    logger.info("%s のレースデータを取得中...", target_date)
    scraper = BaneiScraper()
    df = scraper.scrape_date_range(target_date, target_date, use_entries=True)
    if df.empty:
        logger.info("%s は開催がありません", target_date)
        return None

    # 過去データと結合して特徴量生成（当日データの重複を除去）
    raw_file = RAW_DATA_DIR / "race_results.csv"
    if raw_file.exists():
        past_df = pd.read_csv(rwf_file)
        date_str = target_date.strftime("%Y-%m-%d")
        past_df = past_df[past_df["race_date"] != date_str]
        combined = pd.concat([past_df, df], ignore_index=True)
    else:
        combined = df

    fe = FeatureEngineer(combined)
    features_df = fe.build_features()

    today_mask = features_df["race_date"] == pd.Timestamp(target_date)
    today_df = features_df[today_mask]

    if today_df.empty:
        logger.error("当日のデータが見つかりません")
        return None

    predictions = predictor.predict(today_df)

    # 出馬表ページからオッズを取得
    logger.info("オッズ取得中...")
    scraper2 = BaneiScraper()
    race_nos = df["race_no"].unique()
    odds_rows = []
    for rno in race_nos:
        odds_dict = scraper2.get_odds(target_date, str(rno))
        for num_str, odds_val in odds_dict.items():
            odds_rows.append({
                "race_no": str(rno),
                "horse_number": int(num_str),
                "odds": odds_val,
            })

    if odds_rows:
        odds_df = pd.DataFrame(odds_rows)
        predictions["race_no"] = predictions["race_no"].astype(str)
        predictions = predictions.merge(
            odds_df,
            on=["race_no", "horse_number"],
            how="left",
        )
        logger.info("オッズ取得完了: %d 頭分", len(odds_rows))
    else:
        predictions["odds"] = None

    return predictions


def save_predictions(
    predictions: pd.DataFrame,
    target_date: date,
    race_from: int = 1,
    race_to: int = 12,
) -> str:
    """予想結果をCSVとテキストファイルに保存する"""
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = target_date.strftime("%Y-%m-%d")
    suffix = f"_R{race_from}-{race_to}"

    # CSV保存（既存ファイルがあればマージして更新）
    csv_path = PREDICTIONS_DIR / f"{date_str}.csv"
    if csv_path.exists():
        existing = pd.read_csv(csv_path)
        merged = pd.concat([existing, predictions], ignore_index=True)
        merged = merged.drop_duplicates(
            subset=["race_no", "horse_number"], keep="last"
        )
        merged.to_csv(csv_path, index=False, encoding="utf-8-sig")
        logger.info("CSV更新(マージ): %s", csv_path)
    else:
        predictions.to_csv(csv_path, index=False, encoding="utf-8-sig")
        logger.info("CSV保存: %s", csv_path)

    # テキスト形式で保存（レース範囲ごと）
    text = format_predictions_text(predictions, target_date, race_from, race_to)
    txt_path = PREDICTIONS_DIR / f"{date_str}{suffix}.txt"
    txt_path.write_text(text, encoding="utf-8")
    logger.info("TXT保存: %s", txt_path)

    return text


def format_predictions_text(
    predictions: pd.DataFrame,
    target_date: date,
    race_from: int = 1,
    race_to: int = 12,
) -> str:
    """予想結果をテキスト形式にフォーマットする"""
    lines = []
    lines.append(f"🏇 帯広ばんえい競馬 AI予想")
    lines.append(f"📅 {target_date.strftime('%Y年%m月%d日')} ({race_from}R〜{race_to}R)")
    lines.append("=" * 30)

    predictions = predictions.copy()
    predictions["race_no_int"] = predictions["race_no"].astype(str).str.strip().astype(int)
    predictions = predictions[
        (predictions["race_no_int"] >= race_from) & (predictions["race_no_int"] <= race_to)
    ]
    for (rd, rno), race in predictions.sort_values("race_no_int").groupby(["race_date", "race_no_int"], sort=True):
        lines.append(f"")
        lines.append(f"【{rno}R】")

        for _, row in race.sort_values("pred_rank").head(5).iterrows():
            rank = int(row["pred_rank"])
            num = int(row["horse_number"]) if pd.notna(row["horse_number"]) else "-"
            name = row["horse_name"]
            prob = row["win_prob"]
            mark = "◎" if rank == 1 else "○" if rank == 2 else "▲" if rank == 3 else "△" if rank == 4 else "　"

            odds_str = ""
            ev_str = ""
            if pd.notna(row.get("odds")) and row["odds"] > 0:
                odds_val = row["odds"]
                ev = prob * odds_val
                odds_str = f" ｵｯｽﾞ{odds_val:.1f}"
                if ev > 1.0:
                    ev_str = " ★"

            lines.append(f"  {mark} {num:>2} {name} ({prob:.1%}){odds_str}{ev_str}")

    lines.append("")
    lines.append("=" * 30)
    lines.append("※ ◎本命 ○対抗 ▲単穴 △連下")
    lines.append("※ ★ = 期待値 > 1.0")

    return "\n".join(lines)


def send_telegram(text: str) -> bool:
    """Telegram にメッセージを送信する"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram設定が未設定です（config/settings.py）")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    # 長いメッセージは4096文字で分割
    max_len = 4096
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]

    for chunk in chunks:
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
            "parse_mode": "HTML",
        }
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code != 200:
                logger.error("Telegram送信失敗: %s %s", resp.status_code, resp.text)
                return False
        except requests.RequestException as e:
            logger.error("Telegram送信エラー: %s", e)
            return False

    logger.info("Telegram配信完了")
    return True


def main():
    parser = argparse.ArgumentParser(description="帯広ばんえい競馬 日次予想")
    parser.add_argument("--date", help="予測日 (YYYY-MM-DD, デフォルト: 本日)")
    parser.add_argument("--race-from", type=int, default=1, help="開始レース番号 (デフォルト: 1)")
    parser.add_argument("--race-to", type=int, default=12, help="終了レース番号 (デフォルト: 12)")
    args = parser.parse_args()

    if args.date:
        target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        target_date = date.today()

    logger.info("予想開始: %s (%dR〜%dR)", target_date, args.race_from, args.race_to)

    # 予測実行
    predictions = run_prediction(target_date)
    if predictions is None:
        logger.info("予想対象なし。終了します。")
        sys.exit(0)

    # ファイル保存
    text = save_predictions(predictions, target_date, args.race_from, args.race_to)

    # Telegram配信
    send_telegram(text)

    logger.info("完了")


if __name__ == "__main__":
    main()
