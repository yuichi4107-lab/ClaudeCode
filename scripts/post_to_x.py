#!/usr/bin/env python3
"""Small, approval-gated adapter for posting to X.

Importing this module and running :func:`dry_run` are deliberately offline:
they do not read credentials, import Tweepy, or call X.  Credential loading is
deferred until a live adapter function is called.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS_FILE_ENV = "YNFACTORY_SNS_CREDENTIALS_FILE"
DEFAULT_ENV_PATH = Path.home() / ".ynfactory" / "credentials" / "sns-x.env"
TEXT_LIMIT = 280
URL_WEIGHT = 23
X_CREDENTIAL_KEYS = (
    "X_API_KEY",
    "X_API_KEY_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
)
READBACK_FIELDS = (
    "author_id",
    "conversation_id",
    "created_at",
    "entities",
    "referenced_tweets",
)

# X counts every HTTP(S) URL as its t.co length.  Trailing sentence
# punctuation is removed below and counted as ordinary text.
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ".,!?;:\u3001\u3002\uff01\uff1f\uff1b\uff1a\u201d\u2019\u00bb"
PLACEHOLDER_PATTERNS = (
    re.compile(r"\[\s*[A-Z][A-Z0-9_]*\s*\]"),
    re.compile(r"\{\{?\s*[A-Z][A-Z0-9_]*\s*\}?\}"),
    re.compile(r"\$\{\s*[A-Z][A-Z0-9_]*\s*\}"),
    re.compile(r"<\s*[A-Z][A-Z0-9_]*\s*>"),
)


def _character_weight(character: str) -> int:
    """Return X's configured weight for a non-URL Unicode code point."""
    codepoint = ord(character)
    if (
        0x0000 <= codepoint <= 0x10FF
        or 0x2000 <= codepoint <= 0x200D
        or 0x2010 <= codepoint <= 0x201F
        or 0x2032 <= codepoint <= 0x2037
    ):
        return 1
    return 2


def _plain_text_weight(text: str) -> int:
    return sum(_character_weight(character) for character in text)


def _trim_url(candidate: str) -> str:
    """Exclude punctuation that belongs to the sentence after a URL."""
    while candidate and candidate[-1] in TRAILING_URL_PUNCTUATION:
        candidate = candidate[:-1]

    # Keep balanced closing delimiters that are part of a URL, but trim a
    # closing delimiter with no matching opener (the usual prose case).
    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}")):
        while candidate.endswith(closer) and candidate.count(closer) > candidate.count(opener):
            candidate = candidate[:-1]
    return candidate


def weighted_length(text: str) -> int:
    """Calculate X weighted length (Japanese=2, configured Latin=1, URL=23)."""
    total = 0
    cursor = 0
    for match in URL_RE.finditer(text):
        candidate = match.group(0)
        url = _trim_url(candidate)
        if not url:
            continue
        url_end = match.start() + len(url)
        total += _plain_text_weight(text[cursor:match.start()])
        total += URL_WEIGHT
        cursor = url_end
    total += _plain_text_weight(text[cursor:])
    return total


def unresolved_placeholders(text: str) -> list[str]:
    """Return unresolved template tokens, including the required [NOTE_URL]."""
    placeholders: set[str] = set()
    for pattern in PLACEHOLDER_PATTERNS:
        placeholders.update(match.group(0) for match in pattern.finditer(text))
    return sorted(placeholders)


def _text_blockers(text: str) -> list[str]:
    blockers: list[str] = []
    if not text.strip():
        blockers.append("投稿本文が空です")

    length = weighted_length(text)
    if length > TEXT_LIMIT:
        blockers.append(f"Xのウェイト上限を超えています ({length}/{TEXT_LIMIT})")

    placeholders = unresolved_placeholders(text)
    if placeholders:
        blockers.append(
            f"未解決プレースホルダーがあります: {', '.join(placeholders)}"
        )
    return blockers


def _reply_blockers(in_reply_to_tweet_id: str | None) -> list[str]:
    if in_reply_to_tweet_id is None:
        return []
    if not str(in_reply_to_tweet_id).isdigit():
        return ["--reply-to には数字のTweet IDを指定してください"]
    return []


