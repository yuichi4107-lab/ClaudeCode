"""完成動画の機械検証（字幕正確性の「検証層」+「仕様層」）。

- Whisper逆文字起こし → 台本読み仮名と行単位CER突合（local whisper.cpp / OpenAI API）
- ffprobe: 解像度・コーデック・尺
- blackdetect: 黒フレーム
- ebur128: ラウドネス
- ファイルサイズ

LLM不要・全てローカル/決定的に動くため launchd 無人実行でも堅牢。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .config import CONFIG
from .jp_text import contained_cer, phonetic_cer, phonetic_hira

FF = CONFIG.get("ffmpeg", default="ffmpeg")
FFPROBE = CONFIG.get("ffprobe", default="ffprobe")


def _run_text(cmd: list[str]) -> str:
    proc = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    return (proc.stdout or "") + (proc.stderr or "")


# ---------- Whisper 逆文字起こし ----------

def _transcribe_local(wav: Path, work: Path) -> list[dict]:
    """whisper.cpp で文字起こし。[{start, end, text}] (秒) を返す。"""
    wav16 = work / "verify_16k.wav"
    subprocess.run(
        [FF, "-y", "-i", str(wav), "-ar", "16000", "-ac", "1", str(wav16)],
        capture_output=True,
    )
    prefix = work / "whisper_out"
    cmd = [
        CONFIG.get("verify", "whisper_bin"),
        "-m", CONFIG.get("verify", "whisper_model"),
        "-l", "ja",
        "-f", str(wav16),
        "-oj", "-of", str(prefix), "-np",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    jpath = Path(str(prefix) + ".json")
    if proc.returncode != 0 or not jpath.exists():
        raise RuntimeError(f"whisper-cli失敗 rc={proc.returncode}: {proc.stderr[:300]}")
    data = json.loads(jpath.read_text(encoding="utf-8"))
    segs = []
    for s in data.get("transcription", []):
        off = s.get("offsets", {})
        segs.append(
            {
                "start": off.get("from", 0) / 1000.0,
                "end": off.get("to", 0) / 1000.0,
                "text": s.get("text", "").strip(),
            }
        )
    return segs


def _transcribe_openai(wav: Path, work: Path) -> list[dict]:
    from openai import OpenAI

    client = OpenAI(api_key=CONFIG.openai_api_key)
    with open(wav, "rb") as f:
        resp = client.audio.transcriptions.create(
            model="whisper-1", file=f, language="ja", response_format="verbose_json"
        )
    return [
        {"start": s.start, "end": s.end, "text": s.text.strip()} for s in resp.segments
    ]


def transcribe(wav: Path, work: Path) -> list[dict]:
    provider = CONFIG.get("verify", "whisper_provider", default="local")
    if provider == "openai" and CONFIG.openai_api_key:
        return _transcribe_openai(wav, work)
    return _transcribe_local(wav, work)


# ---------- 字幕CER突合 ----------

def _best_window_cer(cue_norm: str, full_norm: str) -> float:
    """全文の中から最も近い窓を探してCERを返す（タイユスタンプずれ救済用）。"""
    return contained_cer(cue_norm, full_norm)


def check_subtitle_accuracy(
    cues: list[dict], segs: list[dict], cer_line_max: float | None = None
) -> dict:
    """各キューの台本文とWhisper結果を音韻ベース（両辺ひらがな読み化）で突合。

    Args:
        cer_line_max: 行ごとのCER上限。省略時は verify.cer_line_max（VOICEVOX向け）。
            Seedance音声はTTSの読み仮名保証が無いため、呼び出し元が
            seedance.cer_line_max を渡してしきい値を緩めるのが標準。
    """
    full_text = "".join(s["text"] for s in segs)
    full_norm = phonetic_hira(full_text)
    line_max = (
        float(cer_line_max)
        if cer_line_max is not None
        else float(CONFIG.get("verify", "cer_line_max", default=0.20))
    )

    results = []
    for c in cues:
        ref = c["tts_text"]
        # 1) タイユスタンプの重なるセグメントで比較
        window = [
            s for s in segs
            if (s["start"] + s["end"]) / 2 >= c["start"] - 0.35
            and (s["start"] + s["end"]) / 2 <= c["end"] + 0.35
        ]
        heard = "".join(s["text"] for s in window)
        c_cer = phonetic_cer(ref, heard) if heard else 1.0
        # 2) ずれ救済: 全文ベストウィンドウ
        if c_cer > line_max:
            c_cer = min(c_cer, _best_window_cer(phonetic_hira(ref), full_norm))
        results.append(
            {
                "index": c["index"],
                "cer": round(c_cer, 4),
                "pass": c_cer <= line_max,
                "heard": heard[:60],
                "display": " / ".join(c["display"]),
            }
        )
    global_cer = phonetic_cer("".join(c["tts_text"] for c in cues), full_text)
    avg = sum(r["cer"] for r in results) / len(results) if results else 1.0
    return {
        "global_cer": round(global_cer, 4),
        "avg_cer": round(avg, 4),
        "lines": results,
        "failed_indices": [r["index"] for r in results if not r["pass"]],
        "whisper_text": full_text,
    }


# ---------- 仕様検査 ----------

def probe(path: Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
    )
    return json.loads(out.stdout)


def measure_lufs(path: Path) -> float | None:
    txt = _run_text([FF, "-i", str(path), "-filter:a", "ebur128", "-f", "null", "-"])
    m = re.findall(r"I:\s*(-?[\d.]+)\s*LUFS", txt)
    return float(m[-1]) if m else None


def detect_black(path: Path) -> list[str]:
    txt = _run_text(
        [FF, "-i", str(path), "-vf", "blackdetect=d=0.3:pix_th=0.10", "-an", "-f", "null", "-"]
    )
    return re.findall(r"black_start:[\d.]+ black_end:[\d.]+", txt)


def verify_video(
    final: Path,
    cues: list[dict],
    total_dur: float,
    work: Path,
    cer_line_max: float | None = None,
    cer_avg_max: float | None = None,
) -> dict:
    """全検査を実行して quality_report 形式の dict を返す。

    cer_line_max / cer_avg_max を指定すると、その動画だけしきい値を上書きできる
    （Seedance音声版はVOICEVOXより発音ゆれが大きいため緩めた値を使う）。
    """
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "pass": bool(ok), "detail": detail})

    info = probe(final)
    v = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), {})
    dur = float(info.get("format", {}).get("duration", 0))
    size_mb = final.stat().st_size / 1024 / 1024

    add("resolution", v.get("width") == 1080 and v.get("height") == 1920,
        f"{v.get('width')}x{v.get('height')}")
    add("codecs", v.get("codec_name") == "h264" and a.get("codec_name") == "aac",
        f"v={v.get('codec_name')} a={a.get('codec_name')}")
    min_s = float(CONFIG.get("video", "min_sec", default=30)) - 5
    max_s = float(CONFIG.get("video", "max_sec", default=60)) + 5
    add("duration", min_s <= dur <= max_s, f"{dur:.1f}s (許容{min_s:.0f}〜{max_s:.0f})")
    add("filesize", size_mb <= float(CONFIG.get("video", "max_mb", default=50)),
        f"{size_mb:.1f}MB")

    blacks = detect_black(final)
    add("no_black_frames", len(blacks) == 0, "; ".join(blacks) or "黒フレームなし")

    lufs = measure_lufs(final)
    target = float(CONFIG.get("verify", "lufs_target", default=-14.0))
    tol = float(CONFIG.get("verify", "lufs_tol", default=2.0))
    add("loudness", lufs is not None and abs(lufs - target) <= tol,
        f"{lufs} LUFS (目標{target}±{tol})")

    add("subtitle_within_audio",
        all(c["end"] <= total_dur + 0.6 for c in cues),
        f"最終字幕end={cues[-1]['end']:.2f}s / 音声{total_dur:.2f}s")

    # 字幕正確性（Whisper逆突合）
    segs = transcribe(final, work)
    acc = check_subtitle_accuracy(cues, segs, cer_line_max=cer_line_max)
    avg_max = (
        float(cer_avg_max)
        if cer_avg_max is not None
        else float(CONFIG.get("verify", "cer_avg_max", default=0.10))
    )
    line_max_display = (
        cer_line_max if cer_line_max is not None else CONFIG.get("verify", "cer_line_max")
    )
    add("subtitle_accuracy_lines", not acc["failed_indices"],
        f"不合格行 {acc['failed_indices']}（行CER上限{line_max_display}）")
    add("subtitle_accuracy_avg", acc["avg_cer"] <= avg_max,
        f"平均CER={acc['avg_cer']} (上限{avg_max}) / 全文CER={acc['global_cer']}")

    report = {
        "pass": all(c["pass"] for c in checks),
        "checks": checks,
        "accuracy": acc,
        "duration": dur,
        "size_mb": round(size_mb, 2),
        "lufs": lufs,
    }
    return report
