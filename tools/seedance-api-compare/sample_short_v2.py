#!/usr/bin/env python3
"""サンプルv2: image-to-video連鎖で人物統一

reference-to-videoは実在風の顔参照が権利保護フィルタで弾かれるため、
「前カットの最終フレーム→次カットのstart_image」の連鎖方式で人物を統一する。
カット1は既存のものを流用し、その最終フレームからカット2以降を順次生成。

費用目安: 3カット×10秒×$0.09/s(fast) = 約$2.7
"""

import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SAMPLE_DIR = BASE_DIR / "output" / "sample"
ATLAS_BASE = "https://api.atlascloud.ai/api/v1/model"
MODEL = "bytedance/seedance-2.0-fast/image-to-video"
POLL_INTERVAL_SEC = 15
TIMEOUT_SEC = 20 * 60  # 1カットあたり

CUTS = [
    {
        "name": "cut2_tip1_v2",
        "prompt": 'The same woman continues talking directly to the camera in the same room. '
        'She says in Japanese: "1つ目は音声入力。タイピングの3倍速で、散歩しながらアイデア整理ができちゃいます。" '
        "She mimes talking into a phone. Clear natural Japanese speech, vlog style.",
    },
    {
        "name": "cut3_tip2_v2",
        "prompt": 'The same woman continues talking directly to the camera in the same room. '
        'She says in Japanese: "2つ目は画像を見せて質問。冷蔵庫の写真を送るだけで、今夜の献立を考えてくれるんです。" '
        "She shows a phone screen to the camera with a delighted expression. Clear natural Japanese speech, vlog style.",
    },
    {
        "name": "cut4_cta_v2",
        "prompt": 'The same woman continues talking directly to the camera in the same room. '
        'She says in Japanese: "3つ目はプロフィールに続きを書いたので、フォローして確認してくださいね。それではまた明日!" '
        "She waves goodbye with a warm smile. Clear natural Japanese speech, vlog style.",
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
        with urllib.request.urlopen(req, timeout=180) as resp:
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


def last_frame_b64(video: Path) -> str:
    """動画の最終フレームをJPEGで抽出してdata URIにする"""
    tmp = video.with_suffix(".lastframe.jpg")
    subprocess.run(
        ["ffmpeg", "-y", "-sseof", "-0.5", "-i", str(video),
         "-frames:v", "1", "-q:v", "2", "-loglevel", "error", str(tmp)],
        check=True,
    )
    b64 = "data:image/jpeg;base64," + base64.b64encode(tmp.read_bytes()).decode()
    return b64


def generate_cut(api_key, name, prompt, start_image_b64) -> Path:
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "start_image": start_image_b64,
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
        raise RuntimeError(f"投入失敗: {json.dumps(resp, ensure_ascii=False)[:400]}")
    print(f"[{name}] 投入 job={job_id}")
    started = time.time()
    while time.time() - started < TIMEOUT_SEC:
        time.sleep(POLL_INTERVAL_SEC)
        st = http_json("GET", f"{ATLAS_BASE}/prediction/{job_id}", api_key)
        data = st.get("data", st)
        status = str(data.get("status", "")).lower()
        if status == "completed":
            outputs = data.get("outputs") or []
            if not outputs:
                raise RuntimeError("outputsが空")
            dest = SAMPLE_DIR / f"{name}.mp4"
            download(outputs[0], dest)
            print(f"[{name}] 完了 ({int(time.time() - started)}s)")
            return dest
        if status in ("failed", "timeout", "error"):
            raise RuntimeError(f"生成失敗: {(data.get('error') or '')[:300]}")
    raise RuntimeError("タイムアウト")


def main():
    load_env_file()
    api_key = os.environ.get("ATLAS_CLOUD_API_KEY")
    if not api_key:
        print("ATLAS_CLOUD_API_KEY 未設定")
        return 1

    cut1 = SAMPLE_DIR / "cut1_hook.mp4"
    if not cut1.exists():
        print(f"カット1がない: {cut1}")
        return 1

    files = [cut1]
    prev = cut1
    for cut in CUTS:
        try:
            start_b64 = last_frame_b64(prev)
            dest = generate_cut(api_key, cut["name"], cut["prompt"], start_b64)
            files.append(dest)
            prev = dest  # 連鎖: 次のカットはこのカットの最終フレームから
        except Exception as e:
            print(f"[{cut['name']}] エラー: {e}")
            print("以降のカットは前回成功カットの最終フレームから継続")

    if len(files) < 2:
        print("再生成が全滅のため連結中止")
        return 1
    if len(files) < 4:
        print(f"完成カット {len(files)}/4 — 連結は成功分のみで実施")

    concat_list = SAMPLE_DIR / "concat_v2.txt"
    concat_list.write_text("".join(f"file '{f}'\n" for f in files), encoding="utf-8")
    final = SAMPLE_DIR / "sample_seedance_audio_ver2.mp4"
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
