"""
Saxo Sim API トークン有効期限チェックスクリプト

概要:
    Saxo Sim API に GET リクエストを送り、401 が返ってきた場合は
    logs/forward/alert.log にアラートを書き込む。

使い方:
    python scripts/check_saxo_token.py

cron 設定 (毎朝 8:00 JST = 23:00 UTC 前日):
    0 23 * * * /usr/bin/python3 /opt/ai-trade-system/scripts/check_saxo_token.py >> /opt/ai-trade-system/logs/forward/cron.log 2>&1
"""

import os
import sys
import logging
from datetime import datetime, timezone

# プロジェクトルートを sys.path に追加
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import httpx
from dotenv import load_dotenv

load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# ─── 設定 ───
SAXO_SIM_BASE_URL = "https://gateway.saxobank.com/sim/openapi"
TOKEN_ENV_KEY = "SAXO_SIM_TOKEN"
LOG_DIR = os.path.join(PROJECT_ROOT, "logs", "forward")
ALERT_LOG = os.path.join(LOG_DIR, "alert.log")

# ─── ログ設定 ───
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def write_alert(message: str) -> None:
    """alert.log にアラートを書き込む。"""
    os.makedirs(LOG_DIR, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{now}] ALERT: {message}\n"
    with open(ALERT_LOG, "a", encoding="utf-8") as f:
        f.write(line)
    logger.warning("アラート記録: %s", message)


def check_token() -> bool:
    """
    Saxo Sim API の /port/v1/balances/me エンドポイントにリクエストを送り、
    トークンの有効性を確認する（/me はトークン所有者を自動解決するため
    ClientKey/AccountKey クエリパラメータ不要）。

    Returns:
        True  - トークン有効
        False - トークン失効（401）またはその他エラー
    """
    token = os.environ.get(TOKEN_ENV_KEY, "").strip()
    if not token:
        message = (
            f"環境変数 {TOKEN_ENV_KEY} が未設定です。"
            ".env を確認してください。"
        )
        print(f"[ERROR] {message}")
        write_alert(message)
        return False

    url = f"{SAXO_SIM_BASE_URL}/port/v1/balances/me"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(url, headers=headers)

        if response.status_code == 401:
            message = (
                "Saxo Sim API 401 Unauthorized。"
                "PAT トークンが失効しています。"
                "Developer Portal でトークンを再発行し、"
                ".env の SAXO_SIM_TOKEN を更新してください。"
            )
            print(f"[ALERT] {message}")
            write_alert(message)
            return False

        if response.status_code == 200:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"[OK] [{now}] Saxo Sim API トークン有効 (HTTP 200)")
            logger.info("トークンチェック OK: HTTP 200")
            return True

        # 200・401 以外のレスポンス（警告のみ）
        message = (
            f"Saxo Sim API から予期しないレスポンス: "
            f"HTTP {response.status_code}"
        )
        print(f"[WARN] {message}")
        write_alert(f"WARNING: {message}")
        return False

    except httpx.TimeoutException:
        message = "Saxo Sim API への接続がタイムアウトしました。ネットワークを確認してください。"
        print(f"[ERROR] {message}")
        write_alert(message)
        return False

    except Exception as exc:
        message = f"Saxo Sim API チェック中に予期しないエラー: {exc}"
        print(f"[ERROR] {message}")
        write_alert(message)
        return False


def main():
    """メインエントリポイント。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"=== Saxo トークンチェック開始: {now} ===")

    ok = check_token()

    print(f"=== チェック完了: {'OK' if ok else 'NG'} ===")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
