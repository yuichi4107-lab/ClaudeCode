#!/usr/bin/env python3
"""工程1: 曲生成/投入。

song_source(suno_api | manual)に応じて song.mp3(or wav) + lyrics.txt +
song_meta.json をプロジェクトディレクトリ直下に用意する。

使い方:
  python3 step1_music.py --project projects/20260707-neon-tokyo-drive
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mvfactory.common import (  # noqa: E402
    ensure_dirs,
    load_env_file,
    load_project_yaml,
    log,
    project_dir,
)
from mvfactory.providers.music import MusicProviderError, get_provider  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="工程1: 曲生成/投入")
    parser.add_argument("--project", required=True, help="プロジェクトディレクトリ(slugまたはパス)")
    args = parser.parse_args()

    load_env_file()
    pdir = project_dir(args.project)
    if not pdir.exists():
        log(f"ERROR: プロジェクトディレクトリが見つかりません: {pdir}")
        return 1

    try:
        project = load_project_yaml(pdir)
    except (FileNotFoundError, ValueError) as e:
        log(f"ERROR: {e}")
        return 1

    ensure_dirs(pdir)

    song_source = project["song_source"]
    log(f"曲生成モード: {song_source}")

    provider = get_provider(song_source)
    try:
        meta = provider.generate(project, pdir)
    except MusicProviderError as e:
        log(f"ERROR: {e}")
        return 1

    log(f"工程1 完了: {meta.get('audio_file')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
