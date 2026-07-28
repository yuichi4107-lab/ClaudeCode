#!/usr/bin/env python3
"""工程6: 編集・合成(完パケMV出力)。

クリップ結合 -> 曲mux -> 尺合わせ -> フェード処理 -> final_mv_{short,full}_*.mp4

短編集(short)は同じ曲の一部区間(ハイライト)だけを使う設計のため、曲尺が
target_duration_secより大きい場合は、絵コンテのtarget_duration_sec分だけ
曲の先頭から切り出した一時音源(_audio_trimmed_short.mp3)を作成して曲全体(3分超)がmuxされ、映像側が
不自然にfreeze-frame延長されてしまう(2026-07-07 実装時に発覚した不具合)。

使い方:
  python3 step6_mix.py --project <dir> --version short
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mvfactory.analysis import ffprobe_duration_sec  # noqa: E402
from mvfactory.common import load_project_yaml, log, project_dir  # noqa: E402
from mvfactory.mix import run_step6  # noqa: E402
from mvfactory.storyboard import StoryboardError, load_and_validate_storyboard  # noqa: E402


def find_audio(pdir: Path) -> Path:
    for ext in (".mp3", ".wav"):
        p = pdir / f"song{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"song.mp3/song.wav が見つかりません: {pdir}")


def resolve_audio_for_version(pdir: Path, version: str, target_duration_sec: float) -> Path:
    """versionに応じた音源パスを返す。

    short版で曲尺がtarget_duration_secより大きい場合は、曲の先頭から
    target_duration_sec秒を切り出した一時ファイルを作りそれを返す
    (short版は同じ曲のハイライト区間だけを使う設計のため)。
    full版はそのまま曲全体を返す(3分版は曲全体をカバーする設計)。
    """
    audio_path = find_audio(pdir)
    if version != "short":
        return audio_path

    audio_dur = ffprobe_duration_sec(audio_path)
    if audio_dur <= target_duration_sec + 1.0:
        return audio_path

    trimmed = pdir / f"_audio_trimmed_{version}{audio_path.suffix}"
    log(
        f"[short] 曲尺({audio_dur:.1f}s)がtarget({target_duration_sec}s)より長いため、"
        f"先頭{target_duration_sec}s分を切り出します: {trimmed.name}"
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(audio_path),
        "-t", f"{target_duration_sec}",
        "-c:a", "libmp3lame" if audio_path.suffix == ".mp3" else "pcm_s16le",
        str(trimmed),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"曲のトリムに失敗しました: {proc.stderr[-2000:]}")
    return trimmed


def main() -> int:
    parser = argparse.ArgumentParser(description="工程6: 編集・合成(完パケ出力)")
    parser.add_argument("--project", required=True)
    parser.add_argument("--version", required=True, choices=["short", "full"])
    args = parser.parse_args()

    pdir = project_dir(args.project)
    if not pdir.exists():
        log(f"ERROR: プロジェクトディレクトリが見つかりません: {pdir}")
        return 1

    try:
        project = load_project_yaml(pdir)
        storyboard = load_and_validate_storyboard(pdir, args.version)
        audio_path = resolve_audio_for_version(
            pdir, args.version, float(storyboard["target_duration_sec"])
        )
    except (FileNotFoundError, ValueError, StoryboardError, RuntimeError) as e:
        log(f"ERROR: {e}")
        return 1

    clips_dir = pdir / args.version / f"clips_{args.version}"
    clip_paths = []
    missing = []
    for scene in storyboard["scenes"]:
        p = clips_dir / f"{scene['scene_id']}.mp4"
        if p.exists():
            clip_paths.append(p)
        else:
            missing.append(scene["scene_id"])

    if missing:
        log(f"ERROR: 未生成のクリップがあります(工程5を先に完了させてください): {missing}")
        return 1

    mix_cfg = project.get("mix", {})
    try:
        final_path = run_step6(
            pdir, args.version, clip_paths, audio_path, storyboard["aspect_ratio"], mix_cfg,
        )
    except RuntimeError as e:
        log(f"ERROR: {e}")
        return 1

    log(f"工程6({args.version}) 完了: {final_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
