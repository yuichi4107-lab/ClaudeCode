# 絵本2冊『すばるのちいさなて』『とうりがうまれたよるに』実装計画書

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 妹さんへのお祝いとして、すばる（兄5歳）・とうり（弟・新生児）を主役にした絵本2冊を、水彩風挿絵で制作し、KDP（Amazon Kindle）で電子書籍出版する。

**Architecture:** OpenAI gpt-image-2 で水彩風挿絵を生成（共通キャラクター設定で2冊のスタイル統一）→ 固定レイアウトEPUB3に組み立て → KDPメタデータ生成 → KDPに手動アップロード。プロジェクトはCLAUDE.mdの品質ループ（要件定義→実行→品質チェック85点以上）に従う。

**Tech Stack:**
- 画像生成: OpenAI gpt-image-2（`openai-image-gen` スキル経由）
- EPUB組み立て: Python + `ebooklib`（固定レイアウトEPUB3）
- KDPメタデータ: `kdp-cover-and-metadata` スキル
- 品質チェック: `quality-checker` エージェント

**仕様書:** [docs/superpowers/specs/2026-05-18-ehon-subaru-touri-design.md](../specs/2026-05-18-ehon-subaru-touri-design.md)

---

## ファイル構造

```
projects/ehon-subaru-touri/
├── shared/
│   ├── character-sheet.md       # キャラクター設定（共通）
│   ├── style-guide.md           # 水彩風スタイルガイド
│   └── prompt-template.md       # gpt-image-2用プロンプトテンプレート
├── 01-subaru-no-chiisana-te/
│   ├── manuscript.md            # 全12見開き本文
│   ├── prompts/
│   │   ├── spread_01.txt ~ spread_12.txt
│   │   └── cover.txt
│   ├── images/                  # gpt-image-2出力（PNG 1024x1536）
│   │   ├── spread_01.png ~ spread_12.png
│   │   └── cover.png
│   ├── epub/
│   │   ├── build_epub.py
│   │   └── subaru.epub
│   └── kdp/
│       ├── 書籍情報.md
│       ├── ジャンル・キーワード.md
│       └── 書籍紹介文_HTML.html
└── 02-touri-ga-umareta-yoru-ni/
    └── （同構造）
```

---

# Phase 0: 共通準備

## Task 0.1: プロジェクトフォルダ構造の作成

**Files:**
- Create: `projects/ehon-subaru-touri/` 配下の全ディレクトリ

- [ ] **Step 1: ディレクトリ作成**

```powershell
$base = "g:\マイドライブ\YNFactory-cc\projects\ehon-subaru-touri"
$dirs = @(
  "$base\shared",
  "$base\01-subaru-no-chiisana-te\prompts",
  "$base\01-subaru-no-chiisana-te\images",
  "$base\01-subaru-no-chiisana-te\epub",
  "$base\01-subaru-no-chiisana-te\kdp",
  "$base\02-touri-ga-umareta-yoru-ni\prompts",
  "$base\02-touri-ga-umareta-yoru-ni\images",
  "$base\02-touri-ga-umareta-yoru-ni\epub",
  "$base\02-touri-ga-umareta-yoru-ni\kdp"
)
$dirs | ForEach-Object { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
```

- [ ] **Step 2: 確認**

Run: `Get-ChildItem $base -Recurse -Directory | Select-Object FullName`
Expected: 9つのディレクトリが表示される

- [ ] **Step 3: コミット**

```powershell
git add projects/ehon-subaru-touri/.gitkeep
git commit -m "chore(ehon): プロジェクトフォルダ構造を作成"
```
（各ディレクトリに `.gitkeep` を置いてコミット）

---

## Task 0.2: キャラクター設定書の作成

**Files:**
- Create: `projects/ehon-subaru-touri/shared/character-sheet.md`

**目的:** 2冊で登場人物の見た目を完全に統一するための設定書（gpt-image-2のプロンプトに毎回含める）

- [ ] **Step 1: character-sheet.md を書く**

内容:
```markdown
# キャラクター設定書

## すばる（兄・5歳）
- 5-year-old Japanese boy, age 5
- short soft black hair with bangs
- round face, large bright dark eyes
- small build, healthy cheeks
- casual outfit: pastel yellow or sky-blue t-shirt and shorts
- warm gentle expression, slightly shy smile

## とうり（弟・新生児）
- newborn baby boy, Japanese
- very small, soft pink skin
- a few wisps of black hair
- tiny closed or sleepy eyes
- swaddled in soft white blanket with small star pattern
- tiny hands like maple leaves

## ママ
- young Japanese mother, late 20s
- long dark brown hair tied loosely
- soft warm smile, gentle eyes
- simple beige or pale-pink loose blouse

## 雰囲気
- すべてのキャラクターは「やさしさ」「あたたかさ」「安心感」を伝える
- 表情はやわらかく、目線はやさしい
```

