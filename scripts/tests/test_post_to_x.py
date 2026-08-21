from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from scripts import post_to_x


class WeightedLengthTests(unittest.TestCase):
    def test_japanese_is_weight_two_and_latin_is_weight_one(self) -> None:
        self.assertEqual(post_to_x.weighted_length("abcあいう"), 9)

    def test_urls_have_fixed_weight_23(self) -> None:
        short_url = "見て https://x.co/a"
        long_url = "見て https://example.com/a/very/long/path?campaign=123"
        self.assertEqual(post_to_x.weighted_length(short_url), 28)
        self.assertEqual(post_to_x.weighted_length(long_url), 28)

    def test_trailing_japanese_punctuation_is_not_part_of_url(self) -> None:
        self.assertEqual(post_to_x.weighted_length("https://example.com。"), 25)


class DryRunTests(unittest.TestCase):
    def test_dry_run_does_not_read_credentials_or_create_clients(self) -> None:
        with (
            patch.object(
                post_to_x,
                "load_credentials",
                side_effect=AssertionError("credentials must stay unread"),
            ) as load_credentials,
            patch.object(
                post_to_x,
                "_read_env_file",
                side_effect=AssertionError("env file must stay unread"),
            ) as read_env_file,
            patch.object(
                post_to_x.os.environ,
                "get",
                side_effect=AssertionError("process env must stay unread"),
            ) as environ_get,
            patch.object(post_to_x, "get_client") as get_client,
            patch.object(post_to_x, "get_api_v1") as get_api_v1,
        ):
            result = post_to_x.dry_run("テスト https://example.com")

        self.assertEqual(result["status"], "ready_for_review")
        self.assertFalse(result["tokens_read"])
        self.assertFalse(result["api_called"])
        load_credentials.assert_not_called()
        read_env_file.assert_not_called()
        environ_get.assert_not_called()
        get_client.assert_not_called()
        get_api_v1.assert_not_called()

    def test_dry_run_blocks_note_url_and_other_placeholders(self) -> None:
        result = post_to_x.dry_run("詳細は [NOTE_URL] / {CAMPAIGN_NAME}")
        blockers = "\n".join(result["blockers"])

        self.assertEqual(result["status"], "blocked")
        self.assertIn("[NOTE_URL]", blockers)
        self.assertIn("{CAMPAIGN_NAME}", blockers)

    def test_dry_run_uses_weighted_limit(self) -> None:
        result = post_to_x.dry_run("あ" * 141)

        self.assertEqual(result["weighted_length"], 282)
        self.assertEqual(result["status"], "blocked")


class CredentialPathTests(unittest.TestCase):
    def test_default_credential_path_is_local_control_plane(self) -> None:
        self.assertEqual(
            post_to_x.DEFAULT_ENV_PATH,
            Path.home() / ".ynfactory" / "credentials" / "sns-x.env",
        )

    def test_credentials_file_env_overrides_default_path(self) -> None:
        override = Path("/tmp/ynfactory-test/sns-x.env")
        file_values = {
            "X_API_KEY": "test-api-key",
            "X_API_KEY_SECRET": "test-api-key-secret",
            "X_ACCESS_TOKEN": "test-access-token",
            "X_ACCESS_TOKEN_SECRET": "test-access-token-secret",
        }
        with (
            patch.dict(
                post_to_x.os.environ,
                {post_to_x.CREDENTIALS_FILE_ENV: str(override)},
                clear=True,
            ),
            patch.object(
                post_to_x, "_read_env_file", return_value=file_values
            ) as read_env_file,
        ):
            credentials = post_to_x.load_credentials()

        read_env_file.assert_called_once_with(override)
        self.assertEqual(credentials, file_values)


