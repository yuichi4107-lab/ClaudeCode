## Step 7: 製本（EPUB化）

> `ebook-to-manga` SKILL.md の Step 7 から参照される詳細仕様ファイル。EPUB生成スクリプト全文を含む。Step 7 を実行する際は本ファイルを読み込むこと。

固定レイアウトEPUB3をPythonで直接構築する。
**Pandocでは固定レイアウトEPUBを生成できないため、`zipfile` モジュールを使用する。**

### EPUB構造

```
mimetype                          (非圧縮)
META-INF/
  └── container.xml
OEBPS/
  ├── content.opf                 (パッケージメタデータ)
  ├── nav.xhtml                   (ナビゲーション)
  ├── style.css                   (スタイルシート)
  ├── images/
  │   ├── cover.jpg
  │   ├── page_001.png
  │   ├── page_002.png
  │   └── ...
  └── text/
      ├── cover.xhtml
      ├── page_001.xhtml          (画像ページ or テキストページ)
      ├── page_002.xhtml
      └── ...
```

### テキストページの処理

CSVでテンプレが「テキストページ」のページは、画像ではなくHTMLテキストとしてEPUBに含める。
目次・あらすじ・コラム・著者紹介・奥付等がこれに該当する。テキストページ用CSSで読みやすくレンダリングする。

**改ページルール（必須）**: 各テキストページは表示行数が**最大20行**に収まるよう要素単位（h2/h3/p/subtitle）で折り返し行数を推定し、20行を超える場合は新しいXHTMLファイル（`page_NNN.xhtml`, `page_NNNb.xhtml`, `page_NNNc.xhtml` ...）に分割する。見出し（h2/h3）が末尾孤立しないよう、次の本文も同ページに入らない場合は見出しごと次ページへ送る orphan 回避を実装する。viewport 1024×1536 + 1.5倍フォントの条件では、p=42pxで1行63px、利用可能高さ約1444pxで20行≈1260pxとなり安全に収まる。

### CTA固定ページ（後付け・必須）

著者紹介ページの直後・奥付ページの直前に、全巻共通の固定CTA画像を spine に挿入する。

- **アセット**: 本スキルディレクトリの `assets/cta.png`（1024×1536 PNG、全巻共通固定）
- **spine ID**: `page_cta`
- **挿入位置**: `... → page_NNN（著者紹介） → page_cta → page_NNN+1（奥付） → ...`
- **xhtml 生成**: 通常の画像ページと同じ `<div class="page"><img src="../images/page_cta.png" alt="ページ CTA"/></div>`
- **manifest 登録**: `<item id="page_cta" .../>` と `<item id="page_cta-img" href="images/page_cta.png" .../>` の2エントリ

```python
# CTA固定ページの挿入（著者紹介の直後・奥付の直前）
# SKILL_DIR は本SKILL.mdが置かれているスキルディレクトリを指す（実行時に解決する。PC固有パスを直書きしない）
SKILL_DIR = os.path.dirname(os.path.abspath(SKILL_MD_PATH))
CTA_IMAGE = os.path.join(SKILL_DIR, "assets", "cta.png")

# spine 構築時に著者紹介→CTA→奥付の順で追加
# spine.append(("page_NNN_author", "text"))   # 著者紹介
spine.append(("page_cta", "image_cta"))       # CTA固定
# spine.append(("page_NNN_colophon", "text")) # 奥付

# manifest 登録
manifest_items.append('    <item id="page_cta" href="text/page_cta.xhtml" media-type="application/xhtml+xml"/>')
manifest_items.append('    <item id="page_cta-img" href="images/page_cta.png" media-type="image/png"/>')

# EPUB書き込み
with open(CTA_IMAGE, "rb") as f:
    cta_data = f.read()
epub.writestr("OEBPS/images/page_cta.png", cta_data, compress_type=zipfile.ZIP_DEFLATED)
epub.writestr("OEBPS/text/page_cta.xhtml", make_page_xhtml("../images/page_cta.png", "CTA"), compress_type=zipfile.ZIP_DEFLATED)
```

