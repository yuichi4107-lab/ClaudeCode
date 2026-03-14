# OpenClaw + MCP エージェントチーム構成書

## 概要

Claude Code を中心に、MCP（Model Context Protocol）で各種ツール・AIモデルを接続し、
OpenClaw で自動運用する事業管理システム。

---

## 1. エージェント構成

| ID | 役割 | モデル | 担当 |
|---|---|---|---|
| `orchestrator` | 司令塔・タスク振り分け・進捗管理 | Claude Sonnet 4.6 | 事業全体の意思決定 |
| `coder` | コード生成・修正・レビュー | OpenAI Codex | 開発タスク |
| `analyst` | データ分析・ROI評価・レポート | Claude Haiku 4.5 | 定型分析 |
| `scraper` | Webスクレイピング実行 | DeepSeek V3.2 | データ収集 |
| `creative` | 画像生成・画像分析・レポート画像化 | Gemini 2.5 Pro | ビジュアル系タスク |

### モデル選定の原則

- **Opus は使わない** — コスト5倍。司令塔でも Sonnet で十分
- **タスク特化モデル優先** — Codex(コード)、Gemini(画像)は汎用より安くて高品質
- **定型作業は最安モデル** — DeepSeek でトークン単価 1/10 以下

---

## 2. MCP 接続マップ

### 事業管理系

```
github     → Issue/PR 管理、コード管理
notion     → 事業ドキュメント・KPI管理
calendar   → スケジュール管理
slack/LINE → 通知・レポート配信
```

### 開発系

```
claude-code → Claude Code をサブエージェントとして利用
filesystem  → ローカルファイル読み書き
sqlite      → nankan.db 等のDB操作
```

### データ収集系

```
puppeteer → ブラウザ操作（スクレイピング）
```

---

## 3. openclaw.json 設定例

```jsonc
{
  "mcp": {
    "servers": {
      "github": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" }
      },
      "notion": {
        "command": "npx",
        "args": ["-y", "@notionhq/mcp-server"],
        "env": { "NOTION_API_KEY": "${NOTION_API_KEY}" }
      },
      "google-calendar": {
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-google-calendar"]
      },
      "claude-code": {
        "command": "claude",
        "args": ["mcp", "serve"]
      },
      "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]
      },
      "sqlite": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-sqlite", "./data/nankan.db"]
      },
      "slack": {
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-slack"],
        "env": { "SLACK_BOT_TOKEN": "${SLACK_BOT_TOKEN}" }
      },
      "puppeteer": {
        "command": "npx",
        "args": ["-y", "@anthropic/mcp-puppeteer"]
      }
    }
  },
  "agents": {
    "list": [
      {
        "id": "orchestrator",
        "model": "anthropic/claude-sonnet-4-6",
        "tools": ["github", "notion", "google-calendar", "slack"]
      },
      {
        "id": "coder",
        "model": "openai-codex/gpt-5.3-codex",
        "tools": ["claude-code", "filesystem", "github"]
      },
      {
        "id": "analyst",
        "model": "anthropic/claude-haiku-4-5",
        "tools": ["sqlite", "filesystem", "notion"]
      },
      {
        "id": "scraper",
        "model": "deepseek/deepseek-v3.2",
        "tools": ["puppeteer", "sqlite", "filesystem"]
      },
      {
        "id": "creative",
        "model": "google/gemini-2.5-pro",
        "tools": ["filesystem", "slack"]
      }
    ]
  }
}
```

---

## 4. 日次自動運用フロー（Heartbeat）

```
06:00  scraper      netkeiba.com から当日出馬表取得
06:30  analyst      特徴量生成 → モデル推論 → 予想ランキング
07:00  creative     Gemini で予想レポートを画像付きに変換
07:15  orchestrator Slack/LINE に配信
21:00  scraper      レース結果・払戻金を取得
21:30  analyst      的中率・ROI 集計 → Notion に記録
```

---

## 5. 開発サイクル（Issue 駆動）

```
GitHub Issue 作成
  → orchestrator が GitHub MCP で検知
  → coder (Codex) にコード実装を依頼
  → claude-code MCP でファイル編集・テスト実行
  → orchestrator が PR 作成・レビュー依頼
```

---

## 6. コスト見積もり

| エージェント | 月額目安 |
|---|---|
| orchestrator (Sonnet) | $5-15 |
| coder (Codex) | $3-10 |
| analyst (Haiku) | $1-3 |
| scraper (DeepSeek) | $0.5-1 |
| creative (Gemini) | $2-5 |
| **合計** | **$11.5-34** |

---

## 7. 構築手順

1. OpenClaw インストール・基本設定
2. MCP サーバー接続（GitHub, Filesystem, SQLite から開始）
3. orchestrator + scraper の2体でまず稼働
4. Heartbeat で日次自動運用を設定
5. coder, analyst, creative を順次追加
6. 本番運用・チューニング

---

## 8. このプロジェクトとの関係

本リポジトリ（nankan_predictor）は以下のエージェントが担当:

- **scraper** → `nankan scrape` コマンドを実行
- **analyst** → `nankan train` / `nankan evaluate` を実行
- **orchestrator** → `nankan predict` の結果を Slack に配信
- **coder** → 機能追加・バグ修正の PR を作成
