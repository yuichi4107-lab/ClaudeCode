"""Telegram通知（プレビュー送付・承認ボタン・運用アラート）。"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import requests

from .config import CONFIG
from .logging_utils import redact_secrets
from .state_io import atomic_write_json


def _api(method: str) -> str:
    return f"https://api.telegram.org/bot{CONFIG.telegram_token}/{method}"


def _post(method: str, **kwargs) -> requests.Response | None:
    try:
        return requests.post(_api(method), **kwargs)
    except requests.RequestException:
        return None


def _outbox_dir() -> Path:
    p = CONFIG.marketing_dir / "notification_outbox"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_pending_message(payload: dict) -> None:
    path = _outbox_dir() / f"{uuid.uuid4().hex}.json"
    atomic_write_json(path, payload)


def _send_message_payload(payload: dict) -> int | None:
    r = _post("sendMessage", data=payload, timeout=30)
    if r and r.ok:
        return r.json().get("result", {}).get("message_id")
    return None


def enabled() -> bool:
    return bool(
        CONFIG.get("telegram", "enabled", default=True)
        and CONFIG.telegram_token
        and CONFIG.telegram_chat_id
    )


def send_message(text: str, reply_markup: dict | None = None) -> int | None:
    if not enabled():
        return None
    payload: dict = {
        "chat_id": CONFIG.telegram_chat_id,
        "text": redact_secrets(text, [CONFIG.telegram_token])[:4000],
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    mid = _send_message_payload(payload)
    if mid:
        return mid
    # Approval buttons must not be replayed from the outbox after an ambiguous
    # network failure; Telegram may already have accepted the first request.
    if reply_markup:
        return None
    _save_pending_message(payload)
    return None


def send_video(
    video_path: Path, caption: str, reply_markup: dict | None = None
) -> int | None:
    if not enabled():
        return None
    payload: dict = {
        "chat_id": CONFIG.telegram_chat_id,
        "caption": redact_secrets(caption, [CONFIG.telegram_token])[:1000],
        "parse_mode": "HTML",
        "supports_streaming": True,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        with open(video_path, "rb") as f:
            r = requests.post(_api("sendVideo"), data=payload, files={"video": f}, timeout=300)
    except requests.Timeout:
        # The request may have reached Telegram even when the response timed out.
        # Do not send a text fallback immediately; that creates duplicate buttons.
        return None
    except requests.RequestException:
        # Connection errors can occur after Telegram accepted the upload.
        # Avoid a fallback with a second set of approval buttons.
        return None
    except OSError:
        return send_message(caption + "\n（ローカル動画の読み取りに失敗。運用ログを確認してください）", reply_markup)
    if r and r.ok:
        return r.json().get("result", {}).get("message_id")
    # An explicit non-2xx response is a confirmed failure, so text fallback is safe.
    return send_message(caption + "\n（動画の送信に失敗。運用ログを確認してください）", reply_markup)


def approval_keyboard(item_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ 承認して投稿", "callback_data": f"approve:{item_id}"},
                {"text": "❌ 却下", "callback_data": f"reject:{item_id}"},
            ],
            [{"text": "⏸ 保留（また後で）", "callback_data": f"hold:{item_id}"}],
        ]
    }


def quality_blocked_keyboard(item_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ このまま投稿", "callback_data": f"approve:{item_id}"},
                {"text": "🔁 作り直す", "callback_data": f"reject:{item_id}"},
            ],
            [{"text": "⏸ 保留（また後で）", "callback_data": f"hold:{item_id}"}],
        ]
    }


def flush_pending_messages(limit: int = 10) -> int:
    sent = 0
    if not enabled():
        return sent
    for path in sorted(_outbox_dir().glob("*.json"))[:limit]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if _send_message_payload(payload):
            path.unlink(missing_ok=True)
            sent += 1
    return sent


def preview_caption(item: dict) -> str:
    q = item.get("quality", {})
    plats = [p for p, v in item.get("platforms", {}).items() if v.get("enabled")]
    difficulty = item.get("difficulty") or "beginner"
    target_platform = item.get("target_platform") or "common"
    platform_line = (
        f"媒体別動画: {target_platform}\n"
        if target_platform != "common"
        else ""
    )
    return (
        f"🎬 <b>{item['title']}</b>\n"
        f"id: {item['id']}\n"
        f"難易度: {difficulty}\n"
        f"{platform_line}"
        f"尺: {item['video']['duration']}s / {item['video']['size_mb']}MB\n"
        f"字幕検証: {'✅PASS' if q.get('pass') else '⚠️FAIL'} (平均CER {q.get('avg_cer')})\n"
        f"投稿先: {', '.join(plats) or 'なし'}\n\n"
        f"投稿文: SNS別CTA/説明文を適用\n\n"
        f"{item['caption'][:300]}\n"
        f"{' '.join(item['hashtags'][:6])}"
    )
