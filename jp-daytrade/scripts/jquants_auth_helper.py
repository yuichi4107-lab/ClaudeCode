"""
J-Quants V2 認証ヘルパー

J-Quants API V2 は `x-api-key` ヘッダー直接認証（refresh_token/id_token 不要）。
このスクリプトは API Key の .env 書き込み＋疎通確認を一発で行う。

サブコマンド:
    set-token    API Key を config/.env の JQUANTS_API_KEY に書き込む
    test         現在の .env の API Key で GET /equities/master を叩いて疎通確認

使い方:
    # API Key を .env に保存
    python scripts/jquants_auth_helper.py set-token --token C-4wHtaXcU-...

    # 疎通確認（プラン契約・キー有効性の両方を一発で確認）
    python scripts/jquants_auth_helper.py test
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import requests

JQUANTS_BASE_URL = "https://api.jquants.com/v2"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / "config" / ".env"

ENV_VAR = "JQUANTS_API_KEY"


def _load_env_lines() -> list[str]:
    if not ENV_PATH.exists():
        return []
    return ENV_PATH.read_text(encoding="utf-8").splitlines()


def _write_api_key(token: str) -> None:
    lines = _load_env_lines()
    replaced = False
    pattern = re.compile(rf"^\s*{ENV_VAR}\s*=")
    legacy_pattern = re.compile(r"^\s*JQUANTS_REFRESH_TOKEN\s*=")
    new_lines: list[str] = []
    for line in lines:
        if pattern.match(line):
            new_lines.append(f"{ENV_VAR}={token}")
            replaced = True
        elif legacy_pattern.match(line):
            # 旧 V1 変数はコメントアウトして残す
            new_lines.append(f"# [V1 legacy] {line}")
        else:
            new_lines.append(line)
    if not replaced:
        new_lines.append(f"{ENV_VAR}={token}")
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"[OK] {ENV_VAR} を書き込みました: {ENV_PATH}")


def _read_api_key() -> str | None:
    for line in _load_env_lines():
        m = re.match(rf"^\s*{ENV_VAR}\s*=\s*(.*?)\s*$", line)
        if m:
            val = m.group(1)
            return val or None
    return None


def cmd_set_token(args: argparse.Namespace) -> int:
    token = args.token.strip()
    if not token:
        print("[NG] --token が空です")
        return 1
    _write_api_key(token)
    return 0


def cmd_test(_: argparse.Namespace) -> int:
    key = _read_api_key()
    if not key:
        print(f"[NG] {ENV_PATH} に {ENV_VAR} が設定されていません")
        return 1

    print(f"[..] API Key 先頭: {key[:12]}... / 長さ {len(key)} 文字")

    # GET /equities/master で疎通確認
    url = f"{JQUANTS_BASE_URL}/equities/master"
    r = requests.get(url, headers={"x-api-key": key}, timeout=30)
    print(f"[..] GET /equities/master status={r.status_code}")
    if r.status_code != 200:
        print(f"[NG] 認証失敗: {r.text[:400]}")
        print("     - API Key が無効/再発行された / プラン契約が未完了 / ネットワーク不通")
        return 2

    data = r.json().get("data", [])
    print(f"[OK] /equities/master 取得成功: 銘柄数={len(data)}")
    if data:
        sample = data[0]
        print(f"     先頭サンプル: Code={sample.get('Code')}  Name={sample.get('CoName')}  Market={sample.get('MktNm')}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="J-Quants V2 認証ヘルパー")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set-token", help="API Key を .env に書き込む")
    p_set.add_argument("--token", required=True)
    p_set.set_defaults(func=cmd_set_token)

    p_test = sub.add_parser("test", help="現在の API Key で疎通確認")
    p_test.set_defaults(func=cmd_test)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
