import json
import logging
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import receiver


class FakeClient:
    def __init__(self, file_path="photos/file_1.jpg", content=b"IMGDATA"):
        self.file_path = file_path
        self.content = content
        self.downloaded = []
        self.messages = []

    def get_file_path(self, file_id):
        return self.file_path

    def download_file(self, file_path, dest_path):
        with open(dest_path, "wb") as f:
            f.write(self.content)
        self.downloaded.append(dest_path)

    def send_message(self, chat_id, text):
        self.messages.append((chat_id, text))


def make_receiver(tmp, client, allowlist=(123,), confirm=True):
    config = {
        "allowed_chat_ids": list(allowlist),
        "send_confirmation": confirm,
        "poll_timeout": 30,
    }
    state = {"offset": None}
    state_path = os.path.join(tmp, "state.json")
    return receiver.Receiver(client, config, tmp, state, state_path)


def photo_update(chat_id=123, update_id=10):
    return {"update_id": update_id, "message": {
        "chat": {"id": chat_id},
        "photo": [{"file_id": "f", "width": 100, "height": 100}]}}


class ProcessUpdate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        logging.disable(logging.CRITICAL)  # keep test output clean

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_saves_authorized_photo(self):
        client = FakeClient()
        make_receiver(self.tmp, client).process_update(photo_update())
        files = os.listdir(self.tmp)
        self.assertEqual(len(client.downloaded), 1)
        self.assertTrue(any(n.endswith(".jpg") for n in files))

    def test_confirmation_reply_sent(self):
        client = FakeClient()
        make_receiver(self.tmp, client, confirm=True).process_update(photo_update())
        self.assertEqual(len(client.messages), 1)
        self.assertEqual(client.messages[0][0], 123)
        self.assertIn("OK saved:", client.messages[0][1])

    def test_no_reply_when_disabled(self):
        client = FakeClient()
        make_receiver(self.tmp, client, confirm=False).process_update(photo_update())
        self.assertEqual(client.messages, [])

    def test_unauthorized_is_ignored(self):
        client = FakeClient()
        make_receiver(self.tmp, client, allowlist=(123,)).process_update(
            photo_update(chat_id=999))
        self.assertEqual(client.downloaded, [])
        self.assertEqual(os.listdir(self.tmp), [])

    def test_setup_mode_empty_allowlist_saves_nothing(self):
        client = FakeClient()
        make_receiver(self.tmp, client, allowlist=()).process_update(
            photo_update(chat_id=555))
        self.assertEqual(client.downloaded, [])

    def test_text_message_ignored(self):
        client = FakeClient()
        make_receiver(self.tmp, client).process_update(
            {"update_id": 11, "message": {"chat": {"id": 123}, "text": "hi"}})
        self.assertEqual(client.downloaded, [])

    def test_reply_network_failure_does_not_undo_save(self):
        import urllib.error
        client = FakeClient()

        def boom(chat_id, text):
            raise urllib.error.URLError("net down")

        client.send_message = boom
        # process_update must not raise even though the reply fails
        make_receiver(self.tmp, client).process_update(photo_update())
        self.assertEqual(len(client.downloaded), 1)


class RunLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        logging.disable(logging.CRITICAL)  # keep test output clean

    def tearDown(self):
        logging.disable(logging.NOTSET)

    def test_offset_advances_and_loop_stops(self):
        # client returns one batch, then raises StopIteration-like to end the loop
        class OneBatchClient(FakeClient):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def get_updates(self, offset, timeout):
                self.calls += 1
                if self.calls == 1:
                    return [photo_update(update_id=41)]
                raise SystemExit(0)  # end the infinite loop for the test

        client = OneBatchClient()
        r = make_receiver(self.tmp, client)
        with self.assertRaises(SystemExit):
            r.run()
        # offset must be update_id + 1, persisted to state file
        self.assertEqual(r._state["offset"], 42)
        with open(os.path.join(self.tmp, "state.json"), "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["offset"], 42)


class MainEntry(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)
        self._orig = receiver.load_config

    def tearDown(self):
        logging.disable(logging.NOTSET)
        receiver.load_config = self._orig

    def test_missing_config_exits_with_friendly_message(self):
        def _raise(*a, **k):
            raise FileNotFoundError("config.json")
        receiver.load_config = _raise
        with self.assertRaises(SystemExit) as ctx:
            receiver.main()
        self.assertIn("config.json not found", str(ctx.exception))

    def test_placeholder_token_exits(self):
        receiver.load_config = lambda *a, **k: {
            "bot_token": "PUT-YOUR-BOT-TOKEN-HERE", "allowed_chat_ids": [1]}
        with self.assertRaises(SystemExit) as ctx:
            receiver.main()
        self.assertIn("bot_token", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
