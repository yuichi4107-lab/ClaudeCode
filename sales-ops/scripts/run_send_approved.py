"""承認済みの approval_queue を送信する（朝セッション承認後に起動）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from core.config import Config
from core.db import Database
from core.senders.gmail_sender import GmailSender

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def main() -> int:
    load_dotenv()
    cfg = Config.load()
    creds = Credentials.from_authorized_user_file(cfg.gmail_oauth_token_json, SCOPES)
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)

    db = Database(cfg.db_path)
    sender = GmailSender(
        db=db,
        gmail_service=service,
        sender_name=cfg.gmail_sender_name,
        sender_address=cfg.gmail_sender_address,
        reply_to=cfg.gmail_reply_to,
        unsubscribe_url=cfg.gmail_unsubscribe_url,
        dry_run=cfg.dry_run,
        send_interval_sec=cfg.send_interval_sec,
        daily_limit=cfg.daily_send_limit,
    )
    sent = sender.send_all_approved(track="c")
    print(f"[OK] sent {sent} emails (dry_run={cfg.dry_run})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
