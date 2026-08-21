"""SQLite 接続と初期スキーマ。DBファイルはローカル配置（Google Drive配下禁止）。"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS approval_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track TEXT NOT NULL CHECK(track IN ('a', 'b', 'c')),
    item_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'approved', 'rejected', 'sent', 'failed')),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP,
    sent_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_queue_status ON approval_queue(status, track);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK(source IN ('google_maps', 'biz_db', 'manual')),
    segment TEXT NOT NULL CHECK(segment IN ('t1_sme', 't2_pro_service')),
    company_name TEXT NOT NULL,
    website_url TEXT UNIQUE NOT NULL,
    contact_email TEXT,
    industry TEXT,
    size_employees INTEGER,
    location TEXT,
    hp_summary TEXT,
    personalization_hints TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_companies_status ON companies(status);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    direction TEXT NOT NULL CHECK(direction IN ('outbound', 'inbound')),
    subject TEXT,
    body TEXT,
    gmail_message_id TEXT,
    sent_at TIMESTAMP,
    received_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_conv_company ON conversations(company_id);

CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id),
    stage TEXT NOT NULL CHECK(stage IN ('lead', 'qualified', 'proposal', 'won', 'lost')),
    offer TEXT,
    amount_yen INTEGER,
    stage_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS daily_kpi (
    date DATE NOT NULL,
    track TEXT NOT NULL,
    metric TEXT NOT NULL,
    value REAL NOT NULL,
    PRIMARY KEY (date, track, metric)
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def init_schema(db: Database) -> None:
    with db.connect() as conn:
        conn.executescript(SCHEMA_SQL)