def dry_run(
    text: str,
    image_path: str | None = None,
    video_path: str | None = None,
    in_reply_to_tweet_id: str | None = None,
) -> dict[str, Any]:
    """Validate a prospective post without reading env files or calling X."""
    blockers = _text_blockers(text) + _reply_blockers(in_reply_to_tweet_id)
    warnings = ["dry-runのため実投稿しません"]

    resolved_image = Path(image_path).expanduser() if image_path else None
    if resolved_image and not resolved_image.exists():
        blockers.append(f"画像ファイルが見つかりません: {resolved_image}")

    resolved_video = Path(video_path).expanduser() if video_path else None
    if resolved_video:
        if not resolved_video.exists():
            blockers.append(f"動画ファイルが見つかりません: {resolved_video}")
        elif resolved_video.suffix.lower() != ".mp4":
            blockers.append("動画はmp4のみ対応です")
        elif resolved_video.stat().st_size > 512 * 1024 * 1024:
            blockers.append("動画サイズが512MBを超えています")
        if resolved_image:
            warnings.append("--image と --video の同時指定は動画を優先します")

    length = weighted_length(text)
    return {
        "platform": "x",
        "mode": "dry-run",
        "status": "blocked" if blockers else "ready_for_review",
        "would_post": False,
        "tokens_read": False,
        "api_called": False,
        "character_count": len(text),
        "text_length": length,
        "weighted_length": length,
        "text_limit": TEXT_LIMIT,
        "reply_to_tweet_id": str(in_reply_to_tweet_id) if in_reply_to_tweet_id else None,
        "has_image": bool(resolved_image),
        "image_path": str(resolved_image) if resolved_image else None,
        "has_video": bool(resolved_video),
        "video_path": str(resolved_video) if resolved_video else None,
        "blockers": blockers,
        "warnings": warnings,
        "preview": text,
    }


def _read_env_file(path: Path) -> dict[str, str]:
    """Read the small credentials env file without mutating process env."""
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _credentials_file_path(path: Path | None = None) -> Path:
    """Resolve the live credential file without touching it during dry-runs."""
    if path is not None:
        return Path(path).expanduser()
    override = os.environ.get(CREDENTIALS_FILE_ENV)
    if override:
        return Path(override).expanduser()
    return DEFAULT_ENV_PATH


def load_credentials(path: Path | None = None) -> dict[str, str]:
    """Load X credentials lazily for a live operation only."""
    file_values = _read_env_file(_credentials_file_path(path))
    credentials = {
        key: os.environ.get(key) or file_values.get(key, "") for key in X_CREDENTIAL_KEYS
    }
    missing = [key for key, value in credentials.items() if not value]
    if missing:
        raise RuntimeError(f"Missing required X credential(s): {', '.join(missing)}")
    return credentials


def get_client():
    """Create a Tweepy v2 client.  This is the first point credentials are read."""
    import tweepy

    credentials = load_credentials()
    return tweepy.Client(
        consumer_key=credentials["X_API_KEY"],
        consumer_secret=credentials["X_API_KEY_SECRET"],
        access_token=credentials["X_ACCESS_TOKEN"],
        access_token_secret=credentials["X_ACCESS_TOKEN_SECRET"],
    )


def get_api_v1():
    """Create the v1.1 client used only for media upload."""
    import tweepy

    credentials = load_credentials()
    auth = tweepy.OAuth1UserHandler(
        credentials["X_API_KEY"],
        credentials["X_API_KEY_SECRET"],
        credentials["X_ACCESS_TOKEN"],
        credentials["X_ACCESS_TOKEN_SECRET"],
    )
    return tweepy.API(auth)


def _field(data: Any, name: str, default: Any = None) -> Any:
    if isinstance(data, Mapping):
        return data.get(name, default)
    return getattr(data, name, default)


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _tweet_url(tweet_id: str) -> str:
    return f"https://x.com/i/status/{tweet_id}"


def _expand_entity_urls(text: Any, entities: Any) -> str | None:
    """Restore original URLs in API text whose links were shortened to t.co."""
    if text is None:
        return None

    expanded_text = str(text)
    for url_entity in _field(entities, "urls", []) or []:
        shortened_url = _field(url_entity, "url")
        expanded_url = _field(url_entity, "expanded_url")
        if shortened_url is None or expanded_url is None:
            continue
        shortened_url = str(shortened_url)
        if shortened_url:
            expanded_text = expanded_text.replace(shortened_url, str(expanded_url))
    return expanded_text


