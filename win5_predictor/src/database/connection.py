"""SQLiteデータベース接続・マイグレーション管理"""

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from config.settings import DB_PATH

logger = logging.getLogger(__name__)


class Database:
    """SQLiteデータベース接続を管理するクラス"""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = str(db_path or DB_PATH)
        self._shared_conn: sqlite3.Connection | None = None
        if self.db_path != ":memory:":
            self._ensure_db_dir()

    def _ensure_db_dir(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        # :memory: の場合は共有接続を使い回す
        if self.db_path == ":memory:":
            if self._shared_conn is None:
                self._shared_conn = sqlite3.connect(":memory:")
                self._shared_conn.row_factory = sqlite3.Row
                self._shared_conn.execute("PRAGMA foreign_keys=ON")
            return self._shared_conn

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def transaction(self):
        """トランザクション付きコネクションを返すコンテキストマネージャ"""
        conn = self.get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if self.db_path != ":memory:":
                conn.close()

    @contextmanager
    def cursor(self):
        """カーソルを返すコンテキストマネージャ"""
        conn = self.get_connection()
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if self.db_path != ":memory:":
                conn.close()

    def initialize(self):
        """データベースを初期化し、全テーブルを作成する"""
        migration_dir = Path(__file__).parent / "migrations"
        sql_file = migration_dir / "001_initial_schema.sql"

        if not sql_file.exists():
            raise FileNotFoundError(f"Migration file not found: {sql_file}")

        with self.transaction() as conn:
            conn.executescript(sql_file.read_text(encoding="utf-8"))

        logger.info("Database initialized: %s", self.db_path)

    def run_migrations(self):
        """マイグレーションを順次適用する"""
        migration_dir = Path(__file__).parent / "migrations"
        if not migration_dir.exists():
            return

        with self.transaction() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS _migrations ("
                "  filename TEXT PRIMARY KEY,"
                "  applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
                ")"
            )

            applied = {
                row["filename"]
                for row in conn.execute("SELECT filename FROM _migrations").fetchall()
            }

            sql_files = sorted(migration_dir.glob("*.sql"))
            for sql_file in sql_files:
                if sql_file.name not in applied:
                    logger.info("Applying migration: %s", sql_file.name)
                    conn.executescript(sql_file.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO _migrations (filename) VALUES (?)",
                        (sql_file.name,),
                    )

        logger.info("All migrations applied.")


# デフォルトインスタンス
db = Database()
