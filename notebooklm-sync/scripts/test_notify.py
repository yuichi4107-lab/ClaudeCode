"""
Telegram通知の動作確認スクリプト。

使い方:
  python scripts/test_notify.py            # send_summary + send_alert の両方を送信
  python scripts/test_notify.py --summary  # send_summary のみ
  python scripts/test_notify.py --alert    # send_alert のみ

前提:
  secrets.yaml に bot_token / chat_id を記入済みであること。
  未設定の場合は案内メッセージを表示して終了する。

import パス解決: setup_auth.py と同じ方式で src/ を sys.path に追加する。
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

# Windows PowerShell環境でUTF-8出力を強制する
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() not in ("utf-8", "utf8"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# src/ をパスに追加（scripts/ 直下から src/ を参照するため）
THIS_DIR = Path(__file__).resolve().parent
SRC_DIR = THIS_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

import requests  # noqa: E402 (sys.path 操作後にimport)

from config import load_config  # noqa: E402
from notify import send_alert, send_summary  # noqa: E402

# デフォルトの config/secrets を notebooklm-sync/ ルートから探す
_ROOT = THIS_DIR.parent
_CONFIG_PATH = str(_ROOT / "config.yaml")
_SECRETS_PATH = str(_ROOT / "secrets.yaml")

_TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/sendMessage"


def _check_telegram_direct(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """
    Telegram Bot API に直接 requests で送信し、HTTP ステータスを確認する。
    notify.py の _send_message はWARNログのみで成否を返さないため、
    テストスクリプトでは結果を明示するためにここで直接確認する。
    戻り値: (success: bool, detail: str)
    """
    url = _TELEGRAM_API_BASE.format(token=bot_token)
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True, f"HTTP 200 OK — message_id={resp.json().get('result', {}).get('message_id', '?')}"
        else:
            return False, f"HTTP {resp.status_code} — {resp.text[:200]}"
    except Exception as exc:
        return False, f"接続エラー: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Telegram通知の動作確認スクリプト",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--summary", action="store_true", help="send_summary のみ送信")
    parser.add_argument("--alert", action="store_true", help="send_alert のみ送信")
    args = parser.parse_args()

    # どちらも未指定なら両方送信
    do_summary = args.summary or (not args.summary and not args.alert)
    do_alert = args.alert or (not args.summary and not args.alert)

    # 設定を読み込む
    try:
        cfg = load_config(config_path=_CONFIG_PATH, secrets_path=_SECRETS_PATH)
    except FileNotFoundError as e:
        print(f"[ERROR] 設定ファイルが見つかりません: {e}")
        sys.exit(1)

    bot_token = cfg.telegram.bot_token
    chat_id = cfg.telegram.chat_id

    # 未設定チェック（事前に分かりやすく案内して終了）
    if not bot_token or not chat_id:
        print("=" * 60)
        print("[未設定] secrets.yaml に Telegram 認証情報がありません。")
        print()
        print("以下の手順で値を設定してから再実行してください:")
        print("  1. secrets.yaml を開く（secrets.yaml.example を参考に）")
        print("  2. telegram.bot_token に BotFather で発行したトークンを記入")
        print("     例: 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ")
        print("  3. telegram.chat_id に通知先チャットIDを記入")
        print("     確認方法: Telegram で @userinfobot に /start を送ると表示される")
        print("  4. python scripts/test_notify.py を再実行")
        print("=" * 60)
        sys.exit(1)

    print(f"[INFO] bot_token={bot_token[:8]}... chat_id={chat_id}")
    print()

    # --- send_summary テスト ---
    if do_summary:
        dummy_results = [
            {"name": "テストチャンネルA", "added": 2, "skipped": 5, "errors": []},
            {"name": "テストチャンネルB", "added": 0, "skipped": 3, "errors": ["動画取得タイムアウト"]},
        ]
        test_text = (
            "<b>[NotebookLM Sync] 処理完了サマリ</b>\n"
            "  テストチャンネルA: 追加=2 / スキップ=5 / エラー=0\n"
            "  テストチャンネルB: 追加=0 / スキップ=3 / エラー=1\n"
            "\n合計: 追加=2 / エラー=1\n"
            "<i>(これはテスト送信です)</i>"
        )
        ok, detail = _check_telegram_direct(bot_token, chat_id, test_text)
        status = "OK" if ok else "FAIL"
        print(f"[send_summary] {status} — {detail}")
        # notify.py 経由でも呼んで整合性確認（ログは標準エラーに出る）
        send_summary(dummy_results, bot_token, chat_id)

    # --- send_alert テスト ---
    if do_alert:
        test_alert_text = "[テスト] ALERTの動作確認用メッセージです。本番ではエラー発生時に送信されます。"
        ok, detail = _check_telegram_direct(
            bot_token,
            chat_id,
            f"<b>[NotebookLM Sync] ALERT</b>\n{test_alert_text}",
        )
        status = "OK" if ok else "FAIL"
        print(f"[send_alert]   {status} — {detail}")
        # notify.py 経由でも呼んで整合性確認
        send_alert(test_alert_text, bot_token, chat_id)

    print()
    if do_summary and do_alert:
        print("送信完了。Telegram で2件のメッセージを確認してください。")
    elif do_summary:
        print("送信完了。Telegram でサマリメッセージを確認してください。")
    else:
        print("送信完了。Telegram でアラートメッセージを確認してください。")


if __name__ == "__main__":
    main()
