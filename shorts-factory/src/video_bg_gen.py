"""Atlas Cloud Seedance 2.0 API クライアント（AI動画背景生成）。

カット1は text-to-video、カット2以降は前カットの最終フレームを
start_image にした image-to-video で連鎖生成し、人物・服装・部屋を統一する。

参考実装: tools/seedance-api-compare/sample_short.py, sample_short_v2.py
（サンプル制作で確定した技術知見。詳細は
 .company/projects/shorts-factory/2026-07-07-seedance-atlas統合要件定義.md）

技術知見（本番実装の必須要件）:
- reference-to-video（顔画像参照）は権利保護フィルタで弾かれるため使用しない。
  人物統一は「前カット最終フレーム→次カットstart_image」の連鎖方式で行う。
- プロンプトには毎カット、服装・部屋・カメラフレーミング維持の固定句を必ず含める。
  書き忘れるとカット間で服・背景が変わる。
- Cloudflareが標準UAを403で弾くため、全リクエストにUser-Agentヘッダーが必須。
- 生成された動画URLは24時間で失効するため、completed直後に即ダウンロードする。
- 失敗（failed/timeout/フィルタブロック）時は課金されない（実測確認済み）。

コスト計算: 秒数 × 単価（std=$0.112/s, fast=$0.09/s）。
呼び出し元（pipeline.py）がコストログを記録する。
"""
from __future__ import annotations

import base64
import json
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import CONFIG
from .logging_utils import redact_secrets

ATLAS_BASE = "https://api.atlascloud.ai/api/v1/model"
MODEL_T2V = "bytedance/seedance-2.0-fast/text-to-video"
MODEL_I2V = "bytedance/seedance-2.0-fast/image-to-video"
USER_AGENT = "shorts-factory-seedance/1.0"

# モデル別の秒単価（USD）。モデル変更時はここだけ追従すればよい。
PRICE_PER_SEC = {
    "std": 0.112,
    "fast": 0.09,
}

# カット2以降のプロンプトに毎回必ず付与する固定句。
# 服装・部屋・カメラフレーミングの明示を書き忘れると、カット間で
# 服や背景が変わってしまう（v2のカット3で実証済みの不具合）。
CONTINUITY_SUFFIX = (
    " Preserve the exact same facial identity from the start image, not just a similar person: "
    "same slightly long rectangular face, same calm sharp eyes, same medium complexion, "
    "same hairline, same short side-parted black hair with slight gray at the temples, "
    "same clean-shaven look, same age, same outfit, same navy suit, same white shirt, "
    "same dark tie, same room, and same locked-off bust-up camera framing as before. "
    "Do not zoom in, push in, change the background, change clothing, alter the face, "
    "change hairstyle, change gray hair amount, add or remove facial hair, or change the camera angle."
)


class SeedanceError(Exception):
    """Atlas Cloud API呼び出し・生成失敗を表す基底例外。呼び出し元はこれを
    捕捉してフォールバック（静止画カード版）へ切り替える。"""


class SeedanceConfigError(SeedanceError):
    """APIキー未設定など、設定不備による失敗。"""


class SeedanceAPIError(SeedanceError):
    """HTTP通信・レスポンス形式の異常。"""


class SeedanceGenerationFailed(SeedanceError):
    """ジョブが failed/error ステータスで終わった場合。"""


class SeedanceTimeout(SeedanceError):
    """ポーリングがタイムアウト上限に達した場合。"""


@dataclass
class CutResult:
    """1カット分の生成結果。"""

    name: str
    path: Path
    duration_sec: float
    model: str  # "std" | "fast"
    job_id: str
    elapsed_sec: float


@dataclass
class GenerationCostRecord:
    """コスト計測ログ1件分。pipeline側でJSONLに追記する。"""

    video_id: str
    cut_count: int
    total_duration_sec: float
    model: str
    unit_price_per_sec: float
    cost_usd: float
    success: bool
    timestamp: str
    detail: str = ""


def _api_key() -> str:
    key = CONFIG.atlas_cloud_api_key
    if not key:
        raise SeedanceConfigError(
            "Atlas Cloud APIキーが未設定です（secrets.yaml の atlas_cloud.api_key "
            "または環境変数 ATLAS_CLOUD_API_KEY を設定してください）"
        )
    return key


def _poll_interval_sec() -> float:
    return float(CONFIG.get("seedance", "poll_interval_sec", default=15))


def _timeout_sec() -> float:
    return float(CONFIG.get("seedance", "timeout_sec", default=30 * 60))


def _model_name() -> str:
    """configで指定されたモデル種別（std|fast）。"""
    return str(CONFIG.get("seedance", "model", default="fast"))


