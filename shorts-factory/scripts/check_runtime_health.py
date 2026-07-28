#!/usr/bin/env python3
"""Offline health check for the local shorts-factory control plane."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.config import CONFIG  # noqa: E402
from src import queue_lib  # noqa: E402

ACTIVE = {"ready_for_review", "approved", "partial_failed", "failed", "blocked"}


def check() -> dict:
    errors: list[str] = []
    try:
        CONFIG.assert_runtime_ready()
    except RuntimeError as exc:
        errors.append(str(exc))

    hot_paths = {
        key: getattr(CONFIG, key)
        for key in (
            "factory_dir",
            "queue_dir",
            "topics_path",
            "outputs_dir",
            "work_dir",
            "logs_dir",
            "sns_env_path",
        )
    }
    drive_hot_paths = [key for key, path in hot_paths.items() if "CloudStorage" in Path(path).parts]
    if drive_hot_paths:
        errors.append("Drive path remains in hot path: " + ", ".join(drive_hot_paths))

    items = []
    started = time.perf_counter()
    try:
        items = queue_lib.list_items()
    except Exception as exc:  # noqa: BLE001
        errors.append(f"queue scan failed: {exc}")
    scan_sec = time.perf_counter() - started
    if scan_sec > 2.0:
        errors.append(f"queue scan too slow: {scan_sec:.3f}s")
    queue_file_count = len(list(CONFIG.queue_dir.glob("*.json")))
    if queue_file_count != len(items):
        errors.append(
            f"queue JSON unreadable or missing from scan: files={queue_file_count} loaded={len(items)}"
        )

    deferred = [
        item["id"]
        for item in items
        if (item.get("topic_store") or {}).get("consume_deferred_error")
    ]
    if deferred:
        errors.append(f"deferred topic items remain: {len(deferred)}")

    local_media_missing = []
    active_drive_media = []
    for item in items:
        if item.get("status") not in ACTIVE:
            continue
        video = item.get("video") or {}
        video_path = Path(video.get("local_path") or "")
        upload_path = Path(video.get("upload_path") or "")
        if any(
            "/Library/CloudStorage/" in str(path).replace("\\", "/")
            for path in (video_path, upload_path)
        ):
            active_drive_media.append(item["id"])
            continue
        work_path = CONFIG.work_dir / item["id"] / Path(video.get("path") or "final.mp4").name
        archive_path = CONFIG.outputs_dir / item["id"] / Path(video.get("path") or "final.mp4").name
        if not any(path.is_file() for path in (video_path, work_path, archive_path)):
            local_media_missing.append(item["id"])
    if local_media_missing:
        errors.append(f"active local media missing: {len(local_media_missing)}")
    if active_drive_media:
        errors.append(f"active items retain Drive media paths: {len(active_drive_media)}")

    preview_receipt_uncertain = [
        item["id"]
        for item in items
        if item.get("status") == "ready_for_review"
        and int((item.get("telegram") or {}).get("preview_send_attempts") or 0) > 0
        and not (item.get("telegram") or {}).get("message_id")
        and not (item.get("telegram") or {}).get("preview_send_failed_at")
        and not (item.get("telegram") or {}).get("preview_sent_untracked_at")
    ]
    if preview_receipt_uncertain:
        errors.append(f"preview receipts uncertain: {len(preview_receipt_uncertain)}")

    credential_mode = None
    if not CONFIG.sns_env_path.is_file() or CONFIG.sns_env_path.stat().st_size == 0:
        errors.append("local SNS credentials missing or empty")
    else:
        credential_mode = oct(CONFIG.sns_env_path.stat().st_mode & 0o777)
        if credential_mode != "0o600":
            errors.append(f"local SNS credential mode is {credential_mode}, expected 0o600")

    mirror_status = {}
    status_path = CONFIG.mirror_dir / "status.json"
    if status_path.is_file():
        try:
            mirror_status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"mirror status invalid: {exc}")

    posting_ledger_invalid = []
    ledger_dir = CONFIG.runtime_dir / "posting_ledger"
    if ledger_dir.is_dir():
        for ledger_path in ledger_dir.glob("*.json"):
            try:
                data = json.loads(ledger_path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("platforms", {}), dict):
                    raise ValueError("invalid ledger shape")
            except (OSError, json.JSONDecodeError, ValueError):
                posting_ledger_invalid.append(ledger_path.stem)
    if posting_ledger_invalid:
        errors.append(f"posting ledgers invalid: {len(posting_ledger_invalid)}")

    return {
        "ok": not errors,
        "errors": errors,
        "queue_count": len(items),
        "queue_file_count": queue_file_count,
        "statuses": dict(Counter(item.get("status") for item in items)),
        "queue_scan_sec": round(scan_sec, 4),
        "deferred_topic_count": len(deferred),
        "active_local_media_missing": local_media_missing,
        "active_drive_media": active_drive_media,
        "preview_receipt_uncertain": preview_receipt_uncertain,
        "posting_ledger_invalid": posting_ledger_invalid,
        "credential_mode": credential_mode,
        "hot_paths": {key: str(path) for key, path in hot_paths.items()},
        "mirror": mirror_status,
        "pid": os.getpid(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="shorts-factoryローカル制御プレーン診断")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    result = check()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("OK" if result["ok"] else "NG", json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