- [ ] **Step 2: コミット**

```powershell
git add projects/ehon-subaru-touri/shared/character-sheet.md
git commit -m "docs(ehon): キャラクター設定書を追加"
```

---

## Task 0.3: 水彩風スタイルガイドの作成

**Files:**
- Create: `projects/ehon-subaru-touri/shared/style-guide.md`

- [ ] **Step 1: style-guide.md を書く**

```markdown
# 水彩風スタイルガイド

## 共通スタイル指示（全画像に必須）
- soft watercolor illustration, traditional picture book style
- gentle washes of color with visible paper texture
- delicate ink line work, minimal outline
- pastel palette with warm undertones
- soft natural lighting, dreamlike atmosphere
- no harsh shadows, no digital sharpness
- composition leaves room for text (lower 1/3 of frame should be less busy)

## 絵本①『すばるのちいさなて』専用
- 主色相: パステルイエロー、ペールピンク、ライトブルー、クリーム
- 全体的に明るく、昼の場面が多い
- 夜のシーン（5, 12）は深い藍色＋星の温かい光

## 絵本②『とうりがうまれたよるに』専用
- 主色相: ディープブルー、紫、星空のネイビー、月の銀色
- 夜の場面が中心、神秘的で静謐
- 各ページに「あたたかい光源（月・星・窓・街灯）」を1つ配置

## 統一モチーフ
- 「ふたつの星」を、可能な見開きにそっと配置（背景・装飾として）
- 星の色はクリーム〜淡いゴールド

## 解像度・形式
- 1024×1536（縦長、KDP電子書籍に最適）
- PNG形式
```

- [ ] **Step 2: コミット**

```powershell
git add projects/ehon-subaru-touri/shared/style-guide.md
git commit -m "docs(ehon): 水彩風スタイルガイドを追加"
```

---

## Task 0.4: プロンプトテンプレートの作成

**Files:**
- Create: `projects/ehon-subaru-touri/shared/prompt-template.md`

- [ ] **Step 1: プロンプトテンプレート作成**

```markdown
# gpt-image-2 プロンプトテンプレート

## 構造（必ずこの順番）
1. 【スタイル指示】(style-guide.md の「共通スタイル指示」)
2. 【絵本固有スタイル】(該当絵本の専用指示)
3. 【シーン記述】(その見開きの具体シーン)
4. 【キャラクター指示】(character-sheet.md の登場人物)
5. 【構図】(縦長1024x1536、テキスト配置の余白)

## 共通suffix（全プロンプト末尾に付ける）
"soft watercolor picture book illustration, gentle, warm, no text in image, vertical 2:3 composition, leave bottom third less busy for text overlay"

## サンプル（絵本①見開き1）
"A 5-year-old Japanese boy named Subaru standing in a sunny room, spreading both small hands wide with a gentle smile. Short soft black hair, large bright eyes, pastel yellow t-shirt. Soft watercolor illustration with paper texture, pastel palette, warm sunlight from window, two tiny stars subtly painted in the background pattern. soft watercolor picture book illustration, gentle, warm, no text in image, vertical 2:3 composition, leave bottom third less busy for text overlay."
```

- [ ] **Step 2: コミット**

```powershell
git add projects/ehon-subaru-touri/shared/prompt-template.md
git commit -m "docs(ehon): プロンプトテンプレートを追加"
```

---

## Task 0.5: スタイルテスト（1見開き試作 → ユーザー承認）

**目的:** 本番生成前に水彩風スタイルが意図通りか確認。

- [ ] **Step 1: 絵本①見開き1のプロンプトを `01-subaru-no-chiisana-te/prompts/spread_01.txt` に保存**

内容（Task 0.4のサンプルと同じ）

- [ ] **Step 2: `openai-image-gen` スキルで画像生成**

呼び出し: openai-image-gen スキル使用
- 入力プロンプト: spread_01.txt の内容
- サイズ: 1024x1536
- 画質: high
- 出力先: `01-subaru-no-chiisana-te/images/spread_01.png`

- [ ] **Step 3: ユーザーに見せて承認を得る**

ユーザーに画像を表示し、以下を確認:
- 水彩風になっているか
- すばるの見た目が設定通りか
- テキスト用の余白が下1/3にあるか
- 「ふたつの星」がさりげなく入っているか

承認NGの場合:
- プロンプトを修正して再生成（最大3回）
- それでもダメならスタイル選択に戻る

