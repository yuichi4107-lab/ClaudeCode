import json

import pytest

from core.approval_queue import ApprovalQueue, ItemNotFound, InvalidTransition
from core.db import Database, init_schema


@pytest.fixture
def queue(tmp_db_path):
    db = Database(tmp_db_path)
    init_schema(db)
    return ApprovalQueue(db)


def test_enqueue_returns_id_and_is_pending(queue):
    item_id = queue.enqueue(track="c", item_type="dm", payload={"to": "a@b.com", "body": "hi"})
    assert isinstance(item_id, int) and item_id > 0

    items = queue.list_pending(track="c")
    assert len(items) == 1
    assert items[0]["id"] == item_id
    assert items[0]["status"] == "pending"
    assert json.loads(items[0]["payload_json"])["to"] == "a@b.com"


def test_approve_transitions_pending_to_approved(queue):
    item_id = queue.enqueue(track="c", item_type="dm", payload={"to": "a@b.com"})
    queue.approve(item_id)

    item = queue.get(item_id)
    assert item["status"] == "approved"
    assert item["approved_at"] is not None


def test_reject_marks_status(queue):
    item_id = queue.enqueue(track="c", item_type="dm", payload={"to": "a@b.com"})
    queue.reject(item_id)
    assert queue.get(item_id)["status"] == "rejected"


def test_mark_sent_only_from_approved(queue):
    item_id = queue.enqueue(track="c", item_type="dm", payload={"to": "a@b.com"})
    with pytest.raises(InvalidTransition):
        queue.mark_sent(item_id, gmail_message_id="abc")
    queue.approve(item_id)
    queue.mark_sent(item_id, gmail_message_id="abc")
    assert queue.get(item_id)["status"] == "sent"


def test_mark_failed_records_error(queue):
    item_id = queue.enqueue(track="c", item_type="dm", payload={"to": "a@b.com"})
    queue.approve(item_id)
    queue.mark_failed(item_id, "SMTP timeout")
    item = queue.get(item_id)
    assert item["status"] == "failed"
    assert item["error_message"] == "SMTP timeout"


def test_get_raises_when_missing(queue):
    with pytest.raises(ItemNotFound):
        queue.get(999)


def test_list_approved_returns_only_approved(queue):
    a = queue.enqueue(track="c", item_type="dm", payload={})
    b = queue.enqueue(track="c", item_type="dm", payload={})
    queue.approve(a)
    # b は pending のまま

    approved = queue.list_approved(track="c")
    assert [i["id"] for i in approved] == [a]


def test_auto_reject_stale_pending(queue, monkeypatch):
    """48時間経過した pending を自動 reject"""
    import datetime as dt

    item_id = queue.enqueue(track="c", item_type="dm", payload={})
    # created_at を手動で48時間前に書き換え
    with queue.db.connect() as conn:
        conn.execute(
            "UPDATE approval_queue SET created_at = ? WHERE id = ?",
            ((dt.datetime.utcnow() - dt.timedelta(hours=49)).isoformat(), item_id),
        )

    rejected_count = queue.auto_reject_stale(max_age_hours=48)
    assert rejected_count == 1
    assert queue.get(item_id)["status"] == "rejected"
