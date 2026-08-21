import sqlite3

import pytest

from core.db import Database, init_schema


def test_init_schema_creates_all_tables(tmp_db_path):
    db = Database(tmp_db_path)
    init_schema(db)
    with db.connect() as conn:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert "approval_queue" in tables
    assert "companies" in tables
    assert "conversations" in tables
    assert "deals" in tables
    assert "daily_kpi" in tables


def test_init_schema_is_idempotent(tmp_db_path):
    db = Database(tmp_db_path)
    init_schema(db)
    init_schema(db)  # 2回目もエラーなし
    with db.connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    assert count >= 5


def test_companies_unique_website(tmp_db_path):
    db = Database(tmp_db_path)
    init_schema(db)
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO companies (source, segment, company_name, website_url) "
            "VALUES ('google_maps', 't2_pro_service', 'A社', 'https://a.example.com')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO companies (source, segment, company_name, website_url) "
                "VALUES ('google_maps', 't2_pro_service', 'A社別', 'https://a.example.com')"
            )


def test_approval_queue_status_constraint(tmp_db_path):
    db = Database(tmp_db_path)
    init_schema(db)
    with db.connect() as conn:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO approval_queue (track, item_type, payload_json, status) "
                "VALUES ('c', 'dm', '{}', 'invalid_status')"
            )
