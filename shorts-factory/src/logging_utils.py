"""Logging helpers that keep secrets out of local logs and notifications."""
from __future__ import annotations

import re
from typing import Iterable


TELEGRAM_URL_RE = re.compile(r"(https://api\.telegram\.org/bot)([^/\s]+)")
TELEGRAM_BOT_PATH_RE = re.compile(r"(/bot)(\d{6,}:[A-Za-z0-9_-]{20,})")
TELEGRAM_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_-]{20,}\b")


def redact_secrets(value: object, extra_secrets: Iterable[str | None] = ()) -> str:
    """Return a string safe to write to logs or user-facing notifications."""
    text = str(value)
    text = TELEGRAM_URL_RE.sub(r"\1[REDACTED]", text)
    text = TELEGRAM_BOT_PATH_RE.sub(r"\1[REDACTED]", text)
    text = TELEGRAM_TOKEN_RE.sub("[REDACTED]", text)
    for secret in extra_secrets:
        if secret:
            text = text.replace(str(secret), "[REDACTED]")
    return text
