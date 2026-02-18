#!/usr/bin/env python3
"""データ収集 → オッズ別信頼性分析 をワンステップで実行する。

このスクリプトをローカルPCで実行してください。
1. 指定期間のレースデータをスクレイピング（既に取得済みならスキップ）
2. オッズ別に1-2番人気の信頼性を分析
3. 結果をテキストファイルに出力

Usage:
    # 2024年1年分を取得して分析
    python scripts/scrape_and_analyze_odds.py --from-date 2024-01-01 --to-date 2024-12-31

    # 2025年だけ追加で取得して分析
    python scripts/scrape_and_analyze_odds.py --from-date 2025-01-01 --to-date 2025-12-31

    # スクレイピングせず既存データだけで分析
    python scripts/scrape_and_analyze_odds.py --analyze-only

    # DBパスを指定
    python scripts/scrape_and_analyze_odds.py --from-date 2024-01-01 --to-date 2024-12-31 --db D:\\data\\nankan.db
"""

import argparse
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def run_scrape(from_date: str, to_date: str, db_path: str | None = None) -> None:
    """指定期間のスクレイピングを実行する。"""
    from datetime import datetime
    from tqdm import tqdm
    from nankan_predictor.scraper.race_list import RaceListScraper
    from nankan_predictor.scraper.race_result import RaceResultScraper
    from nankan_predictor.scraper.horse_history import HorseHistoryScraper
    from nankan_predictor.storage.database import init_db
    from nankan_predictor.storage.repository import Repository
    from nankan_predictor.config.settings import CACHE_DIR
    import logging

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if db_path:
        from nankan_predictor.config import settings
        settings.DB_PATH = db_path

    init_db()
    repo = Repository()
    race_list_scraper = RaceListScraper(use_cache=True, cache_dir=CACHE_DIR)
    result_scraper = RaceResultScraper(use_cache=True, cache_dir=CACHE_DIR)
    history_scraper = HorseHistoryScraper(use_cache=True, cache_dir=CACHE_DIR)

    from_dt = datetime.strptime(from_date, "%Y-%m-%d")
    to_dt = datetime.strptime(to_date, "%Y-%m-%d")

    # 月単位でレースID取得
    race_ids = []
    current = from_dt.replace(day=1)
    while current <= to_dt:
        ids = race_list_scraper.get_race_ids_for_month(current.year, current.month)
        race_ids.extend(ids)
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    # 範囲外を除外 & 重複除去
    race_ids = list(set(
        r for r in race_ids
        if from_dt <= datetime.strptime(f"{r[0:4]}-{r[6:8]}-{r[8:10]}", "%Y-%m-%d") <= to_dt
    ))
    print(f"\nスクレイピング対象: {len(race_ids)} レース")

    new_horse_ids = set()
    for race_id in tqdm(race_ids, desc="Races"):
        try:
            data = result_scraper.scrape(race_id)
            repo.upsert_race(data["race_info"])
            for entry in data["entries"]:
                if entry.get("horse_id"):
                    repo.upsert_horse(entry["horse_id"], entry.get("horse_name", ""))
                    if not repo.horse_history_exists(entry["horse_id"]):
                        new_horse_ids.add(entry["horse_id"])
                if entry.get("jockey_id"):
                    repo.upsert_jockey(entry["jockey_id"], entry.get("jockey_name", ""))
            repo.upsert_entries(data["entries"])
            for payout in data.get("payouts", []):
                repo.upsert_payout(
                    payout["race_id"], payout["bet_type"],
                    payout["combination"], payout["payout"]
                )
        except Exception as e:
            logging.warning("Failed to scrape race %s: %s", race_id, e)

    # 馬の過去成績（オッズ分析には不要だが、将来の学習用に取得）
    print(f"\n馬の過去成績取得: {len(new_horse_ids)} 頭")
    for horse_id in tqdm(new_horse_ids, desc="Horse histories"):
        try:
            rows = history_scraper.scrape(horse_id)
            repo.upsert_horse_history(horse_id, rows)
        except Exception as e:
            logging.warning("Failed to scrape horse %s: %s", horse_id, e)

    print("スクレイピング完了\n")


