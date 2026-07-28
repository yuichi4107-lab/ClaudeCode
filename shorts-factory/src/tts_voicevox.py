"""VOICEVOX エンジンによる文単位TTS。

字幕正確性の「合成層」防御:
- 字幕1キュー = TTS1チャンク。各wavの実測長から字幕タイミングを機械的に確定
  するため、音声と字幕の同期ずれは構造上発生しない。
- audio_query が返す読み仮名と台本の reading_kana を突合し、乖離が大きい
  キューは reading_kana 直読みに切り替える（漢字誤読・英語誤読の防止）。
- 頻出AI用語は起動時にユーザー辞書へ登録する。
"""
from __future__ import annotations

import json
import subprocess
import time
import wave
from pathlib import Path

import requests

from .config import CONFIG
from .jp_text import TERM_READINGS, enhance_tts_clarity, kana_cer

_BASE = f"http://{CONFIG.get('tts', 'host')}:{CONFIG.get('tts', 'port')}"
_started_proc: subprocess.Popen | None = None


def engine_alive() -> bool:
    try:
        return requests.get(f"{_BASE}/version", timeout=2).status_code == 200
    except requests.RequestException:
        return False


def ensure_engine(timeout: int = 90) -> None:
    """エンジンが起動していなければ起動して疎通を待つ。"""
    global _started_proc
    if engine_alive():
        return
    engine_dir = Path(CONFIG.get("tts", "engine_dir"))
    run_bin = engine_dir / "run"
    if not run_bin.exists():
        raise RuntimeError(f"VOICEVOXエンジンが見つかりません: {run_bin}")
    log = open(CONFIG.logs_dir / "voicevox_engine.log", "ab")
    _started_proc = subprocess.Popen(
        [str(run_bin), "--host", CONFIG.get("tts", "host"), "--port", str(CONFIG.get("tts", "port"))],
        stdout=log,
        stderr=log,
        cwd=str(engine_dir),
    )
    deadline = time.time() + timeout
    while time.time() < deadline:
        if engine_alive():
            return
        if _started_proc.poll() is not None:
            raise RuntimeError("VOICEVOXエンジンが起動直後に終了しました（logs/voicevox_engine.log参照）")
        time.sleep(1.5)
    raise RuntimeError(f"VOICEVOXエンジンが{timeout}秒以内に応答しません")


def shutdown_engine() -> None:
    """このプロセスが起動したエンジンのみ停止する。"""
    global _started_proc
    if _started_proc and _started_proc.poll() is None:
        _started_proc.terminate()
        try:
            _started_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _started_proc.kill()
    _started_proc = None


def apply_user_dict() -> int:
    """TERM_READINGS をユーザー辞書へ登録・更新する。変更件数を返す。"""
    existing = requests.get(f"{_BASE}/user_dict", timeout=10).json()
    by_surface = {w.get("surface"): (uuid, w) for uuid, w in existing.items()}
    changed = 0
    for surface, pron in TERM_READINGS.items():
        cur = by_surface.get(surface)
        if cur and cur[1].get("pronunciation") == pron:
            continue
        params = {"surface": surface, "pronunciation": pron, "accent_type": 0}
        if cur:
            r = requests.put(
                f"{_BASE}/user_dict_word/{cur[0]}", params=params, timeout=10
            )
        else:
            r = requests.post(f"{_BASE}/user_dict_word", params=params, timeout=10)
        if r.status_code in (200, 204):
            changed += 1
    return changed


def _audio_query(text: str, speaker: int) -> dict:
    r = requests.post(
        f"{_BASE}/audio_query", params={"text": text, "speaker": speaker}, timeout=30
    )
    r.raise_for_status()
    return r.json()


