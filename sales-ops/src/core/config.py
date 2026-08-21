"""Sales OS 環境設定ローダー。DRY_RUN はデフォルトTrueで安全側。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


class MissingEnvError(RuntimeError):
    pass


REQUIRED = [
    "ANTHROPIC_API_KEY",
    "GOOGLE_MAPS_API_KEY",
    "GMAIL_SENDER_ADDRESS",
    "GMAIL_SENDER_NAME",
    "OWNER_NAME",
    "OWNER_COMPANY",
    "OWNER_WEBSITE",
]


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    google_maps_api_key: str
    gmail_oauth_client_secret_json: str
    gmail_oauth_token_json: str
    gmail_sender_address: str
    gmail_sender_name: str
    gmail_reply_to: str
    gmail_unsubscribe_url: str
    db_path: str
    dry_run: bool
    daily_send_limit: int
    send_interval_sec: int
    owner_name: str
    owner_company: str
    owner_website: str
    owner_book_link: str
    owner_title: str
    owner_contact_email: str

    @classmethod
    def load(cls) -> "Config":
        missing = [k for k in REQUIRED if not os.getenv(k)]
        if missing:
            raise MissingEnvError(f"Missing env vars: {', '.join(missing)}")

        return cls(
            anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
            google_maps_api_key=os.environ["GOOGLE_MAPS_API_KEY"],
            gmail_oauth_client_secret_json=os.getenv(
                "GMAIL_OAUTH_CLIENT_SECRET_JSON", "./secrets/gmail_client_secret.json"
            ),
            gmail_oauth_token_json=os.getenv(
                "GMAIL_OAUTH_TOKEN_JSON", "./secrets/gmail_token.json"
            ),
            gmail_sender_address=os.environ["GMAIL_SENDER_ADDRESS"],
            gmail_sender_name=os.environ["GMAIL_SENDER_NAME"],
            gmail_reply_to=os.getenv("GMAIL_REPLY_TO", os.environ["GMAIL_SENDER_ADDRESS"]),
            gmail_unsubscribe_url=os.getenv(
                "GMAIL_UNSUBSCRIBE_URL", "https://ynfactory.online/unsubscribe"
            ),
            db_path=os.getenv("SALES_OPS_DB_PATH", "./data/sales_ops.db"),
            dry_run=os.getenv("SALES_OPS_DRY_RUN", "true").lower() == "true",
            daily_send_limit=int(os.getenv("SALES_OPS_DAILY_SEND_LIMIT", "100")),
            send_interval_sec=int(os.getenv("SALES_OPS_SEND_INTERVAL_SEC", "60")),
            owner_name=os.environ["OWNER_NAME"],
            owner_company=os.environ["OWNER_COMPANY"],
            owner_website=os.environ["OWNER_WEBSITE"],
            owner_book_link=os.getenv("OWNER_BOOK_LINK", ""),
            owner_title=os.getenv("OWNER_TITLE", "代表"),
            owner_contact_email=os.getenv(
                "OWNER_CONTACT_EMAIL",
                os.getenv("GMAIL_REPLY_TO", os.environ.get("GMAIL_SENDER_ADDRESS", "")),
            ),
        )