- [ ] **Step 4: 承認されたらコミット**

```powershell
git add projects/ehon-subaru-touri/01-subaru-no-chiisana-te/prompts/spread_01.txt projects/ehon-subaru-touri/01-subaru-no-chiisana-te/images/spread_01.png
git commit -m "feat(ehon-01): スタイルテスト見開き1を承認"
```

---

# Phase 1: 絵本①『すばるのちいさなて』

## Task 1.1: 原稿ファイル作成

**Files:**
- Create: `projects/ehon-subaru-touri/01-subaru-no-chiisana-te/manuscript.md`

- [ ] **Step 1: 仕様書から本文をコピーして manuscript.md を作成**

仕様書 `docs/superpowers/specs/2026-05-18-ehon-subaru-touri-design.md` の「📕 絵本①」テーブルから本文12件を抜粋し、以下の形式で保存:

```markdown
# 『すばるのちいさなて』本文

## 見開き1
ぼくのなまえは すばる。
ちいさな てが ふたつ ある。

## 見開き2
この てで、iPadを もつ。
どうがを みるのが だいすき。

（...見開き12まで全て...）
```

- [ ] **Step 2: コミット**

```powershell
git add projects/ehon-subaru-touri/01-subaru-no-chiisana-te/manuscript.md
git commit -m "feat(ehon-01): 原稿ファイル作成"
```

---

## Task 1.2: 見開き2〜6の挿絵生成

**Files:**
- Create: `01-subaru-no-chiisana-te/prompts/spread_02.txt ~ spread_06.txt`
- Create: `01-subaru-no-chiisana-te/images/spread_02.png ~ spread_06.png`

- [ ] **Step 1: 各見開きのプロンプトを作成**

仕様書の絵柄イメージとスタイルガイドを組み合わせて、5枚分のプロンプトを spread_02.txt 〜 spread_06.txt に保存。

例（spread_02.txt）:
```
A 5-year-old Japanese boy named Subaru sitting on a soft sofa, holding an iPad with both hands, eyes glued to the screen with a happy expression. Cozy living room with watercolor texture, pastel palette, warm afternoon light through window, two tiny stars subtly painted in the wallpaper pattern. soft watercolor picture book illustration, gentle, warm, no text in image, vertical 2:3 composition, leave bottom third less busy for text overlay.
```

例（spread_05.txt 夜のシーン）:
```
A 5-year-old Japanese boy named Subaru gently pressing his ear against his pregnant mother's belly. Mother sitting with a soft warm smile, long dark brown hair, beige loose blouse. Beside the window, deep navy night sky with one bright star twinkling. Soft watercolor with paper texture, warm indoor lamp light contrasting with cool night. soft watercolor picture book illustration, gentle, warm, no text in image, vertical 2:3 composition, leave bottom third less busy for text overlay.
```

各見開きのシーンは仕様書の「絵のイメージ」列を必ず参照。

- [ ] **Step 2: 5枚を順次生成**

`openai-image-gen` スキルで5枚生成（サイズ 1024x1536、画質 high）

- [ ] **Step 3: quality-checker でチェック**

`quality-checker` エージェントを起動。チェック項目:
- スタイル統一（水彩風で揃っているか）
- キャラクター一貫性（すばる、ママの見た目が見開き1と整合しているか）
- 余白（下1/3にテキスト用の空間があるか）
- 「ふたつの星」モチーフ（さりげなく入っているか）
- 雰囲気（仕様書の絵柄イメージと一致しているか）

85点未満なら問題のある画像を特定 → プロンプト修正 → 再生成（最大5回）

- [ ] **Step 4: コミット**

```powershell
git add projects/ehon-subaru-touri/01-subaru-no-chiisana-te/prompts/spread_0[2-6].txt projects/ehon-subaru-touri/01-subaru-no-chiisana-te/images/spread_0[2-6].png
git commit -m "feat(ehon-01): 見開き2〜6の挿絵を生成"
```

---

## Task 1.3: 見開き7〜12の挿絵生成

**Files:**
- Create: `01-subaru-no-chiisana-te/prompts/spread_07.txt ~ spread_12.txt`
- Create: `01-subaru-no-chiisana-te/images/spread_07.png ~ spread_12.png`

- [ ] **Step 1: 6枚分のプロンプト作成**

特に注意:
- spread_07: とうりの小さな手とすばるの手の対比（手のアップ）
- spread_10: 想像シーン → やわらかい光彩、夢のような表現
- spread_12: 二人の手のクローズアップ＋夜空に2つの星（最重要ページ。星モチーフ強調）

