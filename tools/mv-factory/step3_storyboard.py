#!/usr/bin/env python3
"""工程3: 絵コンテ・シーンプロンプト生成(スキーマ検証 / 雛形生成)。

実際のシーン内容の"生成"はClaude Codeのエージェントが行う(README.md参照)。
このスクリプトは2つのサブコマンドを提供する:

  scaffold: song_structure.json + project.yaml を読み、
            storyboard_{short,full}.json の雛形(空scenes)を書き出す。
            エージェントはこの雛形にscenesを書き足してから validate を実行する。
  validate: 既存の storyboard_{short,full}.json をスキーマ検証する。

使い方:
  python3 step3_storyboard.py --project <dir> --version short --mode scaffold
  python3 step3_storyboard.py --project <dir> --version short --mode validate
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mvfactory.common import load_project_yaml, log, project_dir  # noqa: E402
from mvfactory.storyboard import (  # noqa: E402
    StoryboardError,
    load_and_validate_storyboard,
    scaffold_storyboard_template,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="工程3: 絵コンテ・シーンプロンプト生成")
    parser.add_argument("--project", required=True)
    parser.add_argument("--version", required=True, choices=["short", "full"])
    parser.add_argument("--mode", default="validate", choices=["scaffold", "validate"])
    args = parser.parse_args()

    pdir = project_dir(args.project)
    if not pdir.exists():
        log(f"ERROR: プロジェクトディレクトリが見つかりません: {pdir}")
        return 1

    if args.mode == "scaffold":
        try:
            project = load_project_yaml(pdir)
        except (FileNotFoundError, ValueError) as e:
            log(f"ERROR: {e}")
            return 1
        path = scaffold_storyboard_template(pdir, args.version, project)
        log(f"雛形を書き出しました: {path}")
        log("この雛形の scenes[] にエージェントがシーンを作文してください。")
        return 0

    try:
        data = load_and_validate_storyboard(pdir, args.version)
    except StoryboardError as e:
        log(f"ERROR: {e}")
        return 1

    log(f"storyboard_{args.version}.json は検証OKです(scenes={len(data['scenes'])}件)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
