"""EPUBバリデーター - KDP出版前チェック（Level 1 + Level 2）

zipfile + lxml のみで実装。外部バイナリ（Java等）不要。
ファイルはメモリ上のみで処理し、ディスクには書き出さない。
"""

import re
import struct
import zipfile
from io import BytesIO
from typing import Literal

from lxml import etree

# ------------------------------------------------------------------ #
# 定数
# ------------------------------------------------------------------ #
MAX_ENTRIES = 10_000          # ZIP エントリ数上限（ZIP スラム対策）
MAX_ENTRY_SIZE = 500 * 1024 * 1024  # 1 エントリの展開サイズ上限 500MB
MAX_TOTAL_UNCOMPRESSED = 5 * 1024 * 1024 * 1024  # 展開後合計サイズ上限 5GB

# Dublin Core 名前空間
DC_NS = "http://purl.org/dc/elements/1.1/"
OPF_NS = "http://www.idpf.org/2007/opf"
CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

# フォント MIME タイプ
FONT_MIMES = {
    "application/font-woff",
    "application/font-woff2",
    "application/vnd.ms-opentype",
    "font/ttf",
    "font/otf",
    "font/woff",
    "font/woff2",
    "application/x-font-otf",
    "application/x-font-ttf",
}

# 画像 MIME タイプ
IMAGE_MIMES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/gif",
    "image/svg+xml",
    "image/webp",
}

CheckStatus = Literal["pass", "warn", "fail"]


# ------------------------------------------------------------------ #
# ユーティリティ
# ------------------------------------------------------------------ #

def _make_check(
    id_: str,
    category: str,
    label: str,
    status: CheckStatus,
    message: str,
    detail: str | None = None,
) -> dict:
    """チェック結果 dict を生成する。"""
    return {
        "id": id_,
        "category": category,
        "label": label,
        "status": status,
        "message": message,
        "detail": detail,
    }


def _skipped_check(id_: str, category: str, label: str) -> dict:
    """前提チェック失敗によりスキップされたチェック結果を返す。"""
    return _make_check(
        id_=id_,
        category=category,
        label=label,
        status="fail",
        message="前提チェック失敗のためスキップ",
        detail=None,
    )


# ------------------------------------------------------------------ #
# セキュリティチェック（ZIP 開封前）
# ------------------------------------------------------------------ #

def _security_check_bytes(file_bytes: bytes) -> list[str]:
    """
    ZIPを開く前にセキュリティ上の問題を検査する。
    問題があればエラーメッセージのリストを返す（空なら問題なし）。
    """
    errors: list[str] = []

    # まず zipfile が開けるか確認（開けない場合はここでは空 list を返して
    # 後続の zip_structure チェックで fail にする）
    if not zipfile.is_zipfile(BytesIO(file_bytes)):
        return errors  # zip_structure チェックに委ねる

    try:
        with zipfile.ZipFile(BytesIO(file_bytes), "r") as zf:
            infos = zf.infolist()

            # エントリ数上限チェック
            if len(infos) > MAX_ENTRIES:
                errors.append(
                    f"ZIPエントリ数が上限（{MAX_ENTRIES:,}）を超えています "
                    f"（実際: {len(infos):,}）。ZIP スラム攻撃の可能性があります。"
                )
                return errors  # これ以上チェック不要

            # パストラバーサルチェック + 展開後サイズチェック
            total_uncompressed = 0
            for info in infos:
                name = info.filename
                # パスインジェクション検出
                if ".." in name.split("/") or name.startswith("/"):
                    errors.append(
                        f"ZIPエントリ名にディレクトリトラバーサルが含まれています: {name!r}"
                    )
                    return errors

                # 1 エントリのサイズ上限
                if info.file_size > MAX_ENTRY_SIZE:
                    errors.append(
                        f"単一エントリの展開サイズが上限（500MB）を超えています: "
                        f"{name!r} ({info.file_size / 1024 / 1024:.1f} MB)"
                    )
                    return errors

                total_uncompressed += info.file_size

            # 展開後合計サイズ上限
            if total_uncompressed > MAX_TOTAL_UNCOMPRESSED:
                errors.append(
                    f"ZIP展開後の合計サイズが上限（5GB）を超えています "
                    f"（推定: {total_uncompressed / 1024 / 1024 / 1024:.2f} GB）。"
                    "ZIP 爆弾の可能性があります。"
                )

    except zipfile.BadZipFile:
        pass  # zip_structure チェックに委ねる
    except Exception as e:
        errors.append(f"セキュリティチェック中に予期しないエラーが発生しました: {e}")

    return errors


# ------------------------------------------------------------------ #
# Level 1: 基本チェック
# ------------------------------------------------------------------ #

def _check_zip_structure(file_bytes: bytes) -> dict:
    """zip_structure: ZIP として開けるか確認する。"""
    try:
        if not zipfile.is_zipfile(BytesIO(file_bytes)):
            return _make_check(
                "zip_structure", "基本チェック", "ZIP 構造",
                "fail", "ZIP ファイルとして開けません（ファイルが破損しているか、EPUB ではありません）"
            )
        # 実際に開けるか確認
        with zipfile.ZipFile(BytesIO(file_bytes), "r") as _:
            pass
        return _make_check(
            "zip_structure", "基本チェック", "ZIP 構造",
            "pass", "ZIP ファイルとして正常に開けます"
        )
    except zipfile.BadZipFile as e:
        return _make_check(
            "zip_structure", "基本チェック", "ZIP 構造",
            "fail", f"ZIP ファイルが破損しています: {e}"
        )
    except Exception as e:
        return _make_check(
            "zip_structure", "基本チェック", "ZIP 構造",
            "fail", f"ZIP 開封中にエラーが発生しました: {e}"
        )


