#!/usr/bin/env python3
"""One-way migration from the legacy Drive control plane to local runtime state.

This script is explicit and one-shot. Normal generation/approval/posting never
read Drive state back into the runtime.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.config import CONFIG  # noqa: E402
from src import queue_lib, topic_store  # noqa: E402
from src.state_io import atomic_write_json  # noqa: E402


MARKER = CONFIG.state_dir / "migration-v2-local-control-plane.json"


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_aux_dir(source: Path, destination: Path) -> int:
    copied = 0
    if not source.exists():
        return copied
    for path in sorted(source.glob("*.json")):
        data = _read_json(path)
        atomic_write_json(destination / path.name, data)
        copied += 1
    return copied


def _reconcile_deferred_topics() -> int:
    resolved = 0
    for item in queue_lib.list_items():
        state = item.get("topic_store") or {}
        if not state.get("consume_deferred_error") or not item.get("topic"):
            continue
        slug = state.get("consume_group_slug") or item.get("variant_group_id") or item["id"]
        title = state.get("consume_title") or (
            f"SNS別動画: {item['topic']}" if item.get("variant_group_id") else item.get("title", item["topic"])
        )
        remaining = topic_store.consume_topic(
            item["topic"], slug, title, item.get("difficulty")
        )
        state.pop("consume_deferred_error", None)
        state["consume_deferred_resolved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        state["remaining"] = remaining
        item["topic_store"] = state
        item.setdefault("history", []).append(
            {
                "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                "event": f"migration_topic_consume_recovered remaining={remaining}",
            }
        )
        queue_lib.save_item(item)
        resolved += 1
    return resolved


def migrate(source_marketing: Path, *, force: bool = False) -> dict:
    if MARKER.exists() and not force:
        return {"already_migrated": True, **_read_json(MARKER)}

    source_queue = source_marketing / "queue"
    source_topics = source_marketing / "topics.json"
    if not source_queue.exists():
        raise FileNotFoundError(source_queue)

    queue_files = sorted(source_queue.glob("*.json"))
    if not queue_files:
        raise RuntimeError(f"No queue JSON files found in {source_queue}")

    copied_queue = 0
    for source in queue_files:
        item = _read_json(source)
        if not item.get("id") or source.stem != item["id"]:
            raise ValueError(f"Queue id/path mismatch: {source}")
        video = item.setdefault("video", {})
        if "/Library/CloudStorage/" in str(video.get("upload_path") or "").replace("\\", "/"):
            video.pop("upload_path", None)
        legacy_video = Path(video.get("path") or "")
        local_candidates = [
            CONFIG.work_dir / item["id"] / legacy_video.name,
            CONFIG.work_dir / item["id"] / "final.mp4",
            CONFIG.outputs_dir / item["id"] / legacy_video.name,
            CONFIG.outputs_dir / item["id"] / "final.mp4",
        ]
        local_video = next((path for path in local_candidates if path.is_file()), None)
        active = item.get("status") in {
            "ready_for_review", "approved", "partial_failed", "failed", "blocked"
        }
        if local_video is None and active and legacy_video.is_file():
            cache_dir = CONFIG.runtime_dir / "upload_cache" / item["id"]
            cache_dir.mkdir(parents=True, exist_ok=True)
            local_video = cache_dir / (legacy_video.name or "final.mp4")
            shutil.copy2(legacy_video, local_video)
        if local_video is not None:
            video["local_path"] = str(local_video)
        elif active:
            item.setdefault("runtime_guard", {})["local_media_missing"] = True
            item["runtime_guard"]["local_media_checked_at"] = (
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
            item["status"] = "blocked"
            item.setdefault("history", []).append(
                {
                    "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "event": "migration blocked: local media missing",
                }
            )
        queue_lib.save_item(item)
        copied_queue += 1

    topics_source = source_topics if source_topics.exists() else topic_store.TOPICS_CACHE_PATH
    topics = _read_json(topics_source)
    if not isinstance(topics.get("backlog", []), list) or not isinstance(topics.get("used", []), list):
        raise ValueError(f"Invalid topics schema: {topics_source}")
    atomic_write_json(CONFIG.topics_path, topics)

    pending = _copy_aux_dir(
        source_marketing / "pending_rejections",
        CONFIG.marketing_dir / "pending_rejections",
    )
    outbox = _copy_aux_dir(
        source_marketing / "notification_outbox",
        CONFIG.marketing_dir / "notification_outbox",
    )
    resolved = _reconcile_deferred_topics()

    result = {
        "migrated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": str(source_marketing),
        "queue_count": copied_queue,
        "topics_source": str(topics_source),
        "topics_sha256": _sha256(topics_source),
        "backlog_before_reconcile": len(topics.get("backlog", [])),
        "used_before_reconcile": len(topics.get("used", [])),
        "deferred_topic_items_resolved": resolved,
        "pending_rejections": pending,
        "notification_outbox": outbox,
    }
    atomic_write_json(MARKER, result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Driveの旧shorts状態をruntimeへ一方向移行する")
    ap.add_argument("--source-marketing", type=Path, default=CONFIG.drive_marketing_dir)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    result = migrate(args.source_marketing.expanduser(), force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
