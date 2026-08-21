#!/usr/bin/env python3
"""Supervise the Drive mirror worker with a hard wall-clock timeout."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.config import CONFIG  # noqa: E402
from src.drive_mirror import MirrorBusy, mirror_once  # noqa: E402
from src.state_io import atomic_write_json  # noqa: E402

STATUS_PATH = CONFIG.mirror_dir / "status.json"


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _load_status() -> dict:
    try:
        data = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}


def _backoff_active(status: dict) -> bool:
    value = status.get("next_attempt_at")
    if not value:
        return False
    try:
        return datetime.now().astimezone() < datetime.fromisoformat(value)
    except ValueError:
        return False


def supervise(timeout_sec: float) -> dict:
    previous = _load_status()
    if _backoff_active(previous):
        return {"ok": False, "skipped": "backoff", "next_attempt_at": previous["next_attempt_at"]}

    env = os.environ.copy()
    env["SHORTS_FACTORY_ROOT"] = str(APP_ROOT)
    cmd = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    started_at = _now()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(APP_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        if proc.returncode == 0:
            result = json.loads(proc.stdout)
            status = {
                **result,
                "started_at": started_at,
                "completed_at": _now(),
                "consecutive_failures": 0,
                "next_attempt_at": None,
            }
        else:
            raise RuntimeError((proc.stderr or proc.stdout or f"exit={proc.returncode}")[-1000:])
    except (subprocess.TimeoutExpired, RuntimeError, json.JSONDecodeError) as exc:
        failures = int(previous.get("consecutive_failures") or 0) + 1
        delay = min(3600, 300 * (2 ** min(failures - 1, 4)))
        status = {
            "ok": False,
            "started_at": started_at,
            "failed_at": _now(),
            "error": f"{type(exc).__name__}: {exc}"[:1000],
            "consecutive_failures": failures,
            "next_attempt_at": (
                datetime.now().astimezone() + timedelta(seconds=delay)
            ).isoformat(timespec="seconds"),
        }
    atomic_write_json(STATUS_PATH, status)
    return status


def main() -> int:
    ap = argparse.ArgumentParser(description="ローカルshorts状態をDriveへ非同期ミラー")
    ap.add_argument("--worker", action="store_true")
    ap.add_argument("--timeout", type=float, default=90.0)
    args = ap.parse_args()
    if args.worker:
        try:
            result = mirror_once()
        except MirrorBusy as exc:
            print(json.dumps({"ok": False, "busy": str(exc)}, ensure_ascii=False))
            return 75
        print(json.dumps(result, ensure_ascii=False))
        return 0
    print(json.dumps(supervise(args.timeout), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