def _check_mimetype(zf: zipfile.ZipFile) -> dict:
    """mimetype: mimetype ファイルが先頭・無圧縮・正しい内容か確認する。"""
    names = zf.namelist()
    if "mimetype" not in names:
        return _make_check(
            "mimetype", "基本チェック", "mimetype ファイル",
            "fail", "mimetype ファイルが存在しません"
        )

    # 先頭エントリか確認
    if names[0] != "mimetype":
        return _make_check(
            "mimetype", "基本チェック", "mimetype ファイル",
            "fail",
            f"mimetype ファイルが先頭にありません（実際の先頭: {names[0]!r}）。"
            "EPUB 仕様では mimetype が ZIP の最初のエントリである必要があります。",
            detail=f"先頭エントリ: {names[0]!r}"
        )

    # 無圧縮（STORED）か確認
    info = zf.getinfo("mimetype")
    if info.compress_type != zipfile.ZIP_STORED:
        return _make_check(
            "mimetype", "基本チェック", "mimetype ファイル",
            "fail",
            "mimetype ファイルが圧縮されています（STORED である必要があります）",
            detail=f"compress_type: {info.compress_type}"
        )

    # 内容確認
    content = zf.read("mimetype").decode("ascii", errors="replace").strip()
    if content != "application/epub+zip":
        return _make_check(
            "mimetype", "基本チェック", "mimetype ファイル",
            "fail",
            f"mimetype の内容が不正です（期待値: 'application/epub+zip'）",
            detail=f"実際の内容: {content!r}"
        )

    return _make_check(
        "mimetype", "基本チェック", "mimetype ファイル",
        "pass", "mimetype ファイルは正常です（先頭・無圧縮・内容OK）"
    )


def _check_container_xml(zf: zipfile.ZipFile) -> tuple[dict, str | None]:
    """
    container_xml: META-INF/container.xml が存在し OPF パスを返せるか確認する。
    戻り値: (チェック結果, OPF パス or None)
    """
    if "META-INF/container.xml" not in zf.namelist():
        return (
            _make_check(
                "container_xml", "基本チェック", "container.xml",
                "fail", "META-INF/container.xml が存在しません"
            ),
            None
        )

    try:
        xml_bytes = zf.read("META-INF/container.xml")
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        return (
            _make_check(
                "container_xml", "基本チェック", "container.xml",
                "fail", f"container.xml の XML パースに失敗しました: {e}"
            ),
            None
        )

    # OPF パスを取得
    # <rootfile full-path="..." media-type="application/oebps-package+xml"/>
    ns = {"c": CONTAINER_NS}
    rootfiles = root.findall(".//c:rootfile", ns)
    if not rootfiles:
        # 名前空間なしでも試みる
        rootfiles = root.findall(".//{*}rootfile")

    if not rootfiles:
        return (
            _make_check(
                "container_xml", "基本チェック", "container.xml",
                "fail", "container.xml 内に rootfile 要素が見つかりません"
            ),
            None
        )

    opf_path = rootfiles[0].get("full-path")
    if not opf_path:
        return (
            _make_check(
                "container_xml", "基本チェック", "container.xml",
                "fail", "rootfile 要素の full-path 属性が空です"
            ),
            None
        )

    return (
        _make_check(
            "container_xml", "基本チェック", "container.xml",
            "pass", "container.xml は正常です",
            detail=f"OPF パス: {opf_path}"
        ),
        opf_path
    )


def _check_opf_valid(zf: zipfile.ZipFile, opf_path: str) -> tuple[dict, etree._Element | None]:
    """
    opf_valid: OPF ファイルが存在し XML として valid か確認する。
    戻り値: (チェック結果, OPF root element or None)
    """
    # ZIP 内のパスは / 区切り
    opf_path_in_zip = opf_path.lstrip("/")
    if opf_path_in_zip not in zf.namelist():
        return (
            _make_check(
                "opf_valid", "基本チェック", "OPF 構造",
                "fail",
                f"container.xml で指定された OPF ファイルが存在しません: {opf_path!r}"
            ),
            None
        )

    try:
        xml_bytes = zf.read(opf_path_in_zip)
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        return (
            _make_check(
                "opf_valid", "基本チェック", "OPF 構造",
                "fail", f"OPF ファイルの XML パースに失敗しました: {e}"
            ),
            None
        )

    return (
        _make_check(
            "opf_valid", "基本チェック", "OPF 構造",
            "pass", "OPF ファイルは正常な XML です",
            detail=opf_path
        ),
        root
    )


def _check_metadata_field(
    opf_root: etree._Element,
    field_id: str,
    dc_tag: str,
    label: str,
    required: bool = True,
) -> dict:
    """
    dc:title / dc:creator / dc:language / dc:identifier 等を確認する汎用関数。
    """
    # 名前空間付きで検索
    elements = opf_root.findall(f".//{{{DC_NS}}}{dc_tag}")
    if not elements:
        # 名前空間なしでもフォールバック検索
        elements = opf_root.findall(f".//{dc_tag}")

    if not elements:
        status = "fail" if required else "warn"
        return _make_check(
            field_id, "基本チェック", label,
            status, f"<dc:{dc_tag}> が見つかりません"
        )

    text = (elements[0].text or "").strip()
    if not text:
        return _make_check(
            field_id, "基本チェック", label,
            "fail", f"<dc:{dc_tag}> が空です（値が必要です）"
        )

    return _make_check(
        field_id, "基本チェック", label,
        "pass", f"<dc:{dc_tag}> が設定されています",
        detail=text[:100]  # 最大100文字
    )


