#!/usr/bin/env python3
"""工程5b: クリップ品質ゲート(目視検査用contact sheet生成)。

2026-07-07 オーナー指摘を受けて新設。工程5(クリップ生成)完了後・工程6(合成)前に
必ず通す検査ゲート。このスクリプト自体はcontact sheet画像(1クリップにつき
複数フレームを時系列で並べた1枚絵)を作るだけで、実際の合否判定(画風統一/
人物・服装・髪型の一致/物理破綻)はエージェントがcontact sheetをReadして
目視で行う。判定結果は logs/clip_audit.json に人間/エージェントが記録する
(このスクリプトは自動では書き込まない。フォーマットは下記参照)。

## 検査観点チェックリスト

1. **画風統一**: アニメ調・3DCGアニメ調・実写風が混在していないか
   (storyboard側のスタイル矛盾はvalidateで機械チェック済みだが、実際の
   生成結果がプロンプト指示通りになっているとは限らないため目視必須)
2. **人物・服装・髪型の一致**: character_sheetの記述(髪型・服装・靴・体型)が
   クリップ内、およびクリップ間で一貫しているか
3. **物理破綻**:
   - 靴・手足の破綻: 片足に2つの靴/靴を履いていない/指や手足の数がおかしい
   - 移動方向の矛盾: 自転車を演いでいるのに前進しない、背景が流れる向きと
     進行方向が逆
   - 昇降装置の方向矛盾: エスカレーター/エレベーターの移動方向と人物の
     向き・体勢が矛盾している

## 運用フロー

```
工程5(クリップ生成)完了
  → step5b_inspect.py --project <dir> --version <short|full> でcontact sheet生成
  → エージェントが logs/contact_sheets/{version}/{scene_id}.jpg を読み、
    上記チェックリストで判定
  → 判定結果を logs/clip_audit.json に記録(このスクリプトは雛形だけ用意する)
  → NGクリップがあれば該当クリップを backup/ へ退避し、プロンプト修正の上
    step5_generate_clips.py で再生成
  → 再生成分だけ再度 step5b_inspect.py → 目視 → clip_audit.json 更新、を
    NGがなくなるまで繰り返す
  → 全クリップがOKになってから工程6(合成)に進む

run_pipeline.py は工程5の後、工程6の前に logs/clip_audit.json の存在と
「全シーンがreviewed」であることを確認し、なければ警告を出して停止する
(品質ゲートを迂回して合成に進めないようにする安全装置)。
```

## clip_audit.json フォーマット

```json
{
  "version": "short",
  "audit_date": "2026-07-07",
  "scenes": {
    "scene_01": {
      "status": "ok" | "ng",
      "style": "live-action" | "anime" | "3d-cgi" | "mixed",
      "character_consistency": "ok" | "ng",
      "physical_issues": ["shoes: both feet in one shoe visible at frame 3"],
      "notes": "自由記述",
      "reviewed_by": "quality-gate-agent",
      "reviewed_at": "2026-07-07T12:00:00"
    }
  },
  "all_reviewed": true,
  "all_ok": true
}
```

使い方:
  python3 step5b_inspect.py --project <dir> --version short
  python3 step5b_inspect.py --project <dir> --version short --scene scene_01  (1本だけ)
  python3 step5b_inspect.py --project <dir> --version short --frames 6        (フレーム数指定、デフォルト5)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mvfactory.analysis import ffprobe_duration_sec  # noqa: E402
from mvfactory.common import load_project_yaml, log, project_dir, read_json, write_json  # noqa: E402
from mvfactory.storyboard import StoryboardError, load_and_validate_storyboard  # noqa: E402

DEFAULT_FRAME_COUNT = 5


def _ffprobe_nb_frames(clip_path: Path) -> Optional[int]:
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=nb_frames", "-of", "csv=p=0", str(clip_path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        val = out.stdout.strip()
        return int(val) if val.isdigit() else None
    except Exception:
        return None


def build_contact_sheet(clip_path: Path, dest_path: Path, n_frames: int = DEFAULT_FRAME_COUNT) -> bool:
    """clip_pathから時系列でn_frames枚を等間隔抽出し、1枚のcontact sheet画像を作る。

    時系列に等間隔配置することで、動きの方向(自転車が前進しているか、
    エスカレーターの移動方向と人物の向きが一致しているか等)を1枚で
    判定しやすくする設計。tile配置は横並び1行(n_frames列 x 1行)。
    """
    nb_frames = _ffprobe_nb_frames(clip_path)
    if not nb_frames or nb_frames < n_frames:
        # フレーム数が取れない/少ない場合は時間ベースの等間隔selectにフォールバック
        duration = ffprobe_duration_sec(clip_path) or 5.0
        # n_frames等分した時刻でselectする(0秒と末尾ぎりぎりを含む)
        times = [duration * i / max(n_frames - 1, 1) for i in range(n_frames)]
        select_expr = "+".join(f"eq(t\\,{t:.2f})" for t in times)
    else:
        # フレーム番号ベースで等間隔選択(0始まり)
        step = (nb_frames - 1) / max(n_frames - 1, 1)
        frame_indices = [round(step * i) for i in range(n_frames)]
        select_expr = "+".join(f"eq(n\\,{idx})" for idx in frame_indices)

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    # select→tile: 1行にn_frames枚並べる。各フレームに小さく時系列順の意味を持たせる
    vf = f"select='{select_expr}',scale=320:-1,tile={n_frames}x1"
    cmd = [
        "ffmpeg", "-y", "-i", str(clip_path),
        "-vf", vf, "-frames:v", "1", "-vsync", "vfr",
        str(dest_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0 or not dest_path.exists():
        log(f"  WARNING: contact sheet生成失敗 ({clip_path.name}): {proc.stderr[-500:]}")
        return False
    return True


def run_step5b(pdir: Path, version: str, scene_filter: Optional[str], n_frames: int) -> Dict[str, Any]:
    storyboard = load_and_validate_storyboard(pdir, version)
    clips_dir = pdir / version / f"clips_{version}"
    sheets_dir = pdir / "logs" / "contact_sheets" / version

    scenes = storyboard["scenes"]
    if scene_filter:
        scenes = [s for s in scenes if s["scene_id"] == scene_filter]
        if not scenes:
            raise ValueError(f"scene_id={scene_filter} がstoryboardに見つかりません")

    generated = []
    missing = []
    for scene in scenes:
        scene_id = scene["scene_id"]
        clip_path = clips_dir / f"{scene_id}.mp4"
        if not clip_path.exists():
            missing.append(scene_id)
            continue
        dest = sheets_dir / f"{scene_id}.jpg"
        ok = build_contact_sheet(clip_path, dest, n_frames=n_frames)
        if ok:
            generated.append({"scene_id": scene_id, "contact_sheet": str(dest)})
            log(f"[{version}] {scene_id}: contact sheet生成 -> {dest}")
        else:
            missing.append(scene_id)

    if missing:
        log(f"[{version}] contact sheet生成失敗/クリップ未生成: {missing}")

    # audit雛形をマージ更新(既存のclip_audit.jsonがあれば尊重し、新規分だけ追記)
    #
    # フォーマットは常に versions.<version>.scenes に統一する(short/fullを
    # 同一ファイル内で確実に共存させるため、トップレベルscenes形式は使わない。
    # 2026-07-07: 旧ロジックはaudit["version"]の値で書き込み先を出し分けており、
    # short実行後にfull実行するとaudit["version"]が上書きされて
    # run_pipeline._quality_gate_passed()の参照先とズレる不具合があったため修正)
    audit_path = pdir / "logs" / "clip_audit.json"
    audit = read_json(audit_path) if audit_path.exists() else {}
    audit.setdefault("versions", {})
    section = audit["versions"].setdefault(version, {"scenes": {}})
    section.setdefault("scenes", {})

    for g in generated:
        scene_id = g["scene_id"]
        existing = section["scenes"].get(scene_id)
        if existing is None:
            section["scenes"][scene_id] = {
                "status": "pending_review",
                "contact_sheet": g["contact_sheet"],
            }
        else:
            # 既存レビュー結果があれば保持しつつcontact_sheetパスだけ更新
            existing["contact_sheet"] = g["contact_sheet"]

    all_scene_ids = [s["scene_id"] for s in storyboard["scenes"]]
    reviewed = section["scenes"]
    all_reviewed = all(
        reviewed.get(sid, {}).get("status") in ("ok", "ng") for sid in all_scene_ids
    )
    all_ok = all_reviewed and all(
        reviewed.get(sid, {}).get("status") == "ok" for sid in all_scene_ids
    )
    section["all_reviewed"] = all_reviewed
    section["all_ok"] = all_ok
    write_json(audit_path, audit)

    log(
        f"[{version}] contact sheet生成完了: {len(generated)}件 -> "
        f"{sheets_dir}\n"
        f"次のアクション: エージェントが logs/contact_sheets/{version}/*.jpg を"
        f"Readして目視検査し、logs/clip_audit.json の該当sceneの"
        f"status を 'ok' または 'ng'(理由付き)に更新してください。"
        f"NGがあれば該当クリップを再生成→本スクリプト再実行→再検査、"
        f"全て'ok'になってから工程6に進んでください。"
    )

    return {
        "version": version,
        "generated": len(generated),
        "missing": missing,
        "audit_path": str(audit_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="工程5b: クリップ品質ゲート(contact sheet生成)")
    parser.add_argument("--project", required=True)
    parser.add_argument("--version", required=True, choices=["short", "full"])
    parser.add_argument("--scene", help="特定シーンのみ処理(再生成分の再検査等に使用)")
    parser.add_argument("--frames", type=int, default=DEFAULT_FRAME_COUNT, help="1クリップあたりの抽出フレーム数(デフォルト5)")
    args = parser.parse_args()

    pdir = project_dir(args.project)
    if not pdir.exists():
        log(f"ERROR: プロジェクトディレクトリが見つかりません: {pdir}")
        return 1

    try:
        load_project_yaml(pdir)
        result = run_step5b(pdir, args.version, args.scene, args.frames)
    except (StoryboardError, ValueError, FileNotFoundError) as e:
        log(f"ERROR: {e}")
        return 1

    if result["missing"]:
        log(f"工程5b({args.version}) 一部未生成: {result['missing']}")
        return 2

    log(f"工程5b({args.version}) 完了: contact sheet {result['generated']}件生成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
