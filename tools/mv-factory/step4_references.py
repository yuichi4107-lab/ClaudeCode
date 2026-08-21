#!/usr/bin/env python3
"""工程4: 参照画像生成マニフェスト作成(実生成はエージェント/既存スキルが担当)。

使い方:
  python3 step4_references.py --project projects/20260707-neon-tokyo-drive
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mvfactory.common import load_project_yaml, log, project_dir  # noqa: E402
from mvfactory.references import run_step4  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="工程4: 参照画像マニフェスト生成")
    parser.add_argument("--project", required=True)
    args = parser.parse_args()

    pdir = project_dir(args.project)
    if not pdir.exists():
        log(f"ERROR: プロジェクトディレクトリが見つかりません: {pdir}")
        return 1

    try:
        project = load_project_yaml(pdir)
    except (FileNotFoundError, ValueError) as e:
        log(f"ERROR: {e}")
        return 1

    run_step4(pdir, project)
    return 0


if __name__ == "__main__":
    sys.exit(main())
