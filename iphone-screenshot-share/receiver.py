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
            except (TelegramError, OSError) as e:
                # The image is already saved; a failed reply (incl. network
                # errors, which are OSError subclasses) must not undo that.
                log.warning("confirmation reply failed (image was saved): %s", e)

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
                conflict_tries = 0  # a non-conflict error breaks the 409 streak
                log.warning("polling error: %s (retry in %ss)", e, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    try:
        config = load_config()
    except FileNotFoundError:
        raise SystemExit(
            "config.json not found. Copy config.example.json to config.json "
            "and set your bot_token (see README.md).")
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
