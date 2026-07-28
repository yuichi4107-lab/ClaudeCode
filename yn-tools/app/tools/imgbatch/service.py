"""画像一括加工ツール - 画像処理ロジック"""

import io
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

# SNSプリセット定義
SNS_PRESETS: dict[str, tuple[int, int]] = {
    "instagram_post":   (1080, 1080),
    "instagram_story":  (1080, 1920),
    "instagram_reel":   (1080, 1920),
    "x_post":           (1200, 675),
    "facebook_post":    (1200, 628),
    "youtube_thumb":    (1280, 720),
    "ogp":              (1200, 630),
    "line_timeline":    (1040, 1040),
    "tiktok":           (1080, 1920),
}

SNS_PRESET_LABELS: dict[str, str] = {
    "instagram_post":   "Instagram投稿 (1080x1080)",
    "instagram_story":  "Instagramストーリー (1080x1920)",
    "instagram_reel":   "Instagramリール (1080x1920)",
    "x_post":           "X投稿 (1200x675)",
    "facebook_post":    "Facebook投稿 (1200x628)",
    "youtube_thumb":    "YouTubeサムネイル (1280x720)",
    "ogp":              "OGP/SNSシェア (1200x630)",
    "line_timeline":    "LINEタイムライン (1040x1040)",
    "tiktok":           "TikTok (1080x1920)",
}

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
MAX_FILE_SIZE = 20 * 1024 * 1024   # 20MB
MAX_FILES = 20


# ===== ディレクトリ管理 =====

