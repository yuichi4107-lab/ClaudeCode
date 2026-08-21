# openai-image-gen スキル Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** OpenAI `gpt-image-1` を使う画像生成スキル `openai-image-gen` を新規作成し、NanoBanana2 と並行運用できる状態にする。

**Architecture:** 単一の `SKILL.md` にフロントマター＋ワークフロー手順＋Python実行スクリプトを埋め込む形式（NanoBanana2 と同構造）。スキル起動時に prompt/reference_images の有無から generate/edit モードを判定し、Bash ツール経由で Python スクリプトを実行する。

**Tech Stack:**
- OpenAI 公式 Python SDK (`openai`)
- Python 3（Windows 環境では `python` コマンド）
- Bash ツール（並列実行は `run_in_background=true`）
- API キー: 環境変数 `OPENAI_API_KEY`

**Spec:** [docs/superpowers/specs/2026-04-21-openai-image-gen-design.md](../specs/2026-04-21-openai-image-gen-design.md)

---

## File Structure

```
.claude/skills/openai-image-gen/
├── SKILL.md         # スキル定義本体（今回の唯一の実装物）
└── desktop.ini      # NanoBanana2 と同じく Windows 用（空でOK）

.company/outputs/openai-image-gen/
└── （テスト実行時に生成される画像の保存先）

docs/superpowers/specs/2026-04-21-openai-image-gen-design.md  # 既存
docs/superpowers/plans/2026-04-21-openai-image-gen.md         # この計画書
```

**責務:**
- `SKILL.md`: Claude Code が読み込むスキル定義。frontmatter（name/description）、入力仕様、ワークフロー（Step 1-3）、Python コード（generate/edit 両モード）、エラーハンドリング、実行例。

**注意:** skill の動作確認は「Claude Code からスキルを起動して実際に API を叩いて画像を保存できるか」で行う。ユニットテストは不要（外部 API ラッパのため）。代わりに **手動受入テスト** を Task 6 で実施する。

---

## Task 1: スキルディレクトリと SKILL.md 骨組みを作成

**Files:**
- Create: `.claude/skills/openai-image-gen/SKILL.md`
- Create: `.claude/skills/openai-image-gen/desktop.ini`

- [ ] **Step 1: ディレクトリ作成**

```bash
mkdir -p ".claude/skills/openai-image-gen"
```

- [ ] **Step 2: desktop.ini 作成（空ファイル）**

NanoBanana2 と同じパターン。Windows のフォルダメタデータ用。

```bash
touch ".claude/skills/openai-image-gen/desktop.ini"
```

- [ ] **Step 3: SKILL.md を frontmatter + 概要セクションのみで作成**

```markdown
---
name: openai-image-gen
description: OpenAI gpt-image-1 API経由で画像を生成して保存するスキル。単一・複数枚・参照画像入力（最大10枚）・4種のサイズ（1024x1024/1024x1536/1536x1024/auto）・3段階の画質（low/medium/high）に対応。
---

# OpenAI 画像生成スキル

## 概要

このスキルは、テキストプロンプト（および任意で参照画像）を入力として受け取り、OpenAI Images API（gpt-image-1 モデル）を使って画像を生成し、指定フォルダに PNG として保存します。
単一プロンプトでの生成のほか、複数プロンプトの並列生成にも対応しています。
参照画像を指定するとキャラクター一貫性を保った画像を生成できます。

## 入力

- **画像生成プロンプト**（必須）: 生成したい画像の説明テキスト。複数枚の場合はリスト形式
- **保存フォルダ名**（任意）: `.company/outputs/` 配下のフォルダ名。未指定時は `openai-image-gen`
- **サイズ**（任意）: `1024x1024` / `1024x1536` / `1536x1024` / `auto`。未指定時は `1024x1536`
- **画質**（任意）: `low` / `medium` / `high` / `auto`。未指定時は `medium`
- **参照画像**（任意）: 参照画像ファイルパスのリスト。最大10枚、各25MB以下、PNG/JPG/WebP
- **ファイル名プレフィックス**（任意）: 出力ファイル名の先頭に付ける識別子
```

- [ ] **Step 4: コミット**

```bash
git add ".claude/skills/openai-image-gen/"
git commit -m "feat(skill): add openai-image-gen skeleton with frontmatter"
```