class AdapterTests(unittest.TestCase):
    def test_post_one_passes_reply_id(self) -> None:
        client = MagicMock()
        client.create_tweet.return_value = SimpleNamespace(
            data={"id": "200", "text": "返信です"}
        )

        with patch.object(post_to_x, "get_client", return_value=client):
            result = post_to_x.post_one("返信です", in_reply_to_tweet_id="100")

        client.create_tweet.assert_called_once_with(
            text="返信です", in_reply_to_tweet_id="100"
        )
        self.assertEqual(result["id"], "200")
        self.assertEqual(result["reply_to_tweet_id"], "100")

    def test_get_identity_uses_user_auth(self) -> None:
        client = MagicMock()
        client.get_me.return_value = SimpleNamespace(
            data={"id": "10", "username": "ynfactory", "name": "YN Factory"}
        )

        with patch.object(post_to_x, "get_client", return_value=client):
            identity = post_to_x.get_identity()

        client.get_me.assert_called_once_with(user_auth=True)
        self.assertEqual(identity["username"], "ynfactory")

    def test_readback_includes_created_at_and_reply_relationship(self) -> None:
        client = MagicMock()
        created_at = datetime(2026, 7, 19, 9, 0, tzinfo=timezone.utc)
        client.get_tweet.return_value = SimpleNamespace(
            data={
                "id": "200",
                "text": "返信です",
                "author_id": "10",
                "conversation_id": "100",
                "created_at": created_at,
                "referenced_tweets": [{"type": "replied_to", "id": "100"}],
            }
        )

        with patch.object(post_to_x, "get_client", return_value=client):
            result = post_to_x.readback_tweet("200")

        client.get_tweet.assert_called_once_with(
            id="200",
            user_auth=True,
            tweet_fields=list(post_to_x.READBACK_FIELDS),
        )
        self.assertEqual(result["created_at"], created_at.isoformat())
        self.assertEqual(result["expanded_text"], "返信です")
        self.assertTrue(result["is_reply"])
        self.assertEqual(result["reply_to_tweet_id"], "100")

    def test_readback_expands_tco_urls_from_entities(self) -> None:
        client = MagicMock()
        client.get_tweet.return_value = SimpleNamespace(
            data={
                "id": "201",
                "text": "公開しました https://t.co/abc123",
                "entities": {
                    "urls": [
                        {
                            "url": "https://t.co/abc123",
                            "expanded_url": "https://example.com/article?id=42",
                        }
                    ]
                },
            }
        )

        with patch.object(post_to_x, "get_client", return_value=client):
            result = post_to_x.readback_tweet("201")

        requested_fields = client.get_tweet.call_args.kwargs["tweet_fields"]
        self.assertIn("entities", requested_fields)
        self.assertEqual(result["text"], "公開しました https://t.co/abc123")
        self.assertEqual(
            result["expanded_text"],
            "公開しました https://example.com/article?id=42",
        )

    def test_readback_without_urls_keeps_the_same_expanded_text(self) -> None:
        client = MagicMock()
        client.get_tweet.return_value = SimpleNamespace(
            data={
                "id": "202",
                "text": "URLなしの本文です",
                "entities": {"urls": []},
            }
        )

        with patch.object(post_to_x, "get_client", return_value=client):
            result = post_to_x.readback_tweet("202")

        self.assertEqual(result["expanded_text"], result["text"])

    def test_ambiguous_create_error_is_not_retried(self) -> None:
        client = MagicMock()
        client.create_tweet.side_effect = TimeoutError("response lost")

        with (
            patch.object(post_to_x, "get_client", return_value=client),
            self.assertRaises(TimeoutError),
        ):
            post_to_x.post_one("一度だけ送る")

        self.assertEqual(client.create_tweet.call_count, 1)


class CliTests(unittest.TestCase):
    def test_live_cli_requires_publish_approved_before_any_live_helper(self) -> None:
        stdout = io.StringIO()
        with (
            patch.object(post_to_x, "post_one") as post_one,
            patch.object(post_to_x, "load_credentials") as load_credentials,
            redirect_stdout(stdout),
            redirect_stderr(io.StringIO()),
        ):
            exit_code = post_to_x.main(["投稿候補", "--json"])

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse(result["tokens_read"])
        post_one.assert_not_called()
        load_credentials.assert_not_called()

    def test_live_cli_forwards_reply_and_emits_json(self) -> None:
        stdout = io.StringIO()
        created = {
            "platform": "x",
            "status": "posted",
            "id": "200",
            "url": "https://x.com/i/status/200",
            "text": "返信です",
            "reply_to_tweet_id": "100",
        }
        with (
            patch.object(post_to_x, "post_one", return_value=created) as post_one,
            redirect_stdout(stdout),
        ):
            exit_code = post_to_x.main(
                [
                    "返信です",
                    "--reply-to",
                    "100",
                    "--publish-approved",
                    "--json",
                ]
            )

        result = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        post_one.assert_called_once_with("返信です", in_reply_to_tweet_id="100")
        self.assertEqual(result["id"], "200")
        self.assertFalse(result["automatic_retry_attempted"])


if __name__ == "__main__":
    unittest.main()
