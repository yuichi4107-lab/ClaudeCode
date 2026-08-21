#!/usr/bin/env python3
"""工程5: シーン動画生成(Atlas Cloud Seedance 2.0)。

storyboard_{short,full}.json の各シーンについてAtlas Cloudでクリップを生成し、
clips_{short,full}/scene_XX.mp4 に保存する。

想定クリップ数・生成時間目安(要件定義書より):
  - 60秒版: 約8〜12クリップ、5秒クリップ×12本で概算$6.7、生成は1本あたり数十秒〜数分
  - 3分版 : 約20〜40クリップ、5秒クリップ×36本で概算$20.2

使い方:
  python3 step5_generate_clips.py --project <dir> --version short
  python3 step5_generate_clips.py --project <dir> --version short --dry-run
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mvfactory.common import load_env_file, load_project_yaml, log, project_dir, write_json  # noqa: E402
from mvfactory.providers.video import (  # noqa: E402
    BalanceExhaustedError,
    VideoGenerationError,
    generate_clip_with_retry,
)
from mvfactory.storyboard import StoryboardError, load_and_validate_storyboard  # noqa: E402


def resolve_reference(pdir: Path, role: Optional[str]) -> Dict[str, Optional[Path]]:
    """role(none/first_frame/first_last_frame)に応じて参照画像パスを決める。

    現状は references/ 配下の world.png / char_*.png のうち最初に見つかったものを
    汎用参照として使う簡易実装。シーンごとに個別キャラを厳密に割り当てたい場合は
    storyboard側の各シーンに reference_image_file を追加して拡張可能。
    """
    ref_dir = pdir / "references"
    if role in (None, "none") or not ref_dir.exists():
        return {"first": None, "last": None}

    candidates = sorted(ref_dir.glob("*.png"))
    if not candidates:
        return {"first": None, "last": None}

    if role == "first_frame":
        return {"first": candidates[0], "last": None}
    if role == "first_last_frame":
        first = candidates[0]
        last = candidates[1] if len(candidates) > 1 else candidates[0]
        return {"first": first, "last": last}
    return {"first": None, "last": None}


def run_step5(pdir: Path, project: Dict[str, Any], version: str, dry_run: bool) -> Dict[str, Any]:
    storyboard = load_and_validate_storyboard(pdir, version)
    clips_dir = pdir / ("clips_short" if version == "short" else "clips_full")
    # 要件のディレクトリ規約(工程0)に合わせて short/full サブディレクトリ配下にも置く
    versioned_dir = pdir / version / f"clips_{version}"
    versioned_dir.mkdir(parents=True, exist_ok=True)

    vcfg = project.get("video_generation", {}) or {}
    resolution = vcfg.get("resolution", "720p")
    mode = vcfg.get("mode", "std")
    model_override = vcfg.get("model")
    generate_audio = bool(vcfg.get("generate_audio", False))
    watermark = bool(vcfg.get("watermark", False))
    max_retries = int(vcfg.get("max_retries", 2))
    retry_backoff = int(vcfg.get("retry_backoff_sec", 20))

    aspect_ratio = storyboard["aspect_ratio"]
    scenes = storyboard["scenes"]

    results = []
    for scene in scenes:
        scene_id = scene["scene_id"]
        dest = versioned_dir / f"{scene_id}.mp4"
        if dest.exists():
            log(f"[{version}] {scene_id}: 既存クリップをスキップ")
            results.append({"scene_id": scene_id, "status": "already_exists", "file": dest.name})
            continue

        refs = resolve_reference(pdir, scene.get("reference_image_role"))

        if dry_run:
            log(f"[dry-run][{version}] {scene_id}: prompt={scene['video_prompt'][:60]}...")
            results.append({"scene_id": scene_id, "status": "dry_run"})
            continue

        log(f"[{version}] {scene_id}: 生成開始 ({scene['duration_sec']}s, {aspect_ratio}, {resolution})")
        try:
            res = generate_clip_with_retry(
                max_retries=max_retries,
                retry_backoff_sec=retry_backoff,
                prompt=scene["video_prompt"],
                duration_sec=int(scene["duration_sec"]),
                aspect_ratio=aspect_ratio,
                resolution=resolution,
                mode=mode,
                dest_path=dest,
                first_frame_path=refs["first"],
                last_frame_path=refs["last"],
                model_override=model_override,
                generate_audio=generate_audio,
                watermark=watermark,
            )
        except BalanceExhaustedError as e:
            log(f"ERROR: {e}")
            log("残高枯渇のため工程5を中断します。Atlas Cloudにチャージ後、再実行してください。")
            write_json(pdir / "logs" / f"step5_{version}_result.json", {
                "aborted": True, "reason": "balance_exhausted", "results": results,
            })
            raise

        res["scene_id"] = scene_id
        res.setdefault("file", dest.name if dest.exists() else None)
        results.append(res)
        status = res.get("status")
        if status == "skipped":
            log(f"[{version}] {scene_id}: 生成スキップ(リトライ上限到達) - {res.get('error')}")
        else:
            log(f"[{version}] {scene_id}: 完了 ({res.get('elapsed_sec')}s)")

    summary = {
        "version": version,
        "total_scenes": len(scenes),
        "ok": len([r for r in results if r.get("status") in ("ok", "already_exists")]),
        "skipped": len([r for r in results if r.get("status") == "skipped"]),
        "results": results,
    }
    write_json(pdir / "logs" / f"step5_{version}_result.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="工程5: シーン動画生成(Atlas Cloud)")
    parser.add_argument("--project", required=True)
    parser.add_argument("--version", required=True, choices=["short", "full"])
    parser.add_argument("--dry-run", action="store_true", help="API呼び出しをせずプロンプトのみ確認")
    args = parser.parse_args()

    load_env_file()
    pdir = project_dir(args.project)
    if not pdir.exists():
        log(f"ERROR: プロジェクトディレクトリが見つかりません: {pdir}")
        return 1

    try:
        project = load_project_yaml(pdir)
    except (FileNotFoundError, ValueError) as e:
        log(f"ERROR: {e}")
        return 1

    try:
        summary = run_step5(pdir, project, args.version, args.dry_run)
    except (StoryboardError, VideoGenerationError) as e:
        log(f"ERROR: {e}")
        return 1

    log(f"工程5({args.version}) 完了: ok={summary['ok']} skipped={summary['skipped']} / {summary['total_scenes']}")
    return 0 if summary["skipped"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
