"""MV Factory 共通ユーティリティ。

- .env 読み込み
- project.yaml 読み込み・バリデーション
- プロジェクトディレクトリ構成のパス解決
- 共通ログ出力
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ERROR: PyYAML が必要です。`pip3 install pyyaml` を実行してください。", file=sys.stderr)
    raise

# tools/mv-factory/mvfactory/common.py -> tools/mv-factory
MV_FACTORY_ROOT = Path(__file__).resolve().parent.parent
PROJECTS_ROOT = MV_FACTORY_ROOT / "projects"

DEFAULT_ATLAS_MODEL = "bytedance/seedance-2.0/text-to-video"

VALID_SONG_SOURCES = ("suno_api", "suno_bridge", "manual")
VALID_ASPECTS_SHORT = ("9:16",)
VALID_ASPECTS_FULL = ("16:9",)


def log(msg: str) -> None:
    print(f"[mv-factory] {msg}", flush=True)


def load_env_file(env_path: Optional[Path] = None) -> None:
    """tools/mv-factory/.env を読み、未設定の環境変数だけ埋める。

    既存の tools/seedance-api-compare/.env に ATLAS_CLOUD_API_KEY があれば
    フォールバックとして読み込む(要件定義書の指示どおり使い回し可)。
    """
    candidates = []
    if env_path is not None:
        candidates.append(Path(env_path))
    candidates.append(MV_FACTORY_ROOT / ".env")
    candidates.append(MV_FACTORY_ROOT.parent / "seedance-api-compare" / ".env")

    for path in candidates:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if value:
                os.environ.setdefault(key, value)


def project_dir(slug_or_path: str) -> Path:
    """プロジェクトディレクトリを解決する。

    絶対/相対パスが与えられればそれを使い、単純なスラッグ名なら
    projects/<slug> を返す。
    """
    p = Path(slug_or_path)
    if p.is_absolute() or p.exists():
        return p.resolve()
    return (PROJECTS_ROOT / slug_or_path).resolve()


def load_project_yaml(pdir: Path) -> Dict[str, Any]:
    yaml_path = pdir / "project.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"project.yaml が見つかりません: {yaml_path}")
    with yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    validate_project_yaml(data, yaml_path)
    return data


def validate_project_yaml(data: Dict[str, Any], source: Path) -> None:
    """必須フィールドとバリデーションルールを検証する。エラー時は例外を送出。"""
    errors = []

    required_top = ["title", "slug", "genre", "song_source"]
    for key in required_top:
        if key not in data or data[key] in (None, ""):
            errors.append(f"必須フィールド '{key}' がありません")

    song_source = data.get("song_source")
    if song_source not in VALID_SONG_SOURCES:
        errors.append(
            f"song_source は {VALID_SONG_SOURCES} のいずれかである必要があります (実際: {song_source!r})"
        )

    if song_source == "manual":
        manual = data.get("manual_audio") or {}
        if not manual.get("audio_path"):
            errors.append("song_source=manual の場合 manual_audio.audio_path が必須です")
        if not manual.get("lyrics_path"):
            errors.append("song_source=manual の場合 manual_audio.lyrics_path が必須です")

    if song_source == "suno_api":
        suno = data.get("suno_api") or {}
        if not suno.get("theme") and not data.get("theme"):
            errors.append("song_source=suno_api の場合 theme (または suno_api.theme) が必須です")

    if song_source == "suno_bridge":
        suno_bridge = data.get("suno_bridge") or {}
        instrumental = bool(suno_bridge.get("instrumental", False))
        has_lyrics = bool(suno_bridge.get("lyrics") or suno_bridge.get("lyrics_file"))
        if not instrumental and not has_lyrics:
            errors.append(
                "song_source=suno_bridge かつ instrumental=false の場合、"
                "suno_bridge.lyrics または suno_bridge.lyrics_file が必須です"
           )

    versions = data.get("versions") or {}
    for key in ("short", "full"):
        if key not in versions:
            errors.append(f"versions.{key} セクションが必須です")

    short = versions.get("short") or {}
    full = versions.get("full") or {}
    if short and short.get("aspect_ratio") not in VALID_ASPECTS_SHORT:
        errors.append(f"versions.short.aspect_ratio は {VALID_ASPECTS_SHORT} である必須があります")
    if full and full.get("aspect_ratio") not in VALID_ASPECTS_FULL:
        errors.append(f"versions.full.aspect_ratio は {VALID_ASPECTS_FULL} である必須があります")

    if errors:
        detail = "\n".join(f"  - {e}" for e in errors)
        raise ValueError(f"{source} のバリデーションに己敗しました:\n{detail}")


def read_json(path: Path) -> Any:
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def ensure_dirs(pdir: Path) -> None:
    """project.yaml の命名規則に沿ったディレクトリ構成を作成する。

    references/ は60秒版・3分版で共用(工程4の完了条件: 重複生成を避ける)。
    short/ , full/ 配下はそれぞれの中間成果物・完パケのみを置く。
    """
    for sub in [
        "",
        "short",
        "short/clips_short",
        "full",
        "full/clips_full",
        "references",
        "logs",
    ]:
        (pdir / sub).mkdir(parents=True, exist_ok=True)
