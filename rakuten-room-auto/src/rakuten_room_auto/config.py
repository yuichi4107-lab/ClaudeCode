from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .statuses import Statuses


ENV_PATTERN = re.compile(r"\$\{([^}:]+)(?::-([^}]*))?\}")


def expand_env(value: Any) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            name, default = match.group(1), match.group(2)
            return os.environ.get(name, default or "")

        return os.path.expanduser(ENV_PATTERN.sub(replace, value))
    if isinstance(value, dict):
        return {key: expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [expand_env(item) for item in value]
    return value


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def default_config_dict() -> dict[str, Any]:
    return {
        "runtime": {
            "root_dir": "~/rakuten-room-auto",
            "ledger_path": "~/rakuten-room-auto/data/post-ledger.jsonl",
            "log_dir": "~/rakuten-room-auto/logs",
            "max_items_per_run": 1,
        },
        "google": {
            "client_secret_json": "${GOOGLE_CLIENT_SECRET_JSON:-~/rakuten-room-auto/secrets/google-oauth-client.json}",
            "token_json": "${GOOGLE_TOKEN_JSON:-~/rakuten-room-auto/secrets/google-token.json}",
        },
        "sheet": {
            "spreadsheet_id": "${GOOGLE_SHEETS_SPREADSHEET_ID}",
            "worksheet_name": "${GOOGLE_SHEETS_WORKSHEET_NAME:-ROOM投稿管理}",
            "header_row": 1,
            "columns": {
                "product_url": "商品URL",
                "description": "紹介文",
                "status": "ステータス",
                "posted_at": "投稿日時",
                "error": "エラー",
                "attempts": "試行回数",
            },
        },
        "statuses": {
            "unposted": "未投稿",
            "approval_pending": "承認待ち",
            "approved": "承認済",
            "processing": "処理中",
            "completed": "完了",
            "needs_review": "要確認",
            "error": "エラー",
        },
        "browser": {
            "cdp_endpoint": "${RAKUTEN_ROOM_CDP_ENDPOINT:-http://127.0.0.1:9225}",
            "expected_profile_name": "${RAKUTEN_ROOM_EXPECTED_PROFILE:-Yuichi}",
            "room_home_url": "https://room.rakuten.co.jp/",
            "my_room_url": "https://room.rakuten.co.jp/myroom",
            "navigation_timeout_ms": 45000,
            "action_timeout_ms": 20000,
        },
        "llm": {
            "enabled": False,
            "provider": "openai",
            "model": "${OPENAI_MODEL}",
            "max_chars": 180,
        },
        "replenish": {
            "enabled": True,
            "threshold": 5,
            "batch": 5,
            "ranking_urls": [
                "https://ranking.rakuten.co.jp/daily/100804/",  # インテリア・寝具・収納
                "https://ranking.rakuten.co.jp/daily/215783/",  # 日用品雑貨・文房具・手芸
                "https://ranking.rakuten.co.jp/daily/558944/",  # キッチン用品・食器・調理器具
            ],
        },
    }


@dataclass(frozen=True)
class RuntimeConfig:
    root_dir: Path
    ledger_path: Path
    log_dir: Path
    max_items_per_run: int = 1


@dataclass(frozen=True)
class GoogleConfig:
    client_secret_json: Path
    token_json: Path


@dataclass(frozen=True)
class SheetConfig:
    spreadsheet_id: str
    worksheet_name: str
    header_row: int = 1
    columns: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BrowserConfig:
    cdp_endpoint: str
    expected_profile_name: str
    room_home_url: str
    my_room_url: str
    navigation_timeout_ms: int = 45000
    action_timeout_ms: int = 20000


@dataclass(frozen=True)
class LLMConfig:
    enabled: bool = False
    provider: str = "openai"
    model: str = ""
    max_chars: int = 180


@dataclass(frozen=True)
class ReplenishConfig:
    enabled: bool = True
    threshold: int = 5
    batch: int = 5
    ranking_urls: tuple[str, ...] = ()


@dataclass(frozen=True)
class AppConfig:
    runtime: RuntimeConfig
    google: GoogleConfig
    sheet: SheetConfig
    statuses: Statuses
    browser: BrowserConfig
    llm: LLMConfig
    replenish: ReplenishConfig


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def find_config_path(explicit: str | None = None) -> Path:
    if explicit:
        return Path(os.path.expanduser(explicit))
    env_path = os.environ.get("RAKUTEN_ROOM_CONFIG")
    if env_path:
        return Path(os.path.expanduser(env_path))
    local = Path("config.yaml")
    if local.exists():
        return local
    return Path(os.path.expanduser("~/rakuten-room-auto/config.yaml"))


def load_config(explicit: str | None = None) -> AppConfig:
    dotenv_candidates = [Path(".env"), Path(os.path.expanduser("~/rakuten-room-auto/.env"))]
    for dotenv in dotenv_candidates:
        load_dotenv(dotenv)

    raw = default_config_dict()
    config_path = find_config_path(explicit)
    if config_path.exists():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        raw = deep_merge(raw, loaded)

    data = expand_env(raw)
    runtime = RuntimeConfig(
        root_dir=Path(data["runtime"]["root_dir"]),
        ledger_path=Path(data["runtime"]["ledger_path"]),
        log_dir=Path(data["runtime"]["log_dir"]),
        max_items_per_run=int(data["runtime"].get("max_items_per_run", 1)),
    )
    google = GoogleConfig(
        client_secret_json=Path(data["google"]["client_secret_json"]),
        token_json=Path(data["google"]["token_json"]),
    )
    sheet = SheetConfig(
        spreadsheet_id=str(data["sheet"].get("spreadsheet_id", "")),
        worksheet_name=str(data["sheet"].get("worksheet_name", "")),
        header_row=int(data["sheet"].get("header_row", 1)),
        columns=dict(data["sheet"].get("columns", {})),
    )
    statuses = Statuses(**data.get("statuses", {}))
    browser = BrowserConfig(**data["browser"])
    llm = LLMConfig(**data["llm"])
    replenish_data = data.get("replenish", {})
    replenish = ReplenishConfig(
        enabled=bool(replenish_data.get("enabled", True)),
        threshold=int(replenish_data.get("threshold", 5)),
        batch=int(replenish_data.get("batch", 5)),
        ranking_urls=tuple(replenish_data.get("ranking_urls", [])),
    )
    return AppConfig(
        runtime=runtime, google=google, sheet=sheet, statuses=statuses, browser=browser, llm=llm, replenish=replenish
    )
