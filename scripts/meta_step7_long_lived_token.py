#!/usr/bin/env python3
"""Exchange Meta short-lived tokens for longer-lived tokens.

This helper reads the Step6 credential file, requires an App Secret from either
the same file or an environment variable, and updates the credential file
without printing raw tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TOKEN_FILE = (
    ROOT
    / ".company"
    / "engineering"
    / "sns-credentials"
    / "step6-tokens-2026-06-09.txt"
)
API_VERSION = "v25.0"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def upsert_env_lines(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                out.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        out.append(line)

    missing = [key for key in updates if key not in seen]
    if missing:
        out.append("")
        out.append("# Step7 long-lived token exchange")
        out.extend(f"{key}={updates[key]}" for key in missing)

    path.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def graph_get(path: str, params: dict[str, str]) -> dict:
    query = urlencode(params)
    url = f"https://graph.facebook.com/{API_VERSION}/{path}?{query}"
    try:
        with urlopen(url, timeout=30) as response:
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
    data = json.loads(body)
    if "error" in data:
        raise RuntimeError(data["error"].get("message", json.dumps(data["error"], ensure_ascii=False)))
    return data


def secret_from(values: dict[str, str]) -> str:
    for key in ("APP_SECRET", "META_APP_SECRET", "FACEBOOK_APP_SECRET", "FB_APP_SECRET"):
        if values.get(key):
            return values[key]
    for key in ("META_APP_SECRET", "FACEBOOK_APP_SECRET", "FB_APP_SECRET", "APP_SECRET"):
        if os.environ.get(key):
            return os.environ[key]
    return ""


def prefix(token: str) -> str:
    return token[:10] + "..." if token else ""


def main() -> int:
    parser = argparse.ArgumentParser(description="Meta Step7 long-lived token exchange.")
    parser.add_argument("--token-file", type=Path, default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--no-write", action="store_true", help="Validate only; do not update the token file")
    args = parser.parse_args()

    token_file = args.token_file
    if not token_file.exists():
        print(json.dumps({"status": "blocked", "reason": "token_file_not_found", "path": str(token_file)}, ensure_ascii=False))
        return 2

    values = parse_env_file(token_file)
    app_id = values.get("APP_ID", "")
    short_user_token = values.get("USER_ACCESS_TOKEN_SHORT", "")
    app_secret = secret_from(values)

    if not app_id or not short_user_token:
        print(json.dumps({"status": "blocked", "reason": "missing_app_id_or_short_token"}, ensure_ascii=False))
        return 2

    if not app_secret:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "reason": "missing_app_secret",
                    "needed_key": "APP_SECRET",
                    "token_file": str(token_file),
                },
                ensure_ascii=False,
            )
        )
        return 2

    exchange = graph_get(
        "oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_user_token,
        },
    )
    long_user_token = exchange.get("access_token", "")
    expires_in = int(exchange.get("expires_in", 0) or 0)
    if not long_user_token:
        raise RuntimeError("Meta exchange response did not include access_token")

    accounts = graph_get(
        "me/accounts",
        {
            "fields": "id,name,access_token",
            "access_token": long_user_token,
        },
    )
    pages = accounts.get("data", [])
    target_page = next(
        (page for page in pages if page.get("id") == values.get("FB_PAGE_ID")),
        pages[0] if pages else None,
    )
    if not target_page or not target_page.get("access_token"):
        raise RuntimeError("Could not refresh Page Access Token from long-lived user token")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=expires_in) if expires_in else None
    updates = {
        "USER_ACCESS_TOKEN_LONG": long_user_token,
        "USER_TOKEN_LONG_EXPIRES": expires_at.isoformat() if expires_at else "unknown",
        "PAGE_ACCESS_TOKEN_LONG_SOURCE": "me/accounts using USER_ACCESS_TOKEN_LONG",
        "PAGE_ACCESS_TOKEN": target_page["access_token"],
        "STEP7_UPDATED_AT": now.isoformat(),
    }

    if not args.no_write:
        upsert_env_lines(token_file, updates)

    result = {
        "status": "ok",
        "wrote_file": not args.no_write,
        "token_file": str(token_file),
        "user_token_long_prefix": prefix(long_user_token),
        "page_token_prefix": prefix(target_page["access_token"]),
        "expires_at": updates["USER_TOKEN_LONG_EXPIRES"],
        "page_id": target_page.get("id"),
        "page_name": target_page.get("name"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        sys.exit(1)