def _check_manifest_files(
    zf: zipfile.ZipFile,
    opf_root: etree._Element,
    opf_path: str,
) -> dict:
    """manifest_files: manifest の全 href が ZIP 内に存在するか確認する。"""
    # OPF ファイルのベースディレクトリ
    opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

    manifest = opf_root.find(f"{{{OPF_NS}}}manifest")
    if manifest is None:
        manifest = opf_root.find("{*}manifest")
    if manifest is None:
        manifest = opf_root.find("manifest")

    if manifest is None:
        return _make_check(
            "manifest_files", "基本チェック", "マニフェスト参照切れ",
            "fail", "OPF ファイルに manifest 要素が見つかりません"
        )

    zip_names = set(zf.namelist())
    broken = []
    items = manifest.findall(f"{{{OPF_NS}}}item")
    if not items:
        items = manifest.findall("{*}item")
    if not items:
        items = manifest.findall("item")

    for item in items:
        href = item.get("href", "")
        if not href:
            continue
        # 相対 URL のフラグメント（#）除去
        href = href.split("#")[0]
        # パーセントエンコードをデコード（簡易）
        try:
            from urllib.parse import unquote
            href = unquote(href)
        except Exception:
            pass

        full_path = opf_dir + href if not href.startswith("/") else href.lstrip("/")
        # パス正規化（../等の解決）
        # シンプルに正規化
        parts = []
        for part in full_path.split("/"):
            if part == "..":
                if parts:
                    parts.pop()
            elif part and part != ".":
                parts.append(part)
        normalized = "/".join(parts)

        if normalized not in zip_names:
            broken.append(href)

    if broken:
        return _make_check(
            "manifest_files", "基本チェック", "マニフェスト参照切れ",
            "fail",
            f"manifest に記載されたファイルが {len(broken)} 件 ZIP 内に存在しません",
            detail=", ".join(broken[:5]) + ("..." if len(broken) > 5 else "")
        )

    return _make_check(
        "manifest_files", "基本チェック", "マニフェスト参照切れ",
        "pass",
        f"manifest の全ファイル（{len(items)} 件）が ZIP 内に存在します"
    )


def _check_nav_ncx(
    zf: zipfile.ZipFile,
    opf_root: etree._Element,
    opf_path: str,
) -> dict:
    """nav_ncx: NAV（EPUB3）または NCX（EPUB2）が存在するか確認する。"""
    opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

    manifest = opf_root.find(f"{{{OPF_NS}}}manifest")
    if manifest is None:
        manifest = opf_root.find("{*}manifest")
    if manifest is None:
        manifest = opf_root.find("manifest")

    if manifest is None:
        return _make_check(
            "nav_ncx", "基本チェック", "NAV / NCX",
            "fail", "manifest 要素が見つかりません"
        )

    items = manifest.findall(f"{{{OPF_NS}}}item")
    if not items:
        items = manifest.findall("{*}item")
    if not items:
        items = manifest.findall("item")

    zip_names = set(zf.namelist())

    # EPUB3 NAV: properties="nav"
    for item in items:
        props = item.get("properties", "")
        if "nav" in props.split():
            href = item.get("href", "")
            if href:
                full_path = opf_dir + href if not href.startswith("/") else href.lstrip("/")
                return _make_check(
                    "nav_ncx", "基本チェック", "NAV / NCX",
                    "pass", "EPUB3 NAV ドキュメントが存在します",
                    detail=full_path
                )

    # EPUB2 NCX: media-type="application/x-dtbncx+xml"
    for item in items:
        media_type = item.get("media-type", "")
        if media_type == "application/x-dtbncx+xml":
            href = item.get("href", "")
            if href:
                full_path = opf_dir + href if not href.startswith("/") else href.lstrip("/")
                if full_path in zip_names:
                    return _make_check(
                        "nav_ncx", "基本チェック", "NAV / NCX",
                        "pass", "EPUB2 NCX ファイルが存在します",
                        detail=full_path
                    )

    # フォールバック: .ncx 拡張子のファイルを探す
    for name in zip_names:
        if name.endswith(".ncx"):
            return _make_check(
                "nav_ncx", "基本チェック", "NAV / NCX",
                "pass", "NCX ファイルが存在します（フォールバック検出）",
                detail=name
            )

    return _make_check(
        "nav_ncx", "基本チェック", "NAV / NCX",
        "fail",
        "NAV ドキュメント（EPUB3）も NCX ファイル（EPUB2）も見つかりません"
    )


# ------------------------------------------------------------------ #
# Level 2: KDP 特化チェック
# ------------------------------------------------------------------ #

def _get_cover_image_path(
    opf_root: etree._Element,
    opf_path: str,
) -> str | None:
    """OPF から表紙画像のパスを取得する。"""
    opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

    manifest = opf_root.find(f"{{{OPF_NS}}}manifest")
    if manifest is None:
        manifest = opf_root.find("{*}manifest")
    if manifest is None:
        manifest = opf_root.find("manifest")

    if manifest is None:
        return None

    items = manifest.findall(f"{{{OPF_NS}}}item")
    if not items:
        items = manifest.findall("{*}item")
    if not items:
        items = manifest.findall("item")

    # EPUB3: properties="cover-image"
    for item in items:
        props = item.get("properties", "")
        if "cover-image" in props.split():
            href = item.get("href", "")
            if href:
                return opf_dir + href if not href.startswith("/") else href.lstrip("/")

    # EPUB2: <meta name="cover" content="item-id"/>
    metadata = opf_root.find(f"{{{OPF_NS}}}metadata")
    if metadata is None:
        metadata = opf_root.find("{*}metadata")
    if metadata is None:
        metadata = opf_root.find("metadata")

    if metadata is not None:
        for meta in metadata.findall("*"):
            name = meta.get("name", "")
            if name.lower() == "cover":
                cover_id = meta.get("content", "")
                if cover_id:
                    for item in items:
                        if item.get("id") == cover_id:
                            href = item.get("href", "")
                            if href:
                                return opf_dir + href if not href.startswith("/") else href.lstrip("/")

    return None


