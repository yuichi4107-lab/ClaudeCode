# iPhoneスクショ共有ツール 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** iPhoneのスクショを共有シート→Telegram専用ボット経由で、Windows PCの保存先フォルダへ自動保存する常駐ツールを作る。

**Architecture:** Windows常駐のPythonスクリプトがTelegram Bot APIを長ポーリング(getUpdates)し、許可したchat_idから届いた画像(photo/document)をgetFile→ダウンロードして`%USERPROFILE%\Pictures\iPhoneScreenshots\`に保存する。純ロジック(core)・通信(telegram_client)・統合ループ(receiver)を責務分割し、純ロジックと通信モックで単体テストする。

**Tech Stack:** Python 3.8+（標準ライブラリのみ：`urllib`/`json`/`unittest`、pip不要）、Telegram Bot API。

設計書: `docs/superpowers/specs/2026-06-02-iphone-screenshot-share-design.md`

---

## ファイル構成

| ファイル | 責務 |
|---|---|
| `iphone-screenshot-share/core.py` | 純関数：`is_allowed` / `extract_image` / `build_filename` / `expand_save_dir` / `default_save_dir` |
| `iphone-screenshot-share/telegram_client.py` | Telegram Bot API通信：`TelegramClient`（getUpdates/getFile/download/sendMessage）、`ConflictError`/`TelegramError` |
| `iphone-screenshot-share/receiver.py` | 統合：`Receiver`（process_update / run）+ 設定/状態IO + `main()` |
| `iphone-screenshot-share/config.example.json` | 設定雛形（追跡する） |
| `iphone-screenshot-share/config.json` | 実設定（**.gitignore**） |
| `iphone-screenshot-share/state.json` | 受信offset永続化（**.gitignore**） |
| `iphone-screenshot-share/start.bat` | 起動ランチャー（**ASCIIのみ**） |
| `iphone-screenshot-share/README.md` | セットアップ手順（日本語） |
| `iphone-screenshot-share/.gitignore` | config.json / state.json / __pycache__ 除外 |
| `iphone-screenshot-share/tests/__init__.py` | テストパッケージ化（空） |
| `iphone-screenshot-share/tests/test_core.py` | coreの単体テスト |
| `iphone-screenshot-share/tests/test_telegram_client.py` | 通信のテスト（fake opener） |
| `iphone-screenshot-share/tests/test_receiver.py` | Receiverのテスト（fake client + tempdir） |

**テスト実行コマンド（共通）**: フォルダに入って実行する。
```
cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_core -v
```
（全体は `python -m unittest discover -s tests -p "test_*.py" -v`）

---

### Task 1: スキャフォールド（フォルダ・設定雛形・.gitignore）

**Files:**
- Create: `iphone-screenshot-share/.gitignore`
- Create: `iphone-screenshot-share/config.example.json`
- Create: `iphone-screenshot-share/tests/__init__.py`

- [ ] **Step 1: Python確認**

Run: `python --version`
Expected: `Python 3.8` 以上。3.x が出ればOK（無ければREADMEのPython導入を案内）。

- [ ] **Step 2: `.gitignore` 作成**

`iphone-screenshot-share/.gitignore`:
```gitignore
config.json
state.json
__pycache__/
*.pyc
```

- [ ] **Step 3: `config.example.json` 作成**

`iphone-screenshot-share/config.example.json`:
```json
{
  "bot_token": "PUT-YOUR-BOT-TOKEN-HERE",
  "allowed_chat_ids": [],
  "save_dir": "%USERPROFILE%\\Pictures\\iPhoneScreenshots",
  "send_confirmation": true,
  "poll_timeout": 30
}
```

- [ ] **Step 4: `tests/__init__.py` 作成（空ファイル）**

`iphone-screenshot-share/tests/__init__.py`:
```python
```

- [ ] **Step 5: Commit**

```bash
cd "g:/マイドライブ/YNFactory-cc"
git add iphone-screenshot-share/.gitignore iphone-screenshot-share/config.example.json iphone-screenshot-share/tests/__init__.py
git commit -m "feat(iphone-share): scaffold folder, config example, gitignore"
```

---

### Task 2: core.is_allowed（許可リスト判定）

**Files:**
- Create: `iphone-screenshot-share/core.py`
- Test: `iphone-screenshot-share/tests/test_core.py`

- [ ] **Step 1: Write the failing test**

`iphone-screenshot-share/tests/test_core.py`:
```python
import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import core