spread_12 例:
```
Extreme close-up of two small hands holding each other: a 5-year-old boy's hand and a tiny newborn baby's hand intertwined fingers. Above and behind, a dreamy night sky with two bright stars side by side, warm cream glow. Soft watercolor with paper texture, gentle pink and cream tones on hands, deep blue night above. soft watercolor picture book illustration, gentle, warm, no text in image, vertical 2:3 composition, leave bottom third less busy for text overlay.
```

- [ ] **Step 2: 6枚を順次生成**

`openai-image-gen` スキルで生成。

- [ ] **Step 3: quality-checker でチェック**

Task 1.2と同じ基準。加えて:
- 物語の終盤として感情的な高まりがあるか
- 見開き12が表紙にも使える完成度か

- [ ] **Step 4: コミット**

```powershell
git add projects/ehon-subaru-touri/01-subaru-no-chiisana-te/prompts/spread_[0-1][7-9].txt projects/ehon-subaru-touri/01-subaru-no-chiisana-te/prompts/spread_1[0-2].txt projects/ehon-subaru-touri/01-subaru-no-chiisana-te/images/spread_*.png
git commit -m "feat(ehon-01): 見開き7〜12の挿絵を生成"
```

---

## Task 1.4: 表紙画像生成

**Files:**
- Create: `01-subaru-no-chiisana-te/prompts/cover.txt`
- Create: `01-subaru-no-chiisana-te/images/cover.png`

**目的:** KDP電子書籍の表紙（1600x2560推奨、最低1000x1600）

- [ ] **Step 1: 表紙プロンプト作成**

```
Children's picture book cover illustration. A 5-year-old Japanese boy named Subaru in pastel yellow t-shirt, holding a tiny newborn baby's hand with both of his small hands, looking down with a tender warm smile. Behind them, soft watercolor night sky with two stars side by side glowing in warm cream gold. Title space at top (leave upper 1/3 mostly empty with sky/soft color), author name space at bottom. Soft watercolor picture book illustration, gentle warm pastel palette, paper texture, dreamlike, no text in image, vertical composition.
```

- [ ] **Step 2: `openai-image-gen` で生成（サイズ 1024x1536、画質 high）**

- [ ] **Step 3: ユーザー確認**

表紙は本の顔。必ずユーザーに見せて承認を得る。NGなら最大3回まで再生成。

- [ ] **Step 4: コミット**

```powershell
git add projects/ehon-subaru-touri/01-subaru-no-chiisana-te/prompts/cover.txt projects/ehon-subaru-touri/01-subaru-no-chiisana-te/images/cover.png
git commit -m "feat(ehon-01): 表紙画像を生成"
```

---

## Task 1.5: 固定レイアウトEPUB組み立て

**Files:**
- Create: `01-subaru-no-chiisana-te/epub/build_epub.py`
- Create: `01-subaru-no-chiisana-te/epub/subaru.epub`

**目的:** 12見開き＋表紙＋奥付の固定レイアウトEPUB3を生成。

- [ ] **Step 1: ebooklib のインストール確認**

```powershell
pip show ebooklib
```
未インストールなら: `pip install ebooklib`

- [ ] **Step 2: build_epub.py を作成**

