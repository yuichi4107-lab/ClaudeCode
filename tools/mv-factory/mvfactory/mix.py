"""工程6: 編集・合成(完パケ出力)。ffmpegベース。

方式(要件定義書 工程6の完了条件に対応):
  1. クリップを scene_id 順に結合(concat demuxer、コーデック統一のため再エンコード)
  2. 曲(song.mp3/wav)をmux
  3. 尺合わせ:
     - クリップ合計 < 曲尺 → 曲を映像尺に合わせてtrim(fade out込み)
       (video_duration_mode="trim_to_music"の場合は逆に映像側最終フレームをholdして
        音楽尺に合わせる。デフォルトはtrim_to_music: 曲を基準にし、映像が足りなければ
        最終クリップをfreeze-frame延長、超えていれば末尾をtrimする)
     - クリップ合計 > 曲尺 → 映像を曲尺に合わせてtrim
  4. フェードイン/アウト(音声・映像とも)
  5. アスペクト比・解像度をstoryboardのaspect_ratioに合わせて統一(scale+pad)
  6. H.264 + AAC、CRFベースの高品質出力

短編集(short-video-editor)スキルとの関係:
  short-video-editorはトーク動画のジェットカット・テロップ・Whisper前提の
  編集パイプラインであり、MVの「曲に映像を同期させる」用途とは要件が異なるため
  直接流用しない。ただし品質検証の考え方(black frame検知、つなぎ目異音検知)は
  video-quality-checkerエージェントに委任する形で踏襲する(README参照)。
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List

from .analysis import ffprobe_duration_sec
from .common import log


def _run(cmd: List[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpegコマンド失敗: {' '.join(cmd)}\n{proc.stderr[-3000:]}")


def concat_clips(clip_paths: List[Path], aspect_ratio: str, dest: Path) -> None:
    if not clip_paths:
        raise RuntimeError("結合対象のクリップがありません")

    w, h = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)

    list_file = dest.parent / f"{dest.stem}_concat_list.txt"
    list_file.parent.mkdir(parents=True, exist_ok=True)

    # コーデック/解像度を統一するため、まず各クリップを正規化してから concat する
    normalized_dir = dest.parent / "_normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    normalized_paths = []
    for i, clip in enumerate(clip_paths):
        norm = normalized_dir / f"norm_{i:03d}.mp4"
        _run([
            "ffmpeg", "-y", "-i", str(clip),
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1",
            "-r", "30",
            "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "192k",
            str(norm),
        ])
        normalized_paths.append(norm)

    list_file.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in normalized_paths) + "\n", encoding="utf-8"
    )

    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-c", "copy", str(dest),
    ])


def mux_with_music(
    video_path: Path,
    audio_path: Path,
    dest: Path,
    audio_fade_in: float,
    audio_fade_out: float,
    video_fade_out: float,
) -> Dict[str, Any]:
    video_dur = ffprobe_duration_sec(video_path)
    audio_dur = ffprobe_duration_sec(audio_path)

    target_dur = audio_dur  # 曲を基準に尺を合わせる(trim_to_music)
    duration_mode = "video_shorter_than_music" if video_dur < audio_dur else (
        "video_longer_than_music" if video_dur > audio_dur else "equal"
    )

    video_filters = []
    if video_dur < target_dur:
        # 最終フレームをfreeze-frameで延長
        pad_sec = target_dur - video_dur
        video_filters.append(f"tpad=stop_mode=clone:stop_duration={pad_sec:.3f}")
    fade_start = max(target_dur - video_fade_out, 0)
    video_filters.append(f"fade=t=out:st={fade_start:.3f}:d={video_fade_out:.3f}")
    vf = ",".join(video_filters)

    audio_fade_out_start = max(target_dur - audio_fade_out, 0)
    af = "afade=t=in:st=0:d={audio_fade_in:.3f},afade=t=out:st={audio_fade_out_start:.3f}:d={audio_fade_out:.3f}"

    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-vf", vf,
        "-af", af,
        "-t", f"{target_dur:.3f}",
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-crf", "18", "-preset", "medium",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(dest),
    ]
    _run(cmd)

    return {
        "video_duration_sec": round(video_dur, 2),
        "audio_duration_sec": round(audio_dur, 2),
        "final_duration_sec": round(target_dur, 2),
        "duration_mode": duration_mode,
    }


def run_step6(
    pdir: Path,
    version: str,
    clip_paths: List[Path],
    audio_path: Path,
    aspect_ratio: str,
    mix_cfg: Dict[str, Any],
) -> Path:
    out_name = "final_mv_short_9x16.mp4" if version == "short" else "final_mv_full_16x9.mp4"
    version_dir = pdir / version
    version_dir.mkdir(parents=True, exist_ok=True)
    concatenated = version_dir / f"_concat_{version}.mp4"
    final_path = pdir / out_name

    log(f"{version}] クリップ結合中... ({len(clip_paths)}第�B��ۘ�]��\��\�]�\�X�ܘ][��ۘ�][�]Y
B�������ݙ\��[۟WH9���j]�8���l.�d"8���f�.+K����B�[���H]^��]�]\�X���ۘ�][�]Y�]Y[��]��[�[�]�]Y[�٘YW�[�Y��]
Z^�ٙ˙�]
�]Y[�٘YW�[���XȋK�
JK�]Y[�٘YW��]Y��]
Z^�ٙ˙�]
�]Y[�٘YW��]��Xȋ��
JK��Y[�٘YW��]Y��]
Z^�ٙ˙�]
��Y[�٘YW��]��XȋK�
JK�
B������ݙ\��[۟WH9k�8��x�ya�b���ٚ[�[�]H
�[����ٚ[�[�\�][ۗ��X��_\�[�O^�[�����\�][ۗ�[�I�_JH�B��]\���[�[�]