"""既存ソースに公開日プレフィックス [YYYY-MM-DD] を後付けする。

state.sqlite から処理済み動画のリストを取得し、video_dates.json から
title/upload_date を参照。NotebookLMの該当ソースを [YYYY-MM-DD] タイトル 形式にリネーユ。

video_dates.json はローカルで scripts/fetch_dates_local.py で生成する
（VPS IPはYouTubeにbot判定されるためローカルから取得が必要）。

NotebookLMの自動タイトル化と競合するため、URL一致と既存タイトル一致の両方を試す。
"""
import json
import logging
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
log = logging.getLogger("bulk_rename")


def main() -> int:
    cfg_path = THIS_DIR.parent / "config.yaml"
    cfg = load_config(str(cfg_path))

    db_path = THIS_DIR.parent / "state.sqlite"
    db = StateDB(str(db_path))

    # video_dates.json をロード（ローカルで生成しVPSへscp転送した想定）
    json_path = THIS_DIR.parent / "video_dates.json"
    if not json_path.exists():
        log.error("video_dates.json not found at %s. Run scripts/fetch_dates_local.py "
                  "on a Windows/Mac machine and scp the JSON to VPS.", json_path)
        return 1
    video_map = json.loads(json_path.read_text(encoding="utf-8"))
    log.info("loaded %d video entries from %s", len(video_map), json_path)

    total_renamed = 0
    total_failed = 0

    with NotebookLMClient(
        user_data_dir=cfg.playwright.user_data_dir,
        headless=cfg.playwright.headless,
        navigation_timeout_ms=cfg.playwright.navigation_timeout_ms,
        source_add_timeout_ms=cfg.playwright.source_add_timeout_ms,
        notebooklm_url=cfg.playwright.notebooklm_url,
    ) as client:
        for channel in cfg.channels:
            if not channel.notebook_id:
                log.warning("channel_id=%s notebook_id not set, skipping", channel.id)
                continue

            # 1) ノートブック内の現在の aria-label 一覧を取得
            try:
                existing_labels = client.list_sources(channel.notebook_id)
            except SessionExpiredError as exc:
                log.error("Google session expired: %s", exc)
                return 2
            log.info("channel_id=%s name=%s notebook has %d sources",
                     channel.id, channel.name, len(existing_labels))

            # state.sqlite から該当チャンネルの全レコード取得
            cur = db._conn.execute(
                "SELECT video_id, title, published_at FROM processed_videos WHERE channel_id = ?",
                (channel.id,),
            )
            rows = cur.fetchall()
            log.info("channel_id=%s state has %d records", channel.id, len(rows))

            # 2) リネーユ対象ペアを構築
            pairs = []
            target_video_ids = []
            target_info = []
            for vid_id, db_title, db_pub in rows:
                info = video_map.get(vid_id, {})
                title = info.get("title") or db_title or ""
                pub = info.get("upload_date") or db_pub or ""

                if not pub or not title:
                    continue

                new_label = f"[{pub}] {title}"

                # 既にプレフィックス付きのソースがあればスキップ
                if new_label in existing_labels:
                    log.info("channel_id=%s video_id=%s already has target label, skipping",
                             channel.id, vid_id)
                    continue

                # マッチ候補: URLの完全一致 / タイトル完全一致 のうち存在するもの
                video_url = f"https://www.youtube.com/watch?v={vid_id}"
                match_value = None
                if video_url in existing_labels:
                    match_value = video_url
                elif title in existing_labels:
                    match_value = title

                if not match_value:
                    log.warning("channel_id=%s video_id=%s no matching source in notebook, skipping",
                                channel.id, vid_id)
                    total_failed += 1
                    continue

                pairs.append((match_value, new_label))
                target_video_ids.append(vid_id)
                target_info.append((vid_id, title, pub))

            log.info("channel_id=%s prepared %d rename pairs", channel.id, len(pairs))

            # 3) 1劵画ずつ navigate して rename（連続実行えり安定）
            for (vid_id, title, pub), (mv, nl) in zip(target_info, pairs):
                try:
                    ok = client.rename_source(channel.notebook_id, mv, nl)
                except SessionExpiredError as exc:
                    log.error("Google session expired: %s", exc)
                    return 2

                if ok:
                    db.mark_processed(channel.id, vid_id, title, pub)
                    total_renamed += 1
                    log.info("RENAMED [%d] channel_id=%s video_id=%s",
                             total_renamed, channel.id, vid_id)
                else:
                    total_failed += 1
                    log.warning("FAILED channel_id=%s video_id=%s", channel.id, vid_id)
                time.sleep(1)

    log.info("bulk_rename done. renamed=%d failed=%d", total_renamed, total_failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
