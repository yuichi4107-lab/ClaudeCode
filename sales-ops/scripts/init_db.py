"""DB初期化CLI: `python scripts/init_db.py` でスキーマ作成。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

from core.config import Config
from core.db import Database, init_schema


def main() -> int:
    load_dotenv()
    cfg = Config.load()
    db = Database(cfg.db_path)
    init_schema(db)
    print(f"[OK] schema initialized at {cfg.db_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
