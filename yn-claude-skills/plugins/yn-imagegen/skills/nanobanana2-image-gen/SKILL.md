---
name: nanobanana2-image-gen
description: Google AI Studio API経由でNanoBanana2（Gemini画像生成）を使い、プロンプトから画像を生成して保存するスキル。単一・複数枚・アスペクト比指定に対応。ユーザーがNanoBanana/Gemini画像生成を明示的に指定した場合、またはAPIキー保有下でのAPI直接生成が求められる場合に使う。ChatGPT/gpt-image-2系の生成はopenai-image-gen（ガードレール）の対象であり本スキルでは代替しない。KDP本文中の挿絵キュー処理はcodeximageを使う。
---

# NanoBanana2 画像生成スキル

## 概要

このスキルは、テキストプロンプトを入力として受け取り、Google AI Studio API（Gemini 3.1 Flash Image Preview / NanoBanana2）を使って画像を生成し、指定フォルダにPNGとして保存します。
単一プロンプトでの生成のほか、複数プロンプトの並列生成にも対応しています。

## 入力

- **画像生成プロンプト**（必須）: 生成したい画像の説明テキスト。複数枚の場合はリスト形式で受け取る
- **保存フォルダ名**（任意）: `.company/outputs/` 配下のフォルダ名。未指定時は `nanobanana2-gen`
- **アスペクト比**（任意）: `1:1`, `9:16`, `16:9`, `4:3`, `3:4`, `2:3`, `3:2`, `4:5`, `5:4` 等。未指定時は `1:1`
- **ファイル名プレフィックス**（任意）: 出力ファイル名の先頭に付ける識別子

## 実行モード判定

スキル起動時に、入力内容から実行モードを判定する:

| モード | 条件 | 実行方法 |
|--------|------|----------|
| **単一生成** | プロンプトが1つ | Step 2を1回実行 |
| **複数生成** | プロンプトが複数（リスト/表/複数回指示） | Step 2を**並列**（Bash background）で実行 |

## ワークフロー

### Step 1: 環境準備

1. 環境変数 `GOOGLE_AI_STUDIO_API_KEY` が設定されているか確認する。**未設定の場合は `~/.bashrc` から読み込みを試みる。** それでも未設定ならエラー表示して終了。

```bash
source ~/.bashrc 2>/dev/null
if [ -z "$GOOGLE_AI_STUDIO_API_KEY" ]; then
  echo "ERROR: 環境変数 GOOGLE_AI_STUDIO_API_KEY が設定されていません。"
  exit 1
fi
```

2. `google-genai` パッケージがインストールされているか確認し、なければインストールする。

```bash
pip install -q google-genai 2>/dev/null || pip install -q google-genai
```

### Step 2: 画像生成と保存

以下のPythonスクリプトをBashツールで実行する。変数部分はスキル実行時に適切な値に置き換えること。

- `IMAGE_PROMPT`: ユーザーから受け取った画像生成プロンプト
- `OUTPUT_FOLDER`: 保存フォルダ名（デフォルト: `nanobanana2-gen`）
- `ASPECT_RATIO`: アスペクト比（デフォルト: `1:1`）
- `FILE_PREFIX`: ファイル名プレフィックス（デフォルト: 空）
- `PROJECT_ROOT`: プロジェクトルートパス（リポジトリルート。Drive側で作業する場合はDrive側の `YNFactory-cc` の絶対パスに置き換える。PC固有パスをスキル本文に固定しない）

**重要: Windows環境では `python3` ではなく `python` を使用すること。**