---

## Task 2: 実行モード判定とワークフロー文面を追加

**Files:**
- Modify: `.claude/skills/openai-image-gen/SKILL.md`（末尾に追記）

- [ ] **Step 1: 実行モード表とワークフロー見出しを追加**

SKILL.md の末尾に以下を追記する:

```markdown
## 実行モード判定

スキル起動時に、入力内容から実行モードを判定する:

| モード | 条件 | 実行方法 |
|--------|------|----------|
| **generate（単一）** | プロンプト1つ・参照画像なし | Step 2 を1回実行（images.generate） |
| **edit（単一）** | プロンプト1つ・参照画像1枚以上 | Step 2 を1回実行（images.edit） |
| **並列（複数）** | プロンプトが複数 | Step 2 を各プロンプトごとに `run_in_background` で並列実行 |

## ワークフロー

### Step 1: 環境準備

1. 環境変数 `OPENAI_API_KEY` が設定されているか確認する。**未設定の場合は `~/.bashrc` から読み込みを試みる。** それでも未設定ならエラー表示して終了。

```bash
source ~/.bashrc 2>/dev/null
if [ -z "$OPENAI_API_KEY" ]; then
  echo "ERROR: 環境変数 OPENAI_API_KEY が設定されていません。"
  exit 1
fi
```

2. `openai` パッケージがインストールされているか確認し、なければインストールする。

```bash
pip install -q openai 2>/dev/null || pip install -q openai
```
```

- [ ] **Step 2: コミット**

```bash
git add ".claude/skills/openai-image-gen/SKILL.md"
git commit -m "docs(skill): document openai-image-gen workflow modes"
```

---

## Task 3: generate モード用 Python スクリプトを SKILL.md に埋め込む

**Files:**
- Modify: `.claude/skills/openai-image-gen/SKILL.md`

- [ ] **Step 1: Step 2（画像生成）セクションと Python スクリプトを追記**

SKILL.md 末尾に以下を追加:

````markdown
### Step 2: 画像生成と保存

以下のPythonスクリプトをBashツールで実行する。変数部分はスキル実行時に適切な値に置き換えること。

- `IMAGE_PROMPT`: ユーザーから受け取った画像生成プロンプト
- `OUTPUT_FOLDER`: 保存フォルダ名（デフォルト: `openai-image-gen`）
- `SIZE`: サイズ（デフォルト: `1024x1536`）
- `QUALITY`: 画質（デフォルト: `medium`）
- `REFERENCE_IMAGES`: 参照画像パスのカンマ区切り文字列（デフォルト: 空文字）
- `FILE_PREFIX`: ファイル名プレフィックス（デフォルト: 空）
- `PROJECT_ROOT`: プロジェクトルートパス（`G:/マイドライブ/YNFactory-cc`）

**重要: Windows環境では `python3` ではなく `python` を使用すること。**