def _read_image_dimensions(image_bytes: bytes, media_type: str = "") -> tuple[int, int] | None:
    """
    PNG/JPEG バイナリから画像の (width, height) を読み取る。
    Pillow を使わず、ヘッダーを直接解析する。
    """
    if not image_bytes:
        return None

    # PNG: シグネチャ 8 バイト + IHDR チャンク
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        try:
            # IHDR: オフセット16から幅(4bytes)+高さ(4bytes)
            width = struct.unpack(">I", image_bytes[16:20])[0]
            height = struct.unpack(">I", image_bytes[20:24])[0]
            return (width, height)
        except Exception:
            return None

    # JPEG: SOI マーカー FF D8 から始まる
    if image_bytes[:2] == b"\xff\xd8":
        try:
            offset = 2
            while offset < len(image_bytes) - 1:
                if image_bytes[offset] != 0xFF:
                    break
                marker = image_bytes[offset + 1]
                offset += 2
                # SOF マーカー（画像サイズを含む）
                if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                              0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    # セグメント長(2) + 精度(1) + 高さ(2) + 幅(2)
                    height = struct.unpack(">H", image_bytes[offset + 3: offset + 5])[0]
                    width = struct.unpack(">H", image_bytes[offset + 5: offset + 7])[0]
                    return (width, height)
                # その他マーカー: セグメント長を読んで次へ
                length = struct.unpack(">H", image_bytes[offset: offset + 2])[0]
                offset += length
        except Exception:
            return None

    # Pillow でフォールバック（インストール済みの場合）
    try:
        from PIL import Image
        img = Image.open(BytesIO(image_bytes))
        return img.size  # (width, height)
    except Exception:
        return None


def _check_cover_image_exists(
    zf: zipfile.ZipFile,
    opf_root: etree._Element,
    opf_path: str,
) -> tuple[dict, str | None]:
    """
    cover_image_exists: 表紙画像が指定されているか確認する。
    戻り値: (チェック結果, 表紙画像 ZIP パス or None)
    """
    cover_path = _get_cover_image_path(opf_root, opf_path)

    if cover_path is None:
        return (
            _make_check(
                "cover_image_exists", "KDP 特化チェック", "表紙画像",
                "fail",
                "表紙画像が指定されていません。"
                "OPF の manifest に properties=\"cover-image\" または "
                "<meta name=\"cover\"> が必要です。"
            ),
            None
        )

    zip_names = set(zf.namelist())
    if cover_path not in zip_names:
        return (
            _make_check(
                "cover_image_exists", "KDP 特化チェック", "表紙画像",
                "fail",
                f"表紙画像が指定されていますが、ファイルが ZIP 内に存在しません: {cover_path!r}"
            ),
            None
        )

    return (
        _make_check(
            "cover_image_exists", "KDP 特化チェック", "表紙画像",
            "pass", "表紙画像が指定されており、ファイルも存在します",
            detail=cover_path
        ),
        cover_path
    )


def _check_cover_image_size(
    zf: zipfile.ZipFile,
    cover_path: str,
) -> dict:
    """
    cover_image_size: 表紙画像の解像度・アスペクト比を確認する。
    - 最小辺 >= 1000px: pass
    - アスペクト比が推奨範囲外（1.6:1 〜 1:1.6）: warn
    - 最小辺 < 1000px: fail
    """
    try:
        image_bytes = zf.read(cover_path)
    except Exception as e:
        return _make_check(
            "cover_image_size", "KDP 特化チェック", "表紙サイズ",
            "fail", f"表紙画像の読み込みに失敗しました: {e}"
        )

    dims = _read_image_dimensions(image_bytes)
    if dims is None:
        return _make_check(
            "cover_image_size", "KDP 特化チェック", "表紙サイズ",
            "warn",
            "表紙画像のサイズを読み取れませんでした（PNG / JPEG 以外の形式の可能性があります）",
            detail=cover_path
        )

    width, height = dims
    min_side = min(width, height)
    max_side = max(width, height)

    # KDP 推奨: 最大辺 10000px まで
    if max_side > 10000:
        return _make_check(
            "cover_image_size", "KDP 特化チェック", "表紙サイズ",
            "fail",
            f"表紙画像の最大辺が 10,000px を超えています: {max_side}px",
            detail=f"{width} x {height} px"
        )

    if min_side < 1000:
        return _make_check(
            "cover_image_size", "KDP 特化チェック", "表紙サイズ",
            "fail",
            f"表紙画像の最小辺が 1,000px 未満です（KDP 要件）: {min_side}px",
            detail=f"{width} x {height} px"
        )

    # アスペクト比チェック: 推奨 1:1.6（縦長）
    if height > 0 and width > 0:
        ratio = max(width, height) / min(width, height)
        # 推奨範囲: 1.0 〜 1.6 の間（正方形 〜 縦長 1.6）
        # 横長（width > height）または極端に縦長（ratio > 2.0）は warn
        if width > height:
            return _make_check(
                "cover_image_size", "KDP 特化チェック", "表紙サイズ",
                "warn",
                "表紙画像が横長です（KDP では縦長 1:1.6 程度を推奨）",
                detail=f"{width} x {height} px (ratio: {width/height:.2f}:1)"
            )
        if ratio > 2.0:
            return _make_check(
                "cover_image_size", "KDP 特化チェック", "表紙サイズ",
                "warn",
                f"表紙画像のアスペクト比が推奨範囲外です（縦長すぎ: 1:{ratio:.2f}）",
                detail=f"{width} x {height} px"
            )

    return _make_check(
        "cover_image_size", "KDP 特化チェック", "表紙サイズ",
        "pass",
        f"表紙画像のサイズは問題ありません",
        detail=f"{width} x {height} px"
    )