> **差し替えはアセットを更新するだけ**: CTAデザインを変更したい場合は本スキルディレクトリの `assets/cta.png` を新しい1024×1536 PNGで上書きする。次回以降のEPUBビルドで全巻に自動反映される。

### フォント埋め込み（必須）

**端末（特にKindle）にインストールされたCJKフォントは中国語字形にフォールバックすることがあるため、
日本語ゴシックフォント（Noto Sans JP）を必ずEPUB内に埋め込むこと。**

- フォント取得元: `https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/JP/NotoSansJP-Regular.otf`（Bold同様）
- ライセンス: SIL Open Font License（再配布可・商用利用可・KDP出版可）
- EPUB内パス: `OEBPS/fonts/NotoSansJP-{Regular,Bold}.otf`
- ZIP格納時は `ZIP_STORED`（既圧縮のため再圧縮しない）
- `style.css` の `@font-face` で参照、`font-family` の先頭に `"Noto Sans JP"` を指定
- `content.opf` の manifest に `media-type="application/vnd.ms-opentype"` で登録

> **注意**: 下記の「EPUB生成スクリプト」は画像ページ中心の基本形であり、CTA固定ページ挿入・フォント埋め込み・テキストページ改ページの各処理は上記仕様に従って組み込むこと。
>
> **要検証（既知の不整合）**: Step 6 は表紙を `cover.png` で保存する一方、本スクリプトの `COVER_PATH` は `cover.jpg` を前提としている。実行時は「KDP出版用」フォルダ内の実際の表紙ファイル拡張子を確認し、`COVER_PATH`・manifest の media-type（`image/png` / `image/jpeg`）・EPUB内パスを実ファイルに合わせて統一すること（2026-07-08 オーナー決定: 次回実行時に検証して修正する）。

### EPUB生成スクリプト

