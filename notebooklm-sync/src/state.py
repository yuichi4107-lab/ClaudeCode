"""
処理済み動画IDをSQLiteで管理する。
同一video_idの二重挿入を防ぐ冪等設計。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_videos (
    channel_id   TEXT NOT NULL,
    video_id     TEXT NOT NULL,
    title        TEXT,
    published_at TEXT,
    added_at     TEXT NOT NULL,
    PRIMARY KEY (channel_id, video_id)
);
"""


class StateDB:
    def __init__(self, db_path: str = "state.sqlite") -> None:
        self._path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        # 既存DBへのマイグレーション（published_at カラム追加）
        try:
            self._conn.execute("ALTER TABLE processed_videos ADD COLUMN published_at TEXT")
        except sqlite3.OperationalError:
            pass  # already exists
        self._conn.commit()

    def is_processed(self, channel_id: str, video_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM processed_videos WHERE channel_id = ? AND video_id = ?",
            (channel_id, video_id),
        )
        return cur.fetchone() is not None

    def mark_processed(
        self,
        channel_id: str,
        video_id: str,
        title: str = "",
        published_at: str = "",
    ) -> None:
        """INSERT OR REPLACE で冪等に記録する。"""
        added_at = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO processed_videos
                (channel_id, video_id, title, published_at, added_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (channel_id, video_id, title, published_at, added_at),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "StateDB":
        return self

    def __exit__(self, *_) -> None:
        self.close()
