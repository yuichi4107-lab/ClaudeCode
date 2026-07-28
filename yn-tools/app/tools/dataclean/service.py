"""データクリーニングツール - クリーニングロジック"""

import io
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


# ===== 文字コード検出 =====

def detect_encoding(data: bytes) -> str:
    """UTF-8 → Shift-JIS フォールバックでエンコーディングを判定"""
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        data.decode("cp932")
        return "cp932"
    except UnicodeDecodeError:
        pass
    # chardet があれば使う
    try:
        import chardet
        result = chardet.detect(data)
        return result.get("encoding") or "utf-8"
    except ImportError:
        return "utf-8"


# ===== ファイル読み込み =====

def read_file(data: bytes, filename: str):
    """CSV または Excel を pandas DataFrame として返す"""
    import pandas as pd

    ext = Path(filename).suffix.lower()
    if ext in (".xlsx", ".xls"):
        df = pd.read_excel(io.BytesIO(data), dtype=str)
    elif ext == ".csv":
        encoding = detect_encoding(data)
        df = pd.read_csv(io.BytesIO(data), encoding=encoding, dtype=str)
    else:
        raise ValueError(f"対応していないファイル形式です: {ext}")

    return df


# ===== クリーニング処理 =====

# 全角→半角変換テーブル
_FULLHALF_TABLE = str.maketrans(
    "　！＂＃＄％＆＇（）＊＋，－．／"
    "０１２３４５６７８９"
    "：；＜＝＞？＠"
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "［＼］＾＿｀"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
    "｛｜｝～",
    " !\"#$%&'()*+,-./"
    "0123456789"
    ":;<=>?@"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "[\\]^_`"
    "abcdefghijklmnopqrstuvwxyz"
    "{|}~",
)


def _clean_fullhalf(val: str) -> str:
    """全角英数字・記号を半角に変換"""
    return val.translate(_FULLHALF_TABLE)


def _clean_phone(val: str) -> str:
    """電話番号をハイフン付き形式に統一（000-0000-0000）"""
    digits = re.sub(r"\D", "", val)
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return val  # フォーマット不明の場合は変更しない


def _clean_postal(val: str) -> str:
    """郵便番号をハイフン付き形式に統一（000-0000）"""
    digits = re.sub(r"\D", "", val)
    if len(digits) == 7:
        return f"{digits[:3]}-{digits[3:]}"
    return val


def _clean_date(val: str) -> str:
    """日付フォーマットを YYYY/MM/DD に統一"""
    import pandas as pd
    try:
        # 一般的な区切り文字を正規化してパース
        normalized = re.sub(r"[年月\-\.]", "/", val).replace("日", "").strip()
        dt = pd.to_datetime(normalized, errors="coerce")
        if pd.isna(dt):
            return val
        return dt.strftime("%Y/%m/%d")
    except Exception:
        return val


def _clean_whitespace(val: str) -> str:
    """前後の空白・改行を削除"""
    return val.strip()


# 会社名表記揺れ統一ルール（正規表現ベース）
_NAME_NORMALIZE_RULES = [
    (re.compile(r"[（(]株[）)]"), "株式会社"),
    (re.compile(r"株式?会社"), "株式会社"),  # 「株会社」も正規化
    (re.compile(r"[（(]有[）)]"), "有限会社"),
    (re.compile(r"[（(]合[）)]"), "合同会社"),
    (re.compile(r"[（(]名[）)]"), "合名会社"),
    (re.compile(r"[（(]資[）)]"), "合資会社"),
    (re.compile(r"[（(]社[）)]"), "一般社団法人"),
    (re.compile(r"[（(]財[）)]"), "公益財団法人"),
    (re.compile(r"[（(]NPO[）)]"), "NPO法人"),
    (re.compile(r"[（(]LLC[）)]"), "合同会社"),
    (re.compile(r"（株）"), "株式会社"),
    (re.compile(r"（有）"), "有限会社"),
    (re.compile(r"（合）"), "合同会社"),
]


def _clean_name_normalize(val: str) -> str:
    """会社名の表記揺れを固定ルールで統一"""
    result = val
    for pattern, replacement in _NAME_NORMALIZE_RULES:
        result = pattern.sub(replacement, result)
    return result


def apply_cleaning(df_before, options: list[str], dedup_key_col: str | None = None):
    """
    クリーニング処理を適用して (df_after, changed_cells) を返す。
    df_before は文字列型の DataFrame。
    """
    import pandas as pd
    import numpy as np

    df = df_before.copy()

    # --- empty_col: 空白列削除（先に実施） ---
    if "empty_col" in options:
        empty_cols = [
            col for col in df.columns
            if df[col].isna().all() or (df[col].astype(str).str.strip() == "").all()
        ]
        df = df.drop(columns=empty_cols)

    # --- dedup: 重複行削除 ---
    if "dedup" in options:
        subset = [dedup_key_col] if dedup_key_col and dedup_key_col in df.columns else None
        df = df.drop_duplicates(subset=subset).reset_index(drop=True)

    # セル単位の変換処理（列ごとに適用）
    cell_cleaners = []
    if "fullhalf" in options:
        cell_cleaners.append(_clean_fullhalf)
    if "phone" in options:
        cell_cleaners.append(_clean_phone)
    if "postal" in options:
        cell_cleaners.append(_clean_postal)
    if "date" in options:
        cell_cleaners.append(_clean_date)
    if "whitespace" in options:
        cell_cleaners.append(_clean_whitespace)
    if "name_normalize" in options:
        cell_cleaners.append(_clean_name_normalize)

    if cell_cleaners:
        # df_before と df の共通列で比較するため、empty_col 後の列で揃える
        common_cols = [c for c in df.columns if c in df_before.columns]

        def apply_all(val: Any) -> str:
            if pd.isna(val) or val == "":
                return val if not pd.isna(val) else ""
            s = str(val)
            for fn in cell_cleaners:
                s = fn(s)
            return s

        df = df.apply(lambda col: col.map(apply_all))

    # --- 変更セル数カウント ---
    # dedup で行数が変わった場合、削除された行数分は変更行としてカウントしない
    rows_before_subset = df_before[df_before.columns.intersection(df.columns)]
    # 共通の列・行で比較
    min_rows = min(len(df), len(rows_before_subset))
    changed_cells = 0
    if min_rows > 0 and len(df.columns) > 0:
        df_cmp_after = df.iloc[:min_rows].reset_index(drop=True).astype(str).fillna("")
        df_cmp_before = rows_before_subset.iloc[:min_rows].reset_index(drop=True).astype(str).fillna("")
        # 列を揃える
        common_cols_cmp = [c for c in df_cmp_after.columns if c in df_cmp_before.columns]
        changed_cells = int((df_cmp_after[common_cols_cmp] != df_cmp_before[common_cols_cmp]).sum().sum())

    return df, changed_cells


