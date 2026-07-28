#!/usr/bin/env python3
"""Seedance音声版ショート動画サンプル制作

VOICEVOXナレーション無し・Seedance 2.0ネイティブ音声(日本語セリフ)での
ショート動画の仕上がりを確認するためのサンプル。4カットを並列投入して
ポーリングし、ffmpegで1本に連結する。

費用目安: 4カット×10秒×$0.09/s(fast) = 約$3.6
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output" / "sample"
ATLAS_BASE = "https://api.atlascloud.ai/api/v1/model"
MODEL = "bytedance/seedance-2.0-fast/text-to-video"
POLL_INTERVAL_SEC = 20
TIMEOUT_SEC = 40 * 60

CHARACTER = (
    "A cheerful Japanese woman in her mid-20s with shoulder-length black hair, "
    "wearing a light beige sweater, sitting in a bright modern Japanese apartment room "
    "with soft warm lighting, talking directly to the camera, vlog style, realistic, "
    "vertical short-form video"
)

CUTS = [
    {
        "name": "cut1_hook",
        "prompt": CHARACTER + '. She leans in with excitement and says in Japanese: '
        '"実はChatGPT、まだ9割の人が知らない使い方があるんです。今日は3つだけ紹介しますね。" '
        "She holds up three fingers. Clear natural Japanese speech.",
    },
    {
        "name": "cut2_tip1",
        "prompt": CHARACTER + '. She says in Japanese: '
        '"1つ目は音声入力。タイピングの3倍速で、散歩しながらアイデア整理ができちゃいます。" '
        "She mimes talking into a phone while walking gesture. Clear natural Japanese speech.",
    },
    {
        "name": "cut3_tip2",
        "prompt": CHARACTER + '. She says in Japanese: '
        '"2つ目は画像を見せて質問。冷蔵庫の写真を送るだけで、今夜の献立を考えてくれるんです。" '
        "She shows a phone screen to the camera with a delighted expression. Clear natural Japanese speech.",
    },
    {
        "name": "cut4_cta",
        "prompt": CHARACTER + '. She says in Japanese: '
        '"3つ目はプロフィールに続きを書いたので、フォローして確認してくださいね。それではまた明日!" '
        "She waves goodbye with a warm smile. Clear natural Japanese speech.",
    },
]


def load_env_file():
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


def http_json(method, url, api_key, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {api_key}")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "seedance-compare/1.0")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:1000]
        raise RuntimeError(f"HTTP {e.code} {url}\n{body}") from e


def download(url, dest: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "seedance-compare/1.0"})
    with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


def main():
    load_env_file()
    api_key = os.environ.get("ATLAS_CLOUD_API_KEY")
    if not api_key:
        print("ATLAS_CLOUD_API_KEY 未設定")
        return 1
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # 全カットを先に投入(並列生成)
    jobs = {}
    for cut in CUTS:
        payload = {
            "model": MODEL,
            "prompt": cut["prompt"],
            "duration": 10,
            "resolution": "720p",
            "ratio": "9:16",
            "generate_audio": True,
            "watermark": False,
            "seed": 42,
        }
        resp = http_json("POST", f"{ATLAS_BASE}/generateVideo", api_key, payload)
        job_id = resp.get("data", {}).get("id") or resp.get("id")
        if not job_id:
            print(f"[{cut['name']}] 投入失敗: {json.dumps(resp, ensure_ascii=False)[:400]}")
            return 1
        jobs[cut["name"]] = {"id": job_id, "status": "processing", "file": None}
        print(f"[{cut['name']}] 投入 job={job_id}")

    # まとめてポーリング
    started = time.time()
    while time.time() - started < TIMEOUT_SEC:
        time.sleep(POLL_INTERVAL_SEC)
        pending = [n for n, j in jobs.items() if j["status"] == "processing"]
        if not pending:
            break
        for name in pending:
            st = http_json("GET", f"{ATLAS_BASE}/prediction/{jobs[name]['id']}", api_key)
            data = st.get("data", st)
            status = str(data.get("status", "")).lower()
            if status == "completed":
                outputs = data.get("outputs") or []
                if not outputs:
                    jobs[name]["status"] = "failed"
                    print(f"[{name}] outputsが空")
                    continue
                dest = OUTPUT_DIR / f"{name}.mp4"
                download(outputs[0], dest)
                jobs[name]["status"] = "done"
                jobs[name]["file"] = dest
                print(f"[{name}] 完了 ({int(time.time() - started)}s)")
            elif status in ("failed", "timeout", "error"):
                jobs[name]["status"] = "failed"
                print(f"[{name}] 失敗: {json.dumps(data, ensure_ascii=False)[:400]}")
        done = sum(1 for j in jobs.values() if j["status"] == "done")
        print(f"  進捗 {done}/{len(jobs)} ({int(time.time() - started)}s)")

    files = [jobs[c["name"]]["file"] for c in CUTS if jobs[c["name"]]["status"] == "done"]
    if len(files) < len(CUTS):
        print(f"完成カット {len(files)}/{len(CUTS)} — 連結は成功分のみで実施")
    if not files:
        print("全カット失敗")
        return 1

    # ffmpegで連結(同一エンコード設定なのでconcat demuxer + 再エンコードで安全に)
    concat_list = OUTPUT_DIR / "concat.txt"
    concat_list.write_text("".join(f"file '{f}'\n" for f in files), encoding="utf-8")
    final = OUTPUT_DIR / "sample_seedance_audio_ver.mp4"
    rc = os.system(
        f'ffmpeg -y -f concat -safe 0 -i "{concat_list}" '
        f'-c:v libx264 -preset medium -crf 19 -c:a aac -b:a 192k '
        f'-loglevel error "{final}"'
    )
    if rc != 0:
        print("ffmpeg連結失敗。個別カットは output/sample/ にあります")
        return 1
    size_mb = final.stat().st_size / 1024 / 1024
    print(f"\n完成: {final} ({size_mb:.1f}MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
