"""特徴量行列構築スクリプト

Usage:
    python -m scripts.02_build_features --start-date 2021-01-01 --end-date 2025-12-31
"""

import argparse
import os
import sys
import time

import pandas as pd

# プロジェクトルートをsys.pathに追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.database.db_manager import DBManager
from src.features.feature_pipeline import FeaturePipeline
from src.utils.config_loader import get_db_path, get_project_root
from src.utils.logger import setup_logger

logger = setup_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="特徴量行列を構築する")
    parser.add_argument(
        "--start-date", type=str, required=True,
        help="開始日 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date", type=str, required=True,
        help="終了日 (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="出力ファイルパス (デフォルト: data/features.parquet)",
    )
    parser.add_argument(
        "--format", type=str, choices=["parquet", "csv"], default="parquet",
        help="出力形式 (default: parquet)",
    )
    args = parser.parse_args()

    db_path = get_db_path()
    if not os.path.exists(db_path):
        logger.error("Database not found: %s", db_path)
        logger.error("Run 01_scrape_races.py first to populate the database.")
        sys.exit(1)

    db = DBManager(db_path)
    pipeline = FeaturePipeline(db)

    logger.info("Building features from %s to %s", args.start_date, args.end_date)
    start_time = time.time()

    df = pipeline.build_features_for_date_range(args.start_date, args.end_date)

    elapsed = time.time() - start_time
    logger.info("Feature building completed in %.1f seconds", elapsed)

    if df.empty:
        logger.warning("No features were built. Check that the database has data.")
        sys.exit(1)

    # 出力先の決定
    if args.output:
        output_path = args.output
    else:
        data_dir = os.path.join(get_project_root(), "data")
        os.makedirs(data_dir, exist_ok=True)
        ext = ".parquet" if args.format == "parquet" else ".csv"
        output_path = os.path.join(data_dir, f"features{ext}")

    # 保存
    if args.format == "parquet":
        df.to_parquet(output_path, index=False)
    else:
        df.to_csv(output_path, index=False, encoding="utf-8-sig")

    logger.info("Features saved to %s (%d rows x %d columns)", output_path, len(df), len(df.columns))
    logger.info("Feature columns: %s", list(df.columns))


if __name__ == "__main__":
    main()