def _check_fixed_layout(opf_root: etree._Element) -> tuple[dict, bool]:
    """
    fixed_layout: 固定レイアウト（pre-paginated）かどうかを判定する。
    固定レイアウトなら warn（情報提供）、そうでなければ pass。
    戻り値: (チェック結果, is_fixed_layout)
    """
    metadata = opf_root.find(f"{{{OPF_NS}}}metadata")
    if metadata is None:
        metadata = opf_root.find("{*}metadata")
    if metadata is None:
        metadata = opf_root.find("metadata")

    is_fixed = False

    if metadata is not None:
        for meta in metadata.findall("*"):
            # EPUB3: <meta property="rendition:layout">pre-paginated</meta>
            prop = meta.get("property", "")
            if prop == "rendition:layout":
                text = (meta.text or "").strip()
                if text == "pre-paginated":
                    is_fixed = True
                    break

    if is_fixed:
        return (
            _make_check(
                "fixed_layout", "KDP 特化チェック", "固定レイアウト判定",
                "warn",
                "固定レイアウト（pre-paginated）が検出されました。"
                "KDP マンガ・コミック等では通常の設定ですが、"
                "リフロー型 EPUB には適用されません。"
            ),
            True
        )

    return (
        _make_check(
            "fixed_layout", "KDP 特化チェック", "固定レイアウト判定",
            "pass", "固定レイアウト設定は検出されませんでした（リフロー型）"
        ),
        False
    )


def _check_font_embedded(
    zf: zipfile.ZipFile,
    opf_root: etree._Element,
    opf_path: str,
) -> dict:
    """
    font_embedded: manifest にフォントファイルが含まれているか確認する。
    存在しない場合は warn（フォント埋め込みは任意）。
    """
    opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

    manifest = opf_root.find(f"{{{OPF_NS}}}manifest")
    if manifest is None:
        manifest = opf_root.find("{*}manifest")
    if manifest is None:
        manifest = opf_root.find("manifest")

    if manifest is None:
        return _make_check(
            "font_embedded", "KDP 特化チェック", "フォント埋め込み",
            "warn", "manifest が見つからないためフォントを確認できません"
        )

    items = manifest.findall(f"{{{OPF_NS}}}item")
    if not items:
        items = manifest.findall("{*}item")
    if not items:
        items = manifest.findall("item")

    zip_names = set(zf.namelist())
    found_fonts = []

    for item in items:
        media_type = (item.get("media-type") or "").lower()
        href = item.get("href", "")

        is_font_by_mime = media_type in FONT_MIMES
        # 拡張子でもフォールバック
        is_font_by_ext = href.lower().endswith((".woff", ".woff2", ".otf", ".ttf"))

        if is_font_by_mime or is_font_by_ext:
            full_path = opf_dir + href if not href.startswith("/") else href.lstrip("/")
            if full_path in zip_names:
                found_fonts.append(href)

    if not found_fonts:
        return _make_check(
            "font_embedded", "KDP 特化チェック", "フォント埋め込み",
            "warn",
            "フォントファイルが埋め込まれていません。"
            "日本語テキストを含む場合はフォント埋め込みを推奨します。"
        )

    return _make_check(
        "font_embedded", "KDP 特化チェック", "フォント埋め込み",
        "pass",
        f"フォントファイルが {len(found_fonts)} 件埋め込まれています",
        detail=", ".join(found_fonts[:3]) + ("..." if len(found_fonts) > 3 else "")
    )


def _check_file_size_warning(file_size_bytes: int) -> dict:
    """
    file_size_warning: ファイルサイズに応じて pass / warn / fail を返す。
    - < 50MB: pass
    - 50MB 以上 500MB 未満: warn（DL 負荷）
    - >= 500MB: fail（KDP 制限に迫る）
    """
    mb = file_size_bytes / 1024 / 1024

    if mb >= 500:
        return _make_check(
            "file_size_warning", "KDP 特化チェック", "ファイルサイズ",
            "fail",
            f"ファイルサイズが KDP の上限（500MB 級）に達しています: {mb:.1f} MB。"
            "画像を圧縮するか、ファイルを分割してください。",
            detail=f"{mb:.1f} MB"
        )
    elif mb >= 50:
        return _make_check(
            "file_size_warning", "KDP 特化チェック", "ファイルサイズ",
            "warn",
            f"ファイルサイズが大きめです: {mb:.1f} MB。"
            "読者のダウンロード負荷が高くなる可能性があります（KDP の実用上限: 500MB 程度）。",
            detail=f"{mb:.1f} MB"
        )

    return _make_check(
        "file_size_warning", "KDP 特化チェック", "ファイルサイズ",
        "pass",
        f"ファイルサイズは問題ありません: {mb:.1f} MB",
        detail=f"{mb:.1f} MB"
    )


