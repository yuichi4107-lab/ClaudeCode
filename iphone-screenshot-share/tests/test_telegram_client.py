import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import telegram_client


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


class FakeOpener:
    """Stand-in for urllib opener. Returns canned payload or raises an error."""

    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error
        self.requests = []

    def open(self, req, timeout=None):
        self.requests.append(req)
        if self._error is not None:
            raise self._error
        return FakeResp(json.dumps(self._payload).encode("utf-8"))


class GetUpdates(unittest.TestCase):
    def test_returns_result_array(self):
        opener = FakeOpener(payload={"ok": True, "result": [{"update_id": 1}]})
        c = telegram_client.TelegramClient("TOKEN", opener=opener)
        self.assertEqual(c.get_updates(None, 30), [{"update_id": 1}])

    def test_409_raises_conflict(self):
        err = urllib.error.HTTPError("u", 409, "conflict", {},
                                     io.BytesIO(b"conflict"))
        c = telegram_client.TelegramClient("TOKEN", opener=FakeOpener(error=err))
        with self.assertRaises(telegram_client.ConflictError):
            c.get_updates(None, 30)

    def test_api_not_ok_raises(self):
        opener = FakeOpener(payload={"ok": False, "description": "bad token"})
        c = telegram_client.TelegramClient("TOKEN", opener=opener)
        with self.assertRaises(telegram_client.TelegramError):
            c.get_updates(None, 30)


class GetFilePath(unittest.TestCase):
    def test_returns_file_path(self):
        opener = FakeOpener(payload={"ok": True, "result": {"file_path": "photos/f.jpg"}})
        c = telegram_client.TelegramClient("TOKEN", opener=opener)
        self.assertEqual(c.get_file_path("FID"), "photos/f.jpg")


class _BoomOpener:
    def open(self, req, timeout=None):
        raise urllib.error.URLError("network down")


class DownloadFile(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.dest = os.path.join(self.dir, "img.jpg")

    def test_success_writes_dest_and_leaves_no_part(self):
        opener = FakeOpener(payload={"ok": True, "result": []})  # any bytes
        c = telegram_client.TelegramClient("TOKEN", opener=opener)
        c.download_file("photos/f.jpg", self.dest)
        self.assertTrue(os.path.exists(self.dest))
        self.assertFalse(os.path.exists(self.dest + ".part"))

    def test_failure_leaves_no_dest_and_no_part(self):
        c = telegram_client.TelegramClient("TOKEN", opener=_BoomOpener())
        with self.assertRaises(urllib.error.URLError):
            c.download_file("photos/f.jpg", self.dest)
        self.assertFalse(os.path.exists(self.dest))
        self.assertFalse(os.path.exists(self.dest + ".part"))


if __name__ == "__main__":
    unittest.main()