```python
"""絵本①『すばるのちいさなて』固定レイアウトEPUB組み立てスクリプト"""
from pathlib import Path
from ebooklib import epub

BASE = Path(__file__).parent.parent
IMAGES_DIR = BASE / "images"
MANUSCRIPT = BASE / "manuscript.md"
OUT = Path(__file__).parent / "subaru.epub"

TITLE = "すばるのちいさなて"
AUTHOR = "Yuichi"  # 公開著者名（メモリ参照）
LANG = "ja"
PAGE_W, PAGE_H = 1024, 1536

def parse_manuscript() -> list[str]:
    """manuscript.md から12見開き分の本文を抽出"""
    text = MANUSCRIPT.read_text(encoding="utf-8")
    spreads = []
    for i in range(1, 13):
        marker = f"## 見開き{i}"
        start = text.find(marker)
        end = text.find(f"## 見開き{i+1}") if i < 12 else len(text)
        body = text[start + len(marker):end].strip()
        spreads.append(body)
    return spreads

def make_xhtml(idx: int, img_filename: str, body_text: str) -> str:
    """1見開き分の XHTML を生成（画像背景＋テキストオーバーレイ）"""
    safe = body_text.replace("\n", "<br/>")
    return f"""<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" lang="ja">
<head>
  <meta charset="utf-8"/>
  <title>見開き{idx}</title>
  <meta name="viewport" content="width={PAGE_W}, height={PAGE_H}"/>
  <style>
    body {{ margin: 0; padding: 0; width: {PAGE_W}px; height: {PAGE_H}px; position: relative; font-family: "Hiragino Maru Gothic ProN", "Yu Gothic", sans-serif; }}
    .bg {{ position: absolute; top: 0; left: 0; width: {PAGE_W}px; height: {PAGE_H}px; z-index: 0; }}
    .txt {{ position: absolute; bottom: 60px; left: 60px; right: 60px; z-index: 1; font-size: 38px; line-height: 1.6; color: #2c2c2c; text-shadow: 0 0 6px rgba(255,255,255,0.9); }}
  </style>
</head>
<body>
  <img class="bg" src="{img_filename}" alt=""/>
  <div class="txt">{safe}</div>
</body>
</html>
"""

def build():
    book = epub.EpubBook()
    book.set_identifier("ehon-subaru-2026")
    book.set_title(TITLE)
    book.set_language(LANG)
    book.add_author(AUTHOR)

    # 固定レイアウト指定
    book.add_metadata(None, "meta", "true", {"property": "rendition:layout", "name": "rendition:layout", "content": "pre-paginated"})
    book.add_metadata(None, "meta", "portrait", {"property": "rendition:orientation"})
    book.add_metadata(None, "meta", "auto", {"property": "rendition:spread"})

    # 表紙
    cover_bytes = (IMAGES_DIR / "cover.png").read_bytes()
    book.set_cover("cover.png", cover_bytes)

    chapters = []
    spreads = parse_manuscript()
    for i, body in enumerate(spreads, start=1):
        img_name = f"spread_{i:02d}.png"
        img_bytes = (IMAGES_DIR / img_name).read_bytes()
        img_item = epub.EpubImage(uid=f"img_{i:02d}", file_name=f"images/{img_name}", media_type="image/png", content=img_bytes)
        book.add_item(img_item)

        ch = epub.EpubHtml(title=f"見開き{i}", file_name=f"spread_{i:02d}.xhtml", lang=LANG)
        ch.content = make_xhtml(i, f"images/{img_name}", body)
        ch.properties = ["rendition:layout-pre-paginated", "rendition:orientation-portrait"]
        book.add_item(ch)
        chapters.append(ch)

    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["cover"] + chapters

    epub.write_epub(str(OUT), book)
    print(f"OK: {OUT}")

if __name__ == "__main__":
    build()
```

- [ ] **Step 3: スクリプト実行**

```powershell
python "g:\マイドライブ\YNFactory-cc\projects\ehon-subaru-touri\01-subaru-no-chiisana-te\epub\build_epub.py"
```
Expected: `OK: ...\subaru.epub`

- [ ] **Step 4: EPUB検証**

```powershell
# epubcheck がインストール済みの場合
java -jar epubcheck.jar "g:\...\subaru.epub"
```
未インストールなら: https://www.w3.org/publishing/epubcheck/ から取得、または KDP のプレビューで確認

- [ ] **Step 5: コミット**

```powershell
git add projects/ehon-subaru-touri/01-subaru-no-chiisana-te/epub/
git commit -m "feat(ehon-01): 固定レイアウトEPUBを組み立て"
```

---

## Task 1.6: KDPメタデータ作成

**Files:**
- Create: `01-subaru-no-chiisana-te/kdp/書籍情報.md`
- Create: `01-subaru-no-chiisana-te/kdp/ジャンル・キーワード.md`
- Create: `01-subaru-no-chiisana-te/kdp/書籍紹介文_HTML.html`

**目的:** `kdp-cover-and-metadata` スキルでKDPアップロード用の3点メタデータを生成。

- [ ] **Step 1: `kdp-cover-and-metadata` スキルを起動**

入力:
- 書名: 『すばるのちいさなて』
- 著者名: Yuichi（メモリ確定値）
- 内容: 仕様書の絵本①コンセプト＋本文（manuscript.md）
- ターゲット読者: 3〜6歳児とその家族
- 表紙画像: 既存の `images/cover.png`（再生成不要・Step 8をスキップ可能なら指示）

スキルが書籍情報.md / ジャンル・キーワード.md / 書籍紹介文_HTML.html を生成。

- [ ] **Step 2: 生成内容を確認・調整**

特に確認:
- 書籍紹介文に「兄弟愛」「新生児」「お祝い」のキーワードが含まれているか
- カテゴリは「絵本」「日本の絵本」「乳幼児向け」など適切か
- 著者名が「Yuichi」になっているか（「中田 雄一」表記NG・メモリ参照）

- [ ] **Step 3: ユーザー確認**

書籍紹介文をユーザーに見せて承認を得る。

- [ ] **Step 4: コミット**

