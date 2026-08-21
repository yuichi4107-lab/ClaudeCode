"""NotebookLM上の「インポート失敗」ソース（aria-labelがYouTube URLのままのもの）を削除する。

失敗ソースは aria-label が "https://www.youtube.com/watch?v=..." のまま残るため、
これを検出して NotebookLM 上から削除し、state.sqlite からも該当 video_id を取り除く。
sync.py --init を実行すると、削除した動画が再び追加対象になる。"""
import logging
import re
import sys
import time
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SRC_DIR = THIS_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from config import load_config
from notebooklm import NotebookLMClient, SessionExpiredError
from state import StateDB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("delete_error")

_RE_VIDEO_ID = re.compile(r"watch\?v=([A-Za-z0-9_-]{11})")


def main() -> int:
    cfg_path = THIS_DIR.parent / "config.yaml"
    cfg = load_config(str(cfg_path))

    db_path = THIS_DIR.parent / "state.sqlite"
    db = StateDB(str(db_path))

    total_deleted = 0
    total_failed = 0
    deleted_video_ids = []

    with NotebookLMClient(
        user_data_dir=cfg.playwright.user_data_dir,
        headless=cfg.playwright.headless,
        navigation_timeout_ms=cfg.playwright.navigation_timeout_ms,
        source_add_timeout_ms=cfg.playwright.source_add_timeout_ms,
        notebooklm_url=cfg.playwright.notebooklm_url,
    ) as client:
        for channel in cfg.channels:
            if not channel.notebook_id:
                continue

            try:
                labels = client.list_sources(channel.notebook_id)
            except SessionExpiredError as exc:
                log.error("Google session expired: %s", exc)
                return 2

            # URLのまま残っているソースを抽出
            url_labels = [l for l in labels if l.startswith("https://www.youtube.com/watch?v=")]
            log.info("channel_id=%s name=%s found %d error sources (out of %d total)",
                     channel.id, channel.name, len(url_labels), len(labels))

            for url in url_labels:
                m = _RE_VIDEO_ID.search(url)
                vid_id = m.group(1) if m else ""
                try:
                    ok = client.delete_source(channel.notebook_id, url)
                except SessionExpiredError as exc:
                    log.error("Google session expired: %s", exc)
                    return 2

                if ok:
                    total_deleted += 1
                    if vid_id:
                        # state.sqliteから削除して再アップロード対象にする
                        db._conn.execute(
                            "DELETE FROM processed_videos WHERE channel_id = ? AND video_id = ?",
                            (channel.id, vid_id),
                        )
                        db._conn.commit()
                        deleted_video_ids.append(vid_id)
                    log.info("DELETED [%d] channel_id=%s video_id=%s",
                             total_deleted, channel.id, vid_id)
                else:
                    total_failed += 1
                    log.warning("FAILED channel_id=%s url=%s", channel.id, url)

                time.sleep(2)

    log.info("delete_error_sources done. deleted=%d failed=%d", total_deleted, total_failed)
    if deleted_video_ids:
        log.info("deleted video_ids: %s", ",".join(deleted_video_ids))
    return 0


if __name__ == "__main__":
    sys.exit(main())