class IsAllowed(unittest.TestCase):
    def test_in_list(self):
        self.assertTrue(core.is_allowed(5, [1, 5, 9]))

    def test_not_in_list(self):
        self.assertFalse(core.is_allowed(7, [1, 5, 9]))

    def test_empty_list_rejects(self):
        # empty allowlist == setup mode: accept nothing
        self.assertFalse(core.is_allowed(5, []))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_core -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'core'` または `AttributeError: ... is_allowed`）

- [ ] **Step 3: Write minimal implementation**

`iphone-screenshot-share/core.py`:
```python
from __future__ import annotations

import os
from datetime import datetime


def is_allowed(chat_id, allowlist):
    """True only if allowlist is non-empty AND chat_id is in it.

    An empty allowlist means 'setup mode': nothing is accepted yet.
    """
    return bool(allowlist) and chat_id in allowlist
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_core -v`
Expected: PASS（3 tests OK）

- [ ] **Step 5: Commit**

```bash
cd "g:/マイドライブ/YNFactory-cc"
git add iphone-screenshot-share/core.py iphone-screenshot-share/tests/test_core.py
git commit -m "feat(iphone-share): is_allowed allowlist check (TDD)"
```

---

### Task 3: core.extract_image（photo/documentから画像を抽出）

**Files:**
- Modify: `iphone-screenshot-share/core.py`
- Test: `iphone-screenshot-share/tests/test_core.py`

- [ ] **Step 1: Write the failing test（test_core.py に追記）**

`iphone-screenshot-share/tests/test_core.py` の `IsAllowed` クラスの下に追記:
```python
class ExtractImage(unittest.TestCase):
    def test_photo_picks_largest(self):
        msg = {"photo": [
            {"file_id": "small", "width": 90, "height": 90},
            {"file_id": "big", "width": 1280, "height": 960},
        ]}
        self.assertEqual(core.extract_image(msg), ("big", ".jpg"))

    def test_document_png_uses_filename_ext(self):
        msg = {"document": {"file_id": "d1", "mime_type": "image/png",
                            "file_name": "IMG.PNG"}}
        self.assertEqual(core.extract_image(msg), ("d1", ".png"))

    def test_document_uses_mime_when_no_name(self):
        msg = {"document": {"file_id": "d2", "mime_type": "image/jpeg"}}
        self.assertEqual(core.extract_image(msg), ("d2", ".jpg"))

    def test_non_image_document_is_none(self):
        msg = {"document": {"file_id": "d3", "mime_type": "application/pdf",
                            "file_name": "a.pdf"}}
        self.assertIsNone(core.extract_image(msg))

    def test_text_message_is_none(self):
        self.assertIsNone(core.extract_image({"text": "hi"}))

    def test_non_dict_is_none(self):
        self.assertIsNone(core.extract_image(None))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_core -v`
Expected: FAIL（`AttributeError: module 'core' has no attribute 'extract_image'`）

- [ ] **Step 3: Write minimal implementation（core.py に追記）**

`iphone-screenshot-share/core.py` の末尾に追記:
```python
MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "image/heif": ".heif",
}


def _ext_from_document(doc):
    name = doc.get("file_name") or ""
    _, ext = os.path.splitext(name)
    if ext:
        return ext.lower()
    mime = (doc.get("mime_type") or "").lower()
    return MIME_EXT.get(mime, ".bin")


