"""工程5: シーン動画生成(Atlas Cloud Seedance 2.0)。

参考実装: tools/seedance-api-compare/compare_seedance.py の Atlas Cloud呼び凷゗、パターン(User-Agentヘッダー必須・非同期ポーリングほ即て一ムウンロード)を踏襲する。

要件定義書 工程5 完了条件への濖応:
  - エンドポイント: POST /generateVideo -> GET /prediction/{id}
  - User-Agentヘッダー必須(Cloudflareがpython模棥指定卐：
  - image-to-video: 参照画像を first_frame / first_last_frame として渡す
  - 動画URL失効対策: 生成完了検知後、即座にダウンロード
  - モデルID夔凬し: project.yaml の video_generation.model (.�nv のATLAS_MODELで上書き可)
  - 残高枯渇検知: 402/403/insufficient balance相当のエラーメッセージを検知して
    明確なエラーを出す
  - リトライ/スキップ方針: max_retries回リトライ、それでも失敗したらそのシーンを
    スキップしログに記録し、全体は継続する(1シーン失敗で全停止しない)
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..common import DEFAULT_ATLAS_MODEL, log

ATLAS_BASE = "https://api.atlascloud.ai/api/v1/model"
POLL_INTERVAL_SEC = 15
TIMEOUT_SEC = 30 * 60
USER_AGENT = "mv-factory/0.1"

BALANCE_ERROR_HINTS = (
    "insufficient", "balance", "402", "payment required", "top up", "topup", "credit",
)


class VideoGenerationError(RuntimeError):
    pass


class BalanceExhaustedError(VideoGenerationError):
    """Atlas Cloud残高枯渇と推定されるエラー。全自動フローを即座に止めるための専用例外。"""


def _api_key() -> str:
    key = os.environ.get("ATLAS_CLOUD_API_KEY") or os.environ.get("ATLAS_API_KEY")
    if not key:
        raise VideoGenerationError(
            "ATLAS_CLOUD_API_KEY が設定されていません。"
            "tools/mv-factory/.env に設定してください"
            "(tools/seedance-api-compare/.env と共通のキーを使い回せます)。"
        )
    return key


def _http_json(method: str, url: str, api_key: str, payload: Optional[dict] = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", USER_AGENT)  # Cloudflare対策、必須
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:2000]
        lower = body.lower()
        if e.code in (402, 403) and any(h in lower for h in BALANCE_ERROR_HINTS):
            raise BalanceExhaustedError(
                f"Atlas Cloudの残高が枯渇している可能性があります(HTTP {e.code}): {body}"
            ) from e
        raise VideoGenerationError(f"HTTP {e.code} {url}\n{body}") from e


def _image_to_data_uri(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "image/png"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(req, timeout=600) as resp, dest.open("wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def generate_clip(
    prompt: str,
    duration_sec: int,
    aspect_ratio: str,
    resolution: str,
    mode: str,
    dest_path: Path,
    first_frame_path: Optional[Path] = None,
    last_frame_path: Optional[Path] = None,
    model_override: Optional[str] = None,
    generate_audio: bool = False,
    watermark: bool = False,
) -> Dict[str, Any]:
    """1シーン分のクリップを生成し、即座に dest_path へダウンロードする。"""
    api_key = _api_key()

    default_model = model_override or os.environ.get("ATLAS_MODEL") or DEFAULT_ATLAS_MODEL
    if mode == "fast" and "fast" not in default_model:
        default_model = default_model.replace("seedance-2.0", "seedance-2.0-fast")

    payload: Dict[str, Any] = {
        "model": default_model,
        "prompt": prompt,
        "resolution": resolution,
        "duration": duration_sec,
        "ratio": aspect_ratio,
        "generate_audio": generate_audio,
        "watermark": watermark,
    }

    images = []
    if first_frame_path is not None:
        images.append(_image_to_data_uri(first_frame_path))
    if last_frame_path is not None:
        images.append(_image_to_data_uri(last_frame_path))
    if images:
        payload["images"] = images

    started = time.time()
    resp = _http_json("POST", f"{ATLAS_BASE}/generateVideo", api_key, payload)
    job_id = (resp.get("data") or {}).get("id") or resp.get("id")
    if not job_id:
        raise VideoGenerationError(f"ジョブIDが取得できません: {json.dumps(resp, ensure_ascii=False)[:800]}")

    log(f"  Atlas Cloud job {job_id} 開始、ポーリング中...")
    while time.time() - started < TIMEOUT_SEC:
        time.sleep(POLL_INTERVAL_SEC)
        st = _http_json("GET", f"{ATLAS_BASE}/prediction/{job_id}", api_key)
        data = st.get("data", st)
        status = str(data.get("status", "")).lower()
        if status == "completed":
            outputs = data.get("outputs") or []
            video_url = outputs[0] if outputs else None
            if not video_url:
                raise VideoGenerationError(f"動画URLが見つかりません: {json.dumps(data, ensure_ascii=False)[:800]}")
            _download(video_url, dest_path)
            elapsed = time.time() - started
            return {"status": "ok", "elapsed_sec": round(elapsed), "job_id": job_id, "model": default_model}
        if status in ("failed", "timeout", "error", "cancelled"):
            raise VideoGenerationError(f"生成失敗: {json.dumps(data, ensure_ascii=False)[:800]}")
        log(f"  status={status} ({int(time.time() - started)}s)")
    raise VideoGenerationError(f"タイムアウト(job {job_id})")


def generate_clip_with_retry(
    max_retries: int,
    retry_backoff_sec: int,
    **kwargs: Any,
) -> Dict[str, Any]:
    """残高枯渇は即座に中断、それ以外の失敗は max_retries 回リトライしてダメならスキップ扱いにする。"""
    last_error: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            return generate_clip(**kwargs)
        except BalanceExhaustedError:
            raise  # 全体を止める
        except VideoGenerationError as e:
            last_error = e
            log(f"  生成失敗(試行{attempt + 1}/{max_retries + 1}): {e}")
            if attempt < max_retries:
                time.sleep(retry_backoff_sec)
    return {"status": "skipped", "error": str(last_error)}
