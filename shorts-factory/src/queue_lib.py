"""投稿キュー（.company/marketing/shorts-factory/queue/）の管理。

social-auto-ops のステータス設計を踏襲:
  draft → ready_for_review → approved → posted / failed / skipped / blocked

ローカル正本へ atomic write + item単位flock で保存する。
Driveへの反映は別プロセスのミラーが行う。
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path

from .config import CONFIG
from .fs_retry import retry_io, run_with_timeout
from .platform_copy import build_platform_copy_set
from .state_io import atomic_write_json, file_lock

STATUSES = {
    "draft",
    "ready_for_review",
    "approved",
    "posted",
    "partial_failed",
    "failed",
    "skipped",
    "blocked",
}

STATUS_STAGE = {
    "draft": 0,
    "ready_for_review": 1,
    "blocked": 1,
    "approved": 2,
    "partial_failed": 3,
    "failed": 3,
    "posted": 4,
    "skipped": 4,
}

PLATFORM_STATUS_STAGE = {"pending": 0, "failed": 1, "posted": 2}


class QueueStateError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def queue_path(item_id: str) -> Path:
    return CONFIG.queue_dir / f"{item_id}.json"


def _lock_path(item_id: str) -> Path:
    return CONFIG.state_dir / "locks" / "queue" / f"{item_id}.lock"


def _merge_history(current: list, incoming: list) -> list:
    merged: list = []
    seen: set[tuple[str, str]] = set()
    for entry in [*(current or []), *(incoming or [])]:
        if not isinstance(entry, dict):
            continue
        key = (str(entry.get("ts") or ""), str(entry.get("event") or ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
    return merged


def _merge_nested(current: dict, incoming: dict, path: tuple[str, ...] = ()) -> dict:
    """Merge a stale nested snapshot while preserving newer durable facts."""
    merged = copy.deepcopy(current or {})
    for key, value in (incoming or {}).items():
        old = merged.get(key)
        key_path = (*path, key)
        if isinstance(value, dict) and isinstance(old, dict):
            merged[key] = _merge_nested(old, value, key_path)
            continue
        # A stale None must not erase a receipt, URL, timestamp, or decision.
        if value is None and old is not None:
            continue
        if key == "message_id" and old is not None:
            continue
        if key in {"owner_approved", "non_retryable", "reconcile_required"} and old is True:
            continue
        if key in {"attempts", "preview_send_attempts"}:
            try:
                merged[key] = max(int(old or 0), int(value or 0))
                continue
            except (TypeError, ValueError):
                pass
        if key.endswith("_at") and isinstance(old, str) and isinstance(value, str):
            merged[key] = max(old, value)
            continue
        merged[key] = copy.deepcopy(value)
    return merged


def _merged_status(old_status: str, new_status: str) -> str:
    if old_status == new_status:
        return old_status
    # Public posting is irreversible and always wins over stale local terminal states.
    if "posted" in {old_status, new_status}:
        return "posted"
    if STATUS_STAGE.get(old_status, 0) >= STATUS_STAGE.get(new_status, 0):
        return old_status
    return new_status


def _sync_mapping_in_place(target: dict, source: dict) -> None:
    """Replace a snapshot without invalidating references to existing nested dicts."""
    for key in list(target):
        if key not in source:
            del target[key]
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _sync_mapping_in_place(target[key], value)
        elif isinstance(value, list) and isinstance(target.get(key), list):
            target[key][:] = copy.deepcopy(value)
        else:
            target[key] = copy.deepcopy(value)


def _merge_stale_item(current: dict, incoming: dict) -> dict:
    """Merge a stale full snapshot without regressing posting state."""
    merged = copy.deepcopy(current)
    for key, value in incoming.items():
        if key in {"_revision", "history", "platforms"}:
            continue
        if key in {
            "telegram",
            "review",
            "posting_worker",
            "posting_guard",
            "topic_store",
            "deferred_retry",
            "video",
            "quality",
            "recovery",
        } and isinstance(value, dict):
            nested = _merge_nested(dict(merged.get(key) or {}), value, (key,))
            if key == "topic_store" and value.get("consume_deferred_resolved_at"):
                nested.pop("consume_deferred_error", None)
            merged[key] = nested
        else:
            merged[key] = copy.deepcopy(value)

    platforms = copy.deepcopy(current.get("platforms") or {})
    for name, info in (incoming.get("platforms") or {}).items():
        current_info = dict(platforms.get(name) or {})
        updated = _merge_nested(current_info, info, ("platforms", name))
        old_platform_status = str(current_info.get("status") or "pending")
        new_platform_status = str(info.get("status") or old_platform_status)
        if old_platform_status == "posted" or new_platform_status == "posted":
            updated["status"] = "posted"
            if old_platform_status == "posted":
                for durable_key in ("url", "posted_at"):
                    if current_info.get(durable_key) is not None:
                        updated[durable_key] = current_info[durable_key]
                updated["error"] = None
        elif PLATFORM_STATUS_STAGE.get(old_platform_status, 0) > PLATFORM_STATUS_STAGE.get(
            new_platform_status, 0
        ):
            updated["status"] = old_platform_status
        platforms[name] = updated
    if platforms:
        merged["platforms"] = platforms

    merged["history"] = _merge_history(current.get("history", []), incoming.get("history", []))
    old_status = str(current.get("status") or "draft")
    new_status = str(incoming.get("status") or old_status)
    merged["status"] = _merged_status(old_status, new_status)
    return merged


def _save_item_once(item: dict) -> Path:
    CONFIG.queue_dir.mkdir(parents=True, exist_ok=True)
    path = queue_path(item["id"])
    with file_lock(_lock_path(item["id"])):
        current: dict = {}
        if path.exists():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise QueueStateError(f"queue JSON is corrupt: {path}") from exc
        current_revision = int(current.get("_revision") or 0)
        incoming_revision = int(item.get("_revision") or 0)
        saved = (
            _merge_stale_item(current, item)
            if current and incoming_revision != current_revision
            else copy.deepcopy(item)
        )
        saved["_revision"] = current_revision + 1
        atomic_write_json(path, saved)
        _sync_mapping_in_place(item, saved)
    return path


def save_item(item: dict) -> Path:
    return retry_io(
        lambda: run_with_timeout(
            lambda: _save_item_once(item),
            timeout_sec=8.0,
            label=f"write queue {item.get('id', 'unknown')}",
        ),
        attempts=5,
        delay_sec=3.0,
    )


def _load_item_once(item_id: str) -> dict:
    with file_lock(_lock_path(item_id), shared=True):
        text = run_with_timeout(
            lambda: queue_path(item_id).read_text(encoding="utf-8"),
            timeout_sec=5.0,
            label=f"read queue {item_id}",
        )
    return json.loads(text)


def load_item(item_id: str) -> dict:
    return retry_io(lambda: _load_item_once(item_id), attempts=5, delay_sec=3.0)


def list_items(
    status: str | None = None,
    *,
    recent_files: int | None = None,
    max_items: int | None = None,
) -> list[dict]:
    if not CONFIG.queue_dir.exists():
        return []
    items = []
    paths = sorted(CONFIG.queue_dir.glob("*.json"))
    if recent_files is not None:
        paths = paths[-max(0, int(recent_files)) :]
        paths.reverse()
    for p in paths:
        try:
            item = retry_io(
                lambda p=p: json.loads(
                    _read_queue_path(p)
                ),
                attempts=3,
                delay_sec=1.0,
            )
        except (json.JSONDecodeError, OSError):
            continue
        if status is None or item.get("status") == status:
            items.append(item)
            if max_items is not None and len(items) >= max(0, int(max_items)):
                break
    return items


def _read_queue_path(path: Path) -> str:
    with file_lock(_lock_path(path.stem), shared=True):
        return run_with_timeout(
            lambda: path.read_text(encoding="utf-8"),
            timeout_sec=3.0,
            label=f"read queue {path.name}",
        )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def find_due_scheduled_draft(
    now: datetime | None = None,
    difficulty: str | None = None,
    grace: timedelta = timedelta(hours=2),
) -> dict | None:
    """Return a draft reserved for the current scheduled slot, if one is due."""
    now = now or datetime.now().astimezone()
    due: list[tuple[datetime, dict]] = []
    for item in list_items("draft"):
        scheduled_for = _parse_iso(item.get("scheduled_for"))
        if not scheduled_for:
            continue
        if scheduled_for.tzinfo is None and now.tzinfo is not None:
            scheduled_for = scheduled_for.replace(tzinfo=now.tzinfo)
        if item.get("difficulty") and difficulty and item.get("difficulty") != difficulty:
            continue
        if scheduled_for <= now <= scheduled_for + grace:
            due.append((scheduled_for, item))
    if not due:
        return None
    due.sort(key=lambda pair: pair[0])
    return due[0][1]


def new_item(
    item_id: str,
    topic: str,
    script: dict,
    video_path: Path,
    duration: float,
    size_mb: float,
    quality_report_path: Path,
    quality_pass: bool,
    avg_cer: float,
    output_dir: Path,
    *,
    enabled_platforms: list[str] | tuple[str, ...] | None = None,
    variant_group_id: str | None = None,
) -> dict:
    platforms = {}
    enabled_set = (
        set(enabled_platforms)
        if enabled_platforms is not None
        else set(CONFIG.get("queue", "platforms", default=["x"]) or [])
    )
    for p in ("x", "youtube", "instagram", "tiktok"):
        platforms[p] = {
            "enabled": p in enabled_set,
            "status": "pending",
            "url": None,
            "error": None,
            "posted_at": None,
            "attempts": 0,
            "last_attempt_at": None,
            "last_retry_at": None,
        }
    item = {
        "id": item_id,
        "created_at": _now(),
        "topic": topic,
        "difficulty": script.get("difficulty", "beginner"),
        "target_platform": script.get("target_platform", "common"),
        "title": script["title"],
        "caption": script["caption"],
        "hashtags": script["hashtags"],
        "speaker_credit": script.get("speaker_credit", CONFIG.get("speaker_credit")),
        "audio_mode": script.get("audio_mode"),
        "content_strategy": script.get("content_strategy", {}),
        "platform_angles": script.get("platform_angles", {}),
        "video": {
            "path": str(video_path),
            "local_path": str(video_path),
            "duration": round(duration, 2),
            "size_mb": round(size_mb, 2),
        },
        "output_dir": str(output_dir),
        "quality": {
            "pass": quality_pass,
            "avg_cer": avg_cer,
            "report_path": str(quality_report_path),
        },
        "status": "draft",
        "review": {"owner_approved": False, "decided_at": None, "via": None},
        "telegram": {"message_id": None},
        "platforms": platforms,
        "history": [{"ts": _now(), "event": "created"}],
    }
    if variant_group_id:
        item["variant_group_id"] = variant_group_id
    item["platform_copy"] = build_platform_copy_set(item)
    save_item(item)
    return item


def transition(item: dict, status: str, event: str | None = None) -> dict:
    assert status in STATUSES, f"不正なstatus: {status}"
    item["status"] = status
    item.setdefault("history", []).append({"ts": _now(), "event": event or status})
    save_item(item)
    return item


def mark_platform(item: dict, platform: str, status: str, url: str | None = None,
                  error: str | None = None) -> dict:
    p = item["platforms"][platform]
    p["status"] = status
    if url:
        p["url"] = url
    if status == "posted":
        p["error"] = None
    elif error:
        p["error"] = error[:500]
    if status == "posted":
        p["posted_at"] = _now()
    item.setdefault("history", []).append(
        {"ts": _now(), "event": f"{platform}:{status}" + (f" {url}" if url else "")}
    )
    save_item(item)
    return item
