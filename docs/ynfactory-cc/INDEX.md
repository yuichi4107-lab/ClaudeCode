# YNFactory-cc ワークスペース インデックス

Google Drive 上の作業ディレクトリ `YNFactory-cc`（Claude Code / Codex の共有作業場所）の内容を、このリポジトリに共有するためのインデックス。

- Drive フォルダ: [YNFactory-cc](https://drive.google.com/drive/folders/1pTrN2vTBHiHLeYGt31zWSIofwgFjqF9M)
- スナップショット取得日: 2026-07-27（コード本体の取り込み: 2026-07-28）
- **2026-07-28 更新**: 下記の全プロジェクトのコード・テキストファイルをこのリポジトリ直下に取り込み済み（画像・動画・DB・キャッシュ・`.env`等の秘匿ファイルは Drive 側のみ）。各ファイルは Drive の fileSize とのバイト数一致で検証済み
- 同フォルダのルール本体はこのディレクトリ内の [`CLAUDE.md`](./CLAUDE.md) / [`AGENTS.md`](./AGENTS.md) / [`gitignore`](./gitignore)（Drive の `.gitignore` のコピー）を参照

## 運用ポリシー（Drive 側 CLAUDE.md より要約)

- 論理上の作業場所は `YNFactory-cc` リポジトリルート（Mac: `/Users/yuichi/YNFactory-cc`、Windows: `C:\YNFactory-cc`）
- 通常の制作・入力整理・成果物作成は Google Drive 側の `YNFactory-cc` で行い、PC 間で共有する
- GitHub に送るのはコード・スキル・ルール・設定のみ。Drive 側に `.git/` は置かず、Git 操作はローカル Git 作業ディレクトリで行う
- Drive ⇔ ローカル Git の反映は `.company/scripts/sync_drive_git.py`、毎日 3 時（JST）の同期は `.company/scripts/daily_git_sync.py`

## プロジェクト一覧

| フォルダ | 概要 | 最終更新 | Drive |
|---|---|---|---|
| `rakuten-room-auto` | 楽天ROOM自動化 | 2026-07-27 | [開く](https://drive.google.com/drive/folders/1HVoxs86QixN_Afz5Mfnvyu6zfgDy6EOC) |
| `scripts` | 共通スクリプト | 2026-07-19 | [開く](https://drive.google.com/drive/folders/1imPnTMMF3H37HY83CCWNAShnZmAj6RVQ) |
| `tools` | 汎用ツール群 | 2026-07-19 | [開く](https://drive.google.com/drive/folders/1WzjO7KSAblNQQMsT2J7Swn8WgH1QbZmi) |
| `docs` | ドキュメント（backup-zslim.md 等） | 2026-07-11 | [開く](https://drive.google.com/drive/folders/1cIe7W5gizn4_oXonqCog33KZnBM2yCwT) |
| `pdf-annotator` | PDF注釈ツール | 2026-07-08 | [開く](https://drive.google.com/drive/folders/1iBQ-a5y9EJ5NetnqfUml6x3JbEXy0u4N) |
| `quant-bot` | クオンツ売買ボット | 2026-07-08 | [開く](https://drive.google.com/drive/folders/1ce9O3qwv1wHJz09Wf2xbQ_Uvaes3osdo) |
| `shorts-factory` | ショート動画自動生成（launchd 定期実行あり） | 2026-07-07 | [開く](https://drive.google.com/drive/folders/10uIoGL1G9TEV5J0QPACrXwlrn_tHo4Ew) |
| `codex` | Codex 用作業フォルダ | 2026-07-02 | [開く](https://drive.google.com/drive/folders/1xHKNdTJB3kIa45xwfpjKRjb4P4iE8QmW) |
| `blockcraft-lite` | ブラウザゲーム | 2026-06-26 | [開く](https://drive.google.com/drive/folders/19e9MRPuVnR32EvtuMVoVi-zI_nJEH4fP) |
| `multi-ai-sparring` | マルチAI比較検討 | 2026-06-25 | [開く](https://drive.google.com/drive/folders/1isLYYqkOoY9nMUDxNL4S3vnBNWBrvQbg) |
| `internal-tool-starter-kit` | 社内ツール雛形 | 2026-06-08 | [開く](https://drive.google.com/drive/folders/10brkkvCZfvMxGV3YPbQbGa7UwXU-NKnl) |
| `notebooklm-sync` | NotebookLM 連携 | 2026-06-06 | [開く](https://drive.google.com/drive/folders/1oWSNGL-7daxifxPn1lMZ9XEowPanaJk9) |
| `iphone-screenshot-share` | iPhone スクショ共有 | 2026-06-01 | [開く](https://drive.google.com/drive/folders/12eBAzGjwyEHAYJKwwN0yDKDlKfdqeYlA) |
| `sengoku-game` | 戦国ゲーム | 2026-05-31 | [開く](https://drive.google.com/drive/folders/1hiwjmc34eMTqzptEpbrDoz_YVK1uBH8d) |
| `voice-journal` | 音声日記 | 2026-05-31 | [開く](https://drive.google.com/drive/folders/16yXUgm4t88mKdK-AxgeDOJOzpU_CC0pL) |
| `voice-recorder` | 音声レコーダー | 2026-05-30 | [開く](https://drive.google.com/drive/folders/1Q0THHAMQIkLZ2rsoGOWE-tt7U5IEJKD-) |
| `weather-nagoya-app` | 名古屋天気アプリ | 2026-05-20 | [開く](https://drive.google.com/drive/folders/1cCLtrQ7tBRhKzagOtsWdSJH0CIJWV9Pt) |
| `sales-ops` | 営業オペレーション | 2026-04-19 | [開く](https://drive.google.com/drive/folders/1WR1pcs1TErQGvlgoOFxwLB7sy3p43biD) |
| `jp-daytrade` | 日本株デイトレード | 2026-04-15 | [開く](https://drive.google.com/drive/folders/1I7RB-_hxQcyQvTqtKMiLTm893ifjbBws) |
| `biz_idea_generator` | ビジネスアイデア生成 | 2026-04-13 | [開く](https://drive.google.com/drive/folders/1SDFnK8Dy8OPw7lBE4OvFvzv_Uj5QlORW) |
| `gourmet-share` | グルメ共有 | 2026-04-03 | [開く](https://drive.google.com/drive/folders/1O7vmhnzk8riwtRaeMiiVXZC-HSxOn3su) |
| `ai-news-system` | AIニュース収集 | 2026-04-01 | [開く](https://drive.google.com/drive/folders/1uwb-HKCXrsOsruH1vUX1TE8VBVmm4vWV) |
| `keiba-unified` | 競馬統合システム（JRA / WIN5。データは Git 管理外） | 2026-03-28 | [開く](https://drive.google.com/drive/folders/1vGJ2c2Lh19iToi14-SmuVsfvzfDHEfBM) |
| `ebooks` | 電子書籍成果物 | 2026-03-24 | [開く](https://drive.google.com/drive/folders/1C50v0YYuaq7XHGLQdbwVYZlDiHa7GwO1) |
| `yn-tools` | YN ツール群 | 2026-03-18 | [開く](https://drive.google.com/drive/folders/1XprxRluqKYWErDFAZnICw1NsMVSjeWpQ) |
| `ai-trade-system` | AIトレードシステム | 2026-03-18 | [開く](https://drive.google.com/drive/folders/1Z3UCxiwzOCWcbnl6Sje4CrILV5e5B7ef) |
| `ebook-produce` | 電子書籍プロデュース | 2026-03-14 | [開く](https://drive.google.com/drive/folders/1STFiLzVeOjXpL8k84FkiQb9t554C5eER) |
| `comicle-pipeline` | Comicle 漫画CSVパイプライン | 2026-03-11 | [開く](https://drive.google.com/drive/folders/13HiIEZwasj9cUKZNSVkNbY7zZHh2gA5W) |

## 設定・運用フォルダ（ドットフォルダ等）

| フォルダ | 役割 | Drive |
|---|---|---|
| `.company` | 会社運営（秘書 HANDOFF.md・TODO 履歴・sync_drive_git.py 等） | [開く](https://drive.google.com/drive/folders/16-A31yg5aDDgRYpUcju2UMJiMjtA8Dxn) |
| `.claude` | Claude Code 設定・スキル | [開く](https://drive.google.com/drive/folders/1RCE1h7s8b0u-uURfSA5UjqPK9voEqBjS) |
| `.codex` | Codex 設定 | [開く](https://drive.google.com/drive/folders/1OhciN0P5MAElyMUceSTNGTWSFofy9smk) |
| `.agents` | エージェント定義・skills（company スキル等） | [開く](https://drive.google.com/drive/folders/1kKYlanCHpKQPh1HwIE0Ob6dbpQkjhwOK) |
| `.vscode` | VS Code 設定 | [開く](https://drive.google.com/drive/folders/1pQQTA9ODI7cr5M8m-G8z8pi7M7Y71UZl) |
| `.wrangler` | Cloudflare Wrangler | [開く](https://drive.google.com/drive/folders/1ei3xPZOMLPNJQ3NF8cCM4imPWCzJ6Rlt) |
| `_scripts` | 補助スクリプト | [開く](https://drive.google.com/drive/folders/18Vp_qtCxfsz09BXX3P07_4MDBSGB8dQJ) |
| `_archive` | ルート整理アーカイブ（2026-07-05 整理で退避した旧ファイル） | [開く](https://drive.google.com/drive/folders/1xO8CjtXTrlVYu1aIaz_qSLQ1WPZo3fAZ) |
| `.playwright-mcp` / `.pytest_cache` / `test-results` | デバッグ・キャッシュ類（Git 管理外扱い） | — |

## ルート直下の主なファイル

| ファイル | 内容 | 状態 |
|---|---|---|
| `CLAUDE.md` | ワークスペース全体ルール（品質ループ・マルチPC方針） | 本ディレクトリにコピー済み |
| `AGENTS.md` | Codex 向け全体ルール（CLAUDE.md + 画像生成ルール） | 本ディレクトリにコピー済み |
| `.gitignore` | Drive 同期・大容量バイナリ除外ルール | `gitignore` としてコピー済み |
| `skills-bundle-20260726.zip` | スキル一式バンドル（1.6MB、2026-07-26） | [Drive で開く](https://drive.google.com/file/d/1UPj21nd10qI7NYmjYllAMZUdn79MREiU/view) |
| `.git.disabled-20260615` | Drive 側 git 無効化マーカー | Drive のみ |
| 各種スクリーンショット PNG | LP・アプリ確認用キャプチャ | Drive のみ（画像は Git 管理外方針） |
