#!/usr/bin/env python3
"""Retry failed shorts-factory platform posts without duplicating posted media."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src import queue_lib  # noqa: E402
from src import drive_guard  # noqa: E402


RETRYABLE_STATUSES = {"failed", "partial_failed"}


def pending_platforms(item: dict) -> list[str]:
    return [
        name
        for name, info in item.get("platforms", {}).items()
        if info.get("enabled") and info.get("status") != "posted" and not info.get("non_retryable")
    ]


def load_targets(item_ids: list[str], include_all: bool) -> list[dict]:
    if item_ids:
        return [queue_lib.load_item(item_id) for item_id in item_ids]
    if include_all:
        return [
            item
            for item in queue_lib.list_items()
            if item.get("status") in RETRYABLE_STATUSES and pending_platforms(item)
        ]
    raise SystemExit("item_id を指定するか --all を付けてください")


def main() -> int:
    drive_guard.install()
    ap = argparse.ArgumentParser(description="失敗した投稿先だけを再試行する")
    ap.add_argument("item_ids", nargs="*", help="再試行するqueue item id")
    ap.add_argument("--all", action="store_true", help="failed/partial_failed を全件対象にする")
    ap.add_argument("--execute", action="store_true", help="実際に投稿する。未指定ならdry-run")
    args = ap.parse_args()

    targets = load_targets(args.item_ids, args.all)
    plan = [
        {"id": item["id"], "status": item.get("status"), "platforms": pending_platforms(item)}
        for item in targets
        if pending_platforms(item)
    ]
    print(json.dumps({"execute": args.execute, "targets": plan}, ensure_ascii=False, indent=2))
    if not args.execute:
        return 0

    exit_code = 0
    for item in targets:
        if not pending_platforms(item):
            continue
        env = os.environ.copy()
        env["SHORTS_FACTORY_ROOT"] = str(APP_ROOT)
        proc = subprocess.run(
            [
                sys.executable,
                str(APP_ROOT / "scripts" / "post_approved_item.py"),
                item["id"],
                "--retry-failed",
            ],
            cwd=str(APP_ROOT),
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.stdout.strip():
            print(proc.stdout.strip())
        if proc.returncode:
            exit_code = proc.returncode
            print(proc.stderr.strip(), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
