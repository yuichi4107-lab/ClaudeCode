"""工程3: 絵コンテ・シーンプロンプト生成 のスキーマ定義とバリデータ。

シーンプロンプトの「生成」自体はREADME.mdに記載の方式のとおり、
Claude Code実行時にエージェント(このexecutor自身、または後続セッションの
Claude)が song_structure.json + project.yaml を読んで作文する設計とする
(LLM生成方式)。本モジュールはそのLLM生成物のスキーマを固定し、
バリデーション・雛形生成・Seedanceのクリップ長制約(4〜15秒)との整合
チェックを提供する。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

from .common import read_json, write_json

MIN_CLIP_SEC = 4
MAX_CLIP_SEC = 15

VALID_ASPECTS = {"short": "9:16", "full": "16:9"}

# --- キャラクターシート必須化 (2026-07-07 品質ゲート導入) ---
# character_sheet は「服装・髪型・靴・体型等の固定記述」を1箇所にまとめ、
# 全シーンのvideo_promptが同じ記述を再利用することでキャラ一貫性を担保する。
# オーナー指摘(パイロットMVで服装・髪型がシーンごとに変わる問題)を受けて追加。
CHARACTER_SHEET_REQUIRED_KEYS = ["hairstyle", "outfit", "shoes", "build"]

# --- スタイル矛盾バリデータ (2026-07-07 品質ゲート導入) ---
# video_promptに矛盾するスタイル語(アニメ調×実写風など)が同時に入っていたら
# validateで弾く。パイロットMVで"Japanese anime-style live-action-look"という
# 自己矛盾語が全シーンに混入し、アニメ/実写混在の原因になった教訓を反映。
STYLE_KEYWORD_GROUPS = {
    "anime": [
        "anime-style", "anime style", "2d anime", "cel-shaded", "cel shaded",
        "cartoon", "illustration style", "manga style",
    ],
    "3d_cgi": [
        "3d animation", "cgi render", "pixar-style", "pixar style",
        "video game render", "3d cartoon",
    ],
    "live_action": [
        "live-action", "live action", "photorealistic", "shot on real camera",
        "real actress", "documentary-style realism",
    ],
}
# 同一video_prompt内でこれらの組み合わせが同時に出現したら矛盾とみなす
STYLE_CONFLICT_PAIRS = [
    ("anime", "live_action"),
    ("3d_cgi", "live_action"),
]


class StoryboardError(ValueError):
    pass


def _strip_negated_style_phrases(video_prompt: str) -> str:
    """'NOT xxx' / 'not xxx' で明示的に否定されているスタイル語句を除去した
    テキストを返す。プロンプト側で "NOT anime, NOT cel-shaded, NOT 3D
    animation" のように否定形でスタイルを除外する記法(本バリデータ導入時に
    scaffold雛形が推奨する書き方)は、矛盾検出の対象から除外する必要がある。
    "NOT" から次のカンマ/ピリオド/セミコロンまでを1つの否定句とみなし、
    その区間を空文字に置換する(簡易的な構文除去、厳密なNLPは行わない)。
    """
    # "not" の後にスタイル語が続く区間(次の区切り文字まで)を除去する
    return re.sub(r"\bnot\s+[^,;.]+", " ", video_prompt, flags=re.IGNORECASE)


def _detect_style_conflicts(video_prompt: str) -> List[str]:
    """video_prompt内のスタイル矛盾語ペアを検出する。矛盾があれば説明文のリストを返す。

    'NOT anime' のように明示的に否定されているスタイル語は、矛盾判定の
    対象外とする(否定形でのスタイル除外はむしろ推奨される書き方のため)。
    """
    stripped = _strip_negated_style_phrases(video_prompt)
    lower = stripped.lower()
    present_groups = set()
    for group, keywords in STYLE_KEYWORD_GROUPS.items():
        if any(kw in lower for kw in keywords):
            present_groups.add(group)

    conflicts = []
    for a, b in STYLE_CONFLICT_PAIRS:
        if a in present_groups and b in present_groups:
            conflicts.append(f"矛盾スタイル語の混在を検出: '{a}'系と'{b}'系が同一プロンプトに存在")
    return conflicts


def _character_sheet_fingerprint(character_sheet: Dict[str, Any]) -> List[str]:
    """character_sheetの主要な語(服装・髪型・靴等)を抽出し、video_promptとの
    突き合わせに使う短いトークンのリストを返す。完全一致ではなく、
    character_sheetの記述語のうち一定割合がvideo_promptに含まれるかを見る
    ゆるいチェック(厳密なNLP一致は行わない、誤検知よりも見逃し許容の設計)。
    """
    tokens: List[str] = []
    for key in CHARACTER_SHEET_REQUIRED_KEYS:
        val = character_sheet.get(key)
        if not val:
            continue
        # カンマ区切り・スペース区切りの単語をトークン化(3文字未満は除外しノイズを減らす)
        words = re.split(r"[,\s]+", str(val))
        tokens.extend(w.strip(".:;()").lower() for w in words if len(w.strip(".:;()")) >= 3)
    return tokens


def validate_storyboard(data: Dict[str, Any], version: str) -> List[str]:
    """storyboard_short.json / storyboard_full.json の形式チェック。エラーリストを返す。"""
    errors: List[str] = []

    if version not in VALID_ASPECTS:
        errors.append(f"version は 'short' か 'full' である必要があります: {version!r}")
        return errors

    expected_aspect = VALID_ASPECTS[version]
    if data.get("aspect_ratio") != expected_aspect:
        errors.append(
            f"aspect_ratio は {expected_aspect} である必要があります (実際: {data.get('aspect_ratio')!r})"
        )

    if "target_duration_sec" not in data:
        errors.append("target_duration_sec が必須です")

    # --- character_sheet 必須チェック (品質ゲート) ---
    # top-levelのcharacter_sheetを必須とする。複数キャラがいる場合は
    # characters[].character_sheet でも可(いずれか1つ以上が存在すればOK)。
    character_sheets: List[Dict[str, Any]] = []
    top_sheet = data.get("character_sheet")
    if isinstance(top_sheet, dict) and top_sheet:
        character_sheets.append(top_sheet)
    for c in data.get("characters", []) or []:
        cs = c.get("character_sheet") if isinstance(c, dict) else None
        if isinstance(cs, dict) and cs:
            character_sheets.append(cs)

    if not character_sheets:
        errors.append(
            "character_sheet が見つかりません。top-levelの character_sheet、"
            "または characters[].character_sheet のいずれかに"
            f"{CHARACTER_SHEET_REQUIRED_KEYS} を含む固定記述を用意してください"
            "(オーナー指摘: シーンごとに服装・髪型が変わる問題への対策)"
        )
    else:
        for idx, cs in enumerate(character_sheets):
            missing = [k for k in CHARACTER_SHEET_REQUIRED_KEYS if not cs.get(k)]
            if missing:
                errors.append(
                    f"character_sheet[{idx}] に必須キーが不足しています: {missing} "
                    f"(必須: {CHARACTER_SHEET_REQUIRED_KEYS})"
                )

    # 突き合わせ用トークン(全character_sheetのトークンを合算、シーン側チェックで使う)
    all_sheet_tokens: List[str] = []
    for cs in character_sheets:
        all_sheet_tokens.extend(_character_sheet_fingerprint(cs))

    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        errors.append("scenes は1件以上のリストである必要があります")
        return errors

    total = 0.0
    seen_ids = set()
    for i, scene in enumerate(scenes):
        prefix = f"scenes[{i}]"
        scene_id = scene.get("scene_id")
        if not scene_id:
            errors.append(f"{prefix}.scene_id が必須です")
        elif scene_id in seen_ids:
            errors.append(f"{prefix}.scene_id が重複しています: {scene_id}")
        else:
            seen_ids.add(scene_id)

        duration = scene.get("duration_sec")
        if not isinstance(duration, (int, float)):
            errors.append(f"{prefix}.duration_sec が数値ではありません")
        elif not (MIN_CLIP_SEC <= duration <= MAX_CLIP_SEC):
            errors.append(
                f"{prefix}.duration_sec={duration} がSeedance制約({MIN_CLIP_SEC}〜{MAX_CLIP_SEC}秒)外です"
            )
        else:
            total += duration

        video_prompt = scene.get("video_prompt")
        if not video_prompt:
            errors.append(f"{prefix}.video_prompt が必須です")
        else:
            # スタイル矛盾チェック
            for conflict_msg in _detect_style_conflicts(video_prompt):
                errors.append(f"{prefix}.video_prompt: {conflict_msg}")

            # character_sheet反映チェック(人物が登場するシーンのみ、ゆるい一致判定)
            # scene.get("features_character")が明示Falseのシーン(風景のみ等)はスキップ
            if scene.get("features_character", True) and all_sheet_tokens:
                lower_prompt = video_prompt.lower()
                hits = sum(1 for tok in set(all_sheet_tokens) if tok in lower_prompt)
                coverage = hits / max(len(set(all_sheet_tokens)), 1)
                if coverage < 0.25:
                    errors.append(
                        f"{prefix}.video_prompt が character_sheet の記述をほとんど"
                        f"反映していません(一致率{coverage:.0%}、25%未満)。"
                        "服装・髪型等の固定記述をvideo_promptに含めてください"
                    )

        ref = scene.get("reference_image_role")
        if ref not in (None, "none", "first_frame", "first_last_frame"):
            errors.append(f"{prefix}.reference_image_role が不正な値です: {ref!r}")

    target = data.get("target_duration_sec")
    if isinstance(target, (int, float)) and scenes:
        # 60秒版は厳密一致に近いことを推奨、3分版は多少の増減を許容(工程6でtrim/pad)
        tolerance = 5 if version == "short" else 15
        if abs(total - target) > tolerance:
            errors.append(
                f"シーン尺合計 {total}s が target_duration_sec {target}s と"
                f" 許容差{tolerance}s を超えて乖離しています(工程6でtrim/padするが確認推奨)"
            )

    return errors


def load_and_validate_storyboard(pdir: Path, version: str) -> Dict[str, Any]:
    filename = f"storyboard_{version}.json"
    path = pdir / filename
    if not path.exists():
        raise StoryboardError(
            f"{filename} が見つかりません: {path}\n"
            "工程3の絵コンテ生成がまだ行われていません。"
            "README.md記載の手順(エージェントによるLLM生成)に従って作成してください。"
        )
    data = read_json(path)
    errors = validate_storyboard(data, version)
    if errors:
        detail = "\n".join(f"  - {e}" for e in errors)
        raise StoryboardError(f"{path} のスキーマ検証に失敗しました:\n{detail}")
    return data


def scaffold_storyboard_template(pdir: Path, version: str, project: Dict[str, Any]) -> Path:
    """絵コンテ生成を行うエージェント向けの雛形(空のシーン配列)を書き出す。

    実際のシーン内容(video_prompt等)はこの雛形の上にエージェントが
    song_structure.jsonを踏まえて作文する。
    """
    versions_cfg = project.get("versions", {})
    v = versions_cfg.get(version, {})
    aspect = VALID_ASPECTS[version]
    duration = v.get("duration_sec", 60 if version == "short" else 180)

    template = {
        "schema_version": 2,
        "version": version,
        "aspect_ratio": aspect,
        "target_duration_sec": duration,
        "clip_duration_default_sec": v.get("clip_duration_sec", 5),
        "character_sheet": {
            "hairstyle": "",
            "outfit": "",
            "shoes": "",
            "build": "",
            "_note": (
                "必須。服装・髪型・靴・体型を固定記述にし、全シーンのvideo_promptで"
                "同じ語句を再利用すること。例: hairstyle='shoulder-length black hair "
                "with soft bangs', outfit='white long-sleeve shirt tucked into light "
                "blue denim jeans', shoes='white canvas sneakers', build='slim, "
                "170cm, young adult Japanese woman'。シーンごとに服装・髪型が変わる"
                "問題(2026-07-07オーナー指摘)への対策として必須化。"
            ),
        },
        "characters": project.get("reference_images", {}).get("characters", []),
        "world": project.get("reference_images", {}).get("world", {}),
        "scenes": [],
        "generation_note": (
            "scenesはLLM(Claude Code実行時のエージェント)がsong_structure.jsonの"
            "セクション情報をもとに作文すること。各シーンは4〜15秒、"
            "video_promptはカメラワーク・画角・雰囲気を含む英語推奨プロンプトとする。"
            "video_promptには必ずcharacter_sheetの服装・髪型・靴の記述語を含めること"
            "(バリデータが一致率をチェックする)。スタイル指定は単一方向に統一し"
            "(例: photorealistic live-actionで統一するなら anime/cel-shaded/"
            "cartoon/3D animation/CGI/Pixar-style等は全てNOTで明示除外する)、"
            "矛盾するスタイル語を同一プロンプトに混在させないこと(バリデータが検出)。"
            "物理的整合性にも注意: 靴は左右1足ずつ(片足に2つ履かせない)、自転車は"
            "進行方向と背景の流れが一致、エスカレーター/エレベーターは移動方向と"
            "人物の向きが一致するよう明記する。"
        ),
    }
    path = pdir / f"storyboard_{version}.json"
    write_json(path, template)
    return path
