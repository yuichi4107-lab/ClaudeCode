"""Telegram通知 共通モジュール"""

import logging
import requests

logger = logging.getLogger(__name__)


def send_telegram(text: str, token: str, chat_id: str, parse_mode: str = "Markdown") -> bool:
    """Telegramにメッセージを送信する"""
    if not token or not chat_id:
        logger.warning("Telegram設定が未設定です")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    max_len = 4096
    chunks = [text[i:i + max_len] for i in range(0, len(text), max_len)]

    for chunk in chunks:
        payload = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": parse_mode,
        }
        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code != 200:
                logger.error("Telegram送信失敗: %s %s", resp.status_code, resp.text)
                return False
        except requests.RequestException as e:
            logger.error("Telegram送信エラー: %s", e)
            return False

    logger.info("Telegram配信完了")
    return True
