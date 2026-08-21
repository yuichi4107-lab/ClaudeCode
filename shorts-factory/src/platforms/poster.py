"""各SNSへの投稿ディスパッチャ。

Drive File Provider の一時ロックで投稿が落ちないよう、動画とSNS認証情報は
runtime 側のローカルコピーを優先して使う。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from ..config import CONFIG
from .. import drive_guard
from ..fs_retry import retry_io
from ..logging_utils import redact_secrets
from ..platform_copy import copy_for_platform
from ..state_io import atomic_write_json, file_lock

INSTAGRAM_EXISTING_LOOKBACK = timedelta(minutes=30)


class PostingLedgerError(RuntimeError):
    pass


def posting_video_path(item: dict) -> Path:
    """Resolve upload media from local runtime storage only."""
    upload_path = (item.get("video") or {}).get("upload_path")
    if upload_path:
        path = Path(upload_path)
        drive_guard.assert_local(path, "video.upload_path")
        if path.exists():
            return path
    video_path = Path((item.get("video") or {}).get("local_path") or item["video"]["path"])
    drive_guard.assert_local(video_path, "video.local_path")
    output_dir = item.get("output_dir")
    if output_dir:
        runtime_path = CONFIG.work_dir / Path(output_dir).name / video_path.name
        if runtime_path.exists():
            return runtime_path
        archived_path = CONFIG.outputs_dir / Path(output_dir).name / video_path.name
        if archived_path.exists():
            return archived_path
    return video_path


def _ensure_upload_cache(item: dict) -> Path:
    """Materialize a stable local upload file and store it on the queue item."""
    src = posting_video_path(item)
    if not src.exists():
        raise FileNotFoundError(src)

    cache_dir = CONFIG.runtime_dir / "upload_cache" / item["id"]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / src.name

    def _copy_once() -> Path:
        if src.resolve() != cache_path.resolve():
            shutil.copy2(src, cache_path)
        if cache_path.stat().st_size <= 0:
            raise RuntimeError(f"upload cache is empty: {cache_path}")
        return cache_path

    path = retry_io(_copy_once, attempts=5, delay_sec=2.0)
    item.setdefault("video", {})["upload_path"] = str(path)
    return path


def _posting_ledger_path(item_id: str) -> Path:
    ledger_dir = CONFIG.runtime_dir / "posting_ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    return ledger_dir / f"{item_id}.json"


def _load_posting_ledger(item_id: str) -> dict:
    path = _posting_ledger_path(item_id)
    if not path.exists():
        return {"item_id": item_id, "platforms": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise PostingLedgerError(f"posting ledger unreadable: {path}") from exc


def _update_posting_ledger(item_id: str, mutator) -> dict:
    path = _posting_ledger_path(item_id)
    lock_path = CONFIG.runtime_dir / "posting_ledger" / "locks" / f"{item_id}.lock"
    with file_lock(lock_path):
        ledger = _load_posting_ledger(item_id)
        ledger["item_id"] = item_id
        mutator(ledger.setdefault("platforms", {}))
        atomic_write_json(path, ledger)
        return ledger


def _ledger_platform_entry(item_id: str, platform: str) -> dict:
    entry = (_load_posting_ledger(item_id).get("platforms") or {}).get(platform) or {}
    return dict(entry)


def _ledger_posted_url(item_id: str, platform: str) -> str | None:
    entry = _ledger_platform_entry(item_id, platform)
    if entry.get("status") == "posted" and entry.get("url"):
        return str(entry["url"])
    return None


def _record_ledger_posted(item_id: str, platform: str, url: str) -> None:
    def mutate(platforms: dict) -> None:
        platforms[platform] = {
            "status": "posted",
            "url": url,
            "posted_at": _now(),
        }

    _update_posting_ledger(item_id, mutate)


def _record_ledger_intent(item_id: str, platform: str) -> None:
    def mutate(platforms: dict) -> None:
        platforms[platform] = {
            "status": "attempting",
            "attempt_id": uuid.uuid4().hex,
            "started_at": _now(),
            "pid": os.getpid(),
        }

    _update_posting_ledger(item_id, mutate)


def _record_ledger_failure(
    item_id: str,
    platform: str,
    error: str,
    *,
    reconcile_required: bool,
) -> None:
    def mutate(platforms: dict) -> None:
        platforms[platform] = {
            "status": "reconcile_required" if reconcile_required else "failed",
            "error": error[:500],
            "failed_at": _now(),
        }

    _update_posting_ledger(item_id, mutate)


def _sns_env_cache_path() -> Path:
    return CONFIG.sns_env_path


def _parse_env_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _ensure_sns_env_cache() -> Path:
    """Validate the local-only SNS credential snapshot used by posting workers."""
    path = _sns_env_cache_path()
    if not path.exists():
        raise FileNotFoundError(
            f"SNS credential snapshot is missing: {path}. Run sync_runtime_credentials.py."
        )
    if not path.read_text(encoding="utf-8").strip():
        raise RuntimeError(f"SNS credential file is empty: {path}")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def _load_sns_env() -> dict[str, str]:
    path = _ensure_sns_env_cache()
    text = retry_io(lambda: path.read_text(encoding="utf-8"), attempts=3, delay_sec=1.0)
    return _parse_env_text(text)


def _required_env(env: dict[str, str], *keys: str) -> dict[str, str]:
    missing = [key for key in keys if not env.get(key)]
    if missing:
        raise RuntimeError(f"Missing required SNS credential(s): {', '.join(missing)}")
    return {key: env[key] for key in keys}


def _normalized_caption(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _parse_meta_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


def _post_x_direct(text: str, video_path: Path | None = None) -> str:
    import tweepy

    env = _load_sns_env()
    creds = _required_env(
        env,
        "X_API_KEY",
        "X_API_KEY_SECRET",
        "X_ACCESS_TOKEN",
        "X_ACCESS_TOKEN_SECRET",
    )
    client = tweepy.Client(
        consumer_key=creds["X_API_KEY"],
        consumer_secret=creds["X_API_KEY_SECRET"],
        access_token=creds["X_ACCESS_TOKEN"],
        access_token_secret=creds["X_ACCESS_TOKEN_SECRET"],
    )
    media_ids = None
    if video_path:
        auth = tweepy.OAuth1UserHandler(
            creds["X_API_KEY"],
            creds["X_API_KEY_SECRET"],
            creds["X_ACCESS_TOKEN"],
            creds["X_ACCESS_TOKEN_SECRET"],
        )
        api_v1 = tweepy.API(auth)
        media = api_v1.media_upload(
            filename=str(video_path),
            chunked=True,
            media_category="tweet_video",
        )
        deadline = time.time() + 300
        while time.time() < deadline:
            info = getattr(media, "processing_info", None)
            if not info or info.get("state") == "succeeded":
                media_ids = [media.media_id]
                break
            if info.get("state") == "failed":
                raise RuntimeError(f"X動画処理失敗: {info.get('error')}")
            time.sleep(info.get("check_after_secs", 5))
            media = api_v1.get_media_upload_status(media.media_id)
        if media_ids is None:
            raise TimeoutError("X動画処理がタイムアウトしました")

    response = client.create_tweet(text=text, media_ids=media_ids)
    tweet_id = response.data["id"]
    return f"https://x.com/i/status/{tweet_id}"


def _meta_graph_post(path: str, token: str, data: dict, files: dict | None = None) -> dict:
    import requests

    url = f"https://graph.facebook.com/v25.0/{path.lstrip('/')}"
    payload = dict(data)
    payload["access_token"] = token
    response = requests.post(url, data=payload, files=files, timeout=60)
    try:
        result = response.json()
    except ValueError:
        result = {"raw": response.text}
    if response.status_code >= 400 or "error" in result:
        error = result.get("error", result)
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(message)
    return result


def _meta_graph_get(path: str, token: str, params: dict | None = None) -> dict:
    import requests

    url = f"https://graph.facebook.com/v25.0/{path.lstrip('/')}"
    payload = dict(params or {})
    payload["access_token"] = token
    response = requests.get(url, params=payload, timeout=30)
    try:
        result = response.json()
    except ValueError:
        result = {"raw": response.text}
    if response.status_code >= 400 or "error" in result:
        error = result.get("error", result)
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(message)
    return result


def _compact_error(value, limit: int = 500) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    return text[:limit]


def _has_processing_failed(value) -> bool:
    if isinstance(value, dict):
        return any(_has_processing_failed(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_processing_failed(v) for v in value)
    return "ProcessingFailedError" in str(value)


def _reels_upload_attempts(env: dict[str, str]) -> int:
    try:
        return max(1, int(env.get("META_REELS_UPLOAD_ATTEMPTS", 3)))
    except ValueError:
        return 3


def _create_reels_container(ig_user_id: str, user_token: str, text: str) -> tuple[str, str]:
    container = _meta_graph_post(
        f"{ig_user_id}/media",
        user_token,
        {"media_type": "REELS", "upload_type": "resumable", "caption": text},
    )
    container_id = container.get("id")
    if not container_id:
        raise RuntimeError("Reels container id was not returned")
    upload_uri = container.get("uri") or (
        f"https://rupload.facebook.com/ig-api-upload/v25.0/{container_id}"
    )
    return container_id, upload_uri


def _upload_reels_binary(upload_uri: str, user_token: str, video: Path) -> dict:
    import requests

    size = video.stat().st_size
    with video.open("rb") as f:
        resp = requests.post(
            upload_uri,
            headers={
                "Authorization": f"OAuth {user_token}",
                "Content-Type": "video/mp4",
                "offset": "0",
                "file_size": str(size),
            },
            data=f,
            timeout=900,
        )
    try:
        result = resp.json()
    except ValueError:
        result = {"raw": resp.text}
    if resp.status_code >= 400 or not result.get("success", True):
        raise RuntimeError(f"Reels動画アップロード失敗: {_compact_error(result)}")
    return result


def _wait_reels_finished(container_id: str, user_token: str, timeout_sec: int = 600) -> None:
    deadline = time.time() + timeout_sec
    last_status: dict | None = None
    while time.time() < deadline:
        status = _meta_graph_get(container_id, user_token, {"fields": "status_code,status"})
        last_status = status
        status_code = status.get("status_code")
        if status_code == "FINISHED":
            return
        if status_code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Reels処理失敗: {_compact_error(status)}")
        time.sleep(5)
    raise RuntimeError(f"Reels処理がタイムアウトしました: {_compact_error(last_status)}")


def _post_instagram_reels(text: str, video_path: Path, env: dict[str, str]) -> dict:
    creds = _required_env(env, "META_IG_USER_ID", "META_ACCESS_TOKEN")
    ig_user_id = creds["META_IG_USER_ID"]
    user_token = creds["META_ACCESS_TOKEN"]
    video = Path(video_path).expanduser()
    if not video.exists():
        raise RuntimeError(f"動画ファイルが見つかりません: {video}")

    errors: list[str] = []
    container_id = ""
    for attempt in range(1, _reels_upload_attempts(env) + 1):
        try:
            container_id, upload_uri = _create_reels_container(ig_user_id, user_token, text)
            _upload_reels_binary(upload_uri, user_token, video)
            _wait_reels_finished(container_id, user_token)
            break
        except RuntimeError as exc:
            message = str(exc)
            errors.append(f"attempt {attempt}: {message}")
            if attempt >= _reels_upload_attempts(env):
                raise RuntimeError(" / ".join(errors)) from exc
            sleep_sec = 10 * attempt if _has_processing_failed(message) else 5 * attempt
            time.sleep(sleep_sec)

    published = _meta_graph_post(
        f"{ig_user_id}/media_publish",
        user_token,
        {"creation_id": container_id},
    )
    media_id = published.get("id")
    permalink = None
    if media_id:
        try:
            permalink = _meta_graph_get(media_id, user_token, {"fields": "permalink"}).get("permalink")
        except RuntimeError:
            permalink = None
    return {
        "platform": "instagram-reels",
        "status": "posted",
        "id": media_id,
        "permalink": permalink,
        "upload_attempts": len(errors) + 1,
    }


def _find_recent_instagram_post(caption: str, since: datetime) -> str | None:
    """Return an existing permalink for the same caption to avoid duplicate retries."""
    env = _load_sns_env()
    ig_user_id = env.get("META_IG_USER_ID")
    token = env.get("META_ACCESS_TOKEN")
    if not ig_user_id or not token:
        return None

    target = _normalized_caption(caption)
    if not target:
        return None
    response = _meta_graph_get(
        f"{ig_user_id}/media",
        token,
        {"fields": "id,permalink,caption,timestamp,media_type", "limit": 25},
    )
    for media in response.get("data", []):
        timestamp = _parse_meta_timestamp(media.get("timestamp"))
        if timestamp and timestamp < since:
            continue
        media_caption = _normalized_caption(media.get("caption"))
        if media_caption == target:
            return media.get("permalink") or f"media_id:{media.get('id')}"
    return None


def post_x(item: dict) -> str:
    """Xへ動画投稿し、投稿URLを返す。"""
    text = copy_for_platform(item, "x")["text"]
    return _post_x_direct(text, posting_video_path(item))


def post_instagram(item: dict) -> str:
    """Instagram Reels へ投稿し、permalink を返す。

    --publish-approved は Telegram承認（または auto_post 設定）を経た
    キューからのみ呼ばれるため、オーナー承認済みとして付与する。
    """
    caption = copy_for_platform(item, "instagram")["caption"]
    now = datetime.now().astimezone()
    existing = _find_recent_instagram_post(caption, now - INSTAGRAM_EXISTING_LOOKBACK)
    if existing:
        return existing

    result = _post_instagram_reels(
        caption,
        posting_video_path(item),
        _load_sns_env(),
    )
    if result.get("status") != "posted":
        raise RuntimeError(f"IG Reels投稿失敗: {result.get('error', result)}")
    return result.get("permalink") or f"media_id:{result.get('id')}"


def post_youtube(item: dict) -> str:
    """YouTube Shorts へCDP経由でアップロードし、動画URLを返す。"""
    from . import youtube_cdp

    copy = copy_for_platform(item, "youtube")
    return youtube_cdp.upload(
        video_path=posting_video_path(item),
        title=copy["title"],
        description=copy["description"],
    )


def post_tiktok(item: dict) -> str:
    from . import tiktok_cdp

    caption = copy_for_platform(item, "tiktok")["caption"]
    return tiktok_cdp.upload(posting_video_path(item), caption)


POSTERS = {
    "x": post_x,
    "instagram": post_instagram,
    "youtube": post_youtube,
    "tiktok": post_tiktok,
}
POST_ORDER = ("x", "instagram", "tiktok", "youtube")


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _as_bool(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off"}
    return bool(value)


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _retry_settings() -> tuple[int, float]:
    enabled = _as_bool(CONFIG.get("queue", "retry_failed_posts", default=True))
    if not enabled:
        return 0, 0.0
    attempts = _as_int(CONFIG.get("queue", "retry_max_attempts", default=2), 2)
    delay_sec = _as_float(CONFIG.get("queue", "retry_delay_sec", default=60), 60.0)
    return max(0, attempts), max(0.0, delay_sec)


def _recovery_settings() -> tuple[bool, int, int, int]:
    enabled = _as_bool(CONFIG.get("queue", "auto_recover_failed_posts", default=True))
    after_retries = _as_int(CONFIG.get("queue", "recovery_after_retries", default=2), 2)
    retry_attempts = _as_int(CONFIG.get("queue", "recovery_retry_attempts", default=1), 1)
    max_attempts = _as_int(
        CONFIG.get("queue", "recovery_max_attempts_per_platform", default=2), 2
    )
    return enabled, max(0, after_retries), max(0, retry_attempts), max(1, max_attempts)


def _pending_platforms(platforms: dict, ordered_platforms: list[str]) -> list[str]:
    return [
        platform
        for platform in ordered_platforms
        if platforms[platform].get("enabled")
        and platforms[platform].get("status") != "posted"
        and not platforms[platform].get("non_retryable")
    ]


def _non_retryable_error(platform: str, error: str) -> bool:
    if platform == "tiktok":
        return "セッション失効" in error or "ログイン" in error
    if platform == "youtube":
        return "セッション失効" in error or "ログイン" in error
    return False


def diagnose_posting_error(platform: str, error: str | None) -> str:
    text = (error or "").lower()
    if platform in {"x", "instagram"} and any(
        marker in text
        for marker in (
            "dotenv",
            "sns-credentials",
            "credential",
            "x_api_key",
            "meta_access_token",
            ".env",
        )
    ):
        return "credential_io"
    if any(marker in text for marker in ("connection aborted", "timed out", "read timed out")):
        return "network_transient"
    if any(
        marker in text
        for marker in (
            "resource deadlock",
            "読み取れません",
            "read",
            "file not found",
            "no such file",
            "not found",
        )
    ):
        return "media_io"
    if any(marker in text for marker in ("セッション失効", "ログイン", "login", "accounts.google.com")):
        return "session_expired"
    if any(
        marker in text
        for marker in (
            "timeout",
            "waiting for selector",
            "waiting for locator",
            "locator.evaluate",
            "投稿ボタンが有効",
            "upload_stuck",
        )
    ):
        return "browser_ui_stuck" if platform in {"youtube", "tiktok"} else "timeout"
    return "unknown"


def _submission_result_is_uncertain(platform: str, error: str | None) -> bool:
    """Return True when a failure may have happened after the public submit."""
    return diagnose_posting_error(platform, error) in {
        "network_transient",
        "timeout",
        "browser_ui_stuck",
        "unknown",
    }


def _block_for_ledger_reconciliation(item: dict, queue_lib, platform: str, entry: dict) -> dict:
    ledger_status = entry.get("status") or "unknown"
    error = (
        "投稿結果を安全に判定できないため自動再投稿を停止しました。"
        f" posting_ledger={ledger_status}。公開状態を照合してください。"
    )
    item = queue_lib.mark_platform(item, platform, "failed", error=error)
    info = item["platforms"][platform]
    info["non_retryable"] = True
    info["reconcile_required"] = True
    info["ledger_status"] = ledger_status
    if hasattr(queue_lib, "save_item"):
        queue_lib.save_item(item)
    return item


def _check_browser_session(platform: str) -> tuple[bool, str]:
    try:
        if platform == "youtube":
            from . import youtube_cdp

            return bool(youtube_cdp.check_session()), "youtube_session_check"
        if platform == "tiktok":
            from . import tiktok_cdp

            return bool(tiktok_cdp.check_session()), "tiktok_session_check"
    except Exception as exc:
        return False, f"browser_session_error:{redact_secrets(exc)[:160]}"
    return True, "not_browser_platform"


def _recovery_state(item: dict, platform: str) -> dict:
    recovery = item.setdefault("recovery", {}).setdefault("platforms", {})
    return recovery.setdefault(platform, {})


def _recovery_attempts(item: dict, platform: str) -> int:
    return _as_int(_recovery_state(item, platform).get("attempts"), 0)


def _needs_auto_recovery(
    item: dict,
    platforms: list[str],
    *,
    after_retries: int,
    max_attempts: int,
) -> list[str]:
    threshold = after_retries + 1  # initial attempt + retry count
    out = []
    for platform in platforms:
        info = item.get("platforms", {}).get(platform, {})
        if int(info.get("attempts") or 0) < threshold:
            continue
        if _recovery_attempts(item, platform) >= max_attempts:
            continue
        out.append(platform)
    return out


def recover_failed_platforms(item: dict, platforms: list[str], queue_lib) -> list[dict]:
    """Diagnose failed platforms and apply safe local recovery actions."""
    reports: list[dict] = []
    upload_cache_path: Path | None = None

    for platform in platforms:
        info = item.get("platforms", {}).get(platform, {})
        error = info.get("error")
        cause = diagnose_posting_error(platform, error)
        actions: list[str] = []
        recovered = False

        try:
            if cause in {"media_io", "browser_ui_stuck", "timeout", "network_transient", "unknown"}:
                if upload_cache_path is None:
                    upload_cache_path = _ensure_upload_cache(item)
                actions.append(f"local_media:{upload_cache_path}")
                recovered = True
        except Exception as exc:
            actions.append(f"local_media_failed:{redact_secrets(exc)[:160]}")

        if platform in {"x", "instagram"} and cause in {
            "credential_io",
            "media_io",
            "timeout",
            "network_transient",
            "unknown",
        }:
            try:
                env_cache_path = _ensure_sns_env_cache()
                actions.append(f"local_credentials:{env_cache_path}")
                recovered = True
            except Exception as exc:
                actions.append(f"local_credentials_failed:{redact_secrets(exc)[:160]}")

        if platform in {"youtube", "tiktok"} and cause in {
            "browser_ui_stuck",
            "session_expired",
            "timeout",
            "unknown",
        }:
            ready, detail = _check_browser_session(platform)
            actions.append(f"{detail}:{'ready' if ready else 'not_ready'}")
            if ready:
                recovered = True
            elif cause == "session_expired":
                info["non_retryable"] = True

        if cause == "network_transient":
            time.sleep(5)
            actions.append("network_cooldown:5s")
            recovered = True

        state = _recovery_state(item, platform)
        state["attempts"] = _as_int(state.get("attempts"), 0) + 1
        state["last_attempt_at"] = _now()
        state["cause"] = cause
        state["actions"] = actions
        state["recovered"] = recovered
        reports.append(
            {
                "platform": platform,
                "cause": cause,
                "actions": actions,
                "recovered": recovered,
            }
        )

    item.setdefault("history", []).append(
        {
            "ts": _now(),
            "event": "自動原因確認・復旧: "
            + "; ".join(
                f"{r['platform']}={r['cause']}:{'ok' if r['recovered'] else 'ng'}"
                for r in reports
            ),
        }
    )
    if hasattr(queue_lib, "save_item"):
        queue_lib.save_item(item)
    return reports


def _format_recovery_reports(reports: list[dict]) -> str:
    parts = []
    for report in reports:
        status = "復旧処理済み" if report["recovered"] else "要確認"
        parts.append(f"{report['platform']}={report['cause']}({status})")
    return "🛠 自動原因確認: " + " / ".join(parts)


def _record_attempt(item: dict, queue_lib, platform: str, retry_round: int) -> None:
    info = item["platforms"][platform]
    now = _now()
    info["attempts"] = int(info.get("attempts") or 0) + 1
    info["last_attempt_at"] = now
    if retry_round:
        info["last_retry_at"] = now
        info["last_retry_round"] = retry_round
    if hasattr(queue_lib, "save_item"):
        queue_lib.save_item(item)


def post_item(
    item: dict,
    queue_lib,
    notify,
    retry_attempts: int | None = None,
    retry_delay_sec: float | None = None,
) -> dict:
    """有効な全プラットフォームへ投稿し、結果を item に記録して返す。"""
    results = []
    platforms = item.get("platforms", {})
    ordered_platforms = [p for p in POST_ORDER if p in platforms]
    ordered_platforms.extend(p for p in platforms if p not in ordered_platforms)

    configured_retry_attempts, configured_retry_delay_sec = _retry_settings()
    if retry_attempts is None:
        retry_attempts = configured_retry_attempts
    if retry_delay_sec is None:
        retry_delay_sec = configured_retry_delay_sec
    (
        recovery_enabled,
        recovery_after_retries,
        recovery_retry_attempts,
        recovery_max_attempts,
    ) = _recovery_settings()
    recovered_this_run: set[str] = set()

    def _maybe_recover_failed(pending: list[str], retry_round: int, *, allow_extra_retry: bool) -> None:
        nonlocal retry_attempts
        if not recovery_enabled or not pending:
            return
        targets = [
            platform
            for platform in _needs_auto_recovery(
                item,
                pending,
                after_retries=recovery_after_retries,
                max_attempts=recovery_max_attempts,
            )
            if platform not in recovered_this_run
        ]
        if not targets:
            return
        reports = recover_failed_platforms(item, targets, queue_lib)
        recovered_this_run.update(targets)
        results.append(_format_recovery_reports(reports))
        if allow_extra_retry and recovery_retry_attempts:
            retry_attempts = max(retry_attempts, retry_round + recovery_retry_attempts)

    retry_round = 0
    while retry_round <= retry_attempts:
        pending = _pending_platforms(platforms, ordered_platforms)
        if not pending:
            break
        _maybe_recover_failed(pending, retry_round, allow_extra_retry=False)
        pending = _pending_platforms(platforms, ordered_platforms)
        if not pending:
            break
        if retry_round:
            results.append(f"🔁 自動再投稿 {retry_round}/{retry_attempts}: {', '.join(pending)}")
            if retry_delay_sec:
                time.sleep(retry_delay_sec)
        for platform in pending:
            ledger_entry = _ledger_platform_entry(item["id"], platform)
            ledger_url = (
                str(ledger_entry["url"])
                if ledger_entry.get("status") == "posted" and ledger_entry.get("url")
                else None
            )
            if ledger_url is not None:
                item = queue_lib.mark_platform(item, platform, "posted", url=ledger_url)
                results.append(f"↩️ {platform}: 既存投稿を台帳から復元 {ledger_url}")
                continue
            if ledger_entry.get("status") in {"attempting", "reconcile_required", "posted"}:
                item = _block_for_ledger_reconciliation(
                    item, queue_lib, platform, ledger_entry
                )
                results.append(f"⚠️ {platform}: 投稿結果の照合待ち（自動再投稿停止）")
                continue
            external_call_started = False
            ledger_posted = False
            try:
                _record_attempt(item, queue_lib, platform, retry_round)
                # Persist intent before any external submit. If the worker dies after
                # this point, the next worker must reconcile instead of posting twice.
                _record_ledger_intent(item["id"], platform)
                external_call_started = True
                url = POSTERS[platform](item)
                _record_ledger_posted(item["id"], platform, url)
                ledger_posted = True
                item = queue_lib.mark_platform(item, platform, "posted", url=url)
                results.append(f"✅ {platform}: {url}")
            except Exception as e:  # 1媒体の失敗で他媒体を止めない
                if ledger_posted:
                    # The public post and durable ledger are already committed.
                    # Abort so the next worker restores queue state from the ledger.
                    raise
                err = redact_secrets(e)
                reconcile_required = external_call_started and _submission_result_is_uncertain(
                    platform, err
                )
                try:
                    _record_ledger_failure(
                        item["id"],
                        platform,
                        err,
                        reconcile_required=reconcile_required,
                    )
                except Exception as ledger_exc:  # keep the persisted intent fail-closed
                    results.append(
                        f"⚠️ {platform}: 台帳更新失敗 {redact_secrets(ledger_exc)[:120]}"
                    )
                item = queue_lib.mark_platform(item, platform, "failed", error=err)
                if reconcile_required:
                    info = item["platforms"][platform]
                    info["non_retryable"] = True
                    info["reconcile_required"] = True
                    info["ledger_status"] = "reconcile_required"
                    item.setdefault("history", []).append(
                        {
                            "ts": _now(),
                            "event": f"{platform}: 投稿結果不明のため自動再投稿停止",
                        }
                    )
                    if hasattr(queue_lib, "save_item"):
                        queue_lib.save_item(item)
                elif _non_retryable_error(platform, err):
                    item["platforms"][platform]["non_retryable"] = True
                    if hasattr(queue_lib, "save_item"):
                        queue_lib.save_item(item)
                if reconcile_required:
                    results.append(f"⚠️ {platform}: 結果不明のため要照合 {err[:120]}")
                else:
                    results.append(f"❌ {platform}: {err[:120]}")
        _maybe_recover_failed(
            _pending_platforms(platforms, ordered_platforms),
            retry_round,
            allow_extra_retry=True,
        )
        retry_round += 1

    statuses = [v["status"] for v in item["platforms"].values() if v.get("enabled")]
    if statuses and all(s == "posted" for s in statuses):
        item = queue_lib.transition(item, "posted", "全媒体投稿完了")
    elif any(s == "posted" for s in statuses):
        item = queue_lib.transition(item, "partial_failed", "一部媒体のみ投稿成功。失敗媒体は再試行待ち")
    else:
        item = queue_lib.transition(item, "failed", "全媒体投稿失敗")

    extra = ""
    if item["status"] in {"failed", "partial_failed"}:
        reconcile_platforms = [
            name
            for name, info in item.get("platforms", {}).items()
            if info.get("enabled") and info.get("reconcile_required")
        ]
        if reconcile_platforms:
            extra = (
                "\n\n⚠️ 自動再投稿停止: 公開状態の照合が必要です: "
                + ", ".join(reconcile_platforms)
            )
        else:
            retry_note = ""
            if retry_attempts:
                retry_note = f"\n\n自動再投稿: 最大{retry_attempts}回まで実行済み"
            extra = (
                retry_note
                + "\n\n手動再試行: "
                + f"<code>python3 shorts-factory/scripts/retry_failed_posts.py {item['id']} --execute</code>"
            )
    notify.send_message(
        f"📤 <b>{item['title']}</b> 投稿結果\n" + "\n".join(results) + extra
    )
    return item
