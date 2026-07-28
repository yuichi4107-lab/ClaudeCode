#!/usr/bin/env python3
"""工程2: 曲構成解析。song.mp3(wav) + lyrics.txt -> song_structure.json

使い方:
  python3 step2_analyze.py --project projects/20260707-neon-tokyo-drive
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mvfactory.analysis import run_step2  # noqa: E402
from mvfactory.common import log, project_dir  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="工程2: 曲構成解析")
    parser.add_argument("--project", required=True)
    args = parser.parse_args()

    pdir = project_dir(args.project)
    if not pdir.exists():
        log(f"ERROR: プロジェクトディレクトリが見つかりません: {pdir}")
        return 1

    try:
        run_step2(pdir)
    except FileNotFoundError as e:
        log(f"ERROR: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