```bash
export OPENAI_API_KEY="$OPENAI_API_KEY" && python << 'PYTHON_SCRIPT'
import os
import sys
import base64
import datetime

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai not found. Run: pip install openai")
    sys.exit(1)

# --- 設定 ---
API_KEY = os.environ.get("OPENAI_API_KEY")
if not API_KEY:
    print("ERROR: OPENAI_API_KEY is not set.")
    sys.exit(1)

PROMPT = """{{IMAGE_PROMPT}}"""
OUTPUT_FOLDER = "{{OUTPUT_FOLDER}}"
SIZE = "{{SIZE}}"
QUALITY = "{{QUALITY}}"
REFERENCE_IMAGES_RAW = "{{REFERENCE_IMAGES}}"
FILE_PREFIX = "{{FILE_PREFIX}}"
PROJECT_ROOT = r"{{PROJECT_ROOT}}"

# --- バリデーション ---
VALID_SIZES = {"1024x1024", "1024x1536", "1536x1024", "auto"}
if SIZE not in VALID_SIZES:
    print(f"ERROR: Unsupported size '{SIZE}'. Valid: {sorted(VALID_SIZES)}")
    sys.exit(1)

VALID_QUALITIES = {"low", "medium", "high", "auto"}
if QUALITY not in VALID_QUALITIES:
    print(f"ERROR: Unsupported quality '{QUALITY}'. Valid: {sorted(VALID_QUALITIES)}")
    sys.exit(1)

reference_paths = [p.strip() for p in REFERENCE_IMAGES_RAW.split(",") if p.strip()]
if len(reference_paths) > 10:
    print(f"ERROR: Too many reference images ({len(reference_paths)}). Max 10.")
    sys.exit(1)

for p in reference_paths:
    if not os.path.exists(p):
        print(f"ERROR: Reference image not found: {p}")
        sys.exit(1)
    size_bytes = os.path.getsize(p)
    if size_bytes > 25 * 1024 * 1024:
        print(f"ERROR: Reference image exceeds 25MB: {p} ({size_bytes} bytes)")
        sys.exit(1)

# --- 出力ディレクトリ作成 ---
output_dir = os.path.join(PROJECT_ROOT, ".company", "outputs", OUTPUT_FOLDER)
os.makedirs(output_dir, exist_ok=True)

# --- API呼び出し ---
client = OpenAI(api_key=API_KEY)
try:
    if reference_paths:
        # edit モード
        image_files = [open(p, "rb") for p in reference_paths]
        try:
            result = client.images.edit(
                model="gpt-image-1",
                image=image_files if len(image_files) > 1 else image_files[0],
                prompt=PROMPT,
                size=SIZE,
                quality=QUALITY,
                n=1,
            )
        finally:
            for f in image_files:
                f.close()
    else:
        # generate モード
        result = client.images.generate(
            model="gpt-image-1",
            prompt=PROMPT,
            size=SIZE,
            quality=QUALITY,
            n=1,
        )
except Exception as e:
    print(f"ERROR: API call failed: {e}")
    sys.exit(1)

# --- レスポンス処理 ---
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
prefix = f"{FILE_PREFIX}_" if FILE_PREFIX else ""
image_count = 0

for i, item in enumerate(result.data or []):
    b64 = getattr(item, "b64_json", None)
    if not b64:
        continue
    image_count += 1
    filename = f"{prefix}{timestamp}_{image_count:03d}.png"
    filepath = os.path.join(output_dir, filename)
    try:
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(b64))
        print(f"OK: {filepath}")
    except Exception as e:
        print(f"ERROR: save failed: {e}")
        sys.exit(1)

if image_count == 0:
    print("WARNING: No image in response.")
    sys.exit(1)

print(f"\n--- Result ---")
print(f"Images: {image_count}")
print(f"Dir: {output_dir}")
print(f"Mode: {'edit' if reference_paths else 'generate'}")
print(f"Size: {SIZE}, Quality: {QUALITY}")
print("--- Done ---")
PYTHON_SCRIPT
```
````

- [ ] **Step 2: コミット**

```bash
git add ".claude/skills/openai-image-gen/SKILL.md"
git commit -m "feat(skill): embed generate/edit python script in openai-image-gen"
```

---

## Task 4: 並列実行・結果報告・実行例セクションを追記

**Files:**
- Modify: `.claude/skills/openai-image-gen/SKILL.md`

- [ ] **Step 1: 並列実行と結果報告セクションを追加**

SKILL.md 末尾に追記:

````markdown
### Step 2b: 複数枚生成（並列実行）

複数プロンプトが指定された場合、**Step 2のBashコマンドを各プロンプトごとに `run_in_background: true` で並列起動**する。

手順:
1. 各プロンプトに対して、個別の `FILE_PREFIX`（例: `vol1`, `vol2`...）を設定する
2. 全てのBashコマンドを**1つのメッセージ内で同時に**発行する（並列実行）
3. 全タスク完了後、結果をまとめて報告する

例: 4枚生成の場合
- Bash(run_in_background=true): プロンプト1 → FILE_PREFIX="vol1"
- Bash(run_in_background=true): プロンプト2 → FILE_PREFIX="vol2"
- Bash(run_in_background=true): プロンプト3 → FILE_PREFIX="vol3"
- Bash(run_in_background=true): プロンプト4 → FILE_PREFIX="vol4"

### Step 3: 結果報告

生成完了後、以下の情報をユーザーに報告する:

1. 生成された全画像のファイルパス
2. 保存先フォルダのパス
3. 使用モード（generate / edit）
4. 使用サイズ・画質
5. 画像をReadツールで表示する（ユーザーに確認してもらう）

## 実行例

### 単一生成（テキストのみ）

> 「かわいい柴犬がお花畑で遊んでいるイラストを生成して」

1. プロンプト: `かわいい柴犬がお花畑で遊んでいるイラスト`
2. 保存フォルダ: `openai-image-gen`（デフォルト）
3. サイズ: `1024x1536`（デフォルト）
4. 画質: `medium`（デフォルト）
5. API呼び出し → `.company/outputs/openai-image-gen/20260421_153000_001.png` に保存

### 単一生成（参照画像あり）

> 「ミサキが公園を歩いている場面」＋ 参照画像: `ミサキ.png`

1. プロンプト: `ミサキが公園を歩いている場面`
2. 参照画像: `[ミサキ.png]`
3. モード: edit（参照画像あり）
4. API呼び出し（images.edit）→ `.company/outputs/openai-image-gen/` に保存

### 複数枚並列生成

> 「マンガ第1巻の表紙3種を生成」（3つのプロンプトがリストで渡される）

1. 3つのプロンプトを並列で同時実行
2. FILE_PREFIX: `variantA`, `variantB`, `variantC`
3. 保存フォルダ: `openai-image-gen/cover-variants`
4. 全完了後、3枚まとめて報告

## ファイル名規則

- 単一: `{timestamp}_{連番}.png`
- プレフィックス付き: `{prefix}_{timestamp}_{連番}.png`
- timestamp: `YYYYMMDD_HHMMSS`
- 連番: `001` から開始（3桁ゼロ埋め）

## 対応サイズ

| 値 | ピクセル | 用途例 |
|----|---------|--------|
| `1024x1024` | 1024×1024 | SNSアイコン、正方形素材 |
| `1024x1536` | 1024×1536 | マンガコマ、書籍カバー、縦長（デフォルト） |
| `1536x1024` | 1536×1024 | 横長バナー、YouTubeサムネイル |
| `auto` | モデル任せ | 判断を OpenAI に委ねる |

※ NanoBanana2 のような `9:16` や `4:5` 等の任意アスペクト比は非対応。

## 対応画質（料金目安: 1024x1536 1枚あたり）

| 値 | 料金目安 | 用途例 |
|----|----------|--------|
| `low` | $0.016 | テスト、ラフ、大量生成 |
| `medium` | $0.063 | 通常用途（デフォルト） |
| `high` | $0.25 | 最終版、印刷物 |
| `auto` | 不定 | OpenAI任せ |
````

- [ ] **Step 2: コミット**

```bash
git add ".claude/skills/openai-image-gen/SKILL.md"
git commit -m "docs(skill): add parallel execution and usage examples to openai-image-gen"
```

---

## Task 5: エラーハンドリング・注意事項・将来拡張セクションを追記

**Files:**
- Modify: `.claude/skills/openai-image-gen/SKILL.md`

- [ ] **Step 1: 残りの定型セクションを追加**

SKILL.md 末尾に追記:

```markdown
## エラーハンドリング

| エラー | 対処 |
|--------|------|
| `OPENAI_API_KEY` 未設定 | エラーメッセージを表示し、APIキーの取得・設定方法を案内する |
| `openai` 未インストール | `pip install openai` を自動実行する |
| 非対応サイズ | 対応一覧（4種）を表示してエラー終了 |
| 非対応画質 | 対応一覧（4種）を表示してエラー終了 |
| 参照画像ファイル不在 | パスを表示してエラー終了 |
| 参照画像が 25MB 超 | サイズを表示してエラー終了 |
| 参照画像が 10枚超 | 枚数を表示してエラー終了 |
| API 呼び出しエラー | エラー詳細を表示し、プロンプトの修正や rate limit の確認を案内 |
| レスポンスに画像なし | WARNING を表示して終了 |

## 注意事項

- APIキーは環境変数 `OPENAI_API_KEY` に事前設定が必要
- Windows環境では `python3` ではなく `python` コマンドを使用する
- モデル `gpt-image-1` は 2025 年リリースの画像生成モデルで、画像は base64 エンコードされて返される（URL 形式は非対応）
- 生成画像はPNG形式で保存される
- 複数枚生成時はAPI呼び出しが並列で行われるため、レート制限に注意
- 料金は 1 枚ごとの課金で、サイズ・画質により変動する
- アスペクト比は 4 種のネイティブサイズのみ対応（任意比率の自動マッピングは行わない）

## 将来の拡張予定

- マスク編集（inpainting）対応
- ebook-to-manga からの呼び出し切替（設定ファイルで NanoBanana2/OpenAI を選択）
- アスペクト比の自動マッピング層（`9:16` → `1024x1536` 等）
- `n > 1` での 1 プロンプトからの複数バリアント生成
```

