"""list_builder → personalizer → approve → gmail_sender を dry_run で通す結合テスト。"""
import json
from unittest.mock import MagicMock

import pytest

from core.approval_queue import ApprovalQueue
from core.db import Database, init_schema
from core.senders.gmail_sender import GmailSender
from tracks.c_outbound.list_builder import ListBuilder
from tracks.c_outbound.personalizer import Personalizer


def _mock_places_single(place_id="pid_e2e"):
    client = MagicMock()
    client.search_text.return_value = [{
        "place_id": place_id,
        "name": "E2E税理士事務所",
        "website": "https://e2e.example.com",
        "formatted_address": "東京都",
        "types": ["accounting"],
    }]
    return client


def _mock_claude_valid_draft():
    client = MagicMock()
    resp = MagicMock()
    resp.content = [MagicMock(text=json.dumps({
        "subject": "E2E税理士事務所 様 — AI業務自動化ツールのご案内",
        "body": "山田です。貴事務所のHPを拝見しました。\n主な活用例:\n・請求書自動生成\n無料トライアルあります。",
        "personalization_hint": "中小企業支援",
    }, ensure_ascii=False))]
    client.messages.create.return_value = resp
    return client


def _mock_hp_fetcher():
    f = MagicMock()
    f.fetch_summary.return_value = "中小企業の税務顧問を得意とする事務所です"
    return f


def test_end_to_end_dry_run(tmp_db_path, env_stub):
    """list_builder → personalizer → approve → gmail_sender（dry_run）まで一気通貫"""
    db = Database(tmp_db_path)
    init_schema(db)

    # 1. 企業リスト取得
    ListBuilder(db=db, places_client=_mock_places_single()).fetch_t2(
        query="税理士", location=(35.68, 139.76), max_results=10
    )

    # 2. contact_email を設定（本来はユーザが手動または別途補完）
    with db.connect() as conn:
        conn.execute(
            "UPDATE companies SET contact_email = 'e2e@e2e.example.com' WHERE id = 1"
        )

    # 3. 下書き生成 & pending 投入
    processed = Personalizer(
        db=db,
        claude_client=_mock_claude_valid_draft(),
        hp_fetcher=_mock_hp_fetcher(),
    ).process_new_companies(batch_size=10)
    assert processed == 1

    # 4. 承認
    q = ApprovalQueue(db)
    pending = q.list_pending(track="c")
    assert len(pending) == 1
    q.approve(pending[0]["id"])

    # 5. 送信（dry_run）
    sender = GmailSender(
        db=db,
        gmail_service=MagicMock(),
        sender_name="YN Factory",
        sender_address="me@example.com",
        reply_to="me@example.com",
        unsubscribe_url="https://example.com/unsub",
        dry_run=True,
        send_interval_sec=0,
        daily_limit=100,
    )
    sent = sender.send_all_approved(track="c")
    assert sent == 1

    # 6. 最終状態: queue は sent、company は drafted
    final_item = q.get(pending[0]["id"])
    assert final_item["status"] == "sent"
    payload = json.loads(final_item["payload_json"])
    assert payload["gmail_message_id"] == "dry_run"
