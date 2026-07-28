"""
config.yaml と secrets.yaml を読み込み、
アプリ全体で使える設定オブジェクトを提供する。
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

import yaml


@dataclass
class ChannelConfig:
    id: str
    handle: str
    name: str
    notebook_id: str


@dataclass
class SyncConfig:
    rss_max_entries: int = 15
    init_max_videos: int = 0
    request_delay_sec: int = 3
    retry_count: int = 3
    retry_backoff_sec: int = 5


@dataclass
class PlaywrightConfig:
    user_data_dir: str = "./.auth/chromium"
    cdp_endpoint: str = "http://localhost:9222"
    headless: bool = True
    navigation_timeout_ms: int = 60000
    source_add_timeout_ms: int = 30000
    notebooklm_url: str = "https://notebooklm.google.com"


@dataclass
class LoggingConfig:
    file: str = "logs/sync.log"
    level: str = "INFO"
    max_bytes: int = 10485760
    backup_count: int = 5


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""


@dataclass
class AppConfig:
    channels: List[ChannelConfig] = field(default_factory=list)
    sync: SyncConfig = field(default_factory=SyncConfig)
    playwright: PlaywrightConfig = field(default_factory=PlaywrightConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


def _load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(
    config_path: str = "config.yaml",
    secrets_path: str = "secrets.yaml",
) -> AppConfig:
    """config.yaml と secrets.yaml を読み込んで AppConfig を返す。"""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")

    raw = _load_yaml(config_file)

    channels = [
        ChannelConfig(
            id=ch["id"],
            handle=ch.get("handle", ""),
            name=ch.get("name", ch["id"]),
            notebook_id=ch.get("notebook_id", ""),
        )
        for ch in raw.get("channels", [])
    ]

    sync_raw = raw.get("sync", {})
    sync = SyncConfig(
        rss_max_entries=sync_raw.get("rss_max_entries", 15),
        init_max_videos=sync_raw.get("init_max_videos", 0),
        request_delay_sec=sync_raw.get("request_delay_sec", 3),
        retry_count=sync_raw.get("retry_count", 3),
        retry_backoff_sec=sync_raw.get("retry_backoff_sec", 5),
    )

    pw_raw = raw.get("playwright", {})
    yaml_user_data_dir = pw_raw.get("user_data_dir", "./.auth/chromium")
    playwright = PlaywrightConfig(
        user_data_dir=os.getenv("NOTEBOOKLM_AUTH_DIR", yaml_user_data_dir),
        cdp_endpoint=pw_raw.get("cdp_endpoint", "http://localhost:9222"),
        headless=pw_raw.get("headless", True),
        navigation_timeout_ms=pw_raw.get("navigation_timeout_ms", 60000),
        source_add_timeout_ms=pw_raw.get("source_add_timeout_ms", 30000),
        notebooklm_url=pw_raw.get("notebooklm_url", "https://notebooklm.google.com"),
    )

    log_raw = raw.get("logging", {})
    logging_cfg = LoggingConfig(
        file=log_raw.get("file", "logs/sync.log"),
        level=log_raw.get("level", "INFO"),
        max_bytes=log_raw.get("max_bytes", 10485760),
        backup_count=log_raw.get("backup_count", 5),
    )

    # secrets.yaml はオプション。存在しない場合は空のまま継続
    telegram = TelegramConfig()
    secrets_file = Path(secrets_path)
    if secrets_file.exists():
        secrets = _load_yaml(secrets_file)
        tg = secrets.get("telegram", {})
        telegram = TelegramConfig(
            bot_token=tg.get("bot_token", ""),
            chat_id=str(tg.get("chat_id", "")),
        )

    return AppConfig(
        channels=channels,
        sync=sync,
        playwright=playwright,
        logging=logging_cfg,
        telegram=telegram,
    )
