# X投稿くん (X-skill)

Claude（AI）に話しかけるだけで、note記事からX（旧Twitter）・Threads の投稿文を自動生成し、スプレッドシートに予約登録・自動投稿まで行うツールです。

**バージョン: 2.0.0**

---

## YNFactory版: Codex Pro運用

この配布版には、ChatGPT Proプラン内のCodexで投稿文生成を行う運用を追加しています。
OpenAI APIやClaude APIは使いません。

YNFactoryで使う場合は、このCodex Pro運用を優先してください。
以降に残っているClaude / Klavisの記述は、元の配布版に含まれていた旧運用説明です。

流れ:

```text
note記事を公開
  ↓
GASがnote RSSで新着公開記事を検知
  ↓
note公開検知シートに pending_codex として記録
  ↓
Codexが投稿文を生成
  ↓
CodexがX投稿シートへ予約投入
  ↓
GASがX/Threadsへ自動投稿
```

詳細手順:

- [`docs/codex-pro-workflow.md`](./docs/codex-pro-workflow.md)
- [`skills/gas-x-post/NOTE_RSS_BRIDGE_SETUP.md`](./skills/gas-x-post/NOTE_RSS_BRIDGE_SETUP.md)
- [`skills/gas-x-post/CODEX_PENDING_PROCESS_PROMPT.md`](./skills/gas-x-post/CODEX_PENDING_PROCESS_PROMPT.md)

Codex Pro運用では、Klavis MCPの設定は必須ではありません。

---

## このツールでできること

1. note記事のURLを渡すと、ナレッジに基づいてX投稿文を自動生成
2. 生成した投稿文をGoogleスプレッドシートに予約登録
3. Google Apps Script（GAS）が指定時刻に自動でX / Threads へ投稿

```
あなた：「この記事からX投稿を3本作成して、明日の朝・昼・夜に予約してください」
         https://note.com/あなた/n/記事ID

Claude：投稿文を生成 → スプレッドシートに書き込み → GASが自動投稿
```

---

## 必要なもの（前提条件）

