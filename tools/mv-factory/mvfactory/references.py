"""工程4: 参照画像生成(任意、60秒版・3分版で共用)。

既存の画像生成スキルをコード側から重複実装しないため、本モジュールは
「マニフェスト生成」までを担当する:
  1. project.yaml の reference_images.characters / world から
     画像生成プロンプトを組み立てる
  2. references/manifest.json に「必要な参照画像リスト(役割・プロンプト・
     出力予定パス)」を書き出す
  3. 実際の画像生成呼び出しは:
     - nanobanana2-image-gen スキル (Google AI Studio API, コード呼び出し可)
     - openai-image-gen スキル (ChatGPT Pro Web経由、API不使用のガードレール品)
     のどちらかを、Claude Codeのエージェントがmanifest.jsonを見て実行し、
     references/*.png として保存する(README.md参照)。
  4. references/*.png が既に揃っている場合はスキップ(60秒版・3分版の共用、
     重複生成回避)。
  5. reference_images.enabled=false の場合は空マニフォールバックを返し、
     工程5はtext-to-videoにフォールバックする。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .common import log, write_json


def build_manifest(project: Dict[str, Any]) -> Dict[str, Any]:
    ref_cfg = project.get("reference_images", {}) or {}
    enabled = ref_cfg.get("enabled", False)

    if not enabled:
        return {
            "schema_version": 1,
            "enabled": False,
            "images": [],
            "note": "reference_images.enabled=false のため参照画像は使用しません(text-to-videoのみ)。",
        }

    provider = ref_cfg.get("provider", "nanobanana2")
    images: List[Dict[str, Any]] = []

    world = ref_cfg.get("world") or {}
    if world.get("description"):
        images.append({
            "role": "world",
            "name": "world",
            "prompt": world["description"],
            "aspect_ratio": "1:1",
            "output_file": "world.png",
        })

    for i, char in enumerate(ref_cfg.get("characters", []) or []):
        name = char.get("name", f"character{i+1}")
        images.append({
            "role": "character",
            "name": name,
            "prompt": char.get("description", ""),
            "aspect_ratio": "3:4",
            "output_file": f"char_{i+1:02d}_{_slug(name)}.png",
        })

    return {
        "schema_version": 1,
        "enabled": True,
        "provider": provider,
        "images": images,
        "shared_across_versions": True,
        "note": (
            "このmanifestに基づき、nanobanana2-image-gen または openai-image-gen "
            "スキルで references/*.png を生成すること。60秒版・3分版で同じ画像を"
            "使い回すため、references/ 配下に既にファイルがあれば再生成しない。"
        ),
    }


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_") or "unnamed"


def existing_reference_files(pdir: Path) -> List[str]:
    ref_dir = pdir / "references"
    if not ref_dir.exists():
        return []
    return sorted(p.name for p in ref_dir.glob("*.png"))


def run_step4(pdir: Path, project: Dict[str, Any]) -> Dict[str, Any]:
    ref_dir = pdir / "references"
    ref_dir.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(project)
    manifest_path = ref_dir / "manifest.json"
    write_json(manifest_path, manifest)

    existing = existing_reference_files(pdir)
    manifest["already_present"] = existing

    if not manifest["enabled"]:
        log("参照画像は無効化されています(text-to-videoのみで工程5に進みます)")
    elif existing:
        log(f"既存の参照画像を検出、再生成をスキップ: {existing}")
    else:
        log(f"参照画像マニフェストを書き出しました: {manifest_path}")
        log("nanobanana2-image-gen / openai-image-gen スキルで実画像を生成してください。")

    write_json(manifest_path, manifest)
    return manifest
