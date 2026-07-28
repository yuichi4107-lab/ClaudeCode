"""
NotebookLM YouTube 自動同期 メインエントリ

使い方:
  python src/sync.py --init               全動画を取得して未処理のみ追加
  python src/sync.py                       RSSで差分取得して未処理のみ追加
  python src/sync.py --channel UCxxx      特定チャンネルのみ処理
  python src/sync.py --dry-run            追加せず候補をログ出力のみ
  python src/sync.py --help               ヘルプ表示
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import sys
import time
from pathlib import Path
from typing import List

# srcディレクトリをパスに追加（スクリプト直接実行時の対応）
_SRC_DIR = Path(__file__).parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from config import AppConfig, ChannelConfig, load_config
from notebooklm import NotebookLMClient, SessionExpiredError
from notify import send_alert, send_summary
from state import StateDB
from youtube import list_all_videos, list_recent_videos


def _setup_logging(cfg: AppConfig) -> None:
    """ローテーション付きファイルロガーとコンソールロガーを設定する。"""
    log_file = Path(cfg.logging.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(cfg.logging.level)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    )

    # ファイルハンドラ（ローテーション）
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=cfg.logging.max_bytes,
        backupCount=cfg.logging.backup_count,
        encoding="utf-8",
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # コンソールハンドラ
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root.addHandler(ch)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NotebookLM YouTube 自動同期スクリプト"
    )
    parser.add_argument(
        "--init",
        action="store_true",
        help="全動画をyt-dlpで取得し、未処理のものを追加する（初回実行用）",
    )
    parser.add_argument(
        "--channel",
        metavar="CHANNEL_ID",
        help="処理対象を特定のチャンネルIDに絞る",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="NotebookLMへの追加を行わず、追加候補をログ出力のみ",
    )
    return parser.parse_args()


def _fetch_videos(
    channel: ChannelConfig,
    is_init: bool,
    cfg: AppConfig,
) -> list:
    """チャンネルの動画リストを取得する。--initならyt-dlp、通常はRSS。"""
    retry_count = cfg.sync.retry_count
    retry_backoff = cfg.sync.retry_backoff_sec

    if is_init:
        return list_all_videos(
            channel_id=channel.id,
            retry_count=retry_count,
            retry_backoff_sec=retry_backoff,
            max_videos=cfg.sync.init_max_videos,
        )
    else:
        return list_recent_videos(
            channel_id=channel.id,
            max_entries=cfg.sync.rss_max_entries,
            retry_count=retry_count,
            retry_backoff_sec=retry_backoff,
        )


def _should_process_video(
    video: dict,
    channel: ChannelConfig,
    dry_run: bool,
    db: StateDB,
    logger: logging.Logger,
) -> tuple:
    """
    動画を処理すべきか判定する。
    戻り値: (should_process: bool, action: str)
      action = "skip_processed" / "dry_run" / "skip_no_notebook" / "process" / "skip_already"
    """
    vid_id = video["id"]

    if db.is_processed(channel.id, vid_id):
        return (False, "skip_already")

    if dry_run:
        return (False, "dry_run")

    if not channel.notebook_id:
        return (False, "skip_no_notebook")

    return (True, "process")


def _add_video_to_notebook(
    nb_client: NotebookLMClient,
    db: StateDB,
    channel: ChannelConfig,
    video: dict,
    delay_sec: int,
    logger: logging.Logger,
) -> tuple:
    """
    NotebookLMに動画を追加してstateを記録する。
    戻り値: (success: bool, reason: str)
    SessionExpiredError は呼び元に再送出する。
    """
    vid_id = video["id"]
    vid_url = video["url"]
    vid_title = video.get("title", "")
    vid_pub = video.get("published_at", "")

    try:
        success = nb_client.add_youtube_source(channel.notebook_id, vid_url)
    except SessionExpiredError:
        raise
    except Exception as exc:
        logger.error(
            "channel_id=%s video_id=%s result=error reason=unexpected detail=%s",
            channel.id, vid_id, exc,
        )
        return (False, str(exc))

    if not success:
        logger.warning(
            "channel_id=%s video_id=%s result=error reason=add_source_failed",
            channel.id, vid_id,
        )
        return (False, "add_youtube_source returned False")

    db.mark_processed(channel.id, vid_id, vid_title, vid_pub)
    logger.info(
        "channel_id=%s video_id=%s result=success title=%s",
        channel.id, vid_id, vid_title,
    )

    # 公開日付きタイトルにリネーム（NotebookLMが自動でタイトル取得する前にURLマッチで実行）
    if vid_pub and vid_title:
        new_title = f"[{vid_pub}] {vid_title}"
        try:
            renamed = nb_client.rename_source(channel.notebook_id, vid_url, new_title)
            if renamed:
                logger.info(
                    "channel_id=%s video_id=%s result=renamed new_title=%s",
                    channel.id, vid_id, new_title[:60],
                )
            else:
                logger.warning(
                    "channel_id=%s video_id=%s result=rename_skipped",
                    channel.id, vid_id,
                )
        except SessionExpiredError:
            raise
        except Exception as exc:
            logger.warning(
                "channel_id=%s video_id=%s result=rename_error detail=%s",
                channel.id, vid_id, exc,
            )

    time.sleep(delay_sec)
    return (True, "success")


def _process_channel(
    channel: ChannelConfig,
    videos: list,
    nb_client: NotebookLMClient,
    db: StateDB,
    delay_sec: int,
    dry_run: bool,
    logger: logging.Logger,
) -> dict:
    """
    1チャンネル分の動画を処理し、結果辞書を返す。
    SessionExpiredError は呼び元に再送出する。
    """
    result = {
        "name": channel.name,
        "channel_id": channel.id,
        "added": 0,
        "skipped": 0,
        "errors": [],
    }

    for video in videos:
        vid_id = video["id"]
        vid_url = video["url"]
        vid_title = video.get("title", "")

        should_process, action = _should_process_video(video, channel, dry_run, db, logger)

        if action == "skip_already":
            logger.info(
                "channel_id=%s video_id=%s result=skip title=%s",
                channel.id, vid_id, vid_title,
            )
            result["skipped"] += 1
            continue

        if action == "dry_run":
            logger.info(
                "channel_id=%s video_id=%s result=dry-run title=%s url=%s",
                channel.id, vid_id, vid_title, vid_url,
            )
            result["added"] += 1
            continue

        if action == "skip_no_notebook":
            logger.warning(
                "channel_id=%s video_id=%s result=skip reason=notebook_id_not_set",
                channel.id, vid_id,
            )
            result["skipped"] += 1
            continue

        success, reason = _add_video_to_notebook(
            nb_client, db, channel, video, delay_sec, logger
        )
        if success:
            result["added"] += 1
        else:
            result["errors"].append(f"{vid_id}: {reason}")

    return result


def _run_all_channels(
    channels: list,
    db: StateDB,
    nb_client: NotebookLMClient,
    cfg: AppConfig,
    args: argparse.Namespace,
    results: List[dict],
    logger: logging.Logger,
) -> None:
    """
    全チャンネルを順に処理して results に追記する。
    SessionExpiredError は呼び元に再送出する。
    その他の例外は1チャンネル分のスキップとして処理を継続する。
    """
    for channel in channels:
        logger.info("channel_id=%s name=%s processing start", channel.id, channel.name)

        try:
            videos = _fetch_videos(channel, args.init, cfg)
        except Exception as exc:
            logger.error(
                "channel_id=%s result=error reason=fetch_failed detail=%s",
                channel.id, exc,
            )
            send_alert(
                f"動画取得失敗: channel={channel.name} ({channel.id})",
                bot_token=cfg.telegram.bot_token,
                chat_id=cfg.telegram.chat_id,
                error=exc,
            )
            results.append({
                "name": channel.name,
                "channel_id": channel.id,
                "added": 0,
                "skipped": 0,
                "errors": [str(exc)],
            })
            continue

        logger.info("channel_id=%s fetched %d videos", channel.id, len(videos))

        try:
            result = _process_channel(
                channel=channel,
                videos=videos,
                nb_client=nb_client,
                db=db,
                delay_sec=cfg.sync.request_delay_sec,
                dry_run=args.dry_run,
                logger=logger,
            )
        except SessionExpiredError:
            raise

        results.append(result)
        logger.info(
            "channel_id=%s processing done. added=%d skipped=%d errors=%d",
            channel.id, result["added"], result["skipped"], len(result["errors"]),
        )


def main() -> None:
    args = _parse_args()

    cfg = load_config(config_path="config.yaml", secrets_path="secrets.yaml")
    _setup_logging(cfg)

    logger = logging.getLogger(__name__)
    logger.info(
        "sync start. mode=%s channel_filter=%s dry_run=%s",
        "init" if args.init else "diff",
        args.channel or "all",
        args.dry_run,
    )

    channels = cfg.channels
    if args.channel:
        channels = [ch for ch in channels if ch.id == args.channel]
        if not channels:
            logger.error("channel_id=%s not found in config.yaml", args.channel)
            sys.exit(1)

    all_results: List[dict] = []

    with StateDB() as db:
        with NotebookLMClient(
            cdp_endpoint=cfg.playwright.cdp_endpoint,
            user_data_dir=cfg.playwright.user_data_dir,
            headless=cfg.playwright.headless,
            navigation_timeout_ms=cfg.playwright.navigation_timeout_ms,
            source_add_timeout_ms=cfg.playwright.source_add_timeout_ms,
            notebooklm_url=cfg.playwright.notebooklm_url,
        ) as nb_client:
            try:
                _run_all_channels(channels, db, nb_client, cfg, args, all_results, logger)
            except SessionExpiredError as exc:
                logger.error("Google session expired: %s", exc)
                send_alert(
                    "Google session expired. Please re-login and re-upload .auth/ to VPS.",
                    bot_token=cfg.telegram.bot_token,
                    chat_id=cfg.telegram.chat_id,
                    error=exc,
                )
                sys.exit(1)

    send_summary(
        channel_results=all_results,
        bot_token=cfg.telegram.bot_token,
        chat_id=cfg.telegram.chat_id,
    )

    logger.info("sync complete.")


if __name__ == "__main__":
    main()