```powershell
git add projects/ehon-subaru-touri/01-subaru-no-chiisana-te/kdp/
git commit -m "feat(ehon-01): KDPメタデータ作成"
```

---

## Task 1.7: 絵本①最終検証

**目的:** KDPアップロード前の総合検証。

- [ ] **Step 1: quality-checker で総合チェック**

入力: 絵本①のフォルダ全体
チェック項目:
- 12見開き全て揃っているか
- 画像のスタイル統一性
- キャラクター一貫性
- 表紙のクオリティ
- EPUBが正しく開けるか
- KDPメタデータが3点揃っているか
- 著者名が「Yuichi」で統一されているか

85点以上で合格。未満なら問題箇所を修正してこのタスクを再実行（最大5回）。

- [ ] **Step 2: EPUB をKindle Previewer等で開いて目視確認**

KDP公式: https://kdp.amazon.co.jp/ja_JP/help/topic/G202131170 から Kindle Previewer をダウンロードし、subaru.epub を開いて全ページを確認。

- [ ] **Step 3: 承認したらコミット**

```powershell
git commit --allow-empty -m "test(ehon-01): 最終検証パス"
```

---

# Phase 2: 絵本②『とうりがうまれたよるに』

## Task 2.1: 原稿ファイル作成

**Files:**
- Create: `02-touri-ga-umareta-yoru-ni/manuscript.md`

- [ ] **Step 1: 仕様書から本文をコピー**

仕様書の「📘 絵本②」テーブルから本文12件を抜粋し、Task 1.1と同じ形式で保存。

- [ ] **Step 2: コミット**

```powershell
git add projects/ehon-subaru-touri/02-touri-ga-umareta-yoru-ni/manuscript.md
git commit -m "feat(ehon-02): 原稿ファイル作成"
```

---

## Task 2.2: 見開き1〜6の挿絵生成

**Files:**
- Create: `02-touri-ga-umareta-yoru-ni/prompts/spread_01.txt ~ spread_06.txt`
- Create: `02-touri-ga-umareta-yoru-ni/images/spread_01.png ~ spread_06.png`

**重要:** 絵本②は夜のシーン中心。style-guide.md の「絵本②専用」セクションを必ず参照。

- [ ] **Step 1: 6見開きのプロンプト作成**

例（spread_01.txt）:
```
A quiet hospital room at night. Outside the window, a deep navy starry sky stretches silently. A small soft glow from a bedside lamp. Newborn baby Touri sleeps in a tiny white bassinet, swaddled in white blanket with subtle star pattern. Soft watercolor with paper texture, deep blue and gentle cream palette, dreamlike stillness. Two faint stars visible in the sky. soft watercolor picture book illustration, gentle, warm, no text in image, vertical 2:3 composition, leave bottom third less busy for text overlay.
```

例（spread_02.txt）:
```
A large full moon glowing softly above a window curtain that gently sways. Inside the room, a peacefully sleeping newborn in a soft white bassinet. The moon seems to whisper towards the baby. Soft watercolor, deep blue night, warm silver moonlight, paper texture. soft watercolor picture book illustration, gentle, warm, no text in image, vertical 2:3 composition, leave bottom third less busy for text overlay.
```

各見開きとも:
- 各ページに「あたたかい光源」を1つ配置
- 月・星・窓・街灯のどれか

- [ ] **Step 2: 6枚を順次生成**

`openai-image-gen` で生成。

- [ ] **Step 3: quality-checker でチェック**

Task 1.2と同じ基準。加えて:
- 夜の静謐さが伝わるか
- 「あたたかい光源」が各ページに必ずあるか

- [ ] **Step 4: コミット**

```powershell
git add projects/ehon-subaru-touri/02-touri-ga-umareta-yoru-ni/prompts/spread_0[1-6].txt projects/ehon-subaru-touri/02-touri-ga-umareta-yoru-ni/images/spread_0[1-6].png
git commit -m "feat(ehon-02): 見開き1〜6の挿絵を生成"
```

---

## Task 2.3: 見開き7〜12の挿絵生成

**Files:**
- Create: `02-touri-ga-umareta-yoru-ni/prompts/spread_07.txt ~ spread_12.txt`
- Create: `02-touri-ga-umareta-yoru-ni/images/spread_07.png ~ spread_12.png`

**最重要ページ:**
- spread_08: 「ふたつの星」を最大限に強調する中心ページ
- spread_11-12: すばる登場、感情のクライマックス

spread_08 プロンプト例:
```
A wide deep navy night sky with two bright stars side by side, warm cream gold glow, twinkling gently together. Soft watercolor brushwork with paper texture, dreamy clouds in background. The two stars symbolize two brothers (but no people in this image, only the sky). soft watercolor picture book illustration, gentle, warm, no text in image, vertical 2:3 composition, leave bottom third less busy for text overlay.
```