| 必要なもの | 用途 | 費用 |
|---|---|---|
| [Claude Code](https://claude.ai/code) または Cursor | AIとのチャット・自動操作 | $20/月〜 |
| Google アカウント | スプレッドシート・GAS | 無料 |
| [Klavis](https://klavis.ai) アカウント | ClaudeがシートをMCP経由で操作 | 無料プランあり |
| X Developer アカウント | X API（自動投稿） | 従量課金（投稿1件あたり数円程度） |
| Threads アカウント | Threads API（任意） | 無料 |

> **Claudeを使ったことがない方** → まず [Claude Code の使い方](https://docs.anthropic.com/ja/docs/claude-code/overview) を確認してください。

---

## セットアップ（初回）

初回は以下の順番でセットアップしてください。**途中でわからなくなったら、Claudeに「セットアップを手伝ってください」と話しかければ対話形式でガイドしてもらえます。**

---

### Step 1: Klavis に登録してMCPを追加する

ClaudeがGoogleスプレッドシートを自動操作するために必要です。

#### 1-1. Klavisに登録してStrategyを作成

1. [klavis.ai](https://klavis.ai) にアクセスしてアカウントを作成
2. ダッシュボードで **「Create Strata」** をクリック
3. 連携するサービスに **「Google Sheets」** を追加
4. Google アカウントで認証（OAuth）
5. 作成された **Strata ID**（`xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx` 形式）をコピーして保存

#### 1-2. Claude Code に Klavis MCP を追加

ターミナルで以下を実行（`YOUR_STRATA_ID` を Step 1-1 でコピーしたIDに置き換え）：

```bash
claude mcp add --transport sse klavis "https://strata.klavis.ai/mcp/?strata_id=YOUR_STRATA_ID"
```

追加できたか確認：
```bash
claude mcp list
# → klavis が表示されればOK
```

> **Cursor の場合**: Settings → MCP → Add Server から上記URLを追加してください。

---

### Step 2: スプレッドシートを作成してGASを設定する

詳細手順: [`skills/gas-x-post/SETUP.md`](./skills/gas-x-post/SETUP.md)

#### 概要

1. [Google スプレッドシート](https://sheets.google.com) で新規スプレッドシートを作成
2. 「拡張機能」→「Apps Script」を開く
3. [`skills/gas-x-post/Code.gs`](./skills/gas-x-post/Code.gs) の内容を全てコピー＆ペーストして保存
4. `setupSpreadsheet` 関数を実行 → シート・ヘッダー・サンプルデータが自動作成される
5. スクリプトプロパティにAPIキーを設定（Step 3・4 で取得）
6. `setupTrigger` 関数を実行 → 30分ごとの自動投稿が開始

---

### Step 3: X API キーを取得する

> ⚠️ **ここがいちばん難所です。** 画面の遷移が分かりにくく、設定を1つでも間違えると投稿できません。
> **詳細な手順とつまずきポイントは [`docs/SETUP.md`](./docs/SETUP.md) を必ず参照してください。**

#### 公式ドキュメント（一次情報）

- [X Developer Platform 公式トップ](https://developer.x.com)
- [X API ドキュメント (Getting Started)](https://docs.x.com/x-api/getting-started/getting-access)
- [X API Pricing（料金プラン）](https://docs.x.com/x-api/getting-started/about-x-api#pricing)
- [User Authentication 設定ガイド](https://docs.x.com/resources/fundamentals/authentication/oauth-1-0a/api-key-and-secret)

#### 概要（5つのキーを取得します）

1. [developer.x.com](https://developer.x.com) にXアカウントでログイン
2. **有料プラン（Basic以上 / または Pay Per Use）** に登録
   - ※ 2026年現在 Free プランでは投稿APIが使えません
   - Basicプラン: $200/月（月3,000投稿まで）
   - Pay Per Use: 従量課金（投稿1件あたり数円程度）
3. プロジェクト・アプリを作成
4. **App Permissions を「Read and Write」に変更**（デフォルトは Read のみ → 必ず変更）
5. Access Token を **再生成**（Permission変更後は必須）
6. 以下の5つのキーを保存:
   - API Key / API Key Secret / Bearer Token / Access Token / Access Token Secret

取得したキーを GAS スクリプトプロパティに設定：

| プロパティ名 | 内容 |
|---|---|
| `X_API_KEY` | API キー |
| `X_API_SECRET` | API シークレット |
| `X_ACCESS_TOKEN` | アクセストークン |
| `X_ACCESS_TOKEN_SECRET` | アクセストークンシークレット |

---

### Step 4: Threads API トークンを取得する（任意）

Threads に投稿しない場合はスキップしてください。

1. [Meta for Developers](https://developers.facebook.com) でアプリを作成
2. Threads API の権限を追加・審査申請
3. アクセストークンを取得

取得したトークンを GAS スクリプトプロパティに設定：

| プロパティ名 | 内容 |
|---|---|
| `THREADS_ACCESS_TOKEN` | アクセストークン |
| `THREADS_USER_ID` | 空欄でOK（初回実行時に自動取得） |

---

### ✅ セットアップ完了チェックリスト

```
□ Klavis アカウントを作成・Strata を作成・Google Sheets を接続した
□ Claude Code / Cursor に Klavis MCP を追加した（claude mcp list で確認）
□ Google スプレッドシートを作成した
□ Code.gs を GAS に貼り付けた
□ setupSpreadsheet() を実行してシートを初期化した
□ X API キーを GAS スクリプトプロパティに設定した
□ setupTrigger() を実行してトリガーを登録した
□ dryRun() で動作確認した
```

---

## 使い方

セットアップ完了後は、Claude / Cursor に話しかけるだけです。

### 基本的な使い方

```
「この記事からX投稿を3本作成して、明日の7時・12時・19時に予約してください」
https://note.com/あなたのユーザー名/n/記事のID
```

Claude が自動で：
1. 記事を取得・分析
2. ナレッジに従って投稿文を生成（フック・文体・AI臭除去まで）
3. Klavis MCP 経由でスプレッドシートに書き込み
4. GAS が指定時刻に自動投稿

### 活用例

```
「今週投稿する内容をまとめてスプレッドシートに入れておいて」
「この記事から5本バリエーションを作って、来週分として登録して」
「明日の朝7時の投稿を確認して内容を修正して」
```

---

## セットアップを途中で始めた場合（対話ガイド）

セットアップを完了せずに「この記事のX投稿を作って」と依頼した場合、Claude が不足している設定を検出して対話形式でガイドします。

### Claude が確認すること

```
Claude：「Klavis MCP が接続されていません。以下を確認させてください。
         1. klavis.ai でアカウントを作成しましたか？
         2. Strata ID をお持ちですか？
         → あればターミナルで以下を実行してください：
         claude mcp add --transport sse klavis "https://strata.klavis.ai/mcp/?strata_id=あなたのID"」
```

```
Claude：「X API キーが GAS に設定されていません。
         → GAS エディタ → プロジェクトの設定 → スクリプトプロパティ
         で X_API_KEY / X_API_SECRET / X_ACCESS_TOKEN / X_ACCESS_TOKEN_SECRET を設定してください。
         取得方法は docs/SETUP.md を参照してください。」
```

### 途中から始める場合の推奨フロー

```
あなた：「X投稿を作りたいです」

Claude：「まずセットアップ状況を確認します。
         以下のうち、完了しているものを教えてください：
         1. Klavis の Strata ID を取得している
         2. Claude Code に Klavis MCP を追加している
         3. Google スプレッドシートに Code.gs を設定している
         4. X API キーを GAS に設定している」

あなた：「1と2だけできています」

Claude：「では Step 2（スプレッドシートの設定）から始めましょう。
         skills/gas-x-post/SETUP.md の手順に沿って進めます。
         [Googleスプレッドシート](https://sheets.google.com) を開いてください。」
```

> **ポイント：** 完全なセットアップが終わっていなくても投稿文の生成だけはできます。スプレッドシートへの書き込みが必要な場合のみ Klavis MCP が必要です。

---

## アーキテクチャ

```
あなた（note記事URL + 依頼）
        ↓
Claude（X投稿くん）
  ├─ 記事取得（WebFetch）
  ├─ 投稿文生成（ナレッジ適用）
  └─ スプレッドシート書き込み（Klavis MCP）
        ↓
Googleスプレッドシート（投稿データ管理）
        ↓
Google Apps Script（30分ごとに自動チェック）
        ↓
X API v2 / Threads API（自動投稿）
```

---

## スプレッドシート列構成

| 列 | 内容 | 入力者 |
|---|---|---|
| A | 投稿日（例: 2026/4/1） | Claude / 手動 |
| B | 時（0〜23） | Claude / 手動 |
| C | 分（0〜59） | Claude / 手動 |
| D | 投稿内容（本文） | Claude / 手動 |
| E | X投稿する（TRUE/FALSE） | Claude / 手動 |
| F | Threads投稿する（TRUE/FALSE） | Claude / 手動 |
| G〜J | 画像URL（任意） | Claude / 手動 |
| K | 投稿済み | GAS が自動更新 |
| L | X投稿URL | GAS が自動記入 |
| M | Threads投稿URL | GAS が自動記入 |

---

## ファイル構成

```
X投稿くん/
├── skills/
│   ├── x-post-writer/          # 投稿文生成スキル（メイン）
│   │   ├── SKILL.md            # ワークフロー定義・運用ルール
│   │   └── knowledge/          # 投稿品質向上ナレッジ（12ファイル）
│   ├── gas-x-post/             # GAS自動投稿スクリプト
│   │   ├── Code.gs             # GASスクリプト本体
│   │   ├── NoteRssBridge.gs    # note RSS検知 -> Codex処理待ち登録
│   │   ├── SETUP.md            # GASセットアップ詳細手順
│   │   ├── NOTE_RSS_BRIDGE_SETUP.md
│   │   └── CODEX_PENDING_PROCESS_PROMPT.md
│   └── note-to-x/              # note記事→X投稿変換スクリプト（補助）
├── docs/
│   ├── SETUP.md                # X APIキー取得手順
│   ├── codex-pro-workflow.md   # YNFactory版 Codex Pro運用手順
│   ├── sheet-template-X投稿.csv
│   ├── sheet-template-note公開検知.csv
│   └── GITHUB_ACTIONS_SETUP.md # GitHub Actions設定（v1バックアップ）
├── .github/
│   └── workflows/
│       └── auto-post.yml       # GitHub Actions（バックアップ・通常は不使用）
├── .gitignore
├── LICENSE
└── README.md                   # このファイル
```

---

## 別環境（Mac・別PC）への引き継ぎ

このフォルダ一式を新しいPCにコピーすればコードは引き継げます。

以下は環境ごとに別途再設定が必要です：

| 項目 | 保存場所 | 引き継ぎ方法 |
|---|---|---|
| X / Threads APIキー | GAS スクリプトプロパティ | スプレッドシートはGoogle上にあるため自動引き継ぎ |
| Klavis MCP | Claude Code / Cursor の設定 | 新しい環境で `claude mcp add` を再実行 |

**再実行コマンド（Strata IDは変わらない）：**
```bash
claude mcp add --transport sse klavis "https://strata.klavis.ai/mcp/?strata_id=あなたのSTRATA_ID"
```

> スプレッドシート・GAS はGoogle上にあるため、スプレッドシートのURLさえわかれば引き継ぎ不要です。

---

## よくある質問

**Q: 投稿が自動で送信されない**
→ GAS のトリガーが設定されているか確認（`setupTrigger` を再実行）。投稿日時が現在より過去になっているかも確認。

**Q: ClaudeがシートにAI書き込みができない**
→ `claude mcp list` で klavis が表示されているか確認。表示されていなければ Step 1-2 をやり直す。

**Q: X投稿で403エラーが出る**
→ X Developer Portal で App Permissions が「Read and Write」になっているか確認。Readのままだと投稿できない。Access Token を再生成する必要がある。

**Q: Threads 投稿URLが「URL取得失敗」になる**
→ 投稿自体は成功しています。Threads API の仕様でURLの取得に失敗することがあります。

---

## ライセンス

Copyright (c) 2025 株式会社デジイナ

使用・改変・商用利用（社内利用の範囲内）は自由です。
ただし、ソースコードおよびその改変版の再配布は禁止します。
詳細は [LICENSE](./LICENSE) を参照してください。
