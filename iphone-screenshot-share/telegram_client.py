from __future__ import annotations

import json
import os
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
        # Download to a .part file and atomically rename on success so a failed
        # transfer never leaves a truncated image in the save folder.
        tmp = dest_path + ".part"
        try:
            with self._opener.open(req, timeout=60) as resp, open(tmp, "wb") as f:
                f.write(resp.read())
            os.replace(tmp, dest_path)
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise

    def send_message(self, chat_id, text):
        self._request("sendMessage", {"chat_id": chat_id, "text": text})
