"""ローカル実行用: yt-dlpで対象チャンネルの全動画の id/title/upload_date を取得し、
video_dates.json として出力する。VPS IPがbot判定で取れないため、ローカルから取得する。
完了後、生成されたJSONをVPSへscp転送する。"""
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SRC_DIR = THIS_DIR.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from config import load_config
from youtube import normalize_published_date

import yt_dlp


def main() -> int:
    cfg_path = THIS_DIR.parent / "config.yaml"
    cfg = load_config(str(cfg_path))

    out_path = THIS_DIR.parent / "video_dates.json"

    all_videos: dict = {}

    for channel in cfg.channels:
        print(f"[INFO] fetching {channel.name} ({channel.id})...")
        ydl_opts = {"quiet": True, "extract_flat": True, "skip_download": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/channel/{channel.id}/videos",
                download=False,
            )
        entries = info.get("entries") or []
        print(f"  found {len(entries)} videos")

        for i, entry in enumerate(entries):
            vid_id = entry.get("id") or ""
            if not vid_id:
                continue
            # extract_flat=Trueだとupload_date不在のため個別取得
            try:
                with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "no_warnings": True}) as ydl_d:
                    d = ydl_d.extract_info(
                        f"https://www.youtube.com/watch?v={vid_id}",
                        download=False,
                    )
                all_videos[vid_id] = {
                    "title": d.get("title", "") or entry.get("title", ""),
                    "upload_date": normalize_published_date(d.get("upload_date", "")),
                }
                print(f"  [{i+1}/{len(entries)}] {vid_id} -> {all_videos[vid_id]['upload_date']}")
            except Exception as exc:
                print(f"  [{i+1}/{len(entries)}] {vid_id} FAILED: {exc}")
                # extract_flat の title だけは残す
                all_videos[vid_id] = {
                    "title": entry.get("title", ""),
                    "upload_date": "",
                }

    out_path.write_text(json.dumps(all_videos, ensure_ascii=False, indent=2))
    print(f"\n[OK] wrote {len(all_videos)} entries to {out_path}")
    print(f"[NEXT] Transfer to VPS:")
    print(f"  scp \"{out_path}\" root@163.44.101.31:/opt/notebooklm-sync/video_dates.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
