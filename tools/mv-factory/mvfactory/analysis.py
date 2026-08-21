"""工程2: 曲構成解析。

軽量な実装方針(librosa等の重い依存を避ける、要件定義書の指示どおり):
  - 尺・サンプルレート等のメタ情報: ffprobe
  - BPM推定: ffmpeg単体では困難なため、まず「セクション均等分割 + デフォルトBPM」の
    ルールベースにフォールバックする。歌詞タイムスタンプが取れる場合は
    そこから簡易的にセクション境界を推定する。
  - セクション区切り: 歌詞テキストの空行区切り(Aメロ/サビ等のブロック分け)を
    優先的に使う。歌詞に空行区切りがなければ、尺を均等分割してセクションを作る。
  - Whisperタイムスタンプ: 手持ち音源にボーカルがある場合、short-video-editor
    スキルと同じ Whisper API 呼び出しパターンを流用可能(OPENAI_API_KEY要)。
    本モジュールはWhisper連携をオプション機能として提供し、キー未設定/
    呼び出し失敗時はルールベースにフォールバックする(解析誤差時のフォールバック方針)。

出力スキーマ: song_structure.json (詳細はREADME.md参照)
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .common import log, write_json

DEFAULT_BPM = 120.0
DEFAULT_SECTION_NAMES = ["intro", "verse1", "chorus1", "verse2", "chorus2", "bridge", "outro"]


def ffprobe_duration_sec(audio_path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def read_lyrics_blocks(lyrics_path: Path) -> List[List[str]]:
    """空行区切りで歌詞をブロック分割する(Aメロ/サビ等の簡易境界推定)。"""
    if not lyrics_path.exists():
        return []
    text = lyrics_path.read_text(encoding="utf-8")
    raw_blocks = [b.strip("\n") for b in text.split("\n\n")]
    blocks = []
    for b in raw_blocks:
        lines = [ln for ln in b.splitlines() if ln.strip()]
        if lines:
            blocks.append(lines)
    return blocks


def try_whisper_word_timestamps(audio_path: Path) -> Optional[List[Dict[str, Any]]]:
    """OPENAI_API_KEYがあればWhisper APIでワードタイムスタンプを取得する(任意)。

    short-video-editor スキルと同じ発想(ミリ秒単位管理)を踏襲するが、
    依存を最小限にするため openai パッケージが無い場合は None を返し
    呼び出し元でルールベースにフォールバックさせる。
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        log("openai パッケージ未インストールのため歌詞タイムスタンプ解析をスキップします")
        return None

    try:
        client = OpenAI(api_key=api_key)
        with audio_path.open("rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["word"],
            )
        words = getattr(resp, "words", None)
        if not words:
            return None
        return [
            {"word": w.word, "start_ms": int(w.start * 1000), "end_ms": int(w.end * 1000)}
            for w in words
        ]
    except Exception as e:  # noqa: BLE001
        log(f"Whisper解析に失敗、ルールベースにフォールバックします: {e}")
        return None


def build_sections(
    duration_sec: float,
    lyrics_blocks: List[List[str]],
    word_timestamps: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    n = len(lyrics_blocks) if lyrics_blocks else 6
    n = max(n, 3)
    names = (DEFAULT_SECTION_NAMES * ((n // len(DEFAULT_SECTION_NAMES)) + 1))[:n]

    sections = []
    if word_timestamps:
        # ボーカル開始・終了を利用してintro/outroを分離しつつ均等割り
        total_words = len(word_timestamps)
        per = max(total_words // max(n - 2, 1), 1)
        vocal_start = word_timestamps[0]["start_ms"] / 1000.0
        vocal_end = word_timestamps[-1]["end_ms"] / 1000.0
        sections.append({"name": "intro", "start_sec": 0.0, "end_sec": round(vocal_start, 2)})
        idx = 0
        for i in range(1, n - 1):
            name = names[i]
            chunk = word_timestamps[idx: idx + per]
            idx += per
            if not chunk:
                continue
            start = chunk[0]["start_ms"] / 1000.0
            end = chunk[-1]["end_ms"] / 1000.0
            sections.append({"name": name, "start_sec": round(start, 2), "end_sec": round(end, 2)})
        sections.append({"name": "outro", "start_sec": round(vocal_end, 2), "end_sec": round(duration_sec, 2)})
    else:
        # ルールベース: 均等分割
        step = duration_sec / n
        for i in range(n):
            sections.append({
                "name": names[i],
                "start_sec": round(step * i, 2),
                "end_sec": round(step * (i + 1), 2),
            })

    # 歌詞行を割り当て(可能な範囲で)
    for i, sec in enumerate(sections):
        if lyrics_blocks and i < len(lyrics_blocks):
            sec["lyrics"] = lyrics_blocks[i]
        else:
            sec["lyrics"] = []

    return sections


def analyze_song(audio_path: Path, lyrics_path: Path) -> Dict[str, Any]:
    duration_sec = ffprobe_duration_sec(audio_path)
    lyrics_blocks = read_lyrics_blocks(lyrics_path)
    word_timestamps = try_whisper_word_timestamps(audio_path)
    sections = build_sections(duration_sec, lyrics_blocks, word_timestamps)

    analysis_method = {
        "duration": "ffprobe",
        "sections": "whisper_word_timestamps" if word_timestamps else "rule_based_even_split",
        "bpm": "default_fallback",
        "fallback_used": word_timestamps is None,
    }

    structure = {
        "schema_version": 1,
        "duration_sec": round(duration_sec, 2),
        "bpm": DEFAULT_BPM,
        "bpm_confidence": "low",
        "sections": sections,
        "word_timestamps": word_timestamps or [],
        "analysis_method": analysis_method,
        "manual_correction_hint": (
            "BPM・セクション境界は簡易推定です。精度が必要な場合は"
            "song_structure.json を直接編集して手動補正してください"
            "(sections[].start_sec/end_sec, bpm を上書き可能)。"
        ),
    }
    return structure


def run_step2(pdir: Path) -> Dict[str, Any]:
    audio_candidates = list(pdir.glob("song.mp3")) + list(pdir.glob("song.wav"))
    if not audio_candidates:
        raise FileNotFoundError(f"song.mp3/song.wav が見つかりません: {pdir}")
    audio_path = audio_candidates[0]
    lyrics_path = pdir / "lyrics.txt"

    structure = analyze_song(audio_path, lyrics_path)
    out_path = pdir / "song_structure.json"
    write_json(out_path, structure)
    log(f"song_structure.json を書き出しました: {out_path}")
    return structure
