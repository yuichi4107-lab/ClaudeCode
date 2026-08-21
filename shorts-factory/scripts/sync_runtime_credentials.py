#!/usr/bin/env python3
"""Explicitly refresh the local SNS credential snapshot from its managed source."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from src.config import CONFIG  # noqa: E402
from src.state_io import atomic_write_text  # noqa: E402


def sync_credentials(source: Path, destination: Path) -> dict:
    text = source.read_text(encoding="utf-8")
    assignments = [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#") and "=" in line
    ]
    if not assignments:
        raise RuntimeError(f"No credential assignments found in {source}")
    atomic_write_text(destination, text, mode=0o600)
    return {
        "source": str(source),
        "destination": str(destination),
        "assignments": len(assignments),
        "mode": "0600",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="SNS認証をruntimeローカルへ明示同期する")
    ap.add_argument("--source", type=Path, default=CONFIG.drive_sns_env_path)
    ap.add_argument("--destination", type=Path, default=CONFIG.sns_env_path)
    args = ap.parse_args()
    result = sync_credentials(args.source.expanduser(), args.destination.expanduser())
    print(
        "SNS credentials synced: "
        f"{result['source']} -> {result['destination']} "
        f"({result['assignments']} assignments, mode {result['mode']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