spread_12 プロンプト例:
```
Close-up: a 5-year-old Japanese boy Subaru's index finger gently held by a tiny newborn baby Touri's small hand. Soft warm indoor light, white blanket with tiny star pattern visible. The expression on Subaru is tender, the baby's mouth slightly curled into a faint smile. Soft watercolor with paper texture, warm cream and pink tones. soft watercolor picture book illustration, gentle, warm, no text in image, vertical 2:3 composition, leave bottom third less busy for text overlay.
```

- [ ] **Step 1: 6枚分のプロンプト作成**
- [ ] **Step 2: 6枚を順次生成**
- [ ] **Step 3: quality-checker でチェック**（Task 2.2と同じ基準）
- [ ] **Step 4: コミット**

```powershell
git add projects/ehon-subaru-touri/02-touri-ga-umareta-yoru-ni/prompts/spread_*.txt projects/ehon-subaru-touri/02-touri-ga-umareta-yoru-ni/images/spread_*.png
git commit -m "feat(ehon-02): 見開き7〜12の挿絵を生成"
```

---

## Task 2.4: 表紙画像生成

**Files:**
- Create: `02-touri-ga-umareta-yoru-ni/prompts/cover.txt`
- Create: `02-touri-ga-umareta-yoru-ni/images/cover.png`

**コンセプト:** 絵本①の表紙と対になるデザイン。①は明るい兄弟、②は静かな夜の祝福。

- [ ] **Step 1: 表紙プロンプト作成**

```
Children's picture book cover illustration. A peaceful starry deep navy night sky as background, with two bright stars side by side glowing warm cream gold (one slightly larger, one smaller, side by side). Below, a softly lit bassinet with a sleeping newborn baby swaddled in white blanket. Title space at top, author name space at bottom. Soft watercolor with paper texture, gentle warm light, dreamlike night atmosphere, no text in image, vertical composition.
```

- [ ] **Step 2: 生成**
- [ ] **Step 3: ユーザー確認**

①と並べて見せ、対になっているか確認。

- [ ] **Step 4: コミット**

```powershell
git add projects/ehon-subaru-touri/02-touri-ga-umareta-yoru-ni/prompts/cover.txt projects/ehon-subaru-touri/02-touri-ga-umareta-yoru-ni/images/cover.png
git commit -m "feat(ehon-02): 表紙画像を生成"
```

---

## Task 2.5: 固定レイアウトEPUB組み立て

**Files:**
- Create: `02-touri-ga-umareta-yoru-ni/epub/build_epub.py`
- Create: `02-touri-ga-umareta-yoru-ni/epub/touri.epub`

- [ ] **Step 1: Task 1.5 の build_epub.py をコピーして書名・出力ファイル名を変更**

変更点:
- `TITLE = "とうりがうまれたよるに"`
- `OUT = Path(__file__).parent / "touri.epub"`
- `book.set_identifier("ehon-touri-2026")`
- テキスト色: 夜の場面が多いので明るめに変更
  - CSS: `color: #f8f4e8; text-shadow: 0 0 8px rgba(0,0,30,0.85);`

- [ ] **Step 2: スクリプト実行**

```powershell
python "g:\マイドライブ\YNFactory-cc\projects\ehon-subaru-touri\02-touri-ga-umareta-yoru-ni\epub\build_epub.py"
```
Expected: `OK: ...\touri.epub`

- [ ] **Step 3: EPUB検証**（Task 1.5 Step 4と同じ）

- [ ] **Step 4: コミット**

```powershell
git add projects/ehon-subaru-touri/02-touri-ga-umareta-yoru-ni/epub/
git commit -m "feat(ehon-02): 固定レイアウトEPUBを組み立て"
```

---

## Task 2.6: KDPメタデータ作成

**Files:**
- Create: `02-touri-ga-umareta-yoru-ni/kdp/書籍情報.md`
- Create: `02-touri-ga-umareta-yoru-ni/kdp/ジャンル・キーワード.md`
- Create: `02-touri-ga-umareta-yoru-ni/kdp/書籍紹介文_HTML.html`

- [ ] **Step 1: `kdp-cover-and-metadata` スキル起動**

入力:
- 書名: 『とうりがうまれたよるに』
- 著者名: Yuichi
- 内容: 仕様書の絵本②コンセプト＋本文
- ターゲット読者: 0〜6歳児とその家族、新生児のお祝いギフト用

- [ ] **Step 2: 紹介文を「絵本①との対の作品」として位置付ける一文を追加**