def get_identity() -> dict[str, Any]:
    """Return the authenticated X identity using user-context authentication."""
    response = get_client().get_me(user_auth=True)
    data = response.data
    if data is None:
        raise RuntimeError("X get_me returned no identity")
    user_id = _field(data, "id")
    if user_id is None:
        raise RuntimeError("X get_me returned an identity without id")
    return {
        "id": str(user_id),
        "username": _field(data, "username"),
        "name": _field(data, "name"),
    }


def _ensure_postable(text: str, in_reply_to_tweet_id: str | None) -> None:
    blockers = _text_blockers(text) + _reply_blockers(in_reply_to_tweet_id)
    if blockers:
        raise ValueError(" / ".join(blockers))


def _created_tweet(
    response: Any,
    text: str,
    in_reply_to_tweet_id: str | None,
) -> dict[str, Any]:
    data = response.data
    if data is None:
        raise RuntimeError("X create_tweet returned no data")
    tweet_id = _field(data, "id")
    if tweet_id is None:
        raise RuntimeError("X create_tweet returned no Tweet id")
    tweet_id = str(tweet_id)
    return {
        "platform": "x",
        "status": "posted",
        "id": tweet_id,
        "url": _tweet_url(tweet_id),
        "text": _field(data, "text", text),
        "reply_to_tweet_id": (
            str(in_reply_to_tweet_id) if in_reply_to_tweet_id is not None else None
        ),
    }


def post_one(text: str, in_reply_to_tweet_id: str | None = None) -> dict[str, Any]:
    """Create exactly one text Tweet; ambiguous errors are never retried."""
    _ensure_postable(text, in_reply_to_tweet_id)
    kwargs: dict[str, Any] = {"text": text}
    if in_reply_to_tweet_id is not None:
        kwargs["in_reply_to_tweet_id"] = str(in_reply_to_tweet_id)
    response = get_client().create_tweet(**kwargs)
    return _created_tweet(response, text, in_reply_to_tweet_id)


def upload_video(video_path: str, timeout_sec: int = 300) -> Any:
    """Upload one video and poll its processing status without re-uploading it."""
    api_v1 = get_api_v1()
    media = api_v1.media_upload(
        filename=video_path,
        chunked=True,
        media_category="tweet_video",
    )
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        info = getattr(media, "processing_info", None)
        if not info or info.get("state") == "succeeded":
            return media.media_id
        if info.get("state") == "failed":
            raise RuntimeError(f"X動画処理失敗: {info.get('error')}")
        time.sleep(info.get("check_after_secs", 5))
        media = api_v1.get_media_upload_status(media.media_id)
    raise TimeoutError("X動画処理がタイムアウトしました")


def post_with_media(
    text: str,
    image_path: str | None = None,
    video_path: str | None = None,
    in_reply_to_tweet_id: str | None = None,
) -> dict[str, Any]:
    """Create one Tweet with one image or video, preserving the legacy support."""
    _ensure_postable(text, in_reply_to_tweet_id)
    media_ids: list[Any] | None = None
    if video_path:
        media_ids = [upload_video(video_path)]
    elif image_path:
        media = get_api_v1().media_upload(filename=image_path)
        media_ids = [media.media_id]

    kwargs: dict[str, Any] = {"text": text}
    if media_ids:
        kwargs["media_ids"] = media_ids
    if in_reply_to_tweet_id is not None:
        kwargs["in_reply_to_tweet_id"] = str(in_reply_to_tweet_id)
    response = get_client().create_tweet(**kwargs)
    result = _created_tweet(response, text, in_reply_to_tweet_id)
    result.update({"image_path": image_path, "video_path": video_path})
    return result


def post(
    text: str,
    image_path: str | None = None,
    video_path: str | None = None,
    in_reply_to_tweet_id: str | None = None,
) -> str:
    """Backward-compatible media-capable helper returning only the Tweet URL."""
    return post_with_media(text, image_path, video_path, in_reply_to_tweet_id)["url"]


