# openai-image-gen スキル設計書

- 作成日: 2026-04-21
- 目的: OpenAI `gpt-image-1` を使った画像生成スキルを、既存の `nanobanana2-image-gen` と並行運用できる形で新規作成する。ebook-to-manga 等での画質・キャラ一貫性を比較検証可能にする。

## 1. ゴールとスコープ

### ゴール
- `.claude/skills/openai-image-gen/SKILL.md` として、プロンプト→画像生成→PNG保存までをワンストップで行うスキルを新規作成する。
- 参照画像入力（キャラクター一貫性用）に対応し、ebook-to-manga の `ミサキ.png` / `ケンタ.png` のような使い方ができる。
- NanoBanana2 とファイル名規則・保存先規則・並列実行パターンを揃え、将来的に呼び出し側で切り替えやすい形にする。

### スコープ外
- NanoBanana2 スキルの変更・削除（並行運用）。
- ebook-to-manga 等、既存スキルからの呼び出し箇所の差し替え（本スキル完成後に別タスク）。
- 動画生成や音声生成。
- Web UI・CLI ラッパの提供。

## 2. 技術仕様

### 使用モデル
- `gpt-image-1`（OpenAI Images API 2025 モデル）
- エンドポイント: `images.generate`（テキスト→画像）、`images.edit`（参照画像あり）

### 引数仕様

| 引数 | 必須 | デフォルト | 説明 |
|---|---|---|---|
| `prompt` | ✅ | - | 生成プロンプト。複数指定時は並列実行 |
| `output_folder` | - | `openai-image-gen` | `.company/outputs/` 配下のフォルダ名 |
| `size` | - | `1024x1536` | `1024x1024` / `1024x1536` / `1536x1024` / `auto` |
| `quality` | - | `medium` | `low` / `medium` / `high` / `auto` |
| `reference_images` | - | なし | 参照画像ファイルパスのリスト（最大10枚、各25MB以下、PNG/JPG/WebP） |
| `file_prefix` | - | 空 | ファイル名プレフィックス |

### 動作モード判定

| モード | 条件 | 使用 API |
|---|---|---|
| generate | `reference_images` 指定なし | `client.images.generate()` |
| edit | `reference_images` が1件以上 | `client.images.edit()` |
| 並列 | `prompt` が複数 | 上記どちらかを `run_in_background=true` で同時起動 |

### サイズ方針
- NanoBanana2 のような任意アスペクト比（`9:16` 等）は gpt-image-1 では非対応のため **マッピングせずエラー** とする。
- 呼び出し側（人間 or 他スキル）は本スキルの 4 値（`1024x1024` / `1024x1536` / `1536x1024` / `auto`）のいずれかを明示的に渡す。
- ebook-to-manga の `9:16` コマは `1024x1536`（縦長）を使用する運用とする。

### 料金見積り（2026-04 時点の公開価格目安）

| quality | 1024x1536 1枚あたり |
|---|---|
| low | $0.016 |
| medium | $0.063 |
| high | $0.25 |

ebook-to-manga 1冊 100コマで medium 使用時の概算: $6.3 / 約950円。

## 3. ファイル規則

### 保存先
- ルート: `.company/outputs/{output_folder}/`
- プロジェクトルート: `G:/マイドライブ/YNFactory-cc`

### ファイル名
- 単一: `{timestamp}_{連番}.png`
- プレフィックス付き: `{prefix}_{timestamp}_{連番}.png`
- `timestamp`: `YYYYMMDD_HHMMSS`
- 連番: `001` から 3桁ゼロ埋め

## 4. エラーハンドリング

| エラー | 対処 |
|---|---|
| `OPENAI_API_KEY` 未設定 | `source ~/.bashrc` を試行 → それでも未設定ならエラー終了 |
| `openai` パッケージ未インストール | `pip install openai` を自動実行 |
| 非対応 `size` 値 | 対応 4 値を表示してエラー終了 |
| 参照画像ファイル不在 | パスを表示してエラー終了 |
| 参照画像が 25MB 超 | サイズを表示してエラー終了、軽量化を案内 |
| API エラー（rate limit 等） | エラー詳細を表示、再試行不要なら終了 |
| レスポンス画像なし | テキストレスポンスがあれば表示 |

## 5. ワークフロー

### Step 1: 環境準備
1. `OPENAI_API_KEY` 確認（未設定なら `~/.bashrc` 読み込み）。
2. `openai` パッケージ確認、未インストールなら `pip install openai`。

### Step 2: 画像生成
- generate / edit モードに応じて Python スクリプトを実行。
- レスポンスの `b64_json` を base64 デコードして PNG 保存。

### Step 2b: 並列実行（複数プロンプト時）
- 各プロンプトに個別 `file_prefix` を割り当て、1 メッセージ内で `run_in_background=true` の Bash を複数発行。
- 全タスク完了後にまとめて結果報告。

### Step 3: 結果報告
- 生成ファイルパス一覧、保存先フォルダ、API のテキストレスポンス（あれば）を表示。
- 生成画像を Read ツールで表示して確認させる。

## 6. NanoBanana2 との対比

| 項目 | NanoBanana2 | openai-image-gen |
|---|---|---|
| モデル | `gemini-3.1-flash-image-preview` | `gpt-image-1` |
| API キー env | `GOOGLE_AI_STUDIO_API_KEY` | `OPENAI_API_KEY` |
| SDK | `google-genai` | `openai` |
| 参照画像 | プロンプトに埋め込み | `images.edit` に引き渡し（最大10枚） |
| アスペクト比 | 9種類（1:1〜5:4） | 4種類（1024x1024 / 1024x1536 / 1536x1024 / auto） |
| 料金体系 | トークン課金 | 画像1枚課金（quality依存） |
| 保存先規則 | `.company/outputs/{folder}/` | 同左 |
| ファイル名規則 | `{prefix}_{timestamp}_{連番}.png` | 同左 |
| 並列実行 | `run_in_background` | 同左 |

## 7. 完了条件

- [ ] `.claude/skills/openai-image-gen/SKILL.md` が存在する
- [ ] 単一プロンプト（テキストのみ）で画像が生成・保存できる
- [ ] 参照画像 1 枚ありの edit モードで画像が生成できる
- [ ] 参照画像 2 枚以上ありの edit モードで画像が生成できる
- [ ] 複数プロンプトの並列生成ができる
- [ ] 4 種の `size` すべてで生成できる
- [ ] 3 種の `quality`（low/medium/high）すべてで生成できる
- [ ] エラーハンドリング（APIキー未設定・非対応size・参照画像不在）が動作する
- [ ] SKILL.md の frontmatter（name/description）が Claude Code に正しく認識される

## 8. 将来拡張（今回スコープ外）

- `response_format=url` でのURL受け取り（現状は base64 固定）
- マスク編集（inpainting）対応
- ebook-to-manga からの呼び出し切替（設定ファイルで NanoBanana2/OpenAI を選択）
- アスペクト比の自動マッピング層（`9:16` → `1024x1536` 等）
- バックグラウンド生成 + webhook 受信
