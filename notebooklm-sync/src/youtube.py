"""
YouTube動画情報の取得ラッパ。
- 全動画: yt-dlp（初回--init用）
- 差分: feedparser（RSS最大15件、通常実行用）
リトライロジックを内蔵し、最終失敗時は例外を再送出する。
"""
from __future__ import annotations

import logging
import re
import time
from typing import List

import feedparser
import requests
import yt_dlp

_HTML_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "ja,en;q=0.9",
}

_RE_UPLOAD_DATE = re.compile(r'"uploadDate":"([\d\-T:+Z]{10,})"')
_RE_TITLE = re.compile(r'"title":"([^"\\]+(?:\\.[^"\\]*)*)"\s*,\s*"lengthSeconds"')

logger = logging.getLogger(__name__)

# YouTube RSS フィードのURLテンプレート
_RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def _build_video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def normalize_published_date(raw: str) -> str:
    """公開日をYYYY-MM-DD形式に正規化する。
    yt-dlpは upload_date=YYYYMMDD、feedparserは published=ISO8601 のため両方対応。
    空文字や解釈不能な値はそのまま返す。"""
    if not raw:
        return ""
    s = raw.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    return s


def list_all_videos(
    channel_id: str,
    retry_count: int = 3,
    retry_backoff_sec: int = 5,
    max_videos: int = 0,
) -> List[dict]:
    """
    yt-dlp でチャンネルの全動画を取得する。
    max_videos=0 のとき上限なし。
    戻り値: [{"id", "title", "url", "published_at"}, ...]
    """
    channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"
    ydl_opts = {
        "quiet": True,
        "extract_flat": True,
        "skip_download": True,
        "playlistend": max_videos if max_videos > 0 else None,
    }

    last_exc: Exception | None = None
    for attempt in range(1, retry_count + 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(channel_url, download=False)
            entries = info.get("entries") or []
            videos = []
            for entry in entries:
                vid_id = entry.get("id") or entry.get("url", "").split("v=")[-1]
                if not vid_id:
                    continue
                videos.append({
                    "id": vid_id,
                    "title": entry.get("title", ""),
                    "url": _build_video_url(vid_id),
                    "published_at": normalize_published_date(entry.get("upload_date", "")),
                })
            logger.info(
                "channel_id=%s yt-dlp: %d videos fetched (attempt %d)",
                channel_id, len(videos), attempt,
            )
            return videos
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "channel_id=%s yt-dlp attempt %d/%d failed: %s",
                channel_id, attempt, retry_count, exc,
            )
            if attempt < retry_count:
                time.sleep(retry_backoff_sec)

    raise RuntimeError(
        f"list_all_videos failed for channel {channel_id} after {retry_count} attempts"
    ) from last_exc


def get_video_details(
    video_id: str,
    retry_count: int = 3,
    retry_backoff_sec: int = 3,
) -> dict:
    """単一動画の詳細を YouTube HTMLから直接取得する。
    yt-dlpはVPSのIPがbot判定されることがあるため、シンプルなHTTP取得+正規表現で実装。
    戻り値: {"id", "title", "url", "published_at"} - 失敗時は published_at="" のまま返す。"""
    url = _build_video_url(video_id)
    last_exc: Exception | None = None
    for attempt in range(1, retry_count + 1):
        try:
            r = requests.get(url, headers=_HTML_HEADERS, timeout=15)
            r.raise_for_status()
            html = r.text
            date_m = _RE_UPLOAD_DATE.search(html)
            title_m = _RE_TITLE.search(html)
            pub = normalize_published_date(date_m.group(1)) if date_m else ""
            title = title_m.group(1).encode("utf-8").decode("unicode_escape") if title_m else ""
            return {
                "id": video_id,
                "title": title,
                "url": url,
                "published_at": pub,
            }
        except Exception as exc:
            last_exc = exc
            if attempt < retry_count:
                time.sleep(retry_backoff_sec)
                continue
    logger.warning("get_video_details failed for %s: %s", video_id, last_exc)
    return {"id": video_id, "title": "", "url": url, "published_at": ""}


def list_recent_videos(
    channel_id: str,
    max_entries: int = 15,
    retry_count: int = 3,
    retry_backoff_sec: int = 5,
) -> List[dict]:
    """
    feedparser でRSSフィードから最新動画を取得する（最大15件）。
    15件を超える投稿ペースのチャンネルでは取りこぼしが起きうるため、
    その場合は list_all_videos へのフォールバックを呼び元で検討する。
    """
    rss_url = _RSS_URL_TEMPLATE.format(channel_id=channel_id)

    last_exc: Exception | None = None
    for attempt in range(1, retry_count + 1):
        try:
            # feedparser 既定の User-Agent は YouTube に bot 判定され、
            # RSS エンドポイントが 404/500 の HTML エラーページを返すことがある。
            # ブラウザ相当の UA / Accept を明示して成功率を上げる。
            feed = feedparser.parse(
                rss_url,
                agent=_HTML_HEADERS["User-Agent"],
                request_headers={
                    "Accept": "application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": _HTML_HEADERS["Accept-Language"],
                },
            )
            # feedparserはネットワークエラーでも例外を投げないため bozo フラグを確認する
            if feed.bozo and not feed.entries:
                raise RuntimeError(f"feedparser bozo error: {feed.bozo_exception}")

            videos = []
            for entry in feed.entries[:max_entries]:
                vid_id = entry.get("yt_videoid") or ""
                if not vid_id:
                    # id フィールドがURLの場合がある
                    raw_id = entry.get("id", "")
                    if "watch?v=" in raw_id:
                        vid_id = raw_id.split("watch?v=")[-1]
                if not vid_id:
                    continue
                videos.append({
                    "id": vid_id,
                    "title": entry.get("title", ""),
                    "url": _build_video_url(vid_id),
                    "published_at": normalize_published_date(entry.get("published", "")),
                })
            logger.info(
                "channel_id=%s RSS: %d videos fetched (attempt %d)",
                channel_id, len(videos), attempt,
            )
            return videos
        except Exception as exc:
            last_exc = exc
            logger.warning(
                "channel_id=%s RSS attempt %d/%d failed: %s",
                channel_id, attempt, retry_count, exc,
            )
            if attempt < retry_count:
                time.sleep(retry_backoff_sec)

    # RSS が全リトライ失敗（YouTube 側の断続的な 404/500 が主因）。
    # yt-dlp は内部 API を使うため RSS のように弾かれにくい。最後の砦として委譲する。
    logger.warning(
        "channel_id=%s RSS failed after %d attempts; falling back to yt-dlp",
        channel_id, retry_count,
    )
    try:
        videos = list_all_videos(
            channel_id=channel_id,
            retry_count=retry_count,
            retry_backoff_sec=retry_backoff_sec,
            max_videos=max_entries,
        )
        logger.info(
            "channel_id=%s yt-dlp fallback: %d videos fetched",
            channel_id, len(videos),
        )
        return videos
    except Exception as exc:
        raise RuntimeError(
            f"list_recent_videos failed for channel {channel_id}: "
            f"RSS after {retry_count} attempts and yt-dlp fallback both failed"
        ) from exc