def extract_image(message):
    """Return (file_id, ext) for the best image in a message, or None.

    - 'photo': list of PhotoSize; pick the largest by width*height (ext '.jpg').
    - 'document' with image/* mime: use it (ext from file_name or mime).
    Anything else returns None.
    """
    if not isinstance(message, dict):
        return None
    photos = message.get("photo")
    if photos:
        best = max(photos, key=lambda p: p.get("width", 0) * p.get("height", 0))
        return (best["file_id"], ".jpg")
    doc = message.get("document")
    if doc:
        mime = (doc.get("mime_type") or "").lower()
        if mime.startswith("image/"):
            return (doc["file_id"], _ext_from_document(doc))
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_core -v`
Expected: PASS（全テストOK）

- [ ] **Step 5: Commit**

```bash
cd "g:/マイドライブ/YNFactory-cc"
git add iphone-screenshot-share/core.py iphone-screenshot-share/tests/test_core.py
git commit -m "feat(iphone-share): extract_image for photo/document (TDD)"
```

---

### Task 4: core.build_filename（タイムスタンプ名・衝突回避）

**Files:**
- Modify: `iphone-screenshot-share/core.py`
- Test: `iphone-screenshot-share/tests/test_core.py`

- [ ] **Step 1: Write the failing test（test_core.py に追記）**

```python
class BuildFilename(unittest.TestCase):
    def setUp(self):
        self.dt = datetime(2026, 6, 2, 14, 5, 9)

    def test_basic(self):
        self.assertEqual(core.build_filename(self.dt, ".png", set()),
                         "20260602_140509.png")

    def test_adds_leading_dot(self):
        self.assertEqual(core.build_filename(self.dt, "jpg", set()),
                         "20260602_140509.jpg")

    def test_collision_adds_counter(self):
        existing = {"20260602_140509.png"}
        self.assertEqual(core.build_filename(self.dt, ".png", existing),
                         "20260602_140509_01.png")

    def test_double_collision(self):
        existing = {"20260602_140509.png", "20260602_140509_01.png"}
        self.assertEqual(core.build_filename(self.dt, ".png", existing),
                         "20260602_140509_02.png")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_core -v`
Expected: FAIL（`AttributeError: ... build_filename`）

- [ ] **Step 3: Write minimal implementation（core.py に追記）**

```python
def build_filename(dt, ext, existing):
    """Build 'YYYYMMDD_HHMMSS<ext>', adding _NN to avoid names in 'existing'."""
    if not ext.startswith("."):
        ext = "." + ext
    base = dt.strftime("%Y%m%d_%H%M%S")
    candidate = base + ext
    if candidate not in existing:
        return candidate
    n = 1
    while True:
        candidate = "%s_%02d%s" % (base, n, ext)
        if candidate not in existing:
            return candidate
        n += 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_core -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "g:/マイドライブ/YNFactory-cc"
git add iphone-screenshot-share/core.py iphone-screenshot-share/tests/test_core.py
git commit -m "feat(iphone-share): build_filename with collision suffix (TDD)"
```

---

### Task 5: core.expand_save_dir / default_save_dir（保存先解決）

**Files:**
- Modify: `iphone-screenshot-share/core.py`
- Test: `iphone-screenshot-share/tests/test_core.py`

- [ ] **Step 1: Write the failing test（test_core.py に追記）**

```python
class ExpandSaveDir(unittest.TestCase):
    def test_default_when_empty(self):
        result = core.expand_save_dir("")
        self.assertTrue(result.endswith(os.path.join("Pictures", "iPhoneScreenshots")))

    def test_default_when_none(self):
        result = core.expand_save_dir(None)
        self.assertTrue(result.endswith(os.path.join("Pictures", "iPhoneScreenshots")))

    def test_expands_env_var(self):
        os.environ["ISS_TEST_VAR"] = "ZZZ_BASE"
        result = core.expand_save_dir(os.path.join("%ISS_TEST_VAR%", "sub"))
        self.assertIn("ZZZ_BASE", result)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_core -v`
Expected: FAIL（`AttributeError: ... expand_save_dir`）

- [ ] **Step 3: Write minimal implementation（core.py に追記）**

```python
def default_save_dir():
    return os.path.join(
        os.environ.get("USERPROFILE", os.path.expanduser("~")),
        "Pictures",
        "iPhoneScreenshots",
    )


