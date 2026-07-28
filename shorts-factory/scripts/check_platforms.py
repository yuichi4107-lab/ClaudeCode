#!/usr/bin/env python3
"""Check shorts-factory platform readiness without publishing anything."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.config import CONFIG  # noqa: E402


def check_meta_reels() -> dict:
    required = ["META_IG_USER_ID", "META_ACCESS_TOKEN"]
    values: dict[str, str] = {}
    if CONFIG.sns_env_path.exists():
        for raw in CONFIG.sns_env_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
    missing = [key for key in required if not values.get(key)]
    return {
        "platform": "instagram",
        "mode": "env-check",
        "ready": not missing,
        "missing": missing,
        "env_path": str(CONFIG.sns_env_path),
    }


def check_youtube() -> dict:
    from src.platforms import youtube_cdp

    try:
        ready = youtube_cdp.check_session()
        return {"platform": "youtube", "mode": "browser-session", "ready": ready}
    except Exception as exc:
        return {
            "platform": "youtube",
            "mode": "browser-session",
            "ready": False,
            "error": str(exc)[:300],
        }


def check_tiktok() -> dict:
    from src.platforms import tiktok_cdp

    try:
        ready = tiktok_cdp.check_session()
        return {"platform": "tiktok", "mode": "browser-session", "ready": ready}
    except Exception as exc:
        return {
            "platform": "tiktok",
            "mode": "browser-session",
            "ready": False,
            "error": str(exc)[:300],
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="投稿先の準備状況を確認する。実投稿はしない。")
    ap.add_argument("--skip-browser", action="store_true", help="YouTube/TikTokのブラウザ確認を省略")
    args = ap.parse_args()

    results = [
        {
            "platform": "x",
            "mode": "existing-script",
            "ready": True,
            "note": "既存X投稿は稼働済み",
        },
        check_meta_reels(),
    ]
    if not args.skip_browser:
        results.extend([check_youtube(), check_tiktok()])

    print(
        json.dumps(
            {
                "repo_root": str(CONFIG.repo_root),
                "runtime_dir": str(CONFIG.runtime_dir),
                "configured_platforms": CONFIG.get("queue", "platforms", default=[]),
                "auto_post": CONFIG.get("queue", "auto_post", default=False),
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(r.get("ready") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
