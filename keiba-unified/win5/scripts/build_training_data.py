"""学習データ生成スクリプト

FeatureBuilder.build_training_data() を呼び出し、指定期間の特徴量を
parquet 形式で保存する。所要時間を出力する。

使い方:
    PYTHONPATH=src python scripts/build_training_data.py \
        --start 2024-01-01 --end 2024-01-31 --out data/_smoke.parquet
"""

import argparse
import logging
import time
from datetime import date
from pathlib import Path

import pandas as pd

from database.connection import Database
from database.repository import Repository
from features.builder import FeatureBuilder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build training data parquet")
    ap.add_argument("--start", required=True, help="開始日 YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="終了日 YYYY-MM-DD")
    ap.add_argument("--out", required=True, help="出力parquetパス")
    ap.add_argument(
        "--no-odds",
        action="store_true",
        help="オッズ特徴量を除外する（デフォルト: オッズ込み）",
    )
    ap.add_argument(
        "--win5-db",
        default="data/win5.db",
        help="読み込むwin5.dbパス（性能のためローカルSSDコピーを指定可）",
    )
    return ap.parse_args()


def main() -> None:
    args = parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    out_path = Path(args.out)
    include_odds = not args.no_odds

    logger.info(
        "Build training data: %s to %s -> %s (include_odds=%s)",
        start,
        end,
        out_path,
        include_odds,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)

    builder = FeatureBuilder(Repository(Database(db_path=args.win5_db, keep_open=True)))

    t0 = time.perf_counter()
    df = builder.build_training_data(start=start, end=end, include_odds=include_odds)
    elapsed = time.perf_counter() - t0

    if df.empty:
        logger.warning("No data generated. Exiting.")
        print(f"elapsed={elapsed:.1f}s  rows=0")
        return

    df.to_parquet(out_path, index=False)

    n_rows, n_cols = df.shape
    n_feat = len([c for c in df.columns if not c.startswith("_") and c != "target"])
    positive_rate = float(df["target"].mean())

    print(
        f"elapsed={elapsed:.1f}s  rows={n_rows}  cols={n_cols}  "
        f"features={n_feat}  positive_rate={positive_rate:.4f}"
    )
    logger.info(
        "Saved: %s  shape=(%d, %d)  positive_rate=%.4f",
        out_path,
        n_rows,
        n_cols,
        positive_rate,
    )


if __name__ == "__main__":
    main()
