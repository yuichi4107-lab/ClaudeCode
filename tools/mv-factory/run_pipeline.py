#!/usr/bin/env python3
"""MV Factory ワンコマンド実行。

工程0(project.yaml)〜工程6までを、承認ステップなしで最後まで自動実行する。

実行順序: 工程1 -> 2 -> (3-A -> 4 -> 5-A -> 6-A: 60秒版) -> (3-B -> 5-B -> 6-B: 3分版)
オーナー指定の「まず60秒→同じ曲で3分」の順を踏襲する。

工程3(絵コンテ生成)はLLMがsong_structure.jsonを踏まえて作文する工程のため、
storyboard_{short,full}.json が事前に用意されていない場合は、
このスクリプトは雛形を書き出した上で停止し、エージェントによる作文を促す
(全自動の原則は崩さないが、LLM生成ステップだけは"Claude Code実行時にエージェントが
生成する"という要件定義書の設計どおり、事前にファイルとして与えられている必要がある)。

使い方:
  python3 run_pipeline.py --project projects/20260707-neon-tokyo-drive
  python3 run_pipeline.py --project <dir> --only short   # 60秒版のみ
  python3 run_pipeline.py --project <dir> --dry-run-video  # 工程5をAPI呼び出しせず疎通確認
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mvfactory.analysis import run_step2  # noqa: E402
from mvfactory.common import ensure_dirs, load_env_file, load_project_yaml, log, project_dir, read_json  # noqa: E402
from mvfactory.mix import run_step6  # noqa: E402
from mvfactory.providers.music import MusicProviderError, get_provider  # noqa: E402
from mvfactory.providers.video import BalanceExhaustedError, VideoGenerationError  # noqa: E402
from mvfactory.references import run_step4  # noqa: E402
from mvfactory.storyboard import StoryboardError, load_and_validate_storyboard, scaffold_storyboard_template  # noqa: E402
from step5_generate_clips import run_step5  # noqa: E402
from step5b_inspect import run_step5b  # noqa: E402
from step6_mix import resolve_audio_for_version  # noqa: E402


def _quality_gate_passed(pdir: Path, version: str, storyboard: dict) -> bool:
    """logs/clip_audit.json を見て、このversionの全シーンがレビュー済み('ok')かを判定する。

    2026-07-07 オーナー指摘を受けて追加した安全装置。工程5b(contact sheet生成→
    エージェントによる目視検査→clip_audit.json記録)を経ていないクリップ群を
    そのまま工程6(合成)に渡さないためのゲート。
    """
    audit_path = pdir / "logs" / "clip_audit.json"
    if not audit_path.exists():
        return False
    audit = read_json(audit_path)

    # フォーマットは versions.<version>.scenes に統一(step5b_inspect.py参照)。
    # 旧形式(トップレベルにversion/scenesを直接持つ)のファイルとの後方互換のため、
    # versions.<version>が無ければトップレベルもフォールバックで見る。
    scenes_section = audit.get("versions", {}).get(version, {}).get("scenes")
    if scenes_section is None and audit.get("version") == version:
        scenes_section = audit.get("scenes", {})
    scenes_section = scenes_section or {}

    all_scene_ids = [s["scene_id"] for s in storyboard["scenes"]]
    if not all_scene_ids:
        return False
    for sid in all_scene_ids:
        entry = scenes_section.get(sid)
        if not entry or entry.get("status") != "ok":
            return False
    return True


def run_one_version(pdir, project, version: str, dry_run_video: bool) -> bool:
    """1バージョン(short/full)の工程3〜6を実行する。成功したらTrue。"""
    try:
        storyboard = load_and_validate_storyboard(pdir, version)
    except StoryboardError as e:
        log(f"[{version}] storyboard未準備: {e}")
        template_path = scaffold_storyboard_template(pdir, version, project)
        log(f"[{version}] 雛形を書き出しました: {template_path}")
        log(
            f"[{version}] エージェントが song_structure.json を踏まえてscenes[]を作文し、"
            f"python3 step3_storyboard.py --project {pdir} --version {version} --mode validate "
            "で検証してから再実行してください。"
        )
        return False

    run_step4(pdir, project)

    try:
        s5 = run_step5(pdir, project, version, dry_run=dry_run_video)
    except (StoryboardError, VideoGenerationError) as e:
        log(f"[{version}] 工程5でエラー: {e}")
        return False

    if dry_run_video:
        log(f"[{version}] dry-runのため工程6はスキップします")
        return True

    if s5["skipped"] > 0:
        log(f"[{version}] クリップ生成に失敗があるため工程6には進みますが、欠損分は無音/短縮になります")

    # --- 工程5b: 品質ゲート(2026-07-07 オーナー指摘を受けて追加) ---
    # contact sheetをここで自動生成する。ただし実際の目視判定(画風統一/
    # 人物・服装・髪型の一致/物理破綻チェック)はエージェントが行うため、
    # clip_audit.jsonで全シーン'ok'が確認できるまで工程6には進まない。
    log(f"=== {version}版: 工程5b(品質ゲート) ===")
    run_step5b(pdir, version, scene_filter=None, n_frames=5)
    if not _quality_gate_passed(pdir, version, storyboard):
        log(
            f"[{version}] 品質ゲート未通過: logs/clip_audit.json で全シーンが"
            "'ok'になっていません。エージェントが"
            f"logs/contact_sheets/{version}/*.jpg を目視検査し、"
            "logs/clip_audit.json の該当sceneのstatusを'ok'または"
            "'ng'(理由付き)に更新してください。NGクリップは再生成→"
            "step5b再実行→再検査を繰り返し、全て'ok'になってから"
            f"run_pipeline.pyを再実行するか python3 step6_mix.py --project {pdir} "
            f"--version {version} を直接実行してください。"
        )
        return False

    clips_dir = pdir / version / f"clips_{version}"
    clip_paths = [clips_dir / f"{sc['scene_id']}.mp4" for sc in storyboard["scenes"]]
    clip_paths = [p for p in clip_paths if p.exists()]
    if not clip_paths:
        log(f"[{version}] 利用可能なクリップが1本もないため工程6を中止します")
        return False

    audio_path = resolve_audio_for_version(pdir, version, float(storyboard["target_duration_sec"]))
    mix_cfg = project.get("mix", {})
    run_step6(pdir, version, clip_paths, audio_path, storyboard["aspect_ratio"], mix_cfg)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="MV Factory ワンコマンド実行")
    parser.add_argument("--project", required=True)
    parser.add_argument("--only", choices=["short", "full"], help="片方のバージョンのみ実行")
    parser.add_argument("--dry-run-video", action="store_true", help="工程5をAPI呼び出しせず疎通確認のみ")
    parser.add_argument("--skip-music", action="store_true", help="工程1をスキップ(既にsong.mp3がある場合)")
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

    ensure_dirs(pdir)

    # 工程1: 曲生成/投入(共通・1回のみ)
    audio_exists = any((pdir / f"song{ext}").exists() for ext in (".mp3", ".wav"))
    if not args.skip_music and not audio_exists:
        log("=== 工程1: 曲生成/投入 ===")
        provider = get_provider(project["song_source"])
        try:
            provider.generate(project, pdir)
        except MusicProviderError as e:
            log(f"ERROR: {e}")
            return 1
    else:
        log("=== 工程1: スキップ(既存音源を使用) ===")

    # 工程2: 曲構成解析(共通・1回のみ)
    log("=== 工程2: 曲構成解析 ===")
    run_step2(pdir)

    versions = [args.only] if args.only else ["short", "full"]
    overall_ok = True
    for version in versions:
        log(f"=== {version}版: 工程3〜6 ===")
        ok = run_one_version(pdir, project, version, args.dry_run_video)
        overall_ok = overall_ok and ok
        if not ok:
            log(f"[{version}] 未完了のため、このバージョンの生成はここで停止します")

    if overall_ok:
        log("全工程が完了しました。")
        return 0
    log("一部バージョンが未完了です(上記ログ参照)。")
    return 3


if __name__ == "__main__":
    sys.exit(main())
