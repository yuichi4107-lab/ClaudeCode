"""
Telegram bot で処理結果を通知する。
secrets未設定時は警告ログのみ出して継続する（落ちない設計）。
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

import requests

logger = logging.getLogger(__name__)

_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"
_REQUEST_TIMEOUT_SEC = 10
_TELEGRAM_BOT_URL_RE = re.compile(r"((?:api\.telegram\.org/)?bot)\d+:[^/\s]+")


def _redact_sensitive_text(value: object) -> str:
    """ログや通知本文にTelegram Botトークンを残さない。"""
    return _TELEGRAM_BOT_URL_RE.sub(r"\1<redacted>", str(value))


def _send_message(bot_token: str, chat_id: str, text: str) -> None:
    """Telegram Bot APIにメッセージを送信する。失敗時はログに記録して継続する。"""
    url = _TELEGRAM_API_BASE.format(token=bot_token)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, json=payload, timeout=_REQUEST_TIMEOUT_SEC)
        resp.raise_for_status()
        logger.debug("Telegram message sent. chat_id=%s", chat_id)
    except Exception as exc:
        logger.warning("Telegram send failed: %s", _redact_sensitive_text(exc))


def _is_configured(bot_token: str, chat_id: str) -> bool:
    if not bot_token or not chat_id:
        logger.warning(
            "Telegram not configured (bot_token or chat_id is empty). Skipping notification."
        )
        return False
    return True


def send_summary(
    channel_results: List[dict],
    bot_token: str,
    chat_id: str,
) -> None:
    """
    各チャンネルの処理サマリをTelegramへ送信する。
    channel_results の期待形式:
      [{"name": str, "added": int, "skipped": int, "errors": list[str]}, ...]

    通知は「新規追加（完了）またはエラーがあった時のみ」送信する。
    変化なし（追加0・エラー0）の場合はログのみでTelegram送信しない。
    """
    if not _is_configured(bot_token, chat_id):
        return

    # 先に合計を集計し、変化があるかを判定する
    total_added = 0
    total_errors = 0
    for result in channel_results:
        total_added += result.get("added", 0)
        total_errors += len(result.get("errors", []))

    # 新規追加もエラーも無ければ通知しない（定期実行のノイズ抑制）
    if total_added == 0 and total_errors == 0:
        logger.info(
            "No new sources and no errors (added=0, errors=0). Skipping Telegram summary."
        )
        return

    lines = ["<b>[NotebookLM Sync] 処理完了サマリ</b>"]
    for result in channel_results:
        name = result.get("name", "unknown")
        added = result.get("added", 0)
        skipped = result.get("skipped", 0)
        errors = result.get("errors", [])
        lines.append(
            f"  {name}: 追加={added} / スキップ={skipped} / エラー={len(errors)}"
        )

    lines.append(f"\n合計: 追加={total_added} / エラー={total_errors}")
    _send_message(bot_token, chat_id, "\n".join(lines))


def send_alert(
    message: str,
    bot_token: str,
    chat_id: str,
    error: Optional[Exception] = None,
) -> None:
    """
    エラーアラートをTelegramへ送信する。
    secrets未設定時はログのみで継続する。
    """
    if not _is_configured(bot_token, chat_id):
        logger.error("ALERT (Telegram not configured): %s | error=%s", message, error)
        return

    text = f"<b>[NotebookLM Sync] ALERT</b>\n{message}"
    if error:
        text += f"\n<code>{type(error).__name__}: {_redact_sensitive_text(error)}</code>"
    _send_message(bot_token, chat_id, text)