# ===== プレビューHTML生成 =====

def make_preview_html(df, max_rows: int = 10) -> str:
    """先頭 max_rows 行をHTMLテーブルとして返す"""
    import pandas as pd

    preview = df.head(max_rows)
    rows_html = []
    for _, row in preview.iterrows():
        cells = "".join(
            f'<td class="px-3 py-1.5 text-xs text-gray-700 border-b border-gray-100 max-w-xs truncate">{_escape_html(str(v))}</td>'
            for v in row
        )
        rows_html.append(f"<tr>{cells}</tr>")

    headers = "".join(
        f'<th class="px-3 py-2 text-xs font-semibold text-gray-500 text-left bg-gray-50 border-b border-gray-200 whitespace-nowrap">{_escape_html(str(c))}</th>'
        for c in df.columns
    )

    return (
        '<div class="overflow-auto max-h-60">'
        '<table class="min-w-full border-collapse">'
        f"<thead><tr>{headers}</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table></div>"
    )


# ===== 差分プレビューHTML生成 =====

def make_diff_html(df_before, df_after, max_rows: int = 100) -> str:
    """変更セルを黄色ハイライトしたHTMLテーブルを返す"""
    import pandas as pd

    # 共通列
    common_cols = [c for c in df_after.columns if c in df_before.columns]
    df_a = df_after[common_cols].head(max_rows).reset_index(drop=True).astype(str).fillna("")
    df_b = df_before[common_cols].head(max_rows).reset_index(drop=True).astype(str).fillna("")

    headers = "".join(
        f'<th class="px-3 py-2 text-xs font-semibold text-gray-500 text-left bg-gray-50 border-b border-gray-200 whitespace-nowrap">{_escape_html(str(c))}</th>'
        for c in common_cols
    )

    rows_html = []
    for i in range(len(df_a)):
        cells = ""
        for col in common_cols:
            before_val = df_b.iloc[i][col] if i < len(df_b) else ""
            after_val = df_a.iloc[i][col]
            changed = (before_val != after_val)
            highlight = "bg-yellow-100" if changed else ""
            title = f' title="{_escape_html(before_val)} → {_escape_html(after_val)}"' if changed else ""
            cells += (
                f'<td class="px-3 py-1.5 text-xs text-gray-700 border-b border-gray-100 max-w-xs truncate {highlight}"{title}>'
                f"{_escape_html(after_val)}</td>"
            )
        rows_html.append(f"<tr>{cells}</tr>")

    return (
        '<div class="overflow-auto max-h-96">'
        '<table class="min-w-full border-collapse">'
        f"<thead><tr>{headers}</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody>"
        "</table></div>"
    )


def _escape_html(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


# ===== ファイル保存 =====

def get_user_tmpdir(user_id: int) -> Path:
    """ユーザー別一時ディレクトリ"""
    base = Path(tempfile.gettempdir()) / "yn_dataclean" / str(user_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def save_upload(user_id: int, job_id: int, data: bytes, ext: str) -> Path:
    """アップロードファイルを一時保存して Path を返す"""
    path = get_user_tmpdir(user_id) / f"upload_{job_id}{ext}"
    path.write_bytes(data)
    return path


def save_output(user_id: int, job_id: int, df, fmt: str = "csv") -> Path:
    """クリーニング済みデータを一時保存して Path を返す"""
    import pandas as pd

    base = get_user_tmpdir(user_id)
    if fmt == "xlsx":
        path = base / f"clean_{job_id}.xlsx"
        df.to_excel(path, index=False)
    else:
        path = base / f"clean_{job_id}.csv"
        df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def delete_job_files(user_id: int, job_id: int) -> None:
    """ジョブに関連する一時ファイルを全削除"""
    base = get_user_tmpdir(user_id)
    for pat in [f"upload_{job_id}.*", f"clean_{job_id}.*"]:
        for f in base.glob(pat):
            try:
                f.unlink()
            except OSError:
                pass


def load_upload(user_id: int, job_id: int) -> tuple[bytes, str] | None:
    """保存済みアップロードファイルを読み込む。(data, ext) or None"""
    base = get_user_tmpdir(user_id)
    for ext in [".csv", ".xlsx", ".xls"]:
        path = base / f"upload_{job_id}{ext}"
        if path.exists():
            return path.read_bytes(), ext
    return None
