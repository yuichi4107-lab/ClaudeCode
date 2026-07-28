import os
import sys
import tempfile
from pathlib import Path

import pytest

# src/ をimportパスに追加
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def tmp_db_path(tmp_path, monkeypatch):
    """Temp SQLite DB path, isolated per test."""
    db_path = tmp_path / "test_sales_ops.db"
    monkeypatch.setenv("SALES_OPS_DB_PATH", str(db_path))
    return str(db_path)


@pytest.fixture
def env_stub(monkeypatch):
    """共通環境変数を stub する。個別テストで上書き可能。"""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-dummy")
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "gmap-test-dummy")
    monkeypatch.setenv("GMAIL_SENDER_ADDRESS", "test@example.com")
    monkeypatch.setenv("GMAIL_SENDER_NAME", "テスト送信者")
    monkeypatch.setenv("GMAIL_REPLY_TO", "test@example.com")
    monkeypatch.setenv("GMAIL_UNSUBSCRIBE_URL", "https://example.com/unsub")
    monkeypatch.setenv("OWNER_NAME", "山田雄一")
    monkeypatch.setenv("OWNER_COMPANY", "YN Factory")
    monkeypatch.setenv("OWNER_WEBSITE", "https://tools.ynfactory.online")
    monkeypatch.setenv("SALES_OPS_DRY_RUN", "true")
    monkeypatch.setenv("SALES_OPS_DAILY_SEND_LIMIT", "100")
    monkeypatch.setenv("SALES_OPS_SEND_INTERVAL_SEC", "0")
    return monkeypatch
