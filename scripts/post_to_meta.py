#!/usr/bin/env python3
"""Post or dry-run Meta SNS posts.

Actual posting requires --publish-approved so a missing flag cannot accidentally
publish to an external account.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = ROOT / ".company" / "engineering" / "sns-credentials" / ".env"
DEFAULT_API_VERSION = "v25.0"
DEFAULT_REELS_UPLOAD_ATTEMPTS = 3

LIMITS = {
    "instagram": 2200,
    "instagram-reels": 2200,
    "threads": 500,
    "facebook": 63206,
}


def is_public_https_url(value: str | None) -> bool:
    return bool(value and value.startswith("https://"))


def is_url(value: str | None) -> bool:
    return bool(value and re.match(r"^https?://", value))


def load_env(path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def resolve_image(image_path: str | None, image_url: str | None) -> tuple[Path | None, str | None]:
    if image_url:
        return None, image_url
    if image_path and is_url(image_path):
        return None, image_path
    if image_path:
        return Path(image_path).expanduser(), None
    return None, None


def validate(platform: str, text: str, image_path: str | None = None, image_url: str | None = None,
             video_path: str | None = None) -> dict:
    blockers: list[str] = []
    warnings = ["dry-runのため実投稿しません"]
    limit = LIMITS[platform]
    resolved_image, resolved_image_url = resolve_image(image_path, image_url)

    if not text.strip():
        blockers.append("投稿本文が空です")

    if len(text) > limit:
        blockers.append(f"文字数上限を超えています ({len(text)}/{limit})")

    placeholders = sorted(set(re.findall(r"\{[A-Z0-9_]+\}", text)))
    if placeholders:
        blockers.append(f"未解決プレースホルダーがあります: {', '.join(placeholders)}")

    if resolved_image:
        if not resolved_image.exists():
            blockers.append(f"画像ファイルが見つかりません: {resolved_image}")

    if platform == "instagram":
        if not (resolved_image or resolved_image_url):
            blockers.append("Instagramは画像必須ですが --image または --image-url が未指定です")
        if resolved_image and not resolved_image_url:
            warnings.append("Instagram本番投稿では公開HTTPS画像URLが必要です")
        if resolved_image_url and not is_public_https_url(resolved_image_url):
            blockers.append("Instagramの画像URLは公開HTTPS URLである必要があります")

    resolved_video = Path(video_path).expanduser() if video_path else None
    if platform == "instagram-reels":
        if not resolved_video:
            blockers.append("Reels投稿には --video が必須です")
        elif not resolved_video.exists():
            blockers.append(f"動画ファイルが見つかりません: {resolved_video}")
        elif resolved_video.suffix.lower() != ".mp4":
            blockers.append("Reels動画はmp4のみ対応です")
        elif resolved_video.stat().st_size > 1024 * 1024 * 1024:
            blockers.append("Reels動画は1GB以下にしてください")

    return {
        "platform": platform,
        "mode": "dry-run",
        "status": "blocked" if blockers else "ready_for_review",
        "would_post": False,
        "tokens_read": False,
        "api_called": False,
        "text_length": len(text),
        "text_limit": limit,
        "has_image": bool(resolved_image or resolved_image_url),
        "image_path": str(resolved_image) if resolved_image else None,
        "image_url": resolved_image_url,
        "blockers": blockers,
        "warnings": warnings,
        "preview": text,
    }


def required(values: dict[str, str], *keys: str) -> dict[str, str]:
    missing = [key for key in keys if not values.get(key)]
    if missing:
        raise RuntimeError(f"Missing required Meta credential(s): {', '.join(missing)}")
    return {key: values[key] for key in keys}


def graph_post(path: str, token: str, data: dict[str, Any], files: dict[str, Any] | None = None) -> dict:
    import requests

    url = f"https://graph.facebook.com/{DEFAULT_API_VERSION}/{path.lstrip('/')}"
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


def graph_get(path: str, token: str, params: dict[str, Any] | None = None) -> dict:
    import requests

    url = f"https://graph.facebook.com/{DEFAULT_API_VERSION}/{path.lstrip('/')}"
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


def _compact_error(value: Any, limit: int = 500) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False)
    return text[:limit]


def _has_processing_failed(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_processing_failed(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_processing_failed(v) for v in value)
    return "ProcessingFailedError" in str(value)


def _reels_upload_attempts(env: dict[str, str]) -> int:
    try:
        return max(1, int(env.get("META_REELS_UPLOAD_ATTEMPTS", DEFAULT_REELS_UPLOAD_ATTEMPTS)))
    except ValueError:
        return DEFAULT_REELS_UPLOAD_ATTEMPTS


def _create_reels_container(ig_user_id: str, user_token: str, text: str) -> tuple[str, str]:
    container = graph_post(
        f"{ig_user_id}/media",
        user_token,
        {"media_type": "REELS", "upload_type": "resumable", "caption": text},
    )
    container_id = container.get("id")
    if not container_id:
        raise RuntimeError("Reels container id was not returned")
    upload_uri = container.get("uri") or (
        f"https://rupload.facebook.com/ig-api-upload/{DEFAULT_API_VERSION}/{container_id}"
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
    last_status: dict[str, Any] | None = None
    while time.time() < deadline:
        status = graph_get(container_id, user_token, {"fields": "status_code,status"})
        last_status = status
        status_code = status.get("status_code")
        if status_code == "FINISHED":
            return
        if status_code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Reels処理失敗: {_compact_error(status)}")
        time.sleep(5)
    raise RuntimeError(f"Reels処理がタイムアウトしました: {_compact_error(last_status)}")


def post_facebook(text: str, image_path: str | None, image_url: str | None, env: dict[str, str]) -> dict:
    creds = required(env, "META_PAGE_ID", "META_PAGE_ACCESS_TOKEN")
    page_id = creds["META_PAGE_ID"]
    page_token = creds["META_PAGE_ACCESS_TOKEN"]
    resolved_image, resolved_image_url = resolve_image(image_path, image_url)

    if resolved_image_url:
        result = graph_post(
            f"{page_id}/photos",
            page_token,
            {"url": resolved_image_url, "caption": text, "published": "true"},
        )
        post_id = result.get("post_id") or result.get("id")
        return {"platform": "facebook", "status": "posted", "id": post_id}

    if resolved_image:
        with resolved_image.open("rb") as image_file:
            result = graph_post(
                f"{page_id}/photos",
                page_token,
                {"caption": text, "published": "true"},
                files={"source": image_file},
            )
        post_id = result.get("post_id") or result.get("id")
        return {"platform": "facebook", "status": "posted", "id": post_id}

    result = graph_post(f"{page_id}/feed", page_token, {"message": text})
    return {"platform": "facebook", "status": "posted", "id": result.get("id")}


def post_instagram(text: str, image_path: str | None, image_url: str | None, env: dict[str, str]) -> dict:
    creds = required(env, "META_IG_USER_ID", "META_ACCESS_TOKEN")
    ig_user_id = creds["META_IG_USER_ID"]
    user_token = creds["META_ACCESS_TOKEN"]
    resolved_image, resolved_image_url = resolve_image(image_path, image_url)

    if resolved_image and not resolved_image_url:
        raise RuntimeError("Instagram本番投稿には公開HTTPS画像URLが必要です。--image-url を指定してください。")
    if not is_public_https_url(resolved_image_url):
        raise RuntimeError("Instagram本番投稿には公開HTTPS画像URLが必要です。")

    container = graph_post(
        f"{ig_user_id}/media",
        user_token,
        {"media_type": "IMAGE", "image_url": resolved_image_url, "caption": text},
    )
    creation_id = container.get("id")
    if not creation_id:
        raise RuntimeError("Instagram media container id was not returned")

    published = graph_post(f"{ig_user_id}/media_publish", user_token, {"creation_id": creation_id})
    media_id = published.get("id")
    permalink = None
    if media_id:
        try:
            permalink = graph_get(media_id, user_token, {"fields": "permalink"}).get("permalink")
        except RuntimeError:
            permalink = None

    return {
        "platform": "instagram",
        "status": "posted",
        "id": media_id,
        "permalink": permalink,
    }


def post_instagram_reels(text: str, video_path: str, env: dict[str, str]) -> dict:
    """Resumable Upload Protocol でローカル動画を直接 Reels 投稿する（公開URL不要）。"""
    creds = required(env, "META_IG_USER_ID", "META_ACCESS_TOKEN")
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

    published = graph_post(
        f"{ig_user_id}/media_publish", user_token, {"creation_id": container_id}
    )
    media_id = published.get("id")
    permalink = None
    if media_id:
        try:
            permalink = graph_get(media_id, user_token, {"fields": "permalink"}).get("permalink")
        except RuntimeError:
            permalink = None
    return {
        "platform": "instagram-reels",
        "status": "posted",
        "id": media_id,
        "permalink": permalink,
        "upload_attempts": len(errors) + 1,
    }


def post_actual(platform: str, text: str, image_path: str | None, image_url: str | None,
                video_path: str | None = None) -> dict:
    env = load_env()
    if platform == "facebook":
        return post_facebook(text, image_path, image_url, env)
    if platform == "instagram":
        return post_instagram(text, image_path, image_url, env)
    if platform == "instagram-reels":
        return post_instagram_reels(text, video_path, env)
    raise RuntimeError("Threads本番投稿は未実装です。Threads Tokenの別フロー確定後に対応します。")


def emit_json(result: dict, result_json: str | None = None) -> None:
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if result_json:
        path = Path(result_json).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text + "\n", encoding="utf-8")
    print(text, flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Meta SNS posting helper.")
    parser.add_argument("platform", choices=sorted(LIMITS), help="Target platform")
    parser.add_argument("text", help="Post text or caption")
    parser.add_argument("--image", help="Path to image file", default=None)
    parser.add_argument("--image-url", help="Public HTTPS image URL", default=None)
    parser.add_argument("--video", help="Path to mp4 video file (instagram-reels)", default=None)
    parser.add_argument("--result-json", help="Also write the JSON result to this path", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Validate without posting")
    parser.add_argument(
        "--publish-approved",
        action="store_true",
        help="Required for actual external posting after owner approval",
    )
    args = parser.parse_args()

    dry_run_result = validate(args.platform, args.text, args.image, args.image_url, args.video)

    if args.dry_run:
        emit_json(dry_run_result, args.result_json)
        return

    if not args.publish_approved:
        parser.error("Actual Meta posting requires --publish-approved after explicit owner approval.")

    if dry_run_result["blockers"]:
        emit_json(dry_run_result, args.result_json)
        sys.exit(2)

    try:
        result = post_actual(args.platform, args.text, args.image, args.image_url, args.video)
    except Exception as exc:
        emit_json(
            {
                "platform": args.platform,
                "mode": "actual",
                "status": "blocked",
                "api_called": False,
                "tokens_read": True,
                "error": str(exc),
                "error_type": type(exc).__name__,
            },
            args.result_json,
        )
        sys.exit(2)
    result.update(
        {
            "mode": "actual",
            "api_called": True,
            "tokens_read": True,
            "text_length": len(args.text),
        }
    )
    emit_json(result, args.result_json)


if __name__ == "__main__":
    main()
