import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import notify


class TestNotify(unittest.TestCase):
    def test_send_summary_skips_when_no_changes(self):
        with patch("notify._send_message") as send_message:
            notify.send_summary([], "123456:SECRET", "chat1")
            notify.send_summary(
                [{"name": "AI仙人", "added": 0, "skipped": 15, "errors": []}],
                "123456:SECRET",
                "chat1",
            )

        send_message.assert_not_called()

    def test_send_summary_sends_when_added_or_errors_exist(self):
        with patch("notify._send_message") as send_message:
            notify.send_summary(
                [
                    {"name": "AI仙人", "added": 1, "skipped": 14, "errors": []},
                    {"name": "株式会社AX", "added": 0, "skipped": 9, "errors": ["fetch_failed"]},
                ],
                "123456:SECRET",
                "chat1",
            )

        send_message.assert_called_once()
        args = send_message.call_args.args
        self.assertIn("合計: 追加=1 / エラー=1", args[2])

    def test_send_message_redacts_telegram_token_from_error_log(self):
        secret = "123456:SECRET_TOKEN"
        exc = requests.exceptions.ConnectionError(
            f"Max retries exceeded with url: /bot{secret}/sendMessage"
        )

        with patch("notify.requests.post", side_effect=exc), self.assertLogs(
            "notify", level=logging.WARNING
        ) as captured:
            notify._send_message(secret, "chat1", "hello")

        log_text = "\n".join(captured.output)
        self.assertNotIn(secret, log_text)
        self.assertIn("bot<redacted>", log_text)

    def test_send_alert_redacts_error_text_before_sending(self):
        secret = "123456:SECRET_TOKEN"
        error = RuntimeError(f"https://api.telegram.org/bot{secret}/sendMessage failed")

        with patch("notify._send_message") as send_message:
            notify.send_alert("failure", secret, "chat1", error=error)

        text = send_message.call_args.args[2]
        self.assertNotIn(secret, text)
        self.assertIn("bot<redacted>", text)


if __name__ == "__main__":
    unittest.main()