def estimate_cost(duration_sec: float, model: str | None = None) -> float:
    """秒数×単価でコストを見積もる。単価は PRICE_PER_SEC を参照する。"""
    model = model or _model_name()
    unit = PRICE_PER_SEC.get(model, PRICE_PER_SEC["fast"])
    return round(duration_sec * unit, 4)


def _http_json(method: str, url: str, api_key: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:1000]
        # APIキーはヘッダーにのみ含まれ、URLやボディには出ないが念のためredact
        raise SeedanceAPIError(
            redact_secrets(f"HTTP {e.code} {url}\n{body}", [api_key])
        ) from e
    except urllib.error.URLError as e:
        raise SeedanceAPIError(redact_secrets(f"通信エラー: {e}", [api_key])) from e


def _download(url: str, dest: Path) -> None:
    """動画URL（24時間で失効）から即座にダウンロードする。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
    except (urllib.error.URLError, OSError) as e:
        raise SeedanceAPIError(f"動画ダウンロード失敗: {e}") from e


def last_frame_b64(video: Path) -> str:
    """動画の最終フレームをJPEGで抽出し、data URI（base64）にする。

    ffmpegで抽出した最終フレームを次カットのstart_imageに渡すことで、
    reference-to-video（権利フィルタで弾かれる）を使わずに人物を統一する。
    """
    tmp = video.with_suffix(".lastframe.jpg")
    ffmpeg_bin = CONFIG.get("ffmpeg", default="ffmpeg")
    proc = subprocess.run(
        [
            str(ffmpeg_bin), "-y", "-sseof", "-0.5", "-i", str(video),
            "-frames:v", "1", "-q:v", "2", "-loglevel", "error", str(tmp),
        ],
        capture_output=True,
    )
    if proc.returncode != 0 or not tmp.exists():
        raise SeedanceAPIError(
            f"最終フレーム抽出失敗（ffmpeg rc={proc.returncode}）: "
            f"{proc.stderr.decode('utf-8', errors='replace')[:300]}"
        )
    b64 = base64.b64encode(tmp.read_bytes()).decode()
    tmp.unlink(missing_ok=True)
    return f"data:image/jpeg;base64,{b64}"


def _poll_job(job_id: str, api_key: str, out_path: Path, label: str) -> tuple[Path, float]:
    """ジョブをポーリングし、completedになったら即ダウンロードする。

    Returns:
        (ダウンロード先パス, 経過秒数)
    """
    interval = _poll_interval_sec()
    timeout = _timeout_sec()
    started = time.time()
    while time.time() - started < timeout:
        time.sleep(interval)
        status_resp = _http_json("GET", f"{ATLAS_BASE}/prediction/{job_id}", api_key)
        data = status_resp.get("data", status_resp)
        status = str(data.get("status", "")).lower()
        if status == "completed":
            outputs = data.get("outputs") or []
            if not outputs:
                raise SeedanceGenerationFailed(f"[{label}] completedだがoutputsが空")
            _download(outputs[0], out_path)
            return out_path, time.time() - started
        if status in ("failed", "timeout", "error"):
            detail = str(data.get("error") or "")[:300]
            raise SeedanceGenerationFailed(f"[{label}] 生成失敗（status={status}）: {detail}")
        # processing 等の未確定ステータスはポーリング継続
    raise SeedanceTimeout(f"[{label}] {timeout:.0f}秒でタイムアウト（job={job_id}）")


def generate_video(
    prompt: str,
    duration: int,
    out_path: Path,
    *,
    resolution: str = "720p",
    mode: str = "text-to-video",
    start_image_b64: str | None = None,
    ratio: str = "9:16",
    generate_audio: bool = True,
    watermark: bool = False,
    seed: int | None = None,
    model: str | None = None,
    label: str = "cut",
) -> tuple[Path, float]:
    """1カット分の動画を生成し、ローカルにダウンロードする。

    Args:
        prompt: 英語プロンプト（カット2以降はCONTINUITY_SUFFIXを付与すること）
        duration: 秒数
        out_path: ダウンロード先
        resolution: "720p" 等
        mode: "text-to-video" | "image-to-video"
        start_image_b64: image-to-videoの場合のstart_image（data URI）
        ratio: アスペクト比
        generate_audio: Seedanceネイティブ音声を生成するか
        watermark: 透かしを入れるか
        seed: 固定するとスタイルの一貫性が上がる
        model: "std" | "fast"（省略時はconfigのseedance.model）
        label: ログ・エラーメッセージ用のカット名

    Returns:
        (ダウンロードされたmp4のパス, 生成にかかった経過秒数)

    Raises:
        SeedanceConfigError: APIキー未設定
        SeedanceAPIError: HTTP/通信エラー
        SeedanceGenerationFailed: ステータスfailed/error、権利フィルタブロック等
        SeedanceTimeout: ポーリングタイムアウト
    """
    if mode == "image-to-video" and not start_image_b64:
        raise ValueError("image-to-videoモードには start_image_b64 が必須です")

    api_key = _api_key()
    model = model or _model_name()
    model_id = MODEL_I2V if mode == "image-to-video" else MODEL_T2V

    payload: dict = {
        "model": model_id.replace("seedance-2.0-fast", f"seedance-2.0-{model}"),
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "ratio": ratio,
        "generate_audio": generate_audio,
        "watermark": watermark,
    }
    if seed is not None:
        payload["seed"] = seed
    if mode == "image-to-video":
        payload["start_image"] = start_image_b64

    resp = _http_json("POST", f"{ATLAS_BASE}/generateVideo", api_key, payload)
    job_id = (resp.get("data") or {}).get("id") or resp.get("id")
    if not job_id:
        raise SeedanceAPIError(
            f"[{label}] ジョブ投入失敗（idが取得できない）: "
            f"{json.dumps(resp, ensure_ascii=False)[:400]}"
        )
    return _poll_job(job_id, api_key, out_path, label)


@dataclass
class ChainConfig:
    """連鎖生成（カット1: t2v → カット2以降: i2v連鎖）の設定。"""

    cuts: list[dict] = field(default_factory=list)  # [{"name": str, "prompt": str, "duration": int}]
    resolution: str = "720p"
    ratio: str = "9:16"
    generate_audio: bool = True
    watermark: bool = False
    seed: int | None = 42
    model: str | None = None


def generate_chained_cuts(config: ChainConfig, work_dir: Path) -> list[CutResult]:
    """カット1をtext-to-video、カット2以降を前カット最終フレームからの
    image-to-video連鎖で生成する。

    途中のカットが失敗した場合は例外を送出する（呼び出し元でフォールバック判断）。
    連鎖生成は逐次実行のみ（並列不可）。
    """
    if not config.cuts:
        raise ValueError("cuts が空です")
    work_dir.mkdir(parents=True, exist_ok=True)
    results: list[CutResult] = []
    prev_path: Path | None = None

    for i, cut in enumerate(config.cuts):
        name = cut.get("name") or f"cut{i + 1}"
        prompt = cut["prompt"]
        duration = int(cut.get("duration", 10))
        out_path = work_dir / f"{name}.mp4"

        if i == 0:
            mode = "text-to-video"
            start_b64 = None
        else:
            mode = "image-to-video"
            start_b64 = last_frame_b64(prev_path)
            prompt = prompt + CONTINUITY_SUFFIX

        path, elapsed = generate_video(
            prompt,
            duration,
            out_path,
            resolution=config.resolution,
            mode=mode,
            start_image_b64=start_b64,
            ratio=config.ratio,
            generate_audio=config.generate_audio,
            watermark=config.watermark,
            seed=config.seed,
            model=config.model,
            label=name,
        )
        results.append(
            CutResult(
                name=name,
                path=path,
                duration_sec=float(duration),
                model=config.model or _model_name(),
                job_id="",
                elapsed_sec=elapsed,
            )
        )
        prev_path = path

    return results


def concat_cuts(cuts: list[CutResult], out_path: Path, work_dir: Path) -> Path:
    """生成済みカットを連結し、最終規格の1080x1920へアップスケールする。

    Seedance fastモデルの上限は720p(720x1280)のため、verifierの解像度
    チェック(1080x1920固定)に合わせて連結と同時に拡大する。
    """
    ffmpeg_bin = CONFIG.get("ffmpeg", default="ffmpeg")
    concat_list = work_dir / "seedance_concat.txt"
    concat_list.write_text(
        "".join(f"file '{c.path}'\n" for c in cuts), encoding="utf-8"
    )
    proc = subprocess.run(
        [
            str(ffmpeg_bin), "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-vf", "scale=1080:1920:flags=lanczos",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-c:a", "aac", "-b:a", "192k",
            "-loglevel", "error", str(out_path),
        ],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise SeedanceAPIError(
            f"ffmpeg連結失敗: {proc.stderr.decode('utf-8', errors='replace')[:400]}"
        )
    return out_path


# ===================== コスト計測ログ・月次予算制御（工程3） =====================
#
# 記録先: ~/shorts-factory/logs/seedance_costs.jsonl（1行1レコードのJSON Lines）
# 累計コストはこのログファイルを都度読み返して再計算する（別ストアを持たない）
# ことで、ログさえ残っていればいつでも再現可能にしている。

COST_LOG_NAME = "seedance_costs.jsonl"


def cost_log_path() -> Path:
    return CONFIG.logs_dir / COST_LOG_NAME


def record_cost(record: GenerationCostRecord) -> None:
    """1回の生成試行（成功/失敗問わず）をコストログに追記する。

    失敗時は実測どおり cost_usd=0（Atlas Cloudは失敗時無課金と実測確認済み）。
    """
    path = cost_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {
            "timestamp": record.timestamp,
            "video_id": record.video_id,
            "cut_count": record.cut_count,
            "total_duration_sec": record.total_duration_sec,
            "model": record.model,
            "unit_price_per_sec": record.unit_price_per_sec,
            "cost_usd": record.cost_usd,
            "success": record.success,
            "detail": record.detail,
        },
        ensure_ascii=False,
    )
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _read_cost_log() -> list[dict]:
    path = cost_log_path()
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def month_key(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%Y-%m")


def monthly_cost_total(month: str | None = None) -> float:
    """指定月（YYYY-MM、省略時は今月）の累計コスト（成功分のみ）をログから再計算する。"""
    month = month or month_key()
    total = 0.0
    for rec in _read_cost_log():
        ts = str(rec.get("timestamp", ""))
        if ts[:7] == month and rec.get("success"):
            try:
                total += float(rec.get("cost_usd", 0))
            except (TypeError, ValueError):
                continue
    return round(total, 4)


def budget_remaining(month: str | None = None) -> float:
    """今月の残り予算（USD）。monthly_budget_usd - 累計消費額。"""
    budget = float(CONFIG.get("seedance", "monthly_budget_usd", default=130.0))
    spent = monthly_cost_total(month)
    return round(budget - spent, 4)


def is_budget_available(estimated_cost: float, month: str | None = None) -> bool:
    """この動画を生成した場合に月間予算を超過しないかを判定する。

    生成前に呼び出し、超過が見込まれる場合は呼び出し元がフォールバックする。
    """
    remaining = budget_remaining(month)
    max_per_video = float(CONFIG.get("seedance", "max_cost_per_video_usd", default=10.0))
    if estimated_cost > max_per_video:
        return False
    return estimated_cost <= remaining



# ===================== 字幕タイミング確定（Seedance音声→whisper突合） =====================
#
# Seedance版はVOICEVOXのように「1キュー=1wav」の実測長が無いため、
# 各カットの尺（config固定値、例: 10秒）を境界にしてキューを並べたあと、
# whisper.cppの文字起こしセグメントとカット内での重なりを見てタイミングを微調整する。
# 完全一致しなくても、verifier.check_subtitle_accuracy が最終的に音韻CERで
# 正確性を検証するため、ここでは「字幕が音声とズレて表示されない」程度の
# 精度が出ればよい。


def assign_cue_timings_from_cuts(cues: list[dict], cut_results: list[CutResult]) -> list[dict]:
    """カットごとの尺を積み上げて各キューのstart/endを機械的に確定する。

    Seedanceの1カット=1キューという構成なので、カットの実尺（duration_sec）を
    そのままキューの表示区間として割り当てる。VOICEVOXのTTS実測長のような
    精密さは無いが、カット単位の動画なので字幕とカットの境界は必ず一致する。
    """
    if len(cues) != len(cut_results):
        raise ValueError(
            f"cues数({len(cues)})とcut_results数({len(cut_results)})が一致しません"
        )
    out_cues: list[dict] = []
    t = 0.0
    for i, (cue, cut) in enumerate(zip(cues, cut_results)):
        out = dict(cue)
        out["index"] = i
        out["start"] = round(t, 3)
        out["end"] = round(t + cut.duration_sec, 3)
        out["cut_name"] = cut.name
        out_cues.append(out)
        t += cut.duration_sec
    return out_cues


def make_cost_record(
    video_id: str,
    cuts: list[CutResult],
    success: bool,
    detail: str = "",
) -> GenerationCostRecord:
    """生成結果（成功/失敗）からコストレコードを組み立てる。"""
    model = _model_name()
    total_duration = sum(c.duration_sec for c in cuts) if success else 0.0
    cost = estimate_cost(total_duration, model) if success else 0.0
    return GenerationCostRecord(
        video_id=video_id,
        cut_count=len(cuts),
        total_duration_sec=total_duration,
        model=model,
        unit_price_per_sec=PRICE_PER_SEC.get(model, PRICE_PER_SEC["fast"]),
        cost_usd=cost,
        success=success,
        timestamp=datetime.now().astimezone().isoformat(timespec="seconds"),
        detail=detail,
    )