def expand_save_dir(raw):
    """Expand %VARS% and ~ in a configured path; fall back to default."""
    if not raw:
        return default_save_dir()
    return os.path.expanduser(os.path.expandvars(raw))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_core -v`
Expected: PASS（core全クラスがOK）

- [ ] **Step 5: Commit**

```bash
cd "g:/マイドライブ/YNFactory-cc"
git add iphone-screenshot-share/core.py iphone-screenshot-share/tests/test_core.py
git commit -m "feat(iphone-share): expand_save_dir / default_save_dir (TDD)"
```

---

### Task 6: telegram_client.py（Bot API通信・409検出）

**Files:**
- Create: `iphone-screenshot-share/telegram_client.py`
- Test: `iphone-screenshot-share/tests/test_telegram_client.py`

- [ ] **Step 1: Write the failing test**

`iphone-screenshot-share/tests/test_telegram_client.py`:
```python
import io
import json
import os
import sys
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_telegram_client -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'telegram_client'`）

- [ ] **Step 3: Write minimal implementation**

`iphone-screenshot-share/telegram_client.py`:
```python
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class ConflictError(Exception):
    """HTTP 409: another process is polling the same bot token."""


class TelegramError(Exception):
    """Telegram API returned ok=false or a non-409 HTTP error."""


class TelegramClient:
    def __init__(self, token, base_url="https://api.telegram.org", opener=None):
        self._token = token
        self._base = base_url.rstrip("/")
        self._opener = opener or urllib.request.build_opener()

    def _api_url(self, method):
        return "%s/bot%s/%s" % (self._base, self._token, method)

    def _request(self, method, params=None, timeout=35):
        data = None
        if params is not None:
            data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(self._api_url(method), data=data)
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 409:
                raise ConflictError(e.read().decode("utf-8", "replace"))
            raise TelegramError("HTTP %s on %s" % (e.code, method))
        if not payload.get("ok"):
            raise TelegramError(payload.get("description", "unknown error"))
        return payload["result"]

    def get_updates(self, offset, timeout):
        params = {"timeout": timeout, "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            params["offset"] = offset
        # network timeout must exceed the long-poll timeout
        return self._request("getUpdates", params, timeout=timeout + 10)

    def get_file_path(self, file_id):
        result = self._request("getFile", {"file_id": file_id})
        return result["file_path"]

    def download_file(self, file_path, dest_path):
        url = "%s/file/bot%s/%s" % (self._base, self._token, file_path)
        req = urllib.request.Request(url)
        with self._opener.open(req, timeout=60) as resp, open(dest_path, "wb") as f:
            f.write(resp.read())

    def send_message(self, chat_id, text):
        self._request("sendMessage", {"chat_id": chat_id, "text": text})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_telegram_client -v`
Expected: PASS（4 tests OK）

- [ ] **Step 5: Commit**

```bash
cd "g:/マイドライブ/YNFactory-cc"
git add iphone-screenshot-share/telegram_client.py iphone-screenshot-share/tests/test_telegram_client.py
git commit -m "feat(iphone-share): TelegramClient with 409 conflict detection (TDD)"
```

---

### Task 7: receiver.Receiver.process_update（1メッセージ処理）

**Files:**
- Create: `iphone-screenshot-share/receiver.py`
- Test: `iphone-screenshot-share/tests/test_receiver.py`

- [ ] **Step 1: Write the failing test**

`iphone-screenshot-share/tests/test_receiver.py`:
```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_receiver -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'receiver'`）

- [ ] **Step 3: Write minimal implementation**

`iphone-screenshot-share/receiver.py`:
```python
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime

import core
from telegram_client import ConflictError, TelegramClient, TelegramError

log = logging.getLogger("iphone-screenshot-share")

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(_HERE, "config.json")
STATE_PATH = os.path.join(_HERE, "state.json")


def load_config(path=CONFIG_PATH):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_state(path=STATE_PATH):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {"offset": None}


def save_state(state, path=STATE_PATH):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, path)


