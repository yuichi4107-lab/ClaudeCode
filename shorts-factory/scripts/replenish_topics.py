#!/usr/bin/env python3
"""shorts-factory topics.json を不足分だけ自動補充する。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import topic_store  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="shorts-factory ネタ帳の自動補充")
    parser.add_argument(
        "--difficulty",
        choices=sorted(topic_store.VALID_DIFFICULTIES),
        help="補充対象の難易度。省略時は全難易度を確認",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="下限以上でも目標本数まで補充する",
    )
    args = parser.parse_args()
    result = topic_store.replenish_topics(args.difficulty, force=args.force)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