def run_analysis(db_path: str, output_file: str | None = None) -> None:
    """odds_reliability_analysis を実行する。"""
    import sqlite3
    from collections import defaultdict

    # odds_reliability_analysis.py の関数を直接インポート
    sys.path.insert(0, os.path.dirname(__file__))
    from odds_reliability_analysis import (
        get_connection, fetch_race_data,
        analyze_by_fav1_odds, analyze_by_fav2_odds,
        analyze_odds_gap, analyze_combined_odds_level,
        analyze_fav1_odds_threshold_detail, analyze_venue_comparison,
        print_summary,
    )

    if not os.path.exists(db_path):
        print(f"ERROR: {db_path} が見つかりません")
        return

    conn = get_connection(db_path)
    races = fetch_race_data(conn)
    conn.close()

    print(f"\n{'=' * 80}")
    print(f"オッズ別 1-2番人気信頼性分析")
    print(f"対象レース数: {len(races)}")
    print(f"{'=' * 80}")

    if not races:
        print("データがありません。先にスクレイピングを実行してください。")
        return

    # 基本統計
    fav1_wins = sum(1 for r in races if r["fav1_finish"] == 1)
    fav2_wins = sum(1 for r in races if r["fav2_finish"] == 1)
    fav12_wins = sum(1 for r in races if r["fav1_finish"] == 1 or r["fav2_finish"] == 1)
    avg_fav1_odds = sum(r["fav1_odds"] for r in races) / len(races)
    avg_fav2_odds = sum(r["fav2_odds"] for r in races) / len(races)

    print(f"\n  全体統計:")
    print(f"    1番人気 平均オッズ: {avg_fav1_odds:.1f}倍  勝率: {fav1_wins/len(races)*100:.1f}%")
    print(f"    2番人気 平均オッズ: {avg_fav2_odds:.1f}倍  勝率: {fav2_wins/len(races)*100:.1f}%")
    print(f"    1-2人気のどちらかが1着: {fav12_wins/len(races)*100:.1f}%")

    # 各分析を実行
    analyze_by_fav1_odds(races)
    analyze_by_fav2_odds(races)
    analyze_odds_gap(races)
    analyze_combined_odds_level(races)
    analyze_fav1_odds_threshold_detail(races)
    analyze_venue_comparison(races)
    print_summary(races)


def main():
    parser = argparse.ArgumentParser(
        description="データ収集 → オッズ別信頼性分析",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
例:
  # 2024年全データを取得して分析
  python scripts/scrape_and_analyze_odds.py --from-date 2024-01-01 --to-date 2024-12-31

  # スクレイピング済みのDBだけで分析
  python scripts/scrape_and_analyze_odds.py --analyze-only --db D:\\data\\nankan.db

  # 結果をファイルに保存
  python scripts/scrape_and_analyze_odds.py --analyze-only > result.txt
"""
    )
    parser.add_argument("--from-date", help="スクレイピング開始日 (YYYY-MM-DD)")
    parser.add_argument("--to-date", help="スクレイピング終了日 (YYYY-MM-DD)")
    parser.add_argument("--db", default="data/nankan.db", help="DBパス")
    parser.add_argument("--analyze-only", action="store_true",
                        help="スクレイピングせず既存データだけで分析")
    args = parser.parse_args()

    if not args.analyze_only:
        if not args.from_date or not args.to_date:
            print("ERROR: --from-date と --to-date を指定してください")
            print("       既存データだけで分析するなら --analyze-only を使ってください")
            sys.exit(1)
        print("=" * 80)
        print(f"STEP 1: スクレイピング ({args.from_date} ~ {args.to_date})")
        print("=" * 80)
        run_scrape(args.from_date, args.to_date, args.db)

    print("\n" + "=" * 80)
    print("STEP 2: オッズ別信頼性分析")
    print("=" * 80)
    run_analysis(args.db)


if __name__ == "__main__":
    main()
