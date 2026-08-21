#!/usr/bin/env python
"""YouTubeセッション生存確認（launchd手動 or デバッグ用）。

~/shorts-factory/.venv/bin/python scripts/check_youtube_session.py
失効していれば Telegram に再ログイン手順を通知する。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.platforms import youtube_cdp  # noqa: E402
from src import notify  # noqa: E402

RUNBOOK = (
    "🔑 YouTubeセッション失効。再ログイン手順:\n"
    "1. launchctl unload ~/Library/LaunchAgents/com.ynfactory.shorts-chrome.plist\n"
    "2. ~/shorts-factory/app/scripts/login_youtube.sh を実行しGoogleログイン\n"
    "3. Chromeを閉じて launchctl load ~/Library/LaunchAgents/com.ynfactory.shorts-chrome.plist"
)

if __name__ == "__main__":
    try:
        ok = youtube_cdp.check_session()
    except Exception as e:
        print(f"確認失敗: {e}")
        notify.send_message(f"⚠️ YouTubeセッション確認が実行できません: {e}\n常駐Chrome(9223)が起動しているか確認してください")
        sys.exit(2)
    if ok:
        print("YouTubeセッション: OK")
    else:
        print("YouTubeセッション: 失効")
        notify.send_message(RUNBOOK)
        sys.exit(1)
