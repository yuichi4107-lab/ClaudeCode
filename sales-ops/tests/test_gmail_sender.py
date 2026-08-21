import base64
import json
from unittest.mock import MagicMock

import pytest

from core.approval_queue import ApprovalQueue
from core.db import Database, init_schema
from core.senders.gmail_sender import GmailSender, build_raw_email, DailyLimitReached


@pytest.fixture
def db(tmp_db_path):
    d = Database(tmp_db_path)
    init_schema(d)
    with d.connect() as conn:
        conn.execute(
            "INSERT INTO companies (source, segment, company_name, website_url, "
            "contact_email, status) VALUES ('google_maps', 't2_pro_service', "
            "'A税理士', 'https://a.example.com', 'contact@a.example.com', 'drafted')"
        )
    return d


def _enqueue_approved(db, body="本文です", subject="テスト件名", to_company_id=1):
    q = ApprovalQueue(db)
    item_id = q.enqueue(track="c", item_type="dm", payload={
        "to_company_id": to_company_id,
        "subject": subject,
        "body": body,
    })
    q.approve(item_id)
    return item_id


def test_build_raw_email_includes_required_headers():
    raw = build_raw_email(
        sender_name="YN Factory",
        sender_address="me@example.com",
        reply_to="me@example.com",
        to_address="you@example.com",
        subject="件名",
        body_text="本文",
        unsubscribe_url="https://example.com/unsub",
    )
    decoded = base64.urlsafe_b64decode(raw.encode()).decode("utf-8", errors="replace")
    assert "From: YN Factory <me@example.com>" in decoded
    assert "To: you@example.com" in decoded
    assert "Subject: =?utf-8?" in decoded  # MIMEエンコード
    assert "Reply-To: me@example.com" in decoded
    assert "List-Unsubscribe: <https://example.com/unsub>" in decoded


def test_sender_dry_run_does_not_call_api(db, env_stub):
    service = MagicMock()
    sender = GmailSender(
        db=db, gmail_service=service,
        sender_name="YN Factory", sender_address="me@example.com",
        reply_to="me@example.com", unsubscribe_url="https://example.com/unsub",
        dry_run=True, send_interval_sec=0, daily_limit=100,
    )

    item_id = _enqueue_approved(db)
    sender.send_all_approved(track="c")

    service.users().messages().send.assert_not_called()
    q = ApprovalQueue(db)
    assert q.get(item_id)["status"] == "sent"  # dry_runでもsent扱い（動作確認のため）


def test_sender_live_calls_api_and_marks_sent(db, env_stub):
    service = MagicMock()
    service.users().messages().send().execute.return_value = {"id": "gmail_msg_xyz"}

    sender = GmailSender(
        db=db, gmail_service=service,
        sender_name="YN Factory", sender_address="me@example.com",
        reply_to="me@example.com", unsubscribe_url="https://example.com/unsub",
        dry_run=False, send_interval_sec=0, daily_limit=100,
    )

    item_id = _enqueue_approved(db)
    sender.send_all_approved(track="c")

    q = ApprovalQueue(db)
    item = q.get(item_id)
    assert item["status"] == "sent"
    payload = json.loads(item["payload_json"])
    assert payload["gmail_message_id"] == "gmail_msg_xyz"


def test_sender_respects_daily_limit(db, env_stub):
    service = MagicMock()
    service.users().messages().send().execute.return_value = {"id": "msg"}
    sender = GmailSender(
        db=db, gmail_service=service,
        sender_name="YN", sender_address="me@example.com",
        reply_to="me@example.com", unsubscribe_url="https://example.com/unsub",
        dry_run=False, send_interval_sec=0, daily_limit=1,
    )

    _enqueue_approved(db)
    _enqueue_approved(db, to_company_id=1)  # 同じ company_id で2件目

    with pytest.raises(DailyLimitReached):
        sender.send_all_approved(track="c")


def test_sender_blocks_when_company_has_no_email(db, env_stub):
    # contact_email を NULL にしてしまう
    with db.connect() as conn:
        conn.execute("UPDATE companies SET contact_email = NULL WHERE id = 1")

    service = MagicMock()
    sender = GmailSender(
        db=db, gmail_service=service,
        sender_name="YN", sender_address="me@example.com",
        reply_to="me@example.com", unsubscribe_url="https://example.com/unsub",
        dry_run=False, send_interval_sec=0, daily_limit=100,
    )

    item_id = _enqueue_approved(db)
    sender.send_all_approved(track="c")

    q = ApprovalQueue(db)
    item = q.get(item_id)
    assert item["status"] == "failed"
    assert "contact_email" in (item["error_message"] or "")