```bash
python << 'PYTHON_SCRIPT'
import zipfile
import os
import glob
import uuid
from datetime import datetime

BOOK_NAME = "{{book-name}}"
TITLE = "マンガでわかる {{元タイトル}}"
AUTHOR = "{{著者名}}"
OUTPUT_DIR = r"{{出力ディレクトリ}}"
PAGES_DIR = os.path.join(OUTPUT_DIR, "panels", "pages")
COVER_PATH = os.path.join(OUTPUT_DIR, "KDP出版用", "cover.jpg")
EPUB_PATH = os.path.join(OUTPUT_DIR, "KDP出版用", f"{BOOK_NAME}-manga.epub")

# ページ画像の収集（ソート済み）
# Step 5 は全画像を PNG (.png) で保存するため .png を対象とする
page_files = sorted(glob.glob(os.path.join(PAGES_DIR, "page_*.png")))
page_count = len(page_files)
book_id = str(uuid.uuid4())
modified = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

# --- mimetype ---
mimetype = "application/epub+zip"

# --- container.xml ---
container_xml = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

# --- style.css ---
style_css = """body { margin: 0; padding: 0; }
.page { width: 100%; height: 100%; }
.page img { width: 100%; height: 100%; object-fit: contain; }"""

# --- content.opf ---
manifest_items = [
    '    <item id="nav" href="text/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
    '    <item id="style" href="style.css" media-type="text/css"/>',
    '    <item id="cover-image" href="images/cover.jpg" media-type="image/jpeg" properties="cover-image"/>',
    '    <item id="cover" href="text/cover.xhtml" media-type="application/xhtml+xml"/>',
]
spine_items = ['    <itemref idref="cover"/>']

for i in range(1, page_count + 1):
    pid = f"page_{i:03d}"
    manifest_items.append(f'    <item id="{pid}" href="text/{pid}.xhtml" media-type="application/xhtml+xml"/>')
    manifest_items.append(f'    <item id="{pid}-img" href="images/{pid}.png" media-type="image/png"/>')
    spine_items.append(f'    <itemref idref="{pid}"/>')

content_opf = f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="BookId" prefix="rendition: http://www.idpf.org/vocab/rendition/#">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="BookId">{book_id}</dc:identifier>
    <dc:title>{TITLE}</dc:title>
    <dc:creator>{AUTHOR}</dc:creator>
    <dc:language>ja</dc:language>
    <meta property="dcterms:modified">{modified}</meta>
    <meta property="rendition:layout">pre-paginated</meta>
    <meta property="rendition:spread">landscape</meta>
    <meta name="cover" content="cover-image"/>
  </metadata>
  <manifest>
{chr(10).join(manifest_items)}
  </manifest>
  <spine page-progression-direction="ltr">
{chr(10).join(spine_items)}
  </spine>
</package>"""

# --- nav.xhtml ---
nav_xhtml = f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ja">
<head><title>{TITLE}</title></head>
<body>
<nav epub:type="toc">
  <ol>
    <li><a href="cover.xhtml">表紙</a></li>
    <li><a href="page_001.xhtml">本編</a></li>
  </ol>
</nav>
</body>
</html>"""

# --- ページXHTML生成関数 ---
def make_page_xhtml(img_path, alt_text):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" lang="ja">
<head>
  <meta name="viewport" content="width=1080, height=1920"/>
  <link rel="stylesheet" href="../style.css"/>
  <title>{alt_text}</title>
</head>
<body>
  <div class="page"><img src="{img_path}" alt="{alt_text}"/></div>
</body>
</html>"""

# --- EPUB書き出し ---
os.makedirs(os.path.dirname(EPUB_PATH), exist_ok=True)

with zipfile.ZipFile(EPUB_PATH, 'w') as epub:
    # mimetype は非圧縮で最初に追加
    epub.writestr("mimetype", mimetype, compress_type=zipfile.ZIP_STORED)
    epub.writestr("META-INF/container.xml", container_xml, compress_type=zipfile.ZIP_DEFLATED)
    epub.writestr("OEBPS/content.opf", content_opf, compress_type=zipfile.ZIP_DEFLATED)
    epub.writestr("OEBPS/text/nav.xhtml", nav_xhtml, compress_type=zipfile.ZIP_DEFLATED)
    epub.writestr("OEBPS/style.css", style_css, compress_type=zipfile.ZIP_DEFLATED)

    # 表紙
    epub.write(COVER_PATH, "OEBPS/images/cover.jpg", compress_type=zipfile.ZIP_DEFLATED)
    cover_xhtml = make_page_xhtml("../images/cover.jpg", "表紙")
    epub.writestr("OEBPS/text/cover.xhtml", cover_xhtml, compress_type=zipfile.ZIP_DEFLATED)

    # 各ページ（Step 5 が page_{NNN}.png（PNG）で保存するため .png で格納）
    for i, page_file in enumerate(page_files, 1):
        pid = f"page_{i:03d}"
        epub.write(page_file, f"OEBPS/images/{pid}.png", compress_type=zipfile.ZIP_DEFLATED)
        page_xhtml = make_page_xhtml(f"../images/{pid}.png", f"ページ {i}")
        epub.writestr(f"OEBPS/text/{pid}.xhtml", page_xhtml, compress_type=zipfile.ZIP_DEFLATED)

print(f"OK: {EPUB_PATH}")
print(f"Pages: {page_count}")
print(f"Size: {os.path.getsize(EPUB_PATH) / 1024 / 1024:.1f} MB")
PYTHON_SCRIPT
```

### EPUB仕様
- **固定レイアウト**: `rendition:layout: pre-paginated`
- **ページ方向**: `page-progression-direction: ltr`（左開き）
- **ビューポート**: `1080x1920`（9:16）
- **各ページ**: フルビューポート画像1枚

### Step 5 ハイブリッドQCとの下流互換性

Step 5 のハイブリッドQCループは `pages/page_{NNN}.png` を最終成果物として出力する。
本 EPUB 生成スクリプトは `glob("page_*.png")` でこのファイル群を収集するため、
Web生成でPASSしたページだけを追加改修なしで収集できる。

| Step 5 出力パターン | EPUB に含まれるファイル | 対応方法 |
|---|---|---|
| PASS ページ | `page_{NNN}.png`（コピー済み） | そのまま収集 |
| blocked ページ | なし | EPUB化へ進まない |
| 中間ファイル（`_iter_*`） | Step 5 がリネーム前に除去 | `glob` パターンに一致しないため自動除外 |

> **前提**: Step 5 の責務として、`blocked_pages` が空であることを確認してから本ステップを実行すること。

---

