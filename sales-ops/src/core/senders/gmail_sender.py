"""Gmail API 経由でDM送信。承認済みキューから順次送信、日次上限・送信間隔を制御。"""
from __future__ import annotations

import base64
import datetime as dt
import json
import logging
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from core.approval_queue import ApprovalQueue
from core.db import Database

logger = logging.getLogger(__name__)


class DailyLimitReached(RuntimeError):
    pass


def build_raw_email(
    *,
    sender_name: str,
    sender_address: str,
    reply_to: str,
    to_address: str,
    subject: str,
    body_text: str,
    unsubscribe_url: str,
) -> str:
    """Gmail API 用の base64url エンコード済み raw メッセージを構築する。"""
    footer = (
        f"\n\n---\n{sender_name}\n{sender_address}\n"
        f"\n※配信停止をご希望の場合はこちら: {unsubscribe_url}\n"
        "※本メールは事業者様向けのご案内としてお送りしております。"
    )
    full_body = body_text.rstrip() + footer

    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender_address}>"
    msg["To"] = to_address
    msg["Reply-To"] = reply_to
    msg["Subject"] = subject
    msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    msg.attach(MIMEText(full_body, "plain", "utf-8"))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    return raw


class GmailSender:
    def __init__(
        self,
        db: Database,
        gmail_service,
        *,
        sender_name: str,
        sender_address: str,
        reply_to: str,
        unsubscribe_url: str,
        dry_run: bool,
        send_interval_sec: int,
        daily_limit: int,
    ):
        self.db = db
        self.service = gmail_service
        self.sender_name = sender_name
        self.sender_address = sender_address
        self.reply_to = reply_to
        self.unsubscribe_url = unsubscribe_url
        self.dry_run = dry_run
        self.send_interval_sec = send_interval_sec
        self.daily_limit = daily_limit
        self.queue = ApprovalQueue(db)

    def send_all_approved(self, *, track: str) -> int:
        sent_today = self._count_sent_today()
        sent_now = 0

        for item in self.queue.list_approved(track=track):
            if sent_today + sent_now >= self.daily_limit:
                raise DailyLimitReached(
                    f"daily limit {self.daily_limit} reached (today={sent_today}, now={sent_now})"
                )

            try:
                self._send_one(item)
                sent_now += 1
                if self.send_interval_sec > 0:
                    time.sleep(self.send_interval_sec)
            except _SendBlocked as e:
                self.queue.mark_failed(item["id"], str(e))
            except Exception as e:
                logger.exception("gmail send failed for item %s", item["id"])
                self.queue.mark_failed(item["id"], f"{type(e).__name__}: {e}")
        return sent_now

    def _send_one(self, item: dict[str, Any]) -> None:
        payload = json.loads(item["payload_json"])
        company_id = payload.get("to_company_id")
        if company_id is None:
            raise _SendBlocked("payload missing to_company_id")

        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT contact_email FROM companies WHERE id = ?", (company_id,)
            ).fetchone()
        if row is None or not row["contact_email"]:
            raise _SendBlocked("company has no contact_email")

        raw = build_raw_email(
            sender_name=self.sender_name,
            sender_address=self.sender_address,
            reply_to=self.reply_to,
            to_address=row["contact_email"],
            subject=payload["subject"],
            body_text=payload["body"],
            unsubscribe_url=self.unsubscribe_url,
        )

        if self.dry_run:
            logger.info("[DRY_RUN] would send item %s to %s", item["id"], row["contact_email"])
            self.queue.mark_sent(item["id"], gmail_message_id="dry_run")
            return

        resp = (
            self.service.users()
            .messages()
            .send(userId="me", body={"raw": raw})
            .execute()
        )
        self.queue.mark_sent(item["id"], gmail_message_id=resp.get("id"))

    def _count_sent_today(self) -> int:
        today = dt.datetime.utcnow().date().isoformat()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM approval_queue "
                "WHERE status = 'sent' AND DATE(sent_at) = ?",
                (today,),
            ).fetchone()
        return row["c"] if row else 0


class _SendBlocked(RuntimeError):
    pass
