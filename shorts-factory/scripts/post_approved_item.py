#!/usr/bin/env python3
"""Post one approved shorts-factory queue item in a separate worker process."""
from __future__ import annotations

import argparse
import json
import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.config import CONFIG  # noqa: E402
from src import notify, queue_lib, post_lock  # noqa: E402
from src import drive_guard  # noqa: E402
from src.platforms import poster  # noqa: E402

WORKER_TIMEOUT_SEC = 900
APPROVAL_POST_WINDOW = timedelta(minutes=30)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _finish_worker(item: dict, *, exit_code: int, error: str | None = None) -> None:
    worker = item.setdefault("posting_worker", {})
    worker["completed_at"] = _now()
    worker["exit_code"] = exit_code
    if error:
        worker["error"] = error[:500]
    else:
        worker.pop("error", None)
    queue_lib.save_item(item)


def _timeout_handler(_signum, _frame) -> None:
    raise TimeoutError(f"post worker timed out after {WORKER_TIMEOUT_SEC}s")


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _enabled_platform_statuses(item: dict) -> list[str]:
    return [
        info.get("status")
        for info in (item.get("platforms") or {}).values()
        if info.get("enabled")
    ]


def _posting_allowed(item: dict, *, retry_failed: bool = False) -> tuple[bool, str]:
    review = item.get("review") or {}
    if not review.get("owner_approved"):
        return False, "not_owner_approved"
    if retry_failed:
        if item.get("status") not in {"failed", "partial_failed"}:
            return False, "not_retryable_status"
        return True, "retry_failed"
    decided_at = _parse_iso(review.get("decided_at"))
    if not decided_at:
        return False, "missing_decided_at"
    now = datetime.now().astimezone()
    if decided_at.tzinfo is None and now.tzinfo is not None:
        decided_at = decided_at.replace(tzinfo=now.tzinfo)
    if now - decided_at > APPROVAL_POST_WINDOW:
        return False, "approval_expired"
    statuses = _enabled_platform_statuses(item)
    if any(status == "posted" for status in statuses):
        return False, "already_partially_posted"
    return True, "ok"


def post_one(item_id: str, *, retry_failed: bool = False) -> int:
    fd, lock_path = post_lock.acquire(item_id)
    if fd is None:
        print(json.dumps({"id": item_id, "skipped": "locked", "lock": str(lock_path)}, ensure_ascii=False))
        return 0

    try:
        if hasattr(signal, "SIGALRM"):
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(WORKER_TIMEOUT_SEC)
        item = queue_lib.load_item(item_id)
        if not retry_failed and item.get("status") != "approved":
            _finish_worker(item, exit_code=0)
            print(json.dumps({"id": item_id, "skipped": item.get("status")}, ensure_ascii=False))
            return 0
        allowed, reason = _posting_allowed(item, retry_failed=retry_failed)
        if not allowed:
            item.setdefault("posting_guard", {})["worker_block_reason"] = reason
            item["posting_guard"]["worker_blocked_at"] = _now()
            _finish_worker(item, exit_code=0, error=f"blocked: {reason}")
            print(json.dumps({"id": item_id, "skipped": reason}, ensure_ascii=False))
            return 0

        updated = poster.post_item(item, queue_lib, notify)
        _finish_worker(updated, exit_code=0)
        print(json.dumps({"id": item_id, "status": updated.get("status")}, ensure_ascii=False))
        return 0
    except Exception as exc:
        try:
            item = queue_lib.load_item(item_id)
            _finish_worker(item, exit_code=1, error=str(exc))
        except Exception:
            pass
        print(json.dumps({"id": item_id, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)
        post_lock.release(fd, lock_path)


def main() -> int:
    drive_guard.install()
    CONFIG.assert_runtime_ready()
    ap = argparse.ArgumentParser(description="承認済みシート動画を1件だけ投稿する")
    ap.add_argument("item_id")
    ap.add_argument("--retry-failed", action="store_true")
    args = ap.parse_args()
    return post_one(args.item_id, retry_failed=args.retry_failed)


if __name__ == "__main__":
    raise SystemExit(main())