def readback_tweet(tweet_id: str) -> dict[str, Any]:
    """Read a Tweet once, including creation time and its reply relationship."""
    if not str(tweet_id).isdigit():
        raise ValueError("tweet_id must be numeric")
    response = get_client().get_tweet(
        id=str(tweet_id),
        user_auth=True,
        tweet_fields=list(READBACK_FIELDS),
    )
    data = response.data
    if data is None:
        raise RuntimeError(f"X get_tweet returned no Tweet for id={tweet_id}")

    references: list[dict[str, str]] = []
    reply_to_tweet_id = None
    for reference in _field(data, "referenced_tweets", []) or []:
        reference_type = _field(reference, "type")
        reference_id = _field(reference, "id")
        if reference_type is None or reference_id is None:
            continue
        normalized = {"type": str(reference_type), "id": str(reference_id)}
        references.append(normalized)
        if reference_type == "replied_to":
            reply_to_tweet_id = str(reference_id)

    returned_id = str(_field(data, "id", tweet_id))
    text = _field(data, "text")
    return {
        "platform": "x",
        "status": "read_back",
        "id": returned_id,
        "url": _tweet_url(returned_id),
        "text": text,
        "expanded_text": _expand_entity_urls(text, _field(data, "entities")),
        "author_id": (
            str(_field(data, "author_id")) if _field(data, "author_id") is not None else None
        ),
        "conversation_id": (
            str(_field(data, "conversation_id"))
            if _field(data, "conversation_id") is not None
            else None
        ),
        "created_at": _isoformat(_field(data, "created_at")),
        "referenced_tweets": references,
        "is_reply": reply_to_tweet_id is not None,
        "reply_to_tweet_id": reply_to_tweet_id,
    }


def _emit_json(result: dict[str, Any], result_json: str | None = None) -> None:
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if result_json:
        path = Path(result_json).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered, flush=True)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Approval-gated X posting adapter")
    parser.add_argument("text", help="Tweet text")
    parser.add_argument("--image", help="Path to image file", default=None)
    parser.add_argument("--video", help="Path to mp4 video file", default=None)
    parser.add_argument("--reply-to", help="Tweet ID to reply to", default=None)
    parser.add_argument("--dry-run", action="store_true", help="Validate without posting")
    parser.add_argument("--json", action="store_true", help="Emit live result as JSON")
    parser.add_argument("--result-json", help="Also write the JSON result to this path")
    parser.add_argument(
        "--publish-approved",
        action="store_true",
        help="Required for a live post after explicit owner approval",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.dry_run:
        result = dry_run(args.text, args.image, args.video, args.reply_to)
        _emit_json(result, args.result_json)
        return 0 if not result["blockers"] else 2

    # Check the external-action gate before validation can reach any live
    # helper.  In particular, this branch never reads the credential env file.
    if not args.publish_approved:
        message = "Actual X posting requires --publish-approved after explicit owner approval."
        if args.json or args.result_json:
            _emit_json(
                {
                    "platform": "x",
                    "mode": "actual",
                    "status": "blocked",
                    "would_post": False,
                    "tokens_read": False,
                    "api_called": False,
                    "automatic_retry_attempted": False,
                    "error": message,
                },
                args.result_json,
            )
        else:
            print(message, file=sys.stderr)
        return 2

    validation = dry_run(args.text, args.image, args.video, args.reply_to)
    if validation["blockers"]:
        _emit_json(validation, args.result_json)
        return 2

    try:
        if args.image or args.video:
            result = post_with_media(
                args.text,
                image_path=args.image,
                video_path=args.video,
                in_reply_to_tweet_id=args.reply_to,
            )
        else:
            result = post_one(args.text, in_reply_to_tweet_id=args.reply_to)
    except Exception as exc:
        # A create_tweet transport error can be ambiguous: X may have accepted
        # it before the response was lost.  Never retry it automatically.
        error_result = {
            "platform": "x",
            "mode": "actual",
            "status": "not_confirmed",
            "publish_state": "unknown",
            "api_call_may_have_occurred": True,
            "automatic_retry_attempted": False,
            "manual_readback_recommended": True,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
        }
        _emit_json(error_result, args.result_json)
        return 2

    result.update(
        {
            "mode": "actual",
            "tokens_read": True,
            "api_called": True,
            "automatic_retry_attempted": False,
            "character_count": len(args.text),
            "weighted_length": weighted_length(args.text),
        }
    )
    if args.json or args.result_json:
        _emit_json(result, args.result_json)
    else:
        print(f"Posted: {result['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