class Receiver:
    def __init__(self, client, config, save_dir, state, state_path=STATE_PATH):
        self._client = client
        self._allowlist = config.get("allowed_chat_ids") or []
        self._send_confirmation = config.get("send_confirmation", True)
        self._poll_timeout = config.get("poll_timeout", 30)
        self._save_dir = save_dir
        self._state = state
        self._state_path = state_path
        os.makedirs(self._save_dir, exist_ok=True)

    def process_update(self, update):
        message = update.get("message")
        if not message:
            return
        chat_id = (message.get("chat") or {}).get("id")
        if not self._allowlist:
            log.warning("SETUP MODE: received from chat_id=%s. Add this id to "
                        "allowed_chat_ids in config.json and restart.", chat_id)
            return
        if not core.is_allowed(chat_id, self._allowlist):
            log.info("ignoring message from unauthorized chat_id=%s", chat_id)
            return
        found = core.extract_image(message)
        if not found:
            return
        file_id, ext = found
        file_path = self._client.get_file_path(file_id)
        existing = set(os.listdir(self._save_dir))
        name = core.build_filename(datetime.now(), ext, existing)
        dest = os.path.join(self._save_dir, name)
        self._client.download_file(file_path, dest)
        log.info("saved %s", dest)
        if self._send_confirmation:
            try:
                self._client.send_message(chat_id, "OK saved: %s" % name)
            except TelegramError as e:
                log.warning("confirmation reply failed: %s", e)

    def run(self):
        backoff = 1
        conflict_tries = 0
        log.info("polling started (save_dir=%s)", self._save_dir)
        while True:
            try:
                updates = self._client.get_updates(
                    self._state.get("offset"), self._poll_timeout)
                backoff = 1
                conflict_tries = 0
                for update in updates:
                    try:
                        self.process_update(update)
                    except Exception as e:  # one bad update must not stop the loop
                        log.exception("failed to process update %s: %s",
                                      update.get("update_id"), e)
                    self._state["offset"] = update["update_id"] + 1
                    save_state(self._state, self._state_path)
            except ConflictError:
                conflict_tries += 1
                if conflict_tries >= 3:
                    log.error("409 Conflict: another process is polling this bot "
                              "token. Use a DEDICATED bot, separate from the Claude "
                              "bot. Exiting.")
                    raise SystemExit(2)
                time.sleep(3)
            except SystemExit:
                raise
            except Exception as e:
                log.warning("polling error: %s (retry in %ss)", e, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    config = load_config()
    token = config.get("bot_token")
    if not token or token.startswith("PUT-"):
        raise SystemExit("config.json: set your bot_token first (see README.md).")
    save_dir = core.expand_save_dir(config.get("save_dir"))
    state = load_state()
    client = TelegramClient(token)
    if not (config.get("allowed_chat_ids") or []):
        log.warning("allowed_chat_ids is EMPTY (setup mode). Send any message to "
                    "the bot from your iPhone; its chat_id will be printed here.")
    Receiver(client, config, save_dir, state).run()


if __name__ == "__main__":
    main()
```

> 注: 確認返信は `start.bat`（cmd窓・CP932）でも文字化けしないよう英語 `OK saved: <name>` にする。Telegram側の表示はUTF-8だが、ログ・端末安全のため英語に統一。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_receiver -v`
Expected: PASS（6 tests OK）

- [ ] **Step 5: Commit**

```bash
cd "g:/マイドライブ/YNFactory-cc"
git add iphone-screenshot-share/receiver.py iphone-screenshot-share/tests/test_receiver.py
git commit -m "feat(iphone-share): Receiver.process_update + main loop (TDD)"
```

---

### Task 8: run()ループのoffset前進テスト（取りこぼし/重複防止）

**Files:**
- Modify: `iphone-screenshot-share/tests/test_receiver.py`
- （`receiver.py` は Task 7 で実装済み。テスト追加のみ）

- [ ] **Step 1: Write the failing test（test_receiver.py に追記）**

`ProcessUpdate` クラスの下に追記:
```python
class RunLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

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


# add this import at top of file if missing:
import json
```

> 既に先頭に `import json` が無ければ、ファイル冒頭の import 群に `import json` を追加する。

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_receiver -v`
Expected: PASS（実装はTask 7済みのため通る想定）。もしFAILなら `run()` のoffset更新/`save_state`呼び出しを確認して修正。

- [ ] **Step 3: （必要時のみ）修正**

`run()` 内で各updateごとに `self._state["offset"] = update["update_id"] + 1` と `save_state(...)` を呼んでいることを確認。`get_updates` が `SystemExit(0)` を送出した場合に `except SystemExit: raise` で抜けることを確認（Task 7実装済み）。

- [ ] **Step 4: Run test to verify it passes**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest tests.test_receiver -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd "g:/マイドライブ/YNFactory-cc"
git add iphone-screenshot-share/tests/test_receiver.py
git commit -m "test(iphone-share): run loop advances and persists offset"
```

---

### Task 9: start.bat（ASCII）+ README.md（日本語手順）

**Files:**
- Create: `iphone-screenshot-share/start.bat`
- Create: `iphone-screenshot-share/README.md`

- [ ] **Step 1: `start.bat` 作成（ASCII文字のみ・日本語禁止）**

`iphone-screenshot-share/start.bat`:
```bat
@echo off
REM iPhone screenshot share - receiver launcher
REM Requires Python 3.8+ on PATH. See README.md for setup (Japanese).
chcp 65001 >nul
cd /d "%~dp0"
if not exist config.json (
  echo [ERROR] config.json not found. Copy config.example.json to config.json and edit it.
  pause
  exit /b 1
)
python receiver.py
echo.
echo receiver stopped. Press any key to close.
pause >nul
```

> `chcp 65001` で出力をUTF-8にし、Pythonのログ（英語）を文字化けさせない。本文は全てASCIIなのでCP932誤読で即終了しない（[[feedback_windows_bat_ascii]] の教訓）。

- [ ] **Step 2: `README.md` 作成（日本語）**

`iphone-screenshot-share/README.md`:
```markdown
# iPhoneスクショ共有ツール

iPhoneで撮ったスクリーンショットを、Telegram経由でこのPCの
`ピクチャ\iPhoneScreenshots\` フォルダに自動保存します。
家でも外でも（iPhoneがネットに繋がっていれば）使えます。

## 仕組み

```
iPhone: スクショ → 共有シート → Telegram → 専用ボットに送信
PC: receiver.py が受信して画像をフォルダに自動保存
```

## 初回セットアップ（10分）

### 1. 専用ボットを作る（Claude用ボットとは別に必ず新規で）

1. iPhone/PCのTelegramで **@BotFather** を開く
2. `/newbot` を送る → ボット名とユーザー名を決める
3. 表示された **トークン**（`123456:ABC-...` の形）をコピー

> 既存のClaude用ボットのトークンは使わないこと。同じトークンを2つのプログラムで
> 受信すると 409 Conflict エラーになります。

### 2. 設定ファイルを作る

1. `config.example.json` をコピーして `config.json` を作る
2. `config.json` を開き、`bot_token` にコピーしたトークンを貼る
3. 保存する（`allowed_chat_ids` は空のままでOK。次の手順で自動取得）

### 3. 起動して自分のchat_idを登録する

1. `start.bat` をダブルクリックで起動
2. iPhoneのTelegramで、作ったボットを開き **何かメッセージを送る**
3. PCの黒い画面に `SETUP MODE: received from chat_id=XXXXXXXX` と出る
4. その数字（chat_id）を `config.json` の `allowed_chat_ids` に入れる
   例: `"allowed_chat_ids": [12345678]`
5. 黒い画面を閉じ、`start.bat` を再起動

### 4. 使う

1. iPhoneでスクショを撮る
2. 共有シート → Telegram → 作ったボットを選んで送信
3. PCの `ピクチャ\iPhoneScreenshots\` に `YYYYMMDD_HHMMSS.jpg` で保存される
4. Telegramに `OK saved: ...` と返信が来れば成功

## 設定項目（config.json）

| 項目 | 説明 |
|---|---|
| `bot_token` | BotFatherで取得したトークン |
| `allowed_chat_ids` | 受信を許可するchat_idの配列（自分のidのみ推奨） |
| `save_dir` | 保存先。`%USERPROFILE%` 等の環境変数が使える |
| `send_confirmation` | `true`でTelegramに保存完了を返信。不要なら`false` |
| `poll_timeout` | 受信待ちの秒数（既定30） |

## 常駐させたい場合（任意）

- `start.bat` のショートカットを作り、`Win+R` → `shell:startup` で開いた
  スタートアップフォルダに置くと、ログイン時に自動起動します。
- 黒い画面を出したくない場合は、`start.bat` 内の `python` を `pythonw` に
  変えるとウィンドウ無しで常駐します（ログは見えなくなります）。

## 画質について（圧縮されるのが気になる人向け）

- Telegramの共有送信は画像を軽く圧縮（JPEG化）します。通常の閲覧用途では十分です。
- 元のPNGを無劣化で送りたい場合は、iOSショートカットから Bot API の
  `sendDocument` に直接送る「方式B」に拡張できます（受信側 receiver.py は
  document 受信に既に対応済みなので、改修不要）。必要になったら追記します。

## トラブルシューティング

| 症状 | 対処 |
|---|---|
| `409 Conflict ... Exiting` | トークンが他プログラムと重複。**専用ボット**を新規作成して使う |
| 保存されない | `config.json` の `allowed_chat_ids` に自分のchat_idが入っているか確認 |
| `config.json not found` | `config.example.json` をコピーして `config.json` を作る |
| `python` が見つからない | Python 3.8+ をインストールし「Add to PATH」を有効にする |
```

- [ ] **Step 3: 動作確認（起動だけ）**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python receiver.py`
Expected: `config.json` 未作成なら `SystemExit: config.json: set your bot_token first` で即終了すればOK（ここではトークン未設定の正常な失敗を確認するだけ）。Ctrl+Cで終了。

- [ ] **Step 4: Commit**

```bash
cd "g:/マイドライブ/YNFactory-cc"
git add iphone-screenshot-share/start.bat iphone-screenshot-share/README.md
git commit -m "docs(iphone-share): start.bat launcher and Japanese README"
```

---

### Task 10: 全テスト緑化 + 手動E2E + 仕上げコミット

**Files:**
- （新規変更なし。検証のみ。必要なら微修正）

- [ ] **Step 1: 全単体テストを通す**

Run: `cd "g:/マイドライブ/YNFactory-cc/iphone-screenshot-share" && python -m unittest discover -s tests -p "test_*.py" -v`
Expected: 全テスト PASS（core / telegram_client / receiver）。出力は要約＋末尾のみ確認（CLAUDE.md 出力制限）。

- [ ] **Step 2: 手動E2E（実機・ユーザー操作）**

1. README手順でBotFatherから専用ボット作成→`config.json`設定
2. `start.bat`起動→iPhoneから自分のchat_id取得→`allowed_chat_ids`へ登録→再起動
3. iPhoneでスクショ→共有→Telegram→ボット送信
4. `%USERPROFILE%\Pictures\iPhoneScreenshots\` に画像が保存され、Telegramに `OK saved:` 返信が来ることを確認
5. 未許可の別アカウント/別chatから送って**保存されない**ことを確認（任意）

> このStepはユーザーの実機・トークンが必要。実装エージェントはここまでの自動テストが緑であることを確認し、E2Eはユーザーに依頼する。

- [ ] **Step 3: 設計書の完了条件チェック**

設計書 `docs/superpowers/specs/2026-06-02-iphone-screenshot-share-design.md` のセクション11チェックリストを上から確認し、未達があれば該当Taskに戻る。

- [ ] **Step 4: 最終コミット（差分があれば）**

```bash
cd "g:/マイドライブ/YNFactory-cc"
git add iphone-screenshot-share
git commit -m "chore(iphone-share): finalize iphone screenshot share tool"
```

---

## Self-Review メモ（計画作成者による確認）

- **Spec coverage**: 設計書 §3〜§9 を Task 1〜10 が網羅（保存先=Task5/7、許可リスト=Task2/7、409=Task6/7、photo+document=Task3、ファイル名衝突=Task4、状態offset=Task7/8、start.bat ASCII=Task9、README=Task9、テスト=Task2-8、E2E=Task10）。
- **Placeholder scan**: TBD/TODOなし。各コードステップに実コードを記載。
- **Type consistency**: `extract_image`→`(file_id, ext)`、`build_filename(dt, ext, existing)`、`Receiver(client, config, save_dir, state, state_path)`、`TelegramClient(token, base_url, opener)`、`get_updates(offset, timeout)` を全Taskで統一。確認返信文言は実装・テスト・READMEで `OK saved:` に統一。