def _synthesis(query: dict, speaker: int) -> bytes:
    r = requests.post(
        f"{_BASE}/synthesis",
        params={"speaker": speaker},
        json=query,
        timeout=120,
    )
    r.raise_for_status()
    return r.content


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def synthesize_cues(
    cues: list[dict],
    work_dir: Path,
    *,
    speaker_id: int | None = None,
    speed_scale: float | None = None,
) -> dict:
    """全キューを合成し、タイミング情報付きで返す。

    Returns:
        {
          "cues": [{..cue, "wav": path, "dur": float, "start": float, "end": float,
                     "used_kana_fallback": bool, "kana_cer": float}],
          "master_wav": path, "total_dur": float
        }
    """
    ensure_engine()
    apply_user_dict()
    speaker = int(speaker_id if speaker_id is not None else CONFIG.get("speaker_id", default=3))
    speed = float(speed_scale if speed_scale is not None else CONFIG.get("speed_scale", default=1.0))
    sr = int(CONFIG.get("tts", "output_sampling_rate", default=48000))
    mismatch_th = float(CONFIG.get("tts", "kana_mismatch_cer", default=0.15))

    wav_dir = work_dir / "tts"
    wav_dir.mkdir(parents=True, exist_ok=True)

    out_cues: list[dict] = []
    for i, cue in enumerate(cues):
        text = enhance_tts_clarity(cue["tts_text"].strip())
        ref_kana = enhance_tts_clarity(cue["reading_kana"].strip())
        force_kana = bool(cue.get("force_kana"))

        use_text = ref_kana if force_kana else text
        query = _audio_query(use_text, speaker)
        mismatch = kana_cer(ref_kana, query.get("kana", ""))
        used_fallback = force_kana
        if not force_kana and mismatch > mismatch_th:
            # 意図した読みと乖離 → 読み仮名を直接読ませて発音を保証する
            query = _audio_query(ref_kana, speaker)
            mismatch = kana_cer(ref_kana, query.get("kana", ""))
            used_fallback = True

        query["speedScale"] = speed
        query["outputSamplingRate"] = sr
        query["outputStereo"] = False
        query["prePhonemeLength"] = 0.05
        query["postPhonemeLength"] = 0.05

        wav_path = wav_dir / f"cue_{i:02d}.wav"
        wav_path.write_bytes(_synthesis(query, speaker))
        dur = _wav_duration(wav_path)
        out = dict(cue)
        out.update(
            {
                "index": i,
                "wav": str(wav_path),
                "dur": round(dur, 3),
                "used_kana_fallback": used_fallback,
                "kana_cer": round(mismatch, 4),
            }
        )
        out_cues.append(out)

    # タイムライン確定（lead_in + Σ(dur+gap)）→ 字幕は次キュー開始まで表示
    lead = float(CONFIG.get("video", "lead_in_sec", default=0.4))
    gap = float(CONFIG.get("video", "cue_gap_sec", default=0.18))
    tail = float(CONFIG.get("video", "tail_sec", default=0.8))
    t = lead
    for c in out_cues:
        c["start"] = round(t, 3)
        c["end"] = round(t + c["dur"], 3)
        t = c["end"] + gap
    total = t - gap + tail

    master = work_dir / "master_voice.wav"
    _concat_wavs(out_cues, master, sr, lead, gap, total)
    return {"cues": out_cues, "master_wav": str(master), "total_dur": round(total, 3)}


def _concat_wavs(
    cues: list[dict], out_path: Path, sr: int, lead: float, gap: float, total: float
) -> None:
    """無音を挟みながら1本のwav（16bit mono）へ連結する。"""

    def silence(sec: float) -> bytes:
        return b"\x00\x00" * int(sr * max(sec, 0))

    with wave.open(str(out_path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sr)
        out.writeframes(silence(lead))
        for i, c in enumerate(cues):
            with wave.open(c["wav"], "rb") as w:
                assert w.getframerate() == sr and w.getnchannels() == 1, "TTS wavフォーマット不一致"
                out.writeframes(w.readframes(w.getnframes()))
            if i < len(cues) - 1:
                out.writeframes(silence(gap))
        out.writeframes(silence(total - (cues[-1]["end"] if cues else lead)))


def resynth_cues(tts_result: dict, indices: list[int], work_dir: Path) -> dict:
    """指定キューを reading_kana 直読みで再合成し、タイムラインを組み直す。

    検証層で発音不一致が出たキューの自動修正に使う。
    """
    ensure_engine()
    speaker = int(CONFIG.get("speaker_id", default=3))
    speed = float(CONFIG.get("speed_scale", default=1.0))
    sr = int(CONFIG.get("tts", "output_sampling_rate", default=48000))

    cues = tts_result["cues"]
    for i in indices:
        c = cues[i]
        query = _audio_query(enhance_tts_clarity(c["reading_kana"].strip()), speaker)
        query["speedScale"] = speed
        query["outputSamplingRate"] = sr
        query["outputStereo"] = False
        query["prePhonemeLength"] = 0.05
        query["postPhonemeLength"] = 0.05
        wav_path = Path(c["wav"])
        wav_path.write_bytes(_synthesis(query, speaker))
        c["dur"] = round(_wav_duration(wav_path), 3)
        c["used_kana_fallback"] = True

    return rebuild_timeline(cues, work_dir, sr)


def rebuild_timeline(cues: list[dict], work_dir: Path, sr: int | None = None) -> dict:
    """既存のキューwav群からタイムラインとmasterを再構築する。"""
    sr = sr or int(CONFIG.get("tts", "output_sampling_rate", default=48000))
    lead = float(CONFIG.get("video", "lead_in_sec", default=0.4))
    gap = float(CONFIG.get("video", "cue_gap_sec", default=0.18))
    tail = float(CONFIG.get("video", "tail_sec", default=0.8))
    t = lead
    for c in cues:
        c["start"] = round(t, 3)
        c["end"] = round(t + c["dur"], 3)
        t = c["end"] + gap
    total = t - gap + tail
    master = work_dir / "master_voice.wav"
    _concat_wavs(cues, master, sr, lead, gap, total)
    return {"cues": cues, "master_wav": str(master), "total_dur": round(total, 3)}


def speaker_names() -> dict[int, str]:
    """利用可能な話者一覧（id→名前）。デバッグ用。"""
    ensure_engine()
    out: dict[int, str] = {}
    for sp in requests.get(f"{_BASE}/speakers", timeout=10).json():
        for st in sp.get("styles", []):
            out[st["id"]] = f"{sp['name']}（{st['name']}）"
    return out