例: 「兄『すばる』を主役にした『すばるのちいさなて』と対になる、弟『とうり』への祝福の絵本です。」

- [ ] **Step 3: ユーザー確認**

- [ ] **Step 4: コミット**

```powershell
git add projects/ehon-subaru-touri/02-touri-ga-umareta-yoru-ni/kdp/
git commit -m "feat(ehon-02): KDPメタデータ作成"
```

---

## Task 2.7: 絵本②最終検証

Task 1.7と同じ手順を絵本②に対して実施。

- [ ] **Step 1: quality-checker で総合チェック**
- [ ] **Step 2: Kindle Previewer で目視確認**
- [ ] **Step 3: コミット**

```powershell
git commit --allow-empty -m "test(ehon-02): 最終検証パス"
```

---

# Phase 3: KDP出版

## Task 3.1: 絵本①のKDPアップロード（ユーザー手動操作）

**目的:** 実際のアップロードはKDPブラウザUIでユーザーが実施。Claudeはガイドと確認を行う。

- [ ] **Step 1: アップロード手順をユーザーに提示**

1. https://kdp.amazon.co.jp/ にログイン
2. 「+ 電子書籍または有料漫画」をクリック
3. 「Kindle電子書籍の詳細」入力:
   - `kdp/書籍情報.md` の内容を転記
   - `kdp/ジャンル・キーワード.md` のカテゴリ・キーワードを設定
4. 「Kindle電子書籍のコンテンツ」:
   - 原稿: `epub/subaru.epub` をアップロード
   - 表紙: `images/cover.png` をアップロード（もしくはEPUBに含まれるカバーを使用）
   - DRM選択
5. 「Kindle電子書籍の価格設定」:
   - 価格設定（推奨: 99円〜250円、KDP セレクト有効化）
6. プレビューで全ページ確認
7. 「Kindle電子書籍を出版」をクリック

- [ ] **Step 2: ユーザー操作完了の報告を受ける**

- [ ] **Step 3: ASIN を記録**

publication-log.md を作成:
```markdown
# 出版記録

## 絵本①『すばるのちいさなて』
- ASIN: （ユーザー記入）
- 公開日: 2026-MM-DD
- URL: https://www.amazon.co.jp/dp/<ASIN>
```

- [ ] **Step 4: コミット**

```powershell
git add projects/ehon-subaru-touri/publication-log.md
git commit -m "chore(ehon-01): KDP出版完了・ASIN記録"
```

---

## Task 3.2: 絵本②のKDPアップロード

Task 3.1と同じ手順を絵本②に対して実施。

- [ ] **Step 1: アップロード手順実施**
- [ ] **Step 2: ASIN記録**
- [ ] **Step 3: コミット**

```powershell
git commit -m "chore(ehon-02): KDP出版完了・ASIN記録"
```

---

## Task 3.3: 妹さんへの贈呈

- [ ] **Step 1: 公開された2冊のAmazonリンクを妹さんに送付**

メッセージ例:
> 弟くんのご誕生おめでとう！ささやかなお祝いに、すばる君と弟くんのための絵本を2冊作りました。AmazonのKindleでいつでも読めるよ。すばる君と一緒に読んでね。
> ・『すばるのちいさなて』 https://www.amazon.co.jp/dp/...
> ・『とうりがうまれたよるに』 https://www.amazon.co.jp/dp/...

- [ ] **Step 2: ハンドオフ**

`handoff` スキルで HANDOFF.md・TODO・git commit を一括更新してプロジェクト完了。

---

# 未確定事項（実行中に確定）

1. **とうりの漢字** — Task 1.6 / 2.6（KDPメタデータ作成）までに妹さんに確認。著者プロフィールや謝辞に使う場合のみ必要。なくても出版可能。
2. **価格設定** — Task 3.1 で決定（推奨: 99円〜250円）
3. **KDP セレクト加入** — Task 3.1 で決定

---

# リスクと対応

| リスク | 対応 |
|---|---|
| gpt-image-2 でキャラクター一貫性が崩れる | character-sheet.md を毎プロンプトに全文含める／NGなら同プロンプトで再生成 |
| 水彩風スタイルがブレる | style-guide.md の suffix を毎プロンプト末尾に固定 |
| EPUB が KDP で弾かれる | Kindle Previewer で事前確認、必須メタデータを満たす |
| 文字オーバーレイが画像に被って読みにくい | プロンプトで「下1/3を空ける」を強調、CSS の text-shadow で可読性確保 |
| 著者名表記ミス | メモリ参照「公式著者名は Yuichi」、KDPメタデータでチェック |