def _check_image_count(
    zf: zipfile.ZipFile,
    opf_root: etree._Element,
    opf_path: str,
) -> tuple[dict, int]:
    """
    image_count: 画像枚数を集計する（情報提供のみ、status=pass 固定）。
    戻り値: (チェック結果, 画像枚数)
    """
    opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

    manifest = opf_root.find(f"{{{OPF_NS}}}manifest")
    if manifest is None:
        manifest = opf_root.find("{*}manifest")
    if manifest is None:
        manifest = opf_root.find("manifest")

    count = 0
    if manifest is not None:
        items = manifest.findall(f"{{{OPF_NS}}}item")
        if not items:
            items = manifest.findall("{*}item")
        if not items:
            items = manifest.findall("item")

        zip_names = set(zf.namelist())
        for item in items:
            media_type = (item.get("media-type") or "").lower()
            href = item.get("href", "")
            if media_type in IMAGE_MIMES:
                full_path = opf_dir + href if not href.startswith("/") else href.lstrip("/")
                if full_path in zip_names:
                    count += 1

    return (
        _make_check(
            "image_count", "KDP 特化チェック", "画像枚数",
            "pass", f"画像ファイルが {count} 枚含まれています",
            detail=f"{count} 枚"
        ),
        count
    )


def _check_text_estimate(
    zf: zipfile.ZipFile,
    opf_root: etree._Element,
    opf_path: str,
) -> tuple[dict, int]:
    """
    text_estimate: XHTML からテキストを抽出して文字数を概算する（情報提供のみ）。
    戻り値: (チェック結果, 推定文字数)
    """
    opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

    manifest = opf_root.find(f"{{{OPF_NS}}}manifest")
    if manifest is None:
        manifest = opf_root.find("{*}manifest")
    if manifest is None:
        manifest = opf_root.find("manifest")

    total_chars = 0

    if manifest is not None:
        items = manifest.findall(f"{{{OPF_NS}}}item")
        if not items:
            items = manifest.findall("{*}item")
        if not items:
            items = manifest.findall("item")

        zip_names = set(zf.namelist())
        for item in items:
            media_type = (item.get("media-type") or "").lower()
            href = item.get("href", "")
            if media_type not in ("application/xhtml+xml", "text/html"):
                continue

            full_path = opf_dir + href if not href.startswith("/") else href.lstrip("/")
            if full_path not in zip_names:
                continue

            try:
                xhtml_bytes = zf.read(full_path)
                # lxml で解析してテキスト抽出
                root = etree.fromstring(xhtml_bytes)
                # 全テキストノードを結合
                text_content = " ".join(root.itertext())
                # 空白を除いた文字数
                total_chars += len(re.sub(r"\s+", "", text_content))
            except Exception:
                pass  # パースエラーはスキップ

    return (
        _make_check(
            "text_estimate", "KDP 特化チェック", "文字数概算",
            "pass",
            f"XHTML からの概算文字数（空白除く）: {total_chars:,} 文字",
            detail=f"約 {total_chars:,} 文字"
        ),
        total_chars
    )


# ------------------------------------------------------------------ #
# メタデータ収集
# ------------------------------------------------------------------ #

def _collect_metadata(
    file_bytes: bytes,
    opf_root: etree._Element,
    opf_path: str,
    is_fixed_layout: bool,
    image_count: int,
    font_count: int,
    text_chars: int,
) -> dict:
    """バリデーション結果のメタデータ辞書を構築する。"""
    total_size = len(file_bytes)

    def _get_dc(tag: str) -> str | None:
        elems = opf_root.findall(f".//{{{DC_NS}}}{tag}")
        if not elems:
            elems = opf_root.findall(f".//{tag}")
        if elems and elems[0].text:
            return elems[0].text.strip() or None
        return None

    # OPF の spine からページ数を数える
    spine = opf_root.find(f"{{{OPF_NS}}}spine")
    if spine is None:
        spine = opf_root.find("{*}spine")
    if spine is None:
        spine = opf_root.find("spine")

    page_count = 0
    if spine is not None:
        itemrefs = spine.findall(f"{{{OPF_NS}}}itemref")
        if not itemrefs:
            itemrefs = spine.findall("{*}itemref")
        if not itemrefs:
            itemrefs = spine.findall("itemref")
        page_count = len(itemrefs)

    return {
        "title": _get_dc("title"),
        "creator": _get_dc("creator"),
        "language": _get_dc("language"),
        "identifier": _get_dc("identifier"),
        "is_fixed_layout": is_fixed_layout,
        "page_count": page_count,
        "image_count": image_count,
        "font_count": font_count,
        "total_size_bytes": total_size,
        "text_chars_estimate": text_chars,
    }


# ------------------------------------------------------------------ #
# メイン公開関数
# ------------------------------------------------------------------ #