```bash
export GOOGLE_AI_STUDIO_API_KEY="$GOOGLE_AI_STUDIO_API_KEY" && python << 'PYTHON_SCRIPT'
import os
import sys
import datetime

try:
    from google import genai
    from google.genai import types
except ImportError:
    print("ERROR: google-genai not found. Run: pip install google-genai")
    sys.exit(1)

# --- 設定 ---
API_KEY = os.environ.get("GOOGLE_AI_STUDIO_API_KEY")
if not API_KEY:
    print("ERROR: GOOGLE_AI_STUDIO_API_KEY is not set.")
    sys.exit(1)

PROMPT = """{{IMAGE_PROMPT}}"""
OUTPUT_FOLDER = "{{OUTPUT_FOLDER}}"
ASPECT_RATIO = "{{ASPECT_RATIO}}"
FILE_PREFIX = "{{FILE_PREFIX}}"
PROJECT_ROOT = r"{{PROJECT_ROOT}}"

# --- 出力ディレクトリ作成 ---
output_dir = os.path.join(PROJECT_ROOT, ".company", "outputs", OUTPUT_FOLDER)
os.makedirs(output_dir, exist_ok=True)

# --- API呼び出し ---
try:
    client = genai.Client(api_key=API_KEY)
    config_kwargs = {"response_modalities": ["TEXT", "IMAGE"]}
    if ASPECT_RATIO:
        config_kwargs["image_config"] = types.ImageConfig(aspect_ratio=ASPECT_RATIO)
    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=PROMPT,
        config=types.GenerateContentConfig(**config_kwargs),
    )
except Exception as e:
    print(f"ERROR: API call failed: {e}")
    sys.exit(1)

# --- レスポンス処理 ---
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
prefix = f"{FILE_PREFIX}_" if FILE_PREFIX else ""
image_count = 0
text_parts = []

if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data is not None:
            image_count += 1
            filename = f"{prefix}{timestamp}_{image_count:03d}.png"
            filepath = os.path.join(output_dir, filename)
            try:
                image = part.as_image()
                image.save(filepath)
                print(f"OK: {filepath}")
            except Exception as e:
                print(f"ERROR: save failed: {e}")
                sys.exit(1)
        elif hasattr(part, "text") and part.text:
            text_parts.append(part.text)

if image_count == 0:
    print("WARNING: No image in response.")
    if text_parts:
        print(f"Text: {''.join(text_parts)}")
    sys.exit(1)

print(f"\n--- Result ---")
print(f"Images: {image_count}")
print(f"Dir: {output_dir}")
if text_parts:
    print(f"Text: {''.join(text_parts)}")
print("--- Done ---")
PYTHON_SCRIPT
```

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
2. APIから返されたテキストレスポンス（ある場合）
3. 保存先フォルダのパス
4. 画像をReadツールで表示する（ユーザーに確認してもらう）。複数枚生成時は全件表示せず、最新1〜5件のみ表示する

## 実行例

### 単一生成

> 「かわいい柴犬がお花畑で遊んでいるイラストを生成して」

1. プロンプト: `かわいい柴犬がお花畑で遊んでいるイラスト`
2. 保存フォルダ: `nanobanana2-gen`（デフォルト）
3. アスペクト比: `1:1`（デフォルト）
4. API呼び出し → `.company/outputs/nanobanana2-gen/20260324_153000_001.png` に保存

### 複数枚並列生成

> 「2030年問題シリーズ全4巻の表紙を生成して」（各巻のプロンプトがリストで渡される）

1. 4つのプロンプトを並列で同時実行
2. FILE_PREFIX: `vol1`, `vol2`, `vol3`, `vol4`
3. 保存フォルダ: `nanobanana2-gen/2030-series`
4. 全完了後、4枚まとめて報告

## ファイル名規則

- 単一: `{timestamp}_{連番}.png`
- プレフィックス付き: `{prefix}_{timestamp}_{連番}.png`
- timestamp: `YYYYMMDD_HHMMSS`
- 連番: `001` から開始（3桁ゼロ埋め）

## 対応アスペクト比

| 値 | 用途例 |
|----|--------|
| `1:1` | SNSアイコン、正方形素材（デフォルト） |
| `9:16` | 書籍カバー、縦長ストーリーズ |
| `16:9` | YouTube サムネイル、横長バナー |
| `4:3` | プレゼン資料、ブログ画像 |
| `3:4` | ポートレート |
| `2:3` | ポスター |
| `4:5` | Instagram投稿 |

## エラーハンドリング

| エラー | 対処 |
|--------|------|
| `GOOGLE_AI_STUDIO_API_KEY` 未設定 | エラーメッセージを表示し、APIキーの取得・設定方法を案内する |
| `google-genai` 未インストール | `pip install google-genai` を自動実行する |
| API呼び出しエラー | エラー詳細を表示し、プロンプトの修正やAPIキーの確認を案内する |
| レスポンスに画像なし | テキストレスポンスを表示し、プロンプトの修正を提案する |
| 非対応アスペクト比 | 対応一覧を表示し、最も近い比率を提案する |

## 注意事項

- APIキーは環境変数 `GOOGLE_AI_STUDIO_API_KEY` に事前設定が必要
- Windows環境では `python3` ではなく `python` コマンドを使用する
- モデル `gemini-3.1-flash-image-preview` はプレビュー版であり、仕様変更の可能性がある
- 生成画像はPNG形式で保存される
- 複数枚生成時はAPI呼び出しが並列で行われるため、レート制限に注意
- 料金: 入力$0.50/1Mトークン、画像出力$60.00/1Mトークン

## 将来の拡張予定（v3以降）

- 画像編集（既存画像 + プロンプトによる修正）
- スタイル指定（イラスト、写真風、アニメ風など）
- Google Searchグラウンディング（実在の対象を正確に描画）
