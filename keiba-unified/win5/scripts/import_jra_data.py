"""jra/keiba_live.db を win5.db へ移植する実行スクリプト。

使い方:
  cd keiba-unified/win5
  PYTHONPATH=src python scripts/import_jra_data.py \
      --jra-db ../jra/data/keiba_live.db --win5-db data/win5.db
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from database.connection import Database  # noqa: E402
from database.repository import Repository  # noqa: E402
from etl.jra_importer import JraImporter  # noqa: E402


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--jra-db", default="../jra/data/keiba_live.db")
    ap.add_argument("--win5-db", default="data/win5.db")
    args = ap.parse_args()

    db = Database(db_path=args.win5_db)
    db.initialize()
    repo = Repository(db)

    counts = JraImporter(args.jra_db, repo).run()
    print(f"DONE: races={counts['races']} results={counts['results']}")


if __name__ == "__main__":
    main()