def validate_epub(file_bytes: bytes) -> dict:
    """
    EPUB ファイルをバリデーションして結果を返す。

    Args:
        file_bytes: アップロードされた EPUB ファイルのバイト列

    Returns:
        dict: {
            "summary": {
                "total": int,
                "pass": int,
                "warn": int,
                "fail": int,
                "score": float  # 0-100
            },
            "file_size_mb": float,
            "metadata": {
                "title": str | None,
                "creator": str | None,
                "language": str | None,
                "identifier": str | None,
                "is_fixed_layout": bool,
                "page_count": int,
                "image_count": int,
                "font_count": int,
                "total_size_bytes": int,
                "text_chars_estimate": int,
            },
            "checks": [
                {
                    "id": str,
                    "category": str,
                    "label": str,
                    "status": "pass" | "warn" | "fail",
                    "message": str,
                    "detail": str | None,
                }
            ],
            "errors": [str, ...]
        }
    """
    checks: list[dict] = []
    errors: list[str] = []
    file_size_mb = len(file_bytes) / 1024 / 1024

    # ── セキュリティチェック（ZIP 開封前） ──────────────────────────
    security_errors = _security_check_bytes(file_bytes)
    if security_errors:
        errors.extend(security_errors)
        # セキュリティ違反は全チェックをスキップ
        all_check_ids = [
            ("zip_structure", "基本チェック", "ZIP 構造"),
            ("mimetype", "基本チェック", "mimetype ファイル"),
            ("container_xml", "基本チェック", "container.xml"),
            ("opf_valid", "基本チェック", "OPF 構造"),
            ("metadata_title", "基本チェック", "dc:title"),
            ("metadata_creator", "基本チェック", "dc:creator"),
            ("metadata_language", "基本チェック", "dc:language"),
            ("metadata_identifier", "基本チェック", "dc:identifier"),
            ("manifest_files", "基本チェック", "マニフェスト参照切れ"),
            ("nav_ncx", "基本チェック", "NAV / NCX"),
            ("cover_image_exists", "KDP 特化チェック", "表紙画像"),
            ("cover_image_size", "KDP 特化チェック", "表紙サイズ"),
            ("fixed_layout", "KDP 特化チェック", "固定レイアウト判定"),
            ("font_embedded", "KDP 特化チェック", "フォント埋め込み"),
            ("file_size_warning", "KDP 特化チェック", "ファイルサイズ"),
            ("image_count", "KDP 特化チェック", "画像枚数"),
            ("text_estimate", "KDP 特化チェック", "文字数概算"),
        ]
        for id_, cat, label in all_check_ids:
            checks.append(_skipped_check(id_, cat, label))
        return _build_result(checks, errors, file_size_mb, {})

    # ── Level 1: 基本チェック ─────────────────────────────────────

    # 1. ZIP 構造
    zip_check = _check_zip_structure(file_bytes)
    checks.append(zip_check)

    if zip_check["status"] == "fail":
        # ZIP が開けない場合は後続チェック不可
        skip_ids = [
            ("mimetype", "基本チェック", "mimetype ファイル"),
            ("container_xml", "基本チェック", "container.xml"),
            ("opf_valid", "基本チェック", "OPF 構造"),
            ("metadata_title", "基本チェック", "dc:title"),
            ("metadata_creator", "基本チェック", "dc:creator"),
            ("metadata_language", "基本チェック", "dc:language"),
            ("metadata_identifier", "基本チェック", "dc:identifier"),
            ("manifest_files", "基本チェック", "マニフェスト参照切れ"),
            ("nav_ncx", "基本チェック", "NAV / NCX"),
            ("cover_image_exists", "KDP 特化チェック", "表紙画像"),
            ("cover_image_size", "KDP 特化チェック", "表紙サイズ"),
            ("fixed_layout", "KDP 特化チェック", "固定レイアウト判定"),
            ("font_embedded", "KDP 特化チェック", "フォント埋め込み"),
            ("file_size_warning", "KDP 特化チェック", "ファイルサイズ"),
            ("image_count", "KDP 特化チェック", "画像枚数"),
            ("text_estimate", "KDP 特化チェック", "文字数概算"),
        ]
        for id_, cat, label in skip_ids:
            checks.append(_skipped_check(id_, cat, label))
        errors.append("ZIP 構造チェックが失敗したため、後続チェックをスキップしました。")
        return _build_result(checks, errors, file_size_mb, {})

    # ZIP を開いて後続チェックへ
    try:
        with zipfile.ZipFile(BytesIO(file_bytes), "r") as zf:

            # 2. mimetype
            checks.append(_check_mimetype(zf))

            # 3. container.xml
            container_check, opf_path = _check_container_xml(zf)
            checks.append(container_check)

            if opf_path is None:
                # OPF パスが取得できなければ後続スキップ
                skip_ids = [
                    ("opf_valid", "基本チェック", "OPF 構造"),
                    ("metadata_title", "基本チェック", "dc:title"),
                    ("metadata_creator", "基本チェック", "dc:creator"),
                    ("metadata_language", "基本チェック", "dc:language"),
                    ("metadata_identifier", "基本チェック", "dc:identifier"),
                    ("manifest_files", "基本チェック", "マニフェスト参照切れ"),
                    ("nav_ncx", "基本チェック", "NAV / NCX"),
                    ("cover_image_exists", "KDP 特化チェック", "表紙画像"),
                    ("cover_image_size", "KDP 特化チェック", "表紙サイズ"),
                    ("fixed_layout", "KDP 特化チェック", "固定レイアウト判定"),
                    ("font_embedded", "KDP 特化チェック", "フォント埋め込み"),
                    ("file_size_warning", "KDP 特化チェック", "ファイルサイズ"),
                    ("image_count", "KDP 特化チェック", "画像枚数"),
                    ("text_estimate", "KDP 特化チェック", "文字数概算"),
                ]
                for id_, cat, label in skip_ids:
                    checks.append(_skipped_check(id_, cat, label))
                errors.append("container.xml チェックが失敗したため、後続チェックをスキップしました。")
                return _build_result(checks, errors, file_size_mb, {})

            # 4. OPF valid
            opf_check, opf_root = _check_opf_valid(zf, opf_path)
            checks.append(opf_check)

            if opf_root is None:
                skip_ids = [
                    ("metadata_title", "基本チェック", "dc:title"),
                    ("metadata_creator", "基本チェック", "dc:creator"),
                    ("metadata_language", "基本チェック", "dc:language"),
                    ("metadata_identifier", "基本チェック", "dc:identifier"),
                    ("manifest_files", "基本チェック", "マニフェスト参照切れ"),
                    ("nav_ncx", "基本チェック", "NAV / NCX"),
                    ("cover_image_exists", "KDP 特化チェック", "表紙画像"),
                    ("cover_image_size", "KDP 特化チェック", "表紙サイズ"),
                    ("fixed_layout", "KDP 特化チェック", "固定レイアウト判定"),
                    ("font_embedded", "KDP 特化チェック", "フォント埋め込み"),
                    ("file_size_warning", "KDP 特化チェック", "ファイルサイズ"),
                    ("image_count", "KDP 特化チェック", "画像枚数"),
                    ("text_estimate", "KDP 特化チェック", "文字数概算"),
                ]
                for id_, cat, label in skip_ids:
                    checks.append(_skipped_check(id_, cat, label))
                errors.append("OPF チェックが失敗したため、後続チェックをスキップしました。")
                return _build_result(checks, errors, file_size_mb, {})

            # 5-8. メタデータ
            checks.append(_check_metadata_field(opf_root, "metadata_title", "title", "dc:title"))
            checks.append(_check_metadata_field(opf_root, "metadata_creator", "creator", "dc:creator", required=False))
            checks.append(_check_metadata_field(opf_root, "metadata_language", "language", "dc:language"))
            checks.append(_check_metadata_field(opf_root, "metadata_identifier", "identifier", "dc:identifier"))

            # 9. manifest 参照切れ
            checks.append(_check_manifest_files(zf, opf_root, opf_path))

            # 10. NAV / NCX
            checks.append(_check_nav_ncx(zf, opf_root, opf_path))

            # ── Level 2: KDP 特化チェック ────────────────────────────

            # 11. 表紙画像存在
            cover_exists_check, cover_path = _check_cover_image_exists(zf, opf_root, opf_path)
            checks.append(cover_exists_check)

            # 12. 表紙画像サイズ
            if cover_path is not None:
                checks.append(_check_cover_image_size(zf, cover_path))
            else:
                checks.append(_make_check(
                    "cover_image_size", "KDP 特化チェック", "表紙サイズ",
                    "fail",
                    "表紙画像が存在しないためサイズチェックをスキップしました"
                ))

            # 13. 固定レイアウト判定
            fixed_check, is_fixed = _check_fixed_layout(opf_root)
            checks.append(fixed_check)

            # 14. フォント埋め込み
            font_check = _check_font_embedded(zf, opf_root, opf_path)
            checks.append(font_check)
            font_count = 0
            if font_check["status"] == "pass":
                # detail から件数を取得
                detail = font_check.get("detail") or ""
                m = re.search(r"(\d+)\s*件", font_check.get("message", ""))
                if m:
                    font_count = int(m.group(1))

            # 15. ファイルサイズ警告
            checks.append(_check_file_size_warning(len(file_bytes)))

            # 16. 画像枚数（情報提供）
            image_count_check, image_count = _check_image_count(zf, opf_root, opf_path)
            checks.append(image_count_check)

            # 17. 文字数概算（情報提供）
            text_check, text_chars = _check_text_estimate(zf, opf_root, opf_path)
            checks.append(text_check)

            # メタデータ収集
            metadata = _collect_metadata(
                file_bytes, opf_root, opf_path,
                is_fixed, image_count, font_count, text_chars
            )

    except Exception as e:
        errors.append(f"バリデーション中に予期しないエラーが発生しました: {e}")
        # 未実行チェックを fail で埋める
        executed_ids = {c["id"] for c in checks}
        all_ids = [
            ("zip_structure", "基本チェック", "ZIP 構造"),
            ("mimetype", "基本チェック", "mimetype ファイル"),
            ("container_xml", "基本チェック", "container.xml"),
            ("opf_valid", "基本チェック", "OPF 構造"),
            ("metadata_title", "基本チェック", "dc:title"),
            ("metadata_creator", "基本チェック", "dc:creator"),
            ("metadata_language", "基本チェック", "dc:language"),
            ("metadata_identifier", "基本チェック", "dc:identifier"),
            ("manifest_files", "基本チェック", "マニフェスト参照切れ"),
            ("nav_ncx", "基本チェック", "NAV / NCX"),
            ("cover_image_exists", "KDP 特化チェック", "表紙画像"),
            ("cover_image_size", "KDP 特化チェック", "表紙サイズ"),
            ("fixed_layout", "KDP 特化チェック", "固定レイアウト判定"),
            ("font_embedded", "KDP 特化チェック", "フォント埋め込み"),
            ("file_size_warning", "KDP 特化チェック", "ファイルサイズ"),
            ("image_count", "KDP 特化チェック", "画像枚数"),
            ("text_estimate", "KDP 特化チェック", "文字数概算"),
        ]
        for id_, cat, label in all_ids:
            if id_ not in executed_ids:
                checks.append(_skipped_check(id_, cat, label))
        return _build_result(checks, errors, file_size_mb, {})

    return _build_result(checks, errors, file_size_mb, metadata)


def _build_result(
    checks: list[dict],
    errors: list[str],
    file_size_mb: float,
    metadata: dict,
) -> dict:
    """チェック結果を集計して最終 dict を構築する。"""
    total = len(checks)
    pass_count = sum(1 for c in checks if c["status"] == "pass")
    warn_count = sum(1 for c in checks if c["status"] == "warn")
    fail_count = sum(1 for c in checks if c["status"] == "fail")

    # スコア: pass=1点、warn=0.5点、fail=0点 で換算
    raw_score = (pass_count + warn_count * 0.5) / total * 100 if total > 0 else 0.0
    score = round(raw_score, 1)

    return {
        "summary": {
            "total": total,
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
            "score": score,
        },
        "file_size_mb": round(file_size_mb, 2),
        "metadata": metadata,
        "checks": checks,
        "errors": errors,
    }
