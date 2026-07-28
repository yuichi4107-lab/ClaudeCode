#!/usr/bin/env python3
"""Suno楽曲生成ヘルパー（opensuno Bridge Mode経由）。

前提: localhost:3001 で opensuno bridge が稼働し、Chrome拡張が接続済みであること。
標準ライブラリのみ使用（追加pip不要）。

使い方:
  # シンプル生成（プロンプトから2曲生成しMP3保存）
  python3 suno_generate.py generate --prompt "明るいJ-POP、夏の海" --out ./output

  # カスタム生成（歌詞・スタイル・タイトル指定）
  python3 suno_generate.py custom --lyrics-file lyrics.txt --style "acoustic pop" \
      --title "夏の記憶" --out ./output

  # インスト曲（ボーカルなし）
  python3 suno_generate.py generate --prompt "lo-fi chill beat" --instrumental --out ./output

  # 状態確認のみ
  python3 suno_generate.py status

  # クレジット残確認
  python3 suno_generate.py credits
"""

import argparse
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

BRIDGE = "http://localhost:3001"
POLL_INTERVAL = 10   # 秒
POLL_TIMEOUT = 600   # 秒（Suno生成は通常1〜3分）


def api(path, payload=None):
    url = f"{BRIDGE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def check_bridge():
    try:
        status = api("/api/status")
    except (urllib.error.URLError, OSError):
        sys.exit(
            "ERROR: bridgeサーバーに接続できません。\n"
            "起動: cd ~/tools/opensuno && nohup bun run bridge > /tmp/opensuno-bridge.log 2>&1 &"
        )
    if not status.get("connected"):
        sys.exit(
            "ERROR: Chrome拡張が未接続です。\n"
            "常駐ChromeでSuno拡張が有効か、suno.comのログイン済みタブが開いているか確認してください。"
        )


def as_clip_list(data):
    """配列と {clips:[...]} の両形式に対応する。

    /api/generate系はnormalizeClip適用済みの配列、/api/getはSuno feed v2の生データが返る。
    status/audio_url/title は両形式で共通フィールド名のため同じ読み出しロジックでよい。
    """
    if isinstance(data, dict):
        return data.get("clips", [])
    return data or []


def poll_and_download(ids, out_dir):
    """生成完了までポーリングし、MP3をダウンロードする。"""
    deadline = time.time() + POLL_TIMEOUT
    done = {}
    while time.time() < deadline and len(done) < len(ids):
        time.sleep(POLL_INTERVAL)
        clips = as_clip_list(api(f"/api/get?ids={','.join(ids)}"))
        for c in clips:
            st = c.get("status")
            if st in ("complete", "streaming") and c.get("audio_url") and c["id"] not in done:
                if st == "complete":
                    done[c["id"]] = c
        pending = [c.get("status") for c in clips if c["id"] not in done]
        print(f"  待機中... 完了 {len(done)}/{len(ids)} (残り: {pending})", flush=True)
        if any(c.get("status") == "error" for c in clips):
            for c in clips:
                if c.get("status") == "error":
                    print(f"  生成エラー: {c.get('id')} {c.get('metadata', {}).get('error_message', '')}")
                    done[c["id"]] = c  # エラーもカウントして無限待ちを防ぐ
    if len(done) < len(ids):
        sys.exit(f"ERROR: タイムアウト（{POLL_TIMEOUT}秒）。ids={ids} は後で /api/get で再確認可能です。")

    out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for cid, clip in done.items():
        if clip.get("status") == "error" or not clip.get("audio_url"):
            continue
        title = (clip.get("title") or "untitled").replace("/", "_").replace(" ", "_")
        dest = out_dir / f"{title}_{cid[:8]}.mp3"
        urllib.request.urlretrieve(clip["audio_url"], dest)
        results.append({"id": cid, "title": clip.get("title"), "file": str(dest),
                        "duration": clip.get("metadata", {}).get("duration")})
        print(f"  保存: {dest}")
    return results


def main():
    p = argparse.ArgumentParser(description="Suno music generation via opensuno bridge")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="プロンプトから生成")
    g.add_argument("--prompt", required=True)
    g.add_argument("--instrumental", action="store_true")
    g.add_argument("--model", default="chirp-crow", help="chirp-crow(v5)/chirp-auk(v4.5)等")
    g.add_argument("--out", default="./suno-output")

    c = sub.add_parser("custom", help="歌詞・スタイル・タイトル指定で生成")
    c.add_argument("--lyrics-file", help="歌詞テキストファイル")
    c.add_argument("--lyrics", help="歌詞を直接指定")
    c.add_argument("--style", required=True, help="音楽スタイル（例: acoustic pop）")
    c.add_argument("--title", required=True)
    c.add_argument("--instrumental", action="store_true")
    c.add_argument("--model", default="chirp-crow")
    c.add_argument("--out", default="./suno-output")

    sub.add_parser("status", help="bridge接続状態を確認")
    sub.add_parser("credits", help="クレジット残を確認")

    a = p.parse_args()

    if a.cmd == "status":
        print(json.dumps(api("/api/status"), indent=2, ensure_ascii=False))
        return
    if a.cmd == "credits":
        check_bridge()
        print(json.dumps(api("/api/get_limit"), indent=2, ensure_ascii=False))
        return

    check_bridge()

    if a.cmd == "generate":
        payload = {"prompt": a.prompt, "make_instrumental": a.instrumental,
                   "mv": a.model, "wait_audio": False}
        clips = api("/api/generate", payload)
    else:  # custom
        lyrics = a.lyrics or (Path(a.lyrics_file).read_text() if a.lyrics_file else "")
        if not lyrics and not a.instrumental:
            sys.exit("ERROR: --lyrics か --lyrics-file を指定してください（インストなら --instrumental）")
        payload = {"prompt": lyrics, "tags": a.style, "title": a.title,
                   "make_instrumental": a.instrumental, "mv": a.model, "wait_audio": False}
        clips = api("/api/custom_generate", payload)

    if isinstance(clips, dict):
        if clips.get("error"):
            sys.exit(f"ERROR: {clips['error']}")
        clips = as_clip_list(clips)
    ids = [c["id"] for c in clips]
    print(f"生成開始: {len(ids)}曲 ids={ids}")
    results = poll_and_download(ids, Path(a.out))
    print(json.dumps({"status": "completed", "tracks": results}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