- [ ] **Step 2: コミット**

```bash
git add ".claude/skills/openai-image-gen/SKILL.md"
git commit -m "docs(skill): add error handling and notes sections to openai-image-gen"
```

---

## Task 6: 受入テスト（generate モード単一）

**Files:**
- 実行のみ。新規ファイルは生成される画像のみ。

- [ ] **Step 1: API キーが設定されていることを確認**

```bash
source ~/.bashrc 2>/dev/null
echo "OPENAI_API_KEY set: $([ -n "$OPENAI_API_KEY" ] && echo yes || echo no)"
```

Expected: `OPENAI_API_KEY set: yes`

未設定の場合はユーザーに APIキー設定を依頼してから続行。

- [ ] **Step 2: Claude Code からスキルを起動（テキストのみ単一生成）**

スキル起動方法: ユーザーに依頼するか、自セッションで以下のような指示を流す:

> openai-image-gen スキルを使って「夕焼けの富士山を背景にした和風の神社」を 1024x1536 / medium で生成して

- [ ] **Step 3: 生成結果を確認**

```bash
ls -la ".company/outputs/openai-image-gen/"
```

Expected: `{timestamp}_001.png` が 1 つ存在し、サイズが数十 KB〜数 MB 程度。

- [ ] **Step 4: 画像を Read ツールで表示して目視確認**

Read ツールで生成画像を開き、プロンプトに沿った内容であることを確認する。

- [ ] **Step 5: 合否判定**

合格条件:
- ファイルが `1024x1536` 相当の縦長 PNG で保存されている
- プロンプトに沿った内容（夕焼け・富士山・神社が含まれる）

不合格なら SKILL.md を修正して Task 3 に戻る。

---

## Task 7: 受入テスト（edit モード・参照画像あり）

**Files:**
- 実行のみ。

- [ ] **Step 1: 参照画像を用意**

既存のキャラクター画像を利用する（例: ebook-to-manga の manga-career-restart vol1 で使用している `ミサキ.png`）。存在しない場合は任意の人物 PNG を 1 枚用意する。

```bash
find ".company/outputs/ebooks-manga" -name "ミサキ*.png" -type f | head -3
```

- [ ] **Step 2: edit モードでスキルを起動**

> openai-image-gen スキルを使って、参照画像 `<上記で見つけた ミサキ.png のパス>` を渡し、「参照画像の人物が桜並木を歩いている場面」を 1024x1536 / medium で生成して

- [ ] **Step 3: 生成結果を確認**

```bash
ls -la ".company/outputs/openai-image-gen/" | tail -3
```

新しい PNG が生成されていること。

- [ ] **Step 4: 画像を Read ツールで表示**

生成画像を目視確認し、参照画像の人物と外見的特徴（髪型・服装系統）がある程度維持されているかを確認する。

- [ ] **Step 5: 合否判定**

合格条件:
- edit モードでエラーなく画像が 1 枚生成されている
- プロンプト内容（桜並木を歩く）が反映されている
- 参照人物との類似性が一定程度ある（完璧な同一性は求めない）

---

## Task 8: 受入テスト（並列実行）

**Files:**
- 実行のみ。

- [ ] **Step 1: 並列モードでスキルを起動**

> openai-image-gen スキルを使って、以下 3 つのプロンプトを並列で生成して。サイズは全て 1024x1024、quality は low（コスト節約）で、file_prefix は variantA/B/C:
> 1. 赤いバラの花束
> 2. 青いアジサイの花束
> 3. 黄色いヒマワリの花束

- [ ] **Step 2: 結果確認**

