"""
state.py の冪等性テスト。
同一 video_id を二重挿入しても重複レコードが発生しないことを確認する。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

# srcディレクトリをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from state import StateDB


class TestStateDB(unittest.TestCase):
    def setUp(self):
        # 各テストで独立した一時DBを使用する
        self._tmp = tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False)
        self._tmp.close()
        self._db_path = self._tmp.name

    def tearDown(self):
        os.unlink(self._db_path)

    def _make_db(self) -> StateDB:
        return StateDB(db_path=self._db_path)

    def test_is_processed_returns_false_for_new_video(self):
        with self._make_db() as db:
            self.assertFalse(db.is_processed("ch1", "vid1"))

    def test_mark_processed_makes_is_processed_true(self):
        with self._make_db() as db:
            db.mark_processed("ch1", "vid1", "Test Video")
            self.assertTrue(db.is_processed("ch1", "vid1"))

    def test_double_insert_is_idempotent(self):
        """同一 video_id を2回 mark_processed しても1レコードしか存在しない。"""
        with self._make_db() as db:
            db.mark_processed("ch1", "vid1", "Test Video")
            db.mark_processed("ch1", "vid1", "Test Video Updated")  # 2回目
            self.assertTrue(db.is_processed("ch1", "vid1"))

            # レコード数が1であることを確認
            cur = db._conn.execute(
                "SELECT COUNT(*) FROM processed_videos WHERE channel_id=? AND video_id=?",
                ("ch1", "vid1"),
            )
            count = cur.fetchone()[0]
            self.assertEqual(count, 1)

    def test_different_channels_are_independent(self):
        """同じ video_id でもチャンネルが異なれば独立したレコードとして扱う。"""
        with self._make_db() as db:
            db.mark_processed("ch1", "vid1", "Video in ch1")
            self.assertTrue(db.is_processed("ch1", "vid1"))
            self.assertFalse(db.is_processed("ch2", "vid1"))

    def test_different_videos_in_same_channel(self):
        with self._make_db() as db:
            db.mark_processed("ch1", "vid1", "Video 1")
            self.assertFalse(db.is_processed("ch1", "vid2"))
            db.mark_processed("ch1", "vid2", "Video 2")
            self.assertTrue(db.is_processed("ch1", "vid2"))

    def test_persistence_across_connections(self):
        """DBを閉じて再接続しても記録が保持されること。"""
        db1 = self._make_db()
        db1.mark_processed("ch1", "vid1", "Persistent Video")
        db1.close()

        db2 = self._make_db()
        self.assertTrue(db2.is_processed("ch1", "vid1"))
        db2.close()

    def test_sql_injection_safety(self):
        """パラメータバインディングにより、特殊文字を含むIDでもクラッシュしない。"""
        malicious_id = "'; DROP TABLE processed_videos; --"
        with self._make_db() as db:
            db.mark_processed("ch1", malicious_id, "Injection Test")
            self.assertTrue(db.is_processed("ch1", malicious_id))
            # テーブルが存在することを確認（DROPされていない）
            cur = db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='processed_videos'"
            )
            self.assertIsNotNone(cur.fetchone())


if __name__ == "__main__":
    unittest.main()
