"""
test_inbox_writer.py
Unit tests for inbox_writer.append using a temporary directory.
"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import inbox_writer


class TestInboxWriter:
    def test_creates_new_file_with_header(self, tmp_path):
        """A new daily file is created with the correct header."""
        start = datetime(2026, 5, 31, 14, 0, 0)
        end = datetime(2026, 5, 31, 15, 0, 0)

        inbox_writer.append(start, end, "Hello world", inbox_dir=str(tmp_path))

        md_file = tmp_path / "2026-05-31.md"
        assert md_file.exists(), "Daily file not created"
        content = md_file.read_text(encoding="utf-8")
        assert "# 2026-05-31 音声ログ" in content

    def test_section_heading_format(self, tmp_path):
        """Section heading follows ## HH:MM-HH:MM format."""
        start = datetime(2026, 5, 31, 9, 0, 0)
        end = datetime(2026, 5, 31, 10, 0, 0)

        inbox_writer.append(start, end, "テスト", inbox_dir=str(tmp_path))

        content = (tmp_path / "2026-05-31.md").read_text(encoding="utf-8")
        assert "## 09:00–10:00" in content

    def test_text_body_appended(self, tmp_path):
        """Text content is written after the heading."""
        start = datetime(2026, 5, 31, 10, 0, 0)
        end = datetime(2026, 5, 31, 11, 0, 0)
        text = "んれはテスト本文です。"

        inbox_writer.append(start, end, text, inbox_dir=str(tmp_path))

        content = (tmp_path / "2026-05-31.md").read_text(encoding="utf-8")
        assert text in content

    def test_empty_text_uses_placeholder(self, tmp_path):
        """Empty text results in placeholder string."""
        start = datetime(2026, 5, 31, 11, 0, 0)
        end = datetime(2026, 5, 31, 12, 0, 0)

        inbox_writer.append(start, end, "", inbox_dir=str(tmp_path))

        content = (tmp_path / "2026-05-31.md").read_text(encoding="utf-8")
        assert "（無音/認識なし）" in content

    def test_multiple_appends_not_overwrite(self, tmp_path):
        """Multiple appends accumulate entries without overwriting."""
        for hour in range(3):
            start = datetime(2026, 5, 31, hour, 0, 0)
            end = datetime(2026, 5, 31, hour + 1, 0, 0)
            inbox_writer.append(start, end, f"Entry {hour}", inbox_dir=str(tmp_path))

        content = (tmp_path / "2026-05-31.md").read_text(encoding="utf-8")
        for hour in range(3):
            assert f"Entry {hour}" in content
        # Header appears only once
        assert content.count("# 2026-05-31 音声ログ") == 1

    def test_utf8_encoding(self, tmp_path):
        """File is written as UTF-8."""
        start = datetime(2026, 5, 31, 8, 0, 0)
        end = datetime(2026, 5, 31, 9, 0, 0)
        text = "日本語テキスト：こんにちは世界"

        inbox_writer.append(start, end, text, inbox_dir=str(tmp_path))

        raw = (tmp_path / "2026-05-31.md").read_bytes()
        decoded = raw.decode("utf-8")
        assert text in decoded

    def test_creates_inbox_dir_if_missing(self, tmp_path):
        """inbox_dir is created automatically if it does not exist."""
        nested = tmp_path / "deep" / "inbox"
        start = datetime(2026, 5, 31, 6, 0, 0)
        end = datetime(2026, 5, 31, 7, 0, 0)

        inbox_writer.append(start, end, "test", inbox_dir=str(nested))

        assert nested.exists()
        assert (nested / "2026-05-31.md").exists()