```bash
ls -la ".company/outputs/openai-image-gen/" | grep variant
```

Expected: `variantA_*.png`, `variantB_*.png`, `variantC_*.png` の 3 ファイルが存在する。

- [ ] **Step 3: 目視確認**

各画像が対応する花の色であることを Read ツールで確認。

- [ ] **Step 4: 合否判定**

合格条件:
- 3 ファイルすべてが生成されている
- ファイル名プレフィックスが正しく反映されている
- 並列実行されている（一つずつではなく同時起動）

---

## Task 9: 受入テスト（エラーケース）

**Files:**
- 実行のみ。

- [ ] **Step 1: 非対応サイズでのエラー確認**

> openai-image-gen スキルを使って「テスト画像」を size=`9:16` で生成して

Expected: Python スクリプトが `ERROR: Unsupported size '9:16'` を表示して終了する。

- [ ] **Step 2: 存在しない参照画像でのエラー確認**

> openai-image-gen スキルを使って、参照画像 `./nonexistent.png` を渡して「テスト画像」を生成して

Expected: `ERROR: Reference image not found: ./nonexistent.png`

- [ ] **Step 3: 合否判定**

合格条件:
- 両方のケースで Python スクリプトが API を叩く前にエラー終了する
- エラーメッセージが明確で対応方法がわかる

---

## Task 10: 最終確認とメモリ更新

**Files:**
- Modify: `C:/Users/fcmdt/.claude/projects/g---------YNFactory-cc/memory/MEMORY.md`（該当する場合）
- Create: `C:/Users/fcmdt/.claude/projects/g---------YNFactory-cc/memory/project_openai_image_gen.md`

- [ ] **Step 1: SKILL.md の最終レビュー**

[.claude/skills/openai-image-gen/SKILL.md](.claude/skills/openai-image-gen/SKILL.md) を Read で開き、以下を確認:
- frontmatter の `name` と `description` が正しい
- `{{IMAGE_PROMPT}}` などのプレースホルダ変数がすべて記述されている
- Step 1〜3 がすべて揃っている
- 実行例が 3 種（generate 単一・edit 単一・並列）含まれる

- [ ] **Step 2: メモリ記録を作成**

```markdown
---
name: openai-image-gen スキル
description: OpenAI gpt-image-1 を使う画像生成スキル。NanoBanana2 と並行運用、ebook-to-manga での画質比較に使用可能
type: project
---

openai-image-gen スキルを新規作成（2026-04-21）。gpt-image-1 ベースで参照画像入力に対応、NanoBanana2 と並行運用。

**Why:** NanoBanana2 の画質と OpenAI gpt-image-1 の画質を比較検証するため。ebook-to-manga での最終的な画像生成エンジン選定に使う。

**How to apply:** OpenAI の画像生成を使いたい場面では `openai-image-gen` スキル、Gemini を使いたい場面では `nanobanana2-image-gen` スキルを指定する。サイズは gpt-image-1 の 4 種（1024x1024/1024x1536/1536x1024/auto）のみ対応。
```

- [ ] **Step 3: MEMORY.md インデックスに追加**

`MEMORY.md` の末尾に 1 行追加:

```
- [openai-image-gen スキル](project_openai_image_gen.md) — OpenAI gpt-image-1 ベース、NanoBanana2 と並行運用、ebook-to-manga 比較用
```

- [ ] **Step 4: 最終コミット**

```bash
git add ".claude/skills/openai-image-gen/" "docs/superpowers/"
git commit -m "feat(skill): openai-image-gen 実装完了（受入テスト通過）"
```

- [ ] **Step 5: 完了報告**

ユーザーに以下を報告:
- スキルのパス
- 受入テスト結果（Task 6-9 の合否）
- 生成サンプル画像のパス
- 次に試せる用途（例: ebook-to-manga での差し替え実験）

---

## Self-Review Checklist

- [x] Spec 7 章「完了条件」の各項目を Task 6-9 でカバー
- [x] プレースホルダ・TBD なし
- [x] 型・変数名の一貫性（`IMAGE_PROMPT`, `SIZE`, `QUALITY`, `REFERENCE_IMAGES` で統一）
- [x] ファイルパスすべて絶対パス or 相対パスで明示
- [x] 各 Task にコミット step 含む
