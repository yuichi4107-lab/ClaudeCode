"""Approval キュー: pending → approved/rejected → sent/failed のステート管理。"""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from .db import Database


class ItemNotFound(KeyError):
    pass


class InvalidTransition(RuntimeError):
    pass


class ApprovalQueue:
    def __init__(self, db: Database):
        self.db = db

    def enqueue(self, *, track: str, item_type: str, payload: dict[str, Any]) -> int:
        with self.db.connect() as conn:
            cur = conn.execute(
                "INSERT INTO approval_queue (track, item_type, payload_json, status) "
                "VALUES (?, ?, ?, 'pending')",
                (track, item_type, json.dumps(payload, ensure_ascii=False)),
            )
            return cur.lastrowid

    def get(self, item_id: int) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM approval_queue WHERE id = ?", (item_id,)
            ).fetchone()
        if row is None:
            raise ItemNotFound(item_id)
        return dict(row)

    def list_pending(self, *, track: str | None = None) -> list[dict[str, Any]]:
        return self._list_by_status("pending", track=track)

    def list_approved(self, *, track: str | None = None) -> list[dict[str, Any]]:
        return self._list_by_status("approved", track=track)

    def _list_by_status(self, status: str, *, track: str | None) -> list[dict[str, Any]]:
        q = "SELECT * FROM approval_queue WHERE status = ?"
        args: list[Any] = [status]
        if track is not None:
            q += " AND track = ?"
            args.append(track)
        q += " ORDER BY created_at ASC"
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(q, args).fetchall()]

    def approve(self, item_id: int) -> None:
        self._transition(item_id, from_status="pending", to_status="approved",
                         ts_column="approved_at")

    def reject(self, item_id: int) -> None:
        self._transition(item_id, from_status="pending", to_status="rejected",
                         ts_column=None)

    def mark_sent(self, item_id: int, *, gmail_message_id: str | None = None) -> None:
        self._transition(item_id, from_status="approved", to_status="sent",
                         ts_column="sent_at", extra_payload={"gmail_message_id": gmail_message_id})

    def mark_failed(self, item_id: int, error_message: str) -> None:
        self._transition(item_id, from_status="approved", to_status="failed",
                         ts_column=None, error_message=error_message)

    def _transition(
        self,
        item_id: int,
        *,
        from_status: str,
        to_status: str,
        ts_column: str | None,
        error_message: str | None = None,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        item = self.get(item_id)
        if item["status"] != from_status:
            raise InvalidTransition(
                f"Cannot transition {item['status']} -> {to_status}"
            )

        sets = ["status = ?"]
        args: list[Any] = [to_status]
        if ts_column:
            sets.append(f"{ts_column} = ?")
            args.append(dt.datetime.utcnow().isoformat())
        if error_message is not None:
            sets.append("error_message = ?")
            args.append(error_message)
        if extra_payload:
            payload = json.loads(item["payload_json"])
            payload.update(extra_payload)
            sets.append("payload_json = ?")
            args.append(json.dumps(payload, ensure_ascii=False))
        args.append(item_id)

        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE approval_queue SET {', '.join(sets)} WHERE id = ?", args
            )

    def auto_reject_stale(self, *, max_age_hours: int = 48) -> int:
        cutoff = (dt.datetime.utcnow() - dt.timedelta(hours=max_age_hours)).isoformat()
        with self.db.connect() as conn:
            cur = conn.execute(
                "UPDATE approval_queue SET status = 'rejected' "
                "WHERE status = 'pending' AND created_at < ?",
                (cutoff,),
            )
            return cur.rowcount