def get_user_tmpdir(user_id: int) -> Path:
    """ユーザー別一時ディレクトリ"""
    base = Path(tempfile.gettempdir()) / "yn_imgbatch" / str(user_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_job_dir(user_id: int, job_id: int) -> Path:
    """ジョブ別一時ディレクトリ"""
    d = get_user_tmpdir(user_id) / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_input_dir(user_id: int, job_id: int) -> Path:
    """入力ファイル保存ディレクトリ"""
    d = get_job_dir(user_id, job_id) / "input"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_output_dir(user_id: int, job_id: int) -> Path:
    """出力ファイル保存ディレクトリ"""
    d = get_job_dir(user_id, job_id) / "output"
    d.mkdir(parents=True, exist_ok=True)
    return d


def delete_job_files(user_id: int, job_id: int) -> None:
    """ジョブに関連する一時ファイルを全削除"""
    job_dir = get_job_dir(user_id, job_id)
    if job_dir.exists():
        shutil.rmtree(job_dir, ignore_errors=True)


# ===== ファイル保存・読み込み =====

def save_input_files(user_id: int, job_id: int, files_data: list[tuple[str, bytes]]) -> list[Path]:
    """入力ファイルを保存し、保存先パスリストを返す"""
    input_dir = get_input_dir(user_id, job_id)
    saved = []
    for filename, data in files_data:
        path = input_dir / filename
        path.write_bytes(data)
        saved.append(path)
    return saved


def load_input_files(user_id: int, job_id: int) -> list[Path]:
    """保存済み入力ファイルリストを返す"""
    input_dir = get_input_dir(user_id, job_id)
    if not input_dir.exists():
        return []
    return sorted(input_dir.iterdir())


def make_thumbnail_data_url(data: bytes, ext: str) -> str:
    """画像データをbase64 data URLに変換（プレビュー用）"""
    import base64
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.thumbnail((120, 120))
        buf = io.BytesIO()
        fmt = "PNG" if img.mode in ("RGBA", "LA", "P") else "JPEG"
        if img.mode == "P":
            img = img.convert("RGBA")
        img.save(buf, format=fmt)
        b64 = base64.b64encode(buf.getvalue()).decode()
        mime = "image/png" if fmt == "PNG" else "image/jpeg"
        return f"data:{mime};base64,{b64}"
    except Exception:
        return ""


# ===== 画像処理 =====

def _open_image(data: bytes):
    """Pillowで画像を開く。RGBモードに統一（透過チャンネルはRGBAを保持）"""
    from PIL import Image
    img = Image.open(io.BytesIO(data))
    if img.format == "GIF":
        img = img.convert("RGBA")
    return img


def _save_image(img, output_format: str, quality: int = 85) -> bytes:
    """指定フォーマットで画像をバイト列として保存"""
    from PIL import Image
    buf = io.BytesIO()
    fmt = output_format.upper()
    if fmt == "JPG":
        fmt = "JPEG"
    if fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
        img = bg
    elif fmt in ("PNG", "WEBP") and img.mode == "P":
        img = img.convert("RGBA")

    if fmt == "JPEG":
        img.save(buf, format="JPEG", quality=quality, optimize=True)
    elif fmt == "WEBP":
        img.save(buf, format="WEBP", quality=quality)
    elif fmt == "AVIF":
        img.save(buf, format="AVIF", quality=quality)
    else:
        img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def process_resize_preset(data: bytes, src_name: str, preset_name: str) -> tuple[str, bytes]:
    """SNSプリセットサイズにリサイズ。(output_filename, output_bytes) を返す"""
    from PIL import Image
    w, h = SNS_PRESETS[preset_name]
    img = _open_image(data)

    # アスペクト比を保持してリサイズ後、中央クロップ
    src_ratio = img.width / img.height
    tgt_ratio = w / h
    if src_ratio > tgt_ratio:
        # 横が長い: 高さ合わせ
        new_h = h
        new_w = int(new_h * src_ratio)
    else:
        # 縦が長い: 幅合わせ
        new_w = w
        new_h = int(new_w / src_ratio)

    img = img.resize((new_w, new_h), Image.LANCZOS)

    # 中央クロップ
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    img = img.crop((left, top, left + w, top + h))

    stem = Path(src_name).stem
    # 出力拡張子は入力と同じ（JPG系はJPG）
    src_ext = Path(src_name).suffix.lower()
    if src_ext in (".jpg", ".jpeg"):
        out_ext = ".jpg"
        out_data = _save_image(img, "JPEG")
    elif src_ext == ".png":
        out_ext = ".png"
        out_data = _save_image(img, "PNG")
    elif src_ext == ".webp":
        out_ext = ".webp"
        out_data = _save_image(img, "WEBP")
    else:
        out_ext = ".jpg"
        out_data = _save_image(img, "JPEG")

    out_name = f"{stem}_{preset_name}{out_ext}"
    return out_name, out_data


def process_resize_custom(data: bytes, src_name: str, width: int, height: int) -> tuple[str, bytes]:
    """カスタムサイズにリサイズ"""
    from PIL import Image
    img = _open_image(data)
    img = img.resize((width, height), Image.LANCZOS)

    stem = Path(src_name).stem
    src_ext = Path(src_name).suffix.lower()
    if src_ext in (".jpg", ".jpeg"):
        out_ext = ".jpg"
        out_data = _save_image(img, "JPEG")
    elif src_ext == ".png":
        out_ext = ".png"
        out_data = _save_image(img, "PNG")
    elif src_ext == ".webp":
        out_ext = ".webp"
        out_data = _save_image(img, "WEBP")
    else:
        out_ext = ".jpg"
        out_data = _save_image(img, "JPEG")

    out_name = f"{stem}_custom_{width}x{height}{out_ext}"
    return out_name, out_data


def process_format_convert(data: bytes, src_name: str, output_format: str) -> tuple[str, bytes]:
    """フォーマット変換"""
    img = _open_image(data)
    stem = Path(src_name).stem
    fmt_lower = output_format.lower()
    out_ext = f".{fmt_lower}"
    if fmt_lower == "jpg":
        out_ext = ".jpg"
    out_data = _save_image(img, output_format)
    out_name = f"{stem}_converted{out_ext}"
    return out_name, out_data


def process_bg_remove(data: bytes, src_name: str) -> tuple[str, bytes]:
    """rembgによる背景除去。出力は透過PNG"""
    try:
        from rembg import remove
    except ImportError:
        raise RuntimeError("背景除去機能は現在ご利用いただけません。管理者にお問い合わせください。")

    output_data = remove(data)
    if not output_data:
        raise ValueError("背景除去の処理に失敗しました（出力が空です）。")

    # α値の検証: RGBAでない場合は変換
    from PIL import Image
    img = Image.open(io.BytesIO(output_data))
    if img.mode != "RGBA":
        img = img.convert("RGBA")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        output_data = buf.getvalue()

    stem = Path(src_name).stem
    out_name = f"{stem}_nobg.png"
    return out_name, output_data


def process_crop_center(data: bytes, src_name: str, width: int, height: int) -> tuple[str, bytes]:
    """中央クロップ（アスペクト比指定）"""
    from PIL import Image
    img = _open_image(data)

    src_ratio = img.width / img.height
    tgt_ratio = width / height
    if src_ratio > tgt_ratio:
        new_h = img.height
        new_w = int(new_h * tgt_ratio)
    else:
        new_w = img.width
        new_h = int(new_w / tgt_ratio)

    left = (img.width - new_w) // 2
    top = (img.height - new_h) // 2
    img = img.crop((left, top, left + new_w, top + new_h))
    img = img.resize((width, height), Image.LANCZOS)

    stem = Path(src_name).stem
    src_ext = Path(src_name).suffix.lower()
    if src_ext in (".jpg", ".jpeg"):
        out_ext = ".jpg"
        out_data = _save_image(img, "JPEG")
    else:
        out_ext = ".png"
        out_data = _save_image(img, "PNG")

    out_name = f"{stem}_crop_{width}x{height}{out_ext}"
    return out_name, out_data


def process_optimize(data: bytes, src_name: str, quality: int = 75) -> tuple[str, bytes]:
    """ファイルサイズ最適化"""
    img = _open_image(data)
    stem = Path(src_name).stem
    src_ext = Path(src_name).suffix.lower()

    if src_ext in (".jpg", ".jpeg"):
        out_ext = ".jpg"
        out_data = _save_image(img, "JPEG", quality=quality)
    elif src_ext == ".png":
        out_ext = ".png"
        out_data = _save_image(img, "PNG")
    elif src_ext == ".webp":
        out_ext = ".webp"
        out_data = _save_image(img, "WEBP", quality=quality)
    else:
        out_ext = ".jpg"
        out_data = _save_image(img, "JPEG", quality=quality)

    out_name = f"{stem}_optimized{out_ext}"
    return out_name, out_data


# ===== バッチ処理メイン =====

def run_batch(
    user_id: int,
    job_id: int,
    mode: str,
    preset_names: list[str] | None = None,
    custom_w: int | None = None,
    custom_h: int | None = None,
    output_format: str | None = None,
) -> tuple[int, str]:
    """
    バッチ処理を実行し (output_file_count, zip_path) を返す。
    エラー時は例外を送出。
    """
    input_files = load_input_files(user_id, job_id)
    if not input_files:
        raise ValueError("入力ファイルが見つかりません。")

    output_dir = get_output_dir(user_id, job_id)
    output_items: list[tuple[str, bytes]] = []  # (filename, data)

    for fpath in input_files:
        data = fpath.read_bytes()
        src_name = fpath.name

        try:
            if mode == "resize_preset":
                presets = preset_names or []
                for preset in presets:
                    if preset not in SNS_PRESETS:
                        continue
                    out_name, out_data = process_resize_preset(data, src_name, preset)
                    output_items.append((out_name, out_data))

            elif mode == "resize_custom":
                if not custom_w or not custom_h:
                    raise ValueError("カスタムサイズの幅・高さを指定してください。")
                out_name, out_data = process_resize_custom(data, src_name, custom_w, custom_h)
                output_items.append((out_name, out_data))

            elif mode == "format_convert":
                fmt = output_format or "jpg"
                out_name, out_data = process_format_convert(data, src_name, fmt)
                output_items.append((out_name, out_data))

            elif mode == "bg_remove":
                out_name, out_data = process_bg_remove(data, src_name)
                output_items.append((out_name, out_data))

            elif mode == "crop_center":
                if not custom_w or not custom_h:
                    raise ValueError("クロップサイズの幅・高さを指定してください。")
                out_name, out_data = process_crop_center(data, src_name, custom_w, custom_h)
                output_items.append((out_name, out_data))

            elif mode == "optimize":
                out_name, out_data = process_optimize(data, src_name)
                output_items.append((out_name, out_data))

            else:
                raise ValueError(f"未対応のモード: {mode}")

        except RuntimeError:
            raise
        except Exception as e:
            raise ValueError(f"{src_name} の処理に失敗しました: {str(e)}")

    if not output_items:
        raise ValueError("出力ファイルが生成されませんでした。")

    # 出力ファイルを保存
    for out_name, out_data in output_items:
        (output_dir / out_name).write_bytes(out_data)

    # ZIPアーカイブ作成
    zip_path = get_job_dir(user_id, job_id) / f"batch_{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for out_name, out_data in output_items:
            zf.writestr(out_name, out_data)

    return len(output_items), str(zip_path)


def get_output_thumbnails(user_id: int, job_id: int) -> list[dict]:
    """出力ファイルのサムネイル情報リストを返す"""
    output_dir = get_output_dir(user_id, job_id)
    if not output_dir.exists():
        return []

    result = []
    for fpath in sorted(output_dir.iterdir()):
        if fpath.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}:
            continue
        try:
            data = fpath.read_bytes()
            thumb = make_thumbnail_data_url(data, fpath.suffix)
            size_kb = len(data) / 1024
            result.append({
                "filename": fpath.name,
                "size_kb": round(size_kb, 1),
                "thumbnail": thumb,
            })
        except Exception:
            pass
    return result
