import json
from unittest.mock import MagicMock

import pytest

from core.approval_queue import ApprovalQueue
from core.db import Database, init_schema
from tracks.c_outbound.personalizer import Personalizer


@pytest.fixture
def db(tmp_db_path):
    d = Database(tmp_db_path)
    init_schema(d)
    # 新規企業を1件登録
    with d.connect() as conn:
        conn.execute(
            "INSERT INTO companies (source, segment, company_name, website_url, "
            "industry, status) VALUES ('google_maps', 't2_pro_service', "
            "'A税理士事務所', 'https://a-tax.example.com', 'accounting', 'new')"
        )
    return d


def _mock_claude(response_json: dict):
    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps(response_json, ensure_ascii=False))]
    client.messages.create.return_value = resp
    return client


def _mock_http_fetch(text: str = "当事務所は中小企業の経営支援に注力しています"):
    fetcher = MagicMock()
    fetcher.fetch_summary.return_value = text
    return fetcher


def test_personalize_inserts_pending_dm(db, env_stub):
    claude = _mock_claude({
        "subject": "A税理士事務所 様 — 顧問先の業務自動化ツールのご案内",
        "body": "山田と申します。貴事務所のHPで中小企業支援に注力されている旨を拝見し……",
        "personalization_hint": "中小企業支援",
    })
    fetcher = _mock_http_fetch()
    p = Personalizer(db=db, claude_client=claude, hp_fetcher=fetcher, model="claude-opus-4-7")

    processed = p.process_new_companies(batch_size=10)
    assert processed == 1

    queue = ApprovalQueue(db)
    items = queue.list_pending(track="c")
    assert len(items) == 1
    payload = json.loads(items[0]["payload_json"])
    assert "A税理士事務所" in payload["subject"]
    assert payload["to_company_id"] is not None


def test_personalize_updates_company_status(db, env_stub):
    claude = _mock_claude({
        "subject": "件名",
        "body": "本文",
        "personalization_hint": "ヒント",
    })
    p = Personalizer(db=db, claude_client=claude, hp_fetcher=_mock_http_fetch())
    p.process_new_companies(batch_size=10)

    with db.connect() as conn:
        row = conn.execute("SELECT status FROM companies").fetchone()
    assert row["status"] == "drafted"


def test_personalize_blocks_unfilled_placeholders(db, env_stub):
    # Claude が差込変数を残したまま返した場合はブロック
    claude = _mock_claude({
        "subject": "{{company_name}} 様 — オファー",  # 未展開
        "body": "本文",
        "personalization_hint": "",
    })
    p = Personalizer(db=db, claude_client=claude, hp_fetcher=_mock_http_fetch())
    processed = p.process_new_companies(batch_size=10)

    # ブロックされてキューには入らない
    queue = ApprovalQueue(db)
    assert queue.list_pending(track="c") == []
    # 企業ステータスは needs_retry
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM companies").fetchone()
    assert row["status"] == "needs_retry"


def test_personalize_skips_when_no_new_companies(db, env_stub):
    with db.connect() as conn:
        conn.execute("UPDATE companies SET status = 'drafted'")
    p = Personalizer(db=db, claude_client=_mock_claude({}), hp_fetcher=_mock_http_fetch())
    assert p.process_new_companies(batch_size=10) == 0
