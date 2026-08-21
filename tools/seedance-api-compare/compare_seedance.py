#!/usr/bin/env python3
"""Seedance 2.0 API 比較テスト: Atlas Cloud vs EvoLink

同一プロンプトを両プロバイダに投げて、生成時間・結果動画を比較する。
APIキーは環境変数 (ATLAS_CLOUD_API_KEY / EVOLINK_API_KEY) か、
このディレクトリの .env ファイルから読む。片方だけでも動く。

使い方:
  python3 compare_seedance.py --prompt "A cat walking on a beach at sunset" \
      --duration 5 --resolution 720p
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

ATLAS_BASE = "https://api.atlascloud.ai/api/v1/model"
EVOLINK_BASE = "https://api.evolink.ai/v1"

POLL_INTERVAL_SEC = 15
TIMEOUT_SEC = 30 * 60  # 30分で打ち切り


def load_env_file():
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def http_json(method, url, api_key, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    # Cloudflareがpython-urllibのデフォルトUAを403(1010)で弾くため必須
    req.add_header("User-Agent", "seedance-compare/1.0")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP {e.code} {url}\n{body}") from e


def download(url, dest: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "seedance-compare/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def run_atlas(api_key, prompt, duration, resolution, mode):
    """Atlas Cloud: POST /generateVideo -> GET /prediction/{id}"""
    default_model = ("bytedance/seedance-2.0-fast/text-to-video" if mode == "fast"
                     else "bytedance/seedance-2.0/text-to-video")
    payload = {
        "model": os.environ.get("ATLAS_MODEL", default_model),
        "prompt": prompt,
        "resolution": resolution,
        "duration": duration,
        "ratio": "9:16",
        "generate_audio": True,
        "watermark": False,
    }
    started = time.time()
    resp = http_json("POST", f"{ATLAS_BASE}/generateVideo", api_key, payload)
    job_id = resp.get("data", {}).get("id") or resp.get("id")
    if not job_id:
        raise RuntimeError(f"ジョブIDが取れない: {json.dumps(resp, ensure_ascii=False)[:800]}")
    print(f"  [atlas] job {job_id} 開始、ポーリング中...")
    while time.time() - started < TIMEOUT_SEC:
        time.sleep(POLL_INTERVAL_SEC)
        st = http_json("GET", f"{ATLAS_BASE}/prediction/{job_id}", api_key)
        data = st.get("data", st)
        status = str(data.get("status", "")).lower()
        if status == "completed":
            outputs = data.get("outputs") or []
            video_url = outputs[0] if outputs else None
            return video_url, time.time() - started, data
        if status in ("failed", "timeout", "error", "cancelled"):
            raise RuntimeError(f"生成失敗: {json.dumps(data, ensure_ascii=False)[:800]}")
        print(f"  [atlas] status={status} ({int(time.time() - started)}s)")
    raise RuntimeError("タイムアウト")


def run_evolink(api_key, prompt, duration, resolution, mode):
    """EvoLink: POST /videos/generations -> GET /tasks/{id}"""
    payload = {
        "model": os.environ.get("EVOLINK_MODEL", "seedance-2.0-text-to-video"),
        "prompt": prompt,
        "duration": duration,
        "quality": resolution,
        "aspect_ratio": "9:16",
        "generate_audio": True,
    }
    started = time.time()
    resp = http_json("POST", f"{EVOLINK_BASE}/videos/generations", api_key, payload)
    task_id = resp.get("id")
    if not task_id:
        raise RuntimeError(f"タスクIDが取れない: {json.dumps(resp, ensure_ascii=False)[:800]}")
    print(f"  [evolink] task {task_id} 開始、ポーリング中...")
    while time.time() - started < TIMEOUT_SEC:
        time.sleep(POLL_INTERVAL_SEC)
        st = http_json("GET", f"{EVOLINK_BASE}/tasks/{task_id}", api_key)
        status = str(st.get("status", "")).lower()
        if status in ("completed", "succeeded", "success"):
            video_url = None
            for key in ("video_url", "url", "output"):
                if st.get(key):
                    video_url = st[key]
                    break
            if not video_url and isinstance(st.get("results"), list) and st["results"]:
                first = st["results"][0]
                video_url = first.get("url") if isinstance(first, dict) else first
            return video_url, time.time() - started, st
        if status in ("failed", "error", "cancelled"):
            raise RuntimeError(f"生成失敗: {json.dumps(st, ensure_ascii=False)[:800]}")
        print(f"  [evolink] status={status} progress={st.get('progress')} ({int(time.time() - started)}s)")
    raise RuntimeError("タイムアウト")


PROVIDERS = {
    "atlas": ("ATLAS_CLOUD_API_KEY", run_atlas),
    "evolink": ("EVOLINK_API_KEY", run_evolink),
}


def main():
    parser = argparse.ArgumentParser(description="Seedance 2.0: Atlas Cloud vs EvoLink 比較")
    parser.add_argument("--prompt", required=True, help="生成プロンプト(英語推奨)")
    parser.add_argument("--duration", type=int, default=5, help="秒数 4-15 (default: 5)")
    parser.add_argument("--resolution", default="720p", choices=["480p", "720p", "1080p"])
    parser.add_argument("--mode", default="std", choices=["std", "fast"])
    parser.add_argument("--only", choices=list(PROVIDERS), help="片方だけ実行")
    args = parser.parse_args()

    load_env_file()
    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    summary = {"prompt": args.prompt, "duration": args.duration,
               "resolution": args.resolution, "mode": args.mode, "results": {}}

    targets = [args.only] if args.only else list(PROVIDERS)
    for name in targets:
        env_key, runner = PROVIDERS[name]
        api_key = os.environ.get(env_key)
        if not api_key:
            print(f"[{name}] スキップ: 環境変数 {env_key} が未設定")
            summary["results"][name] = {"status": "skipped", "reason": f"{env_key} 未設定"}
            continue
        print(f"[{name}] 生成開始: {args.duration}s {args.resolution} {args.mode}")
        try:
            video_url, elapsed, raw = runner(api_key, args.prompt, args.duration,
                                             args.resolution, args.mode)
            if not video_url:
                raise RuntimeError(f"動画URLが見つからない: {json.dumps(raw, ensure_ascii=False)[:800]}")
            dest = OUTPUT_DIR / f"{stamp}_{name}_{args.resolution}_{args.duration}s.mp4"
            download(video_url, dest)
            size_mb = dest.stat().st_size / 1024 / 1024
            print(f"[{name}] 完了: {elapsed:.0f}秒 -> {dest.name} ({size_mb:.1f}MB)")
            summary["results"][name] = {"status": "ok", "elapsed_sec": round(elapsed),
                                        "file": dest.name, "size_mb": round(size_mb, 1),
                                        "video_url": video_url}
        except Exception as e:
            print(f"[{name}] エラー: {e}")
            summary["results"][name] = {"status": "error", "error": str(e)[:1500]}

    report = OUTPUT_DIR / f"{stamp}_summary.json"
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nサマリ: {report}")
    ok = [n for n, r in summary["results"].items() if r.get("status") == "ok"]
    print(f"成功: {ok if ok else 'なし'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
