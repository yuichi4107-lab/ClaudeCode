#!/usr/bin/env python3
"""TopView API クライアント（残クレジット照会 / テキスト→動画生成）。

標準ライブラリのみで動く。認証は環境変数 TOPVIEW_API_KEY と TOPVIEW_UID、
または同ディレクトリの .env から読む。

使い方:
    python3 topview_client.py credit
    python3 topview_client.py generate --prompt "..." --duration 5
    python3 topview_client.py generate --prompt "..." --dry-run

API 仕様: https://docs.topview.ai/llms.txt
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE_URL = "https://api.topview.ai"

# 残クレジット照会は /v1 を挟まないパスがドキュメント記載。仕様変更に備えて
# 両方を順に試す。
CREDIT_PATHS = ("/user/credit/detail", "/v1/user/credit/detail")
SUBMIT_PATH = "/v1/common_task/text2video/task/submit"
QUERY_PATH = "/v1/common_task/text2video/task/query"

# docs.topview.ai/reference/error-response より
ERROR_CODES = {
    "4000": "リクエストパラメータエラー",
    "4001": "リクエストデータ形式が不正",
    "4002": "電子署名が一致しない",
    "4003": "必須パラメータが null",
    "4004": "リソースが見つからない",
    "4005": "名前が重複",
    "4006": "リクエスト拒否",
    "4007": "未完了のタスクがあります。前のタスクの完了を待ってください",
    "4100": "クレジット不足",
    "5000": "サーバー内部エラー",
    "5001": "Feign 呼び出しエラー",
    "5003": "サーバー混雑。時間をおいて再試行",
    "5004": "I/O エラー",
    "5005": "不明なエラー",
    "6001": "セキュリティ上の問題を検出",
}

HERE = Path(__file__).resolve().parent


class TopViewError(RuntimeError):
    """API がエラーコードを返した、または通信に失敗した。"""


def load_env() -> tuple[str, str]:
    """API キーと UID を環境変数か .env から取得する。"""
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

    api_key = os.environ.get("TOPVIEW_API_KEY", "").strip()
    uid = os.environ.get("TOPVIEW_UID", "").strip()

    missing = [
        name
        for name, value in (("TOPVIEW_API_KEY", api_key), ("TOPVIEW_UID", uid))
        if not value
    ]
    if missing:
        raise TopViewError(
            f"認証情報が未設定です: {', '.join(missing)}\n"
            "  topview.ai/api-settings で発行し、環境変数に設定するか\n"
            f"  {env_file} に記述してください（.env は git 管理外）。"
        )
    return api_key, uid


def request(
    method: str,
    path: str,
    api_key: str,
    uid: str,
    *,
    params: dict | None = None,
    body: dict | None = None,
    timeout: int = 60,
) -> dict:
    """TopView API を呼び、result 部分を返す。"""
    url = BASE_URL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)

    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Topview-Uid", uid)
    if data is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise TopViewError(f"HTTP {exc.code} {exc.reason}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise TopViewError(f"通信エラー: {exc.reason}") from exc

    code = str(payload.get("code", ""))
    if code not in ("200", "0", ""):
        hint = ERROR_CODES.get(code, payload.get("message", "不明なエラー"))
        raise TopViewError(f"APIエラー code={code}: {hint}")
    return payload.get("result") or {}


def cmd_credit(api_key: str, uid: str) -> int:
    """残クレジットと有効期限を表示する。"""
    last_error: TopViewError | None = None
    for path in CREDIT_PATHS:
        try:
            result = request("GET", path, api_key, uid)
        except TopViewError as exc:
            last_error = exc
            continue

        remain = result.get("remainCredit")
        print("=== TopView 残クレジット ===")
        print(f"  UID          : {result.get('uid', uid)}")
        print(f"  残クレジット : {remain}")
        print(f"  有効期限     : {result.get('expiredTime', '(記載なし)')}")

        if isinstance(remain, (int, float)):
            # Ultra は 1 クレジット = $0.10、Seedance 2.0 は 1 クレジット/秒。
            print(f"  → 5秒動画に換算: 約 {int(remain // 5)} 本")
            print(f"  → 金額換算($0.10/クレジット): 約 ${remain * 0.10:,.2f}")

        print(
            "\n注意: Ultra プランのクレジットは API では消費できません"
            "（Web UI 専用）。\n"
            "      API 利用には standard subscription credits または"
            " credit pack が必要です。\n"
            "      https://docs.topview.ai/docs/billing-rules"
        )
        return 0

    raise last_error or TopViewError("残クレジットを取得できませんでした")


def cmd_generate(api_key: str, uid: str, args: argparse.Namespace) -> int:
    """テキストから動画を生成し、完了までポーリングして保存する。"""
    body = {
        "model": args.model,
        "prompt": args.prompt,
        "resolution": args.resolution,
        "aspectRatio": args.aspect_ratio,
        "duration": args.duration,
        "sound": args.sound,
        "generatingCount": 1,
    }

    print("=== 生成リクエスト ===")
    print(json.dumps(body, ensure_ascii=False, indent=2))

    if args.dry_run:
        print("\n--dry-run のため送信しませんでした。")
        return 0

    result = request("POST", SUBMIT_PATH, api_key, uid, body=body)
    task_id = result.get("taskId")
    if not task_id:
        raise TopViewError(f"taskId が返りませんでした: {result}")
    print(f"\ntaskId: {task_id}")

    deadline = time.monotonic() + args.timeout
    while True:
        if time.monotonic() > deadline:
            raise TopViewError(
                f"{args.timeout}秒でタイムアウトしました。taskId={task_id} は"
                " 生成継続中の可能性があります。"
            )

        time.sleep(args.poll_interval)
        status_result = request(
            "GET", QUERY_PATH, api_key, uid, params={"taskId": task_id}
        )
        status = status_result.get("status", "unknown")
        print(f"  status={status}")

        if status == "success":
            break
        if status == "fail":
            raise TopViewError(
                f"生成に失敗しました: {status_result.get('message', status_result)}"
            )

    urls = extract_video_urls(status_result)
    if not urls:
        raise TopViewError(f"動画URLを取得できませんでした: {status_result}")

    outdir = HERE / "output"
    outdir.mkdir(parents=True, exist_ok=True)
    for index, url in enumerate(urls, start=1):
        dest = outdir / f"{task_id}_{index}.mp4"
        print(f"  ダウンロード中 -> {dest}")
        urllib.request.urlretrieve(url, dest)

    print("\n完了。生成URLは有効期限があるため、保存済みファイルを使ってください。")
    return 0


def extract_video_urls(result: dict) -> list[str]:
    """レスポンスから動画URLを拾う。フィールド名の揺れを吸収する。"""
    urls: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if (
                    isinstance(value, str)
                    and value.startswith("http")
                    and ("video" in key.lower() or ".mp4" in value.lower())
                ):
                    urls.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(result)
    # 重複を除きつつ順序を保つ
    return list(dict.fromkeys(urls))


def main() -> int:
    parser = argparse.ArgumentParser(description="TopView API クライアント")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("credit", help="残クレジットを照会する")

    gen = sub.add_parser("generate", help="テキストから動画を生成する")
    gen.add_argument("--prompt", required=True, help="生成プロンプト")
    gen.add_argument("--model", default="Seedance 1.5 pro", help="モデル名")
    gen.add_argument("--duration", type=int, default=5, help="秒数")
    gen.add_argument("--resolution", type=int, default=720, choices=[480, 720, 1080])
    gen.add_argument("--aspect-ratio", default="9:16", help="16:9 / 9:16 / 1:1")
    gen.add_argument("--sound", default="on", choices=["on", "off"])
    gen.add_argument("--poll-interval", type=int, default=10, help="ポーリング間隔(秒)")
    gen.add_argument("--timeout", type=int, default=900, help="待機上限(秒)")
    gen.add_argument("--dry-run", action="store_true", help="送信せず内容だけ表示")

    args = parser.parse_args()

    try:
        api_key, uid = load_env()
        if args.command == "credit":
            return cmd_credit(api_key, uid)
        return cmd_generate(api_key, uid, args)
    except TopViewError as exc:
        print(f"エラー: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
